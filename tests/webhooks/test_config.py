"""Tests for webhook configuration module.

Tests cover:
- WebhookConfig Pydantic model validation
- URL scheme validation
- Event type filtering and normalization
- Factory methods and serialization
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from claude_task_master.webhooks.config import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    DEFAULT_TIMEOUT,
    DEFAULT_VERIFY_SSL,
    WebhookConfig,
)
from claude_task_master.webhooks.events import EventType

# =============================================================================
# Test: WebhookConfig Initialization
# =============================================================================


class TestWebhookConfigInit:
    """Tests for WebhookConfig initialization and defaults."""

    def test_init_with_url_only(self) -> None:
        """Test config with just URL uses defaults."""
        config = WebhookConfig(url="https://example.com/webhook")

        assert config.url == "https://example.com/webhook"
        assert config.secret is None
        assert config.events is None
        assert config.enabled is True
        assert config.timeout == DEFAULT_TIMEOUT
        assert config.max_retries == DEFAULT_MAX_RETRIES
        assert config.retry_delay == DEFAULT_RETRY_DELAY
        assert config.verify_ssl == DEFAULT_VERIFY_SSL
        assert config.headers == {}
        assert config.name is None
        assert config.description is None

    def test_init_with_all_parameters(self) -> None:
        """Test config with all parameters specified."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            secret="my-secret",
            events=[EventType.TASK_COMPLETED, EventType.PR_CREATED],
            enabled=False,
            timeout=60.0,
            max_retries=5,
            retry_delay=2.0,
            verify_ssl=False,
            headers={"X-Custom": "value"},
            name="Production Webhook",
            description="Sends task events to production",
        )

        assert config.url == "https://example.com/webhook"
        assert config.secret == "my-secret"
        assert config.events == [EventType.TASK_COMPLETED, EventType.PR_CREATED]
        assert config.enabled is False
        assert config.timeout == 60.0
        assert config.max_retries == 5
        assert config.retry_delay == 2.0
        assert config.verify_ssl is False
        assert config.headers == {"X-Custom": "value"}
        assert config.name == "Production Webhook"
        assert config.description == "Sends task events to production"


# =============================================================================
# Test: URL Validation
# =============================================================================


class TestURLValidation:
    """Tests for URL scheme validation."""

    def test_accepts_https_url(self) -> None:
        """Test that HTTPS URLs are accepted."""
        config = WebhookConfig(url="https://secure.example.com/webhook")
        assert config.url == "https://secure.example.com/webhook"

    def test_accepts_http_url(self) -> None:
        """Test that HTTP URLs are accepted (for development)."""
        config = WebhookConfig(url="http://localhost:8080/webhook")
        assert config.url == "http://localhost:8080/webhook"

    def test_rejects_empty_url(self) -> None:
        """Test that empty URL is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            WebhookConfig(url="")
        assert (
            "min_length" in str(exc_info.value).lower()
            or "at least 1" in str(exc_info.value).lower()
        )

    def test_rejects_ftp_url(self) -> None:
        """Test that FTP URLs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            WebhookConfig(url="ftp://example.com/webhook")
        assert "http" in str(exc_info.value).lower()

    def test_rejects_file_url(self) -> None:
        """Test that file:// URLs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            WebhookConfig(url="file:///path/to/file")
        assert "http" in str(exc_info.value).lower()

    def test_rejects_url_without_scheme(self) -> None:
        """Test that URLs without scheme are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            WebhookConfig(url="example.com/webhook")
        assert "http" in str(exc_info.value).lower()


# =============================================================================
# Test: Event Type Normalization
# =============================================================================


