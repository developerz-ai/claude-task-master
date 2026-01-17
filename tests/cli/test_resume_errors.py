"""Tests for resume command error handling.

This module tests all error scenarios for the resume command, including:
- Missing files and directories
- Terminal states (success/failed)
- Credential errors
- State file corruption
- Orchestrator exceptions
"""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager

from .conftest import mock_resume_context


@pytest.fixture
def setup_error_state(mock_state_dir, mock_goal_file, mock_plan_file, state_data_factory):
    """Fixture to set up state for error testing."""

    def _setup(**state_kwargs):
        state_data = state_data_factory(**state_kwargs)
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return state_data

    return _setup


# =============================================================================
# Missing Files and State Errors
# =============================================================================


class TestResumeMissingFiles:
    """Tests for resume command when required files are missing."""

    def test_resume_no_task_found(self, cli_runner, temp_dir):
        """Test resume when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "No task found to resume" in result.output
        assert "start" in result.output

    def test_resume_no_plan(self, cli_runner, mock_state_dir, mock_state_file, mock_goal_file):
        """Test resume when no plan exists."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "No plan file found" in result.output or "No plan found" in result.output

    def test_resume_no_goal_file(self, cli_runner, mock_state_dir, mock_state_file, mock_plan_file):
        """Test resume when goal file is missing."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "No goal" in result.output or "goal.txt" in result.output.lower()

    def test_resume_no_state_file_with_other_files(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume when state.json is missing but other files exist."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "No task found" in result.output or "state" in result.output.lower()


# =============================================================================
# Terminal State Errors
# =============================================================================


class TestResumeTerminalStates:
    """Tests for resume when task is in a terminal state."""

    def test_resume_success_state(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file, state_data_factory
    ):
        """Test resume when task has already succeeded."""
        state_data = state_data_factory(status="success", session_count=5, current_task_index=3)
        (mock_state_dir / "state.json").write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "already completed successfully" in result.output

    def test_resume_failed_state(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file, state_data_factory
    ):
        """Test resume when task has failed."""
        state_data = state_data_factory(status="failed", session_count=3, current_task_index=2)
        (mock_state_dir / "state.json").write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "failed and cannot be resumed" in result.output

    def test_resume_success_shows_clean_suggestion(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file, state_data_factory
    ):
        """Test resume success state shows suggestion about clean command."""
        state_data = state_data_factory(status="success")
        (mock_state_dir / "state.json").write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "clean" in result.output.lower()

    def test_resume_failed_shows_clean_suggestion(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file, state_data_factory
    ):
        """Test resume failed state shows suggestion about clean command."""
        state_data = state_data_factory(status="failed")
        (mock_state_dir / "state.json").write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "clean" in result.output.lower()


# =============================================================================
# Credential Errors
# =============================================================================


class TestResumeCredentialErrors:
    """Tests for resume command credential error handling."""

    def test_resume_credential_not_found(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles credential file not found."""
        setup_error_state()

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.side_effect = FileNotFoundError(
                    "Credentials not found"
                )
                result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "Credentials not found" in result.output
        assert "doctor" in result.output

    def test_resume_credential_expired(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles expired credentials."""
        setup_error_state()

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.side_effect = ValueError(
                    "OAuth token expired"
                )
                result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "token" in result.output.lower() or "expired" in result.output.lower()

    def test_resume_credential_permission_denied(
        self, cli_runner, mock_state_dir, setup_error_state
    ):
        """Test resume handles permission errors reading credentials."""
        setup_error_state()

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.side_effect = PermissionError(
                    "Permission denied"
                )
                result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "Permission" in result.output or "permission" in result.output


# =============================================================================
# State File Corruption Errors
# =============================================================================


class TestResumeStateFileCorruption:
    """Tests for resume command state file corruption handling."""

    def test_resume_corrupt_json(self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file):
        """Test resume handles corrupt JSON in state file."""
        (mock_state_dir / "state.json").write_text("{ invalid json }")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert any(w in result.output.lower() for w in ["corrupt", "error", "invalid", "parse"])

    def test_resume_empty_state_file(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume handles empty state file."""
        (mock_state_dir / "state.json").write_text("")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1

    def test_resume_partial_json(self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file):
        """Test resume handles partially written JSON."""
        (mock_state_dir / "state.json").write_text('{"status": "working", "index": ')

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1

    def test_resume_wrong_json_type(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume handles state file with wrong JSON type (array instead of object)."""
        (mock_state_dir / "state.json").write_text('["array", "not", "object"]')

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1

    def test_resume_null_state(self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file):
        """Test resume handles state file containing null."""
        (mock_state_dir / "state.json").write_text("null")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1


# =============================================================================
# Missing Fields Errors
# =============================================================================


class TestResumeMissingFields:
    """Tests for resume command with missing state fields."""

    def test_resume_missing_status(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume handles missing status field."""
        timestamp = datetime.now().isoformat()
        state_data: dict[str, object] = {
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "sonnet",
            "options": {},
        }
        (mock_state_dir / "state.json").write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            cli_runner.invoke(app, ["resume"])

        # Should handle gracefully - either default or error

    def test_resume_empty_options(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles empty options dictionary gracefully."""
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
            "options": {},
        }
        (mock_state_dir / "state.json").write_text(json.dumps(state_data))
        (mock_state_dir / "logs").mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0


# =============================================================================
# Generic Exception Errors
# =============================================================================


class TestResumeGenericErrors:
    """Tests for resume command generic exception handling."""

    def test_resume_runtime_error(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles runtime errors."""
        setup_error_state()

        with mock_resume_context(mock_state_dir, raise_exception=RuntimeError("Unexpected")):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "Unexpected" in result.output

    def test_resume_keyboard_interrupt(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles keyboard interrupt."""
        setup_error_state()

        with mock_resume_context(mock_state_dir, raise_exception=KeyboardInterrupt()):
            cli_runner.invoke(app, ["resume"])
        # KeyboardInterrupt should be handled gracefully

    def test_resume_os_error(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles OS errors."""
        setup_error_state()

        with mock_resume_context(mock_state_dir, raise_exception=OSError("Disk full")):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "Disk" in result.output or "error" in result.output.lower()

    def test_resume_memory_error(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles memory errors."""
        setup_error_state()

        with mock_resume_context(mock_state_dir, raise_exception=MemoryError()):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1


# =============================================================================
# Orchestrator Return Code Errors
# =============================================================================


class TestResumeOrchestratorReturnCodes:
    """Tests for resume command orchestrator return code handling."""

    def test_resume_pauses_again(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume when orchestrator returns paused (code 2)."""
        setup_error_state()

        with mock_resume_context(mock_state_dir, return_code=2):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 2
        assert "paused" in result.output
        assert "resume" in result.output

    def test_resume_blocks(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume when orchestrator returns blocked (code 1)."""
        setup_error_state()

        with mock_resume_context(mock_state_dir, return_code=1):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "blocked" in result.output or "failed" in result.output

    def test_resume_unexpected_code(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles unexpected return codes."""
        setup_error_state()

        with mock_resume_context(mock_state_dir, return_code=3):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 3
        assert "blocked" in result.output.lower() or "failed" in result.output.lower()

    def test_resume_negative_code(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles negative return codes."""
        setup_error_state()

        with mock_resume_context(mock_state_dir, return_code=-1):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code != 0

    def test_resume_high_code(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles high return codes."""
        setup_error_state()

        with mock_resume_context(mock_state_dir, return_code=255):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 255


# =============================================================================
# Agent Wrapper Errors
# =============================================================================


class TestResumeAgentErrors:
    """Tests for resume command agent wrapper error handling."""

    def test_resume_agent_init_error(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles agent wrapper initialization errors."""
        setup_error_state()

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper") as mock_agent:
                    mock_agent.side_effect = ValueError("Invalid config")
                    result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "Invalid config" in result.output or "error" in result.output.lower()


# =============================================================================
# Timeout and Connection Errors
# =============================================================================


class TestResumeConnectionErrors:
    """Tests for resume command timeout and connection error handling."""

    def test_resume_timeout(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles timeout errors."""
        setup_error_state()

        with mock_resume_context(mock_state_dir, raise_exception=TimeoutError("Timed out")):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "timed out" in result.output.lower() or "timeout" in result.output.lower()

    def test_resume_connection_failed(self, cli_runner, mock_state_dir, setup_error_state):
        """Test resume handles connection errors."""
        setup_error_state()

        with mock_resume_context(mock_state_dir, raise_exception=ConnectionError("Failed")):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "connect" in result.output.lower() or "error" in result.output.lower()


# =============================================================================
# Plan File Errors
# =============================================================================


class TestResumePlanErrors:
    """Tests for resume command plan file error handling."""

    def test_resume_empty_plan(self, cli_runner, mock_state_dir, mock_state_file, mock_goal_file):
        """Test resume handles empty plan file."""
        (mock_state_dir / "plan.md").write_text("")
        (mock_state_dir / "logs").mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        mock_orch.return_value.run.return_value = 0
                        cli_runner.invoke(app, ["resume"])

        # Should handle empty plan gracefully

    def test_resume_plan_no_tasks(
        self, cli_runner, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test resume handles plan with no parseable tasks."""
        (mock_state_dir / "plan.md").write_text("## Task List\n\nNo tasks yet.\n")
        (mock_state_dir / "logs").mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        mock_orch.return_value.run.return_value = 0
                        cli_runner.invoke(app, ["resume"])

        # Should handle case of no parseable tasks

    def test_resume_plan_invalid_checkboxes(
        self, cli_runner, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test resume handles plan with malformed checkboxes."""
        (mock_state_dir / "plan.md").write_text("## Task List\n\n- [invalid] Task\n- [ Unclosed\n")
        (mock_state_dir / "logs").mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        mock_orch.return_value.run.return_value = 0
                        cli_runner.invoke(app, ["resume"])

        # Should handle malformed task lists gracefully


# =============================================================================
# Multiple Error Scenarios
# =============================================================================


class TestResumeMultipleErrors:
    """Tests for resume command with multiple simultaneous issues."""

    def test_resume_missing_goal_and_plan(self, cli_runner, mock_state_dir, mock_state_file):
        """Test resume when both goal and plan files are missing."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1

    def test_resume_corrupt_state_no_logs(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume with corrupt state and missing logs directory."""
        (mock_state_dir / "state.json").write_text("not valid json")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1


# =============================================================================
# Error Message Quality
# =============================================================================


class TestResumeErrorMessages:
    """Tests for resume command error message quality."""

    def test_error_suggests_start_command(self, cli_runner, temp_dir):
        """Test that 'no task found' error suggests 'start' command."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "start" in result.output

    def test_terminal_state_suggests_clean(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file, state_data_factory
    ):
        """Test that terminal state errors suggest clean command."""
        state_data = state_data_factory(status="failed")
        (mock_state_dir / "state.json").write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "clean" in result.output.lower()

    def test_credential_error_suggests_doctor(self, cli_runner, mock_state_dir, setup_error_state):
        """Test that credential errors suggest doctor command."""
        setup_error_state()

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.side_effect = FileNotFoundError(
                    "Credentials not found"
                )
                result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "doctor" in result.output
