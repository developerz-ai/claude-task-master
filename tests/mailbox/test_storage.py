"""Tests for MailboxStorage class.

Tests message storage, retrieval, clearing, and persistence.
"""

import json
from datetime import datetime
from pathlib import Path

from claude_task_master.mailbox.models import Priority
from claude_task_master.mailbox.storage import MailboxStorage


class TestMailboxStorageBasics:
    """Test basic MailboxStorage operations."""

    def test_init_default_path(self):
        """Test storage initializes with default path."""
        storage = MailboxStorage()

        assert storage.state_dir == Path(".claude-task-master")
        assert storage.storage_path == Path(".claude-task-master/mailbox.json")

    def test_init_custom_path(self, state_dir):
        """Test storage with custom state directory."""
        storage = MailboxStorage(state_dir=state_dir)

        assert storage.state_dir == state_dir
        assert storage.storage_path == state_dir / "mailbox.json"

    def test_exists_false_when_no_file(self, state_dir):
        """Test exists returns False when mailbox.json doesn't exist."""
        storage = MailboxStorage(state_dir=state_dir)

        assert storage.exists() is False

    def test_exists_true_after_message(self, state_dir):
        """Test exists returns True after adding a message."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test")

        assert storage.exists() is True
        assert storage.storage_path.exists()


class TestAddMessage:
    """Test adding messages to the mailbox."""

    def test_add_simple_message(self, state_dir):
        """Test adding a basic message."""
        storage = MailboxStorage(state_dir=state_dir)
        msg_id = storage.add_message("Test message")

        assert msg_id is not None
        assert len(msg_id) == 36  # UUID format

    def test_add_message_with_sender(self, state_dir):
        """Test adding message with sender."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test", sender="user@test.com")

        messages = storage.get_messages()
        assert len(messages) == 1
        assert messages[0].sender == "user@test.com"

    def test_add_message_with_priority(self, state_dir):
        """Test adding message with priority."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Urgent!", priority=Priority.URGENT)

        messages = storage.get_messages()
        assert messages[0].priority == Priority.URGENT

    def test_add_message_with_int_priority(self, state_dir):
        """Test adding message with int priority."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("High priority", priority=2)

        messages = storage.get_messages()
        assert messages[0].priority == Priority.HIGH

    def test_add_message_with_metadata(self, state_dir):
        """Test adding message with metadata."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test", metadata={"source": "api", "version": 1})

        messages = storage.get_messages()
        assert messages[0].metadata == {"source": "api", "version": 1}

    def test_add_multiple_messages(self, state_dir):
        """Test adding multiple messages."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.add_message("Message 1")
        storage.add_message("Message 2")
        storage.add_message("Message 3")

        assert storage.count() == 3

    def test_messages_persisted_to_disk(self, state_dir):
        """Test that messages are persisted."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Persistent message")

        # Create new storage instance
        storage2 = MailboxStorage(state_dir=state_dir)
        messages = storage2.get_messages()

        assert len(messages) == 1
        assert messages[0].content == "Persistent message"


class TestGetMessages:
    """Test retrieving messages."""

    def test_get_empty_mailbox(self, state_dir):
        """Test getting messages from empty mailbox."""
        storage = MailboxStorage(state_dir=state_dir)
        messages = storage.get_messages()

        assert messages == []

    def test_get_messages_sorted_by_priority(self, state_dir):
        """Test messages are sorted by priority (highest first)."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.add_message("Low", priority=Priority.LOW)
        storage.add_message("High", priority=Priority.HIGH)
        storage.add_message("Normal", priority=Priority.NORMAL)
        storage.add_message("Urgent", priority=Priority.URGENT)

        messages = storage.get_messages()

        assert messages[0].content == "Urgent"
        assert messages[1].content == "High"
        assert messages[2].content == "Normal"
        assert messages[3].content == "Low"

    def test_get_messages_same_priority_sorted_by_timestamp(self, state_dir):
        """Test messages with same priority sorted by timestamp."""
        storage = MailboxStorage(state_dir=state_dir)

        # Add messages with same priority
        storage.add_message("First", priority=Priority.NORMAL)
        storage.add_message("Second", priority=Priority.NORMAL)
        storage.add_message("Third", priority=Priority.NORMAL)

        messages = storage.get_messages()

        # First message should come first (ascending timestamp)
        assert messages[0].content == "First"
        assert messages[1].content == "Second"
        assert messages[2].content == "Third"

    def test_get_messages_does_not_clear(self, state_dir):
        """Test that get_messages doesn't remove messages."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test")

        storage.get_messages()
        messages = storage.get_messages()

        assert len(messages) == 1


class TestGetAndClear:
    """Test the atomic get and clear operation."""

    def test_get_and_clear_empty_mailbox(self, state_dir):
        """Test get_and_clear on empty mailbox."""
        storage = MailboxStorage(state_dir=state_dir)
        messages = storage.get_and_clear()

        assert messages == []

    def test_get_and_clear_removes_messages(self, state_dir):
        """Test that get_and_clear removes messages."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Message 1")
        storage.add_message("Message 2")

        messages = storage.get_and_clear()
        assert len(messages) == 2

        # Should be empty now
        remaining = storage.get_messages()
        assert remaining == []
        assert storage.count() == 0

    def test_get_and_clear_updates_last_checked(self, state_dir):
        """Test that get_and_clear updates last_checked."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test")

        before = datetime.now()
        storage.get_and_clear()
        after = datetime.now()

        status = storage.get_status()
        last_checked = datetime.fromisoformat(status["last_checked"])

        assert before <= last_checked <= after

    def test_get_and_clear_returns_sorted(self, state_dir):
        """Test that get_and_clear returns sorted messages."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.add_message("Normal", priority=Priority.NORMAL)
        storage.add_message("Urgent", priority=Priority.URGENT)

        messages = storage.get_and_clear()

        assert messages[0].content == "Urgent"
        assert messages[1].content == "Normal"


