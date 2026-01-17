"""Tests for the plan CLI command."""

from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestPlanCommand:
    """Tests for the plan command."""

    def test_plan_no_active_task(self, cli_runner, temp_dir):
        """Test plan when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["plan"])

        assert result.exit_code == 1
        assert "No active task found" in result.output

    def test_plan_no_plan_file(self, cli_runner, temp_dir, mock_state_dir, mock_state_file):
        """Test plan when no plan.md exists."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["plan"])

        assert result.exit_code == 1
        assert "No plan found" in result.output

    def test_plan_shows_plan_content(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_plan_file
    ):
        """Test plan shows plan content."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["plan"])

        assert result.exit_code == 0
        assert "Task Plan" in result.output
        assert "Task 1" in result.output
        assert "Task 2" in result.output
        assert "Success Criteria" in result.output

    def test_plan_handles_error(self, cli_runner, temp_dir, mock_state_dir, mock_state_file):
        """Test plan handles errors gracefully."""
        # Create a plan file that will cause a rendering error
        plan_file = mock_state_dir / "plan.md"
        plan_file.write_text("Valid plan content")

        # Mock load_plan to raise an exception
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch.object(StateManager, "load_plan", side_effect=Exception("IO Error")):
                result = cli_runner.invoke(app, ["plan"])

        assert result.exit_code == 1
        assert "Error:" in result.output
