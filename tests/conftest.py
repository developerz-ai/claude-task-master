"""Pytest configuration and fixtures for claude-task-master tests."""

import json
import time
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Directory and File Fixtures
# =============================================================================


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for tests."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def state_dir(temp_dir: Path) -> Path:
    """Provide a state directory path for tests."""
    state_path = temp_dir / ".claude-task-master"
    state_path.mkdir(parents=True)
    return state_path


@pytest.fixture
def logs_dir(state_dir: Path) -> Path:
    """Provide a logs directory path for tests."""
    logs_path = state_dir / "logs"
    logs_path.mkdir(parents=True)
    return logs_path


# =============================================================================
# Credentials Fixtures
# =============================================================================


@pytest.fixture
def mock_credentials_data() -> dict[str, Any]:
    """Provide raw mock credentials data as stored in file."""
    # Timestamp in milliseconds for a future date (1 hour from now)
    future_timestamp = int((datetime.now() + timedelta(hours=1)).timestamp() * 1000)
    return {
        "claudeAiOauth": {
            "accessToken": "test-access-token-12345",
            "refreshToken": "test-refresh-token-67890",
            "expiresAt": future_timestamp,
            "tokenType": "Bearer",
        }
    }


@pytest.fixture
def mock_expired_credentials_data() -> dict[str, Any]:
    """Provide mock expired credentials data."""
    # Timestamp in milliseconds for a past date (1 hour ago)
    past_timestamp = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)
    return {
        "claudeAiOauth": {
            "accessToken": "expired-access-token",
            "refreshToken": "test-refresh-token-67890",
            "expiresAt": past_timestamp,
            "tokenType": "Bearer",
        }
    }


@pytest.fixture
def mock_credentials_file(temp_dir: Path, mock_credentials_data: dict[str, Any]) -> Path:
    """Create a mock credentials file and return its path."""
    credentials_path = temp_dir / ".claude" / ".credentials.json"
    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    credentials_path.write_text(json.dumps(mock_credentials_data))
    return credentials_path


@pytest.fixture
def mock_expired_credentials_file(
    temp_dir: Path, mock_expired_credentials_data: dict[str, Any]
) -> Path:
    """Create a mock expired credentials file and return its path."""
    credentials_path = temp_dir / ".claude" / ".credentials.json"
    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    credentials_path.write_text(json.dumps(mock_expired_credentials_data))
    return credentials_path


# =============================================================================
# State Fixtures
# =============================================================================


@pytest.fixture
def sample_task_options() -> dict[str, Any]:
    """Provide sample task options."""
    return {
        "auto_merge": True,
        "max_sessions": 10,
        "pause_on_pr": False,
    }


@pytest.fixture
def sample_task_state(sample_task_options: dict[str, Any]) -> dict[str, Any]:
    """Provide sample task state data."""
    timestamp = datetime.now().isoformat()
    return {
        "status": "working",
        "current_task_index": 0,
        "session_count": 1,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "20250115-120000",
        "model": "sonnet",
        "options": sample_task_options,
    }


@pytest.fixture
def sample_state_file(state_dir: Path, sample_task_state: dict[str, Any]) -> Path:
    """Create a sample state file and return its path."""
    state_file = state_dir / "state.json"
    state_file.write_text(json.dumps(sample_task_state))
    return state_file


@pytest.fixture
def sample_goal() -> str:
    """Provide a sample goal."""
    return "Implement a new feature with tests and documentation"


@pytest.fixture
def sample_goal_file(state_dir: Path, sample_goal: str) -> Path:
    """Create a sample goal file and return its path."""
    goal_file = state_dir / "goal.txt"
    goal_file.write_text(sample_goal)
    return goal_file


@pytest.fixture
def sample_plan() -> str:
    """Provide a sample plan markdown."""
    return """## Task List

- [ ] Set up project structure
- [ ] Implement core functionality
- [ ] Add unit tests
- [x] Write documentation

## Success Criteria

1. All tests pass with >80% coverage
2. Documentation is complete
3. No critical bugs
"""


@pytest.fixture
def sample_plan_file(state_dir: Path, sample_plan: str) -> Path:
    """Create a sample plan file and return its path."""
    plan_file = state_dir / "plan.md"
    plan_file.write_text(sample_plan)
    return plan_file


@pytest.fixture
def sample_criteria() -> str:
    """Provide sample success criteria."""
    return """1. All tests pass with >80% coverage
2. Documentation is complete
3. No critical bugs
"""


@pytest.fixture
def sample_criteria_file(state_dir: Path, sample_criteria: str) -> Path:
    """Create a sample criteria file and return its path."""
    criteria_file = state_dir / "criteria.txt"
    criteria_file.write_text(sample_criteria)
    return criteria_file


