"""Shared fixtures for CLI command tests."""

import json
import re
from datetime import datetime
from pathlib import Path

import pytest


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
