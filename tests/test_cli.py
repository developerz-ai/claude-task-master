"""Comprehensive tests for CLI commands."""

import json
import re
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_pattern.sub("", text)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def cli_runner():
    """Provide a Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_state_dir(temp_dir: Path) -> Path:
    """Create a mock state directory."""
    state_dir = temp_dir / ".claude-task-master"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture
def mock_logs_dir(mock_state_dir: Path) -> Path:
    """Create a mock logs directory."""
    logs_dir = mock_state_dir / "logs"
    logs_dir.mkdir(parents=True)
    return logs_dir


@pytest.fixture
def mock_state_file(mock_state_dir: Path) -> Path:
    """Create a mock state.json file."""
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "current_task_index": 2,
        "session_count": 3,
        "current_pr": 123,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "20250115-120000",
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": 10,
            "pause_on_pr": False,
        },
    }
    state_file = mock_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data))
    return state_file


@pytest.fixture
def mock_goal_file(mock_state_dir: Path) -> Path:
    """Create a mock goal.txt file."""
    goal_file = mock_state_dir / "goal.txt"
    goal_file.write_text("Make the app production ready")
    return goal_file


@pytest.fixture
def mock_plan_file(mock_state_dir: Path) -> Path:
    """Create a mock plan.md file."""
    plan_file = mock_state_dir / "plan.md"
    plan_file.write_text("""## Task List

- [x] Task 1: Setup project
- [ ] Task 2: Implement feature
- [ ] Task 3: Add tests

## Success Criteria

1. All tests pass
2. Coverage > 80%
""")
    return plan_file


@pytest.fixture
def mock_context_file(mock_state_dir: Path) -> Path:
    """Create a mock context.md file."""
    context_file = mock_state_dir / "context.md"
    context_file.write_text("""# Accumulated Context

## Session 1

Explored the codebase and identified key components.

## Learning

The project uses a modular architecture.
""")
    return context_file


@pytest.fixture
def mock_progress_file(mock_state_dir: Path) -> Path:
    """Create a mock progress.md file."""
    progress_file = mock_state_dir / "progress.md"
    progress_file.write_text("""# Progress Update

Session: 3
Current Task: 2 of 3

## Latest Task
Implement feature X

