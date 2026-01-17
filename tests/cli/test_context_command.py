"""Tests for the context CLI command."""

from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestContextCommand:
    """Tests for the context command."""

    def test_context_no_active_task(self, cli_runner, temp_dir):
        """Test context when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["context"])

        assert result.exit_code == 1
        assert "No active task found" in result.output

    def test_context_no_context_accumulated(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test context when no context.md exists."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["context"])

        assert result.exit_code == 0
        assert "No context accumulated yet" in result.output

    def test_context_shows_content(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_context_file
    ):
        """Test context shows context content."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["context"])

        assert result.exit_code == 0
        assert "Accumulated Context" in result.output
        assert "Session 1" in result.output
        assert "modular architecture" in result.output

    def test_context_handles_error(self, cli_runner, temp_dir, mock_state_dir, mock_state_file):
        """Test context handles errors gracefully."""
        # Mock load_context to raise an exception
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch.object(StateManager, "load_context", side_effect=Exception("IO Error")):
                result = cli_runner.invoke(app, ["context"])

        assert result.exit_code == 1
        assert "Error:" in result.output
