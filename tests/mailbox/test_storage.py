"""Tests for MailboxStorage class.

Tests message storage, retrieval, clearing, and persistence.
"""

import json
import multiprocessing
import threading
from datetime import datetime
from pathlib import Path

import pytest

from claude_task_master.core.state import StateLockError, file_lock
from claude_task_master.mailbox.models import Priority
from claude_task_master.mailbox.storage import MailboxStorage

# ---------------------------------------------------------------------------
# Module-level workers for cross-process tests.
# These must be at module scope (not inside classes) so ``multiprocessing``
# can pickle them on platforms that use the "spawn" start method.
# ---------------------------------------------------------------------------


def _proc_add_n(state_dir_str: str, tid: int, n: int) -> None:
    """Add n messages to the mailbox from a child process."""
    from pathlib import Path as _Path

    from claude_task_master.mailbox.storage import MailboxStorage as _Storage

    storage = _Storage(state_dir=_Path(state_dir_str))
    for i in range(n):
        storage.add_message(f"t{tid}-m{i}")


def _proc_dequeue_n(
    state_dir_str: str, n_rounds: int, result_queue: "multiprocessing.Queue[list[str]]"
) -> None:
    """Call get_and_clear n_rounds times and put collected contents into result_queue."""
    from pathlib import Path as _Path

    from claude_task_master.mailbox.storage import MailboxStorage as _Storage

    storage = _Storage(state_dir=_Path(state_dir_str))
    collected: list[str] = []
    for _ in range(n_rounds):
        msgs = storage.get_and_clear()
        collected.extend(m.content for m in msgs)
    result_queue.put(collected)


def _proc_hold_lock(
    lock_file_str: str,
    ready: "multiprocessing.synchronize.Event",
    done: "multiprocessing.synchronize.Event",
) -> None:
    """Acquire the mailbox flock, signal ``ready``, then wait for ``done``."""
    from pathlib import Path as _Path

    from claude_task_master.core.state import file_lock as _file_lock

    with _file_lock(_Path(lock_file_str), timeout=5.0):
        ready.set()
        done.wait(timeout=5.0)


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