## Result
Successfully implemented with all edge cases handled.
""")
    return progress_file


@pytest.fixture
def mock_log_file(mock_logs_dir: Path) -> Path:
    """Create a mock log file."""
    log_file = mock_logs_dir / "run-20250115-120000.txt"
    log_file.write_text("\n".join([f"Log line {i}" for i in range(150)]))
    return log_file


# =============================================================================
# Status Command Tests
# =============================================================================


class TestStatusCommand:
    """Tests for the status command."""

    def test_status_no_active_task(self, cli_runner, temp_dir):
        """Test status when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 1
        assert "No active task found" in result.output

    def test_status_shows_task_info(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test status shows task information."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "Task Status" in result.output
        assert "Make the app production ready" in result.output
        assert "working" in result.output
        assert "sonnet" in result.output
        assert "3" in result.output  # Session count
        assert "20250115-120000" in result.output  # Run ID

    def test_status_shows_pr_number(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test status shows current PR number when set."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "123" in result.output

    def test_status_shows_options(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file
    ):
        """Test status shows task options."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "Auto-merge:" in result.output
        assert "Max sessions:" in result.output
        assert "Pause on PR:" in result.output

    def test_status_handles_error(self, cli_runner, temp_dir, mock_state_dir):
        """Test status handles errors gracefully."""
        # Create invalid state file
        state_file = mock_state_dir / "state.json"
        state_file.write_text("invalid json{")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 1
        assert "Error:" in result.output


# =============================================================================
# Plan Command Tests
# =============================================================================


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


# =============================================================================
# Logs Command Tests
# =============================================================================


class TestLogsCommand:
    """Tests for the logs command."""

    def test_logs_no_active_task(self, cli_runner, temp_dir):
        """Test logs when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 1
        assert "No active task found" in result.output

    def test_logs_no_log_file(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_logs_dir
    ):
        """Test logs when no log file exists."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 1
        assert "No log file found" in result.output

    def test_logs_shows_log_content(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_logs_dir,
        mock_log_file,
    ):
        """Test logs shows log content."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 0
        assert "Logs" in result.output
        # Should show last 100 lines by default
        assert "Log line 149" in result.output
        assert "Log line 50" in result.output

    def test_logs_with_tail_option(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_logs_dir,
        mock_log_file,
    ):
        """Test logs with custom tail option."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs", "--tail", "10"])

        assert result.exit_code == 0
        assert "Log line 149" in result.output
        assert "Log line 140" in result.output
        # Ensure earlier lines are not shown
        assert "Log line 130" not in result.output

    def test_logs_shows_file_path(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_logs_dir,
        mock_log_file,
    ):
        """Test logs shows file path in output."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 0
        assert "run-20250115-120000.txt" in result.output

    def test_logs_handles_error(self, cli_runner, temp_dir, mock_state_dir):
        """Test logs handles errors gracefully."""
        # Create invalid state file
        state_file = mock_state_dir / "state.json"
        state_file.write_text("invalid json")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 1
        assert "Error:" in result.output


# =============================================================================
# Context Command Tests
# =============================================================================


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


# =============================================================================
# Progress Command Tests
# =============================================================================


class TestProgressCommand:
    """Tests for the progress command."""

    def test_progress_no_active_task(self, cli_runner, temp_dir):
        """Test progress when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            result = cli_runner.invoke(app, ["progress"])

        assert result.exit_code == 1
        assert "No active task found" in result.output

    def test_progress_no_progress_recorded(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test progress when no progress.md exists."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["progress"])

        assert result.exit_code == 0
        assert "No progress recorded yet" in result.output

    def test_progress_shows_content(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_progress_file
    ):
        """Test progress shows progress content."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["progress"])

        assert result.exit_code == 0
        assert "Progress Summary" in result.output
        assert "Session: 3" in result.output
        assert "Implement feature X" in result.output

    def test_progress_handles_error(self, cli_runner, temp_dir, mock_state_dir, mock_state_file):
        """Test progress handles errors gracefully."""
        # Mock load_progress to raise an exception
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch.object(StateManager, "load_progress", side_effect=Exception("IO Error")):
                result = cli_runner.invoke(app, ["progress"])

        assert result.exit_code == 1
        assert "Error:" in result.output


# =============================================================================
# Clean Command Tests
# =============================================================================


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


# =============================================================================
# Doctor Command Tests
# =============================================================================


class TestDoctorCommand:
    """Tests for the doctor command."""

    def test_doctor_returns_success_when_all_pass(self, cli_runner, temp_dir):
        """Test doctor returns success when all checks pass."""
        from claude_task_master.utils.doctor import SystemDoctor

        with patch.object(SystemDoctor, "run_checks", return_value=True):
            result = cli_runner.invoke(app, ["doctor"])

        assert result.exit_code == 0

    def test_doctor_returns_failure_when_checks_fail(self, cli_runner, temp_dir):
        """Test doctor returns failure when checks fail."""
        from claude_task_master.utils.doctor import SystemDoctor

        with patch.object(SystemDoctor, "run_checks", return_value=False):
            result = cli_runner.invoke(app, ["doctor"])

        assert result.exit_code == 1


# =============================================================================
# Resume Command Tests
# =============================================================================


class TestResumeCommand:
    """Tests for the resume command."""

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
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.return_value = 0

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output
        assert "paused" in result.output.lower() or "working" in result.output.lower()

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
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.return_value = 0

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Attempting to resume blocked task" in result.output

    def test_resume_working_task(
        self, cli_runner, temp_dir, mock_state_dir, mock_goal_file, mock_plan_file, mock_state_file
    ):
        """Test resume from working state (e.g., after crash)."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.return_value = 0

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output

    def test_resume_credential_error(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file, mock_plan_file
    ):
        """Test resume handles credential errors."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.side_effect = FileNotFoundError(
                    "Credentials not found"
                )

                result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "Credentials not found" in result.output
        assert "doctor" in result.output

    def test_resume_displays_status(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file, mock_plan_file
    ):
        """Test resume displays current status before resuming."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.return_value = 2

                        result = cli_runner.invoke(app, ["resume"])

        # Should display goal and status info
        assert "Goal:" in result.output
        assert "Status:" in result.output
        assert "Current Task:" in result.output
        assert "Session Count:" in result.output

    def test_resume_orchestrator_pauses_again(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file, mock_plan_file
    ):
        """Test resume when orchestrator returns paused status."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.return_value = 2

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 2
        assert "paused" in result.output
        assert "resume" in result.output

    def test_resume_orchestrator_blocks(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file, mock_plan_file
    ):
        """Test resume when orchestrator returns blocked status."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.return_value = 1

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "blocked" in result.output or "failed" in result.output

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
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.return_value = 0

                        result = cli_runner.invoke(app, ["resume"])

        # Planning state should be resumable - it's not a terminal state
        assert result.exit_code == 0
        assert "completed successfully" in result.output

    def test_resume_generic_exception(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file, mock_plan_file
    ):
        """Test resume handles generic exceptions."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.side_effect = RuntimeError("Unexpected error")

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "Unexpected error" in result.output

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
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.return_value = 0

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        # State with current_pr should still work
        assert "completed successfully" in result.output

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
                with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                    mock_cred.return_value.get_valid_token.return_value = "test-token"
                    with patch("claude_task_master.cli.AgentWrapper"):
                        with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                            mock_orch.return_value.run.return_value = 0

                            result = cli_runner.invoke(app, ["resume"])

            assert result.exit_code == 0, f"Failed for model {model}"

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
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.return_value = 0

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        # Should show status update message
        assert "paused" in result.output.lower()

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
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.return_value = 2

                        result = cli_runner.invoke(app, ["resume"])

        # Exit code 2 means paused again
        assert result.exit_code == 2
        assert "Attempting to resume blocked task" in result.output

    def test_resume_orchestrator_unexpected_return_code(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file, mock_plan_file
    ):
        """Test resume handles unexpected orchestrator return codes."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        # Return code 3 or higher
                        mock_orch.return_value.run.return_value = 3

                        result = cli_runner.invoke(app, ["resume"])

        # Any non-0 and non-2 should be treated as blocked/failed
        assert result.exit_code == 3
        assert "blocked" in result.output.lower() or "failed" in result.output.lower()

    def test_resume_verbose_output(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_goal_file, mock_plan_file
    ):
        """Test resume outputs loading and status messages."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
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
            with patch("claude_task_master.cli.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.WorkLoopOrchestrator") as mock_orch:
                        mock_orch.return_value.run.return_value = 0

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "100" in result.output  # Session count displayed


# =============================================================================
# Comments Command Tests
# =============================================================================


class TestCommentsCommand:
    """Tests for the comments command (TODO implementation)."""

    def test_comments_not_implemented(self, cli_runner):
        """Test comments returns failure (not implemented yet)."""
        result = cli_runner.invoke(app, ["comments"])

        # Currently not implemented, should exit with 1
        assert result.exit_code == 1
        assert "PR Comments" in result.output

    def test_comments_with_pr_option(self, cli_runner):
        """Test comments with --pr option."""
        result = cli_runner.invoke(app, ["comments", "--pr", "123"])

        # Currently not implemented
        assert result.exit_code == 1


# =============================================================================
# PR Command Tests
# =============================================================================


class TestPRCommand:
    """Tests for the pr command (TODO implementation)."""

    def test_pr_not_implemented(self, cli_runner):
        """Test pr returns failure (not implemented yet)."""
        result = cli_runner.invoke(app, ["pr"])

        # Currently not implemented, should exit with 1
        assert result.exit_code == 1
        assert "PR Status" in result.output


# =============================================================================
# Start Command Tests
# =============================================================================


class TestStartCommand:
    """Tests for the start command."""

    def test_start_with_existing_task(self, cli_runner, temp_dir, mock_state_dir, mock_state_file):
        """Test start fails when task already exists."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["start", "New goal"])

        assert result.exit_code == 1
        assert "Task already exists" in result.output
        assert "resume" in result.output or "clean" in result.output

    def test_start_shows_goal(self, cli_runner, temp_dir):
        """Test start shows the goal."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            # Mock the credential manager to avoid actual credential loading
            with patch("claude_task_master.cli.CredentialManager") as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                # Mock the agent to avoid actual agent initialization
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(app, ["start", "My test goal"])

        # Should print the goal (even though it fails later)
        assert "My test goal" in result.output

    def test_start_default_model(self, cli_runner, temp_dir):
        """Test start uses default model."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(app, ["start", "Test goal"])

        # Should show default model (opus is the default)
        assert "opus" in result.output

    def test_start_with_custom_model(self, cli_runner, temp_dir):
        """Test start with custom model option."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(app, ["start", "Test goal", "--model", "opus"])

        assert "opus" in result.output

    def test_start_credential_error(self, cli_runner, temp_dir):
        """Test start handles credential errors."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.side_effect = FileNotFoundError(
                    "Credentials not found"
                )

                result = cli_runner.invoke(app, ["start", "Test goal"])

        assert result.exit_code == 1
        assert "Credentials not found" in result.output
        assert "doctor" in result.output

    def test_start_with_auto_merge_false(self, cli_runner, temp_dir):
        """Test start with --no-auto-merge option."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(
                            app,
                            ["start", "Test goal", "--no-auto-merge"],
                        )

        assert "Auto-merge: False" in result.output

    def test_start_with_max_sessions(self, cli_runner, temp_dir):
        """Test start with --max-sessions option."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(
                            app,
                            ["start", "Test goal", "--max-sessions", "5"],
                        )

        # Should start without error related to max-sessions
        assert result.exit_code == 1  # Still fails at planning, but accepted option

    def test_start_with_pause_on_pr(self, cli_runner, temp_dir):
        """Test start with --pause-on-pr option."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(
                            app,
                            ["start", "Test goal", "--pause-on-pr"],
                        )

        # Should start without error related to pause-on-pr
        assert result.exit_code == 1  # Still fails at planning, but accepted option


