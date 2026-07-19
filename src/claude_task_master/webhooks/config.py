"""Webhook configuration model with Pydantic validation.

This module defines the WebhookConfig Pydantic model for configuring webhook
endpoints with support for:

- URL validation and HTTP/HTTPS schemes
- Optional shared secret for HMAC signature generation
- Event type filtering (subscribe to specific events)
- Retry and timeout configuration
- SSL verification toggle for development

The configuration can be loaded from JSON, environment variables, or constructed
programmatically.

Example:
    >>> from claude_task_master.webhooks import WebhookConfig, EventType
    >>> config = WebhookConfig(
    ...     url="https://example.com/webhook",
    ...     secret="my-shared-secret",
    ...     events=[EventType.TASK_COMPLETED, EventType.PR_CREATED],
    ... )
    >>> config.should_send_event(EventType.TASK_COMPLETED)
    True
    >>> config.should_send_event(EventType.SESSION_STARTED)
    False
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from claude_task_master.webhooks.events import EventType

# =============================================================================
# Default Configuration Values
# =============================================================================

DEFAULT_TIMEOUT = 30.0  # seconds
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0  # seconds
DEFAULT_VERIFY_SSL = True


# =============================================================================
# WebhookConfig Model
# =============================================================================


class WebhookConfig(BaseModel):
    """Configuration for a webhook endpoint.

    Defines all settings needed to configure a webhook destination including
    URL, authentication, event filtering, and delivery options.

    Attributes:
        url: The webhook endpoint URL (must be http:// or https://).
        secret: Optional shared secret for HMAC-SHA256 signature generation.
            When set, payloads will be signed and the signature included in
            the X-Webhook-Signature-256 header.
        events: List of event types to subscribe to. If empty or None,
            all events will be delivered.
        enabled: Whether this webhook is active. Disabled webhooks are skipped.
        timeout: Request timeout in seconds (1-300).
        max_retries: Maximum retry attempts for failed deliveries (0-10).
        retry_delay: Base delay between retries in seconds (0.1-60).
        verify_ssl: Whether to verify SSL certificates. Set to False for
            self-signed certificates in development.
        headers: Additional HTTP headers to include in webhook requests.
        name: Optional friendly name for this webhook configuration.
        description: Optional description of this webhook's purpose.

    Example:
        >>> config = WebhookConfig(
        ...     url="https://api.example.com/webhooks/task-master",
        ...     secret="whsec_abc123",
        ...     events=["task.completed", "pr.created"],
        ...     name="Production Webhook",
        ... )
    """

    url: str = Field(
        ...,
        min_length=1,
        description="Webhook endpoint URL (must be http:// or https://).",
    )
    secret: str | None = Field(
        default=None,
        description="Shared secret for HMAC-SHA256 signature generation.",
    )
    events: list[EventType] | None = Field(
        default=None,
        description="Event types to subscribe to. None or empty means all events.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this webhook is active.",
    )
    timeout: float = Field(
        default=DEFAULT_TIMEOUT,
        ge=1.0,
        le=300.0,
        description="Request timeout in seconds (1-300).",
    )
    max_retries: int = Field(
        default=DEFAULT_MAX_RETRIES,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed deliveries (0-10).",
    )
    retry_delay: float = Field(
        default=DEFAULT_RETRY_DELAY,
        ge=0.1,
        le=60.0,
        description="Base delay between retries in seconds (0.1-60).",
    )
    verify_ssl: bool = Field(
        default=DEFAULT_VERIFY_SSL,
        description="Whether to verify SSL certificates.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional HTTP headers to include in requests.",
    )
    name: str | None = Field(
        default=None,
        max_length=100,
        description="Optional friendly name for this webhook.",
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Optional description of this webhook's purpose.",
    )

    # =========================================================================
    # Validators
    # =========================================================================

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, v: str) -> str:
        """Ensure URL uses http:// or https:// scheme.

        Args:
            v: The URL value to validate.

        Returns:
            The validated URL.

        Raises:
            ValueError: If URL doesn't start with http:// or https://.
        """
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"Webhook URL must start with http:// or https://, got: {v}")
        return v

    @field_validator("events", mode="before")
    @classmethod
    def normalize_events(cls, v: Any) -> list[EventType] | None:
        """Normalize event types from strings or EventType enums.

        Accepts:
        - None (all events)
        - Empty list (all events)
        - List of strings like ["task.completed", "pr.created"]
        - List of EventType enums

        Args:
            v: The events value to normalize.

        Returns:
            List of EventType enums or None.

        Raises:
            ValueError: If any event type string is invalid.
        """
        if v is None:
            return None

        if isinstance(v, list):
            if len(v) == 0:
                return None

            normalized = []
            for event in v:
                if isinstance(event, EventType):
                    normalized.append(event)
                elif isinstance(event, str):
                    try:
                        normalized.append(EventType.from_string(event))
                    except ValueError as e:
                        raise ValueError(
                            f"Invalid event type: {event}. "
                            f"Valid types: {[e.value for e in EventType]}"
                        ) from e
                else:
                    raise ValueError(f"Event must be string or EventType, got: {type(event)}")
            return normalized

        raise ValueError(f"Events must be a list or None, got: {type(v)}")

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, v: dict[str, str]) -> dict[str, str]:
        """Validate that headers are string key-value pairs.

        Args:
            v: The headers dictionary to validate.

        Returns:
            The validated headers dictionary.

        Raises:
            ValueError: If any key or value is not a string.
        """
        for key, value in v.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(f"Header key and value must be strings: {key}={value}")
        return v

    @model_validator(mode="after")
    def validate_secret_with_https(self) -> WebhookConfig:
        """Warn if using secret with non-HTTPS URL.

        This is a soft validation that doesn't raise an error but could
        be used for logging warnings in production.

        Returns:
            The validated model instance.
        """
        # Note: We don't raise an error here to allow local development
        # with HTTP endpoints, but production usage should use HTTPS
        return self

    # =========================================================================
    # Event Filtering
    # =========================================================================

    def should_send_event(self, event_type: EventType | str) -> bool:
        """Check if this webhook should receive a specific event type.

        When no events are configured (None or empty), all events are sent.
        Otherwise, only events in the configured list are sent.

        Args:
            event_type: The event type to check (EventType enum or string).

        Returns:
            True if the event should be sent to this webhook.

        Example:
            >>> config = WebhookConfig(
            ...     url="https://example.com/webhook",
            ...     events=[EventType.TASK_COMPLETED],
            ... )
            >>> config.should_send_event(EventType.TASK_COMPLETED)
            True
            >>> config.should_send_event("task.failed")
            False
        """
        # Normalize string to EventType
        if isinstance(event_type, str):
            try:
                event_type = EventType.from_string(event_type)
            except ValueError:
                return False

        # None or empty list means all events
        if self.events is None or len(self.events) == 0:
            return True

        return event_type in self.events

    def get_subscribed_events(self) -> list[EventType]:
        """Get the list of subscribed event types.

        Returns:
            List of EventType enums this webhook is subscribed to.
            If no filter is set, returns all possible event types.

        Example:
            >>> config = WebhookConfig(
            ...     url="https://example.com/webhook",
            ...     events=[EventType.TASK_COMPLETED, EventType.PR_CREATED],
            ... )
            >>> config.get_subscribed_events()
            [<EventType.TASK_COMPLETED: 'task.completed'>, <EventType.PR_CREATED: 'pr.created'>]
        """
        if self.events is None or len(self.events) == 0:
            return list(EventType)
        return list(self.events)

    # =========================================================================
    # Factory Methods
    # =========================================================================

    @classmethod
    def from_url(
        cls,
        url: str,
        secret: str | None = None,
        events: list[str | EventType] | None = None,
    ) -> WebhookConfig:
        """Create a WebhookConfig from a URL with optional settings.

        Convenience factory method for simple webhook configuration.

        Args:
            url: The webhook endpoint URL.
            secret: Optional shared secret for signatures.
            events: Optional list of event types to subscribe to.

        Returns:
            Configured WebhookConfig instance.

        Example:
            >>> config = WebhookConfig.from_url(
            ...     "https://example.com/webhook",
            ...     secret="my-secret",
            ... )
        """
        return cls(url=url, secret=secret, events=events)  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebhookConfig:
        """Create a WebhookConfig from a dictionary.

        Useful for loading configuration from JSON files or environment.

        Args:
            data: Dictionary with webhook configuration.

        Returns:
            Configured WebhookConfig instance.

        Raises:
            ValidationError: If the data is invalid.

        Example:
            >>> config = WebhookConfig.from_dict({
            ...     "url": "https://example.com/webhook",
            ...     "secret": "my-secret",
            ...     "events": ["task.completed"],
            ... })
        """
        return cls(**data)

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self, exclude_secret: bool = False) -> dict[str, Any]:
        """Convert configuration to dictionary.

        Args:
            exclude_secret: If True, exclude the secret from output.
                Useful for logging or displaying configuration.

        Returns:
            Dictionary representation of the configuration.

        Example:
            >>> config = WebhookConfig(url="https://example.com", secret="abc")
            >>> config.to_dict(exclude_secret=True)
            {'url': 'https://example.com', 'secret': None, ...}
        """
        data = self.model_dump()

        # Convert EventType enums to strings
        if data.get("events"):
            data["events"] = [e.value if isinstance(e, EventType) else e for e in data["events"]]

        if exclude_secret:
            data["secret"] = None

        return data

    def to_safe_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary with secret masked.

        The secret is replaced with "***" if set, useful for logging.

        Returns:
            Dictionary with secret masked.
        """
        data = self.to_dict()
        if self.secret:
            data["secret"] = "***"
        return data

    # =========================================================================
    # Display
    # =========================================================================

    def __repr__(self) -> str:
        """Return a safe string representation (secret masked)."""
        events_str = f"[{', '.join(e.value for e in self.events)}]" if self.events else "all"
        return (
            f"WebhookConfig("
            f"url={self.url!r}, "
            f"has_secret={self.secret is not None}, "
            f"events={events_str}, "
            f"enabled={self.enabled})"
        )

    def __str__(self) -> str:
        """Return human-readable string representation."""
        events_count = len(self.events) if self.events else "all"
        status = "enabled" if self.enabled else "disabled"
        name_part = f" ({self.name})" if self.name else ""
        return f"Webhook{name_part}: {self.url} [{events_count} events, {status}]"


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "WebhookConfig",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_DELAY",
    "DEFAULT_VERIFY_SSL",
]
