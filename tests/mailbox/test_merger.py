"""Tests for MessageMerger class.

Tests message merging for plan update prompts.
"""

from datetime import datetime

import pytest

from claude_task_master.mailbox.merger import MessageMerger
from claude_task_master.mailbox.models import MailboxMessage, Priority


@pytest.fixture
def merger():
    """Create a MessageMerger instance."""
    return MessageMerger()


class TestMessageMergerCreation:
    """Test MessageMerger instantiation."""

    def test_create_instance(self):
        """Test creating a MessageMerger instance."""
        m = MessageMerger()
        assert m is not None

    def test_multiple_instances_independent(self):
        """Test that multiple instances are independent."""
        m1 = MessageMerger()
        m2 = MessageMerger()
        assert m1 is not m2


class TestMergeSingleMessage:
    """Test merging a single message."""

    def test_single_message_returns_content(self, merger):
        """Test that single message returns just the content."""
        msg = MailboxMessage(content="Fix the authentication bug")
        result = merger.merge([msg])

        assert "Fix the authentication bug" in result

    def test_single_message_with_sender(self, merger):
        """Test single message includes sender attribution."""
        msg = MailboxMessage(
            content="Add unit tests",
            sender="senior-dev@company.com",
        )
        result = merger.merge([msg])

        assert "Add unit tests" in result
        assert "senior-dev@company.com" in result

    def test_single_anonymous_message_no_attribution(self, merger):
        """Test anonymous message doesn't include attribution."""
        msg = MailboxMessage(content="Simple change", sender="anonymous")
        result = merger.merge([msg])

        assert "Simple change" in result
        assert "anonymous" not in result


class TestMergeMultipleMessages:
    """Test merging multiple messages."""

    def test_multiple_messages_header(self, merger):
        """Test multiple messages include header with count."""
        messages = [
            MailboxMessage(content="Change 1"),
            MailboxMessage(content="Change 2"),
        ]
        result = merger.merge(messages)

        assert "2 messages" in result
        assert "Consolidated Change Requests" in result

    def test_multiple_messages_all_content_included(self, merger):
        """Test all message content is included."""
        messages = [
            MailboxMessage(content="First change request"),
            MailboxMessage(content="Second change request"),
            MailboxMessage(content="Third change request"),
        ]
        result = merger.merge(messages)

        assert "First change request" in result
        assert "Second change request" in result
        assert "Third change request" in result

    def test_messages_numbered(self, merger):
        """Test messages are numbered."""
        messages = [
            MailboxMessage(content="Change A"),
            MailboxMessage(content="Change B"),
        ]
        result = merger.merge(messages)

        assert "Request 1" in result
        assert "Request 2" in result

    def test_footer_instructions(self, merger):
        """Test footer includes instructions."""
        messages = [
            MailboxMessage(content="A"),
            MailboxMessage(content="B"),
        ]
        result = merger.merge(messages)

        assert "Please address ALL" in result
        assert "2 change requests" in result


class TestPriorityLabels:
    """Test priority label formatting.

    Note: Priority labels only appear when merging multiple messages.
    Single messages use a simpler format without labels.
    """

    def test_urgent_priority_label_in_multiple(self, merger):
        """Test urgent messages get label when multiple messages."""
        messages = [
            MailboxMessage(content="Urgent fix", priority=Priority.URGENT),
            MailboxMessage(content="Normal message"),  # Need 2+ for labels
        ]
        result = merger.merge(messages)

        assert "[URGENT]" in result

    def test_high_priority_label(self, merger):
        """Test high priority messages get label."""
        messages = [
            MailboxMessage(content="Important", priority=Priority.HIGH),
            MailboxMessage(content="Normal"),  # Should not have label
        ]
        result = merger.merge(messages)

        assert "[HIGH]" in result

    def test_normal_priority_no_label(self, merger):
        """Test normal priority has no label in single message."""
        messages = [
            MailboxMessage(content="Regular change", priority=Priority.NORMAL),
        ]
        result = merger.merge(messages)

        # Single message uses simple format - no priority labels
        assert "[NORMAL]" not in result
        assert "[HIGH]" not in result
        assert "[LOW]" not in result
        assert "[URGENT]" not in result

    def test_low_priority_label_in_multiple(self, merger):
        """Test low priority messages get label when multiple messages."""
        messages = [
            MailboxMessage(content="Minor", priority=Priority.LOW),
            MailboxMessage(content="Another", priority=Priority.NORMAL),
        ]
        result = merger.merge(messages)

        assert "[LOW]" in result

    def test_priority_order_instructions(self, merger):
        """Test footer mentions priority ordering."""
        messages = [
            MailboxMessage(content="A"),
            MailboxMessage(content="B"),
        ]
        result = merger.merge(messages)

        assert "URGENT" in result
        assert "HIGH" in result


