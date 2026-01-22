"""Pydantic models for the mailbox system.

This module defines the data models used by the mailbox:
- MailboxMessage: A single message with metadata
- MailboxState: The overall mailbox state for persistence
- MessagePreview: A shortened version for status display
"""

from datetime import datetime
from enum import IntEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Priority(IntEnum):
    """Message priority levels.

    Higher values indicate higher priority.
    Messages with higher priority are processed first.
    """

    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


class MailboxMessage(BaseModel):
    """A message in the mailbox.

    Attributes:
        id: Unique message identifier (auto-generated UUID).
        sender: Identifier of the message sender.
        content: The message content/body.
        priority: Message priority level (higher = more important).
        timestamp: When the message was created.
        metadata: Optional additional metadata.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    sender: str = "anonymous"
    content: str
    priority: Priority = Priority.NORMAL
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_preview(self, max_length: int = 100) -> "MessagePreview":
        """Convert to a preview for status display.

        Args:
            max_length: Maximum length of the content preview.

        Returns:
            MessagePreview with truncated content.
        """
        preview_content = self.content
        if len(preview_content) > max_length:
            preview_content = preview_content[: max_length - 3] + "..."

        return MessagePreview(
            id=self.id,
            sender=self.sender,
            content_preview=preview_content,
            priority=self.priority,
            timestamp=self.timestamp,
        )


class MessagePreview(BaseModel):
    """A shortened preview of a message.

    Used in status responses to avoid sending full message content.
    """

    id: str
    sender: str
    content_preview: str
    priority: Priority
    timestamp: datetime


class MailboxState(BaseModel):
    """Persistent state of the mailbox.

    Attributes:
        messages: List of messages currently in the mailbox.
        last_checked: When the mailbox was last checked/processed.
        total_messages_received: Total count of messages ever received.
    """

    messages: list[MailboxMessage] = Field(default_factory=list)
    last_checked: datetime | None = None
    total_messages_received: int = 0
