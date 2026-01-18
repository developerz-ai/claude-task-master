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
