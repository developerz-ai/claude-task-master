"""Mailbox request and response models for the REST API.

Covers sending messages to the mailbox, checking mailbox status,
and clearing the mailbox.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "SendMailboxMessageRequest",
    "SendMailboxMessageResponse",
    "MailboxMessagePreview",
    "MailboxStatusResponse",
    "ClearMailboxResponse",
]


# =============================================================================
# Mailbox Request/Response Models
# =============================================================================


class SendMailboxMessageRequest(BaseModel):
    """Request model for sending a message to the mailbox.

    Attributes:
        content: The message content describing the change request.
        sender: Identifier of the sender (default: "anonymous").
        priority: Message priority (0=low, 1=normal, 2=high, 3=urgent).
        metadata: Optional additional metadata.
    """

    content: str = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="The message content describing the change request",
        examples=["Please also add tests for the new feature", "Prioritize the bug fix"],
    )
    sender: str = Field(
        default="anonymous",
        max_length=256,
        description="Identifier of the sender",
        examples=["supervisor-agent", "user@example.com", "monitoring-system"],
    )
    priority: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Message priority (0=low, 1=normal, 2=high, 3=urgent)",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional additional metadata",
    )


class SendMailboxMessageResponse(BaseModel):
    """Response model for sending a message to the mailbox.

    Attributes:
        success: Whether the message was sent successfully.
        message_id: The ID of the created message.
        message: Human-readable result message.
        error: Error message if request failed.
    """

    success: bool
    message_id: str | None = None
    message: str | None = None
    error: str | None = None


class MailboxMessagePreview(BaseModel):
    """Preview of a mailbox message for status responses.

    Attributes:
        id: Message ID.
        sender: Message sender.
        content_preview: Truncated message content.
        priority: Message priority level.
        timestamp: When the message was created.
    """

    id: str
    sender: str
    content_preview: str
    priority: int
    timestamp: datetime


class MailboxStatusResponse(BaseModel):
    """Response model for mailbox status check.

    Attributes:
        success: Whether the request succeeded.
        count: Number of pending messages.
        messages: List of message previews.
        last_checked: When the mailbox was last checked.
        total_messages_received: Total count of messages ever received.
        error: Error message if request failed.
    """

    success: bool
    count: int = 0
    messages: list[MailboxMessagePreview] = []
    last_checked: datetime | None = None
    total_messages_received: int = 0
    error: str | None = None


class ClearMailboxResponse(BaseModel):
    """Response model for clearing the mailbox.

    Attributes:
        success: Whether the operation succeeded.
        messages_cleared: Number of messages that were cleared.
        message: Human-readable result message.
        error: Error message if operation failed.
    """

    success: bool
    messages_cleared: int = 0
    message: str | None = None
    error: str | None = None