class TestEventNormalization:
    """Tests for event type normalization and validation."""

    def test_accepts_event_type_enums(self) -> None:
        """Test that EventType enums are accepted."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            events=[EventType.TASK_STARTED, EventType.TASK_COMPLETED],
        )

        assert config.events == [EventType.TASK_STARTED, EventType.TASK_COMPLETED]

    def test_accepts_event_type_strings(self) -> None:
        """Test that event type strings are normalized to enums."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            events=["task.started", "task.completed"],  # type: ignore[list-item]
        )

        assert config.events == [EventType.TASK_STARTED, EventType.TASK_COMPLETED]

    def test_accepts_mixed_event_types(self) -> None:
        """Test that mixed strings and enums are accepted."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            events=["task.started", EventType.PR_CREATED],  # type: ignore[list-item]
        )

        assert config.events == [EventType.TASK_STARTED, EventType.PR_CREATED]

    def test_none_events_means_all(self) -> None:
        """Test that None events means all events."""
        config = WebhookConfig(url="https://example.com/webhook", events=None)
        assert config.events is None

    def test_empty_list_normalized_to_none(self) -> None:
        """Test that empty event list is normalized to None."""
        config = WebhookConfig(url="https://example.com/webhook", events=[])
        assert config.events is None

    def test_rejects_invalid_event_string(self) -> None:
        """Test that invalid event type strings are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            WebhookConfig(
                url="https://example.com/webhook",
                events=["task.invalid"],  # type: ignore[list-item]
            )
        assert "invalid event type" in str(exc_info.value).lower()

    def test_rejects_non_list_events(self) -> None:
        """Test that non-list events value is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            WebhookConfig(
                url="https://example.com/webhook",
                events="task.started",  # type: ignore
            )
        assert "list" in str(exc_info.value).lower()


# =============================================================================
# Test: Field Constraints
# =============================================================================


class TestFieldConstraints:
    """Tests for field value constraints."""

    def test_timeout_min_value(self) -> None:
        """Test minimum timeout value."""
        config = WebhookConfig(url="https://example.com/webhook", timeout=1.0)
        assert config.timeout == 1.0

    def test_timeout_max_value(self) -> None:
        """Test maximum timeout value."""
        config = WebhookConfig(url="https://example.com/webhook", timeout=300.0)
        assert config.timeout == 300.0

    def test_timeout_below_min_rejected(self) -> None:
        """Test that timeout below minimum is rejected."""
        with pytest.raises(ValidationError):
            WebhookConfig(url="https://example.com/webhook", timeout=0.5)

    def test_timeout_above_max_rejected(self) -> None:
        """Test that timeout above maximum is rejected."""
        with pytest.raises(ValidationError):
            WebhookConfig(url="https://example.com/webhook", timeout=301.0)

    def test_max_retries_range(self) -> None:
        """Test max_retries valid range."""
        config0 = WebhookConfig(url="https://example.com/webhook", max_retries=0)
        config10 = WebhookConfig(url="https://example.com/webhook", max_retries=10)
        assert config0.max_retries == 0
        assert config10.max_retries == 10

    def test_max_retries_negative_rejected(self) -> None:
        """Test that negative max_retries is rejected."""
        with pytest.raises(ValidationError):
            WebhookConfig(url="https://example.com/webhook", max_retries=-1)

    def test_max_retries_too_high_rejected(self) -> None:
        """Test that max_retries above 10 is rejected."""
        with pytest.raises(ValidationError):
            WebhookConfig(url="https://example.com/webhook", max_retries=11)

    def test_retry_delay_range(self) -> None:
        """Test retry_delay valid range."""
        config_min = WebhookConfig(url="https://example.com/webhook", retry_delay=0.1)
        config_max = WebhookConfig(url="https://example.com/webhook", retry_delay=60.0)
        assert config_min.retry_delay == 0.1
        assert config_max.retry_delay == 60.0

    def test_retry_delay_too_low_rejected(self) -> None:
        """Test that retry_delay below minimum is rejected."""
        with pytest.raises(ValidationError):
            WebhookConfig(url="https://example.com/webhook", retry_delay=0.05)

    def test_retry_delay_too_high_rejected(self) -> None:
        """Test that retry_delay above maximum is rejected."""
        with pytest.raises(ValidationError):
            WebhookConfig(url="https://example.com/webhook", retry_delay=61.0)

    def test_name_max_length(self) -> None:
        """Test name maximum length constraint."""
        long_name = "x" * 100  # Exactly at limit
        config = WebhookConfig(url="https://example.com/webhook", name=long_name)
        assert config.name == long_name

    def test_name_too_long_rejected(self) -> None:
        """Test that name exceeding max length is rejected."""
        with pytest.raises(ValidationError):
            WebhookConfig(url="https://example.com/webhook", name="x" * 101)

    def test_description_max_length(self) -> None:
        """Test description maximum length constraint."""
        long_desc = "x" * 500  # Exactly at limit
        config = WebhookConfig(url="https://example.com/webhook", description=long_desc)
        assert config.description == long_desc

    def test_description_too_long_rejected(self) -> None:
        """Test that description exceeding max length is rejected."""
        with pytest.raises(ValidationError):
            WebhookConfig(url="https://example.com/webhook", description="x" * 501)


# =============================================================================
# Test: Event Filtering Methods
# =============================================================================


class TestEventFiltering:
    """Tests for event filtering methods."""

    def test_should_send_event_when_subscribed(self) -> None:
        """Test that subscribed events return True."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            events=[EventType.TASK_COMPLETED, EventType.PR_CREATED],
        )

        assert config.should_send_event(EventType.TASK_COMPLETED) is True
        assert config.should_send_event(EventType.PR_CREATED) is True

    def test_should_send_event_when_not_subscribed(self) -> None:
        """Test that non-subscribed events return False."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            events=[EventType.TASK_COMPLETED],
        )

        assert config.should_send_event(EventType.TASK_STARTED) is False
        assert config.should_send_event(EventType.PR_CREATED) is False

    def test_should_send_event_all_when_no_filter(self) -> None:
        """Test that all events return True when no filter is set."""
        config = WebhookConfig(url="https://example.com/webhook", events=None)

        for event_type in EventType:
            assert config.should_send_event(event_type) is True

    def test_should_send_event_accepts_string(self) -> None:
        """Test that should_send_event accepts string event types."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            events=[EventType.TASK_COMPLETED],
        )

        assert config.should_send_event("task.completed") is True
        assert config.should_send_event("task.started") is False

    def test_should_send_event_invalid_string_returns_false(self) -> None:
        """Test that invalid event string returns False."""
        config = WebhookConfig(url="https://example.com/webhook")

        assert config.should_send_event("invalid.event") is False

    def test_get_subscribed_events_with_filter(self) -> None:
        """Test get_subscribed_events returns filtered events."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            events=[EventType.TASK_COMPLETED, EventType.PR_CREATED],
        )

        subscribed = config.get_subscribed_events()

        assert len(subscribed) == 2
        assert EventType.TASK_COMPLETED in subscribed
        assert EventType.PR_CREATED in subscribed

    def test_get_subscribed_events_all_when_no_filter(self) -> None:
        """Test get_subscribed_events returns all when no filter."""
        config = WebhookConfig(url="https://example.com/webhook")

        subscribed = config.get_subscribed_events()

        assert len(subscribed) == len(list(EventType))
        for event_type in EventType:
            assert event_type in subscribed


# =============================================================================
# Test: Factory Methods
# =============================================================================


class TestFactoryMethods:
    """Tests for factory methods."""

    def test_from_url_basic(self) -> None:
        """Test from_url factory with URL only."""
        config = WebhookConfig.from_url("https://example.com/webhook")

        assert config.url == "https://example.com/webhook"
        assert config.secret is None
        assert config.events is None

    def test_from_url_with_secret(self) -> None:
        """Test from_url factory with secret."""
        config = WebhookConfig.from_url(
            "https://example.com/webhook",
            secret="my-secret",
        )

        assert config.secret == "my-secret"

    def test_from_url_with_events(self) -> None:
        """Test from_url factory with events."""
        config = WebhookConfig.from_url(
            "https://example.com/webhook",
            events=["task.completed", EventType.PR_CREATED],
        )

        assert config.events == [EventType.TASK_COMPLETED, EventType.PR_CREATED]

    def test_from_dict_basic(self) -> None:
        """Test from_dict factory method."""
        config = WebhookConfig.from_dict(
            {
                "url": "https://example.com/webhook",
                "secret": "dict-secret",
            }
        )

        assert config.url == "https://example.com/webhook"
        assert config.secret == "dict-secret"

    def test_from_dict_with_all_fields(self) -> None:
        """Test from_dict with all fields."""
        config = WebhookConfig.from_dict(
            {
                "url": "https://example.com/webhook",
                "secret": "my-secret",
                "events": ["task.completed"],
                "enabled": False,
                "timeout": 45.0,
                "max_retries": 5,
                "name": "Test Webhook",
            }
        )

        assert config.url == "https://example.com/webhook"
        assert config.secret == "my-secret"
        assert config.events == [EventType.TASK_COMPLETED]
        assert config.enabled is False
        assert config.timeout == 45.0
        assert config.max_retries == 5
        assert config.name == "Test Webhook"


# =============================================================================
# Test: Serialization
# =============================================================================


class TestSerialization:
    """Tests for serialization methods."""

    def test_to_dict_basic(self) -> None:
        """Test to_dict serialization."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            secret="my-secret",
            events=[EventType.TASK_COMPLETED],
        )

        data = config.to_dict()

        assert data["url"] == "https://example.com/webhook"
        assert data["secret"] == "my-secret"
        assert data["events"] == ["task.completed"]
        assert data["enabled"] is True

    def test_to_dict_excludes_secret(self) -> None:
        """Test to_dict with secret exclusion."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            secret="my-secret",
        )

        data = config.to_dict(exclude_secret=True)

        assert data["secret"] is None

    def test_to_safe_dict_masks_secret(self) -> None:
        """Test to_safe_dict masks secret."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            secret="my-secret",
        )

        data = config.to_safe_dict()

        assert data["secret"] == "***"

    def test_to_safe_dict_without_secret(self) -> None:
        """Test to_safe_dict when no secret is set."""
        config = WebhookConfig(url="https://example.com/webhook")

        data = config.to_safe_dict()

        assert data["secret"] is None