class TestSenderAttribution:
    """Test sender attribution in merged messages."""

    def test_sender_in_merged_output(self, merger):
        """Test sender is included in merged output."""
        messages = [
            MailboxMessage(content="Review needed", sender="reviewer@test.com"),
        ]
        result = merger.merge(messages)

        assert "reviewer@test.com" in result

    def test_multiple_senders(self, merger):
        """Test multiple different senders."""
        messages = [
            MailboxMessage(content="Change A", sender="user1"),
            MailboxMessage(content="Change B", sender="user2"),
        ]
        result = merger.merge(messages)

        assert "user1" in result
        assert "user2" in result

    def test_anonymous_not_shown_in_merged(self, merger):
        """Test anonymous sender not explicitly shown."""
        messages = [
            MailboxMessage(content="Change A", sender="anonymous"),
            MailboxMessage(content="Change B", sender="named-user"),
        ]
        result = merger.merge(messages)

        # anonymous should not appear as attribution
        # (it might appear in other contexts, but not as "(from anonymous)")
        assert "(from anonymous)" not in result
        assert "(from named-user)" in result


class TestEdgeCases:
    """Test edge cases for message merging."""

    def test_empty_list_raises_error(self, merger):
        """Test merging empty list raises ValueError."""
        with pytest.raises(ValueError, match="Cannot merge empty message list"):
            merger.merge([])

    def test_whitespace_content_preserved(self, merger):
        """Test that content whitespace is preserved."""
        msg = MailboxMessage(content="  Indented content\n  with newlines  ")
        result = merger.merge([msg])

        assert "Indented content" in result
        assert "with newlines" in result

    def test_special_characters_preserved(self, merger):
        """Test special characters in content preserved."""
        msg = MailboxMessage(content="Code: `func()` and **bold** text")
        result = merger.merge([msg])

        assert "`func()`" in result
        assert "**bold**" in result


class TestMergeToSingleContent:
    """Test the simpler merge_to_single_content method."""

    def test_single_message(self, merger):
        """Test single message returns just content."""
        msg = MailboxMessage(content="Simple content")
        result = merger.merge_to_single_content([msg])

        assert result == "Simple content"

    def test_multiple_messages_concatenated(self, merger):
        """Test multiple messages are concatenated with separators."""
        messages = [
            MailboxMessage(content="First"),
            MailboxMessage(content="Second"),
            MailboxMessage(content="Third"),
        ]
        result = merger.merge_to_single_content(messages)

        assert "First" in result
        assert "Second" in result
        assert "Third" in result
        assert "---" in result  # Separator

    def test_empty_list_raises_error(self, merger):
        """Test empty list raises ValueError."""
        with pytest.raises(ValueError):
            merger.merge_to_single_content([])


class TestTimestampInHeader:
    """Test timestamp formatting in merged output."""

    def test_header_contains_timestamp(self, merger):
        """Test merged header contains processing timestamp."""
        messages = [
            MailboxMessage(content="A"),
            MailboxMessage(content="B"),
        ]
        result = merger.merge(messages)

        assert "Processed at:" in result
        # Should contain a date-like string
        assert "202" in result or "203" in result  # Year prefix


