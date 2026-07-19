"""Task control tool handlers for MCP.

Covers: pause_task, stop_task, resume_task, update_config.

Query/read operations live in
:mod:`claude_task_master.mcp.tool_handlers_task`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_task_master.core.services import ServiceOutcome, TaskService
from claude_task_master.core.state import StateManager
from claude_task_master.mcp.tool_models import (
    PauseTaskResult,
    ResumeTaskResult,
    StopTaskResult,
    UpdateConfigResult,
)

# =============================================================================
# Internal helper (mirrored from tool_handlers_task to avoid cross-import)
# =============================================================================


def _task_service(work_dir: Path, state_dir: str | None) -> TaskService:
    """Build a :class:`TaskService` bound to the resolved state directory."""
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    return TaskService(StateManager(state_dir=state_path))


# =============================================================================
# Control handlers
# =============================================================================


def pause_task(
    work_dir: Path,
    reason: str | None = None,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Pause a running task.

    Transitions the task from planning/working status to paused status.
    The task can be resumed later using resume_task.

    Args:
        work_dir: Working directory for the server.
        reason: Optional reason for pausing (stored in progress).
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary indicating success or failure with status details.
    """
    result = _task_service(work_dir, state_dir).pause(reason=reason)

    if result.outcome is ServiceOutcome.NOT_FOUND:
        return PauseTaskResult(
            success=False,
            message="No active task found. Initialize a task first.",
        ).model_dump()
    if result.outcome is ServiceOutcome.INVALID:
        return PauseTaskResult(
            success=False,
            message=result.message,
            previous_status=result.data.get("previous_status"),
        ).model_dump()
    if not result.success:
        return PauseTaskResult(
            success=False,
            message=f"Failed to pause task: {result.error}",
        ).model_dump()

    control_result = result.data["result"]
    return PauseTaskResult(
        success=True,
        message=control_result.message,
        previous_status=control_result.previous_status,
        new_status=control_result.new_status,
        reason=reason,
    ).model_dump()


def stop_task(
    work_dir: Path,
    reason: str | None = None,
    cleanup: bool = False,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Stop a running task and trigger graceful shutdown.

    Transitions the task from planning/working/blocked/paused status to stopped
    status and triggers shutdown of any running processes. The task can be
    resumed later if not cleaned up.

    Args:
        work_dir: Working directory for the server.
        reason: Optional reason for stopping (stored in progress).
        cleanup: If True, also cleanup state files after stopping.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary indicating success or failure with status details.
    """
    result = _task_service(work_dir, state_dir).stop(reason=reason, cleanup=cleanup)

    if result.outcome is ServiceOutcome.NOT_FOUND:
        return StopTaskResult(
            success=False,
            message="No active task found. Nothing to stop.",
        ).model_dump()
    if result.outcome is ServiceOutcome.INVALID:
        return StopTaskResult(
            success=False,
            message=result.message,
            previous_status=result.data.get("previous_status"),
        ).model_dump()
    if not result.success:
        return StopTaskResult(
            success=False,
            message=f"Failed to stop task: {result.error}",
        ).model_dump()

    control_result = result.data["result"]
    return StopTaskResult(
        success=True,
        message=control_result.message,
        previous_status=control_result.previous_status,
        new_status=control_result.new_status,
        reason=reason,
        cleanup=cleanup,
    ).model_dump()


def resume_task(
    work_dir: Path,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Resume a paused or blocked task.

    Transitions the task from paused/blocked/stopped status back to working
    status. This is distinct from CLI resume - it only updates the state
    without restarting the work loop.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary indicating success or failure with status details.
    """
    result = _task_service(work_dir, state_dir).resume()

    if result.outcome is ServiceOutcome.NOT_FOUND:
        return ResumeTaskResult(
            success=False,
            message="No active task found. Initialize a task first.",
        ).model_dump()
    if result.outcome is ServiceOutcome.INVALID:
        return ResumeTaskResult(
            success=False,
            message=result.message,
            previous_status=result.data.get("previous_status"),
        ).model_dump()
    if not result.success:
        return ResumeTaskResult(
            success=False,
            message=f"Failed to resume task: {result.error}",
        ).model_dump()

    control_result = result.data["result"]
    return ResumeTaskResult(
        success=True,
        message=control_result.message,
        previous_status=control_result.previous_status,
        new_status=control_result.new_status,
    ).model_dump()


def update_config(
    work_dir: Path,
    auto_merge: bool | None = None,
    max_sessions: int | None = None,
    max_prs: int | None = None,
    pause_on_pr: bool | None = None,
    enable_checkpointing: bool | None = None,
    log_level: str | None = None,
    log_format: str | None = None,
    pr_per_task: bool | None = None,
    state_dir: str | None = None,
    *,
    enable_release: bool | None = None,
    enable_verification: bool | None = None,
) -> dict[str, Any]:
    """Update task configuration options at runtime.

    Updates the TaskOptions stored in the task state. Only specified
    options are updated; others retain their current values.

    Args:
        work_dir: Working directory for the server.
        auto_merge: Whether to auto-merge PRs when approved.
        max_sessions: Maximum number of work sessions before pausing.
        max_prs: Maximum number of pull requests to create.
        pause_on_pr: Whether to pause after creating PR for manual review.
        enable_checkpointing: Whether to enable state checkpointing.
        log_level: Log level (quiet, normal, verbose).
        log_format: Log format (text, json).
        pr_per_task: Whether to create PR per task vs per group.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary indicating success or failure with updated config details.
    """
    # Build kwargs from provided options (only non-None values)
    kwargs: dict[str, bool | int | str | None] = {}
    if auto_merge is not None:
        kwargs["auto_merge"] = auto_merge
    if enable_release is not None:
        kwargs["enable_release"] = enable_release
    if enable_verification is not None:
        kwargs["enable_verification"] = enable_verification
    if max_sessions is not None:
        kwargs["max_sessions"] = max_sessions
    if max_prs is not None:
        kwargs["max_prs"] = max_prs
    if pause_on_pr is not None:
        kwargs["pause_on_pr"] = pause_on_pr
    if enable_checkpointing is not None:
        kwargs["enable_checkpointing"] = enable_checkpointing
    if log_level is not None:
        kwargs["log_level"] = log_level
    if log_format is not None:
        kwargs["log_format"] = log_format
    if pr_per_task is not None:
        kwargs["pr_per_task"] = pr_per_task

    # If no options provided, return error
    if not kwargs:
        return UpdateConfigResult(
            success=False,
            message="No configuration options provided",
            error="At least one configuration option must be specified",
        ).model_dump()

    result = _task_service(work_dir, state_dir).update_config(**kwargs)

    if result.outcome is ServiceOutcome.NOT_FOUND:
        return UpdateConfigResult(
            success=False,
            message="No active task found. Initialize a task first.",
            error="No task state exists",
        ).model_dump()
    if result.outcome is ServiceOutcome.INVALID:
        return UpdateConfigResult(
            success=False,
            message=result.message,
            error="Invalid configuration option",
        ).model_dump()
    if not result.success:
        return UpdateConfigResult(
            success=False,
            message=f"Failed to update configuration: {result.error}",
            error=result.error,
        ).model_dump()

    control_result = result.data["result"]
    details = control_result.details
    return UpdateConfigResult(
        success=True,
        message=control_result.message,
        updated=details.get("updated") if details else None,
        current=details.get("current") if details else None,
    ).model_dump()
