"""Tests for MessageMerger class.

Tests message merging for plan update prompts.
"""

import pytest

from claude_task_master.mailbox.merger import MessageMerger
from claude_task_master.mailbox.models import MailboxMessage, Priority


@pytest.fixture
def merger():
    """Create a MessageMerger instance."""
    return MessageMerger()


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