class TestMessageOrdering:
    """Test that message ordering is preserved."""

    def test_message_order_preserved(self, merger):
        """Test messages maintain their input order in output."""
        messages = [
            MailboxMessage(content="FIRST_MARKER"),
            MailboxMessage(content="SECOND_MARKER"),
            MailboxMessage(content="THIRD_MARKER"),
        ]
        result = merger.merge(messages)

        # Find positions
        first_pos = result.find("FIRST_MARKER")
        second_pos = result.find("SECOND_MARKER")
        third_pos = result.find("THIRD_MARKER")

        assert first_pos < second_pos < third_pos


class TestFormatSingleMessage:
    """Test the internal _format_single_message method."""

    def test_single_message_content_only(self, merger):
        """Test single message formatting with content only."""
        msg = MailboxMessage(content="Simple task", sender="anonymous")
        result = merger._format_single_message(msg)

        assert result == "Simple task"

    def test_single_message_with_named_sender(self, merger):
        """Test single message with named sender includes attribution."""
        msg = MailboxMessage(content="Important task", sender="admin@test.com")
        result = merger._format_single_message(msg)

        assert "Important task" in result
        assert "admin@test.com" in result
        assert "---" in result  # Separator before attribution
        assert "*From:" in result

    def test_single_message_multiline_content(self, merger):
        """Test single message with multiline content."""
        content = "Line 1\nLine 2\nLine 3"
        msg = MailboxMessage(content=content)
        result = merger._format_single_message(msg)

        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result


class TestFormatMultipleMessages:
    """Test the internal _format_multiple_messages method."""

    def test_two_messages_basic(self, merger):
        """Test formatting two basic messages."""
        messages = [
            MailboxMessage(content="Task A"),
            MailboxMessage(content="Task B"),
        ]
        result = merger._format_multiple_messages(messages)

        assert "Task A" in result
        assert "Task B" in result
        assert "2 messages" in result

    def test_three_messages_with_senders(self, merger):
        """Test formatting three messages with different senders."""
        messages = [
            MailboxMessage(content="First", sender="user1"),
            MailboxMessage(content="Second", sender="user2"),
            MailboxMessage(content="Third", sender="user3"),
        ]
        result = merger._format_multiple_messages(messages)

        assert "user1" in result
        assert "user2" in result
        assert "user3" in result


class TestBuildHeader:
    """Test the internal _build_header method."""

    def test_header_count_two(self, merger):
        """Test header shows correct count for two messages."""
        messages = [MailboxMessage(content="A"), MailboxMessage(content="B")]
        result = merger._build_header(messages)

        assert "2 messages" in result

    def test_header_count_five(self, merger):
        """Test header shows correct count for five messages."""
        messages = [MailboxMessage(content=f"Msg {i}") for i in range(5)]
        result = merger._build_header(messages)

        assert "5 messages" in result

    def test_header_contains_consolidated_title(self, merger):
        """Test header contains title."""
        messages = [MailboxMessage(content="X"), MailboxMessage(content="Y")]
        result = merger._build_header(messages)

        assert "Consolidated Change Requests" in result

    def test_header_contains_processed_at(self, merger):
        """Test header contains timestamp."""
        messages = [MailboxMessage(content="X"), MailboxMessage(content="Y")]
        result = merger._build_header(messages)

        assert "Processed at:" in result


class TestBuildBody:
    """Test the internal _build_body method."""

    def test_body_numbered_requests(self, merger):
        """Test body contains numbered requests."""
        messages = [
            MailboxMessage(content="Alpha"),
            MailboxMessage(content="Beta"),
            MailboxMessage(content="Gamma"),
        ]
        result = merger._build_body(messages)

        assert "Request 1" in result
        assert "Request 2" in result
        assert "Request 3" in result

    def test_body_with_priority_labels(self, merger):
        """Test body includes priority labels."""
        messages = [
            MailboxMessage(content="Urgent", priority=Priority.URGENT),
            MailboxMessage(content="High", priority=Priority.HIGH),
            MailboxMessage(content="Low", priority=Priority.LOW),
        ]
        result = merger._build_body(messages)

        assert "[URGENT]" in result
        assert "[HIGH]" in result
        assert "[LOW]" in result

    def test_body_separators_between_messages(self, merger):
        """Test messages are separated by dividers."""
        messages = [
            MailboxMessage(content="One"),
            MailboxMessage(content="Two"),
        ]
        result = merger._build_body(messages)

        assert "---" in result


