"""Tests for the single-instance session lock on ``start`` / ``resume``.

Both commands must acquire the session lock before touching shared state and
release it on every exit path, so two concurrent runs cannot corrupt state,
duplicate PRs, or race OAuth refresh-token rotation.
"""

import json
from datetime import datetime
from unittest.mock import patch

from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager

from .conftest import mock_resume_context

# After the workflow.py split, patch targets live in the focused sub-modules:
# CredentialManager is looked up in workflow_start/workflow_resume (per command),
# while AgentWrapper/Planner/WorkLoopOrchestrator live in workflow_helpers.
WORKFLOW_HELPERS = "claude_task_master.cli_commands.workflow_helpers"
WORKFLOW_START = "claude_task_master.cli_commands.workflow_start"
WORKFLOW_RESUME = "claude_task_master.cli_commands.workflow_resume"


class TestStartSessionLock:
    """The ``start`` command guards concurrent runs with the session lock."""

    def test_start_aborts_when_session_lock_held(self, cli_runner: CliRunner, temp_dir):
        """A second start refuses to run (and never loads creds) when the lock is held."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch.object(StateManager, "acquire_session_lock", return_value=False):
                with patch(f"{WORKFLOW_START}.CredentialManager") as mock_cred:
                    result = cli_runner.invoke(app, ["start", "Test goal"])
                    # Lock guard runs before credential loading (closes the
                    # OAuth refresh-token rotation race), so creds are untouched.
                    mock_cred.assert_not_called()

        assert result.exit_code == 1
        assert "Another claudetm session is active" in result.output
        assert "clean -f" in result.output

    def test_start_releases_lock_on_planning_failure(self, cli_runner: CliRunner, temp_dir):
        """A failed start frees the lock so a later run can acquire it."""
        state_dir = temp_dir / ".claude-task-master"
        with patch.object(StateManager, "STATE_DIR", state_dir):
            with patch(f"{WORKFLOW_START}.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                mock_cred.return_value.resync_from_live.return_value = False
                with patch(f"{WORKFLOW_HELPERS}.AgentWrapper"):
                    with patch(f"{WORKFLOW_HELPERS}.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("boom")

                        result = cli_runner.invoke(app, ["start", "Test goal"])

            assert result.exit_code == 1
            # The finally must remove the PID lock even though start failed.
            assert not (state_dir / ".pid").exists()

    def test_start_releases_lock_on_success(self, cli_runner: CliRunner, temp_dir):
        """A successful start releases the lock via the finally on exit."""
        state_dir = temp_dir / ".claude-task-master"
        with patch.object(StateManager, "STATE_DIR", state_dir):
            with patch(f"{WORKFLOW_START}.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                mock_cred.return_value.resync_from_live.return_value = False
                with patch(f"{WORKFLOW_HELPERS}.AgentWrapper"):
                    with patch(f"{WORKFLOW_HELPERS}.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.return_value = {
                            "plan": "## Tasks\n- [ ] Task 1",
                            "raw_output": "Planning output",
                        }
                        with patch(f"{WORKFLOW_HELPERS}.WorkLoopOrchestrator") as mock_orch:
                            mock_orch.return_value.run.return_value = 0

                            result = cli_runner.invoke(app, ["start", "Test goal"])

            assert result.exit_code == 0
            assert not (state_dir / ".pid").exists()


class TestResumeSessionLock:
    """The ``resume`` command guards concurrent runs with the session lock."""

    def test_resume_aborts_when_session_lock_held(
        self, cli_runner: CliRunner, mock_state_dir, setup_resume_state
    ):
        """Resume refuses to run (and never loads creds) when the lock is held."""
        setup_resume_state(status="paused")
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch.object(StateManager, "acquire_session_lock", return_value=False):
                with patch(f"{WORKFLOW_RESUME}.CredentialManager") as mock_cred:
                    result = cli_runner.invoke(app, ["resume"])
                    mock_cred.assert_not_called()

        assert result.exit_code == 1
        assert "Another claudetm session is active" in result.output

    def test_resume_releases_lock_on_exit(
        self, cli_runner: CliRunner, mock_state_dir, setup_resume_state
    ):
        """Resume frees the PID lock on exit so a later run can acquire it."""
        setup_resume_state(status="paused")
        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert not (mock_state_dir / ".pid").exists()

    def test_resume_terminal_state_never_acquires_lock(
        self, cli_runner: CliRunner, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """A no-op resume of a finished task exits without taking the lock."""
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
            "options": {"auto_merge": True, "max_sessions": None, "pause_on_pr": False},
        }
        (mock_state_dir / "state.json").write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch.object(StateManager, "acquire_session_lock") as mock_acquire:
                result = cli_runner.invoke(app, ["resume"])
                mock_acquire.assert_not_called()

        assert result.exit_code == 0
        assert "already completed successfully" in result.output
