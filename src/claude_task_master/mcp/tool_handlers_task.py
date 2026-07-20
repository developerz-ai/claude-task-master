"""Task query and management tool handlers for MCP.

Covers: get_status, get_plan, get_logs, get_progress, get_context,
clean_task, initialize_task, list_tasks, health_check, and the four
resource helpers (resource_goal, resource_plan, resource_progress,
resource_context).

Control operations (pause/stop/resume/update_config) live in
:mod:`claude_task_master.mcp.tool_handlers_control`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_task_master.core.agent_models import validate_model
from claude_task_master.core.services import ServiceOutcome, TaskService
from claude_task_master.core.state import StateManager, TaskOptions
from claude_task_master.mcp.tool_models import (
    CleanResult,
    HealthCheckResult,
    LogsResult,
    StartTaskResult,
    TaskStatus,
)

# =============================================================================
# Internal helpers
# =============================================================================


def _state_path_for(work_dir: Path, state_dir: str | None) -> Path:
    """Resolve the state directory for a tool call.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional explicit state directory path.

    Returns:
        The state directory path: ``state_dir`` if given, else
        ``work_dir/.claude-task-master``.
    """
    return Path(state_dir) if state_dir else work_dir / ".claude-task-master"


def _task_service(work_dir: Path, state_dir: str | None) -> TaskService:
    """Build a :class:`TaskService` bound to the resolved state directory.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional explicit state directory path.

    Returns:
        A task service operating on the resolved state directory.
    """
    return TaskService(StateManager(state_dir=_state_path_for(work_dir, state_dir)))


# =============================================================================
# Query handlers
# =============================================================================


def get_status(
    work_dir: Path,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Get the current status of a claudetm task.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary containing task status information.
    """
    result = _task_service(work_dir, state_dir).get_status()

    if result.outcome is ServiceOutcome.NOT_FOUND:
        return {
            "success": False,
            "error": "No active task found",
            "suggestion": "Use start_task to begin a new task",
        }
    if not result.success:
        return {"success": False, "error": result.error}

    state = result.data["state"]
    return TaskStatus(
        goal=result.data["goal"],
        status=state.status,
        model=state.model,
        current_task_index=state.current_task_index,
        session_count=state.session_count,
        run_id=state.run_id,
        current_pr=state.current_pr,
        workflow_stage=state.workflow_stage,
        options=state.options.model_dump(),
    ).model_dump()


