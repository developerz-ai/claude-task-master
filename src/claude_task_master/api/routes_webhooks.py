"""REST API routes for webhook management.

This module provides CRUD endpoints for managing webhook configurations:

Endpoints:
- GET /webhooks: List all configured webhooks
- POST /webhooks: Create a new webhook configuration
- GET /webhooks/{webhook_id}: Get a specific webhook configuration
- PUT /webhooks/{webhook_id}: Update a webhook configuration
- DELETE /webhooks/{webhook_id}: Delete a webhook configuration
- POST /webhooks/test: Send a test webhook to verify configuration

Webhooks are stored in the state directory as webhooks.json and are used
by the orchestrator to send notifications about task lifecycle events.

Usage:
    from claude_task_master.api.routes_webhooks import create_webhooks_router

    router = create_webhooks_router()
    app.include_router(router, prefix="/webhooks")
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, field_validator

from claude_task_master.webhooks import (
    EventType,
    WebhookClient,
    WebhookDeliveryResult,
)

if TYPE_CHECKING:
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse

# Import FastAPI - using try/except for graceful degradation
try:
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)

# Webhooks config file name
WEBHOOKS_FILE = "webhooks.json"


# =============================================================================
# Request/Response Models
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


def _get_webhooks_file(request: Request) -> Path:
    """Get the webhooks configuration file path.

    Args:
        request: FastAPI request object.

    Returns:
        Path to the webhooks.json file.
    """
    working_dir: Path = getattr(request.app.state, "working_dir", Path.cwd())
    state_dir = working_dir / ".claude-task-master"
    return state_dir / WEBHOOKS_FILE


def _load_webhooks(webhooks_file: Path) -> dict[str, dict[str, Any]]:
    """Load webhooks from the configuration file.

    Args:
        webhooks_file: Path to the webhooks file.

    Returns:
        Dictionary mapping webhook IDs to webhook configurations.
    """
    if not webhooks_file.exists():
        return {}

    try:
        with open(webhooks_file) as f:
            data = json.load(f)
            webhooks: dict[str, dict[str, Any]] = data.get("webhooks", {})
            return webhooks
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load webhooks file: {e}")
        return {}


def _save_webhooks(webhooks_file: Path, webhooks: dict[str, dict[str, Any]]) -> None:
    """Save webhooks to the configuration file.

    Args:
        webhooks_file: Path to the webhooks file.
        webhooks: Dictionary mapping webhook IDs to configurations.
    """
    # Ensure state directory exists
    webhooks_file.parent.mkdir(parents=True, exist_ok=True)

    data = {"webhooks": webhooks, "updated_at": datetime.now().isoformat()}

    with open(webhooks_file, "w") as f:
        json.dump(data, f, indent=2, default=str)


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
        headers=webhook.get("headers", {}),
        created_at=webhook.get("created_at", datetime.now().isoformat()),
        updated_at=webhook.get("updated_at", datetime.now().isoformat()),
    )


# =============================================================================
# Webhooks Router
# =============================================================================


def create_webhooks_router() -> APIRouter:
    """Create router for webhook management endpoints.

    These endpoints allow CRUD operations on webhook configurations
    and testing webhook delivery.

    Returns:
        APIRouter configured with webhook management endpoints.

    Raises:
        ImportError: If FastAPI is not installed.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI not installed. Install with: pip install claude-task-master[api]"
        )

    router = APIRouter(tags=["Webhooks"])

    # =========================================================================
    # GET /webhooks - List all webhooks
    # =========================================================================

    @router.get(
        "",
        response_model=WebhooksListResponse,
        responses={
            500: {"model": WebhookErrorResponse, "description": "Internal server error"},
        },
        summary="List Webhooks",
        description="List all configured webhook endpoints.",
    )
    async def list_webhooks(request: Request) -> WebhooksListResponse | JSONResponse:
        """List all configured webhooks.

        Returns all webhook configurations without exposing secrets.

        Returns:
            WebhooksListResponse with list of webhooks.
        """
        try:
            webhooks_file = _get_webhooks_file(request)
            webhooks = _load_webhooks(webhooks_file)

            webhook_responses = [
                _webhook_to_response(wh_id, wh_data) for wh_id, wh_data in webhooks.items()
            ]

            return WebhooksListResponse(
                success=True,
                webhooks=webhook_responses,
                total=len(webhook_responses),
            )

        except Exception as e:
            logger.exception("Error listing webhooks")
            return JSONResponse(
                status_code=500,
                content=WebhookErrorResponse(
                    error="internal_error",
                    message="Failed to list webhooks",
                    detail=str(e),
                ).model_dump(),
            )

    # =========================================================================
    # POST /webhooks - Create webhook
    # =========================================================================

    @router.post(
        "",
        response_model=WebhookCreateResponse,
        status_code=201,
        responses={
            400: {"model": WebhookErrorResponse, "description": "Invalid request"},
            409: {"model": WebhookErrorResponse, "description": "Webhook already exists"},
            500: {"model": WebhookErrorResponse, "description": "Internal server error"},
        },
        summary="Create Webhook",
        description="Create a new webhook configuration.",
    )
    async def create_webhook(
        request: Request, webhook_request: WebhookCreateRequest
    ) -> WebhookCreateResponse | JSONResponse:
        """Create a new webhook configuration.

        Args:
            webhook_request: Webhook configuration details.

        Returns:
            WebhookCreateResponse with created webhook.
        """
        try:
            webhooks_file = _get_webhooks_file(request)
            webhooks = _load_webhooks(webhooks_file)

            # Check for duplicate URL
            for existing_id, existing_webhook in webhooks.items():
                if existing_webhook["url"] == webhook_request.url:
                    return JSONResponse(
                        status_code=409,
                        content=WebhookErrorResponse(
                            error="duplicate_webhook",
                            message=f"A webhook with URL '{webhook_request.url}' already exists",
                            detail=f"Existing webhook ID: {existing_id}",
                        ).model_dump(),
                    )

            # Generate unique ID
            webhook_id = _generate_webhook_id(webhook_request.url)

            # Ensure ID is unique (very unlikely to collide, but check anyway)
            while webhook_id in webhooks:
                webhook_id = _generate_webhook_id(webhook_request.url + str(uuid.uuid4()))

            # Create webhook configuration
            now = datetime.now().isoformat()
            webhook_data = {
                "url": webhook_request.url,
                "secret": webhook_request.secret,
                "events": webhook_request.events,
                "enabled": webhook_request.enabled,
                "name": webhook_request.name,
                "description": webhook_request.description,
                "timeout": webhook_request.timeout,
                "max_retries": webhook_request.max_retries,
                "verify_ssl": webhook_request.verify_ssl,
                "headers": webhook_request.headers,
                "created_at": now,
                "updated_at": now,
            }

            # Save webhook
            webhooks[webhook_id] = webhook_data
            _save_webhooks(webhooks_file, webhooks)

            logger.info(f"Created webhook {webhook_id} for URL: {webhook_request.url}")

            return WebhookCreateResponse(
                success=True,
                message="Webhook created successfully",
                webhook=_webhook_to_response(webhook_id, webhook_data),
            )

        except Exception as e:
            logger.exception("Error creating webhook")
            return JSONResponse(
                status_code=500,
                content=WebhookErrorResponse(
                    error="internal_error",
                    message="Failed to create webhook",
                    detail=str(e),
                ).model_dump(),
            )

    # =========================================================================
    # GET /webhooks/{webhook_id} - Get specific webhook
    # =========================================================================

    @router.get(
        "/{webhook_id}",
        response_model=WebhookResponse,
        responses={
            404: {"model": WebhookErrorResponse, "description": "Webhook not found"},
            500: {"model": WebhookErrorResponse, "description": "Internal server error"},
        },
        summary="Get Webhook",
        description="Get a specific webhook configuration by ID.",
    )
    async def get_webhook(request: Request, webhook_id: str) -> WebhookResponse | JSONResponse:
        """Get a specific webhook configuration.

        Args:
            webhook_id: The webhook ID.

        Returns:
            WebhookResponse with webhook configuration.
        """
        try:
            webhooks_file = _get_webhooks_file(request)
            webhooks = _load_webhooks(webhooks_file)

            if webhook_id not in webhooks:
                return JSONResponse(
                    status_code=404,
                    content=WebhookErrorResponse(
                        error="not_found",
                        message=f"Webhook '{webhook_id}' not found",
                    ).model_dump(),
                )

            return _webhook_to_response(webhook_id, webhooks[webhook_id])

        except Exception as e:
            logger.exception("Error getting webhook")
            return JSONResponse(
                status_code=500,
                content=WebhookErrorResponse(
                    error="internal_error",
                    message="Failed to get webhook",
                    detail=str(e),
                ).model_dump(),
            )

    # =========================================================================
    # PUT /webhooks/{webhook_id} - Update webhook
    # =========================================================================

    @router.put(
        "/{webhook_id}",
        response_model=WebhookResponse,
        responses={
            400: {"model": WebhookErrorResponse, "description": "Invalid request"},
            404: {"model": WebhookErrorResponse, "description": "Webhook not found"},
            409: {"model": WebhookErrorResponse, "description": "URL conflict"},
            500: {"model": WebhookErrorResponse, "description": "Internal server error"},
        },
        summary="Update Webhook",
        description="Update an existing webhook configuration.",
    )
    async def update_webhook(
        request: Request, webhook_id: str, update_request: WebhookUpdateRequest
    ) -> WebhookResponse | JSONResponse:
        """Update an existing webhook configuration.

        Only provided fields are updated.

        Args:
            webhook_id: The webhook ID to update.
            update_request: Fields to update.

        Returns:
            WebhookResponse with updated webhook configuration.
        """
        try:
            webhooks_file = _get_webhooks_file(request)
            webhooks = _load_webhooks(webhooks_file)

            if webhook_id not in webhooks:
                return JSONResponse(
                    status_code=404,
                    content=WebhookErrorResponse(
                        error="not_found",
                        message=f"Webhook '{webhook_id}' not found",
                    ).model_dump(),
                )

            # Check for URL conflict if URL is being updated
            if update_request.url is not None:
                for other_id, other_webhook in webhooks.items():
                    if other_id != webhook_id and other_webhook["url"] == update_request.url:
                        return JSONResponse(
                            status_code=409,
                            content=WebhookErrorResponse(
                                error="duplicate_webhook",
                                message=f"A webhook with URL '{update_request.url}' already exists",
                                detail=f"Existing webhook ID: {other_id}",
                            ).model_dump(),
                        )

            # Update fields
            webhook = webhooks[webhook_id]

            if update_request.url is not None:
                webhook["url"] = update_request.url
            if update_request.secret is not None:
                # Empty string clears the secret
                webhook["secret"] = update_request.secret if update_request.secret else None
            if update_request.events is not None:
                # Empty list clears the filter (all events)
                webhook["events"] = update_request.events if update_request.events else None
            if update_request.enabled is not None:
                webhook["enabled"] = update_request.enabled
            if update_request.name is not None:
                webhook["name"] = update_request.name if update_request.name else None
            if update_request.description is not None:
                webhook["description"] = (
                    update_request.description if update_request.description else None
                )
            if update_request.timeout is not None:
                webhook["timeout"] = update_request.timeout
            if update_request.max_retries is not None:
                webhook["max_retries"] = update_request.max_retries
            if update_request.verify_ssl is not None:
                webhook["verify_ssl"] = update_request.verify_ssl
            if update_request.headers is not None:
                webhook["headers"] = update_request.headers

            webhook["updated_at"] = datetime.now().isoformat()

            # Save changes
            _save_webhooks(webhooks_file, webhooks)

            logger.info(f"Updated webhook {webhook_id}")

            return _webhook_to_response(webhook_id, webhook)

        except Exception as e:
            logger.exception("Error updating webhook")
            return JSONResponse(
                status_code=500,
                content=WebhookErrorResponse(
                    error="internal_error",
                    message="Failed to update webhook",
                    detail=str(e),
                ).model_dump(),
            )

    # =========================================================================
    # DELETE /webhooks/{webhook_id} - Delete webhook
    # =========================================================================

    @router.delete(
        "/{webhook_id}",
        response_model=WebhookDeleteResponse,
        responses={
            404: {"model": WebhookErrorResponse, "description": "Webhook not found"},
            500: {"model": WebhookErrorResponse, "description": "Internal server error"},
        },
        summary="Delete Webhook",
        description="Delete a webhook configuration.",
    )
    async def delete_webhook(
        request: Request, webhook_id: str
    ) -> WebhookDeleteResponse | JSONResponse:
        """Delete a webhook configuration.

        Args:
            webhook_id: The webhook ID to delete.

        Returns:
            WebhookDeleteResponse with deletion result.
        """
        try:
            webhooks_file = _get_webhooks_file(request)
            webhooks = _load_webhooks(webhooks_file)

            if webhook_id not in webhooks:
                return JSONResponse(
                    status_code=404,
                    content=WebhookErrorResponse(
                        error="not_found",
                        message=f"Webhook '{webhook_id}' not found",
                    ).model_dump(),
                )

            # Delete webhook
            del webhooks[webhook_id]
            _save_webhooks(webhooks_file, webhooks)

            logger.info(f"Deleted webhook {webhook_id}")

            return WebhookDeleteResponse(
                success=True,
                message="Webhook deleted successfully",
                id=webhook_id,
            )

        except Exception as e:
            logger.exception("Error deleting webhook")
            return JSONResponse(
                status_code=500,
                content=WebhookErrorResponse(
                    error="internal_error",
                    message="Failed to delete webhook",
                    detail=str(e),
                ).model_dump(),
            )

    # =========================================================================
    # POST /webhooks/test - Test webhook
    # =========================================================================

    @router.post(
        "/test",
        response_model=WebhookTestResponse,
        responses={
            400: {"model": WebhookErrorResponse, "description": "Invalid request"},
            404: {"model": WebhookErrorResponse, "description": "Webhook not found"},
            500: {"model": WebhookErrorResponse, "description": "Internal server error"},
        },
        summary="Test Webhook",
        description="Send a test webhook to verify configuration.",
    )
    async def test_webhook(
        request: Request, test_request: WebhookTestRequest
    ) -> WebhookTestResponse | JSONResponse:
        """Send a test webhook to verify configuration.

        Can test either an existing webhook by ID or a new URL directly.

        Args:
            test_request: Test request with webhook_id or url/secret.

        Returns:
            WebhookTestResponse with delivery result.
        """
        try:
            # Determine webhook URL and secret
            if test_request.webhook_id:
                # Test existing webhook
                webhooks_file = _get_webhooks_file(request)
                webhooks = _load_webhooks(webhooks_file)

                if test_request.webhook_id not in webhooks:
                    return JSONResponse(
                        status_code=404,
                        content=WebhookErrorResponse(
                            error="not_found",
                            message=f"Webhook '{test_request.webhook_id}' not found",
                        ).model_dump(),
                    )

                webhook = webhooks[test_request.webhook_id]
                url = webhook["url"]
                secret = webhook.get("secret")
                timeout = webhook.get("timeout", 30.0)
                verify_ssl = webhook.get("verify_ssl", True)
                headers = webhook.get("headers", {})

            elif test_request.url:
                # Test direct URL
                url = test_request.url
                secret = test_request.secret
                timeout = 30.0
                verify_ssl = True
                headers = {}

            else:
                return JSONResponse(
                    status_code=400,
                    content=WebhookErrorResponse(
                        error="invalid_request",
                        message="Either webhook_id or url must be provided",
                    ).model_dump(),
                )

            # Create test payload
            event_id = str(uuid.uuid4())
            test_payload = {
                "event_type": "webhook.test",
                "event_id": event_id,
                "timestamp": datetime.now().isoformat(),
                "message": "This is a test webhook from Claude Task Master",
                "test": True,
            }

            # Send test webhook
            client = WebhookClient(
                url=url,
                secret=secret,
                timeout=timeout,
                max_retries=1,  # Only try once for tests
                verify_ssl=verify_ssl,
                headers=headers,
            )

            result: WebhookDeliveryResult = await client.send(
                data=test_payload,
                event_type="webhook.test",
                delivery_id=event_id,
            )

            if result.success:
                return WebhookTestResponse(
                    success=True,
                    message="Test webhook delivered successfully",
                    status_code=result.status_code,
                    delivery_time_ms=result.delivery_time_ms,
                    attempt_count=result.attempt_count,
                )
            else:
                return WebhookTestResponse(
                    success=False,
                    message="Test webhook delivery failed",
                    status_code=result.status_code,
                    delivery_time_ms=result.delivery_time_ms,
                    attempt_count=result.attempt_count,
                    error=result.error,
                )

        except Exception as e:
            logger.exception("Error testing webhook")
            return JSONResponse(
                status_code=500,
                content=WebhookErrorResponse(
                    error="internal_error",
                    message="Failed to test webhook",
                    detail=str(e),
                ).model_dump(),
            )

    return router


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "create_webhooks_router",
    "WebhookCreateRequest",
    "WebhookUpdateRequest",
    "WebhookTestRequest",
    "WebhookResponse",
    "WebhooksListResponse",
    "WebhookCreateResponse",
    "WebhookDeleteResponse",
    "WebhookTestResponse",
    "WebhookErrorResponse",
]
