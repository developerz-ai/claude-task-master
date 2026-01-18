"""Unit tests for cli_commands/info.py module.

Tests the info command functions directly (status, plan, logs, context, progress)
as well as the register_info_commands utility.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer import Typer

from claude_task_master.cli_commands import info
from claude_task_master.core.state import StateManager

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_console():
    """Mock the rich console."""
    with patch.object(info, "console") as mock:
        yield mock


@pytest.fixture
def mock_state_manager():
    """Create a mock StateManager."""
    mock = MagicMock(spec=StateManager)
    return mock


@pytest.fixture
def info_state_dir(temp_dir: Path) -> Path:
    """Create a state directory for info command tests."""
    state_dir = temp_dir / ".claude-task-master"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture
def info_logs_dir(info_state_dir: Path) -> Path:
    """Create a logs directory for info command tests."""
    logs_dir = info_state_dir / "logs"
    logs_dir.mkdir(parents=True)
    return logs_dir


@pytest.fixture
def info_state_file(info_state_dir: Path) -> Path:
    """Create a mock state file."""
    from datetime import datetime

    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "current_task_index": 2,
        "session_count": 5,
        "current_pr": 42,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "test-run-123",
        "model": "sonnet",
        "options": {
            "auto_merge": False,
            "max_sessions": 20,
            "pause_on_pr": True,
            "log_level": "normal",
            "log_format": "text",
        },
    }
    state_file = info_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data))
    return state_file


@pytest.fixture
def info_goal_file(info_state_dir: Path) -> Path:
    """Create a mock goal file."""
    goal_file = info_state_dir / "goal.txt"
    goal_file.write_text("Build a comprehensive test suite")
    return goal_file


@pytest.fixture
def info_plan_file(info_state_dir: Path) -> Path:
    """Create a mock plan file."""
    plan_content = """## Task List

- [x] Task 1: Setup project
- [ ] Task 2: Implement feature
- [ ] Task 3: Add tests

## Success Criteria

1. All tests pass
2. Coverage > 80%
"""
    plan_file = info_state_dir / "plan.md"
    plan_file.write_text(plan_content)
    return plan_file


@pytest.fixture
def info_context_file(info_state_dir: Path) -> Path:
    """Create a mock context file."""
    context_content = """# Accumulated Context

## Session 1

Explored the codebase and identified key components.

## Learning

The project uses a modular architecture.
"""
    context_file = info_state_dir / "context.md"
    context_file.write_text(context_content)
    return context_file


@pytest.fixture
def info_progress_file(info_state_dir: Path) -> Path:
    """Create a mock progress file."""
    progress_content = """# Progress Update

Session: 5
Current Task: 3 of 5

## Latest Task
Implement feature X

