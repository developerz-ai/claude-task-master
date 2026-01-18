"""Webhook event types and event data structures.

This module defines the event types that can be sent via webhooks and their
associated data structures. Events follow a consistent pattern with:

- Event type enum for type-safe event identification
- Base event class with common fields (timestamp, event_id, event_type)
- Specialized event classes for each event type with relevant data

Supported Event Types:
    - task.started: Task execution has begun
    - task.completed: Task completed successfully
    - task.failed: Task failed with error
    - pr.created: Pull request was created
    - pr.merged: Pull request was merged
    - session.started: Work session has begun
    - session.completed: Work session completed

Example:
    >>> from claude_task_master.webhooks.events import (
    ...     EventType,
    ...     TaskStartedEvent,
    ...     create_event,
    ... )
    >>>
    >>> # Create event using helper function
    >>> event = create_event(
    ...     EventType.TASK_STARTED,
    ...     task_index=1,
    ...     task_description="Implement feature X",
    ... )
    >>> event.to_dict()
    {'event_type': 'task.started', 'event_id': '...', 'timestamp': '...', ...}
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

# =============================================================================
# Event Type Enum
# =============================================================================


class EventType(str, Enum):
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
    """

    # Task lifecycle events
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # Pull request events
    PR_CREATED = "pr.created"
    PR_MERGED = "pr.merged"

    # Session events
    SESSION_STARTED = "session.started"
    SESSION_COMPLETED = "session.completed"

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


# =============================================================================
# Base Event Class
# =============================================================================


def _generate_event_id() -> str:
    """Generate a unique event ID.

    Returns:
        UUID4 string for event identification.
    """
    return str(uuid.uuid4())


def _current_timestamp() -> str:
    """Get current UTC timestamp in ISO format.

    Returns:
        ISO 8601 formatted timestamp string with timezone.
    """
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WebhookEvent:
    """Base class for all webhook events.

    All webhook events share common metadata fields for identification
    and tracking. Specialized event classes inherit from this and add
    event-specific data.

    Note: This is an abstract base class. Use the specific event classes
    (TaskStartedEvent, PRCreatedEvent, etc.) or the create_event() factory.

    Attributes:
        event_type: The type of event (from EventType enum). Set automatically
            by subclasses in __post_init__.
        event_id: Unique identifier for this event instance.
        timestamp: When the event occurred (ISO 8601 format).
        run_id: The orchestrator run ID (optional, for correlation).
    """

    # Note: event_type is set by subclasses in __post_init__
    # We use a placeholder that will be overwritten
    event_type: EventType = field(default=EventType.TASK_STARTED)
    event_id: str = field(default_factory=_generate_event_id)
    timestamp: str = field(default_factory=_current_timestamp)
    run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for JSON serialization.

        Returns:
            Dictionary representation of the event suitable for
            JSON serialization and webhook delivery.
        """
        return {
            "event_type": str(self.event_type),
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
        }

    def __post_init__(self) -> None:
        """Validate and normalize event data after initialization."""
        # Ensure event_type is an EventType instance
        if isinstance(self.event_type, str):
            self.event_type = EventType.from_string(self.event_type)


# =============================================================================
# Task Events
# =============================================================================


@dataclass
class TaskStartedEvent(WebhookEvent):
    """Event emitted when a task begins execution.

    Attributes:
        task_index: Zero-based index of the task in the plan.
        task_description: Human-readable description of the task.
        total_tasks: Total number of tasks in the plan.
        branch: Git branch name being used (optional).
        pr_group: PR group name if task is part of a group (optional).
    """

    task_index: int = 0
    task_description: str = ""
    total_tasks: int = 0
    branch: str | None = None
    pr_group: str | None = None

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.TASK_STARTED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus task-specific data.
        """
        data = super().to_dict()
        data.update(
            {
                "task_index": self.task_index,
                "task_description": self.task_description,
                "total_tasks": self.total_tasks,
                "branch": self.branch,
                "pr_group": self.pr_group,
            }
        )
        return data


@dataclass
class TaskCompletedEvent(WebhookEvent):
    """Event emitted when a task completes successfully.

    Attributes:
        task_index: Zero-based index of the completed task.
        task_description: Human-readable description of the task.
        total_tasks: Total number of tasks in the plan.
        completed_tasks: Number of tasks completed so far.
        duration_seconds: Time taken to complete the task.
        commit_hash: Git commit hash if changes were committed (optional).
        branch: Git branch name (optional).
        pr_group: PR group name if task is part of a group (optional).
    """

    task_index: int = 0
    task_description: str = ""
    total_tasks: int = 0
    completed_tasks: int = 0
    duration_seconds: float | None = None
    commit_hash: str | None = None
    branch: str | None = None
    pr_group: str | None = None

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.TASK_COMPLETED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus task completion data.
        """
        data = super().to_dict()
        data.update(
            {
                "task_index": self.task_index,
                "task_description": self.task_description,
                "total_tasks": self.total_tasks,
                "completed_tasks": self.completed_tasks,
                "duration_seconds": self.duration_seconds,
                "commit_hash": self.commit_hash,
                "branch": self.branch,
                "pr_group": self.pr_group,
            }
        )
        return data


@dataclass
class TaskFailedEvent(WebhookEvent):
    """Event emitted when a task fails with an error.

    Attributes:
        task_index: Zero-based index of the failed task.
        task_description: Human-readable description of the task.
        error_message: Description of the failure.
        error_type: Type/classification of the error (optional).
        duration_seconds: Time elapsed before failure (optional).
        branch: Git branch name (optional).
        pr_group: PR group name if task is part of a group (optional).
        recoverable: Whether the error is potentially recoverable.
    """

    task_index: int = 0
    task_description: str = ""
    error_message: str = ""
    error_type: str | None = None
    duration_seconds: float | None = None
    branch: str | None = None
    pr_group: str | None = None
    recoverable: bool = True

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.TASK_FAILED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus failure data.
        """
        data = super().to_dict()
        data.update(
            {
                "task_index": self.task_index,
                "task_description": self.task_description,
                "error_message": self.error_message,
                "error_type": self.error_type,
                "duration_seconds": self.duration_seconds,
                "branch": self.branch,
                "pr_group": self.pr_group,
                "recoverable": self.recoverable,
            }
        )
        return data