# =============================================================================
# Start Command Full Workflow Tests
# =============================================================================


class TestStartCommandWorkflow:
    """Tests for start command workflow."""

    def test_start_successful_planning(self, cli_runner, temp_dir):
        """Test start with successful planning phase."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.return_value = {
                            "plan": "## Tasks\n- [ ] Task 1",
                            "raw_output": "Planning output",
                        }
                        with patch(
                            "claude_task_master.cli.WorkLoopOrchestrator"
                        ) as mock_orchestrator:
                            mock_orchestrator.return_value.run.return_value = 0

                            result = cli_runner.invoke(app, ["start", "Complete the task"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output

    def test_start_orchestrator_paused(self, cli_runner, temp_dir):
        """Test start when orchestrator returns paused status."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.return_value = {
                            "plan": "## Tasks\n- [ ] Task 1",
                            "raw_output": "Planning output",
                        }
                        with patch(
                            "claude_task_master.cli.WorkLoopOrchestrator"
                        ) as mock_orchestrator:
                            mock_orchestrator.return_value.run.return_value = 2

                            result = cli_runner.invoke(app, ["start", "Complete the task"])

        assert result.exit_code == 2
        assert "paused" in result.output
        assert "resume" in result.output

    def test_start_orchestrator_blocked(self, cli_runner, temp_dir):
        """Test start when orchestrator returns blocked status."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.return_value = {
                            "plan": "## Tasks\n- [ ] Task 1",
                            "raw_output": "Planning output",
                        }
                        with patch(
                            "claude_task_master.cli.WorkLoopOrchestrator"
                        ) as mock_orchestrator:
                            mock_orchestrator.return_value.run.return_value = 1

                            result = cli_runner.invoke(app, ["start", "Complete the task"])

        assert result.exit_code == 1
        assert "blocked" in result.output or "failed" in result.output

    def test_start_planning_phase_failure(self, cli_runner, temp_dir):
        """Test start when planning phase fails."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch("claude_task_master.cli.CredentialManager") as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli.AgentWrapper"):
                    with patch("claude_task_master.cli.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception(
                            "Planning failed: API error"
                        )

                        result = cli_runner.invoke(app, ["start", "Complete the task"])

        assert result.exit_code == 1
        assert "Planning failed" in result.output


