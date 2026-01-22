"""Tests for MCP mailbox tools.

Tests send_message, check_mailbox, and clear_mailbox MCP tool implementations.
"""

import pytest

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestSendMessageTool:
    """Test the send_message MCP tool."""

    def test_send_simple_message(self, temp_dir):
        """Test sending a basic message."""
        from claude_task_master.mcp.tools import send_message

        result = send_message(temp_dir, content="Test message")

        assert result["success"] is True
        assert result["message_id"] is not None
        assert len(result["message_id"]) == 36  # UUID format
        assert "Test message" not in result["message"]  # Message not echoed
        assert "successfully" in result["message"]

    def test_send_message_with_sender(self, temp_dir):
        """Test sending message with custom sender."""
        from claude_task_master.mcp.tools import check_mailbox, send_message

        send_message(temp_dir, content="Test", sender="test@example.com")
        status = check_mailbox(temp_dir)

        assert status["count"] == 1
        assert status["previews"][0]["sender"] == "test@example.com"

    def test_send_message_with_priority(self, temp_dir):
        """Test sending message with priority."""
        from claude_task_master.mcp.tools import check_mailbox, send_message

        send_message(temp_dir, content="Urgent!", priority=3)
        status = check_mailbox(temp_dir)

        assert status["previews"][0]["priority"] == 3

    def test_send_message_empty_content_fails(self, temp_dir):
        """Test that empty content fails."""
        from claude_task_master.mcp.tools import send_message

        result = send_message(temp_dir, content="")

        assert result["success"] is False
        assert "empty" in result["error"].lower()

    def test_send_message_whitespace_content_fails(self, temp_dir):
        """Test that whitespace-only content fails."""
        from claude_task_master.mcp.tools import send_message

        result = send_message(temp_dir, content="   \n\t  ")

        assert result["success"] is False
        assert "empty" in result["error"].lower()

    def test_send_message_invalid_priority_fails(self, temp_dir):
        """Test that invalid priority fails."""
        from claude_task_master.mcp.tools import send_message

        result = send_message(temp_dir, content="Test", priority=5)

        assert result["success"] is False
        assert "priority" in result["error"].lower()

    def test_send_message_negative_priority_fails(self, temp_dir):
        """Test that negative priority fails."""
        from claude_task_master.mcp.tools import send_message

        result = send_message(temp_dir, content="Test", priority=-1)

        assert result["success"] is False
        assert "priority" in result["error"].lower()

    def test_send_multiple_messages(self, temp_dir):
        """Test sending multiple messages."""
        from claude_task_master.mcp.tools import check_mailbox, send_message

        send_message(temp_dir, content="Message 1")
        send_message(temp_dir, content="Message 2")
        send_message(temp_dir, content="Message 3")

        status = check_mailbox(temp_dir)

        assert status["count"] == 3

    def test_send_message_with_custom_state_dir(self, temp_dir, state_dir):
        """Test sending message to custom state directory."""
        from claude_task_master.mcp.tools import check_mailbox, send_message

        result = send_message(temp_dir, content="Custom dir test", state_dir=str(state_dir))

        assert result["success"] is True

        status = check_mailbox(temp_dir, state_dir=str(state_dir))
        assert status["count"] == 1


class TestCheckMailboxTool:
    """Test the check_mailbox MCP tool."""

    def test_check_empty_mailbox(self, temp_dir):
        """Test checking empty mailbox."""
        from claude_task_master.mcp.tools import check_mailbox

        result = check_mailbox(temp_dir)

        assert result["success"] is True
        assert result["count"] == 0
        assert result["previews"] == []
        assert result["last_checked"] is None
        assert result["total_messages_received"] == 0

    def test_check_mailbox_with_messages(self, temp_dir):
        """Test checking mailbox with messages."""
        from claude_task_master.mcp.tools import check_mailbox, send_message

        send_message(temp_dir, content="Test message", sender="tester")
        result = check_mailbox(temp_dir)

        assert result["success"] is True
        assert result["count"] == 1
        assert len(result["previews"]) == 1
        assert result["previews"][0]["sender"] == "tester"
        assert "Test message" in result["previews"][0]["content_preview"]

    def test_check_mailbox_previews_sorted_by_priority(self, temp_dir):
        """Test previews are sorted by priority."""
        from claude_task_master.mcp.tools import check_mailbox, send_message

        send_message(temp_dir, content="Low priority", priority=0)
        send_message(temp_dir, content="High priority", priority=2)
        send_message(temp_dir, content="Normal priority", priority=1)

        result = check_mailbox(temp_dir)

        assert result["previews"][0]["content_preview"] == "High priority"
        assert result["previews"][1]["content_preview"] == "Normal priority"
        assert result["previews"][2]["content_preview"] == "Low priority"

    def test_check_mailbox_total_includes_cleared(self, temp_dir):
        """Test total_messages_received includes cleared messages."""
        from claude_task_master.mcp.tools import check_mailbox, clear_mailbox, send_message

        send_message(temp_dir, content="Message 1")
        send_message(temp_dir, content="Message 2")
        clear_mailbox(temp_dir)
        send_message(temp_dir, content="Message 3")

        result = check_mailbox(temp_dir)

        assert result["count"] == 1  # Current count
        assert result["total_messages_received"] == 3  # All-time total

    def test_check_mailbox_with_custom_state_dir(self, temp_dir, state_dir):
        """Test checking mailbox with custom state directory."""
        from claude_task_master.mcp.tools import check_mailbox, send_message

        send_message(temp_dir, content="Test", state_dir=str(state_dir))
        result = check_mailbox(temp_dir, state_dir=str(state_dir))

        assert result["success"] is True
        assert result["count"] == 1


