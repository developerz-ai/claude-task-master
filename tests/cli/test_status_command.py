"""Tests for the status CLI command."""

from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestStatusCommand:
    """Tests for the status command."""

    def test_status_no_active_task(self, cli_runner, temp_dir):
        """Test status when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 1
        assert "No active task found" in result.output

    def test_status_shows_task_info(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test status shows task information."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "Task Status" in result.output
        assert "Make the app production ready" in result.output
        assert "working" in result.output
        assert "sonnet" in result.output
        assert "3" in result.output  # Session count
        assert "20250115-120000" in result.output  # Run ID

    def test_status_shows_pr_number(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test status shows current PR number when set."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "123" in result.output

    def test_status_shows_options(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test status shows task options."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "Auto-merge:" in result.output
        assert "Max sessions:" in result.output
        assert "Pause on PR:" in result.output

    def test_status_handles_error(self, cli_runner, temp_dir, mock_state_dir):
        """Test status handles errors gracefully."""
        # Create invalid state file
        state_file = mock_state_dir / "state.json"
        state_file.write_text("invalid json{")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 1
        assert "Error:" in result.output
