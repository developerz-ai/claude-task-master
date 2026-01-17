"""Tests for the logs CLI command."""

from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestLogsCommand:
    """Tests for the logs command."""

    def test_logs_no_active_task(self, cli_runner, temp_dir):
        """Test logs when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 1
        assert "No active task found" in result.output

    def test_logs_no_log_file(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_logs_dir
    ):
        """Test logs when no log file exists."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 1
        assert "No log file found" in result.output

    def test_logs_shows_log_content(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_logs_dir,
        mock_log_file,
    ):
        """Test logs shows log content."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 0
        assert "Logs" in result.output
        # Should show last 100 lines by default
        assert "Log line 149" in result.output
        assert "Log line 50" in result.output

    def test_logs_with_tail_option(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_logs_dir,
        mock_log_file,
    ):
        """Test logs with custom tail option."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs", "--tail", "10"])

        assert result.exit_code == 0
        assert "Log line 149" in result.output
        assert "Log line 140" in result.output
        # Ensure earlier lines are not shown
        assert "Log line 130" not in result.output

    def test_logs_shows_file_path(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_logs_dir,
        mock_log_file,
    ):
        """Test logs shows file path in output."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 0
        assert "run-20250115-120000.txt" in result.output

    def test_logs_handles_error(self, cli_runner, temp_dir, mock_state_dir):
        """Test logs handles errors gracefully."""
        # Create invalid state file
        state_file = mock_state_dir / "state.json"
        state_file.write_text("invalid json")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 1
        assert "Error:" in result.output
