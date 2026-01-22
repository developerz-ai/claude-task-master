"""Property-based tests for the mailbox system.

Tests the properties of mailbox message handling, priority sorting,
and storage operations.
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from claude_task_master.mailbox.models import (
    MailboxMessage,
    MailboxState,
    Priority,
)
from claude_task_master.mailbox.storage import MailboxStorage

# Define strategies for mailbox testing
priority_strategy = st.sampled_from(list(Priority))
sender_strategy = st.text(
    min_size=1, max_size=50, alphabet=st.characters(blacklist_categories=["Cs"])
)
content_strategy = st.text(
    min_size=0, max_size=5000, alphabet=st.characters(blacklist_categories=["Cs"])
)
metadata_strategy = st.fixed_dictionaries(
    {},
    optional={
        "source": st.sampled_from(["cli", "api", "mcp", "webhook"]),
        "instance_id": st.text(
            min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
        ),
    },
)


class TestMailboxMessageProperties:
    """Property-based tests for MailboxMessage."""

    @given(
        content=content_strategy,
        sender=sender_strategy,
        priority=priority_strategy,
    )
    @settings(max_examples=100)
    def test_message_creation_preserves_data(self, content: str, sender: str, priority: Priority):
        """Creating a message should preserve all input data."""
        message = MailboxMessage(
            content=content,
            sender=sender,
            priority=priority,
        )

        assert message.content == content
        assert message.sender == sender
        assert message.priority == priority
        assert message.id is not None
        assert len(message.id) > 0
        assert message.timestamp is not None

    @given(
        content=st.text(
            min_size=1, max_size=5000, alphabet=st.characters(blacklist_categories=["Cs"])
        ),
        max_length=st.integers(min_value=10, max_value=500),
    )
    @settings(max_examples=100)
    def test_preview_respects_max_length(self, content: str, max_length: int):
        """Preview should respect max_length parameter."""
        message = MailboxMessage(content=content, sender="test")
        preview = message.to_preview(max_length=max_length)

        if len(content) <= max_length:
            assert preview.content_preview == content
        else:
            assert len(preview.content_preview) <= max_length
            assert preview.content_preview.endswith("...")

    @given(
        content=content_strategy,
        sender=sender_strategy,
        priority=priority_strategy,
    )
    @settings(max_examples=100)
    def test_preview_preserves_metadata(self, content: str, sender: str, priority: Priority):
        """Preview should preserve message metadata."""
        message = MailboxMessage(
            content=content,
            sender=sender,
            priority=priority,
        )
        preview = message.to_preview()

        assert preview.id == message.id
        assert preview.sender == message.sender
        assert preview.priority == message.priority
        assert preview.timestamp == message.timestamp

    @given(
        messages=st.lists(
            st.fixed_dictionaries(
                {
                    "content": content_strategy,
                    "priority": priority_strategy,
                }
            ),
            min_size=0,
            max_size=20,
        )
    )
    @settings(max_examples=100)
    def test_all_messages_get_unique_ids(self, messages: list):
        """All messages should receive unique IDs."""
        created_messages = [
            MailboxMessage(content=m["content"], priority=m["priority"]) for m in messages
        ]

        ids = [m.id for m in created_messages]
        assert len(ids) == len(set(ids))  # All IDs should be unique


class TestMailboxStateProperties:
    """Property-based tests for MailboxState."""

    @given(
        message_count=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=50)
    def test_state_message_count_matches_list(self, message_count: int):
        """State should correctly track message count."""
        messages = [
            MailboxMessage(content=f"Message {i}", priority=Priority.NORMAL)
            for i in range(message_count)
        ]

        state = MailboxState(
            messages=messages,
            total_messages_received=message_count,
        )

        assert len(state.messages) == message_count
        assert state.total_messages_received == message_count


class TestPrioritySortingProperties:
    """Property-based tests for priority-based message sorting."""

    @given(
        priorities=st.lists(priority_strategy, min_size=1, max_size=30),
    )
    @settings(max_examples=100)
    def test_higher_priority_messages_come_first(self, priorities: list):
        """Messages should be sorted with higher priority first."""
        messages = [
            MailboxMessage(
                content=f"Message {i}",
                priority=p,
                timestamp=datetime.now() + timedelta(minutes=i),  # Sequential timestamps
            )
            for i, p in enumerate(priorities)
        ]

        # Sort by priority descending, then timestamp ascending
        sorted_messages = sorted(messages, key=lambda m: (-m.priority, m.timestamp))

        for i in range(len(sorted_messages) - 1):
            current = sorted_messages[i]
            next_msg = sorted_messages[i + 1]

            # Higher or equal priority should come first
            assert current.priority >= next_msg.priority

    @given(
        count_per_priority=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=50)
    def test_same_priority_sorted_by_timestamp(self, count_per_priority: int):
        """Messages with same priority should be sorted by timestamp."""
        messages = []
        base_time = datetime.now()

        for i in range(count_per_priority):
            messages.append(
                MailboxMessage(
                    content=f"Message {i}",
                    priority=Priority.NORMAL,
                    timestamp=base_time + timedelta(minutes=i),
                )
            )

        sorted_messages = sorted(messages, key=lambda m: (-m.priority, m.timestamp))

        for i in range(len(sorted_messages) - 1):
            assert sorted_messages[i].timestamp <= sorted_messages[i + 1].timestamp


class TestMailboxStorageProperties:
    """Property-based tests for MailboxStorage."""

    @given(
        contents=st.lists(content_strategy, min_size=0, max_size=20),
    )
    @settings(max_examples=50)
    def test_add_then_get_returns_all_messages(self, contents: list):
        """All added messages should be retrievable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = MailboxStorage(state_dir=Path(tmpdir))

            for content in contents:
                storage.add_message(content=content)

            messages = storage.get_messages()
            assert len(messages) == len(contents)

    @given(
        contents=st.lists(
            st.text(min_size=1, max_size=100, alphabet=st.characters(blacklist_categories=["Cs"])),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=50)
    def test_get_and_clear_empties_mailbox(self, contents: list):
        """get_and_clear should return all messages and empty the mailbox."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = MailboxStorage(state_dir=Path(tmpdir))

            for content in contents:
                storage.add_message(content=content)

            messages = storage.get_and_clear()
            assert len(messages) == len(contents)

            # Mailbox should now be empty
            remaining = storage.get_messages()
            assert len(remaining) == 0

    @given(
        priorities=st.lists(priority_strategy, min_size=2, max_size=20),
    )
    @settings(max_examples=50)
    def test_get_messages_returns_sorted_by_priority(self, priorities: list):
        """get_messages should return messages sorted by priority."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = MailboxStorage(state_dir=Path(tmpdir))

            for i, priority in enumerate(priorities):
                storage.add_message(content=f"Message {i}", priority=priority)

            messages = storage.get_messages()

            for i in range(len(messages) - 1):
                assert messages[i].priority >= messages[i + 1].priority

    @given(count=st.integers(min_value=0, max_value=30))
    @settings(max_examples=30)
    def test_count_matches_added_messages(self, count: int):
        """count() should match the number of added messages."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = MailboxStorage(state_dir=Path(tmpdir))

            for i in range(count):
                storage.add_message(content=f"Message {i}")

            assert storage.count() == count

    @given(
        add_count=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=30)
    def test_clear_returns_correct_count(self, add_count: int):
        """clear() should return the number of cleared messages."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = MailboxStorage(state_dir=Path(tmpdir))

            for i in range(add_count):
                storage.add_message(content=f"Message {i}")

            cleared = storage.clear()
            assert cleared == add_count
            assert storage.count() == 0

    @given(
        contents=st.lists(content_strategy, min_size=1, max_size=10),
    )
    @settings(max_examples=30)
    def test_total_messages_received_increments(self, contents: list):
        """total_messages_received should increment with each message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = MailboxStorage(state_dir=Path(tmpdir))

            for i, content in enumerate(contents, start=1):
                storage.add_message(content=content)
                status = storage.get_status()
                assert status["total_messages_received"] == i

    @given(
        add_counts=st.lists(st.integers(min_value=1, max_value=5), min_size=2, max_size=5),
    )
    @settings(max_examples=30)
    def test_total_received_persists_after_clear(self, add_counts: list):
        """total_messages_received should persist even after clearing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = MailboxStorage(state_dir=Path(tmpdir))
            expected_total = 0

            for count in add_counts:
                for i in range(count):
                    storage.add_message(content=f"Message {i}")
                expected_total += count

                # Clear doesn't reset total_messages_received
                storage.clear()

                status = storage.get_status()
                assert status["total_messages_received"] == expected_total