class TestGetPriorityLabel:
    """Test the internal _get_priority_label method."""

    def test_low_priority_label(self, merger):
        """Test low priority returns [LOW]."""
        assert merger._get_priority_label(Priority.LOW) == " [LOW]"

    def test_normal_priority_no_label(self, merger):
        """Test normal priority returns empty string."""
        assert merger._get_priority_label(Priority.NORMAL) == ""

    def test_high_priority_label(self, merger):
        """Test high priority returns [HIGH]."""
        assert merger._get_priority_label(Priority.HIGH) == " [HIGH]"

    def test_urgent_priority_label(self, merger):
        """Test urgent priority returns [URGENT]."""
        assert merger._get_priority_label(Priority.URGENT) == " [URGENT]"

    def test_unknown_priority_empty(self, merger):
        """Test unknown priority value returns empty string."""
        assert merger._get_priority_label(99) == ""
        assert merger._get_priority_label(-1) == ""


class TestBuildFooter:
    """Test the internal _build_footer method."""

    def test_footer_count_two(self, merger):
        """Test footer shows correct count."""
        result = merger._build_footer(2)

        assert "ALL 2 change requests" in result

    def test_footer_count_ten(self, merger):
        """Test footer with larger count."""
        result = merger._build_footer(10)

        assert "ALL 10 change requests" in result

    def test_footer_priority_instructions(self, merger):
        """Test footer includes priority instructions."""
        result = merger._build_footer(3)

        assert "URGENT" in result
        assert "HIGH" in result
        assert "conflict" in result.lower()


class TestUnicodeContent:
    """Test unicode content handling."""

    def test_unicode_in_single_message(self, merger):
        """Test single message with unicode."""
        msg = MailboxMessage(content="日本語テスト 🚀 αβγ")
        result = merger.merge([msg])

        assert "日本語テスト" in result
        assert "🚀" in result
        assert "αβγ" in result

    def test_unicode_in_multiple_messages(self, merger):
        """Test multiple messages with unicode."""
        messages = [
            MailboxMessage(content="Hello 世界", sender="用户"),
            MailboxMessage(content="Привет мир", sender="пользователь"),
        ]
        result = merger.merge(messages)

        assert "世界" in result
        assert "Привет" in result
        assert "用户" in result
        assert "пользователь" in result

    def test_unicode_sender(self, merger):
        """Test unicode in sender field."""
        msg = MailboxMessage(content="Test", sender="日本太郎")
        result = merger.merge([msg])

        assert "日本太郎" in result


class TestLongContent:
    """Test handling of long content."""

    def test_very_long_single_message(self, merger):
        """Test single message with very long content."""
        content = "A" * 10000
        msg = MailboxMessage(content=content)
        result = merger.merge([msg])

        assert "A" * 100 in result  # At least some content present
        assert len(result) >= 10000

    def test_very_long_multiple_messages(self, merger):
        """Test multiple messages with long content."""
        messages = [
            MailboxMessage(content="B" * 5000),
            MailboxMessage(content="C" * 5000),
        ]
        result = merger.merge(messages)

        assert "B" * 100 in result
        assert "C" * 100 in result


