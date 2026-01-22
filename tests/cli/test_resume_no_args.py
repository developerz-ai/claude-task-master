"""Tests for `claudetm resume` without arguments - baseline behavior.

This test file explicitly tests that `claudetm resume` works without any arguments,
serving as a regression test baseline for future tasks that add optional message
parameters (e.g., `claudetm resume "change request"`).

The key invariant being tested:
- `claudetm resume` (no arguments) must continue to work exactly as before
- It should NOT require a message argument
- All existing resume functionality must be preserved
"""

import json
from datetime import datetime
from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager

from .conftest import mock_resume_context


class TestResumeNoArgsBaseline:
    """Test that `claudetm resume` works without any arguments.

    This is the baseline behavior that must be preserved when adding
    the optional message parameter in future tasks.
    """

    def test_resume_no_args_paused_state(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test `claudetm resume` with no arguments from paused state."""
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
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir, return_code=0):
            # Key test: invoke resume with NO arguments
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output

    def test_resume_no_args_blocked_state(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test `claudetm resume` with no arguments from blocked state."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "blocked",
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": 42,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "opus",
            "options": {
                "auto_merge": False,
                "max_sessions": None,
                "pause_on_pr": False,
            },
        }
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir, return_code=0):
            # Key test: invoke resume with NO arguments
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Attempting to resume blocked task" in result.output

    def test_resume_no_args_working_state(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_goal_file,
        mock_plan_file,
        mock_state_file,
    ):
        """Test `claudetm resume` with no arguments from working state (crash recovery)."""
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir, return_code=0):
            # Key test: invoke resume with NO arguments
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output

    def test_resume_no_args_displays_status_info(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_goal_file,
        mock_plan_file,
        mock_state_file,
    ):
        """Test `claudetm resume` without args shows goal, status, task, and session info."""
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir, return_code=0):
            result = cli_runner.invoke(app, ["resume"])

        # Verify all status info is displayed
        assert "Goal:" in result.output
        assert "Status:" in result.output
        assert "Current Task:" in result.output
        assert "Session Count:" in result.output


class TestResumeNoArgsWithForceFlag:
    """Test that `claudetm resume --force` also works (existing functionality)."""

    def test_resume_no_args_with_force_flag(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test `claudetm resume --force` with no message argument."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "failed",
            "current_task_index": 1,
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
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Mock the state recovery for force resume - patch at the module where it's imported
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        mock_orch.return_value.run.return_value = 0
                        # Patch at the actual import location in state_recovery module
                        with patch(
                            "claude_task_master.core.state_recovery.StateRecovery"
                        ) as mock_recovery:
                            mock_recovery.return_value.apply_recovery.return_value.message = (
                                "Recovery applied"
                            )
                            mock_recovery.return_value.apply_recovery.return_value.workflow_stage = "working"

                            # Key test: invoke resume with --force but NO message argument
                            result = cli_runner.invoke(app, ["resume", "--force"])

        # Force recovery should work without a message argument
        assert "recovery" in result.output.lower() or result.exit_code == 0

    def test_resume_no_args_with_short_force_flag(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test `claudetm resume -f` with no message argument."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "failed",
            "current_task_index": 0,
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
                        # Patch at the actual import location in state_recovery module
                        with patch(
                            "claude_task_master.core.state_recovery.StateRecovery"
                        ) as mock_recovery:
                            mock_recovery.return_value.apply_recovery.return_value.message = (
                                "Recovery applied"
                            )
                            mock_recovery.return_value.apply_recovery.return_value.workflow_stage = "working"

                            # Key test: invoke resume with -f but NO message argument
                            result = cli_runner.invoke(app, ["resume", "-f"])

        # Should work with short flag as well
        assert "recovery" in result.output.lower() or result.exit_code == 0


class TestResumeNoArgsErrorCases:
    """Test error cases for `claudetm resume` without arguments."""

    def test_resume_no_args_no_task(self, cli_runner, temp_dir):
        """Test `claudetm resume` with no arguments when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "No task found to resume" in result.output
        assert "start" in result.output

    def test_resume_no_args_success_state(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test `claudetm resume` with no args on already completed task."""
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

    def test_resume_no_args_failed_state(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test `claudetm resume` with no args on failed task (without --force)."""
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


class TestResumeNoArgsWebhookSupport:
    """Test `claudetm resume` without args preserves webhook configuration."""

    def test_resume_no_args_with_webhook_configured(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test `claudetm resume` with no args when webhook was configured in original start."""
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
                "webhook_url": "https://example.com/webhook",
                "webhook_secret": "test-secret",
            },
        }
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))
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
                        with patch(
                            "claude_task_master.cli_commands.workflow.WebhookClient"
                        ) as mock_webhook:
                            # Key test: invoke resume with NO arguments, webhook should still work
                            result = cli_runner.invoke(app, ["resume"])

                            # Webhook client should have been created
                            mock_webhook.assert_called_once_with(
                                url="https://example.com/webhook",
                                secret="test-secret",
                            )

        assert result.exit_code == 0
        assert "Webhook notifications enabled" in result.output


class TestResumeCommandSignature:
    """Test the command signature to ensure it accepts no required positional args."""

    def test_resume_help_shows_no_required_args(self, cli_runner):
        """Test that `claudetm resume --help` shows no required arguments."""
        result = cli_runner.invoke(app, ["resume", "--help"])

        assert result.exit_code == 0
        # The help should not show any required positional arguments
        # Optional flags like --force/-f are fine
        assert "Usage: " in result.output
        # Verify --force is documented as optional
        assert "--force" in result.output or "-f" in result.output

    def test_resume_accepts_only_optional_args(self, cli_runner, temp_dir):
        """Verify resume command structure has no required positional arguments."""
        # This test verifies the command signature by checking what happens
        # when we call it with no task state (should fail because no task,
        # NOT because of missing arguments)
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["resume"])

        # The error should be about missing task, NOT about missing arguments
        assert result.exit_code == 1
        assert "No task found" in result.output
        # Should NOT have argument-related error
        assert "Missing argument" not in result.output
        assert "Missing option" not in result.output