def get_plan(
    work_dir: Path,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Get the current task plan with checkboxes.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary containing the plan content or error.
    """
    result = _task_service(work_dir, state_dir).get_plan()

    if result.outcome is ServiceOutcome.NOT_FOUND:
        return {"success": False, "error": result.message or "No active task found"}
    if not result.success:
        return {"success": False, "error": result.error}

    return {"success": True, "plan": result.data["plan"]}


def get_logs(
    work_dir: Path,
    tail: int = 100,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Get logs from the current task run.

    Args:
        work_dir: Working directory for the server.
        tail: Number of lines to return from the end of the log (must be >= 1).
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary containing log content or error.
    """
    result = _task_service(work_dir, state_dir).get_logs(tail)

    if result.success:
        return LogsResult(
            success=True,
            log_content=result.data["log_content"],
            log_file=result.data["log_file"],
        ).model_dump()

    if result.outcome is ServiceOutcome.INVALID:
        return LogsResult(success=False, error=result.error).model_dump()
    if result.outcome is ServiceOutcome.NOT_FOUND:
        return LogsResult(
            success=False, error=result.message or "No active task found"
        ).model_dump()
    return LogsResult(success=False, error=result.error).model_dump()


def get_progress(
    work_dir: Path,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Get the human-readable progress summary.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary containing progress content or error.
    """
    result = _task_service(work_dir, state_dir).get_progress()

    if result.outcome is ServiceOutcome.NOT_FOUND:
        return {"success": False, "error": result.message or "No active task found"}
    if not result.success:
        return {"success": False, "error": result.error}

    if result.data["progress"] is None:
        return {"success": True, "progress": None, "message": result.message}
    return {"success": True, "progress": result.data["progress"]}


def get_context(
    work_dir: Path,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Get the accumulated context and learnings.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary containing context content or error.
    """
    result = _task_service(work_dir, state_dir).get_context()

    if result.outcome is ServiceOutcome.NOT_FOUND:
        return {"success": False, "error": result.message or "No active task found"}
    if not result.success:
        return {"success": False, "error": result.error}

    return {"success": True, "context": result.data["context"] or ""}


# =============================================================================
# Task lifecycle management
# =============================================================================


def clean_task(
    work_dir: Path,
    force: bool = False,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Clean up task state directory.

    Args:
        work_dir: Working directory for the server.
        force: If True, force cleanup even if session is active.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary indicating success or failure.
    """
    # Confine the cleanup target to work_dir: clean_task rmtree's the state
    # directory, so an unconstrained state_dir would allow arbitrary tree deletion.
    # This confinement is MCP-specific (relative to the server's work_dir), so it
    # stays here rather than in the transport-neutral service.
    if state_dir is not None:
        candidate = Path(state_dir).expanduser().resolve()
        work_base = Path(work_dir).expanduser().resolve()
        if not candidate.is_relative_to(work_base):
            return CleanResult(
                success=False,
                message=(
                    f"Refusing to clean '{candidate}': outside the working directory '{work_base}'."
                ),
                files_removed=False,
            ).model_dump()
        state_path = candidate
    else:
        state_path = work_dir / ".claude-task-master"

    result = TaskService(StateManager(state_dir=state_path)).clean(force=force)

    # MCP treats "nothing to clean" as a benign success.
    if result.outcome is ServiceOutcome.NOT_FOUND:
        return CleanResult(
            success=True,
            message="No task state found to clean",
            files_removed=False,
        ).model_dump()
    if result.outcome is ServiceOutcome.INVALID:
        return CleanResult(
            success=False,
            message=result.message,
            files_removed=False,
        ).model_dump()
    if not result.success:
        return CleanResult(
            success=False,
            message=f"Failed to clean task state: {result.error}",
        ).model_dump()

    if result.data["files_removed"]:
        return CleanResult(
            success=True,
            message="Task state cleaned successfully",
            files_removed=True,
        ).model_dump()
    return CleanResult(
        success=True,
        message="State directory did not exist",
        files_removed=False,
    ).model_dump()


def initialize_task(
    work_dir: Path,
    goal: str,
    model: str = "opus",
    auto_merge: bool = True,
    max_sessions: int | None = None,
    max_prs: int | None = None,
    pause_on_pr: bool = False,
    state_dir: str | None = None,
    *,
    enable_release: bool = False,
    enable_verification: bool = False,
) -> dict[str, Any]:
    """Initialize a new task with the given goal.

    Args:
        work_dir: Working directory for the server.
        goal: The goal to achieve.
        model: Model to use (opus, sonnet, haiku).
        auto_merge: Whether to auto-merge PRs when approved.
        max_sessions: Max work sessions before pausing.
        max_prs: Max pull requests to create.
        pause_on_pr: Pause after creating PR for manual review.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary indicating success with run_id or failure.
    """
    try:
        validate_model(model)
    except ValueError as e:
        return StartTaskResult(success=False, message=str(e)).model_dump()

    options = TaskOptions(
        auto_merge=auto_merge,
        enable_release=enable_release,
        enable_verification=enable_verification,
        max_sessions=max_sessions,
        max_prs=max_prs,
        pause_on_pr=pause_on_pr,
    )
    result = _task_service(work_dir, state_dir).init_task(goal, model, options)

    if result.outcome is ServiceOutcome.CONFLICT:
        return StartTaskResult(
            success=False,
            message="Task already exists. Use clean_task first or resume the existing task.",
        ).model_dump()
    if not result.success:
        return StartTaskResult(
            success=False,
            message=f"Failed to initialize task: {result.error}",
        ).model_dump()

    state = result.data["state"]
    return StartTaskResult(
        success=True,
        message=f"Task initialized successfully with goal: {goal}",
        run_id=state.run_id,
        status=state.status,
    ).model_dump()


def list_tasks(
    work_dir: Path,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """List tasks from the current plan.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary containing list of tasks with status.
    """
    result = _task_service(work_dir, state_dir).list_tasks()

    if result.outcome is ServiceOutcome.NOT_FOUND:
        return {"success": False, "error": result.message or "No active task found"}
    if not result.success:
        return {"success": False, "error": result.error}

    return {
        "success": True,
        "tasks": result.data["tasks"],
        "total": result.data["total"],
        "completed": result.data["completed"],
        "current_index": result.data["current_index"],
    }


def health_check(
    work_dir: Path,
    server_name: str = "claude-task-master",
    start_time: float | None = None,
) -> dict[str, Any]:
    """Perform a health check on the MCP server.

    Args:
        work_dir: Working directory for the server.
        server_name: Name of the MCP server.
        start_time: Server start time (timestamp) for uptime calculation.

    Returns:
        Dictionary containing health status information.
    """
    import time

    from claude_task_master import __version__

    # Calculate uptime if start_time provided
    uptime = None
    if start_time is not None:
        uptime = time.time() - start_time

    # Check for active tasks
    active_tasks = 0
    state_dir = work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_dir)
    if state_manager.exists():
        try:
            state_manager.load_state()
            active_tasks = 1
        except Exception:
            pass  # State exists but couldn't be loaded - treat as no active task

    return HealthCheckResult(
        status="healthy",
        version=__version__,
        server_name=server_name,
        uptime_seconds=uptime,
        active_tasks=active_tasks,
    ).model_dump()


# =============================================================================
# Resource implementations
# =============================================================================


def resource_goal(work_dir: Path) -> str:
    """Get the current task goal."""
    state_manager = StateManager(state_dir=work_dir / ".claude-task-master")
    if not state_manager.exists():
        return "No active task"
    try:
        return state_manager.load_goal()
    except Exception:
        return "Error loading goal"


def resource_plan(work_dir: Path) -> str:
    """Get the current task plan."""
    state_manager = StateManager(state_dir=work_dir / ".claude-task-master")
    if not state_manager.exists():
        return "No active task"
    try:
        plan = state_manager.load_plan()
        return plan or "No plan found"
    except Exception:
        return "Error loading plan"


def resource_progress(work_dir: Path) -> str:
    """Get the current progress summary."""
    state_manager = StateManager(state_dir=work_dir / ".claude-task-master")
    if not state_manager.exists():
        return "No active task"
    try:
        progress = state_manager.load_progress()
        return progress or "No progress recorded"
    except Exception:
        return "Error loading progress"


def resource_context(work_dir: Path) -> str:
    """Get accumulated context and learnings."""
    state_manager = StateManager(state_dir=work_dir / ".claude-task-master")
    if not state_manager.exists():
        return "No active task"
    try:
        return state_manager.load_context()
    except Exception:
        return "Error loading context"