@pytest.fixture
def sample_progress() -> str:
    """Provide a sample progress summary."""
    return """# Progress Update

Session: 1
Current Task: 2 of 4

## Latest Task
Implement core functionality

## Result
Successfully implemented core functionality with all edge cases handled.
"""


@pytest.fixture
def sample_progress_file(state_dir: Path, sample_progress: str) -> Path:
    """Create a sample progress file and return its path."""
    progress_file = state_dir / "progress.md"
    progress_file.write_text(sample_progress)
    return progress_file


@pytest.fixture
def sample_context() -> str:
    """Provide sample accumulated context."""
    return """# Accumulated Context

## Session 1

Completed initial setup and explored the codebase.

## Learning

The project uses a modular architecture with clear separation of concerns.
"""


@pytest.fixture
def sample_context_file(state_dir: Path, sample_context: str) -> Path:
    """Create a sample context file and return its path."""
    context_file = state_dir / "context.md"
    context_file.write_text(sample_context)
    return context_file


# =============================================================================
# State Manager Fixture
# =============================================================================


@pytest.fixture
def state_manager(state_dir: Path):
    """Provide a configured StateManager instance."""
    from claude_task_master.core.state import StateManager

    return StateManager(state_dir)


@pytest.fixture
def initialized_state_manager(state_manager, sample_goal: str, sample_task_options: dict[str, Any]):
    """Provide an initialized StateManager with state already created."""
    from claude_task_master.core.state import TaskOptions

    options = TaskOptions(**sample_task_options)
    state_manager.initialize(goal=sample_goal, model="sonnet", options=options)
    return state_manager


# =============================================================================
# Agent Fixtures
# =============================================================================


@pytest.fixture
def mock_claude_agent_sdk():
    """Mock the Claude Agent SDK."""
    with patch.dict("sys.modules", {"claude_agent_sdk": MagicMock()}):
        mock_module = MagicMock()
        mock_module.query = AsyncMock()
        mock_module.ClaudeAgentOptions = MagicMock()
        yield mock_module


@pytest.fixture
def mock_agent_wrapper(temp_dir: Path):
    """Provide a mocked AgentWrapper."""
    mock = MagicMock()
    mock.access_token = "test-token"
    mock.model = "sonnet"
    mock.working_dir = str(temp_dir)

    # Mock the methods
    mock.run_planning_phase = MagicMock(
        return_value={
            "plan": "## Task List\n- [ ] Task 1\n- [ ] Task 2",
            "criteria": "All tasks completed",
            "raw_output": "Planning output",
        }
    )
    mock.run_work_session = MagicMock(return_value={"output": "Work completed", "success": True})
    mock.verify_success_criteria = MagicMock(
        return_value={"success": True, "details": "All criteria met"}
    )
    mock.get_tools_for_phase = MagicMock(
        side_effect=lambda phase: ["Read", "Glob", "Grep"]
        if phase == "planning"
        else ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
    )

    return mock


# =============================================================================
# Planner Fixtures
# =============================================================================


@pytest.fixture
def planner(mock_agent_wrapper, state_manager):
    """Provide a Planner instance with mocked agent."""
    from claude_task_master.core.planner import Planner

    return Planner(agent=mock_agent_wrapper, state_manager=state_manager)


# =============================================================================
# Orchestrator Fixtures
# =============================================================================


@pytest.fixture
def orchestrator(mock_agent_wrapper, initialized_state_manager, planner, mock_github_client):
    """Provide a WorkLoopOrchestrator instance."""
    from claude_task_master.core.orchestrator import WorkLoopOrchestrator

    # Save a plan first
    initialized_state_manager.save_plan(
        "## Task List\n- [ ] Task 1\n- [ ] Task 2\n\n## Success Criteria\n1. All done"
    )

    return WorkLoopOrchestrator(
        agent=mock_agent_wrapper,
        state_manager=initialized_state_manager,
        planner=planner,
        github_client=mock_github_client,
    )


# =============================================================================
# Logger Fixtures
# =============================================================================


@pytest.fixture
def log_file(logs_dir: Path) -> Path:
    """Provide a log file path for tests."""
    return logs_dir / "run-test.txt"


@pytest.fixture
def task_logger(log_file: Path):
    """Provide a TaskLogger instance with VERBOSE level for full test coverage."""
    from claude_task_master.core.logger import LogLevel, TaskLogger

    # Use VERBOSE level to ensure all logging methods write output for existing tests
    return TaskLogger(log_file, level=LogLevel.VERBOSE)


