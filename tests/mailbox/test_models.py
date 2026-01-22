"""Tests for mailbox Pydantic models.

Tests MailboxMessage, MailboxState, MessagePreview, and Priority.
"""

from datetime import datetime

import pytest

from claude_task_master.mailbox.models import (
    MailboxMessage,
    MailboxState,
    MessagePreview,
    Priority,
)


class TestPriority:
    """Test the Priority enum."""

    def test_priority_values(self):
        """Test that priority values are ordered correctly."""
        assert Priority.LOW == 0
        assert Priority.NORMAL == 1
        assert Priority.HIGH == 2
        assert Priority.URGENT == 3

    def test_priority_comparison(self):
        """Test that priorities can be compared."""
        assert Priority.URGENT > Priority.HIGH
        assert Priority.HIGH > Priority.NORMAL
        assert Priority.NORMAL > Priority.LOW

    def test_priority_from_int(self):
        """Test creating priority from int."""
        assert Priority(0) == Priority.LOW
        assert Priority(3) == Priority.URGENT


class TestMailboxMessage:
    """Test the MailboxMessage model."""

    def test_create_minimal_message(self):
        """Test creating a message with just content."""
        msg = MailboxMessage(content="Test message")

        assert msg.content == "Test message"
        assert msg.sender == "anonymous"
        assert msg.priority == Priority.NORMAL
        assert msg.id is not None
        assert len(msg.id) == 36  # UUID format
        assert msg.timestamp is not None
        assert msg.metadata == {}

    def test_create_full_message(self):
        """Test creating a message with all fields."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0)
        msg = MailboxMessage(
            id="custom-id-123",
            sender="user@example.com",
            content="Full test message",
            priority=Priority.HIGH,
            timestamp=timestamp,
            metadata={"source": "test"},
        )

        assert msg.id == "custom-id-123"
        assert msg.sender == "user@example.com"
        assert msg.content == "Full test message"
        assert msg.priority == Priority.HIGH
        assert msg.timestamp == timestamp
        assert msg.metadata == {"source": "test"}

    def test_auto_generated_id_unique(self):
        """Test that auto-generated IDs are unique."""
        msg1 = MailboxMessage(content="Message 1")
        msg2 = MailboxMessage(content="Message 2")

        assert msg1.id != msg2.id

    def test_to_preview_short_content(self):
        """Test preview generation with short content."""
        msg = MailboxMessage(
            content="Short",
            sender="tester",
            priority=Priority.HIGH,
        )
        preview = msg.to_preview()

        assert isinstance(preview, MessagePreview)
        assert preview.id == msg.id
        assert preview.sender == "tester"
        assert preview.content_preview == "Short"
        assert preview.priority == Priority.HIGH
        assert preview.timestamp == msg.timestamp

    def test_to_preview_long_content(self):
        """Test preview generation with long content gets truncated."""
        long_content = "A" * 200
        msg = MailboxMessage(content=long_content)
        preview = msg.to_preview(max_length=100)

        assert len(preview.content_preview) == 100
        assert preview.content_preview.endswith("...")

    def test_to_preview_custom_max_length(self):
        """Test preview with custom max length."""
        msg = MailboxMessage(content="A" * 50)
        preview = msg.to_preview(max_length=20)

        assert len(preview.content_preview) == 20
        assert preview.content_preview.endswith("...")

    def test_message_serialization(self):
        """Test that message can be serialized to dict."""
        msg = MailboxMessage(content="Test")
        data = msg.model_dump()

        assert "id" in data
        assert data["content"] == "Test"
        assert data["sender"] == "anonymous"
        assert data["priority"] == Priority.NORMAL


class TestMessagePreview:
    """Test the MessagePreview model."""

    def test_create_preview(self):
        """Test creating a preview directly."""
        timestamp = datetime.now()
        preview = MessagePreview(
            id="test-id",
            sender="tester",
            content_preview="Preview content...",
            priority=Priority.NORMAL,
            timestamp=timestamp,
        )

        assert preview.id == "test-id"
        assert preview.sender == "tester"
        assert preview.content_preview == "Preview content..."
        assert preview.priority == Priority.NORMAL
        assert preview.timestamp == timestamp


class TestMailboxState:
    """Test the MailboxState model."""

    def test_create_empty_state(self):
        """Test creating an empty mailbox state."""
        state = MailboxState()

        assert state.messages == []
        assert state.last_checked is None
        assert state.total_messages_received == 0

    def test_create_state_with_messages(self):
        """Test creating state with messages."""
        msg1 = MailboxMessage(content="Message 1")
        msg2 = MailboxMessage(content="Message 2")
        timestamp = datetime.now()

        state = MailboxState(
            messages=[msg1, msg2],
            last_checked=timestamp,
            total_messages_received=5,
        )

        assert len(state.messages) == 2
        assert state.messages[0].content == "Message 1"
        assert state.messages[1].content == "Message 2"
        assert state.last_checked == timestamp
        assert state.total_messages_received == 5

    def test_state_serialization(self):
        """Test that state can be serialized and deserialized."""
        msg = MailboxMessage(content="Test message")
        state = MailboxState(
            messages=[msg],
            last_checked=datetime.now(),
            total_messages_received=1,
        )

        # Serialize
        data = state.model_dump(mode="json")

        # Deserialize
        restored = MailboxState(**data)

        assert len(restored.messages) == 1
        assert restored.messages[0].content == "Test message"
        assert restored.total_messages_received == 1


class TestPriorityEdgeCases:
    """Test edge cases for Priority enum."""

    def test_invalid_priority_raises_error(self):
        """Test that invalid priority values raise errors."""
        with pytest.raises(ValueError):
            Priority(5)

        with pytest.raises(ValueError):
            Priority(-1)

    def test_priority_as_int_in_message(self):
        """Test using int for priority in message."""
        # Should work - Pydantic should coerce int to Priority
        msg = MailboxMessage(content="Test", priority=2)
        assert msg.priority == Priority.HIGH
