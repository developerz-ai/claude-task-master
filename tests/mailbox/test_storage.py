"""Tests for MailboxStorage class.

Tests message storage, retrieval, clearing, and persistence.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

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

    def test_state_dir_created_on_first_write(self, temp_dir):
        """Test that state directory is created if it doesn't exist."""
        new_state_dir = temp_dir / "new_state_dir"
        storage = MailboxStorage(state_dir=new_state_dir)

        assert not new_state_dir.exists()

        storage.add_message("Test")

        assert new_state_dir.exists()
        assert storage.storage_path.exists()


class TestPersistence:
    """Test persistence and state integrity."""

    def test_total_messages_persisted_across_sessions(self, state_dir):
        """Test that total_messages_received is persisted across sessions."""
        storage1 = MailboxStorage(state_dir=state_dir)
        storage1.add_message("1")
        storage1.add_message("2")
        storage1.add_message("3")

        # New session
        storage2 = MailboxStorage(state_dir=state_dir)
        status = storage2.get_status()

        assert status["total_messages_received"] == 3

    def test_last_checked_persisted_across_sessions(self, state_dir):
        """Test that last_checked is persisted across sessions."""
        storage1 = MailboxStorage(state_dir=state_dir)
        storage1.add_message("Test")
        storage1.get_and_clear()

        # New session
        storage2 = MailboxStorage(state_dir=state_dir)
        status = storage2.get_status()

        assert status["last_checked"] is not None

    def test_messages_with_all_fields_persisted(self, state_dir):
        """Test that all message fields survive persistence."""
        storage1 = MailboxStorage(state_dir=state_dir)
        msg_id = storage1.add_message(
            content="Test content",
            sender="test@example.com",
            priority=Priority.HIGH,
            metadata={"key": "value", "nested": {"a": 1}},
        )

        # New session
        storage2 = MailboxStorage(state_dir=state_dir)
        messages = storage2.get_messages()

        assert len(messages) == 1
        msg = messages[0]
        assert msg.id == msg_id
        assert msg.content == "Test content"
        assert msg.sender == "test@example.com"
        assert msg.priority == Priority.HIGH
        assert msg.metadata == {"key": "value", "nested": {"a": 1}}

    def test_empty_state_persists_correctly(self, state_dir):
        """Test that empty state is handled correctly."""
        storage1 = MailboxStorage(state_dir=state_dir)
        storage1.add_message("Test")
        storage1.clear()

        # New session
        storage2 = MailboxStorage(state_dir=state_dir)

        assert storage2.count() == 0
        assert storage2.get_messages() == []


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_add_message_with_empty_content(self, state_dir):
        """Test adding message with empty content."""
        storage = MailboxStorage(state_dir=state_dir)
        msg_id = storage.add_message("")

        messages = storage.get_messages()
        assert len(messages) == 1
        assert messages[0].content == ""
        assert messages[0].id == msg_id

    def test_add_message_with_unicode(self, state_dir):
        """Test adding message with unicode characters."""
        storage = MailboxStorage(state_dir=state_dir)
        content = "Hello 日本語 🎉 مرحبا"
        storage.add_message(content, sender="日本人")

        # Verify persistence
        storage2 = MailboxStorage(state_dir=state_dir)
        messages = storage2.get_messages()

        assert messages[0].content == content
        assert messages[0].sender == "日本人"

    def test_add_message_with_very_long_content(self, state_dir):
        """Test adding message with very long content."""
        storage = MailboxStorage(state_dir=state_dir)
        content = "A" * 100000
        storage.add_message(content)

        messages = storage.get_messages()
        assert len(messages[0].content) == 100000

    def test_add_message_with_newlines(self, state_dir):
        """Test adding message with newlines and special chars."""
        storage = MailboxStorage(state_dir=state_dir)
        content = "Line 1\nLine 2\r\nLine 3\tTabbed"
        storage.add_message(content)

        messages = storage.get_messages()
        assert messages[0].content == content

    def test_add_message_preserves_order_with_same_timestamp(self, state_dir):
        """Test that messages added rapidly maintain consistent ordering."""
        storage = MailboxStorage(state_dir=state_dir)

        # Add many messages rapidly
        for i in range(20):
            storage.add_message(f"Message {i}", priority=Priority.NORMAL)

        messages = storage.get_messages()
        assert len(messages) == 20

        # Should maintain insertion order for same priority
        contents = [m.content for m in messages]
        expected = [f"Message {i}" for i in range(20)]
        assert contents == expected

    def test_priority_boundaries(self, state_dir):
        """Test priority values at boundaries."""
        storage = MailboxStorage(state_dir=state_dir)

        # Test all valid priority values
        storage.add_message("Low", priority=0)
        storage.add_message("Normal", priority=1)
        storage.add_message("High", priority=2)
        storage.add_message("Urgent", priority=3)

        messages = storage.get_messages()
        assert messages[0].priority == Priority.URGENT
        assert messages[1].priority == Priority.HIGH
        assert messages[2].priority == Priority.NORMAL
        assert messages[3].priority == Priority.LOW

    def test_get_messages_does_not_mutate_state(self, state_dir):
        """Test that get_messages doesn't modify the stored state."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test")

        # Get messages multiple times
        for _ in range(5):
            messages = storage.get_messages()
            assert len(messages) == 1

        # Should still be there
        assert storage.count() == 1

    def test_clear_updates_last_checked(self, state_dir):
        """Test that clear updates last_checked timestamp."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test")

        storage.clear()

        status_after = storage.get_status()
        assert status_after["last_checked"] is not None

    def test_status_preview_truncation(self, state_dir):
        """Test that status previews are truncated for long messages."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("A" * 200)

        status = storage.get_status()
        preview = status["previews"][0]["content_preview"]

        # Default preview length is 100
        assert len(preview) == 100
        assert preview.endswith("...")

    def test_metadata_with_special_types(self, state_dir):
        """Test metadata with various types serializable to JSON."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message(
            "Test",
            metadata={
                "int": 42,
                "float": 3.14,
                "bool": True,
                "none": None,
                "list": [1, 2, 3],
                "nested": {"a": {"b": {"c": "deep"}}},
            },
        )

        # Reload and verify
        storage2 = MailboxStorage(state_dir=state_dir)
        messages = storage2.get_messages()

        meta = messages[0].metadata
        assert meta["int"] == 42
        assert meta["float"] == 3.14
        assert meta["bool"] is True
        assert meta["none"] is None
        assert meta["list"] == [1, 2, 3]
        assert meta["nested"]["a"]["b"]["c"] == "deep"


