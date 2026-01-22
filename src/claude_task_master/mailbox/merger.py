"""Message merger for combining multiple mailbox messages.

This module provides the MessageMerger class that consolidates multiple
messages into a single coherent change request for plan updates.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import MailboxMessage


class MessageMerger:
    """Merges multiple mailbox messages into a single change request.

    The merger consolidates messages by:
    1. Sorting by priority (highest first)
    2. Grouping by sender (optional)
    3. Formatting into a structured change request

    This is deterministic (no AI) to ensure consistent behavior.
    """

    def merge(self, messages: list[MailboxMessage]) -> str:
        """Merge multiple messages into a single change request.

        Args:
            messages: List of MailboxMessage objects to merge.

        Returns:
            A formatted string suitable for plan update prompts.

        Raises:
            ValueError: If messages list is empty.
        """
        if not messages:
            raise ValueError("Cannot merge empty message list")

        if len(messages) == 1:
            return self._format_single_message(messages[0])

        return self._format_multiple_messages(messages)

    def _format_single_message(self, message: MailboxMessage) -> str:
        """Format a single message as a change request.

        Args:
            message: The message to format.

        Returns:
            Formatted change request string.
        """
        parts = [message.content]

        # Add sender attribution if not anonymous
        if message.sender != "anonymous":
            parts.append(f"\n\n---\n*From: {message.sender}*")

        return "".join(parts)

    def _format_multiple_messages(self, messages: list[MailboxMessage]) -> str:
        """Format multiple messages as a consolidated change request.

        Args:
            messages: List of messages to format (already sorted by priority).

        Returns:
            Formatted change request with all messages.
        """
        header = self._build_header(messages)
        body = self._build_body(messages)
        footer = self._build_footer(len(messages))

        return f"{header}\n\n{body}\n\n{footer}"

    def _build_header(self, messages: list[MailboxMessage]) -> str:
        """Build the header section for merged messages.

        Args:
            messages: List of messages.

        Returns:
            Header string with count and timestamp.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"**Consolidated Change Requests ({len(messages)} messages)**\n"
            f"*Processed at: {timestamp}*"
        )

    def _build_body(self, messages: list[MailboxMessage]) -> str:
        """Build the body section with all message contents.

        Args:
            messages: List of messages to include.

        Returns:
            Formatted body with numbered messages.
        """
        parts = []

        for i, msg in enumerate(messages, 1):
            priority_label = self._get_priority_label(msg.priority)
            sender_info = f" (from {msg.sender})" if msg.sender != "anonymous" else ""

            parts.append(f"### Request {i}{priority_label}{sender_info}\n\n{msg.content}")

        return "\n\n---\n\n".join(parts)

    def _get_priority_label(self, priority: int) -> str:
        """Get a human-readable priority label.

        Args:
            priority: Priority value (0-3).

        Returns:
            Priority label string or empty string for normal priority.
        """
        labels = {
            0: " [LOW]",
            1: "",  # Normal - no label
            2: " [HIGH]",
            3: " [URGENT]",
        }
        return labels.get(priority, "")

    def _build_footer(self, count: int) -> str:
        """Build the footer with instructions.

        Args:
            count: Number of messages.

        Returns:
            Footer string with instructions.
        """
        return (
            f"**Please address ALL {count} change requests above in the plan update.**\n"
            f"Prioritize URGENT requests first, then HIGH, then others.\n"
            f"If requests conflict, prefer higher-priority requests."
        )

    def merge_to_single_content(self, messages: list[MailboxMessage]) -> str:
        """Merge messages to just the content strings combined.

        A simpler alternative to merge() that just concatenates content.

        Args:
            messages: List of messages.

        Returns:
            Combined content string.
        """
        if not messages:
            raise ValueError("Cannot merge empty message list")

        if len(messages) == 1:
            return messages[0].content

        contents = [msg.content for msg in messages]
        return "\n\n---\n\n".join(contents)
