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
