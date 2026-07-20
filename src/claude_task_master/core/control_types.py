"""Types, exceptions, constants, and result dataclass for the control module."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# Bounded wait for an *other* live session to release the state directory before
# ``stop(cleanup=True)`` deletes it. A stop request written from one process can
# reach an orchestrator running in another that is still mid-cycle and holding
# the session lock; deleting the state dir underneath it races its next
# ``save_state`` (which would recreate a half-populated directory). Both bounds
# are env-configurable, mirroring the timeout idiom in ``agent_query``.
SESSION_RELEASE_TIMEOUT_SEC = float(os.environ.get("CLAUDETM_SESSION_RELEASE_TIMEOUT_SEC", "30"))
SESSION_RELEASE_POLL_INTERVAL_SEC = float(
    os.environ.get("CLAUDETM_SESSION_RELEASE_POLL_INTERVAL_SEC", "0.5")
)


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


__all__ = [
    "SESSION_RELEASE_TIMEOUT_SEC",
    "SESSION_RELEASE_POLL_INTERVAL_SEC",
    "ControlError",
    "ControlOperationNotAllowedError",
    "NoActiveTaskError",
    "ControlResult",
]
