"""File operation tool handlers for MCP.

Covers: delete_coding_style.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_task_master.core.services import ServiceOutcome, TaskService
from claude_task_master.core.state import StateManager
from claude_task_master.mcp.tool_models import DeleteCodingStyleResult


def _task_service(work_dir: Path, state_dir: str | None) -> TaskService:
    """Build a :class:`TaskService` bound to the resolved state directory."""
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    return TaskService(StateManager(state_dir=state_path))


def delete_coding_style(
    work_dir: Path,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Delete the coding style guide file (coding-style.md).

    The coding style file is a cached guide that's preserved across runs to save
    tokens. Call this to force regeneration on the next planning phase when
    project conventions have changed.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary indicating success or failure with deletion status.
    """
    result = _task_service(work_dir, state_dir).delete_coding_style()

    if result.outcome is ServiceOutcome.NOT_FOUND:
        return DeleteCodingStyleResult(
            success=False,
            message="No task state found",
            deleted=False,
            error="No active task found. Initialize a task first.",
        ).model_dump()
    if not result.success:
        return DeleteCodingStyleResult(
            success=False,
            message=f"Failed to delete coding style guide: {result.error}",
            deleted=False,
            error=result.error,
        ).model_dump()

    if result.data["deleted"]:
        return DeleteCodingStyleResult(
            success=True,
            message="Coding style guide deleted successfully",
            deleted=True,
        ).model_dump()
    return DeleteCodingStyleResult(
        success=True,
        message="Coding style guide did not exist",
        deleted=False,
    ).model_dump()
