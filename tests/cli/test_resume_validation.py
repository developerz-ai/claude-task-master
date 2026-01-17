"""Tests for resume command validation and edge cases."""

import json
from datetime import datetime
from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestResumeTaskIndexValidation:
    """Tests for resume command task index validation."""

    def test_resume_negative_task_index(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume with invalid negative task index."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "working",
            "current_task_index": -1,  # Invalid negative index
            "session_count": 1,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": False,
            },
        }
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "negative" in result.output.lower() or "invalid" in result.output.lower()

    def test_resume_task_index_out_of_bounds(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume with task index exceeding plan tasks."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "working",
            "current_task_index": 100,  # Far exceeds the 3 tasks in plan
            "session_count": 1,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": False,
            },
        }
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "exceeds" in result.output.lower() or "Task index" in result.output

    def test_resume_validation_error_shows_details(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test that validation errors show helpful details."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "working",
            "current_task_index": 50,  # Out of bounds
            "session_count": 1,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": False,
            },
        }
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        # Should show some helpful context
        assert "Task index" in result.output or "clean" in result.output.lower()
