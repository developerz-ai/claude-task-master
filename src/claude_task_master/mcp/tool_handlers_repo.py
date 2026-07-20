"""Repository operation tool handlers for MCP: clone_repo and plan_repo.

``setup_repo`` lives in :mod:`claude_task_master.mcp.tool_handlers_setup`.

``DEFAULT_WORKSPACE_BASE`` and ``is_auth_enabled`` are defined in
:mod:`claude_task_master.mcp.tools` so tests can patch them there.  The
helpers below read those names through a deferred module lookup so every
call sees the current (possibly patched) value without a circular import.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from claude_task_master.mcp.tool_models import CloneRepoResult, PlanRepoResult

_REPO_AUTH_REQUIRED_MESSAGE = (
    "Repository operations are disabled because authentication is not configured. "
    "Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH to enable them."
)


# Deferred lookups — read patchable names from mcp.tools at call time so that
# ``monkeypatch.setattr(tools_mod, "DEFAULT_WORKSPACE_BASE", ...)`` is visible.
def _tools_ns() -> Any:
    import claude_task_master.mcp.tools as _t  # noqa: PLC0415

    return _t


def _workspace_base() -> Path:
    return _tools_ns().DEFAULT_WORKSPACE_BASE  # type: ignore[no-any-return]


def _is_auth_enabled() -> bool:
    return _tools_ns().is_auth_enabled()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Security / path helpers
# ---------------------------------------------------------------------------


class WorkspaceConfinementError(ValueError):
    """Raised when a user-supplied path resolves outside the workspace base."""


def _resolve_within_workspace(path: str | Path) -> Path:
    """Resolve *path* and ensure it stays within ``DEFAULT_WORKSPACE_BASE``.

    Expands ``~`` and resolves ``..``/symlinks, then verifies the result is the
    workspace base itself or a descendant. This blocks path-traversal escapes
    (e.g. ``target_dir="/etc"`` or ``"../../root"``) from the repo endpoints,
    which would otherwise allow arbitrary-filesystem writes.

    Args:
        path: The user-supplied filesystem path.

    Returns:
        The fully-resolved absolute path, guaranteed inside the workspace base.

    Raises:
        WorkspaceConfinementError: If the resolved path escapes the workspace base.
    """
    resolved = Path(path).expanduser().resolve()
    base = _workspace_base().expanduser().resolve()
    if not resolved.is_relative_to(base):
        raise WorkspaceConfinementError(
            f"Path '{resolved}' is outside the permitted workspace '{base}'. "
            "Repository paths must stay within the workspace base."
        )
    return resolved


def _extract_repo_name(url: str) -> str:
    """Extract repository name from a git URL.

    Supports both HTTPS and SSH URLs:
    - https://github.com/user/repo.git -> repo
    - git@github.com:user/repo.git -> repo
    - https://github.com/user/repo -> repo

    Args:
        url: Git repository URL.

    Returns:
        Repository name without .git suffix.
    """
    # Remove trailing .git if present
    clean_url = url.rstrip("/")
    if clean_url.endswith(".git"):
        clean_url = clean_url[:-4]

    # Extract repo name from path
    # For SSH: git@github.com:user/repo
    if ":" in clean_url and "@" in clean_url:
        repo_name = clean_url.split("/")[-1]
    else:
        # For HTTPS: https://github.com/user/repo
        repo_name = clean_url.split("/")[-1]

    return repo_name


# ---------------------------------------------------------------------------
# clone_repo
# ---------------------------------------------------------------------------


def clone_repo(
    url: str,
    target_dir: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Clone a git repository to the workspace.

    Clones the repository to ~/workspace/claude-task-master/{project-name}
    by default, or to a custom target directory if specified.

    Args:
        url: Git repository URL (HTTPS or SSH).
        target_dir: Optional custom target directory path. If not provided,
            defaults to ~/workspace/claude-task-master/{repo-name}.
        branch: Optional branch to checkout after cloning.

    Returns:
        Dictionary containing clone result with success status and details.
    """
    # Refuse when authentication is not configured: this endpoint writes to the
    # filesystem and must never be reachable unauthenticated.
    if not _is_auth_enabled():
        return CloneRepoResult(
            success=False,
            message=_REPO_AUTH_REQUIRED_MESSAGE,
            repo_url=url or None,
            error="authentication_required",
        ).model_dump()

    # Validate URL
    if not url or not url.strip():
        return CloneRepoResult(
            success=False,
            message="Repository URL is required",
            error="Repository URL cannot be empty",
        ).model_dump()

    url = url.strip()

    # Basic URL validation
    if not (
        url.startswith("https://")
        or url.startswith("git@")
        or url.startswith("git://")
        or url.startswith("ssh://")
    ):
        return CloneRepoResult(
            success=False,
            message="Invalid repository URL format",
            repo_url=url,
            error="URL must start with https://, git@, git://, or ssh://",
        ).model_dump()

    # Determine target directory (confined to the workspace base)
    repo_name = _extract_repo_name(url)
    if target_dir:
        try:
            target_path = _resolve_within_workspace(target_dir)
        except WorkspaceConfinementError as e:
            return CloneRepoResult(
                success=False,
                message=str(e),
                repo_url=url,
                target_dir=str(Path(target_dir).expanduser()),
                error="path_outside_workspace",
            ).model_dump()
    else:
        # Default to ~/workspace/claude-task-master/{repo-name}, confined like the
        # explicit target_dir branch: repo_name is derived from the URL, so a value
        # such as ".." must not resolve outside the workspace base.
        try:
            target_path = _resolve_within_workspace(_workspace_base() / repo_name)
        except WorkspaceConfinementError as e:
            return CloneRepoResult(
                success=False,
                message=str(e),
                repo_url=url,
                error="path_outside_workspace",
            ).model_dump()

    # Check if target already exists
    if target_path.exists():
        return CloneRepoResult(
            success=False,
            message=f"Target directory already exists: {target_path}",
            repo_url=url,
            target_dir=str(target_path),
            error="Target directory already exists. Remove it first or specify a different target.",
        ).model_dump()

    # Ensure parent directory exists
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        return CloneRepoResult(
            success=False,
            message=f"Permission denied creating parent directory: {target_path.parent}",
            repo_url=url,
            target_dir=str(target_path),
            error=str(e),
        ).model_dump()
    except OSError as e:
        return CloneRepoResult(
            success=False,
            message=f"Failed to create parent directory: {target_path.parent}",
            repo_url=url,
            target_dir=str(target_path),
            error=str(e),
        ).model_dump()

    # Build git clone command
    cmd = ["git", "clone"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([url, str(target_path)])

    # Execute git clone
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,  # 5 minute timeout for large repos
        )

        if result.returncode != 0:
            # Clean up partial clone if it exists
            if target_path.exists():
                shutil.rmtree(target_path, ignore_errors=True)

            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return CloneRepoResult(
                success=False,
                message=f"Git clone failed: {error_msg}",
                repo_url=url,
                target_dir=str(target_path),
                branch=branch,
                error=error_msg,
            ).model_dump()

        return CloneRepoResult(
            success=True,
            message=f"Successfully cloned {repo_name} to {target_path}",
            repo_url=url,
            target_dir=str(target_path),
            branch=branch,
        ).model_dump()

    except subprocess.TimeoutExpired:
        # Clean up partial clone
        if target_path.exists():
            shutil.rmtree(target_path, ignore_errors=True)

        return CloneRepoResult(
            success=False,
            message="Git clone timed out (5 minute limit exceeded)",
            repo_url=url,
            target_dir=str(target_path),
            branch=branch,
            error="Clone operation timed out - repository may be too large or network is slow",
        ).model_dump()

    except FileNotFoundError:
        return CloneRepoResult(
            success=False,
            message="Git is not installed or not in PATH",
            repo_url=url,
            target_dir=str(target_path),
            branch=branch,
            error="git command not found - please install git",
        ).model_dump()

    except Exception as e:
        # Clean up partial clone
        if target_path.exists():
            shutil.rmtree(target_path, ignore_errors=True)

        return CloneRepoResult(
            success=False,
            message=f"Clone failed: {e}",
            repo_url=url,
            target_dir=str(target_path),
            branch=branch,
            error=str(e),
        ).model_dump()


