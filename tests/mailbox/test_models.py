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


class TestMailboxMessageEdgeCases:
    """Test edge cases for MailboxMessage."""

    def test_empty_content_message(self):
        """Test message with empty content is allowed."""
        msg = MailboxMessage(content="")
        assert msg.content == ""

    def test_very_long_content(self):
        """Test message with very long content."""
        long_content = "X" * 10000
        msg = MailboxMessage(content=long_content)
        assert msg.content == long_content
        assert len(msg.content) == 10000

    def test_multiline_content(self):
        """Test message with multiline content."""
        content = "Line 1\nLine 2\nLine 3"
        msg = MailboxMessage(content=content)
        assert "\n" in msg.content
        assert msg.content.count("\n") == 2

    def test_special_characters_in_content(self):
        """Test message with special characters."""
        content = "Hello! @#$%^&*() 日本語 emoji: 🎉"
        msg = MailboxMessage(content=content)
        assert msg.content == content

    def test_metadata_complex_structure(self):
        """Test message with complex nested metadata."""
        metadata = {
            "source": "api",
            "tags": ["urgent", "feature"],
            "nested": {"level1": {"level2": "value"}},
        }
        msg = MailboxMessage(content="Test", metadata=metadata)
        assert msg.metadata == metadata
        assert msg.metadata["nested"]["level1"]["level2"] == "value"

    def test_message_immutability_pattern(self):
        """Test that message fields can be accessed after creation."""
        timestamp = datetime(2024, 6, 15, 12, 0, 0)
        msg = MailboxMessage(
            content="Test",
            timestamp=timestamp,
            priority=Priority.URGENT,
        )
        # Verify all fields are accessible
        _ = msg.id
        _ = msg.sender
        _ = msg.content
        _ = msg.priority
        _ = msg.timestamp
        _ = msg.metadata


class TestMessagePreviewEdgeCases:
    """Test edge cases for message preview."""

    def test_preview_exact_max_length(self):
        """Test preview when content is exactly max_length."""
        msg = MailboxMessage(content="A" * 100)
        preview = msg.to_preview(max_length=100)
        # Should not truncate when exactly at limit
        assert preview.content_preview == "A" * 100
        assert not preview.content_preview.endswith("...")

    def test_preview_one_over_max_length(self):
        """Test preview when content is one char over max_length."""
        msg = MailboxMessage(content="A" * 101)
        preview = msg.to_preview(max_length=100)
        # Should truncate
        assert len(preview.content_preview) == 100
        assert preview.content_preview.endswith("...")

    def test_preview_empty_content(self):
        """Test preview with empty content."""
        msg = MailboxMessage(content="")
        preview = msg.to_preview()
        assert preview.content_preview == ""

    def test_preview_small_max_length(self):
        """Test preview with very small max_length."""
        msg = MailboxMessage(content="Hello World")
        preview = msg.to_preview(max_length=5)
        assert len(preview.content_preview) == 5
        assert preview.content_preview == "He..."

    def test_preview_preserves_all_metadata(self):
        """Test that preview preserves message metadata correctly."""
        timestamp = datetime(2024, 3, 20, 14, 30, 0)
        msg = MailboxMessage(
            id="unique-123",
            sender="important-sender",
            content="Some content here",
            priority=Priority.URGENT,
            timestamp=timestamp,
        )
        preview = msg.to_preview()

        assert preview.id == "unique-123"
        assert preview.sender == "important-sender"
        assert preview.priority == Priority.URGENT
        assert preview.timestamp == timestamp


