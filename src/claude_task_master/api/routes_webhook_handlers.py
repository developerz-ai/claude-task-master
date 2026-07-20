"""Read/write webhook endpoint handlers (list, create, get, update, delete).

The test-webhook handler lives in routes_webhooks.py alongside the SSRF
helpers it depends on, so that monkeypatch.setattr(rw, "_resolve_host", ...)
in the test suite intercepts calls inside _url_ssrf_error.

These five handlers have no such constraint and are extracted here to keep
routes_webhooks.py under the 500-LOC limit.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from claude_task_master.api.webhook_models import (
    WebhookCreateRequest,
    WebhookCreateResponse,
    WebhookDeleteResponse,
    WebhookErrorResponse,
    WebhookResponse,
    WebhooksListResponse,
    WebhookUpdateRequest,
    _auth_required_response,
    _generate_webhook_id,
    _get_registry,
    _webhook_to_response,
)
from claude_task_master.webhooks import (
    WebhookConflictError,
    WebhookNotFoundError,
)

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.responses import JSONResponse

try:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)

__all__ = [
    "_handle_list_webhooks",
    "_handle_create_webhook",
    "_handle_get_webhook",
    "_handle_update_webhook",
    "_handle_delete_webhook",
]


def _is_auth_enabled() -> bool:
    """Deferred lookup of is_auth_enabled() through routes_webhooks.

    Routes through routes_webhooks so that monkeypatch.setattr(rw, "is_auth_enabled", ...)
    in the test suite intercepts the call here too.
    """
    import claude_task_master.api.routes_webhooks as _rw

    return _rw.is_auth_enabled()


async def _handle_list_webhooks(request: Request) -> WebhooksListResponse | JSONResponse:
    """List all configured webhooks."""
    if not _is_auth_enabled():
        return _auth_required_response()
    try:
        webhooks = _get_registry(request).load()
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


async def _handle_create_webhook(
    request: Request, webhook_request: WebhookCreateRequest
) -> WebhookCreateResponse | JSONResponse:
    """Create a new webhook configuration."""
    if not _is_auth_enabled():
        return _auth_required_response()
    try:
        # The whole duplicate-check + insert runs under the registry lock so
        # two concurrent creates cannot both pass the check and clobber one another.
        with _get_registry(request).transaction() as webhooks:
            # Check for duplicate URL
            for existing_id, existing_webhook in webhooks.items():
                if existing_webhook["url"] == webhook_request.url:
                    raise WebhookConflictError(webhook_request.url, existing_id)

            # Generate unique ID
            webhook_id = _generate_webhook_id(webhook_request.url)
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
            webhooks[webhook_id] = webhook_data

        logger.info(f"Created webhook {webhook_id} for URL: {webhook_request.url}")
        return WebhookCreateResponse(
            success=True,
            message="Webhook created successfully",
            webhook=_webhook_to_response(webhook_id, webhook_data),
        )
    except WebhookConflictError as e:
        return JSONResponse(
            status_code=409,
            content=WebhookErrorResponse(
                error="duplicate_webhook",
                message=f"A webhook with URL '{e.url}' already exists",
                detail=f"Existing webhook ID: {e.existing_id}",
            ).model_dump(),
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


async def _handle_get_webhook(request: Request, webhook_id: str) -> WebhookResponse | JSONResponse:
    """Get a specific webhook configuration."""
    if not _is_auth_enabled():
        return _auth_required_response()
    try:
        webhook = _get_registry(request).get(webhook_id)
        if webhook is None:
            return JSONResponse(
                status_code=404,
                content=WebhookErrorResponse(
                    error="not_found",
                    message=f"Webhook '{webhook_id}' not found",
                ).model_dump(),
            )
        return _webhook_to_response(webhook_id, webhook)
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


async def _handle_update_webhook(
    request: Request, webhook_id: str, update_request: WebhookUpdateRequest
) -> WebhookResponse | JSONResponse:
    """Update an existing webhook configuration."""
    if not _is_auth_enabled():
        return _auth_required_response()

    if not update_request.has_updates():
        return JSONResponse(
            status_code=400,
            content=WebhookErrorResponse(
                error="validation_error",
                message="At least one field must be provided for update",
            ).model_dump(),
        )

    try:
        with _get_registry(request).transaction() as webhooks:
            if webhook_id not in webhooks:
                raise WebhookNotFoundError(webhook_id)

            if update_request.url is not None:
                for other_id, other_webhook in webhooks.items():
                    if other_id != webhook_id and other_webhook["url"] == update_request.url:
                        raise WebhookConflictError(update_request.url, other_id)

            webhook = webhooks[webhook_id]

            if update_request.url is not None:
                webhook["url"] = update_request.url
            if update_request.secret is not None:
                webhook["secret"] = update_request.secret if update_request.secret else None
            if update_request.events is not None:
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

        logger.info(f"Updated webhook {webhook_id}")
        return _webhook_to_response(webhook_id, webhook)

    except WebhookNotFoundError:
        return JSONResponse(
            status_code=404,
            content=WebhookErrorResponse(
                error="not_found",
                message=f"Webhook '{webhook_id}' not found",
            ).model_dump(),
        )
    except WebhookConflictError as e:
        return JSONResponse(
            status_code=409,
            content=WebhookErrorResponse(
                error="duplicate_webhook",
                message=f"A webhook with URL '{e.url}' already exists",
                detail=f"Existing webhook ID: {e.existing_id}",
            ).model_dump(),
        )
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


async def _handle_delete_webhook(
    request: Request, webhook_id: str
) -> WebhookDeleteResponse | JSONResponse:
    """Delete a webhook configuration."""
    if not _is_auth_enabled():
        return _auth_required_response()
    try:
        with _get_registry(request).transaction() as webhooks:
            if webhook_id not in webhooks:
                raise WebhookNotFoundError(webhook_id)
            del webhooks[webhook_id]

        logger.info(f"Deleted webhook {webhook_id}")
        return WebhookDeleteResponse(
            success=True,
            message="Webhook deleted successfully",
            id=webhook_id,
        )
    except WebhookNotFoundError:
        return JSONResponse(
            status_code=404,
            content=WebhookErrorResponse(
                error="not_found",
                message=f"Webhook '{webhook_id}' not found",
            ).model_dump(),
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