# =============================================================================
# Test: Display Methods
# =============================================================================


class TestDisplayMethods:
    """Tests for __repr__ and __str__ methods."""

    def test_repr_masks_secret(self) -> None:
        """Test that repr doesn't expose secret."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            secret="super-secret",
        )

        repr_str = repr(config)

        assert "super-secret" not in repr_str
        assert "has_secret=True" in repr_str

    def test_repr_shows_events(self) -> None:
        """Test that repr shows event types."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            events=[EventType.TASK_COMPLETED],
        )

        repr_str = repr(config)

        assert "task.completed" in repr_str

    def test_repr_shows_all_events_when_no_filter(self) -> None:
        """Test that repr shows 'all' when no event filter."""
        config = WebhookConfig(url="https://example.com/webhook")

        repr_str = repr(config)

        assert "events=all" in repr_str

    def test_str_human_readable(self) -> None:
        """Test human-readable string format."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            name="My Webhook",
            events=[EventType.TASK_COMPLETED, EventType.PR_CREATED],
        )

        str_repr = str(config)

        assert "My Webhook" in str_repr
        assert "example.com" in str_repr
        assert "2 events" in str_repr
        assert "enabled" in str_repr

    def test_str_shows_disabled(self) -> None:
        """Test that disabled status is shown."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            enabled=False,
        )

        str_repr = str(config)

        assert "disabled" in str_repr