class TestMergeToSingleContentExtended:
    """Extended tests for merge_to_single_content."""

    def test_preserves_order(self, merger):
        """Test content order is preserved."""
        messages = [
            MailboxMessage(content="FIRST"),
            MailboxMessage(content="SECOND"),
            MailboxMessage(content="THIRD"),
        ]
        result = merger.merge_to_single_content(messages)

        first_pos = result.find("FIRST")
        second_pos = result.find("SECOND")
        third_pos = result.find("THIRD")

        assert first_pos < second_pos < third_pos

    def test_ignores_priority(self, merger):
        """Test priority doesn't affect simple merge."""
        messages = [
            MailboxMessage(content="Low", priority=Priority.LOW),
            MailboxMessage(content="Urgent", priority=Priority.URGENT),
        ]
        result = merger.merge_to_single_content(messages)

        # Order should be preserved, not sorted by priority
        low_pos = result.find("Low")
        urgent_pos = result.find("Urgent")
        assert low_pos < urgent_pos

    def test_ignores_sender(self, merger):
        """Test sender is not included in simple merge."""
        msg = MailboxMessage(content="Content only", sender="important@user.com")
        result = merger.merge_to_single_content([msg])

        assert "important@user.com" not in result
        assert result == "Content only"


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    def test_all_priorities_mixed(self, merger):
        """Test merging messages with all priority levels."""
        messages = [
            MailboxMessage(content="Normal 1", priority=Priority.NORMAL),
            MailboxMessage(content="Urgent", priority=Priority.URGENT),
            MailboxMessage(content="Low", priority=Priority.LOW),
            MailboxMessage(content="High", priority=Priority.HIGH),
            MailboxMessage(content="Normal 2", priority=Priority.NORMAL),
        ]
        result = merger.merge(messages)

        # All content should be present
        assert "Normal 1" in result
        assert "Urgent" in result
        assert "Low" in result
        assert "High" in result
        assert "Normal 2" in result
        assert "5 messages" in result

    def test_mixed_senders_and_anonymous(self, merger):
        """Test mixing named senders with anonymous."""
        messages = [
            MailboxMessage(content="From user", sender="user@example.com"),
            MailboxMessage(content="Anonymous"),  # Default is anonymous
            MailboxMessage(content="From admin", sender="admin"),
        ]
        result = merger.merge(messages)

        assert "user@example.com" in result
        assert "admin" in result
        # Anonymous attribution should not appear
        assert "(from anonymous)" not in result

    def test_multiline_content_in_multiple(self, merger):
        """Test multiline content in multiple messages."""
        messages = [
            MailboxMessage(content="Line 1\nLine 2"),
            MailboxMessage(content="Paragraph 1\n\nParagraph 2"),
        ]
        result = merger.merge(messages)

        assert "Line 1" in result
        assert "Line 2" in result
        assert "Paragraph 1" in result
        assert "Paragraph 2" in result

    def test_code_blocks_preserved(self, merger):
        """Test that code blocks are preserved."""
        content = "```python\ndef hello():\n    print('world')\n```"
        msg = MailboxMessage(content=content)
        result = merger.merge([msg])

        assert "```python" in result
        assert "def hello():" in result
        assert "```" in result

    def test_markdown_formatting_preserved(self, merger):
        """Test markdown formatting is preserved."""
        content = "# Header\n\n- Item 1\n- Item 2\n\n**Bold** and *italic*"
        msg = MailboxMessage(content=content)
        result = merger.merge([msg])

        assert "# Header" in result
        assert "- Item 1" in result
        assert "**Bold**" in result
        assert "*italic*" in result


class TestEmptyAndWhitespaceContent:
    """Test edge cases with empty and whitespace content."""

    def test_empty_content_single(self, merger):
        """Test single message with empty content."""
        msg = MailboxMessage(content="")
        result = merger.merge([msg])

        # Should not crash, result exists
        assert isinstance(result, str)

    def test_empty_content_multiple(self, merger):
        """Test multiple messages with empty content."""
        messages = [
            MailboxMessage(content=""),
            MailboxMessage(content=""),
        ]
        result = merger.merge(messages)

        assert "2 messages" in result

    def test_whitespace_only_content(self, merger):
        """Test message with whitespace-only content."""
        msg = MailboxMessage(content="   \n\t\n   ")
        result = merger.merge([msg])

        assert isinstance(result, str)

    def test_mixed_empty_and_content(self, merger):
        """Test mix of empty and non-empty messages."""
        messages = [
            MailboxMessage(content=""),
            MailboxMessage(content="Real content"),
            MailboxMessage(content="   "),
        ]
        result = merger.merge(messages)

        assert "Real content" in result
        assert "3 messages" in result