class TestConcurrentAccess:
    """Test concurrent access scenarios."""

    def test_separate_instances_see_same_data(self, state_dir):
        """Test that separate instances see the same data."""
        storage1 = MailboxStorage(state_dir=state_dir)
        storage2 = MailboxStorage(state_dir=state_dir)

        storage1.add_message("From storage1")

        messages = storage2.get_messages()
        assert len(messages) == 1
        assert messages[0].content == "From storage1"

    def test_interleaved_operations(self, state_dir):
        """Test interleaved operations from multiple instances."""
        storage1 = MailboxStorage(state_dir=state_dir)
        storage2 = MailboxStorage(state_dir=state_dir)

        storage1.add_message("Message 1")
        storage2.add_message("Message 2")
        storage1.add_message("Message 3")

        messages = storage1.get_messages()
        assert len(messages) == 3

    def test_one_clears_other_sees_empty(self, state_dir):
        """Test that when one instance clears, another sees empty."""
        storage1 = MailboxStorage(state_dir=state_dir)
        storage2 = MailboxStorage(state_dir=state_dir)

        storage1.add_message("Test")
        assert storage2.count() == 1

        storage1.clear()
        assert storage2.count() == 0


class TestComplexSorting:
    """Test complex sorting scenarios."""

    def test_mixed_priority_timestamp_sorting(self, state_dir):
        """Test sorting with mixed priorities and timestamps."""
        storage = MailboxStorage(state_dir=state_dir)

        # Add in specific order
        storage.add_message("Normal 1", priority=Priority.NORMAL)
        storage.add_message("High 1", priority=Priority.HIGH)
        storage.add_message("Normal 2", priority=Priority.NORMAL)
        storage.add_message("Low 1", priority=Priority.LOW)
        storage.add_message("High 2", priority=Priority.HIGH)
        storage.add_message("Urgent 1", priority=Priority.URGENT)

        messages = storage.get_messages()

        # Verify priority ordering
        assert messages[0].content == "Urgent 1"
        assert messages[1].content == "High 1"
        assert messages[2].content == "High 2"
        assert messages[3].content == "Normal 1"
        assert messages[4].content == "Normal 2"
        assert messages[5].content == "Low 1"

    def test_all_same_priority_maintains_order(self, state_dir):
        """Test that same-priority messages maintain insertion order."""
        storage = MailboxStorage(state_dir=state_dir)

        for i in range(10):
            storage.add_message(f"Msg {i}", priority=Priority.HIGH)

        messages = storage.get_messages()

        for i, msg in enumerate(messages):
            assert msg.content == f"Msg {i}"

    def test_get_and_clear_returns_sorted(self, state_dir):
        """Test that get_and_clear returns properly sorted messages."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.add_message("Low", priority=Priority.LOW)
        storage.add_message("Urgent", priority=Priority.URGENT)
        storage.add_message("Normal", priority=Priority.NORMAL)

        messages = storage.get_and_clear()

        assert messages[0].content == "Urgent"
        assert messages[1].content == "Normal"
        assert messages[2].content == "Low"
        assert storage.count() == 0


class TestFileCorruption:
    """Test file corruption and recovery scenarios."""

    def test_partial_json_recovers(self, state_dir):
        """Test recovery from partial/truncated JSON."""
        storage = MailboxStorage(state_dir=state_dir)

        # Create partial JSON file
        storage.storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage.storage_path.write_text('{"messages": [{"content": "te')

        messages = storage.get_messages()
        assert messages == []

    def test_wrong_json_type_raises_error(self, state_dir):
        """Test that wrong JSON type (array instead of object) raises TypeError.

        Note: The current implementation doesn't handle this case gracefully.
        This test documents the current behavior.
        """
        storage = MailboxStorage(state_dir=state_dir)

        storage.storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage.storage_path.write_text("[]")  # Array instead of object

        # Current behavior: raises TypeError (not handled)
        with pytest.raises(TypeError):
            storage.get_messages()

    def test_missing_required_fields_recovers(self, state_dir):
        """Test recovery from missing required message fields."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.storage_path.parent.mkdir(parents=True, exist_ok=True)
        # Message missing required 'content' field
        storage.storage_path.write_text('{"messages": [{"sender": "test"}]}')

        messages = storage.get_messages()
        assert messages == []

    def test_add_after_corruption_works(self, state_dir):
        """Test that adding messages after corruption works."""
        storage = MailboxStorage(state_dir=state_dir)

        # Create corrupted file
        storage.storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage.storage_path.write_text("corrupted")

        # Should work - starts fresh
        storage.add_message("New message")

        messages = storage.get_messages()
        assert len(messages) == 1
        assert messages[0].content == "New message"

    def test_binary_file_raises_error(self, state_dir):
        """Test that binary data in mailbox file raises UnicodeDecodeError.

        Note: The current implementation doesn't handle this case gracefully.
        This test documents the current behavior.
        """
        storage = MailboxStorage(state_dir=state_dir)

        storage.storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage.storage_path.write_bytes(b"\x00\x01\x02\x03\xff\xfe")

        # Current behavior: raises UnicodeDecodeError (not handled)
        with pytest.raises(UnicodeDecodeError):
            storage.get_messages()


