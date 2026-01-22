"""Mailbox system for inter-instance communication.

This module provides a mailbox system that allows multiple Claude Task Master
instances (or external systems) to send messages that can trigger plan updates.

Main Components:
- MailboxMessage: Message model with content, sender, priority
- MailboxStorage: Persistent storage for messages
- MessageMerger: Merges multiple messages into a single change request
"""

from .merger import MessageMerger
from .models import MailboxMessage, MailboxState, MessagePreview, Priority
from .storage import MailboxStorage

__all__ = [
    "MailboxMessage",
    "MailboxState",
    "MailboxStorage",
    "MessageMerger",
    "MessagePreview",
    "Priority",
]