# =============================================================================
# Pull Request Events
# =============================================================================


@dataclass
class PRCreatedEvent(WebhookEvent):
    """Event emitted when a pull request is created.

    Attributes:
        pr_number: The pull request number.
        pr_url: URL to the pull request.
        pr_title: Title of the pull request.
        branch: Source branch name.
        base_branch: Target branch name.
        tasks_included: Number of tasks included in this PR.
        pr_group: PR group name (optional).
        repository: Repository name (owner/repo format, optional).
    """

    pr_number: int = 0
    pr_url: str = ""
    pr_title: str = ""
    branch: str = ""
    base_branch: str = "main"
    tasks_included: int = 0
    pr_group: str | None = None
    repository: str | None = None

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.PR_CREATED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus PR creation data.
        """
        data = super().to_dict()
        data.update(
            {
                "pr_number": self.pr_number,
                "pr_url": self.pr_url,
                "pr_title": self.pr_title,
                "branch": self.branch,
                "base_branch": self.base_branch,
                "tasks_included": self.tasks_included,
                "pr_group": self.pr_group,
                "repository": self.repository,
            }
        )
        return data


@dataclass
class PRMergedEvent(WebhookEvent):
    """Event emitted when a pull request is merged.

    Attributes:
        pr_number: The pull request number.
        pr_url: URL to the pull request.
        pr_title: Title of the pull request.
        branch: Source branch that was merged.
        base_branch: Target branch that received the merge.
        merge_commit_hash: The merge commit hash.
        merged_at: When the PR was merged (ISO 8601 format).
        pr_group: PR group name (optional).
        repository: Repository name (owner/repo format, optional).
        auto_merged: Whether this was an auto-merge.
    """

    pr_number: int = 0
    pr_url: str = ""
    pr_title: str = ""
    branch: str = ""
    base_branch: str = "main"
    merge_commit_hash: str | None = None
    merged_at: str | None = None
    pr_group: str | None = None
    repository: str | None = None
    auto_merged: bool = False

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.PR_MERGED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus PR merge data.
        """
        data = super().to_dict()
        data.update(
            {
                "pr_number": self.pr_number,
                "pr_url": self.pr_url,
                "pr_title": self.pr_title,
                "branch": self.branch,
                "base_branch": self.base_branch,
                "merge_commit_hash": self.merge_commit_hash,
                "merged_at": self.merged_at,
                "pr_group": self.pr_group,
                "repository": self.repository,
                "auto_merged": self.auto_merged,
            }
        )
        return data


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
# Event Factory
# =============================================================================


# Mapping of event types to event classes
_EVENT_CLASSES: dict[EventType, type[WebhookEvent]] = {
    EventType.TASK_STARTED: TaskStartedEvent,
    EventType.TASK_COMPLETED: TaskCompletedEvent,
    EventType.TASK_FAILED: TaskFailedEvent,
    EventType.PR_CREATED: PRCreatedEvent,
    EventType.PR_MERGED: PRMergedEvent,
    EventType.SESSION_STARTED: SessionStartedEvent,
    EventType.SESSION_COMPLETED: SessionCompletedEvent,
}


def create_event(event_type: EventType | str, **kwargs: Any) -> WebhookEvent:
    """Create a webhook event of the specified type.

    Factory function that creates the appropriate event class instance
    based on the event type. This is the recommended way to create events
    programmatically.

    Args:
        event_type: The type of event to create (EventType enum or string).
        **kwargs: Event-specific data to include (varies by event type).

    Returns:
        A WebhookEvent subclass instance appropriate for the event type.

    Raises:
        ValueError: If the event type is unknown.

    Example:
        >>> event = create_event(
        ...     EventType.TASK_COMPLETED,
        ...     task_index=0,
        ...     task_description="Implement feature",
        ...     run_id="abc123",
        ... )
        >>> event.event_type
        <EventType.TASK_COMPLETED: 'task.completed'>
    """
    # Normalize event type
    if isinstance(event_type, str):
        event_type = EventType.from_string(event_type)

    # Get the appropriate event class
    event_class = _EVENT_CLASSES.get(event_type)
    if event_class is None:
        raise ValueError(f"Unknown event type: {event_type}")

    # Create and return the event
    return event_class(**kwargs)


def get_event_class(event_type: EventType | str) -> type[WebhookEvent]:
    """Get the event class for a given event type.

    Args:
        event_type: The event type to look up.

    Returns:
        The WebhookEvent subclass for the event type.

    Raises:
        ValueError: If the event type is unknown.
    """
    if isinstance(event_type, str):
        event_type = EventType.from_string(event_type)

    event_class = _EVENT_CLASSES.get(event_type)
    if event_class is None:
        raise ValueError(f"Unknown event type: {event_type}")

    return event_class


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Enum
    "EventType",
    # Base class
    "WebhookEvent",
    # Task events
    "TaskStartedEvent",
    "TaskCompletedEvent",
    "TaskFailedEvent",
    # PR events
    "PRCreatedEvent",
    "PRMergedEvent",
    # Session events
    "SessionStartedEvent",
    "SessionCompletedEvent",
    # Factory functions
    "create_event",
    "get_event_class",
]
