"""Mailbox endpoints: send, status, and clear messages.

These endpoints allow external systems to send messages to the mailbox
which will be processed after the current task completes.
"""

from __future__ import annotations

import logging
from datetime import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING

from claude_task_master.api.models import (
    ClearMailboxResponse,
    ErrorResponse,
    MailboxMessagePreview,
    MailboxStatusResponse,
    SendMailboxMessageRequest,
    SendMailboxMessageResponse,
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

__all__ = ["create_mailbox_router"]


def create_mailbox_router() -> APIRouter:
    """Create router for mailbox endpoints.

    These endpoints allow external systems to send messages to the mailbox
    which will be processed after the current task completes.

    Returns:
        APIRouter configured with mailbox endpoints.

    Raises:
        ImportError: If FastAPI is not installed.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI not installed. Install with: pip install claude-task-master[api]"
        )

    router = APIRouter(tags=["Mailbox"])

    @router.post(
        "/send",
        response_model=SendMailboxMessageResponse,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Send Message to Mailbox",
        description="Send a message to the claudetm mailbox for processing after the current task.",
    )
    async def send_message(
        request: Request, message_request: SendMailboxMessageRequest
    ) -> SendMailboxMessageResponse | JSONResponse:
        """Send a message to the mailbox."""
        from claude_task_master.mailbox import MailboxStorage

        working_dir: Path = getattr(request.app.state, "working_dir", Path.cwd())
        state_dir = working_dir / ".claude-task-master"

        # Validate content is not empty/whitespace only
        if not message_request.content.strip():
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="invalid_request",
                    message="Message content cannot be empty or whitespace only",
                    suggestion="Provide a non-empty message content",
                ).model_dump(),
            )

        try:
            mailbox = MailboxStorage(state_dir=state_dir)
            message_id = mailbox.add_message(
                content=message_request.content.strip(),
                sender=message_request.sender,
                priority=message_request.priority,
                metadata=message_request.metadata or {},
            )

            return SendMailboxMessageResponse(
                success=True,
                message_id=message_id,
                message=f"Message sent successfully (id: {message_id})",
            )

        except Exception as e:
            logger.exception("Error sending message to mailbox")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to send message to mailbox",
                    detail=str(e),
                ).model_dump(),
            )

    @router.get(
        "",
        response_model=MailboxStatusResponse,
        responses={
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Get Mailbox Status",
        description="Check the status of the mailbox including message count and previews.",
    )
    async def get_mailbox_status(request: Request) -> MailboxStatusResponse | JSONResponse:
        """Get mailbox status."""
        from claude_task_master.mailbox import MailboxStorage

        working_dir: Path = getattr(request.app.state, "working_dir", Path.cwd())
        state_dir = working_dir / ".claude-task-master"

        try:
            mailbox = MailboxStorage(state_dir=state_dir)
            status = mailbox.get_status()

            # Convert preview dicts to MailboxMessagePreview models
            previews = []
            for preview_data in status["previews"]:
                previews.append(
                    MailboxMessagePreview(
                        id=preview_data["id"],
                        sender=preview_data["sender"],
                        content_preview=preview_data["content_preview"],
                        priority=preview_data["priority"],
                        timestamp=dt.fromisoformat(preview_data["timestamp"]),
                    )
                )

            # Parse last_checked if present
            last_checked = None
            if status["last_checked"]:
                last_checked = dt.fromisoformat(status["last_checked"])

            return MailboxStatusResponse(
                success=True,
                count=status["count"],
                messages=previews,
                last_checked=last_checked,
                total_messages_received=status["total_messages_received"],
            )

        except Exception as e:
            logger.exception("Error checking mailbox status")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to check mailbox status",
                    detail=str(e),
                ).model_dump(),
            )

    @router.delete(
        "",
        response_model=ClearMailboxResponse,
        responses={
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Clear Mailbox",
        description="Clear all messages from the mailbox.",
    )
    async def clear_mailbox(request: Request) -> ClearMailboxResponse | JSONResponse:
        """Clear all messages from the mailbox."""
        from claude_task_master.mailbox import MailboxStorage

        working_dir: Path = getattr(request.app.state, "working_dir", Path.cwd())
        state_dir = working_dir / ".claude-task-master"

        try:
            mailbox = MailboxStorage(state_dir=state_dir)
            count = mailbox.clear()

            return ClearMailboxResponse(
                success=True,
                messages_cleared=count,
                message=f"Cleared {count} message(s) from mailbox",
            )

        except Exception as e:
            logger.exception("Error clearing mailbox")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to clear mailbox",
                    detail=str(e),
                ).model_dump(),
            )

    return router
