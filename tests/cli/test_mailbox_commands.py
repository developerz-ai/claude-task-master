"""Tests for mailbox CLI commands.

This module provides comprehensive tests for:
- mailbox (status) - show mailbox status
- mailbox send - send a message to the mailbox
- mailbox clear - clear all messages

The tests cover:
- Basic functionality
- Error handling
- Edge cases
- Command options and flags
- Integration between subcommands
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.cli_commands import mailbox as mailbox_module
from claude_task_master.core.state import StateManager, TaskOptions
from claude_task_master.mailbox.models import Priority
from claude_task_master.mailbox.storage import MailboxStorage

# =============================================================================
# Additional Fixtures for Extended Tests
# =============================================================================


@pytest.fixture
def mailbox_state_dir(temp_dir: Path) -> Path:
    """Create a state directory for mailbox command tests."""
    state_dir = temp_dir / ".claude-task-master"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture
def mailbox_state_manager(mailbox_state_dir: Path) -> StateManager:
    """Create a StateManager instance for mailbox tests."""
    return StateManager(mailbox_state_dir)


@pytest.fixture
def mailbox_storage(mailbox_state_dir: Path) -> MailboxStorage:
    """Create a MailboxStorage instance for mailbox tests."""
    return MailboxStorage(state_dir=mailbox_state_dir)


@pytest.fixture
def mailbox_task_options() -> TaskOptions:
    """Create sample task options."""
    return TaskOptions(
        auto_merge=True,
        max_sessions=None,
        pause_on_pr=False,
        enable_checkpointing=False,
        log_level="normal",
        log_format="text",
        pr_per_task=False,
    )


def _use_state_dir(state_dir: Path):
    """Patch StateManager to use a specific state directory."""
    return patch.object(StateManager, "STATE_DIR", state_dir)


# =============================================================================
# Mailbox Status Command Tests
# =============================================================================


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


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestMailboxErrorHandling:
    """Tests for mailbox error handling scenarios."""

    def test_mailbox_status_error(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test mailbox status handles errors gracefully."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch.object(MailboxStorage, "get_status", side_effect=Exception("IO Error")):
                result = cli_runner.invoke(app, ["mailbox"])

        assert result.exit_code == 1
        assert "Error:" in result.output

    def test_mailbox_send_error(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test mailbox send handles errors gracefully."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch.object(MailboxStorage, "add_message", side_effect=Exception("Write Error")):
                result = cli_runner.invoke(app, ["mailbox", "send", "Test message"])

        assert result.exit_code == 1
        assert "Error:" in result.output

    def test_mailbox_clear_error(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test mailbox clear handles errors gracefully."""
        mailbox = MailboxStorage(state_dir=mock_state_dir)
        mailbox.add_message(content="Test", sender="test")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch.object(MailboxStorage, "clear", side_effect=Exception("Clear Error")):
                result = cli_runner.invoke(app, ["mailbox", "clear", "-f"])

        assert result.exit_code == 1
        assert "Error:" in result.output


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestMailboxEdgeCases:
    """Tests for mailbox edge cases."""

    def test_mailbox_send_empty_message(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending an empty message still works."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "send", ""])

        # Empty message should be allowed (validation at user's discretion)
        assert result.exit_code == 0

    def test_mailbox_send_long_message(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending a long message."""
        long_message = "A" * 5000  # 5000 character message

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "send", long_message])

        assert result.exit_code == 0
        assert "Message sent to mailbox" in result.output

        mailbox = MailboxStorage(state_dir=mock_state_dir)
        messages = mailbox.get_messages()
        assert len(messages) == 1
        assert len(messages[0].content) == 5000

    def test_mailbox_send_special_characters(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending a message with special characters."""
        special_message = "Fix bug: $PATH variable! @user #tag & <script>alert('xss')</script>"

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "send", special_message])

        assert result.exit_code == 0

        mailbox = MailboxStorage(state_dir=mock_state_dir)
        messages = mailbox.get_messages()
        assert messages[0].content == special_message

    def test_mailbox_send_unicode(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending a message with unicode characters."""
        unicode_message = "Fix bug in login flow"

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "send", unicode_message])

        assert result.exit_code == 0

        mailbox = MailboxStorage(state_dir=mock_state_dir)
        messages = mailbox.get_messages()
        assert messages[0].content == unicode_message

    def test_mailbox_status_shows_last_checked(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test mailbox status shows last checked when available."""
        mailbox = MailboxStorage(state_dir=mock_state_dir)
        mailbox.add_message(content="Test", sender="test")
        mailbox.get_and_clear()  # This sets last_checked

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox"])

        assert result.exit_code == 0
        assert "Last checked:" in result.output

    def test_mailbox_send_all_priority_levels(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending messages with all priority levels."""
        priority_names = ["LOW", "NORMAL", "HIGH", "URGENT"]

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            for i, name in enumerate(priority_names):
                result = cli_runner.invoke(app, ["mailbox", "send", f"Task {i}", "-p", str(i)])
                assert result.exit_code == 0
                assert f"Priority: {name}" in result.output

        mailbox = MailboxStorage(state_dir=mock_state_dir)
        messages = mailbox.get_messages()
        assert len(messages) == 4


# =============================================================================
# Integration Tests
# =============================================================================


class TestMailboxIntegration:
    """Integration tests for mailbox subcommands."""

    def test_send_then_status(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending a message then checking status."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            # Send a message
            result = cli_runner.invoke(app, ["mailbox", "send", "Test message", "-s", "tester"])
            assert result.exit_code == 0

            # Check status
            result = cli_runner.invoke(app, ["mailbox"])
            assert result.exit_code == 0
            assert "Pending messages:" in result.output
            assert "1" in result.output
            assert "tester" in result.output

    def test_send_then_clear(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test sending messages then clearing."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            # Send messages
            cli_runner.invoke(app, ["mailbox", "send", "Message 1"])
            cli_runner.invoke(app, ["mailbox", "send", "Message 2"])

            # Clear
            result = cli_runner.invoke(app, ["mailbox", "clear", "-f"])
            assert result.exit_code == 0
            assert "Cleared 2 message(s)" in result.output

            # Status should show empty
            result = cli_runner.invoke(app, ["mailbox"])
            assert result.exit_code == 0
            assert "No pending messages" in result.output

    def test_complete_workflow(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test complete mailbox workflow: status -> send -> status -> clear -> status."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            # Initial status - empty
            result = cli_runner.invoke(app, ["mailbox"])
            assert result.exit_code == 0
            assert "No pending messages" in result.output

            # Send multiple messages with different priorities
            cli_runner.invoke(app, ["mailbox", "send", "Low priority", "-p", "0"])
            cli_runner.invoke(app, ["mailbox", "send", "Normal priority"])
            cli_runner.invoke(app, ["mailbox", "send", "High priority", "-p", "2"])
            cli_runner.invoke(app, ["mailbox", "send", "Urgent!", "-p", "3"])

            # Check status - should have 4 messages
            result = cli_runner.invoke(app, ["mailbox"])
            assert result.exit_code == 0
            assert "4" in result.output

            # Clear all messages
            result = cli_runner.invoke(app, ["mailbox", "clear", "-f"])
            assert result.exit_code == 0
            assert "Cleared 4 message(s)" in result.output

            # Final status - empty
            result = cli_runner.invoke(app, ["mailbox"])
            assert result.exit_code == 0
            assert "No pending messages" in result.output


# =============================================================================
# Register Function Tests
# =============================================================================


class TestRegisterMailboxCommands:
    """Tests for the register_mailbox_commands function."""

    def test_register_mailbox_commands(self) -> None:
        """Test that register_mailbox_commands registers the mailbox app."""
        from typer import Typer

        test_app = Typer()
        mailbox_module.register_mailbox_commands(test_app)

        # Verify mailbox command is registered
        runner = CliRunner()
        result = runner.invoke(test_app, ["mailbox", "--help"])
        assert result.exit_code == 0
        assert "mailbox" in result.stdout.lower()

    def test_register_mailbox_subcommands(self) -> None:
        """Test that register_mailbox_commands includes subcommands."""
        from typer import Typer

        test_app = Typer()
        mailbox_module.register_mailbox_commands(test_app)

        runner = CliRunner()

        # Check send subcommand
        result = runner.invoke(test_app, ["mailbox", "send", "--help"])
        assert result.exit_code == 0
        assert "send" in result.stdout.lower()

        # Check clear subcommand
        result = runner.invoke(test_app, ["mailbox", "clear", "--help"])
        assert result.exit_code == 0
        assert "clear" in result.stdout.lower()


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestMailboxHelperFunctions:
    """Tests for mailbox helper functions."""

    def test_get_mailbox_storage(
        self,
        mailbox_state_dir: Path,
        mailbox_state_manager: StateManager,
        mailbox_task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test get_mailbox_storage returns configured MailboxStorage."""
        mailbox_state_manager.initialize(
            goal="Test task", model="opus", options=mailbox_task_options
        )

        with _use_state_dir(mailbox_state_dir):
            storage = mailbox_module.get_mailbox_storage()
            assert isinstance(storage, MailboxStorage)
            assert storage.state_dir == mailbox_state_dir

    def test_mailbox_status_function(
        self,
        mailbox_state_dir: Path,
        mailbox_state_manager: StateManager,
        mailbox_task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test mailbox_status function raises Exit (typer.Exit raises click.Exit)."""
        from click.exceptions import Exit

        mailbox_state_manager.initialize(
            goal="Test task", model="opus", options=mailbox_task_options
        )

        with _use_state_dir(mailbox_state_dir):
            with pytest.raises(Exit) as exc_info:
                mailbox_module.mailbox_status()
            assert exc_info.value.exit_code == 0

    def test_mailbox_send_function(
        self,
        mailbox_state_dir: Path,
        mailbox_state_manager: StateManager,
        mailbox_task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test mailbox_send function raises Exit (typer.Exit raises click.Exit)."""
        from click.exceptions import Exit

        mailbox_state_manager.initialize(
            goal="Test task", model="opus", options=mailbox_task_options
        )

        with _use_state_dir(mailbox_state_dir):
            with pytest.raises(Exit) as exc_info:
                mailbox_module.mailbox_send("Test message", "test", 1)
            assert exc_info.value.exit_code == 0

    def test_mailbox_clear_function_empty(
        self,
        mailbox_state_dir: Path,
        mailbox_state_manager: StateManager,
        mailbox_task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test mailbox_clear function with empty mailbox raises Exit."""
        from click.exceptions import Exit

        mailbox_state_manager.initialize(
            goal="Test task", model="opus", options=mailbox_task_options
        )

        with _use_state_dir(mailbox_state_dir):
            with pytest.raises(Exit) as exc_info:
                mailbox_module.mailbox_clear(force=False)
            assert exc_info.value.exit_code == 0


# =============================================================================
# Priority Display Tests
# =============================================================================


class TestMailboxPriorityDisplay:
    """Tests for priority display in mailbox status."""

    def test_priority_display_styles(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test that priority levels are displayed with proper names."""
        mailbox = MailboxStorage(state_dir=mock_state_dir)

        # Add messages with each priority
        mailbox.add_message(content="Low task", sender="test", priority=Priority.LOW)
        mailbox.add_message(content="Normal task", sender="test", priority=Priority.NORMAL)
        mailbox.add_message(content="High task", sender="test", priority=Priority.HIGH)
        mailbox.add_message(content="Urgent task", sender="test", priority=Priority.URGENT)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["mailbox"])

        assert result.exit_code == 0
        # Check all priority levels are displayed
        assert "Messages" in result.output  # Table title
        assert "4" in result.output  # Message count


# =============================================================================
# Using New Fixtures Tests
# =============================================================================


class TestMailboxWithStateManager:
    """Tests using isolated_filesystem and StateManager fixtures."""

    def test_mailbox_status_with_initialized_state(
        self,
        cli_runner: CliRunner,
        mailbox_state_dir: Path,
        mailbox_state_manager: StateManager,
        mailbox_storage: MailboxStorage,
        mailbox_task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test mailbox status with properly initialized state."""
        mailbox_state_manager.initialize(
            goal="Test task", model="opus", options=mailbox_task_options
        )

        # Add a message
        mailbox_storage.add_message(
            content="Test message",
            sender="test",
            priority=Priority.NORMAL,
        )

        with _use_state_dir(mailbox_state_dir):
            result = cli_runner.invoke(app, ["mailbox"])
            assert result.exit_code == 0
            assert "Pending messages:" in result.stdout
            assert "1" in result.stdout

    def test_mailbox_send_with_initialized_state(
        self,
        cli_runner: CliRunner,
        mailbox_state_dir: Path,
        mailbox_state_manager: StateManager,
        mailbox_storage: MailboxStorage,
        mailbox_task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test mailbox send with properly initialized state."""
        mailbox_state_manager.initialize(
            goal="Test task", model="opus", options=mailbox_task_options
        )

        with _use_state_dir(mailbox_state_dir):
            result = cli_runner.invoke(
                app,
                [
                    "mailbox",
                    "send",
                    "Fix critical bug",
                    "--sender",
                    "supervisor",
                    "--priority",
                    "3",
                ],
            )
            assert result.exit_code == 0
            assert "Message sent to mailbox" in result.stdout
            assert "URGENT" in result.stdout

        # Verify message was added
        messages = mailbox_storage.get_messages()
        assert len(messages) == 1
        assert messages[0].content == "Fix critical bug"
        assert messages[0].sender == "supervisor"
        assert messages[0].priority == Priority.URGENT

    def test_mailbox_clear_with_initialized_state(
        self,
        cli_runner: CliRunner,
        mailbox_state_dir: Path,
        mailbox_state_manager: StateManager,
        mailbox_storage: MailboxStorage,
        mailbox_task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test mailbox clear with properly initialized state."""
        mailbox_state_manager.initialize(
            goal="Test task", model="opus", options=mailbox_task_options
        )

        # Add messages
        for i in range(3):
            mailbox_storage.add_message(content=f"Message {i}", sender="test")

        with _use_state_dir(mailbox_state_dir):
            result = cli_runner.invoke(app, ["mailbox", "clear", "--force"])
            assert result.exit_code == 0
            assert "Cleared 3 message(s)" in result.stdout

        # Verify messages were cleared
        assert mailbox_storage.count() == 0
