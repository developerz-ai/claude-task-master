"""Base webhook event class and timestamp/ID helpers.

Provides the abstract WebhookEvent dataclass that all concrete event
classes inherit from, plus the helper functions for generating unique
event IDs and UTC timestamps.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .event_types import EventType


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
    return datetime.now(UTC).isoformat()


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

    # ``event_type`` is abstract: it is NOT an __init__ parameter and has no
    # default. Every concrete subclass assigns it in its own __post_init__ before
    # calling super().__post_init__(). Instantiating the base directly (or a
    # subclass that forgets to set it) leaves it unset, which __post_init__ turns
    # into a loud TypeError rather than silently mislabelling the event.
    event_type: EventType = field(init=False)
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
        """Validate and normalize event data after initialization.

        Raises:
            TypeError: If ``event_type`` was never assigned — i.e. ``WebhookEvent``
                was instantiated directly, or a subclass failed to set it. The
                base class is abstract and must not produce an untyped event.
        """
        # Concrete subclasses assign event_type before calling super(); if it is
        # still unset the caller used the abstract base incorrectly.
        event_type = getattr(self, "event_type", None)
        if event_type is None:
            raise TypeError(
                "WebhookEvent is abstract: event_type must be set by a concrete "
                "event subclass or via create_event(); do not instantiate "
                "WebhookEvent directly."
            )
        # Ensure event_type is an EventType instance.
        if isinstance(event_type, str):
            self.event_type = EventType.from_string(event_type)


__all__ = [
    "WebhookEvent",
    "_generate_event_id",
    "_current_timestamp",
]
