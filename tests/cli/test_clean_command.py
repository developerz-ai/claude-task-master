"""Tests for the clean CLI command."""

from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestCleanCommand:
    """Tests for the clean command."""

    def test_clean_no_task_state(self, cli_runner, temp_dir):
        """Test clean when no task state exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["clean"])

        assert result.exit_code == 0
        assert "No task state found" in result.output

    def test_clean_prompts_confirmation(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test clean prompts for confirmation."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["clean"], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.output

    def test_clean_with_force_flag(self, cli_runner, temp_dir, mock_state_dir, mock_state_file):
        """Test clean with --force flag skips confirmation."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["clean", "--force"])

        assert result.exit_code == 0
        assert "Cleaning task state" in result.output
        assert "cleaned" in result.output

    def test_clean_with_f_flag(self, cli_runner, temp_dir, mock_state_dir, mock_state_file):
        """Test clean with -f short flag."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["clean", "-f"])

        assert result.exit_code == 0
        assert "cleaned" in result.output

    def test_clean_removes_state_directory(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test clean removes state directory."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["clean", "--force"])

        assert result.exit_code == 0
        assert not mock_state_dir.exists()

    def test_clean_confirmed_removes_directory(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test clean when confirmed removes directory."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["clean"], input="y\n")

        assert result.exit_code == 0
        assert "cleaned" in result.output
        assert not mock_state_dir.exists()
