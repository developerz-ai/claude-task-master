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
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from claude_task_master.mcp import tools

if TYPE_CHECKING:
    from starlette.applications import Starlette

# Import MCP SDK - using try/except for graceful degradation
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[misc, assignment]

# Import auth utilities - optional, only needed for network transports
try:
    from claude_task_master.auth import is_auth_enabled
    from claude_task_master.mcp.auth import add_auth_middleware, check_auth_config

    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    is_auth_enabled = lambda: False  # noqa: E731
    add_auth_middleware = None  # type: ignore[assignment]
    check_auth_config = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Security: Default host for network transports
MCP_HOST = os.getenv("CLAUDETM_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("CLAUDETM_MCP_PORT", "8080"))

# =============================================================================
# Re-export response models for convenience
# =============================================================================

TaskStatus = tools.TaskStatus
StartTaskResult = tools.StartTaskResult
CleanResult = tools.CleanResult
LogsResult = tools.LogsResult
HealthCheckResult = tools.HealthCheckResult
PauseTaskResult = tools.PauseTaskResult
StopTaskResult = tools.StopTaskResult
ResumeTaskResult = tools.ResumeTaskResult
UpdateConfigResult = tools.UpdateConfigResult
SendMessageResult = tools.SendMessageResult
MailboxStatusResult = tools.MailboxStatusResult
ClearMailboxResult = tools.ClearMailboxResult
CloneRepoResult = tools.CloneRepoResult
SetupRepoResult = tools.SetupRepoResult
PlanRepoResult = tools.PlanRepoResult


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

    @mcp.tool()
    def get_status(state_dir: str | None = None) -> dict[str, Any]:
        """Get the current status of a claudetm task.

        Returns task goal, status, model, current task index, session count,
        and configuration options.

        Args:
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary containing task status information.
        """
        return tools.get_status(work_dir, state_dir)

    @mcp.tool()
    def get_plan(state_dir: str | None = None) -> dict[str, Any]:
        """Get the current task plan with checkboxes.

        Returns the markdown task list showing completion status.

        Args:
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary containing the plan content or error.
        """
        return tools.get_plan(work_dir, state_dir)

    @mcp.tool()
    def get_logs(
        tail: int = 100,
        state_dir: str | None = None,
    ) -> dict[str, Any]:
        """Get logs from the current task run.

        Args:
            tail: Number of lines to return from the end of the log.
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary containing log content or error.
        """
        return tools.get_logs(work_dir, tail, state_dir)

    @mcp.tool()
    def get_progress(state_dir: str | None = None) -> dict[str, Any]:
        """Get the human-readable progress summary.

        Returns what has been accomplished and what remains.

        Args:
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary containing progress content or error.
        """
        return tools.get_progress(work_dir, state_dir)

    @mcp.tool()
    def get_context(state_dir: str | None = None) -> dict[str, Any]:
        """Get the accumulated context and learnings.

        Returns insights gathered during execution.

        Args:
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary containing context content or error.
        """
        return tools.get_context(work_dir, state_dir)

    @mcp.tool()
    def clean_task(
        force: bool = False,
        state_dir: str | None = None,
    ) -> dict[str, Any]:
        """Clean up task state directory.

        Removes all state files to allow starting fresh.

        Args:
            force: If True, skip confirmation (always True for MCP).
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary indicating success or failure.
        """
        return tools.clean_task(work_dir, force, state_dir)

    @mcp.tool()
    def initialize_task(
        goal: str,
        model: str = "opus",
        auto_merge: bool = True,
        max_sessions: int | None = None,
        pause_on_pr: bool = False,
        state_dir: str | None = None,
    ) -> dict[str, Any]:
        """Initialize a new task with the given goal.

        This only initializes the task state - it does NOT run the task.
        Use this to set up a task that will be executed separately.

        Args:
            goal: The goal to achieve.
            model: Model to use (opus, sonnet, haiku).
            auto_merge: Whether to auto-merge PRs when approved.
            max_sessions: Max work sessions before pausing.
            pause_on_pr: Pause after creating PR for manual review.
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary indicating success with run_id or failure.
        """
        return tools.initialize_task(
            work_dir, goal, model, auto_merge, max_sessions, pause_on_pr, state_dir
        )

    @mcp.tool()
    def list_tasks(state_dir: str | None = None) -> dict[str, Any]:
        """List tasks from the current plan.

        Returns parsed tasks with their completion status.

        Args:
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary containing list of tasks with status.
        """
        return tools.list_tasks(work_dir, state_dir)

    @mcp.tool()
    def health_check() -> dict[str, Any]:
        """Health check endpoint for the MCP server.

        Returns server health information including status, version,
        server name, uptime, and number of active tasks.

        Returns:
            Dictionary containing health status information.
        """
        return tools.health_check(work_dir, name, start_time)

    @mcp.tool()
    def pause_task(
        reason: str | None = None,
        state_dir: str | None = None,
    ) -> dict[str, Any]:
        """Pause a running task.

        Transitions the task from planning/working status to paused status.
        The task can be resumed later using resume_task.

        Args:
            reason: Optional reason for pausing (stored in progress).
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary indicating success or failure with status details.
        """
        return tools.pause_task(work_dir, reason, state_dir)

    @mcp.tool()
    def stop_task(
        reason: str | None = None,
        cleanup: bool = False,
        state_dir: str | None = None,
    ) -> dict[str, Any]:
        """Stop a running task and trigger graceful shutdown.

        Transitions the task from any active status to stopped status and
        triggers shutdown of any running processes. The task can be resumed
        later if not cleaned up.

        Args:
            reason: Optional reason for stopping (stored in progress).
            cleanup: If True, also cleanup state files after stopping.
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary indicating success or failure with status details.
        """
        return tools.stop_task(work_dir, reason, cleanup, state_dir)

    @mcp.tool()
    def resume_task(state_dir: str | None = None) -> dict[str, Any]:
        """Resume a paused or blocked task.

        Transitions the task from paused/blocked/stopped status back to working
        status. This is distinct from CLI resume - it only updates the state
        without restarting the work loop.

        Args:
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary indicating success or failure with status details.
        """
        return tools.resume_task(work_dir, state_dir)

    @mcp.tool()
    def update_config(
        auto_merge: bool | None = None,
        max_sessions: int | None = None,
        pause_on_pr: bool | None = None,
        enable_checkpointing: bool | None = None,
        log_level: str | None = None,
        log_format: str | None = None,
        pr_per_task: bool | None = None,
        state_dir: str | None = None,
    ) -> dict[str, Any]:
        """Update task configuration options at runtime.

        Updates the TaskOptions stored in the task state. Only specified
        options are updated; others retain their current values.

        Args:
            auto_merge: Whether to auto-merge PRs when approved.
            max_sessions: Maximum number of work sessions before pausing.
            pause_on_pr: Whether to pause after creating PR for manual review.
            enable_checkpointing: Whether to enable state checkpointing.
            log_level: Log level (quiet, normal, verbose).
            log_format: Log format (text, json).
            pr_per_task: Whether to create PR per task vs per group.
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary indicating success or failure with updated config.
        """
        return tools.update_config(
            work_dir,
            auto_merge=auto_merge,
            max_sessions=max_sessions,
            pause_on_pr=pause_on_pr,
            enable_checkpointing=enable_checkpointing,
            log_level=log_level,
            log_format=log_format,
            pr_per_task=pr_per_task,
            state_dir=state_dir,
        )

    # =============================================================================
    # Mailbox Tool Wrappers
    # =============================================================================

    @mcp.tool()
    def send_message(
        content: str,
        sender: str = "anonymous",
        priority: int = 1,
        state_dir: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to the claudetm mailbox.

        Messages are processed after the current task completes. Multiple messages
        are merged into a single change request that updates the plan before
        continuing work.

        Use this to send instructions, feedback, or change requests to a running
        claudetm instance from external systems or other AI agents.

        Args:
            content: The message content describing the change request.
            sender: Identifier of the sender (default: "anonymous").
            priority: Message priority - 0=low, 1=normal, 2=high, 3=urgent.
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary containing the message_id on success, or error info.

        Example:
            send_message("Please also add unit tests for the new feature")
            send_message("URGENT: Fix the security bug first", priority=3)
        """
        return tools.send_message(work_dir, content, sender, priority, state_dir)

    @mcp.tool()
    def check_mailbox(state_dir: str | None = None) -> dict[str, Any]:
        """Check the status of the claudetm mailbox.

        Returns the number of pending messages and previews of each.
        Use this to see what messages are waiting to be processed.

        Args:
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary containing mailbox status with message previews.
        """
        return tools.check_mailbox(work_dir, state_dir)

    @mcp.tool()
    def clear_mailbox(state_dir: str | None = None) -> dict[str, Any]:
        """Clear all messages from the claudetm mailbox.

        Use this to discard all pending messages without processing them.

        Args:
            state_dir: Optional custom state directory path.

        Returns:
            Dictionary indicating success and number of messages cleared.
        """
        return tools.clear_mailbox(work_dir, state_dir)

    # =============================================================================
    # Repo Setup Tool Wrappers
    # =============================================================================

    @mcp.tool()
    def clone_repo(
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
        return tools.clone_repo(url, target_dir, branch)

    @mcp.tool()
    def setup_repo(
        repo_dir: str,
    ) -> dict[str, Any]:
        """Set up a cloned repository for development.

        Detects the project type and performs appropriate setup:
        - Creates virtual environment (for Python projects)
        - Installs dependencies (pip, npm, pnpm, yarn, bun)
        - Runs setup scripts (setup-hooks.sh, setup.sh, etc.)

        Supports Python projects (pyproject.toml, setup.py, requirements.txt)
        and Node.js projects (package.json). Uses uv for Python dependency
        management when available, falling back to standard venv + pip.

        Args:
            repo_dir: Path to the cloned repository directory to set up.

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
        return tools.setup_repo(repo_dir)

    @mcp.tool()
    def plan_repo(
        repo_dir: str,
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
            repo_dir: Path to the repository directory to plan for.
            goal: The goal/task description to plan for. Be specific about
                what you want to accomplish.
            model: Model to use for planning (default: "opus" for best quality).
                Options: "opus", "sonnet", "haiku".

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
        return tools.plan_repo(repo_dir, goal, model)

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


# =============================================================================
# Server Runner
# =============================================================================


# Transport type alias
TransportType = Literal["stdio", "sse", "streamable-http"]


def _get_authenticated_app(
    mcp: FastMCP,
    transport: TransportType,
    mount_path: str | None = None,
) -> Starlette:
    """Get the Starlette app with authentication middleware if configured.

    Args:
        mcp: The FastMCP server instance.
        transport: The transport type (sse or streamable-http).
        mount_path: Optional mount path for SSE transport.

    Returns:
        Starlette application with optional authentication middleware.
    """
    # Get the appropriate app based on transport
    if transport == "sse":
        app = mcp.sse_app(mount_path)
    else:  # streamable-http
        app = mcp.streamable_http_app()

    # Add authentication middleware if enabled
    if AUTH_AVAILABLE and is_auth_enabled() and add_auth_middleware is not None:
        logger.info("Adding password authentication to MCP server")
        add_auth_middleware(app)

    return app


async def _run_network_transport_async(
    mcp: FastMCP,
    transport: TransportType,
    host: str,
    port: int,
    mount_path: str | None = None,
) -> None:
    """Run the MCP server with network transport and authentication.

    This is an async function that runs the server with uvicorn,
    adding authentication middleware for network transports.

    Args:
        mcp: The FastMCP server instance.
        transport: The transport type (sse or streamable-http).
        host: Host to bind to.
        port: Port to bind to.
        mount_path: Optional mount path for SSE transport.
    """
    import uvicorn

    # Get the app with authentication
    app = _get_authenticated_app(mcp, transport, mount_path)

    # Run with uvicorn
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=mcp.settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


def _log_server_config(
    transport: TransportType,
    host: str,
    port: int,
    auth_enabled: bool,
) -> None:
    """Log server configuration at startup.

    Args:
        transport: The transport type.
        host: The host address.
        port: The port number.
        auth_enabled: Whether authentication is enabled.
    """
    logger.info("=" * 50)
    logger.info("MCP Server Configuration:")
    logger.info(f"  Transport: {transport}")
    if transport != "stdio":
        logger.info(f"  Host: {host}")
        logger.info(f"  Port: {port}")
        logger.info(f"  Password Auth: {'enabled' if auth_enabled else 'disabled'}")
    logger.info("=" * 50)


def run_server(
    name: str = "claude-task-master",
    working_dir: str | None = None,
    transport: TransportType = "stdio",
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Run the MCP server.

    Args:
        name: Server name for identification.
        working_dir: Working directory for task execution.
        transport: Transport type (stdio, sse, streamable-http).
        host: Host to bind to (only for network transports). Defaults to 127.0.0.1.
        port: Port to bind to (only for network transports). Defaults to 8080.

    Security:
        For network transports (sse, streamable-http):
        - Defaults to localhost binding for security
        - ⚠️  AUTHENTICATION REQUIRED: Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH to enable password-based authentication
        - Clients must provide password as Bearer token: Authorization: Bearer <password>
        - When binding to non-localhost addresses, authentication is REQUIRED for security
        - Default authentication is disabled - must be explicitly enabled via CLAUDETM_PASSWORD env var or --password CLI arg
    """
    import anyio

    effective_host = host or MCP_HOST
    effective_port = port or MCP_PORT

    # Check authentication configuration for network transports
    if transport != "stdio" and AUTH_AVAILABLE and check_auth_config is not None:
        auth_enabled, warning = check_auth_config(transport, effective_host)
        if warning:
            logger.warning(warning)
    else:
        auth_enabled = AUTH_AVAILABLE and is_auth_enabled()

    # Log configuration
    _log_server_config(transport, effective_host, effective_port, auth_enabled)

    # Enforce auth for non-localhost network binds (as promised in docstring)
    if transport != "stdio" and effective_host not in ("127.0.0.1", "localhost", "::1"):
        if not auth_enabled:
            logger.error(
                f"MCP server cannot bind to non-localhost address ({effective_host}) "
                "without authentication. Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH."
            )
            raise SystemExit(1)

    # Create the MCP server
    mcp = create_server(name=name, working_dir=working_dir)

    # Configure host/port in FastMCP settings for network transports
    if transport != "stdio":
        mcp.settings.host = effective_host
        mcp.settings.port = effective_port

    # Run based on transport type
    if transport == "stdio":
        # stdio transport - no authentication needed, use FastMCP directly
        mcp.run(transport="stdio")
    else:
        # Network transports - use custom runner with authentication
        anyio.run(
            lambda: _run_network_transport_async(mcp, transport, effective_host, effective_port)
        )


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> None:
    """Main entry point for running the MCP server standalone."""
    import argparse

    parser = argparse.ArgumentParser(description="Run Claude Task Master MCP server")
    parser.add_argument(
        "--name",
        default="claude-task-master",
        help="Server name",
    )
    parser.add_argument(
        "--working-dir",
        help="Working directory for task execution",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport type (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=MCP_HOST,
        help=f"Host to bind to for network transports (default: {MCP_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=MCP_PORT,
        help=f"Port to bind to for network transports (default: {MCP_PORT})",
    )
    parser.add_argument(
        "--password",
        help=(
            "Password for MCP authentication (sets CLAUDETM_PASSWORD env var). "
            "Required for secure access when using network transports."
        ),
    )

    args = parser.parse_args()

    # If --password provided, set the environment variable for auth middleware
    if args.password:
        os.environ["CLAUDETM_PASSWORD"] = args.password

    run_server(
        name=args.name,
        working_dir=args.working_dir,
        transport=args.transport,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
