"""MCP Tool implementations for Claude Task Master.

This module contains the actual tool logic that can be tested independently
of the MCP server wrapper.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from claude_task_master.core.control import (
    ControlManager,
    ControlOperationNotAllowedError,
    NoActiveTaskError,
)
from claude_task_master.core.state import (
    StateManager,
    TaskOptions,
)

# =============================================================================
# Response Models
# =============================================================================


class TaskStatus(BaseModel):
    """Status response for get_status tool."""

    goal: str
    status: str
    model: str
    current_task_index: int
    session_count: int
    run_id: str
    current_pr: int | None = None
    workflow_stage: str | None = None
    options: dict[str, Any]


class StartTaskResult(BaseModel):
    """Result from start_task tool."""

    success: bool
    message: str
    run_id: str | None = None
    status: str | None = None


class CleanResult(BaseModel):
    """Result from clean tool."""

    success: bool
    message: str
    files_removed: bool = False


class LogsResult(BaseModel):
    """Result from get_logs tool."""

    success: bool
    log_content: str | None = None
    log_file: str | None = None
    error: str | None = None


class HealthCheckResult(BaseModel):
    """Result from health_check tool."""

    status: str
    version: str
    server_name: str
    uptime_seconds: float | None = None
    active_tasks: int = 0


class PauseTaskResult(BaseModel):
    """Result from pause_task tool."""

    success: bool
    message: str
    previous_status: str | None = None
    new_status: str | None = None
    reason: str | None = None


class StopTaskResult(BaseModel):
    """Result from stop_task tool."""

    success: bool
    message: str
    previous_status: str | None = None
    new_status: str | None = None
    reason: str | None = None
    cleanup: bool = False


class ResumeTaskResult(BaseModel):
    """Result from resume_task tool."""

    success: bool
    message: str
    previous_status: str | None = None
    new_status: str | None = None


class UpdateConfigResult(BaseModel):
    """Result from update_config tool."""

    success: bool
    message: str
    updated: dict[str, bool | int | str | None] | None = None
    current: dict[str, bool | int | str | None] | None = None
    error: str | None = None


class SendMessageResult(BaseModel):
    """Result from send_message mailbox tool."""

    success: bool
    message_id: str | None = None
    message: str | None = None
    error: str | None = None


class MailboxStatusResult(BaseModel):
    """Result from check_mailbox tool."""

    success: bool
    count: int = 0
    previews: list[dict[str, Any]] = []
    last_checked: str | None = None
    total_messages_received: int = 0
    error: str | None = None


class ClearMailboxResult(BaseModel):
    """Result from clear_mailbox tool."""

    success: bool
    messages_cleared: int = 0
    message: str | None = None
    error: str | None = None


class CloneRepoResult(BaseModel):
    """Result from clone_repo tool."""

    success: bool
    message: str
    repo_url: str | None = None
    target_dir: str | None = None
    branch: str | None = None
    error: str | None = None


class SetupRepoResult(BaseModel):
    """Result from setup_repo tool."""

    success: bool
    message: str
    work_dir: str | None = None
    steps_completed: list[str] = []
    venv_path: str | None = None
    dependencies_installed: bool = False
    setup_scripts_run: list[str] = []
    error: str | None = None


class PlanRepoResult(BaseModel):
    """Result from plan_repo tool."""

    success: bool
    message: str
    work_dir: str | None = None
    goal: str | None = None
    plan: str | None = None
    criteria: str | None = None
    run_id: str | None = None
    error: str | None = None


# =============================================================================
# Tool Implementations
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
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": False,
            "error": "No active task found",
            "suggestion": "Use start_task to begin a new task",
        }

    try:
        state = state_manager.load_state()
        goal = state_manager.load_goal()

        return TaskStatus(
            goal=goal,
            status=state.status,
            model=state.model,
            current_task_index=state.current_task_index,
            session_count=state.session_count,
            run_id=state.run_id,
            current_pr=state.current_pr,
            workflow_stage=state.workflow_stage,
            options=state.options.model_dump(),
        ).model_dump()
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


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
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": False,
            "error": "No active task found",
        }

    try:
        plan = state_manager.load_plan()
        if not plan:
            return {
                "success": False,
                "error": "No plan found",
            }

        return {
            "success": True,
            "plan": plan,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def get_logs(
    work_dir: Path,
    tail: int = 100,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Get logs from the current task run.

    Args:
        work_dir: Working directory for the server.
        tail: Number of lines to return from the end of the log.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary containing log content or error.
    """
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return LogsResult(
            success=False,
            error="No active task found",
        ).model_dump()

    try:
        state = state_manager.load_state()
        log_file = state_manager.get_log_file(state.run_id)

        if not log_file.exists():
            return LogsResult(
                success=False,
                error="No log file found",
            ).model_dump()

        with open(log_file) as f:
            lines = f.readlines()

        log_content = "".join(lines[-tail:])

        return LogsResult(
            success=True,
            log_content=log_content,
            log_file=str(log_file),
        ).model_dump()
    except Exception as e:
        return LogsResult(
            success=False,
            error=str(e),
        ).model_dump()


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
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": False,
            "error": "No active task found",
        }

    try:
        progress = state_manager.load_progress()
        if not progress:
            return {
                "success": True,
                "progress": None,
                "message": "No progress recorded yet",
            }

        return {
            "success": True,
            "progress": progress,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


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
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": False,
            "error": "No active task found",
        }

    try:
        context = state_manager.load_context()
        return {
            "success": True,
            "context": context or "",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


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
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return CleanResult(
            success=True,
            message="No task state found to clean",
            files_removed=False,
        ).model_dump()

    # Check for active session
    if state_manager.is_session_active() and not force:
        return CleanResult(
            success=False,
            message="Another claudetm session is active. Use force=True to override.",
            files_removed=False,
        ).model_dump()

    try:
        # Release session lock before cleanup
        state_manager.release_session_lock()

        if state_manager.state_dir.exists():
            shutil.rmtree(state_manager.state_dir)
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
    except Exception as e:
        return CleanResult(
            success=False,
            message=f"Failed to clean task state: {e}",
        ).model_dump()


def initialize_task(
    work_dir: Path,
    goal: str,
    model: str = "opus",
    auto_merge: bool = True,
    max_sessions: int | None = None,
    pause_on_pr: bool = False,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Initialize a new task with the given goal.

    Args:
        work_dir: Working directory for the server.
        goal: The goal to achieve.
        model: Model to use (opus, sonnet, haiku).
        auto_merge: Whether to auto-merge PRs when approved.
        max_sessions: Max work sessions before pausing.
        pause_on_pr: Pause after creating PR for manual review.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary indicating success with run_id or failure.
    """
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)

    if state_manager.exists():
        return StartTaskResult(
            success=False,
            message="Task already exists. Use clean_task first or resume the existing task.",
        ).model_dump()

    try:
        options = TaskOptions(
            auto_merge=auto_merge,
            max_sessions=max_sessions,
            pause_on_pr=pause_on_pr,
        )
        state = state_manager.initialize(goal=goal, model=model, options=options)

        return StartTaskResult(
            success=True,
            message=f"Task initialized successfully with goal: {goal}",
            run_id=state.run_id,
            status=state.status,
        ).model_dump()
    except Exception as e:
        return StartTaskResult(
            success=False,
            message=f"Failed to initialize task: {e}",
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
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": False,
            "error": "No active task found",
        }

    try:
        plan = state_manager.load_plan()
        if not plan:
            return {
                "success": False,
                "error": "No plan found",
            }

        tasks = []
        for line in plan.split("\n"):
            stripped = line.strip()
            if stripped.startswith("- [ ]"):
                tasks.append(
                    {
                        "task": stripped[5:].strip(),
                        "completed": False,
                    }
                )
            elif stripped.startswith("- [x]"):
                tasks.append(
                    {
                        "task": stripped[5:].strip(),
                        "completed": True,
                    }
                )

        state = state_manager.load_state()

        return {
            "success": True,
            "tasks": tasks,
            "total": len(tasks),
            "completed": sum(1 for t in tasks if t["completed"]),
            "current_index": state.current_task_index,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
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
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)
    control_manager = ControlManager(state_manager=state_manager)

    try:
        result = control_manager.pause(reason=reason)
        return PauseTaskResult(
            success=True,
            message=result.message,
            previous_status=result.previous_status,
            new_status=result.new_status,
            reason=reason,
        ).model_dump()
    except NoActiveTaskError:
        return PauseTaskResult(
            success=False,
            message="No active task found. Initialize a task first.",
        ).model_dump()
    except ControlOperationNotAllowedError as e:
        return PauseTaskResult(
            success=False,
            message=e.message,
            previous_status=e.current_status,
        ).model_dump()
    except Exception as e:
        return PauseTaskResult(
            success=False,
            message=f"Failed to pause task: {e}",
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
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)
    control_manager = ControlManager(state_manager=state_manager)

    try:
        result = control_manager.stop(reason=reason, cleanup=cleanup)
        return StopTaskResult(
            success=True,
            message=result.message,
            previous_status=result.previous_status,
            new_status=result.new_status,
            reason=reason,
            cleanup=cleanup,
        ).model_dump()
    except NoActiveTaskError:
        return StopTaskResult(
            success=False,
            message="No active task found. Nothing to stop.",
        ).model_dump()
    except ControlOperationNotAllowedError as e:
        return StopTaskResult(
            success=False,
            message=e.message,
            previous_status=e.current_status,
        ).model_dump()
    except Exception as e:
        return StopTaskResult(
            success=False,
            message=f"Failed to stop task: {e}",
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
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)
    control_manager = ControlManager(state_manager=state_manager)

    try:
        result = control_manager.resume()
        return ResumeTaskResult(
            success=True,
            message=result.message,
            previous_status=result.previous_status,
            new_status=result.new_status,
        ).model_dump()
    except NoActiveTaskError:
        return ResumeTaskResult(
            success=False,
            message="No active task found. Initialize a task first.",
        ).model_dump()
    except ControlOperationNotAllowedError as e:
        return ResumeTaskResult(
            success=False,
            message=e.message,
            previous_status=e.current_status,
        ).model_dump()
    except Exception as e:
        return ResumeTaskResult(
            success=False,
            message=f"Failed to resume task: {e}",
        ).model_dump()


def update_config(
    work_dir: Path,
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
        work_dir: Working directory for the server.
        auto_merge: Whether to auto-merge PRs when approved.
        max_sessions: Maximum number of work sessions before pausing.
        pause_on_pr: Whether to pause after creating PR for manual review.
        enable_checkpointing: Whether to enable state checkpointing.
        log_level: Log level (quiet, normal, verbose).
        log_format: Log format (text, json).
        pr_per_task: Whether to create PR per task vs per group.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary indicating success or failure with updated config details.
    """
    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"
    state_manager = StateManager(state_dir=state_path)
    control_manager = ControlManager(state_manager=state_manager)

    # Build kwargs from provided options (only non-None values)
    kwargs: dict[str, bool | int | str | None] = {}
    if auto_merge is not None:
        kwargs["auto_merge"] = auto_merge
    if max_sessions is not None:
        kwargs["max_sessions"] = max_sessions
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

    try:
        result = control_manager.update_config(**kwargs)
        return UpdateConfigResult(
            success=True,
            message=result.message,
            updated=result.details.get("updated") if result.details else None,
            current=result.details.get("current") if result.details else None,
        ).model_dump()
    except NoActiveTaskError:
        return UpdateConfigResult(
            success=False,
            message="No active task found. Initialize a task first.",
            error="No task state exists",
        ).model_dump()
    except ValueError as e:
        return UpdateConfigResult(
            success=False,
            message=str(e),
            error="Invalid configuration option",
        ).model_dump()
    except Exception as e:
        return UpdateConfigResult(
            success=False,
            message=f"Failed to update configuration: {e}",
            error=str(e),
        ).model_dump()


# =============================================================================
# Resource Implementations
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


# =============================================================================
# Mailbox Tool Implementations
# =============================================================================


def send_message(
    work_dir: Path,
    content: str,
    sender: str = "anonymous",
    priority: int = 1,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Send a message to the claudetm mailbox.

    Messages in the mailbox will be processed after the current task completes.
    Multiple messages are merged into a single change request that updates
    the plan before continuing work.

    Args:
        work_dir: Working directory for the server.
        content: The message content describing the change request.
        sender: Identifier of the sender (default: "anonymous").
        priority: Message priority (0=low, 1=normal, 2=high, 3=urgent).
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary containing the message_id on success, or error info.
    """
    from claude_task_master.mailbox import MailboxStorage

    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"

    # Validate content
    if not content or not content.strip():
        return SendMessageResult(
            success=False,
            error="Message content cannot be empty",
        ).model_dump()

    # Validate priority range
    if priority < 0 or priority > 3:
        return SendMessageResult(
            success=False,
            error="Priority must be between 0 (low) and 3 (urgent)",
        ).model_dump()

    try:
        mailbox = MailboxStorage(state_dir=state_path)
        message_id = mailbox.add_message(
            content=content.strip(),
            sender=sender,
            priority=priority,
        )

        return SendMessageResult(
            success=True,
            message_id=message_id,
            message=f"Message sent successfully (id: {message_id})",
        ).model_dump()
    except Exception as e:
        return SendMessageResult(
            success=False,
            error=f"Failed to send message: {e}",
        ).model_dump()


def check_mailbox(
    work_dir: Path,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Check the status of the claudetm mailbox.

    Returns the number of pending messages and previews of each.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary containing mailbox status information.
    """
    from claude_task_master.mailbox import MailboxStorage

    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"

    try:
        mailbox = MailboxStorage(state_dir=state_path)
        status = mailbox.get_status()

        return MailboxStatusResult(
            success=True,
            count=status["count"],
            previews=status["previews"],
            last_checked=status["last_checked"],
            total_messages_received=status["total_messages_received"],
        ).model_dump()
    except Exception as e:
        return MailboxStatusResult(
            success=False,
            error=f"Failed to check mailbox: {e}",
        ).model_dump()


def clear_mailbox(
    work_dir: Path,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """Clear all messages from the claudetm mailbox.

    Args:
        work_dir: Working directory for the server.
        state_dir: Optional custom state directory path.

    Returns:
        Dictionary indicating success and number of messages cleared.
    """
    from claude_task_master.mailbox import MailboxStorage

    state_path = Path(state_dir) if state_dir else work_dir / ".claude-task-master"

    try:
        mailbox = MailboxStorage(state_dir=state_path)
        count = mailbox.clear()

        return ClearMailboxResult(
            success=True,
            messages_cleared=count,
            message=f"Cleared {count} message(s) from mailbox",
        ).model_dump()
    except Exception as e:
        return ClearMailboxResult(
            success=False,
            error=f"Failed to clear mailbox: {e}",
        ).model_dump()


# =============================================================================
# Repo Setup Tool Implementations
# =============================================================================

# Default workspace base for repo setup
DEFAULT_WORKSPACE_BASE = Path.home() / "workspace" / "claude-task-master"


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
    import subprocess

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

    # Determine target directory
    repo_name = _extract_repo_name(url)
    if target_dir:
        target_path = Path(target_dir).expanduser().resolve()
    else:
        # Default to ~/workspace/claude-task-master/{repo-name}
        target_path = DEFAULT_WORKSPACE_BASE / repo_name

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


def setup_repo(
    work_dir: str | Path,
) -> dict[str, Any]:
    """Set up a cloned repository for development.

    Detects the project type and performs appropriate setup:
    - Creates virtual environment (for Python projects)
    - Installs dependencies (pip, npm, etc.)
    - Runs setup scripts (setup-hooks.sh, etc.)

    Args:
        work_dir: Path to the cloned repository directory.

    Returns:
        Dictionary containing setup result with success status and details.
    """
    import subprocess
    import sys

    work_path = Path(work_dir).expanduser().resolve()
    steps_completed: list[str] = []
    setup_scripts_run: list[str] = []
    venv_path: str | None = None
    dependencies_installed = False

    # Validate work directory
    if not work_path.exists():
        return SetupRepoResult(
            success=False,
            message=f"Directory does not exist: {work_path}",
            work_dir=str(work_path),
            error="Work directory not found",
        ).model_dump()

    if not work_path.is_dir():
        return SetupRepoResult(
            success=False,
            message=f"Path is not a directory: {work_path}",
            work_dir=str(work_path),
            error="Path is not a directory",
        ).model_dump()

    # Detect project type based on manifest files
    is_python = (work_path / "pyproject.toml").exists() or (work_path / "setup.py").exists()
    is_node = (work_path / "package.json").exists()
    has_requirements = (work_path / "requirements.txt").exists()
    has_uv_lock = (work_path / "uv.lock").exists()

    # Detect setup scripts
    setup_scripts: list[Path] = []
    scripts_dir = work_path / "scripts"
    if scripts_dir.exists():
        # Look for common setup scripts
        for script_name in ["setup-hooks.sh", "setup.sh", "install.sh", "bootstrap.sh"]:
            script_path = scripts_dir / script_name
            if script_path.exists() and script_path.is_file():
                setup_scripts.append(script_path)

    # Also check root directory for setup scripts
    for script_name in ["setup.sh", "install.sh", "bootstrap.sh"]:
        script_path = work_path / script_name
        if script_path.exists() and script_path.is_file():
            setup_scripts.append(script_path)

    try:
        # === Python Project Setup ===
        if is_python:
            steps_completed.append("Detected Python project")

            # Check for uv (preferred) or fall back to standard venv + pip
            has_uv = shutil.which("uv") is not None

            if has_uv:
                # Use uv for virtual environment and dependency management
                steps_completed.append("Using uv for dependency management")

                # Create venv with uv if not exists
                venv_dir = work_path / ".venv"
                if not venv_dir.exists():
                    result = subprocess.run(
                        ["uv", "venv", str(venv_dir)],
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=60,
                    )
                    if result.returncode != 0:
                        return SetupRepoResult(
                            success=False,
                            message=f"Failed to create venv with uv: {result.stderr}",
                            work_dir=str(work_path),
                            steps_completed=steps_completed,
                            error=result.stderr,
                        ).model_dump()
                    steps_completed.append("Created virtual environment with uv")
                else:
                    steps_completed.append("Virtual environment already exists")

                venv_path = str(venv_dir)

                # Install dependencies with uv
                # Prefer uv sync for uv-managed projects, otherwise uv pip install
                if has_uv_lock or (work_path / "pyproject.toml").exists():
                    # Use uv sync for projects with pyproject.toml
                    sync_cmd = ["uv", "sync"]
                    # Try to install all extras if available
                    if (work_path / "pyproject.toml").exists():
                        sync_cmd.append("--all-extras")

                    result = subprocess.run(
                        sync_cmd,
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=300,
                    )
                    if result.returncode == 0:
                        dependencies_installed = True
                        steps_completed.append("Installed dependencies with uv sync")
                    else:
                        # Fall back to basic uv sync without extras
                        result = subprocess.run(
                            ["uv", "sync"],
                            cwd=work_path,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=300,
                        )
                        if result.returncode == 0:
                            dependencies_installed = True
                            steps_completed.append("Installed dependencies with uv sync (basic)")
                        else:
                            steps_completed.append(f"Warning: uv sync failed: {result.stderr}")
                elif has_requirements:
                    result = subprocess.run(
                        ["uv", "pip", "install", "-r", "requirements.txt"],
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=300,
                    )
                    if result.returncode == 0:
                        dependencies_installed = True
                        steps_completed.append("Installed dependencies from requirements.txt")
                    else:
                        steps_completed.append(f"Warning: pip install failed: {result.stderr}")
            else:
                # Fall back to standard Python venv + pip
                steps_completed.append("Using standard venv + pip")

                venv_dir = work_path / ".venv"
                if not venv_dir.exists():
                    result = subprocess.run(
                        ["python3", "-m", "venv", str(venv_dir)],
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=120,
                    )
                    if result.returncode != 0:
                        return SetupRepoResult(
                            success=False,
                            message=f"Failed to create venv: {result.stderr}",
                            work_dir=str(work_path),
                            steps_completed=steps_completed,
                            error=result.stderr,
                        ).model_dump()
                    steps_completed.append("Created virtual environment")
                else:
                    steps_completed.append("Virtual environment already exists")

                venv_path = str(venv_dir)
                # Use platform-appropriate path for pip
                pip_path = (
                    venv_dir
                    / ("Scripts" if sys.platform == "win32" else "bin")
                    / ("pip.exe" if sys.platform == "win32" else "pip")
                )

                # Install dependencies with pip
                if (work_path / "pyproject.toml").exists():
                    # Install project in editable mode with dev extras
                    result = subprocess.run(
                        [str(pip_path), "install", "-e", ".[dev]"],
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=300,
                    )
                    if result.returncode == 0:
                        dependencies_installed = True
                        steps_completed.append("Installed project with pip (editable + dev)")
                    else:
                        # Try without dev extras
                        result = subprocess.run(
                            [str(pip_path), "install", "-e", "."],
                            cwd=work_path,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=300,
                        )
                        if result.returncode == 0:
                            dependencies_installed = True
                            steps_completed.append("Installed project with pip (editable)")
                        else:
                            steps_completed.append(f"Warning: pip install failed: {result.stderr}")
                elif has_requirements:
                    result = subprocess.run(
                        [str(pip_path), "install", "-r", "requirements.txt"],
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=300,
                    )
                    if result.returncode == 0:
                        dependencies_installed = True
                        steps_completed.append("Installed dependencies from requirements.txt")
                    else:
                        steps_completed.append(f"Warning: pip install failed: {result.stderr}")

        # === Node.js Project Setup ===
        if is_node:
            steps_completed.append("Detected Node.js project")

            # Check for package managers (lock files indicate preferred manager)
            has_pnpm_lock = (work_path / "pnpm-lock.yaml").exists()
            has_yarn_lock = (work_path / "yarn.lock").exists()
            has_bun_lock = (work_path / "bun.lockb").exists()

            # Determine which package manager to use
            if has_bun_lock and shutil.which("bun"):
                pkg_manager = "bun"
                install_cmd = ["bun", "install"]
            elif has_pnpm_lock and shutil.which("pnpm"):
                pkg_manager = "pnpm"
                install_cmd = ["pnpm", "install"]
            elif has_yarn_lock and shutil.which("yarn"):
                pkg_manager = "yarn"
                install_cmd = ["yarn", "install"]
            elif shutil.which("npm"):
                pkg_manager = "npm"
                install_cmd = ["npm", "install"]
            else:
                steps_completed.append("Warning: No Node.js package manager found")
                pkg_manager = None
                install_cmd = None

            if install_cmd:
                result = subprocess.run(
                    install_cmd,
                    cwd=work_path,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=300,
                )
                if result.returncode == 0:
                    dependencies_installed = True
                    steps_completed.append(f"Installed dependencies with {pkg_manager}")
                else:
                    steps_completed.append(
                        f"Warning: {pkg_manager} install failed: {result.stderr}"
                    )

        # === Run Setup Scripts ===
        for script in setup_scripts:
            try:
                # Make script executable (skip on Windows where chmod is not needed)
                if sys.platform != "win32":
                    script.chmod(script.stat().st_mode | 0o755)

                result = subprocess.run(
                    [str(script)],
                    cwd=work_path,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=120,
                )
                if result.returncode == 0:
                    setup_scripts_run.append(str(script.relative_to(work_path)))
                    steps_completed.append(f"Ran setup script: {script.name}")
                else:
                    steps_completed.append(
                        f"Warning: Setup script {script.name} failed: {result.stderr}"
                    )
            except Exception as e:
                steps_completed.append(f"Warning: Could not run {script.name}: {e}")

        # Determine overall success
        # Success if we detected a project type and either installed deps or ran scripts
        success = len(steps_completed) > 0 and (
            dependencies_installed or len(setup_scripts_run) > 0
        )

        if not is_python and not is_node:
            steps_completed.append("No recognized project type (Python or Node.js)")
            if setup_scripts_run:
                success = True  # Still success if we ran setup scripts
            else:
                success = False

        message = (
            f"Setup completed for {work_path.name}"
            if success
            else f"Setup incomplete for {work_path.name}"
        )

        return SetupRepoResult(
            success=success,
            message=message,
            work_dir=str(work_path),
            steps_completed=steps_completed,
            venv_path=venv_path,
            dependencies_installed=dependencies_installed,
            setup_scripts_run=setup_scripts_run,
        ).model_dump()

    except subprocess.TimeoutExpired as e:
        return SetupRepoResult(
            success=False,
            message=f"Setup timed out: {e}",
            work_dir=str(work_path),
            steps_completed=steps_completed,
            venv_path=venv_path,
            dependencies_installed=dependencies_installed,
            setup_scripts_run=setup_scripts_run,
            error="Operation timed out",
        ).model_dump()

    except Exception as e:
        return SetupRepoResult(
            success=False,
            message=f"Setup failed: {e}",
            work_dir=str(work_path),
            steps_completed=steps_completed,
            venv_path=venv_path,
            dependencies_installed=dependencies_installed,
            setup_scripts_run=setup_scripts_run,
            error=str(e),
        ).model_dump()


def plan_repo(
    work_dir: str | Path,
    goal: str,
    model: str = "opus",
) -> dict[str, Any]:
    """Create a plan for a repository without executing any work.

    This is a plan-only mode that reads the codebase using read-only tools
    (Read, Glob, Grep, Bash) and outputs a structured plan with tasks and
    success criteria. No changes are made to the repository.

    Use this after `clone_repo` and `setup_repo` to plan work before execution,
    or to get a plan for a new goal in an existing repository.

    Args:
        work_dir: Path to the repository directory to plan for.
        goal: The goal/task description to plan for.
        model: Model to use for planning (default: "opus" for best quality).

    Returns:
        Dictionary containing planning result with success status, plan, and criteria.
    """
    work_path = Path(work_dir).expanduser().resolve()

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
        from claude_task_master.core.agent_models import ModelType
        from claude_task_master.core.credentials import CredentialManager

        # Get valid access token
        cred_manager = CredentialManager()
        access_token = cred_manager.get_valid_token()

        # Map model string to ModelType
        model_map = {
            "opus": ModelType.OPUS,
            "sonnet": ModelType.SONNET,
            "haiku": ModelType.HAIKU,
        }
        model_type = model_map.get(model.lower(), ModelType.OPUS)

        # Initialize task state
        options = TaskOptions(
            auto_merge=False,  # Plan-only mode
            max_sessions=1,
            pause_on_pr=True,
        )
        state = state_manager.initialize(goal=goal, model=model, options=options)

        # Update status to planning
        state.status = "planning"
        state_manager.save_state(state)

        # Create agent wrapper
        agent = AgentWrapper(
            access_token=access_token,
            model=model_type,
            working_dir=str(work_path),
            enable_safety_hooks=True,
        )

        # Run planning phase (read-only)
        result = agent.run_planning_phase(goal=goal, context="")

        # Extract plan and criteria
        plan = result.get("plan", "")
        criteria = result.get("criteria", "")

        # Save plan and criteria to state
        if plan:
            state_manager.save_plan(plan)
        if criteria:
            state_manager.save_criteria(criteria)

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
