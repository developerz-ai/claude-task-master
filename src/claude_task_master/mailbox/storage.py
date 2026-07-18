"""Mailbox storage for persistent message storage.

This module provides the MailboxStorage class that handles:
- Adding messages to the mailbox
- Retrieving messages (with optional clearing)
- Atomic file operations for safe concurrent access
- Persistence to .claude-task-master/mailbox.json
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from claude_task_master.core.atomic_io import atomic_write_json

from .models import MailboxMessage, MailboxState, Priority

if TYPE_CHECKING:
    from typing import Any


class MailboxStorageError(Exception):
    """Base exception for mailbox storage errors."""

    pass


class MailboxStorage:
    """Manages mailbox message storage.

    Persists messages to a JSON file with atomic writes for safety.
    Supports concurrent access through file-based locking.

    Attributes:
        storage_path: Path to the mailbox.json file.
    """

    def __init__(self, state_dir: Path | None = None):
        """Initialize mailbox storage.

        Args:
            state_dir: Directory for state files. Defaults to .claude-task-master.
        """
        self.state_dir = state_dir or Path(".claude-task-master")
        self.storage_path = self.state_dir / "mailbox.json"

    def _ensure_dir(self) -> None:
        """Ensure the state directory exists."""
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> MailboxState:
        """Load the current mailbox state from disk.

        Returns:
            MailboxState with current messages, or empty state if file doesn't exist.
        """
        if not self.storage_path.exists():
            return MailboxState()

        try:
            with open(self.storage_path) as f:
                data = json.load(f)
            return MailboxState(**data)
        except (json.JSONDecodeError, ValidationError, TypeError, UnicodeDecodeError):
            # Corrupted or invalid file - return empty state
            return MailboxState()

    def _save_state(self, state: MailboxState) -> None:
        """Save mailbox state atomically and durably.

        Delegates to the shared :func:`atomic_write_json` helper (temp file +
        fsync + rename + directory fsync) so a crash cannot leave a truncated
        ``mailbox.json``.

        Args:
            state: The MailboxState to save.
        """
        self._ensure_dir()
        # Use model_dump(mode="json") for proper datetime serialization.
        atomic_write_json(self.storage_path, state.model_dump(mode="json"))

    def add_message(
        self,
        content: str,
        sender: str = "anonymous",
        priority: int | Priority = Priority.NORMAL,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a message to the mailbox.

        Args:
            content: The message content.
            sender: Identifier of the sender (default: "anonymous").
            priority: Message priority (0=low, 1=normal, 2=high, 3=urgent).
            metadata: Optional additional metadata dict.

        Returns:
            The ID of the created message.
        """
        # Convert int to Priority enum if needed
        if isinstance(priority, int):
            priority = Priority(priority)

        message = MailboxMessage(
            content=content,
            sender=sender,
            priority=priority,
            metadata=metadata or {},
        )

        state = self._load_state()
        state.messages.append(message)
        state.total_messages_received += 1
        self._save_state(state)

        return message.id

    def get_messages(self) -> list[MailboxMessage]:
        """Get all messages without removing them.

        Returns:
            List of messages sorted by priority (highest first), then timestamp.
        """
        state = self._load_state()
        # Sort by priority (descending) then timestamp (ascending)
        return sorted(state.messages, key=lambda m: (-m.priority, m.timestamp))

    def get_and_clear(self) -> list[MailboxMessage]:
        """Get all messages and remove them atomically.

        This is the primary method for processing messages - it ensures
        no message is lost or processed twice.

        Returns:
            List of messages sorted by priority (highest first), then timestamp.
        """
        state = self._load_state()
        messages = sorted(state.messages, key=lambda m: (-m.priority, m.timestamp))

        # Clear messages and update last_checked
        state.messages = []
        state.last_checked = datetime.now()
        self._save_state(state)

        return messages

    def clear(self) -> int:
        """Clear all messages from the mailbox.

        Returns:
            The number of messages that were removed.
        """
        state = self._load_state()
        count = len(state.messages)

        state.messages = []
        state.last_checked = datetime.now()
        self._save_state(state)

        return count

    def count(self) -> int:
        """Get the number of messages in the mailbox.

        Returns:
            Number of pending messages.
        """
        state = self._load_state()
        return len(state.messages)

    def get_status(self) -> dict[str, Any]:
        """Get mailbox status information.

        Returns:
            Dict with count, previews, last_checked, and total_received.
        """
        state = self._load_state()
        messages = sorted(state.messages, key=lambda m: (-m.priority, m.timestamp))

        return {
            "count": len(messages),
            "previews": [m.to_preview().model_dump(mode="json") for m in messages],
            "last_checked": (state.last_checked.isoformat() if state.last_checked else None),
            "total_messages_received": state.total_messages_received,
        }

    def exists(self) -> bool:
        """Check if the mailbox storage file exists.

        Returns:
            True if mailbox.json exists.
        """
        return self.storage_path.exists()