class TestMailboxStateEdgeCases:
    """Test edge cases for MailboxState."""

    def test_state_with_many_messages(self):
        """Test state with many messages."""
        messages = [MailboxMessage(content=f"Message {i}") for i in range(100)]
        state = MailboxState(messages=messages, total_messages_received=100)

        assert len(state.messages) == 100
        assert state.messages[0].content == "Message 0"
        assert state.messages[99].content == "Message 99"

    def test_state_messages_preserve_order(self):
        """Test that message order is preserved."""
        messages = [
            MailboxMessage(content="First", priority=Priority.LOW),
            MailboxMessage(content="Second", priority=Priority.HIGH),
            MailboxMessage(content="Third", priority=Priority.NORMAL),
        ]
        state = MailboxState(messages=messages)

        assert state.messages[0].content == "First"
        assert state.messages[1].content == "Second"
        assert state.messages[2].content == "Third"

    def test_state_json_roundtrip(self):
        """Test complete JSON serialization round-trip."""
        import json

        timestamp = datetime(2024, 5, 10, 9, 45, 30)
        msg = MailboxMessage(
            id="roundtrip-id",
            sender="json-test",
            content="Roundtrip content",
            priority=Priority.HIGH,
            timestamp=timestamp,
            metadata={"key": "value"},
        )
        state = MailboxState(
            messages=[msg],
            last_checked=timestamp,
            total_messages_received=10,
        )

        # Serialize to JSON string
        json_str = state.model_dump_json()

        # Parse back
        data = json.loads(json_str)

        # Reconstruct
        restored = MailboxState(**data)

        assert len(restored.messages) == 1
        assert restored.messages[0].id == "roundtrip-id"
        assert restored.messages[0].sender == "json-test"
        assert restored.messages[0].priority == Priority.HIGH
        assert restored.total_messages_received == 10

    def test_state_empty_messages_list(self):
        """Test state explicitly with empty messages list."""
        state = MailboxState(messages=[])
        assert state.messages == []
        assert len(state.messages) == 0

    def test_state_total_messages_independent_of_current(self):
        """Test that total_messages_received is independent of messages list."""
        # Could have received 100 messages but only 2 remain (others processed)
        messages = [MailboxMessage(content="Remaining 1"), MailboxMessage(content="Remaining 2")]
        state = MailboxState(messages=messages, total_messages_received=100)

        assert len(state.messages) == 2
        assert state.total_messages_received == 100


class TestPriorityEnumBehavior:
    """Test Priority enum behavior in various contexts."""

    def test_priority_sorting(self):
        """Test that priorities can be sorted correctly."""
        priorities = [Priority.NORMAL, Priority.URGENT, Priority.LOW, Priority.HIGH]
        sorted_priorities = sorted(priorities)

        assert sorted_priorities == [
            Priority.LOW,
            Priority.NORMAL,
            Priority.HIGH,
            Priority.URGENT,
        ]

    def test_priority_in_list_context(self):
        """Test using priority in list operations."""
        messages = [
            MailboxMessage(content="Low", priority=Priority.LOW),
            MailboxMessage(content="Urgent", priority=Priority.URGENT),
            MailboxMessage(content="High", priority=Priority.HIGH),
        ]

        # Sort by priority (highest first)
        sorted_msgs = sorted(messages, key=lambda m: m.priority, reverse=True)

        assert sorted_msgs[0].content == "Urgent"
        assert sorted_msgs[1].content == "High"
        assert sorted_msgs[2].content == "Low"

    def test_priority_equality_with_int(self):
        """Test that priority can be compared with int."""
        assert Priority.LOW == 0
        assert Priority.URGENT == 3
        assert Priority.HIGH != 1


class TestMessageValidation:
    """Test Pydantic validation on message models."""

    def test_message_missing_content_raises(self):
        """Test that message without content raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            MailboxMessage()

        assert "content" in str(exc_info.value)

    def test_preview_missing_required_fields(self):
        """Test that preview without required fields raises error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MessagePreview()

        # Missing specific fields
        with pytest.raises(ValidationError):
            MessagePreview(id="test")

    def test_message_priority_invalid_string(self):
        """Test that invalid priority string raises error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MailboxMessage(content="Test", priority="invalid")
