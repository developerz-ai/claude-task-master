"""Tests for resume command state handling - resuming from different states."""

import json
from datetime import datetime
from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestResumeFromPausedState:
    """Tests for resuming from paused state."""

    def test_resume_paused_task(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume from paused state."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
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
        assert "completed successfully" in result.output
        assert "paused" in result.output.lower() or "working" in result.output.lower()

    def test_resume_state_update_from_paused_to_working(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume correctly updates state from paused to working."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
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
        # Should show status update message
        assert "paused" in result.output.lower()


class TestResumeFromBlockedState:
    """Tests for resuming from blocked state."""

    def test_resume_blocked_task(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume from blocked state."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "blocked",
            "current_task_index": 1,
            "session_count": 3,
            "current_pr": 42,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "opus",
            "options": {
                "auto_merge": False,
                "max_sessions": 5,
                "pause_on_pr": True,
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
        assert "Attempting to resume blocked task" in result.output

    def test_resume_blocked_state_attempt_message(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume from blocked state shows attempt message."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "blocked",
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": 99,  # Blocked on PR
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "sonnet",
            "options": {
                "auto_merge": False,
                "max_sessions": None,
                "pause_on_pr": True,
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
                        mock_orch.return_value.run.return_value = 2

                        result = cli_runner.invoke(app, ["resume"])

        # Exit code 2 means paused again
        assert result.exit_code == 2
        assert "Attempting to resume blocked task" in result.output


class TestResumeFromWorkingState:
    """Tests for resuming from working state (e.g., after crash)."""

    def test_resume_working_task(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_goal_file,
        mock_plan_file,
        mock_state_file,
    ):
        """Test resume from working state (e.g., after crash)."""
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
        assert "completed successfully" in result.output


class TestResumeFromPlanningState:
    """Tests for resuming from planning state."""

    def test_resume_planning_state(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume from planning state (interrupted during planning)."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "planning",
            "current_task_index": 0,
            "session_count": 0,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "haiku",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
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

        # Planning state should be resumable - it's not a terminal state
        assert result.exit_code == 0
        assert "completed successfully" in result.output


class TestResumeWithDifferentModels:
    """Tests for resuming with different model types."""

    def test_resume_different_model_types(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume works with different model types (opus, haiku)."""
        timestamp = datetime.now().isoformat()

        for model in ["opus", "haiku", "sonnet"]:
            state_data = {
                "status": "paused",
                "current_task_index": 0,
                "session_count": 1,
                "current_pr": None,
                "created_at": timestamp,
                "updated_at": timestamp,
                "run_id": "20250115-120000",
                "model": model,
                "options": {
                    "auto_merge": True,
                    "max_sessions": None,
                    "pause_on_pr": False,
                },
            }
            state_file = mock_state_dir / "state.json"
            state_file.write_text(json.dumps(state_data))

            # Create logs directory
            logs_dir = mock_state_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            with patch.object(StateManager, "STATE_DIR", mock_state_dir):
                with patch(
                    "claude_task_master.cli_commands.workflow.CredentialManager"
                ) as mock_cred:
                    mock_cred.return_value.get_valid_token.return_value = "test-token"
                    with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                        with patch(
                            "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                        ) as mock_orch:
                            mock_orch.return_value.run.return_value = 0

                            result = cli_runner.invoke(app, ["resume"])

            assert result.exit_code == 0, f"Failed for model {model}"