# =============================================================================
# Context Accumulator Fixtures
# =============================================================================


@pytest.fixture
def context_accumulator(state_manager):
    """Provide a ContextAccumulator instance."""
    from claude_task_master.core.context_accumulator import ContextAccumulator

    # Ensure state directory exists
    state_manager.state_dir.mkdir(exist_ok=True)
    return ContextAccumulator(state_manager)


# =============================================================================
# GitHub Client Fixtures
# =============================================================================


@pytest.fixture
def mock_gh_cli_success():
    """Mock successful gh CLI operations."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/owner/repo/pull/123\n",
            stderr="",
        )
        yield mock_run


@pytest.fixture
def mock_gh_cli_failure():
    """Mock failed gh CLI operations."""
    with patch("subprocess.run") as mock_run:
        from subprocess import CalledProcessError

        mock_run.side_effect = CalledProcessError(1, "gh", "Error message")
        yield mock_run


@pytest.fixture
def mock_github_client():
    """Provide a mocked GitHubClient."""
    mock = MagicMock()
    mock.create_pr = MagicMock(return_value=123)
    mock.get_pr_for_current_branch = MagicMock(return_value=None)
    mock.get_pr_status = MagicMock(
        return_value=MagicMock(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[],
        )
    )
    mock.get_pr_comments = MagicMock(return_value="")
    mock.merge_pr = MagicMock()
    return mock


@pytest.fixture
def sample_pr_graphql_response() -> dict[str, Any]:
    """Provide a sample GraphQL response for PR queries."""
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "commits": {
                        "nodes": [
                            {
                                "commit": {
                                    "statusCheckRollup": {
                                        "state": "SUCCESS",
                                        "contexts": {
                                            "nodes": [
                                                {
                                                    "__typename": "CheckRun",
                                                    "name": "tests",
                                                    "status": "COMPLETED",
                                                    "conclusion": "SUCCESS",
                                                    "detailsUrl": "https://example.com/check",
                                                }
                                            ]
                                        },
                                    }
                                }
                            }
                        ]
                    },
                    "reviewThreads": {
                        "nodes": [
                            {
                                "isResolved": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "reviewer"},
                                            "body": "Please fix this",
                                            "path": "src/main.py",
                                            "line": 42,
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                }
            }
        }
    }


# =============================================================================
# CLI Fixtures
# =============================================================================


@pytest.fixture
def cli_runner():
    """Provide a Typer CLI test runner."""
    from typer.testing import CliRunner

    return CliRunner()


@pytest.fixture
def cli_app():
    """Provide the CLI app for testing."""
    from claude_task_master.cli import app

    return app


# =============================================================================
# Doctor Fixtures
# =============================================================================


@pytest.fixture
def mock_doctor_checks():
    """Mock all doctor system checks."""
    with patch("subprocess.run") as mock_run:
        # Mock gh CLI check
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        yield mock_run


# =============================================================================
# Async Test Helpers
# =============================================================================


@pytest.fixture
def event_loop_policy():
    """Provide the default event loop policy for async tests."""
    import asyncio

    return asyncio.DefaultEventLoopPolicy()


# =============================================================================
# Pytest Configuration
# =============================================================================


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (require external services)"
    )
    config.addinivalue_line("markers", "unit: marks tests as unit tests")


def pytest_collection_modifyitems(config, items):
    """Automatically mark tests based on their location."""
    for item in items:
        # Add 'unit' marker to tests in core/ or utils/
        if "core" in str(item.fspath) or "utils" in str(item.fspath):
            item.add_marker(pytest.mark.unit)

        # Add 'integration' marker to tests in github/
        if "github" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


# =============================================================================
# Cleanup Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def cleanup_env(monkeypatch):
    """Clean up environment variables after each test."""
    # Store original environment

    yield

    # No cleanup needed as monkeypatch handles it automatically


@pytest.fixture
def isolated_filesystem(temp_dir: Path, monkeypatch):
    """Provide an isolated filesystem for tests that need to change cwd."""
    Path.cwd()
    monkeypatch.chdir(temp_dir)
    yield temp_dir
    # monkeypatch automatically restores cwd


# =============================================================================
# Multi-file Log Fixtures (for cleanup tests)
# =============================================================================


@pytest.fixture
def multiple_log_files(logs_dir: Path) -> list[Path]:
    """Create multiple log files for testing cleanup."""
    log_files = []
    for i in range(15):  # Create 15 log files
        log_file = logs_dir / f"run-2025011{i:02d}-120000.txt"
        log_file.write_text(f"Log content for session {i}")
        time.sleep(0.01)  # Small delay to ensure different mtime
        log_files.append(log_file)
    return log_files
