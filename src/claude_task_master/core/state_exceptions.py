"""Exception classes for State Manager operations.

This module contains all custom exception classes used by the StateManager
for handling various error conditions like missing state, corrupted files,
validation failures, permission issues, and lock errors.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


# =============================================================================
# Valid State Transitions (needed by InvalidStateTransitionError)
# =============================================================================

# Define valid status values
VALID_STATUSES = frozenset(["planning", "working", "blocked", "paused", "success", "failed"])

# Define workflow stages for PR lifecycle
WORKFLOW_STAGES = frozenset(
    [
        "working",  # Implementing tasks
        "pr_created",  # PR created, waiting for CI/reviews
        "waiting_ci",  # Polling CI status
        "ci_failed",  # CI failed, needs fixes
        "waiting_reviews",  # Waiting for code reviews
        "addressing_reviews",  # Working on review feedback
        "ready_to_merge",  # All checks passed, ready to merge
        "merged",  # PR merged, ready for next task
    ]
)

# Define terminal statuses (cannot be resumed)
TERMINAL_STATUSES = frozenset(["success", "failed"])

# Define resumable statuses (can resume execution)
RESUMABLE_STATUSES = frozenset(["paused", "working", "blocked"])

# Define valid state transitions
VALID_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "planning": frozenset(["working", "failed", "paused"]),
    "working": frozenset(
        ["blocked", "success", "failed", "working", "paused"]
    ),  # working -> working for retries
    "blocked": frozenset(["working", "failed", "paused"]),
    "paused": frozenset(["working", "failed"]),  # Can resume or fail from paused
    "success": frozenset([]),  # Terminal state
    "failed": frozenset([]),  # Terminal state
}


# =============================================================================
# Custom Exception Classes
# =============================================================================


class StateError(Exception):
    """Base exception for all state-related errors."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class StateNotFoundError(StateError):
    """Raised when state file is not found."""

    def __init__(self, path: Path):
        super().__init__(
            f"No task state found at {path}",
            "Please run 'start' first to initialize a new task.",
        )
        self.path = path


class StateCorruptedError(StateError):
    """Raised when state file is corrupted and cannot be parsed."""

    def __init__(self, path: Path, reason: str, recoverable: bool = True):
        self.path = path
        self.recoverable = recoverable
        details = f"Parse error: {reason}"
        if recoverable:
            details += " A backup will be created and state may be recoverable."
        super().__init__(f"State file at {path} is corrupted", details)


class StateValidationError(StateError):
    """Raised when state data fails validation."""

    def __init__(
        self,
        message: str,
        missing_fields: list[str] | None = None,
        invalid_fields: list[str] | None = None,
    ):
        self.missing_fields = missing_fields or []
        self.invalid_fields = invalid_fields or []

        details_parts = []
        if missing_fields:
            details_parts.append(f"Missing required fields: {', '.join(missing_fields)}")
        if invalid_fields:
            details_parts.append(f"Invalid fields: {'; '.join(invalid_fields)}")

        super().__init__(message, " | ".join(details_parts) if details_parts else None)


class InvalidStateTransitionError(StateError):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, current_status: str, new_status: str):
        self.current_status = current_status
        self.new_status = new_status
        super().__init__(
            f"Invalid state transition from '{current_status}' to '{new_status}'",
            f"Valid transitions from '{current_status}': {', '.join(VALID_TRANSITIONS.get(current_status, frozenset()))}",
        )


class StatePermissionError(StateError):
    """Raised when there are permission issues accessing state files."""

    def __init__(self, path: Path, operation: str, original_error: Exception):
        self.path = path
        self.operation = operation
        self.original_error = original_error
        super().__init__(
            f"Permission denied when {operation} state file at {path}",
            f"Check file permissions. Original error: {original_error}",
        )


class StateLockError(StateError):
    """Raised when state file cannot be locked for access."""

    def __init__(self, path: Path, timeout: float):
        self.path = path
        self.timeout = timeout
        super().__init__(
            f"Could not acquire lock on state file at {path}",
            f"Another process may be accessing this file. Timeout after {timeout} seconds.",
        )


class StateResumeValidationError(StateError):
    """Raised when state is not valid for resumption."""

    def __init__(
        self,
        reason: str,
        status: str | None = None,
        current_task_index: int | None = None,
        total_tasks: int | None = None,
        suggestion: str | None = None,
    ):
        self.reason = reason
        self.status = status
        self.current_task_index = current_task_index
        self.total_tasks = total_tasks
        self.suggestion = suggestion

        details_parts = []
        if status:
            details_parts.append(f"Current status: {status}")
        if current_task_index is not None:
            details_parts.append(f"Task index: {current_task_index}")
        if total_tasks is not None:
            details_parts.append(f"Total tasks: {total_tasks}")
        if suggestion:
            details_parts.append(f"Suggestion: {suggestion}")

        super().__init__(
            f"Cannot resume task: {reason}",
            " | ".join(details_parts) if details_parts else None,
        )
