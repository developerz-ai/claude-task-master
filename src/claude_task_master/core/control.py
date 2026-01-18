"""Control Manager - Runtime control operations for task execution.

This module provides the ControlManager class for managing runtime control
operations like pause, stop, resume, and config updates. It coordinates
between StateManager and ShutdownManager to handle graceful state transitions.

Example usage:
    ```python
    from claude_task_master.core.control import ControlManager
    from claude_task_master.core.state import StateManager

    state_manager = StateManager()
    control = ControlManager(state_manager)

    # Pause a running task
    result = control.pause("User requested pause")

    # Resume a paused task
    result = control.resume()

    # Update configuration
    result = control.update_config(max_sessions=10, auto_merge=False)

    # Stop and cleanup
    result = control.stop("Task completed")
    ```
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from claude_task_master.core.shutdown import (
    ShutdownManager,
    get_shutdown_manager,
    request_shutdown,
)
from claude_task_master.core.state import (
    StateManager,
    StateNotFoundError,
    TaskOptions,
)
from claude_task_master.core.state_exceptions import RESUMABLE_STATUSES

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# Control Exceptions
# =============================================================================


class ControlError(Exception):
    """Base exception for control operation errors."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class ControlOperationNotAllowedError(ControlError):
    """Raised when a control operation is not allowed in the current state."""

    def __init__(
        self,
        operation: str,
        current_status: str,
        allowed_statuses: frozenset[str] | None = None,
    ):
        self.operation = operation
        self.current_status = current_status
        self.allowed_statuses = allowed_statuses

        if allowed_statuses:
            details = f"Current status: {current_status}. Allowed statuses: {', '.join(sorted(allowed_statuses))}"
        else:
            details = f"Current status: {current_status}"

        super().__init__(
            f"Cannot {operation} task in current state",
            details,
        )


class NoActiveTaskError(ControlError):
    """Raised when a control operation is attempted without an active task."""

    def __init__(self, operation: str):
        self.operation = operation
        super().__init__(
            f"Cannot {operation}: no active task found",
            "Initialize a task first using 'start' command.",
        )


# =============================================================================
# Control Result
# =============================================================================


@dataclass
class ControlResult:
    """Result of a control operation.

    Attributes:
        success: Whether the operation succeeded.
        operation: The operation that was performed.
        previous_status: The status before the operation.
        new_status: The status after the operation.
        message: Human-readable description of the result.
        details: Additional details about the operation.
    """

    success: bool
    operation: str
    previous_status: str | None
    new_status: str | None
    message: str
    details: dict[str, Any] | None = None


# =============================================================================
# Control Manager
# =============================================================================