# ---------------------------------------------------------------------------
# plan_repo
# ---------------------------------------------------------------------------


def plan_repo(
    work_dir: str | Path,
    goal: str,
    model: str = "opus",
) -> dict[str, Any]:
    """Create a plan for a repository without executing any work.

    This is a plan-only mode that reads the codebase using read-only tools
    (Read, Glob, Grep, Bash) and outputs a structured plan with tasks and
    success criteria. No changes are made to the repository.

    Use this after ``clone_repo`` and ``setup_repo`` to plan work before
    execution, or to get a plan for a new goal in an existing repository.

    Args:
        work_dir: Path to the repository directory to plan for.
        goal: The goal/task description to plan for.
        model: Model to use for planning (default: "opus" for best quality).

    Returns:
        Dictionary containing planning result with success status, plan, and criteria.
    """
    from claude_task_master.core.agent_models import validate_model
    from claude_task_master.core.state import StateManager, TaskOptions

    # Refuse when authentication is not configured: this endpoint spawns an agent
    # and must never be reachable unauthenticated.
    if not _is_auth_enabled():
        return PlanRepoResult(
            success=False,
            message=_REPO_AUTH_REQUIRED_MESSAGE,
            work_dir=str(work_dir),
            goal=goal,
            error="authentication_required",
        ).model_dump()

    # Confine the work directory to the workspace base.
    try:
        work_path = _resolve_within_workspace(work_dir)
    except WorkspaceConfinementError as e:
        return PlanRepoResult(
            success=False,
            message=str(e),
            work_dir=str(Path(work_dir).expanduser()),
            goal=goal,
            error="path_outside_workspace",
        ).model_dump()

    # Validate work directory
    if not work_path.exists():
        return PlanRepoResult(
            success=False,
            message=f"Directory does not exist: {work_path}",
            work_dir=str(work_path),
            goal=goal,
            error="Work directory not found",
        ).model_dump()

    if not work_path.is_dir():
        return PlanRepoResult(
            success=False,
            message=f"Path is not a directory: {work_path}",
            work_dir=str(work_path),
            goal=goal,
            error="Path is not a directory",
        ).model_dump()

    # Validate goal
    if not goal or not goal.strip():
        return PlanRepoResult(
            success=False,
            message="Goal is required",
            work_dir=str(work_path),
            error="Goal cannot be empty",
        ).model_dump()

    goal = goal.strip()

    # Validate the model up front through the shared path so an unknown name
    # fails fast with a clear error instead of being silently coerced to Opus.
    try:
        model_type = validate_model(model)
    except ValueError as e:
        return PlanRepoResult(
            success=False,
            message=str(e),
            work_dir=str(work_path),
            goal=goal,
            error="invalid_model",
        ).model_dump()

    # Initialize state manager for this repo
    state_path = work_path / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)

    # Check if task already exists
    if state_manager.exists():
        # Load existing state to check if we can replan
        try:
            existing_state = state_manager.load_state()
            # If task is in progress, don't overwrite
            if existing_state.status in ("planning", "working"):
                return PlanRepoResult(
                    success=False,
                    message=f"Task already in progress (status: {existing_state.status})",
                    work_dir=str(work_path),
                    goal=goal,
                    run_id=existing_state.run_id,
                    error="Cannot create new plan while task is active. Use clean_task first.",
                ).model_dump()
        except Exception:
            pass  # State exists but couldn't be loaded - will be overwritten

    try:
        # Import credentials and agent here to avoid circular imports
        from claude_task_master.core.agent import AgentWrapper
        from claude_task_master.core.credentials import CredentialManager

        # Get valid access token
        cred_manager = CredentialManager()
        access_token = cred_manager.get_valid_token()

        # Initialize task state. The model was validated above; persist its
        # canonical identifier.
        options = TaskOptions(
            auto_merge=False,  # Plan-only mode
            max_sessions=1,
            pause_on_pr=True,
        )
        state = state_manager.initialize(goal=goal, model=model_type.value, options=options)

        # Update status to planning
        state.status = "planning"
        state_manager.save_state(state)

        # Create agent wrapper
        agent = AgentWrapper(
            access_token=access_token,
            model=model_type,
            working_dir=str(work_path),
        )

        # Route planning through the Planner so plan-only mode receives the same
        # inputs as `start`: a generated coding-style guide, the release guide
        # (only when release is enabled — it is not here), accumulated context,
        # and the max_prs constraint. Calling run_planning_phase(context="")
        # directly skipped all of these and produced a lower-quality plan.
        from claude_task_master.core.planner import Planner

        planner = Planner(agent=agent, state_manager=state_manager)
        result = planner.create_plan(goal=goal)

        # create_plan already persists plan.md / criteria.txt; read the values
        # back for the response payload.
        plan = result.get("plan", "")
        criteria = result.get("criteria", "")

        # Update state to paused (plan complete, ready for work)
        state.status = "paused"
        state_manager.save_state(state)

        return PlanRepoResult(
            success=True,
            message=f"Successfully created plan for: {goal}",
            work_dir=str(work_path),
            goal=goal,
            plan=plan,
            criteria=criteria,
            run_id=state.run_id,
        ).model_dump()

    except ImportError as e:
        return PlanRepoResult(
            success=False,
            message="Failed to import required modules",
            work_dir=str(work_path),
            goal=goal,
            error=f"Import error: {e}. Ensure claude-agent-sdk is installed.",
        ).model_dump()

    except Exception as e:
        # Try to update state to failed if possible
        try:
            if state_manager.exists():
                state = state_manager.load_state()
                state.status = "blocked"
                state_manager.save_state(state)
        except Exception:
            pass  # State update failed, continue with error return

        return PlanRepoResult(
            success=False,
            message=f"Planning failed: {e}",
            work_dir=str(work_path),
            goal=goal,
            error=str(e),
        ).model_dump()