class TestClear:
    """Test clearing the mailbox."""

    def test_clear_empty_mailbox(self, state_dir):
        """Test clearing empty mailbox."""
        storage = MailboxStorage(state_dir=state_dir)
        count = storage.clear()

        assert count == 0

    def test_clear_returns_count(self, state_dir):
        """Test clear returns number of messages removed."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("1")
        storage.add_message("2")
        storage.add_message("3")

        count = storage.clear()

        assert count == 3

    def test_clear_removes_all_messages(self, state_dir):
        """Test clear removes all messages."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test")

        storage.clear()

        assert storage.count() == 0
        assert storage.get_messages() == []


class TestCount:
    """Test counting messages."""

    def test_count_empty_mailbox(self, state_dir):
        """Test count on empty mailbox."""
        storage = MailboxStorage(state_dir=state_dir)

        assert storage.count() == 0

    def test_count_with_messages(self, state_dir):
        """Test count with messages."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.add_message("1")
        assert storage.count() == 1

        storage.add_message("2")
        assert storage.count() == 2

        storage.add_message("3")
        assert storage.count() == 3


class TestGetStatus:
    """Test getting mailbox status."""

    def test_status_empty_mailbox(self, state_dir):
        """Test status of empty mailbox."""
        storage = MailboxStorage(state_dir=state_dir)
        status = storage.get_status()

        assert status["count"] == 0
        assert status["previews"] == []
        assert status["last_checked"] is None
        assert status["total_messages_received"] == 0

    def test_status_with_messages(self, state_dir):
        """Test status with messages."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test message", sender="tester")

        status = storage.get_status()

        assert status["count"] == 1
        assert len(status["previews"]) == 1
        assert status["previews"][0]["sender"] == "tester"
        assert status["total_messages_received"] == 1

    def test_status_total_includes_cleared(self, state_dir):
        """Test that total_messages_received includes cleared messages."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.add_message("1")
        storage.add_message("2")
        storage.clear()
        storage.add_message("3")

        status = storage.get_status()

        assert status["count"] == 1  # Only current messages
        assert status["total_messages_received"] == 3  # All-time total

    def test_status_previews_sorted_by_priority(self, state_dir):
        """Test that status previews are sorted by priority."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.add_message("Low", priority=Priority.LOW)
        storage.add_message("Urgent", priority=Priority.URGENT)

        status = storage.get_status()

        assert status["previews"][0]["content_preview"] == "Urgent"
        assert status["previews"][1]["content_preview"] == "Low"


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_corrupted_file_returns_empty(self, state_dir):
        """Test that corrupted mailbox.json returns empty state."""
        storage = MailboxStorage(state_dir=state_dir)

        # Create corrupted file
        storage.storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage.storage_path.write_text("not valid json")

        # Should return empty list, not error
        messages = storage.get_messages()
        assert messages == []

    def test_empty_json_returns_empty(self, state_dir):
        """Test that empty JSON returns empty state."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage.storage_path.write_text("{}")

        messages = storage.get_messages()
        assert messages == []

    def test_invalid_json_structure_returns_empty(self, state_dir):
        """Test invalid JSON structure returns empty state."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage.storage_path.write_text('{"messages": "not a list"}')

        messages = storage.get_messages()
        assert messages == []


class TestAtomicWrites:
    """Test atomic write functionality."""

    def test_atomic_write_creates_file(self, state_dir):
        """Test that atomic write creates the file."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test")

        assert storage.storage_path.exists()

        # Verify content
        with open(storage.storage_path) as f:
            data = json.load(f)

        assert len(data["messages"]) == 1

    def test_no_temp_files_left(self, state_dir):
        """Test that no temp files are left after write."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test")

        # Check for temp files
        temp_files = list(state_dir.glob(".mailbox_*"))
        assert len(temp_files) == 0