class TestSpecialCharacters:
    """Test special character handling."""

    def test_html_entities(self, merger):
        """Test HTML entities are preserved."""
        msg = MailboxMessage(content="&lt;script&gt; &amp; &quot;test&quot;")
        result = merger.merge([msg])

        assert "&lt;script&gt;" in result
        assert "&amp;" in result

    def test_escape_sequences(self, merger):
        """Test escape sequences are preserved."""
        msg = MailboxMessage(content="Tab:\tNewline:\nCarriage:\r")
        result = merger.merge([msg])

        assert "Tab:\t" in result or "Tab:" in result

    def test_quotes_and_backticks(self, merger):
        """Test quotes and backticks are preserved."""
        msg = MailboxMessage(content="Single ' Double \" Backtick `")
        result = merger.merge([msg])

        assert "'" in result
        assert '"' in result
        assert "`" in result


class TestMessageWithMetadata:
    """Test messages with metadata field (not used in merging but should not interfere)."""

    def test_message_with_metadata(self, merger):
        """Test that metadata doesn't affect merge output."""
        msg = MailboxMessage(
            content="Test",
            metadata={"source": "api", "version": 2, "nested": {"key": "value"}},
        )
        result = merger.merge([msg])

        # Content should be present
        assert "Test" in result
        # Metadata should not appear in output
        assert "source" not in result
        assert "api" not in result

    def test_multiple_with_metadata(self, merger):
        """Test multiple messages with metadata."""
        messages = [
            MailboxMessage(content="A", metadata={"id": 1}),
            MailboxMessage(content="B", metadata={"id": 2}),
        ]
        result = merger.merge(messages)

        assert "A" in result
        assert "B" in result


class TestLargeBatchMerge:
    """Test merging large batches of messages."""

    def test_ten_messages(self, merger):
        """Test merging 10 messages."""
        messages = [MailboxMessage(content=f"Message {i}") for i in range(10)]
        result = merger.merge(messages)

        assert "10 messages" in result
        for i in range(10):
            assert f"Message {i}" in result

    def test_hundred_messages(self, merger):
        """Test merging 100 messages."""
        messages = [MailboxMessage(content=f"Msg{i:03d}") for i in range(100)]
        result = merger.merge(messages)

        assert "100 messages" in result
        # Spot check some messages
        assert "Msg000" in result
        assert "Msg050" in result
        assert "Msg099" in result

    def test_large_batch_to_single_content(self, merger):
        """Test merge_to_single_content with large batch."""
        messages = [MailboxMessage(content=f"Content {i}") for i in range(50)]
        result = merger.merge_to_single_content(messages)

        assert "Content 0" in result
        assert "Content 49" in result


class TestOutputStructure:
    """Test the structure of merged output."""

    def test_multiple_messages_has_three_sections(self, merger):
        """Test merged output has header, body, and footer."""
        messages = [
            MailboxMessage(content="A"),
            MailboxMessage(content="B"),
        ]
        result = merger.merge(messages)

        # Header elements
        assert "Consolidated Change Requests" in result
        assert "Processed at:" in result

        # Body elements
        assert "Request 1" in result
        assert "Request 2" in result

        # Footer elements
        assert "Please address ALL" in result

    def test_single_message_simple_structure(self, merger):
        """Test single message has simpler structure."""
        msg = MailboxMessage(content="Simple task")
        result = merger.merge([msg])

        # Should NOT have multi-message header/footer
        assert "Consolidated Change Requests" not in result
        assert "Please address ALL" not in result
        assert "Request 1" not in result

        # Should have content
        assert "Simple task" in result


class TestTimestampBehavior:
    """Test timestamp-related behavior."""

    def test_message_timestamp_not_in_output(self, merger):
        """Test that individual message timestamps don't appear in output."""
        specific_time = datetime(2024, 1, 15, 10, 30, 0)
        msg = MailboxMessage(content="Test", timestamp=specific_time)
        result = merger.merge([msg])

        # Individual message timestamp should not appear
        assert "2024-01-15" not in result
        assert "10:30" not in result

    def test_header_uses_current_time(self, merger):
        """Test header timestamp is current (processing) time."""
        messages = [
            MailboxMessage(content="A"),
            MailboxMessage(content="B"),
        ]
        result = merger.merge(messages)

        # Should contain current year
        current_year = str(datetime.now().year)
        assert current_year in result