class ControlManager:
    """Manages runtime control operations for task execution.

    This class provides methods for pausing, stopping, resuming, and updating
    configuration of running tasks. It coordinates with StateManager for
    state persistence and ShutdownManager for graceful shutdown handling.

    Attributes:
        state_manager: The StateManager instance for state operations.
        shutdown_manager: The ShutdownManager instance for shutdown coordination.
    """

    # Statuses that can be paused
    PAUSABLE_STATUSES = frozenset(["planning", "working"])

    # Statuses that can be resumed
    RESUMABLE_STATUSES = RESUMABLE_STATUSES

    # Statuses that can be stopped
    STOPPABLE_STATUSES = frozenset(["planning", "working", "blocked", "paused"])

    def __init__(
        self,
        state_manager: StateManager | None = None,
        shutdown_manager: ShutdownManager | None = None,
        state_dir: Path | None = None,
    ):
        """Initialize control manager.

        Args:
            state_manager: StateManager instance. If None, creates a new one.
            shutdown_manager: ShutdownManager instance. If None, uses global instance.
            state_dir: State directory path for StateManager. Only used if
                state_manager is None.
        """
        self.state_manager = state_manager or StateManager(state_dir)
        self.shutdown_manager = shutdown_manager or get_shutdown_manager()

    def _ensure_task_exists(self, operation: str) -> None:
        """Ensure an active task exists.

        Args:
            operation: The operation being attempted (for error message).

        Raises:
            NoActiveTaskError: If no task state exists.
        """
        if not self.state_manager.exists():
            raise NoActiveTaskError(operation)

    def pause(self, reason: str | None = None) -> ControlResult:
        """Pause a running task.

        Transitions the task from planning/working status to paused status.
        The task can be resumed later using the resume() method.

        Args:
            reason: Optional reason for pausing (stored in progress).

        Returns:
            ControlResult: The result of the pause operation.

        Raises:
            NoActiveTaskError: If no active task exists.
            ControlOperationNotAllowedError: If the task cannot be paused.
        """
        self._ensure_task_exists("pause")

        state = self.state_manager.load_state()
        previous_status = state.status

        # Check if task can be paused
        if previous_status not in self.PAUSABLE_STATUSES:
            raise ControlOperationNotAllowedError(
                "pause",
                previous_status,
                self.PAUSABLE_STATUSES,
            )

        # Transition to paused
        state.status = "paused"
        self.state_manager.save_state(state)

        # Append reason to progress if provided
        if reason:
            progress = self.state_manager.load_progress() or ""
            progress_update = f"\n\n## Paused\n\nReason: {reason}"
            self.state_manager.save_progress(progress + progress_update)

        return ControlResult(
            success=True,
            operation="pause",
            previous_status=previous_status,
            new_status="paused",
            message=f"Task paused successfully (was {previous_status})",
            details={"reason": reason} if reason else None,
        )

    def resume(self) -> ControlResult:
        """Resume a paused or blocked task.

        Transitions the task from paused/blocked status back to working status.

        Returns:
            ControlResult: The result of the resume operation.

        Raises:
            NoActiveTaskError: If no active task exists.
            ControlOperationNotAllowedError: If the task cannot be resumed.
        """
        self._ensure_task_exists("resume")

        state = self.state_manager.load_state()
        previous_status = state.status

        # Check if task can be resumed
        if previous_status not in self.RESUMABLE_STATUSES:
            raise ControlOperationNotAllowedError(
                "resume",
                previous_status,
                self.RESUMABLE_STATUSES,
            )

        # Transition to working
        state.status = "working"
        self.state_manager.save_state(state)

        # Append resume note to progress
        progress = self.state_manager.load_progress() or ""
        progress_update = f"\n\n## Resumed\n\nResumed from {previous_status} status."
        self.state_manager.save_progress(progress + progress_update)

        return ControlResult(
            success=True,
            operation="resume",
            previous_status=previous_status,
            new_status="working",
            message=f"Task resumed successfully (was {previous_status})",
        )

    def stop(self, reason: str | None = None, cleanup: bool = False) -> ControlResult:
        """Stop a running task.

        Transitions the task to stopped status and optionally triggers
        shutdown of any running processes.

        Args:
            reason: Optional reason for stopping.
            cleanup: If True, also cleanup state files (like failed state).

        Returns:
            ControlResult: The result of the stop operation.

        Raises:
            NoActiveTaskError: If no active task exists.
            ControlOperationNotAllowedError: If the task cannot be stopped.
        """
        self._ensure_task_exists("stop")

        state = self.state_manager.load_state()
        previous_status = state.status

        # Check if task can be stopped
        if previous_status not in self.STOPPABLE_STATUSES:
            raise ControlOperationNotAllowedError(
                "stop",
                previous_status,
                self.STOPPABLE_STATUSES,
            )

        # Request shutdown to stop any running processes
        shutdown_reason = reason or "stop requested"
        request_shutdown(shutdown_reason)

        # Transition to failed (which is the closest terminal state for a stopped task)
        # Note: A future PR will add a "stopped" status for cleaner semantics
        state.status = "failed"
        self.state_manager.save_state(state, validate_transition=False)

        # Append reason to progress if provided
        if reason:
            progress = self.state_manager.load_progress() or ""
            progress_update = f"\n\n## Stopped\n\nReason: {reason}"
            self.state_manager.save_progress(progress + progress_update)

        # Optionally cleanup state
        if cleanup:
            run_id = state.run_id
            self.state_manager.cleanup_on_success(run_id)

        return ControlResult(
            success=True,
            operation="stop",
            previous_status=previous_status,
            new_status="failed",
            message=f"Task stopped successfully (was {previous_status})",
            details={"reason": reason, "cleanup": cleanup},
        )

    def update_config(self, **kwargs: Any) -> ControlResult:
        """Update task configuration at runtime.

        Updates the TaskOptions stored in the task state. Only specified
        options are updated; others retain their current values.

        Supported options:
            - auto_merge: bool - Whether to auto-merge PRs
            - max_sessions: int | None - Maximum number of sessions
            - pause_on_pr: bool - Whether to pause on PR creation
            - enable_checkpointing: bool - Whether to enable checkpointing
            - log_level: str - Log level (quiet, normal, verbose)
            - log_format: str - Log format (text, json)
            - pr_per_task: bool - Whether to create PR per task

        Args:
            **kwargs: Configuration options to update.

        Returns:
            ControlResult: The result of the update operation.

        Raises:
            NoActiveTaskError: If no active task exists.
            ValueError: If invalid configuration options are provided.
        """
        self._ensure_task_exists("update_config")

        state = self.state_manager.load_state()

        # Get valid option names from TaskOptions
        valid_options = set(TaskOptions.model_fields.keys())
        provided_options = set(kwargs.keys())

        # Check for invalid options
        invalid_options = provided_options - valid_options
        if invalid_options:
            raise ValueError(
                f"Invalid configuration options: {', '.join(sorted(invalid_options))}. "
                f"Valid options: {', '.join(sorted(valid_options))}"
            )

        # Get current options as dict
        current_options = state.options.model_dump()
        updated_options: dict[str, Any] = {}

        # Apply updates
        for key, value in kwargs.items():
            if value is not None and current_options.get(key) != value:
                current_options[key] = value
                updated_options[key] = value

        # Update state with new options
        state.options = TaskOptions(**current_options)
        self.state_manager.save_state(state, validate_transition=False)

        if updated_options:
            message = f"Configuration updated: {', '.join(f'{k}={v}' for k, v in updated_options.items())}"
        else:
            message = "No configuration changes needed"

        return ControlResult(
            success=True,
            operation="update_config",
            previous_status=state.status,
            new_status=state.status,
            message=message,
            details={"updated": updated_options, "current": current_options},
        )

    def get_status(self) -> ControlResult:
        """Get current task status and information.

        Returns:
            ControlResult: Contains current task status and details.

        Raises:
            NoActiveTaskError: If no active task exists.
        """
        self._ensure_task_exists("get_status")

        state = self.state_manager.load_state()
        goal = self.state_manager.load_goal()
        plan = self.state_manager.load_plan()

        # Parse tasks from plan
        tasks = self.state_manager._parse_plan_tasks(plan or "")
        completed_tasks = sum(1 for _ in range(state.current_task_index))
        total_tasks = len(tasks)

        return ControlResult(
            success=True,
            operation="get_status",
            previous_status=state.status,
            new_status=state.status,
            message=f"Task is {state.status}",
            details={
                "goal": goal,
                "status": state.status,
                "workflow_stage": state.workflow_stage,
                "current_task_index": state.current_task_index,
                "session_count": state.session_count,
                "current_pr": state.current_pr,
                "model": state.model,
                "run_id": state.run_id,
                "created_at": state.created_at,
                "updated_at": state.updated_at,
                "options": state.options.model_dump(),
                "tasks": {
                    "completed": completed_tasks,
                    "total": total_tasks,
                    "progress": f"{completed_tasks}/{total_tasks}" if total_tasks else "No tasks",
                },
            },
        )

    def can_pause(self) -> bool:
        """Check if the current task can be paused.

        Returns:
            bool: True if the task can be paused, False otherwise.
        """
        if not self.state_manager.exists():
            return False
        try:
            state = self.state_manager.load_state()
            return state.status in self.PAUSABLE_STATUSES
        except StateNotFoundError:
            return False

    def can_resume(self) -> bool:
        """Check if the current task can be resumed.

        Returns:
            bool: True if the task can be resumed, False otherwise.
        """
        if not self.state_manager.exists():
            return False
        try:
            state = self.state_manager.load_state()
            return state.status in self.RESUMABLE_STATUSES
        except StateNotFoundError:
            return False

    def can_stop(self) -> bool:
        """Check if the current task can be stopped.

        Returns:
            bool: True if the task can be stopped, False otherwise.
        """
        if not self.state_manager.exists():
            return False
        try:
            state = self.state_manager.load_state()
            return state.status in self.STOPPABLE_STATUSES
        except StateNotFoundError:
            return False
