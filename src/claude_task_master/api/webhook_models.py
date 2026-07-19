"""Pydantic models and storage/response helpers for webhook management.

Contains all request/response models used by the webhooks REST API, plus
the per-request helpers that convert stored webhook dicts to response models.
Security helpers (SSRF guards, header sanitisation) live in webhook_security.py.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, field_validator

from claude_task_master.webhooks import EventType

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from claude_task_master.webhooks import WebhookRegistry

# Import FastAPI - using try/except for graceful degradation
try:
    from fastapi import Request  # noqa: F811

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

__all__ = [
    # Request models
    "WebhookCreateRequest",
    "WebhookUpdateRequest",
    "WebhookTestRequest",
    # Response models
    "WebhookResponse",
    "WebhooksListResponse",
    "WebhookCreateResponse",
    "WebhookDeleteResponse",
    "WebhookTestResponse",
    "WebhookErrorResponse",
    # Storage / response helpers
    "_get_registry",
    "_generate_webhook_id",
    "_webhook_to_response",
    "_auth_required_response",
]


# =============================================================================
# Request / Response Models
# =============================================================================


class WebhookCreateRequest(BaseModel):
    """Request model for creating a new webhook.

    Attributes:
        url: The webhook endpoint URL (must be http:// or https://).
        secret: Optional shared secret for HMAC signature generation.
        events: List of event types to subscribe to. Empty means all events.
        enabled: Whether the webhook is active.
        name: Optional friendly name for the webhook.
        description: Optional description of the webhook's purpose.
        timeout: Request timeout in seconds.
        max_retries: Maximum retry attempts for failed deliveries.
        verify_ssl: Whether to verify SSL certificates.
        headers: Additional HTTP headers to include in requests.
    """

    url: str = Field(
        ...,
        min_length=1,
        description="Webhook endpoint URL (must be http:// or https://)",
        examples=["https://example.com/webhook"],
    )
    secret: str | None = Field(
        default=None,
        description="Shared secret for HMAC-SHA256 signature generation",
    )
    events: list[str] | None = Field(
        default=None,
        description="Event types to subscribe to (empty/null = all events)",
        examples=[["task.completed", "pr.created"]],
    )
    enabled: bool = Field(
        default=True,
        description="Whether this webhook is active",
    )
    name: str | None = Field(
        default=None,
        max_length=100,
        description="Optional friendly name for this webhook",
        examples=["Production Slack Notifications"],
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Optional description of this webhook's purpose",
    )
    timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Request timeout in seconds (1-300)",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed deliveries (0-10)",
    )
    verify_ssl: bool = Field(
        default=True,
        description="Whether to verify SSL certificates",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional HTTP headers to include in requests",
    )

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, v: str) -> str:
        """Ensure URL uses http:// or https:// scheme."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("Webhook URL must start with http:// or https://")
        return v

    @field_validator("events", mode="before")
    @classmethod
    def validate_events(cls, v: Any) -> list[str] | None:
        """Validate event types."""
        if v is None:
            return None
        if isinstance(v, list):
            if len(v) == 0:
                return None
            valid_events = {e.value for e in EventType}
            for event in v:
                if event not in valid_events:
                    raise ValueError(
                        f"Invalid event type: {event}. Valid types: {sorted(valid_events)}"
                    )
            return v
        raise ValueError("Events must be a list or null")


class WebhookUpdateRequest(BaseModel):
    """Request model for updating an existing webhook.

    All fields are optional - only provided fields are updated.

    Attributes:
        url: The webhook endpoint URL.
        secret: Shared secret (set to empty string to remove).
        events: Event types to subscribe to.
        enabled: Whether the webhook is active.
        name: Friendly name for the webhook.
        description: Description of the webhook's purpose.
        timeout: Request timeout in seconds.
        max_retries: Maximum retry attempts.
        verify_ssl: Whether to verify SSL certificates.
        headers: Additional HTTP headers.
    """

    url: str | None = Field(default=None, min_length=1)
    secret: str | None = Field(default=None)
    events: list[str] | None = Field(default=None)
    enabled: bool | None = Field(default=None)
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    timeout: float | None = Field(default=None, ge=1.0, le=300.0)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    verify_ssl: bool | None = Field(default=None)
    headers: dict[str, str] | None = Field(default=None)

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, v: str | None) -> str | None:
        """Ensure URL uses http:// or https:// scheme."""
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("Webhook URL must start with http:// or https://")
        return v

    @field_validator("events", mode="before")
    @classmethod
    def validate_events(cls, v: Any) -> list[str] | None:
        """Validate event types."""
        if v is None:
            return None
        if isinstance(v, list):
            if len(v) == 0:
                return []  # Explicitly empty = clear filter
            valid_events = {e.value for e in EventType}
            for event in v:
                if event not in valid_events:
                    raise ValueError(
                        f"Invalid event type: {event}. Valid types: {sorted(valid_events)}"
                    )
            return v
        raise ValueError("Events must be a list or null")

    def has_updates(self) -> bool:
        """Check if any updates were provided."""
        # Check all fields except 'secret' which uses sentinel
        for field_name in self.model_fields.keys():
            value = getattr(self, field_name)
            if value is not None:
                return True
        return False


