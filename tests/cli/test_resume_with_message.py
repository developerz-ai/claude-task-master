"""Tests for the resume command with message functionality."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestResumeWithMessageBasic:
    """Basic tests for resume with message."""

    def test_resume_without_message_still_works(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test that resume without message works as before."""
        # Create a valid working state
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
            "current_task_index": 0,
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

                        # Resume without message
                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Resuming task" in result.output

    def test_resume_with_message_updates_plan(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test that resume with message updates the plan."""
        # Create a valid working state
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
            "current_task_index": 0,
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

        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.PlanUpdater"
                    ) as mock_plan_updater:
                        mock_plan_updater.return_value.update_plan.return_value = {
                            "success": True,
                            "changes_made": True,
                            "plan": "## Task List\n- [ ] New task",
                        }
                        with patch(
                            "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                        ) as mock_orch:
                            mock_orch.return_value.run.return_value = 0

                            # Resume with message
                            result = cli_runner.invoke(app, ["resume", "Add authentication"])

        assert result.exit_code == 0
        assert "Updating plan" in result.output
        mock_plan_updater.return_value.update_plan.assert_called_once_with("Add authentication")

    def test_resume_with_message_shows_plan_update_success(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test that successful plan update is displayed."""
        # Create a valid working state
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
            "current_task_index": 0,
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

        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.PlanUpdater"
                    ) as mock_plan_updater:
                        mock_plan_updater.return_value.update_plan.return_value = {
                            "success": True,
                            "changes_made": True,
                            "plan": "## Task List\n- [ ] New task",
                        }
                        with patch(
                            "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                        ) as mock_orch:
                            mock_orch.return_value.run.return_value = 0

                            result = cli_runner.invoke(app, ["resume", "Add new feature"])

        assert result.exit_code == 0
        assert "Plan updated successfully" in result.output

    def test_resume_with_message_no_changes_needed(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume when plan doesn't need changes."""
        # Create a valid working state
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
            "current_task_index": 0,
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

        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.PlanUpdater"
                    ) as mock_plan_updater:
                        # Simulate no changes needed
                        mock_plan_updater.return_value.update_plan.return_value = {
                            "success": True,
                            "changes_made": False,
                            "plan": "## Task List\n- [ ] Existing task",
                        }
                        with patch(
                            "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                        ) as mock_orch:
                            mock_orch.return_value.run.return_value = 0

                            result = cli_runner.invoke(app, ["resume", "No changes"])

        assert result.exit_code == 0
        assert "No changes needed" in result.output


class TestResumeWithMessageErrors:
    """Tests for error handling in resume with message."""

    def test_resume_with_message_plan_update_error_continues(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test that resume continues even if plan update fails."""
        # Create a valid working state
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
            "current_task_index": 0,
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

        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.PlanUpdater"
                    ) as mock_plan_updater:
                        # Simulate plan update failure
                        mock_plan_updater.return_value.update_plan.side_effect = Exception(
                            "API error"
                        )
                        with patch(
                            "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                        ) as mock_orch:
                            mock_orch.return_value.run.return_value = 0

                            result = cli_runner.invoke(app, ["resume", "Update plan"])

        # Should continue with existing plan
        assert result.exit_code == 0
        assert "Error updating plan" in result.output
        assert "Continuing with existing plan" in result.output


class TestResumeWithMessageDisplay:
    """Tests for message display in resume command."""

    def test_resume_shows_message_preview(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test that a preview of the message is shown."""
        # Create a valid working state
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
            "current_task_index": 0,
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

        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.PlanUpdater"
                    ) as mock_plan_updater:
                        mock_plan_updater.return_value.update_plan.return_value = {
                            "success": True,
                            "changes_made": True,
                            "plan": "## Task List\n- [ ] Task",
                        }
                        with patch(
                            "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                        ) as mock_orch:
                            mock_orch.return_value.run.return_value = 0

                            result = cli_runner.invoke(app, ["resume", "Add a new feature"])

        assert "Add a new feature" in result.output

    def test_resume_truncates_long_message(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test that long messages are truncated in the display."""
        # Create a valid working state
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
            "current_task_index": 0,
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

        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Create a long message (over 100 chars)
        long_message = "A" * 150

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.PlanUpdater"
                    ) as mock_plan_updater:
                        mock_plan_updater.return_value.update_plan.return_value = {
                            "success": True,
                            "changes_made": True,
                            "plan": "## Task List\n- [ ] Task",
                        }
                        with patch(
                            "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                        ) as mock_orch:
                            mock_orch.return_value.run.return_value = 0

                            result = cli_runner.invoke(app, ["resume", long_message])

        # Should show truncation indicator
        assert "..." in result.output


class TestResumeWithMessageAndForce:
    """Tests for using resume with both message and force flag."""

    def test_resume_with_message_and_force(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume with both message and --force flag."""
        # Create a failed state
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "blocked",
            "workflow_stage": "ci_failed",
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": 123,
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
                        "claude_task_master.cli_commands.workflow.PlanUpdater"
                    ) as mock_plan_updater:
                        mock_plan_updater.return_value.update_plan.return_value = {
                            "success": True,
                            "changes_made": True,
                            "plan": "## Task List\n- [ ] Task",
                        }
                        with patch(
                            "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                        ) as mock_orch:
                            mock_orch.return_value.run.return_value = 0
                            # StateRecovery is imported locally, so patch in the module
                            with patch(
                                "claude_task_master.core.state_recovery.StateRecovery"
                            ) as mock_recovery:
                                mock_recovery.return_value.apply_recovery.return_value = MagicMock(
                                    message="Recovery applied",
                                    workflow_stage="working",
                                )

                                result = cli_runner.invoke(
                                    app, ["resume", "Fix the CI issues", "--force"]
                                )

        # Should succeed with both force recovery and plan update
        assert result.exit_code == 0
        assert "Updating plan" in result.output


class TestResumeWithMessageHelp:
    """Tests for help text of resume with message."""

    def test_resume_help_shows_message_argument(self, cli_runner):
        """Test that resume --help shows the message argument."""
        result = cli_runner.invoke(app, ["resume", "--help"])

        assert result.exit_code == 0
        assert "message" in result.output.lower() or "change request" in result.output.lower()

    def test_resume_help_shows_examples(self, cli_runner):
        """Test that resume --help shows usage examples."""
        result = cli_runner.invoke(app, ["resume", "--help"])

        assert result.exit_code == 0
        # Should show example with message
        assert "resume" in result.output