class TestClearMailboxTool:
    """Test the clear_mailbox MCP tool."""

    def test_clear_empty_mailbox(self, temp_dir):
        """Test clearing empty mailbox."""
        from claude_task_master.mcp.tools import clear_mailbox

        result = clear_mailbox(temp_dir)

        assert result["success"] is True
        assert result["messages_cleared"] == 0
        assert "0 message" in result["message"]

    def test_clear_mailbox_with_messages(self, temp_dir):
        """Test clearing mailbox with messages."""
        from claude_task_master.mcp.tools import check_mailbox, clear_mailbox, send_message

        send_message(temp_dir, content="Message 1")
        send_message(temp_dir, content="Message 2")
        send_message(temp_dir, content="Message 3")

        result = clear_mailbox(temp_dir)

        assert result["success"] is True
        assert result["messages_cleared"] == 3
        assert "3 message" in result["message"]

        # Verify cleared
        status = check_mailbox(temp_dir)
        assert status["count"] == 0

    def test_clear_mailbox_updates_last_checked(self, temp_dir):
        """Test that clearing updates last_checked."""
        from claude_task_master.mcp.tools import check_mailbox, clear_mailbox, send_message

        send_message(temp_dir, content="Test")
        clear_mailbox(temp_dir)

        status = check_mailbox(temp_dir)
        assert status["last_checked"] is not None

    def test_clear_mailbox_with_custom_state_dir(self, temp_dir, state_dir):
        """Test clearing with custom state directory."""
        from claude_task_master.mcp.tools import check_mailbox, clear_mailbox, send_message

        send_message(temp_dir, content="Test", state_dir=str(state_dir))
        result = clear_mailbox(temp_dir, state_dir=str(state_dir))

        assert result["success"] is True
        assert result["messages_cleared"] == 1

        status = check_mailbox(temp_dir, state_dir=str(state_dir))
        assert status["count"] == 0


class TestMailboxToolsIntegration:
    """Integration tests for mailbox tools."""

    def test_full_send_check_clear_cycle(self, temp_dir):
        """Test complete send -> check -> clear cycle."""
        from claude_task_master.mcp.tools import check_mailbox, clear_mailbox, send_message

        # Send messages
        result1 = send_message(temp_dir, content="First message", sender="user1")
        result2 = send_message(temp_dir, content="Second message", priority=2)

        assert result1["success"] is True
        assert result2["success"] is True

        # Check
        status = check_mailbox(temp_dir)
        assert status["count"] == 2

        # Clear
        clear_result = clear_mailbox(temp_dir)
        assert clear_result["messages_cleared"] == 2

        # Verify empty
        final_status = check_mailbox(temp_dir)
        assert final_status["count"] == 0
        assert final_status["total_messages_received"] == 2

    def test_concurrent_state_directories(self, temp_dir):
        """Test that different state directories are independent."""
        from claude_task_master.mcp.tools import check_mailbox, send_message

        # Create two separate state directories
        custom_state_dir_1 = temp_dir / ".state-dir-1"
        custom_state_dir_2 = temp_dir / ".state-dir-2"

        # Send to first state dir
        send_message(temp_dir, content="First dir message", state_dir=str(custom_state_dir_1))

        # Send to second state dir
        send_message(temp_dir, content="Second dir message", state_dir=str(custom_state_dir_2))

        # Check they're independent
        status_1 = check_mailbox(temp_dir, state_dir=str(custom_state_dir_1))
        status_2 = check_mailbox(temp_dir, state_dir=str(custom_state_dir_2))

        assert status_1["count"] == 1
        assert status_2["count"] == 1

        # Different content
        assert "First" in status_1["previews"][0]["content_preview"]
        assert "Second" in status_2["previews"][0]["content_preview"]


class TestResponseModels:
    """Test that response models are properly structured."""

    def test_send_message_result_model(self, temp_dir):
        """Test SendMessageResult model structure."""
        from claude_task_master.mcp.tools import send_message

        result = send_message(temp_dir, content="Test")

        # Check all expected fields exist
        assert "success" in result
        assert "message_id" in result
        assert "message" in result
        assert "error" in result

    def test_mailbox_status_result_model(self, temp_dir):
        """Test MailboxStatusResult model structure."""
        from claude_task_master.mcp.tools import check_mailbox

        result = check_mailbox(temp_dir)

        assert "success" in result
        assert "count" in result
        assert "previews" in result
        assert "last_checked" in result
        assert "total_messages_received" in result
        assert "error" in result

    def test_clear_mailbox_result_model(self, temp_dir):
        """Test ClearMailboxResult model structure."""
        from claude_task_master.mcp.tools import clear_mailbox

        result = clear_mailbox(temp_dir)

        assert "success" in result
        assert "messages_cleared" in result
        assert "message" in result
        assert "error" in result
