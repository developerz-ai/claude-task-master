"""Webhook event types and event data structures.

This module defines the event types that can be sent via webhooks and their
associated data structures. Events follow a consistent pattern with:

- Event type enum for type-safe event identification
- Base event class with common fields (timestamp, event_id, event_type)
- Specialized event classes for each event type with relevant data
- Factory functions for creating events programmatically

Supported Event Types:
    - task.started: Task execution has begun
    - task.completed: Task completed successfully
    - task.failed: Task failed with error
    - pr.created: Pull request was created
    - pr.merged: Pull request was merged
    - session.started: Work session has begun
    - session.completed: Work session completed
    - ci.passed: CI checks passed
    - ci.failed: CI checks failed
    - plan.updated: Plan was updated (via mailbox or resume)
    - status.changed: Orchestrator status changed
    - run.started: Orchestrator run started
    - run.completed: Orchestrator run completed

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

# Re-export everything so existing imports continue to work unchanged.
from .event_base import WebhookEvent, _current_timestamp, _generate_event_id
from .event_classes import (
    CIFailedEvent,
    CIPassedEvent,
    PRCreatedEvent,
    PRMergedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskStartedEvent,
)
from .event_classes_lifecycle import (
    PlanUpdatedEvent,
    RunCompletedEvent,
    RunStartedEvent,
    SessionCompletedEvent,
    SessionStartedEvent,
    StatusChangedEvent,
)
from .event_factory import _EVENT_CLASSES, create_event, get_event_class
from .event_types import EventType

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
    # CI events
    "CIPassedEvent",
    "CIFailedEvent",
    # Session events
    "SessionStartedEvent",
    "SessionCompletedEvent",
    # Plan events
    "PlanUpdatedEvent",
    # Orchestrator lifecycle events
    "StatusChangedEvent",
    "RunStartedEvent",
    "RunCompletedEvent",
    # Factory functions
    "create_event",
    "get_event_class",
    # Internal helpers (re-exported for backward compatibility)
    "_generate_event_id",
    "_current_timestamp",
    "_EVENT_CLASSES",
]
