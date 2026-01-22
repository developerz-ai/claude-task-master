"""Tests for mailbox CLI commands."""

from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager
from claude_task_master.mailbox.models import Priority
from claude_task_master.mailbox.storage import MailboxStorage


class TestMailboxStatusCommand:
    """Tests for the mailbox status command (claudetm mailbox)."""

    def test_mailbox_status_no_active_task(self, cli_runner, temp_dir):
        """Test mailbox command when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["mailbox"])

        assert result.exit_code == 1
        assert "No active task found" in result.output

    def test_mailbox_status_empty(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test mailbox status when mailbox is empty."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox"])

        assert result.exit_code == 0
        assert "Mailbox Status" in result.output
        assert "No pending messages" in result.output

    def test_mailbox_status_with_messages(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test mailbox status shows messages."""
        # Add a message to the mailbox
        mailbox = MailboxStorage(state_dir=mock_state_dir)
        mailbox.add_message(
            content="Please update the README",
            sender="supervisor",
            priority=Priority.HIGH,
        )

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox"])

        assert result.exit_code == 0
        assert "Mailbox Status" in result.output
        assert "Pending messages:" in result.output
        assert "1" in result.output  # Count
        assert "supervisor" in result.output
        assert "Please update the README" in result.output

    def test_mailbox_status_multiple_messages(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test mailbox status shows multiple messages sorted by priority."""
        mailbox = MailboxStorage(state_dir=mock_state_dir)
        mailbox.add_message(content="Low priority task", sender="cli", priority=Priority.LOW)
        mailbox.add_message(content="Urgent fix needed!", sender="alert", priority=Priority.URGENT)
        mailbox.add_message(content="Normal task", sender="user", priority=Priority.NORMAL)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox"])

        assert result.exit_code == 0
        assert "Pending messages:" in result.output
        assert "3" in result.output  # Count
        # All messages should be visible
        assert "alert" in result.output
        assert "cli" in result.output
        assert "user" in result.output

    def test_mailbox_status_shows_total_received(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test mailbox status shows total received count."""
        mailbox = MailboxStorage(state_dir=mock_state_dir)
        mailbox.add_message(content="Message 1", sender="test")
        mailbox.add_message(content="Message 2", sender="test")
        mailbox.get_and_clear()  # Clear messages
        mailbox.add_message(content="Message 3", sender="test")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox"])

        assert result.exit_code == 0
        assert "Total received:" in result.output
        assert "3" in result.output  # Total received


class TestMailboxSendCommand:
    """Tests for the mailbox send command (claudetm mailbox send)."""

    def test_mailbox_send_no_active_task(self, cli_runner, temp_dir):
        """Test mailbox send when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["mailbox", "send", "Test message"])

        assert result.exit_code == 1
        assert "No active task found" in result.output

    def test_mailbox_send_basic(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending a basic message."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "send", "Please fix the bug"])

        assert result.exit_code == 0
        assert "Message sent to mailbox" in result.output
        assert "ID:" in result.output
        assert "cli" in result.output  # Default sender

        # Verify message was added
        mailbox = MailboxStorage(state_dir=mock_state_dir)
        messages = mailbox.get_messages()
        assert len(messages) == 1
        assert messages[0].content == "Please fix the bug"
        assert messages[0].sender == "cli"

    def test_mailbox_send_with_sender(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending a message with custom sender."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(
                app, ["mailbox", "send", "Task update", "--sender", "supervisor"]
            )

        assert result.exit_code == 0
        assert "supervisor" in result.output

        mailbox = MailboxStorage(state_dir=mock_state_dir)
        messages = mailbox.get_messages()
        assert messages[0].sender == "supervisor"

    def test_mailbox_send_with_priority(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending a message with priority."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "send", "Urgent task", "--priority", "3"])

        assert result.exit_code == 0
        assert "URGENT" in result.output

        mailbox = MailboxStorage(state_dir=mock_state_dir)
        messages = mailbox.get_messages()
        assert messages[0].priority == Priority.URGENT

    def test_mailbox_send_with_short_options(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending a message with short option flags."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(
                app, ["mailbox", "send", "High priority task", "-s", "bot", "-p", "2"]
            )

        assert result.exit_code == 0
        assert "bot" in result.output
        assert "HIGH" in result.output

        mailbox = MailboxStorage(state_dir=mock_state_dir)
        messages = mailbox.get_messages()
        assert messages[0].sender == "bot"
        assert messages[0].priority == Priority.HIGH

    def test_mailbox_send_invalid_priority(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending a message with invalid priority."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "send", "Test", "--priority", "5"])

        assert result.exit_code == 1
        assert "Priority must be between 0 and 3" in result.output

    def test_mailbox_send_negative_priority(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending a message with negative priority."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "send", "Test", "--priority", "-1"])

        assert result.exit_code == 1
        assert "Priority must be between 0 and 3" in result.output


class TestMailboxClearCommand:
    """Tests for the mailbox clear command (claudetm mailbox clear)."""

    def test_mailbox_clear_no_active_task(self, cli_runner, temp_dir):
        """Test mailbox clear when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["mailbox", "clear"])

        assert result.exit_code == 1
        assert "No active task found" in result.output

    def test_mailbox_clear_empty(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test clearing an empty mailbox."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "clear"])

        assert result.exit_code == 0
        assert "Mailbox is already empty" in result.output

    def test_mailbox_clear_with_confirmation(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test clearing mailbox with confirmation."""
        mailbox = MailboxStorage(state_dir=mock_state_dir)
        mailbox.add_message(content="Message 1", sender="test")
        mailbox.add_message(content="Message 2", sender="test")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "clear"], input="y\n")

        assert result.exit_code == 0
        assert "Cleared 2 message(s)" in result.output

        # Verify messages were cleared
        assert mailbox.count() == 0

    def test_mailbox_clear_cancelled(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test clearing mailbox cancelled by user."""
        mailbox = MailboxStorage(state_dir=mock_state_dir)
        mailbox.add_message(content="Message 1", sender="test")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "clear"], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.output

        # Verify messages were NOT cleared
        assert mailbox.count() == 1

    def test_mailbox_clear_force(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test clearing mailbox with --force flag."""
        mailbox = MailboxStorage(state_dir=mock_state_dir)
        mailbox.add_message(content="Message 1", sender="test")
        mailbox.add_message(content="Message 2", sender="test")
        mailbox.add_message(content="Message 3", sender="test")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "clear", "--force"])

        assert result.exit_code == 0
        assert "Cleared 3 message(s)" in result.output
        assert mailbox.count() == 0

    def test_mailbox_clear_force_short(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test clearing mailbox with -f flag."""
        mailbox = MailboxStorage(state_dir=mock_state_dir)
        mailbox.add_message(content="Message", sender="test")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "clear", "-f"])

        assert result.exit_code == 0
        assert "Cleared 1 message(s)" in result.output


class TestMailboxHelp:
    """Tests for mailbox help output."""

    def test_mailbox_help(self, cli_runner):
        """Test mailbox --help shows all subcommands."""
        result = cli_runner.invoke(app, ["mailbox", "--help"])

        assert result.exit_code == 0
        assert "send" in result.output
        assert "clear" in result.output
        assert "mailbox" in result.output.lower()

    def test_mailbox_send_help(self, cli_runner):
        """Test mailbox send --help shows options."""
        result = cli_runner.invoke(app, ["mailbox", "send", "--help"])

        assert result.exit_code == 0
        assert "--sender" in result.output
        assert "--priority" in result.output
        assert "MESSAGE" in result.output.upper() or "message" in result.output

    def test_mailbox_clear_help(self, cli_runner):
        """Test mailbox clear --help shows options."""
        result = cli_runner.invoke(app, ["mailbox", "clear", "--help"])

        assert result.exit_code == 0
        assert "--force" in result.output