class WebhookTestRequest(BaseModel):
    """Request model for testing a webhook.

    Can test either an existing webhook by ID or a new URL directly.

    Attributes:
        webhook_id: ID of an existing webhook to test.
        url: URL to test directly (if not using webhook_id).
        secret: Secret for direct URL testing.
    """

    webhook_id: str | None = Field(
        default=None,
        description="ID of an existing webhook to test",
    )
    url: str | None = Field(
        default=None,
        description="URL to test directly (alternative to webhook_id)",
    )
    secret: str | None = Field(
        default=None,
        description="Secret for direct URL testing",
    )

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, v: str | None) -> str | None:
        """Ensure URL uses http:// or https:// scheme."""
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("Webhook URL must start with http:// or https://")
        return v


class WebhookResponse(BaseModel):
    """Response model for a single webhook.

    Attributes:
        id: Unique webhook identifier.
        url: Webhook endpoint URL.
        has_secret: Whether a secret is configured (secret itself is not exposed).
        events: List of subscribed event types (null = all events).
        enabled: Whether the webhook is active.
        name: Friendly name.
        description: Description.
        timeout: Request timeout in seconds.
        max_retries: Maximum retry attempts.
        verify_ssl: Whether SSL certificates are verified.
        headers: Additional HTTP headers (values may be masked).
        created_at: When the webhook was created.
        updated_at: When the webhook was last updated.
    """

    id: str
    url: str
    has_secret: bool = False
    events: list[str] | None = None
    enabled: bool = True
    name: str | None = None
    description: str | None = None
    timeout: float = 30.0
    max_retries: int = 3
    verify_ssl: bool = True
    headers: dict[str, str] = Field(default_factory=dict)
    created_at: datetime | str
    updated_at: datetime | str


class WebhooksListResponse(BaseModel):
    """Response model for listing webhooks.

    Attributes:
        success: Whether the request succeeded.
        webhooks: List of webhook configurations.
        total: Total number of webhooks.
    """

    success: bool = True
    webhooks: list[WebhookResponse]
    total: int


class WebhookCreateResponse(BaseModel):
    """Response model for webhook creation.

    Attributes:
        success: Whether creation succeeded.
        message: Human-readable result message.
        webhook: The created webhook configuration.
    """

    success: bool = True
    message: str
    webhook: WebhookResponse


class WebhookDeleteResponse(BaseModel):
    """Response model for webhook deletion.

    Attributes:
        success: Whether deletion succeeded.
        message: Human-readable result message.
        id: ID of the deleted webhook.
    """

    success: bool = True
    message: str
    id: str


class WebhookTestResponse(BaseModel):
    """Response model for webhook test.

    Attributes:
        success: Whether the test webhook was delivered successfully.
        message: Human-readable result message.
        delivery_result: Details about the delivery attempt.
    """

    success: bool
    message: str
    status_code: int | None = None
    delivery_time_ms: float | None = None
    attempt_count: int = 1
    error: str | None = None


class WebhookErrorResponse(BaseModel):
    """Error response for webhook endpoints.

    Attributes:
        success: Always False.
        error: Error type/code.
        message: Human-readable error message.
        detail: Additional error details.
    """

    success: bool = False
    error: str
    message: str
    detail: str | None = None


# =============================================================================
# Storage Helpers
# =============================================================================


def _get_registry(request: Request) -> WebhookRegistry:
    """Get the durable, lock-protected webhook registry for this request.

    The registry is the single source of truth shared with the orchestrator's
    fan-out emitter. It serialises concurrent writes with a file lock and writes
    atomically, so registrations are never lost to a racing request or a crash
    mid-save.

    Args:
        request: FastAPI request object.

    Returns:
        A ``WebhookRegistry`` bound to this run's state directory.
    """
    from claude_task_master.webhooks import WebhookRegistry

    working_dir: Path = getattr(request.app.state, "working_dir", Path.cwd())
    state_dir = working_dir / ".claude-task-master"
    return WebhookRegistry(state_dir)


def _generate_webhook_id(url: str) -> str:
    """Generate a unique webhook ID based on URL hash and UUID.

    Args:
        url: The webhook URL.

    Returns:
        Unique webhook ID string.
    """
    # Use first 8 chars of URL hash + short UUID for uniqueness
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
    unique_id = str(uuid.uuid4())[:8]
    return f"wh_{url_hash}_{unique_id}"


def _webhook_to_response(webhook_id: str, webhook: dict[str, Any]) -> WebhookResponse:
    """Convert a stored webhook to response model.

    Args:
        webhook_id: The webhook ID.
        webhook: The webhook configuration dictionary.

    Returns:
        WebhookResponse model instance.
    """
    from claude_task_master.api.webhook_security import _mask_headers

    return WebhookResponse(
        id=webhook_id,
        url=webhook["url"],
        has_secret=bool(webhook.get("secret")),
        events=webhook.get("events"),
        enabled=webhook.get("enabled", True),
        name=webhook.get("name"),
        description=webhook.get("description"),
        timeout=webhook.get("timeout", 30.0),
        max_retries=webhook.get("max_retries", 3),
        verify_ssl=webhook.get("verify_ssl", True),
        headers=_mask_headers(webhook.get("headers", {})),
        created_at=webhook.get("created_at", datetime.now().isoformat()),
        updated_at=webhook.get("updated_at", datetime.now().isoformat()),
    )


def _auth_required_response() -> JSONResponse:
    """Build a 403 response refusing a webhook operation when auth is disabled.

    Webhook endpoints manage outbound-request configuration and can trigger
    server-side requests (POST /webhooks/test), so they must never be reachable
    when authentication is not configured.

    Returns:
        A 403 JSONResponse instructing the operator to configure a password.
    """
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=403,
        content=WebhookErrorResponse(
            error="authentication_required",
            message="Webhook operations require authentication to be enabled.",
            detail="Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH before starting the server.",
        ).model_dump(),
    )
