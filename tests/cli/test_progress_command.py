"""Tests for the progress CLI command."""

from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestProgressCommand:
    """Tests for the progress command."""

    def test_progress_no_active_task(self, cli_runner, temp_dir):
        """Test progress when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["progress"])

        assert result.exit_code == 1
        assert "No active task found" in result.output

    def test_progress_no_progress_recorded(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test progress when no progress.md exists."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["progress"])

        assert result.exit_code == 0
        assert "No progress recorded yet" in result.output

    def test_progress_shows_content(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_progress_file
    ):
        """Test progress shows progress content."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["progress"])

        assert result.exit_code == 0
        assert "Progress Summary" in result.output
        assert "Session: 3" in result.output
        assert "Implement feature X" in result.output

    def test_progress_handles_error(self, cli_runner, temp_dir, mock_state_dir, mock_state_file):
        """Test progress handles errors gracefully."""
        # Mock load_progress to raise an exception
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch.object(StateManager, "load_progress", side_effect=Exception("IO Error")):
                result = cli_runner.invoke(app, ["progress"])

        assert result.exit_code == 1
        assert "Error:" in result.output
