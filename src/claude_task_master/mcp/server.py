"""MCP Server implementation for Claude Task Master.

This module implements an MCP server that exposes claudetm functionality
as tools that other Claude instances can use, enabling remote task orchestration.

Security Note:
    The MCP server defaults to stdio transport which is inherently secure.
    When using network transports (sse, streamable-http), the server binds
    to localhost (127.0.0.1) by default for security.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

# Import MCP SDK - using try/except for graceful degradation
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)

# Security: Default host for network transports
MCP_HOST = os.getenv("CLAUDETM_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("CLAUDETM_MCP_PORT", "8080"))

from claude_task_master.mcp import tools

# =============================================================================
# Re-export response models for convenience
# =============================================================================

TaskStatus = tools.TaskStatus
StartTaskResult = tools.StartTaskResult
CleanResult = tools.CleanResult
LogsResult = tools.LogsResult


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
    if FastMCP is None:
        raise ImportError("MCP SDK not installed. Install with: pip install mcp")

    # Create the server
    mcp = FastMCP(name)

    # Store working directory in server context
    work_dir = Path(working_dir) if working_dir else Path.cwd()

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
        For network transports, defaults to localhost binding for security.
        Set CLAUDETM_MCP_HOST to override (use with caution).
    """
    # Security warning for non-localhost binding
    effective_host = host or MCP_HOST
    if transport != "stdio" and effective_host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            f"MCP server binding to non-localhost address ({effective_host}). "
            "Ensure proper authentication is configured."
        )

    mcp = create_server(name=name, working_dir=working_dir)
    mcp.run(transport=transport)


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

    args = parser.parse_args()
    run_server(
        name=args.name,
        working_dir=args.working_dir,
        transport=args.transport,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