## Result
Successfully implemented with all edge cases handled.
"""
    progress_file = info_state_dir / "progress.md"
    progress_file.write_text(progress_content)
    return progress_file


@pytest.fixture
def info_log_file(info_logs_dir: Path) -> Path:
    """Create a mock log file."""
    log_file = info_logs_dir / "run-test-run-123.txt"
    log_file.write_text("\n".join([f"Log line {i}" for i in range(200)]))
    return log_file


# =============================================================================
# Tests for status()
# =============================================================================


class TestStatusFunction:
    """Unit tests for the status() function."""

    def test_status_no_active_task(self, temp_dir: Path, mock_console):
        """Test status when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with pytest.raises(typer.Exit) as exc_info:
                info.status()

        assert exc_info.value.exit_code == 1
        mock_console.print.assert_called()
        # Check that "No active task found" message was printed
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("No active task found" in str(call) for call in calls)

    def test_status_shows_task_info(
        self,
        info_state_dir: Path,
        info_state_file: Path,
        info_goal_file: Path,
        mock_console,
    ):
        """Test status displays task information correctly."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            info.status()

        # Verify console.print was called with expected content
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Task Status" in str(call) for call in calls)
        assert any("Build a comprehensive test suite" in str(call) for call in calls)
        assert any("working" in str(call) for call in calls)
        assert any("sonnet" in str(call) for call in calls)

    def test_status_shows_pr_number(
        self,
        info_state_dir: Path,
        info_state_file: Path,
        info_goal_file: Path,
        mock_console,
    ):
        """Test status shows current PR number when set."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            info.status()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("42" in str(call) for call in calls)

    def test_status_shows_options(
        self,
        info_state_dir: Path,
        info_state_file: Path,
        info_goal_file: Path,
        mock_console,
    ):
        """Test status shows task options."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            info.status()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Auto-merge" in str(call) for call in calls)
        assert any("Max sessions" in str(call) for call in calls)
        assert any("Pause on PR" in str(call) for call in calls)

    def test_status_handles_load_error(self, info_state_dir: Path, mock_console):
        """Test status handles load errors gracefully."""
        # Create invalid state file
        state_file = info_state_dir / "state.json"
        state_file.write_text("invalid json{")

        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            with pytest.raises(typer.Exit) as exc_info:
                info.status()

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Error" in str(call) for call in calls)

    def test_status_without_pr(
        self,
        info_state_dir: Path,
        info_goal_file: Path,
        mock_console,
    ):
        """Test status when no PR is set."""
        from datetime import datetime

        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "planning",
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "test-run",
            "model": "opus",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": False,
                "log_level": "verbose",
                "log_format": "json",
            },
        }
        state_file = info_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            info.status()

        # Should not crash, but won't have PR line
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Task Status" in str(call) for call in calls)


# =============================================================================
# Tests for plan()
# =============================================================================


class TestPlanFunction:
    """Unit tests for the plan() function."""

    def test_plan_no_active_task(self, temp_dir: Path, mock_console):
        """Test plan when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with pytest.raises(typer.Exit) as exc_info:
                info.plan()

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("No active task found" in str(call) for call in calls)

    def test_plan_no_plan_file(self, info_state_dir: Path, info_state_file: Path, mock_console):
        """Test plan when no plan.md exists."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            with pytest.raises(typer.Exit) as exc_info:
                info.plan()

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("No plan found" in str(call) for call in calls)

    def test_plan_shows_content(
        self,
        info_state_dir: Path,
        info_state_file: Path,
        info_plan_file: Path,
        mock_console,
    ):
        """Test plan shows plan content."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            info.plan()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Task Plan" in str(call) for call in calls)

    def test_plan_handles_error(self, info_state_dir: Path, info_state_file: Path, mock_console):
        """Test plan handles errors gracefully."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            with patch.object(StateManager, "load_plan", side_effect=Exception("IO Error")):
                with pytest.raises(typer.Exit) as exc_info:
                    info.plan()

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Error" in str(call) for call in calls)


# =============================================================================
# Tests for logs()
# =============================================================================


class TestLogsFunction:
    """Unit tests for the logs() function."""

    def test_logs_no_active_task(self, temp_dir: Path, mock_console):
        """Test logs when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with pytest.raises(typer.Exit) as exc_info:
                info.logs(session=None, tail=100)

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("No active task found" in str(call) for call in calls)

    def test_logs_no_log_file(
        self,
        info_state_dir: Path,
        info_state_file: Path,
        info_logs_dir: Path,
        mock_console,
    ):
        """Test logs when no log file exists."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            with pytest.raises(typer.Exit) as exc_info:
                info.logs(session=None, tail=100)

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("No log file found" in str(call) for call in calls)

    def test_logs_shows_content(
        self,
        info_state_dir: Path,
        info_state_file: Path,
        info_log_file: Path,
        mock_console,
        capsys,
    ):
        """Test logs shows log content."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            # Call with explicit parameters since typer defaults don't work in tests
            info.logs(session=None, tail=100)

        # Check console output for header
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Logs" in str(call) for call in calls)

        # Check stdout for log content (logs uses print() for log lines)
        captured = capsys.readouterr()
        assert "Log line 199" in captured.out
        assert "Log line 100" in captured.out

    def test_logs_with_tail_option(
        self,
        info_state_dir: Path,
        info_state_file: Path,
        info_log_file: Path,
        mock_console,
        capsys,
    ):
        """Test logs with custom tail option."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            info.logs(tail=10)

        captured = capsys.readouterr()
        assert "Log line 199" in captured.out
        assert "Log line 190" in captured.out
        assert "Log line 180" not in captured.out

    def test_logs_handles_error(self, info_state_dir: Path, mock_console):
        """Test logs handles errors gracefully."""
        # Create invalid state file
        state_file = info_state_dir / "state.json"
        state_file.write_text("invalid json")

        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            with pytest.raises(typer.Exit) as exc_info:
                info.logs(session=None, tail=100)

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Error" in str(call) for call in calls)

    def test_logs_session_parameter_ignored(
        self,
        info_state_dir: Path,
        info_state_file: Path,
        info_log_file: Path,
        mock_console,
        capsys,
    ):
        """Test logs with session parameter (currently ignored but accepted)."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            # Should not raise - session is accepted but not used
            info.logs(session=5, tail=100)

        captured = capsys.readouterr()
        assert "Log line" in captured.out


