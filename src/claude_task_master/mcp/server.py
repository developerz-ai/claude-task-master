"""MCP Server implementation for Claude Task Master.

This module implements an MCP server that exposes claudetm functionality
as tools that other Claude instances can use, enabling remote task orchestration.

Security Note:
    The MCP server defaults to stdio transport which is inherently secure.
    When using network transports (sse, streamable-http), the server binds
    to localhost (127.0.0.1) by default for security.

    Password authentication can be enabled for network transports by setting
    the CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH environment variable.
    When enabled, clients must provide the password as a Bearer token in the
    Authorization header.

Forwarding-tool specs live in :mod:`.server_specs`.
Runner and CLI entry-point live in :mod:`.server_runner`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_task_master.core.services import RepoService
from claude_task_master.mcp import tools

from .server_runner import (
    MCP_HOST,  # noqa: F401 — re-exported for callers and CLI defaults
    MCP_PORT,  # noqa: F401 — re-exported for callers and CLI defaults
    TransportType,  # noqa: F401 — re-exported for callers
    _get_authenticated_app,  # noqa: F401 — re-exported so server.py callers still work
    main,  # noqa: F401 — re-exported for the claudetm-mcp-server entry point
    run_server,  # noqa: F401 — re-exported for callers
)
from .server_specs import (
    _FORWARDING_SPECS,
    CleanResult,  # noqa: F401
    ClearMailboxResult,  # noqa: F401
    CloneRepoResult,  # noqa: F401
    DeleteCodingStyleResult,  # noqa: F401
    HealthCheckResult,  # noqa: F401
    LogsResult,  # noqa: F401
    MailboxStatusResult,  # noqa: F401
    PauseTaskResult,  # noqa: F401
    PlanRepoResult,  # noqa: F401
    ResumeTaskResult,  # noqa: F401
    SendMessageResult,  # noqa: F401
    SetupRepoResult,  # noqa: F401
    StartTaskResult,  # noqa: F401
    StopTaskResult,  # noqa: F401
    TaskStatus,  # noqa: F401
    UpdateConfigResult,  # noqa: F401
)

if TYPE_CHECKING:
    pass

# Import MCP SDK - using try/except for graceful degradation
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[misc, assignment]

# Import auth utilities - optional, only needed for network transports
try:
    from claude_task_master.auth import is_auth_enabled  # noqa: F401

    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False

logger = logging.getLogger(__name__)

# Stateless service centralising repo path-confinement and thread-offloading,
# shared with the REST transport.
_repo_service = RepoService()

_MCP_HOST = os.getenv("CLAUDETM_MCP_HOST", "127.0.0.1")
_MCP_PORT = int(os.getenv("CLAUDETM_MCP_PORT", "8080"))


# =============================================================================
# MCP Server Factory
# =============================================================================


def create_server(
    name: str = "claude-task-master",
    working_dir: str | None = None,
) -> FastMCP:
    """Create and configure the MCP server with all tools.

    Args:
        name: Server name for identification.
        working_dir: Working directory for task execution. Defaults to cwd.

    Returns:
        Configured FastMCP server instance.

    Raises:
        ImportError: If MCP SDK is not installed.
    """
    import time

    if FastMCP is None:
        raise ImportError("MCP SDK not installed. Install with: pip install mcp")

    # Create the server
    mcp = FastMCP(name)

    # Store working directory in server context
    work_dir = Path(working_dir) if working_dir else Path.cwd()

    # Track server start time for uptime
    start_time = time.time()

    # =============================================================================
    # Tool Wrappers - Delegate to tools module
    # =============================================================================

    # The task and mailbox tools are generated from the declarative
    # _FORWARDING_SPECS table so their parameters are derived from the
    # underlying tools functions and can never silently drift.
    from claude_task_master.mcp.tool_forwarding import register_forwarding_tools  # noqa: PLC0415

    register_forwarding_tools(mcp, _FORWARDING_SPECS, work_dir=work_dir)

    @mcp.tool()
    def health_check() -> dict[str, Any]:
        """Health check endpoint for the MCP server.

        Returns server health information including status, version,
        server name, uptime, and number of active tasks.

        Returns:
            Dictionary containing health status information.
        """
        return tools.health_check(work_dir, name, start_time)

    # =============================================================================
    # Repo Setup Tool Wrappers
    # =============================================================================

    @mcp.tool()
    async def clone_repo(
        url: str,
        target_dir: str | None = None,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Clone a git repository to the workspace.

        Clones the repository to ~/workspace/claude-task-master/{project-name}
        by default, or to a custom target directory if specified. This is the
        first step in setting up a new development environment for AI developers.

        Args:
            url: Git repository URL (HTTPS or SSH format).
                Examples: https://github.com/user/repo.git or git@github.com:user/repo.git
            target_dir: Optional custom target directory path. If not provided,
                defaults to ~/workspace/claude-task-master/{repo-name}.
            branch: Optional branch to checkout after cloning.

        Returns:
            Dictionary containing:
            - success: Whether clone was successful
            - message: Human-readable result message
            - repo_url: The cloned repository URL
            - target_dir: The directory where repo was cloned
            - branch: The branch checked out (if specified)
            - error: Error details on failure

        Example:
            clone_repo("https://github.com/anthropics/claude-code")
            clone_repo("git@github.com:user/project.git", branch="develop")
            clone_repo("https://github.com/user/project", target_dir="/custom/path")
        """
        # RepoService offloads the blocking subprocess work to a thread so the
        # MCP event loop is never frozen during a (potentially minutes-long)
        # clone; ``data`` is the underlying tool dict, forwarded verbatim.
        return (await _repo_service.clone(url, target_dir, branch)).data

    @mcp.tool()
    async def setup_repo(
        work_dir: str,
        run_setup_scripts: bool = False,
    ) -> dict[str, Any]:
        """Set up a cloned repository for development.

        Detects the project type and performs appropriate setup:
        - Creates virtual environment (for Python projects)
        - Installs dependencies (pip, npm, pnpm, yarn, bun)
        - Runs setup scripts (setup-hooks.sh, setup.sh, etc.) only when opted in

        Supports Python projects (pyproject.toml, setup.py, requirements.txt)
        and Node.js projects (package.json). Uses uv for Python dependency
        management when available, falling back to standard venv + pip.

        Args:
            work_dir: Path to the cloned repository directory to set up.
            run_setup_scripts: Execute repo-supplied setup scripts. Disabled by
                default because running untrusted scripts is a remote-code-execution
                risk; scripts are detected but skipped unless this is True.

        Returns:
            Dictionary containing:
            - success: Whether setup completed successfully
            - message: Human-readable result message
            - work_dir: The directory that was set up
            - steps_completed: List of completed setup steps
            - venv_path: Path to virtual environment (Python projects)
            - dependencies_installed: Whether dependencies were installed
            - setup_scripts_run: List of setup scripts that were executed
            - error: Error details on failure

        Example:
            setup_repo("/home/user/workspace/claude-task-master/my-project")
            setup_repo("~/workspace/claude-task-master/python-app")
        """
        # RepoService offloads the blocking subprocess work to a thread so the
        # MCP event loop is never frozen during dependency installation / setup
        # scripts; ``data`` is the underlying tool dict, forwarded verbatim.
        return (await _repo_service.setup(work_dir, run_setup_scripts=run_setup_scripts)).data

    @mcp.tool()
    async def plan_repo(
        work_dir: str,
        goal: str,
        model: str = "opus",
    ) -> dict[str, Any]:
        """Create a plan for a repository without executing any work.

        This is a plan-only mode that reads the codebase using read-only tools
        (Read, Glob, Grep) and outputs a structured plan with tasks and success
        criteria. No changes are made to the repository.

        Use this after `clone_repo` and `setup_repo` to plan work before execution,
        or to get a plan for a new goal in an existing repository.

        Args:
            work_dir: Path to the repository directory to plan for.
            goal: The goal/task description to plan for. Be specific about
                what you want to accomplish.
            model: Model to use for planning (default: "opus" for best quality).
                Options: "opus", "sonnet", "fable", "haiku", "sonnet_1m".

        Returns:
            Dictionary containing:
            - success: Whether planning completed successfully
            - message: Human-readable result message
            - work_dir: The directory that was planned for
            - goal: The goal that was planned for
            - plan: The generated task plan (markdown with checkboxes)
            - criteria: Success criteria for verifying completion
            - run_id: Unique identifier for this planning session
            - error: Error details on failure

        Example:
            plan_repo("/home/user/workspace/project", "Add user authentication")
            plan_repo("~/workspace/my-app", "Fix the login bug", model="sonnet")
        """
        # RepoService offloads to a thread: keeps the MCP event loop responsive
        # and lets the agent's ``run_async_with_cleanup`` drive its own loop in a
        # thread that has none, avoiding the running-loop RuntimeError; ``data``
        # is the underlying tool dict, forwarded verbatim.
        return (await _repo_service.plan(work_dir, goal, model)).data

    # =============================================================================
    # Resource Wrappers
    # =============================================================================

    @mcp.resource("task://goal")
    def resource_goal() -> str:
        """Get the current task goal."""
        return tools.resource_goal(work_dir)

    @mcp.resource("task://plan")
    def resource_plan() -> str:
        """Get the current task plan."""
        return tools.resource_plan(work_dir)

    @mcp.resource("task://progress")
    def resource_progress() -> str:
        """Get the current progress summary."""
        return tools.resource_progress(work_dir)

    @mcp.resource("task://context")
    def resource_context() -> str:
        """Get accumulated context and learnings."""
        return tools.resource_context(work_dir)

    return mcp


if __name__ == "__main__":
    main()
