"""Concrete webhook event dataclasses — session, plan, and lifecycle events.

Contains the event dataclasses for:
  - Session lifecycle: SessionStartedEvent, SessionCompletedEvent
  - Plan updates: PlanUpdatedEvent
  - Orchestrator lifecycle: StatusChangedEvent, RunStartedEvent, RunCompletedEvent
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .event_base import WebhookEvent
from .event_types import EventType

# =============================================================================
# Session Events
# =============================================================================


@dataclass
class SessionStartedEvent(WebhookEvent):
    """Event emitted when a work session begins.

    A work session is a single Claude Agent SDK query with its own
    context and tool execution. Multiple sessions may be needed to
    complete a task.

    Attributes:
        session_number: Current session number (1-indexed).
        max_sessions: Maximum allowed sessions (optional, None if unlimited).
        task_index: Index of the task being worked on.
        task_description: Description of the current task.
        phase: Current phase (planning, working, verification).
    """

    session_number: int = 1
    max_sessions: int | None = None
    task_index: int = 0
    task_description: str = ""
    phase: str = "working"

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.SESSION_STARTED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus session start data.
        """
        data = super().to_dict()
        data.update(
            {
                "session_number": self.session_number,
                "max_sessions": self.max_sessions,
                "task_index": self.task_index,
                "task_description": self.task_description,
                "phase": self.phase,
            }
        )
        return data


@dataclass
class SessionCompletedEvent(WebhookEvent):
    """Event emitted when a work session completes.

    Attributes:
        session_number: Session number that completed.
        max_sessions: Maximum allowed sessions.
        task_index: Index of the task being worked on.
        task_description: Description of the task.
        phase: Phase that was completed.
        duration_seconds: Duration of the session.
        result: Outcome of the session (success, blocked, etc.).
        tools_used: Number of tool invocations in this session.
        tokens_used: Total tokens used (optional).
    """

    session_number: int = 1
    max_sessions: int | None = None
    task_index: int = 0
    task_description: str = ""
    phase: str = "working"
    duration_seconds: float | None = None
    result: str = "success"
    tools_used: int = 0
    tokens_used: int | None = None

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.SESSION_COMPLETED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus session completion data.
        """
        data = super().to_dict()
        data.update(
            {
                "session_number": self.session_number,
                "max_sessions": self.max_sessions,
                "task_index": self.task_index,
                "task_description": self.task_description,
                "phase": self.phase,
                "duration_seconds": self.duration_seconds,
                "result": self.result,
                "tools_used": self.tools_used,
                "tokens_used": self.tokens_used,
            }
        )
        return data


# =============================================================================
# Plan Events
# =============================================================================


@dataclass
class PlanUpdatedEvent(WebhookEvent):
    """Event emitted when the plan is updated via mailbox or resume.

    Attributes:
        update_source: Source of the update ("mailbox", "resume", "manual").
        message: The update message that triggered the change (optional).
        tasks_added: Number of new tasks added to the plan.
        tasks_modified: Number of existing tasks modified.
        tasks_removed: Number of tasks removed from the plan.
        total_tasks: Total number of tasks after update.
        completed_tasks: Number of tasks already completed.
    """

    update_source: str = "manual"
    message: str | None = None
    tasks_added: int = 0
    tasks_modified: int = 0
    tasks_removed: int = 0
    total_tasks: int = 0
    completed_tasks: int = 0

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.PLAN_UPDATED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus plan update data.
        """
        data = super().to_dict()
        data.update(
            {
                "update_source": self.update_source,
                "message": self.message,
                "tasks_added": self.tasks_added,
                "tasks_modified": self.tasks_modified,
                "tasks_removed": self.tasks_removed,
                "total_tasks": self.total_tasks,
                "completed_tasks": self.completed_tasks,
            }
        )
        return data


# =============================================================================
# Orchestrator Lifecycle Events
# =============================================================================


@dataclass
class StatusChangedEvent(WebhookEvent):
    """Event emitted when the orchestrator status changes.

    Attributes:
        previous_status: The status before the change.
        new_status: The status after the change.
        reason: Reason for the status change (optional).
        task_index: Current task index at time of change (optional).
        session_number: Current session number at time of change (optional).
    """

    previous_status: str = ""
    new_status: str = ""
    reason: str | None = None
    task_index: int | None = None
    session_number: int | None = None

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.STATUS_CHANGED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus status change data.
        """
        data = super().to_dict()
        data.update(
            {
                "previous_status": self.previous_status,
                "new_status": self.new_status,
                "reason": self.reason,
                "task_index": self.task_index,
                "session_number": self.session_number,
            }
        )
        return data


@dataclass
class RunStartedEvent(WebhookEvent):
    """Event emitted when an orchestrator run starts.

    Attributes:
        goal: The user's goal for this run.
        working_directory: The working directory for the run.
        max_sessions: Maximum number of sessions allowed.
        auto_merge: Whether auto-merge is enabled.
        pr_mode: PR creation mode ("per-task", "per-group", etc.).
        resumed: Whether this is a resumed run.
    """

    goal: str = ""
    working_directory: str = ""
    max_sessions: int | None = None
    auto_merge: bool = False
    pr_mode: str = "per-group"
    resumed: bool = False

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.RUN_STARTED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus run start data.
        """
        data = super().to_dict()
        data.update(
            {
                "goal": self.goal,
                "working_directory": self.working_directory,
                "max_sessions": self.max_sessions,
                "auto_merge": self.auto_merge,
                "pr_mode": self.pr_mode,
                "resumed": self.resumed,
            }
        )
        return data


@dataclass
class RunCompletedEvent(WebhookEvent):
    """Event emitted when an orchestrator run completes.

    Attributes:
        goal: The user's goal for this run.
        result: Outcome of the run ("success", "blocked", "failed", "interrupted").
        exit_code: Exit code of the run (0=success, 1=blocked, 2=interrupted).
        total_tasks: Total number of tasks in the plan.
        completed_tasks: Number of tasks completed.
        total_sessions: Total number of sessions used.
        duration_seconds: Total duration of the run.
        prs_created: Number of PRs created during the run.
        prs_merged: Number of PRs merged during the run.
        final_status: Final orchestrator status.
        error_message: Error message if run failed (optional).
    """

    goal: str = ""
    result: str = "success"
    exit_code: int = 0
    total_tasks: int = 0
    completed_tasks: int = 0
    total_sessions: int = 0
    duration_seconds: float | None = None
    prs_created: int = 0
    prs_merged: int = 0
    final_status: str = ""
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.RUN_COMPLETED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus run completion data.
        """
        data = super().to_dict()
        data.update(
            {
                "goal": self.goal,
                "result": self.result,
                "exit_code": self.exit_code,
                "total_tasks": self.total_tasks,
                "completed_tasks": self.completed_tasks,
                "total_sessions": self.total_sessions,
                "duration_seconds": self.duration_seconds,
                "prs_created": self.prs_created,
                "prs_merged": self.prs_merged,
                "final_status": self.final_status,
                "error_message": self.error_message,
            }
        )
        return data


__all__ = [
    "SessionStartedEvent",
    "SessionCompletedEvent",
    "PlanUpdatedEvent",
    "StatusChangedEvent",
    "RunStartedEvent",
    "RunCompletedEvent",
]
