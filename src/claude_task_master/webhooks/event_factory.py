"""Webhook event factory — create_event() and get_event_class() helpers.

Maps EventType values to their concrete dataclass implementations and
exposes factory functions for programmatic event creation.
"""

from __future__ import annotations

from typing import Any

from .event_base import WebhookEvent
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
from .event_types import EventType

# Mapping of event types to event classes
_EVENT_CLASSES: dict[EventType, type[WebhookEvent]] = {
    EventType.TASK_STARTED: TaskStartedEvent,
    EventType.TASK_COMPLETED: TaskCompletedEvent,
    EventType.TASK_FAILED: TaskFailedEvent,
    EventType.PR_CREATED: PRCreatedEvent,
    EventType.PR_MERGED: PRMergedEvent,
    EventType.SESSION_STARTED: SessionStartedEvent,
    EventType.SESSION_COMPLETED: SessionCompletedEvent,
    EventType.CI_PASSED: CIPassedEvent,
    EventType.CI_FAILED: CIFailedEvent,
    EventType.PLAN_UPDATED: PlanUpdatedEvent,
    EventType.STATUS_CHANGED: StatusChangedEvent,
    EventType.RUN_STARTED: RunStartedEvent,
    EventType.RUN_COMPLETED: RunCompletedEvent,
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


__all__ = [
    "_EVENT_CLASSES",
    "create_event",
    "get_event_class",
]