# =============================================================================
# CLI App Configuration Tests
# =============================================================================


class TestCLIAppConfiguration:
    """Tests for CLI app configuration."""

    def test_app_name(self):
        """Test app has correct name."""
        assert app.info.name == "claude-task-master"

    def test_app_help_text(self):
        """Test app has help text."""
        assert app.info.help and "Claude Agent SDK" in app.info.help

    def test_app_commands_registered(self, cli_runner):
        """Test all commands are registered."""
        result = cli_runner.invoke(app, ["--help"])

        assert "start" in result.output
        assert "resume" in result.output
        assert "status" in result.output
        assert "plan" in result.output
        assert "logs" in result.output
        assert "context" in result.output
        assert "progress" in result.output
        assert "comments" in result.output
        assert "pr" in result.output
        assert "clean" in result.output
        assert "doctor" in result.output


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestCLIEdgeCases:
    """Edge case tests for CLI commands."""

    def test_status_with_no_current_pr(self, cli_runner, temp_dir, mock_state_dir, mock_goal_file):
        """Test status when current_pr is None."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "working",
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": None,  # No PR
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,  # Unlimited
                "pause_on_pr": False,
            },
        }
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "unlimited" in result.output  # max_sessions is None

    def test_logs_with_empty_log_file(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_logs_dir
    ):
        """Test logs with empty log file."""
        log_file = mock_logs_dir / "run-20250115-120000.txt"
        log_file.write_text("")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 0

    def test_logs_with_tail_larger_than_file(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file, mock_logs_dir
    ):
        """Test logs with tail option larger than file content."""
        log_file = mock_logs_dir / "run-20250115-120000.txt"
        log_file.write_text("Line 1\nLine 2\nLine 3\n")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["logs", "--tail", "100"])

        assert result.exit_code == 0
        assert "Line 1" in result.output
        assert "Line 2" in result.output
        assert "Line 3" in result.output

    def test_context_with_empty_context(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test context with empty context file."""
        context_file = mock_state_dir / "context.md"
        context_file.write_text("")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["context"])

        # Empty context should show "No context accumulated"
        assert result.exit_code == 0

    def test_progress_with_empty_progress(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test progress with empty progress file."""
        progress_file = mock_state_dir / "progress.md"
        progress_file.write_text("")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["progress"])

        # Empty progress should show "No progress recorded"
        assert result.exit_code == 0

    def test_plan_with_complex_markdown(
        self, cli_runner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test plan with complex markdown content."""
        plan_file = mock_state_dir / "plan.md"
        plan_file.write_text("""# Complex Plan

## Phase 1

```python
def example():
    return "Hello"
```

| Table | Header |
|-------|--------|
| Cell  | Data   |

> Blockquote with **bold** and *italic*
""")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["plan"])

        assert result.exit_code == 0
        assert "Complex Plan" in result.output


