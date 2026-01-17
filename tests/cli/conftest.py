"""Shared fixtures for CLI command tests."""

import json
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_task_master.core.state import StateManager


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_pattern.sub("", text)


# =============================================================================
# Mock State Directory Fixtures
# =============================================================================


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


# =============================================================================
# Mock State File Fixtures
# =============================================================================


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
# State Creation Helpers
# =============================================================================


def create_state_data(
    status: str = "paused",
    current_task_index: int = 0,
    session_count: int = 1,
    current_pr: int | None = None,
    model: str = "sonnet",
    auto_merge: bool = True,
    max_sessions: int | None = None,
    pause_on_pr: bool = False,
    run_id: str = "20250115-120000",
    created_at: str | None = None,
) -> dict:
    """Create state data with customizable values."""
    timestamp = datetime.now().isoformat()
    return {
        "status": status,
        "current_task_index": current_task_index,
        "session_count": session_count,
        "current_pr": current_pr,
        "created_at": created_at or timestamp,
        "updated_at": timestamp,
        "run_id": run_id,
        "model": model,
        "options": {
            "auto_merge": auto_merge,
            "max_sessions": max_sessions,
            "pause_on_pr": pause_on_pr,
        },
    }


@pytest.fixture
def state_data_factory():
    """Factory fixture for creating state data."""
    return create_state_data


# =============================================================================
# Resume Command Mock Context
# =============================================================================


@contextmanager
def mock_resume_context(mock_state_dir: Path, return_code: int = 0, raise_exception=None):
    """Context manager for mocking the resume workflow dependencies.

    This is a shared context manager used across multiple resume test modules
    to mock the workflow components needed for testing the resume command.

    Args:
        mock_state_dir: Path to the mock state directory
        return_code: Return code from the orchestrator (default 0 for success)
        raise_exception: Optional exception to raise from orchestrator.run()

    Yields:
        mock_orch: The mocked WorkLoopOrchestrator instance

    Example:
        with mock_resume_context(mock_state_dir) as mock_orch:
            result = cli_runner.invoke(app, ["resume"])
            assert result.exit_code == 0
    """
    with patch.object(StateManager, "STATE_DIR", mock_state_dir):
        with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
            mock_cred.return_value.get_valid_token.return_value = "test-token"
            with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                with patch(
                    "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                ) as mock_orch:
                    if raise_exception:
                        mock_orch.return_value.run.side_effect = raise_exception
                    else:
                        mock_orch.return_value.run.return_value = return_code
                    yield mock_orch


# =============================================================================
# Resume Command Setup Fixtures
# =============================================================================


@pytest.fixture
def setup_resume_state(
    mock_state_dir: Path, mock_goal_file: Path, mock_plan_file: Path, state_data_factory
):
    """Generic fixture to setup state for resume command testing.

    This fixture creates a state file with the provided parameters and ensures
    the logs directory exists. It's designed to be flexible for various resume
    test scenarios.

    Args:
        mock_state_dir: Path to the mock state directory (from fixture)
        mock_goal_file: Path to the mock goal file (from fixture)
        mock_plan_file: Path to the mock plan file (from fixture)
        state_data_factory: Factory function for creating state data (from fixture)

    Returns:
        A setup function that accepts keyword arguments matching create_state_data parameters

    Example:
        def test_resume_something(cli_runner, mock_state_dir, setup_resume_state):
            setup_resume_state(status="paused", session_count=5, current_pr=123)
            with mock_resume_context(mock_state_dir):
                result = cli_runner.invoke(app, ["resume"])
            assert result.exit_code == 0
    """

    def _setup(**state_kwargs: object) -> dict[str, object]:
        """Setup state file and logs directory with given parameters.

        Args:
            **state_kwargs: Keyword arguments passed to create_state_data()

        Returns:
            The created state data dictionary
        """
        state_data: dict[str, object] = state_data_factory(**state_kwargs)
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return state_data

    return _setup