class TestRemoveMessages:
    """Test selective removal of messages by ID."""

    def test_remove_messages_removes_specified_ids(self, state_dir):
        """Test remove_messages deletes only the given IDs."""
        storage = MailboxStorage(state_dir=state_dir)
        keep = storage.add_message("keep me")
        drop = storage.add_message("drop me")

        removed = storage.remove_messages([drop])

        assert removed == 1
        remaining = storage.get_messages()
        assert [m.id for m in remaining] == [keep]

    def test_remove_messages_returns_removed_count(self, state_dir):
        """Test remove_messages returns the number actually removed."""
        storage = MailboxStorage(state_dir=state_dir)
        a = storage.add_message("1")
        b = storage.add_message("2")
        storage.add_message("3")

        assert storage.remove_messages([a, b]) == 2
        assert storage.count() == 1

    def test_remove_messages_ignores_unknown_ids(self, state_dir):
        """Test unknown IDs are silently ignored, leaving messages intact."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("keep me")

        assert storage.remove_messages(["does-not-exist"]) == 0
        assert storage.count() == 1

    def test_remove_messages_empty_iterable_is_noop(self, state_dir):
        """Test removing an empty ID list changes nothing."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("keep me")

        assert storage.remove_messages([]) == 0
        assert storage.count() == 1

    def test_remove_messages_persists_across_instances(self, state_dir):
        """Test removal is written to disk and visible to a new instance."""
        storage = MailboxStorage(state_dir=state_dir)
        drop = storage.add_message("drop me")
        storage.add_message("keep me")

        storage.remove_messages([drop])

        reloaded = MailboxStorage(state_dir=state_dir)
        contents = [m.content for m in reloaded.get_messages()]
        assert contents == ["keep me"]


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

    def test_wrong_json_type_recovers(self, state_dir):
        """Test that wrong JSON type (array instead of object) recovers gracefully."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage.storage_path.write_text("[]")  # Array instead of object

        # Should recover gracefully and return empty list
        messages = storage.get_messages()
        assert messages == []

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

    def test_binary_file_recovers(self, state_dir):
        """Test that binary data in mailbox file recovers gracefully."""
        storage = MailboxStorage(state_dir=state_dir)

        storage.storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage.storage_path.write_bytes(b"\x00\x01\x02\x03\xff\xfe")

        # Should recover gracefully and return empty list
        messages = storage.get_messages()
        assert messages == []


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


class TestAtomicWriteFailure:
    """Test atomic write failure handling."""

    def test_save_state_cleans_temp_file_on_error(self, state_dir, monkeypatch):
        """Test that temp file is cleaned up when the atomic rename fails."""
        from pathlib import Path as RealPath

        storage = MailboxStorage(state_dir=state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)

        # Track temp files created
        temp_files_created = []
        original_mkstemp = __import__("tempfile").mkstemp

        def tracking_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            temp_files_created.append(path)
            return fd, path

        # Mock os.replace (the atomic rename) to fail
        def failing_replace(src, dst):
            raise OSError("Simulated disk full error")

        monkeypatch.setattr("tempfile.mkstemp", tracking_mkstemp)
        monkeypatch.setattr("os.replace", failing_replace)

        # Should raise the error
        with pytest.raises(OSError, match="Simulated disk full error"):
            storage.add_message("Test message")

        # Verify temp file was cleaned up
        for temp_path in temp_files_created:
            assert not RealPath(temp_path).exists(), f"Temp file {temp_path} was not cleaned up"

    def test_save_state_temp_cleanup_handles_missing_file(self, state_dir, monkeypatch):
        """Test that temp file cleanup handles already-deleted files gracefully."""
        from pathlib import Path as RealPath

        storage = MailboxStorage(state_dir=state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)

        original_mkstemp = __import__("tempfile").mkstemp
        temp_files_created = []

        def tracking_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            temp_files_created.append(path)
            return fd, path

        def failing_replace_and_delete_temp(src, dst):
            # Delete the temp file before the cleanup code can
            try:
                RealPath(src).unlink()
            except Exception:
                pass
            raise OSError("Simulated error after temp deletion")

        monkeypatch.setattr("tempfile.mkstemp", tracking_mkstemp)
        monkeypatch.setattr("os.replace", failing_replace_and_delete_temp)

        # Should still raise the original error, even if temp cleanup fails
        with pytest.raises(OSError, match="Simulated error after temp deletion"):
            storage.add_message("Test message")


class TestMailboxLocking:
    """Test that every mutation serializes its load→modify→save under a lock.

    Without the ``.mailbox.lock`` flock, a REST/MCP/CLI ``add_message`` racing
    the orchestrator's ``get_and_clear`` interleaves read-modify-write and
    silently destroys or resurrects messages (the slice-05 P0 bug).
    """

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda s: s.add_message("blocked"),
            lambda s: s.get_and_clear(),
            lambda s: s.clear(),
        ],
        ids=["add_message", "get_and_clear", "clear"],
    )
    def test_mutation_requires_the_lock(self, state_dir, mutate):
        """Each mutation waits on the mailbox lock and times out if held elsewhere."""
        state_dir.mkdir(parents=True, exist_ok=True)
        storage = MailboxStorage(state_dir=state_dir)
        storage.LOCK_TIMEOUT = 0.1  # fail fast instead of blocking the full 5s

        # Simulate another process/instance holding the mailbox lock.
        with file_lock(storage._lock_file, timeout=1.0):
            with pytest.raises(StateLockError):
                mutate(storage)

    def test_reads_do_not_require_the_lock(self, state_dir):
        """Read-only accessors never block on the mailbox lock (atomic writes suffice)."""
        state_dir.mkdir(parents=True, exist_ok=True)
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("present")

        # Hold the lock, then confirm reads still resolve immediately.
        with file_lock(storage._lock_file, timeout=1.0):
            assert storage.count() == 1
            assert len(storage.get_messages()) == 1
            assert storage.get_status()["count"] == 1
            assert storage.exists() is True

    def test_concurrent_adds_lose_no_messages(self, state_dir):
        """Threads adding concurrently never clobber each other's write."""
        storage = MailboxStorage(state_dir=state_dir)
        n_threads = 6
        per_thread = 4
        total = n_threads * per_thread
        barrier = threading.Barrier(n_threads)

        def worker(tid: int) -> None:
            barrier.wait()  # release all threads at once to maximize contention
            for i in range(per_thread):
                storage.add_message(f"t{tid}-m{i}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert storage.count() == total
        assert storage.get_status()["total_messages_received"] == total

    def test_concurrent_add_and_dequeue_conserve_messages(self, state_dir):
        """Adders racing dequeuers destroy no message and resurrect none."""
        storage = MailboxStorage(state_dir=state_dir)
        n = 3
        per = 3
        barrier = threading.Barrier(2 * n)
        drained: list[str] = []
        drained_lock = threading.Lock()

        def adder(tid: int) -> None:
            barrier.wait()
            for i in range(per):
                storage.add_message(f"t{tid}-m{i}")

        def dequeuer() -> None:
            barrier.wait()
            for _ in range(per):
                caught = storage.get_and_clear()
                with drained_lock:
                    drained.extend(m.content for m in caught)

        threads = [threading.Thread(target=adder, args=(t,)) for t in range(n)] + [
            threading.Thread(target=dequeuer) for _ in range(n)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Collect whatever the dequeuers hadn't caught by the time they finished.
        drained.extend(m.content for m in storage.get_and_clear())

        expected = sorted(f"t{t}-m{i}" for t in range(n) for i in range(per))
        # Every message present exactly once: none destroyed, none duplicated.
        assert sorted(drained) == expected
        assert storage.count() == 0


class TestConcurrentProcesses:
    """Cross-process safety using real OS processes and an fcntl flock.

    These tests exercise the mailbox file lock across process boundaries
    (not merely threads), which is the actual runtime topology: the REST/MCP
    server and the orchestrator run in separate processes.
    """

    @pytest.mark.slow
    @pytest.mark.timeout(15)
    def test_two_processes_adding_lose_no_messages(self, state_dir):
        """Two OS processes adding messages concurrently never clobber each other."""
        storage = MailboxStorage(state_dir=state_dir)
        n_per_proc = 4
        procs = [
            multiprocessing.Process(target=_proc_add_n, args=(str(state_dir), t, n_per_proc))
            for t in range(2)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=10)

        assert storage.count() == 2 * n_per_proc
        assert storage.get_status()["total_messages_received"] == 2 * n_per_proc

    @pytest.mark.slow
    @pytest.mark.timeout(15)
    def test_two_processes_add_vs_get_and_clear_conserve_all(self, state_dir):
        """Adder and dequeuer in separate processes: no message is lost or duplicated."""
        n_adds = 5
        # Give the dequeuer enough rounds to drain all adds.
        n_dequeue_rounds = n_adds + 2

        result_q: multiprocessing.Queue[list[str]] = multiprocessing.Queue()
        adder = multiprocessing.Process(target=_proc_add_n, args=(str(state_dir), 0, n_adds))
        dequeuer = multiprocessing.Process(
            target=_proc_dequeue_n, args=(str(state_dir), n_dequeue_rounds, result_q)
        )

        adder.start()
        dequeuer.start()
        adder.join(timeout=10)
        dequeuer.join(timeout=10)

        # Collect any messages the dequeuer missed (add completed after last get_and_clear).
        storage = MailboxStorage(state_dir=state_dir)
        leftover = [m.content for m in storage.get_and_clear()]

        dequeued = result_q.get(timeout=5)
        all_seen = sorted(dequeued + leftover)
        expected = sorted(f"t0-m{i}" for i in range(n_adds))

        # Every message appears exactly once: none destroyed, none duplicated.
        assert all_seen == expected

    @pytest.mark.slow
    @pytest.mark.timeout(10)
    def test_lock_held_by_child_blocks_parent_mutation(self, state_dir):
        """Lock held in a child process blocks a mutation from the parent process."""
        state_dir.mkdir(parents=True, exist_ok=True)
        storage = MailboxStorage(state_dir=state_dir)
        # Shrink the timeout so the test does not block for the full 5 s.
        storage.LOCK_TIMEOUT = 0.2

        ready: multiprocessing.synchronize.Event = multiprocessing.Event()
        done: multiprocessing.synchronize.Event = multiprocessing.Event()
        child = multiprocessing.Process(
            target=_proc_hold_lock,
            args=(str(storage._lock_file), ready, done),
        )
        child.start()
        try:
            ready.wait(timeout=5.0)
            with pytest.raises(StateLockError):
                storage.add_message("blocked by child lock")
        finally:
            done.set()
            child.join(timeout=5.0)
            if child.is_alive():
                child.kill()


class TestImportOrder:
    """The package must import regardless of which subpackage is reached first."""

    def test_mailbox_imports_without_core_first(self):
        """Regression: `core.control` imported `mailbox.storage` at module level,
        while `mailbox.storage` imports `core.atomic_io` (which runs `core/__init__`,
        which imports `core.control`). Importing `claude_task_master.mailbox` in a
        fresh interpreter therefore died with "cannot import name 'MailboxStorage'
        from partially initialized module" — hit by any consumer, and by pytest
        whenever a worker collected a mailbox test file first.
        """
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c", "import claude_task_master.mailbox"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, f"mailbox-first import failed:\n{result.stderr}"