# =============================================================================
# Tests for context()
# =============================================================================


class TestContextFunction:
    """Unit tests for the context() function."""

    def test_context_no_active_task(self, temp_dir: Path, mock_console):
        """Test context when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with pytest.raises(typer.Exit) as exc_info:
                info.context()

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("No active task found" in str(call) for call in calls)

    def test_context_no_context_file(
        self, info_state_dir: Path, info_state_file: Path, mock_console
    ):
        """Test context when no context.md exists."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            info.context()  # Should not raise

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("No context accumulated yet" in str(call) for call in calls)

    def test_context_shows_content(
        self,
        info_state_dir: Path,
        info_state_file: Path,
        info_context_file: Path,
        mock_console,
    ):
        """Test context shows context content."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            info.context()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Accumulated Context" in str(call) for call in calls)

    def test_context_handles_error(self, info_state_dir: Path, info_state_file: Path, mock_console):
        """Test context handles errors gracefully."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            with patch.object(StateManager, "load_context", side_effect=Exception("IO Error")):
                with pytest.raises(typer.Exit) as exc_info:
                    info.context()

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Error" in str(call) for call in calls)


# =============================================================================
# Tests for progress()
# =============================================================================


class TestProgressFunction:
    """Unit tests for the progress() function."""

    def test_progress_no_active_task(self, temp_dir: Path, mock_console):
        """Test progress when no task exists."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with pytest.raises(typer.Exit) as exc_info:
                info.progress()

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("No active task found" in str(call) for call in calls)

    def test_progress_no_progress_file(
        self, info_state_dir: Path, info_state_file: Path, mock_console
    ):
        """Test progress when no progress.md exists."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            info.progress()  # Should not raise

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("No progress recorded yet" in str(call) for call in calls)

    def test_progress_shows_content(
        self,
        info_state_dir: Path,
        info_state_file: Path,
        info_progress_file: Path,
        mock_console,
    ):
        """Test progress shows progress content."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            info.progress()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Progress Summary" in str(call) for call in calls)

    def test_progress_handles_error(
        self, info_state_dir: Path, info_state_file: Path, mock_console
    ):
        """Test progress handles errors gracefully."""
        with patch.object(StateManager, "STATE_DIR", info_state_dir):
            with patch.object(StateManager, "load_progress", side_effect=Exception("IO Error")):
                with pytest.raises(typer.Exit) as exc_info:
                    info.progress()

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Error" in str(call) for call in calls)


# =============================================================================
# Tests for register_info_commands()
# =============================================================================


class TestRegisterInfoCommands:
    """Unit tests for the register_info_commands() function."""

    def test_register_all_commands(self):
        """Test that all info commands are registered."""
        app = Typer()
        info.register_info_commands(app)

        # Get registered command names (name or callback function name)
        command_names = [
            cmd.name or (cmd.callback.__name__ if cmd.callback else None)
            for cmd in app.registered_commands
        ]

        assert "status" in command_names
        assert "plan" in command_names
        assert "logs" in command_names
        assert "context" in command_names
        assert "progress" in command_names

    def test_register_commands_count(self):
        """Test that exactly 5 commands are registered."""
        app = Typer()
        info.register_info_commands(app)

        assert len(app.registered_commands) == 5

    def test_commands_are_callable(self):
        """Test that registered commands are callable."""
        app = Typer()
        info.register_info_commands(app)

        for cmd in app.registered_commands:
            assert callable(cmd.callback)