# =============================================================================
# Help Text Tests
# =============================================================================


class TestCLIHelpText:
    """Tests for CLI help text."""

    def test_start_help(self, cli_runner):
        """Test start command help."""
        result = cli_runner.invoke(app, ["start", "--help"])
        output = strip_ansi(result.output)

        assert "goal" in output.lower()
        assert "--model" in output
        assert "--auto-merge" in output
        assert "--max-sessions" in output
        assert "--pause-on-pr" in output

    def test_status_help(self, cli_runner):
        """Test status command help."""
        result = cli_runner.invoke(app, ["status", "--help"])

        assert "status" in result.output.lower()

    def test_plan_help(self, cli_runner):
        """Test plan command help."""
        result = cli_runner.invoke(app, ["plan", "--help"])

        assert "plan" in result.output.lower()

    def test_logs_help(self, cli_runner):
        """Test logs command help."""
        result = cli_runner.invoke(app, ["logs", "--help"])
        output = strip_ansi(result.output)

        assert "--tail" in output
        assert "--session" in output

    def test_context_help(self, cli_runner):
        """Test context command help."""
        result = cli_runner.invoke(app, ["context", "--help"])

        assert "context" in result.output.lower()

    def test_progress_help(self, cli_runner):
        """Test progress command help."""
        result = cli_runner.invoke(app, ["progress", "--help"])

        assert "progress" in result.output.lower()

    def test_comments_help(self, cli_runner):
        """Test comments command help."""
        result = cli_runner.invoke(app, ["comments", "--help"])
        output = strip_ansi(result.output)

        assert "--pr" in output

    def test_pr_help(self, cli_runner):
        """Test pr command help."""
        result = cli_runner.invoke(app, ["pr", "--help"])

        assert "pr" in result.output.lower()

    def test_clean_help(self, cli_runner):
        """Test clean command help."""
        result = cli_runner.invoke(app, ["clean", "--help"])
        output = strip_ansi(result.output)

        assert "--force" in output

    def test_doctor_help(self, cli_runner):
        """Test doctor command help."""
        result = cli_runner.invoke(app, ["doctor", "--help"])

        assert "doctor" in result.output.lower()

    def test_resume_help(self, cli_runner):
        """Test resume command help."""
        result = cli_runner.invoke(app, ["resume", "--help"])

        assert "resume" in result.output.lower()
