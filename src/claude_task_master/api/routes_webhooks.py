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

import ipaddress
import logging
import socket
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from claude_task_master.api.routes_webhook_handlers import (
    _handle_create_webhook,
    _handle_delete_webhook,
    _handle_get_webhook,
    _handle_list_webhooks,
    _handle_update_webhook,
)
from claude_task_master.api.webhook_models import (
    WebhookCreateRequest,
    WebhookCreateResponse,
    WebhookDeleteResponse,
    WebhookErrorResponse,
    WebhookResponse,
    WebhooksListResponse,
    WebhookTestRequest,
    WebhookTestResponse,
    WebhookUpdateRequest,
    _auth_required_response,
    _get_registry,
)
from claude_task_master.api.webhook_security import (
    _is_blocked_ip,
    _mask_headers,
    _strip_hop_headers,
)
from claude_task_master.auth import is_auth_enabled
from claude_task_master.webhooks import (
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


# =============================================================================
# DNS / SSRF helpers (defined here so monkeypatch.setattr(rw, "_resolve_host", ...)
# in tests intercepts the call made by _url_ssrf_error in this same namespace)
# =============================================================================


def _resolve_host(host: str) -> list[str]:
    """Resolve a hostname to all of its IP addresses.

    Numeric IP literals are returned as-is (no network I/O). Defined at module
    level so test fixtures can stub DNS via monkeypatch.setattr on this module.

    Args:
        host: The hostname or IP literal to resolve.

    Returns:
        List of resolved IP address strings.

    Raises:
        OSError: If resolution fails (e.g. unknown host).
    """
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _url_ssrf_error(url: str) -> str | None:
    """Validate that a URL's host resolves only to public addresses.

    Resolves the host post-DNS and rejects the request if any resolved address
    falls in a private/loopback/link-local/reserved range.

    Args:
        url: The target URL.

    Returns:
        An error message if the target is not permitted, otherwise None.
    """
    host = urlparse(url).hostname
    if not host:
        return "URL has no host"
    try:
        addresses = _resolve_host(host)
    except OSError:
        return f"Could not resolve host: {host}"
    if not addresses:
        return f"Could not resolve host: {host}"
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return f"Invalid resolved address: {addr}"
        if _is_blocked_ip(ip):
            return (
                f"Target resolves to a non-public address ({addr}); "
                "private, loopback, link-local, and reserved ranges are blocked"
            )
    return None


# =============================================================================
# Test Webhook Handler (kept here: calls _url_ssrf_error from this namespace)
# =============================================================================


async def _handle_test_webhook(
    request: Request, test_request: WebhookTestRequest
) -> WebhookTestResponse | JSONResponse:
    """Send a test webhook to verify configuration."""
    if not is_auth_enabled():
        return _auth_required_response()
    try:
        if test_request.webhook_id:
            webhook = _get_registry(request).get(test_request.webhook_id)
            if webhook is None:
                return JSONResponse(
                    status_code=404,
                    content=WebhookErrorResponse(
                        error="not_found",
                        message=f"Webhook '{test_request.webhook_id}' not found",
                    ).model_dump(),
                )
            url = webhook["url"]
            secret = webhook.get("secret")
            timeout = webhook.get("timeout", 30.0)
            verify_ssl = webhook.get("verify_ssl", True)
            headers = webhook.get("headers", {})
        elif test_request.url:
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

        # SSRF guard: resolve the target host and refuse private/loopback/reserved addresses.
        ssrf_error = _url_ssrf_error(url)
        if ssrf_error is not None:
            return JSONResponse(
                status_code=400,
                content=WebhookErrorResponse(
                    error="url_not_allowed",
                    message="Webhook target address is not permitted",
                    detail=ssrf_error,
                ).model_dump(),
            )

        # Strip hop-by-hop/routing headers before the outbound request.
        headers = _strip_hop_headers(headers)

        # Create test payload
        event_id = str(uuid.uuid4())
        test_payload = {
            "event_type": "webhook.test",
            "event_id": event_id,
            "timestamp": datetime.now().isoformat(),
            "message": "This is a test webhook from Claude Task Master",
            "test": True,
        }

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

    router.get(
        "",
        response_model=WebhooksListResponse,
        responses={500: {"model": WebhookErrorResponse, "description": "Internal server error"}},
        summary="List Webhooks",
        description="List all configured webhook endpoints.",
    )(_handle_list_webhooks)

    router.post(
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
    )(_handle_create_webhook)

    router.get(
        "/{webhook_id}",
        response_model=WebhookResponse,
        responses={
            404: {"model": WebhookErrorResponse, "description": "Webhook not found"},
            500: {"model": WebhookErrorResponse, "description": "Internal server error"},
        },
        summary="Get Webhook",
        description="Get a specific webhook configuration by ID.",
    )(_handle_get_webhook)

    router.put(
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
    )(_handle_update_webhook)

    router.delete(
        "/{webhook_id}",
        response_model=WebhookDeleteResponse,
        responses={
            404: {"model": WebhookErrorResponse, "description": "Webhook not found"},
            500: {"model": WebhookErrorResponse, "description": "Internal server error"},
        },
        summary="Delete Webhook",
        description="Delete a webhook configuration.",
    )(_handle_delete_webhook)

    router.post(
        "/test",
        response_model=WebhookTestResponse,
        responses={
            400: {"model": WebhookErrorResponse, "description": "Invalid request"},
            404: {"model": WebhookErrorResponse, "description": "Webhook not found"},
            500: {"model": WebhookErrorResponse, "description": "Internal server error"},
        },
        summary="Test Webhook",
        description="Send a test webhook to verify configuration.",
    )(_handle_test_webhook)

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
    # Security helpers (some defined here, some re-exported from webhook_security)
    "_resolve_host",
    "_url_ssrf_error",
    "_mask_headers",
    "_is_blocked_ip",
    "_strip_hop_headers",
]
