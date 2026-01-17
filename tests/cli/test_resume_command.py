"""Tests for the resume CLI command - basic functionality."""

import json
from datetime import datetime
from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestResumeCommandBasic:
    """Basic tests for the resume command."""

    def test_resume_no_task_found(self, cli_runner, temp_dir):
        """Test resume when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "No task found to resume" in result.output
        assert "start" in result.output

    def test_resume_success_state(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume when task has already succeeded."""
        # Create a state with success status
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "success",
            "current_task_index": 3,
            "session_count": 5,
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

        assert result.exit_code == 0
        assert "already completed successfully" in result.output

    def test_resume_failed_state(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume when task has failed."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "failed",
            "current_task_index": 2,
            "session_count": 3,
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
        assert "failed and cannot be resumed" in result.output

    def test_resume_no_plan(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test resume when no plan exists."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "No plan file found" in result.output or "No plan found" in result.output

    def test_resume_success_shows_suggestion(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume success state shows suggestion about clean command."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "success",
            "current_task_index": 2,
            "session_count": 4,
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

        assert result.exit_code == 0
        # Should show suggestion to use clean
        assert "clean" in result.output.lower()

    def test_resume_failed_shows_suggestion(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume failed state shows suggestion about clean command."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "failed",
            "current_task_index": 1,
            "session_count": 2,
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
        # Should show suggestion to use clean
        assert "clean" in result.output.lower()


class TestResumeCommandDisplay:
    """Tests for resume command display output."""

    def test_resume_displays_status(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_goal_file,
        mock_plan_file,
    ):
        """Test resume displays current status before resuming."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        mock_orch.return_value.run.return_value = 2

                        result = cli_runner.invoke(app, ["resume"])

        # Should display goal and status info
        assert "Goal:" in result.output
        assert "Status:" in result.output
        assert "Current Task:" in result.output
        assert "Session Count:" in result.output

    def test_resume_verbose_output(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_goal_file,
        mock_plan_file,
    ):
        """Test resume outputs loading and status messages."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        mock_orch.return_value.run.return_value = 0

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        # Check for key output messages
        assert "Resuming task" in result.output
        assert "Loading credentials" in result.output
        assert "Resuming Execution" in result.output

    def test_resume_high_session_count(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume displays high session counts correctly."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
            "current_task_index": 1,  # Within bounds of 3 tasks in mock plan
            "session_count": 100,  # High session count
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": 200,
                "pause_on_pr": False,
            },
        }
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        mock_orch.return_value.run.return_value = 0

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "100" in result.output  # Session count displayed

    def test_resume_with_current_pr(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume displays PR information when present."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
            "current_task_index": 1,
            "session_count": 2,
            "current_pr": 123,  # Has an active PR
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": True,  # Paused on PR
            },
        }
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        mock_orch.return_value.run.return_value = 0

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        # State with current_pr should still work
        assert "completed successfully" in result.output