class TestStateManagement:
    """Test internal state management."""

    def test_total_messages_survives_clear(self, state_dir):
        """Test that total_messages_received survives clear operations."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.add_message("1")
        storage.add_message("2")
        storage.clear()
        storage.add_message("3")
        storage.get_and_clear()
        storage.add_message("4")

        status = storage.get_status()
        assert status["total_messages_received"] == 4
        assert status["count"] == 1

    def test_status_after_multiple_operations(self, state_dir):
        """Test status reflects multiple operations correctly."""
        storage = MailboxStorage(state_dir=state_dir)

        # Add messages
        storage.add_message("1", priority=Priority.URGENT)
        storage.add_message("2", priority=Priority.LOW)
        storage.add_message("3", priority=Priority.NORMAL)

        status = storage.get_status()
        assert status["count"] == 3
        assert status["total_messages_received"] == 3
        assert len(status["previews"]) == 3

        # Previews should be sorted by priority
        assert status["previews"][0]["content_preview"] == "1"  # URGENT
        assert status["previews"][1]["content_preview"] == "3"  # NORMAL
        assert status["previews"][2]["content_preview"] == "2"  # LOW

    def test_exists_after_clear(self, state_dir):
        """Test that exists() returns True even after clearing messages."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("Test")
        storage.clear()

        # File should still exist (just empty)
        assert storage.exists()


class TestMailboxStorageError:
    """Test MailboxStorageError exception."""

    def test_exception_exists(self):
        """Test that MailboxStorageError can be raised and caught."""
        from claude_task_master.mailbox.storage import MailboxStorageError

        with pytest.raises(MailboxStorageError):
            raise MailboxStorageError("Test error")

    def test_exception_message(self):
        """Test that exception message is preserved."""
        from claude_task_master.mailbox.storage import MailboxStorageError

        try:
            raise MailboxStorageError("Custom error message")
        except MailboxStorageError as e:
            assert str(e) == "Custom error message"
