"""Webhook event type enum and helpers.

Defines the EventType StrEnum used to identify every webhook event
emitted by the task orchestration system.
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    """Webhook event types.

    Each event type corresponds to a specific lifecycle event in the
    task orchestration system.

    Attributes:
        TASK_STARTED: Emitted when a task begins execution.
        TASK_COMPLETED: Emitted when a task completes successfully.
        TASK_FAILED: Emitted when a task fails with an error.
        PR_CREATED: Emitted when a pull request is created.
        PR_MERGED: Emitted when a pull request is merged.
        SESSION_STARTED: Emitted when a work session begins.
        SESSION_COMPLETED: Emitted when a work session completes.
        CI_PASSED: Emitted when CI checks pass.
        CI_FAILED: Emitted when CI checks fail.
        PLAN_UPDATED: Emitted when the plan is updated via mailbox or resume.
        STATUS_CHANGED: Emitted when orchestrator status changes.
        RUN_STARTED: Emitted when orchestrator run starts.
        RUN_COMPLETED: Emitted when orchestrator run completes.
    """

    # Task lifecycle events
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # Pull request events
    PR_CREATED = "pr.created"
    PR_MERGED = "pr.merged"

    # CI events
    CI_PASSED = "ci.passed"
    CI_FAILED = "ci.failed"

    # Session events
    SESSION_STARTED = "session.started"
    SESSION_COMPLETED = "session.completed"

    # Plan events
    PLAN_UPDATED = "plan.updated"

    # Orchestrator lifecycle events
    STATUS_CHANGED = "status.changed"
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"

    @classmethod
    def from_string(cls, value: str) -> EventType:
        """Convert a string to an EventType.

        Args:
            value: The event type string (e.g., "task.started").

        Returns:
            The corresponding EventType enum value.

        Raises:
            ValueError: If the string doesn't match any event type.
        """
        for event_type in cls:
            if event_type.value == value:
                return event_type
        raise ValueError(f"Unknown event type: {value}")

    def __str__(self) -> str:
        """Return the event type string value."""
        return self.value


__all__ = ["EventType"]
