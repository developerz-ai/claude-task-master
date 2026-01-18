"""Shared fixtures for API tests.

Provides common fixtures for testing FastAPI endpoints including:
- TestClient for HTTP testing
- Mocked state directory and files
- Sample data for API requests/responses
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

# Skip all API tests if FastAPI is not installed
try:
    from fastapi.testclient import TestClient

    FASTAPI_AVAILABLE = True
except ImportError:
    TestClient = None  # type: ignore[assignment,misc]
    FASTAPI_AVAILABLE = False

# Apply skip marker to all tests in this package
pytestmark = pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")


# =============================================================================
# FastAPI App Fixtures
# =============================================================================


@pytest.fixture
def api_state_dir(temp_dir: Path) -> Path:
    """Create a state directory for API tests."""
    state_dir = temp_dir / ".claude-task-master"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture
def api_logs_dir(api_state_dir: Path) -> Path:
    """Create a logs directory for API tests."""
    logs_dir = api_state_dir / "logs"
    logs_dir.mkdir(parents=True)
    return logs_dir


@pytest.fixture
def api_app(temp_dir: Path, api_state_dir: Path):
    """Create a FastAPI app instance for testing.

    The app is configured with a temporary working directory and
    no CORS restrictions for testing.
    """
    from claude_task_master.api.server import create_app

    return create_app(
        working_dir=temp_dir,
        cors_origins=["*"],
        include_docs=True,
    )


@pytest.fixture
def api_client(api_app):
    """Create a FastAPI TestClient for making HTTP requests.

    This fixture provides a client that can make synchronous HTTP requests
    to the FastAPI app without running an actual server.

    Example:
        def test_endpoint(api_client):
            response = api_client.get("/health")
            assert response.status_code == 200
    """
    if TestClient is None:
        pytest.skip("FastAPI not installed")

    with TestClient(api_app) as client:
        yield client


# =============================================================================
# State File Fixtures for API Tests
# =============================================================================


@pytest.fixture
def api_goal_file(api_state_dir: Path) -> Path:
    """Create a mock goal.txt file for API tests."""
    goal_file = api_state_dir / "goal.txt"
    goal_file.write_text("Build a production-ready REST API")
    return goal_file


@pytest.fixture
def api_state_file(api_state_dir: Path) -> Path:
    """Create a mock state.json file for API tests."""
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "current_task_index": 1,
        "session_count": 2,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "20250118-120000",
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": 10,
            "pause_on_pr": False,
        },
    }
    state_file = api_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data))
    return state_file


@pytest.fixture
def api_plan_file(api_state_dir: Path) -> Path:
    """Create a mock plan.md file for API tests."""
    plan_file = api_state_dir / "plan.md"
    plan_file.write_text("""## Task List

- [x] Task 1: Design API endpoints
- [ ] Task 2: Implement REST routes
- [ ] Task 3: Add authentication
- [ ] Task 4: Write API tests

## Success Criteria

1. All endpoints return correct status codes
2. API documentation is complete
3. Tests achieve >90% coverage
""")
    return plan_file


@pytest.fixture
def api_context_file(api_state_dir: Path) -> Path:
    """Create a mock context.md file for API tests."""
    context_file = api_state_dir / "context.md"
    context_file.write_text("""# Accumulated Context

## Session 1

Analyzed existing codebase and identified FastAPI as the best framework.

## Session 2

Implemented basic routes and health checks.

## Learnings

- FastAPI provides excellent automatic documentation
- TestClient makes testing straightforward
""")
    return context_file


@pytest.fixture
def api_progress_file(api_state_dir: Path) -> Path:
    """Create a mock progress.md file for API tests."""
    progress_file = api_state_dir / "progress.md"
    progress_file.write_text("""# Progress Update

Session: 2
Current Task: 2 of 4

## Latest Task
Implement REST routes

## Result
Successfully implemented status, plan, logs, and progress endpoints.
All endpoints tested and working correctly.
""")
    return progress_file


@pytest.fixture
def api_log_file(api_logs_dir: Path) -> Path:
    """Create a mock log file for API tests."""
    log_file = api_logs_dir / "run-20250118-120000.txt"
    log_lines = [
        "[2025-01-18 12:00:00] Task started",
        "[2025-01-18 12:00:05] Planning phase complete",
        "[2025-01-18 12:00:10] Beginning work session 1",
        "[2025-01-18 12:05:00] Work session 1 complete",
        "[2025-01-18 12:05:05] Beginning work session 2",
        "[2025-01-18 12:10:00] Work session 2 in progress",
    ]
    log_file.write_text("\n".join(log_lines))
    return log_file


@pytest.fixture
def api_criteria_file(api_state_dir: Path) -> Path:
    """Create a mock criteria.txt file for API tests."""
    criteria_file = api_state_dir / "criteria.txt"
    criteria_file.write_text("""1. All endpoints return correct status codes
2. API documentation is complete
3. Tests achieve >90% coverage
4. CORS is properly configured
5. Error handling covers edge cases
""")
    return criteria_file


# =============================================================================
# Complete API State Setup
# =============================================================================


@pytest.fixture
def api_complete_state(
    api_state_dir: Path,
    api_goal_file: Path,
    api_state_file: Path,
    api_plan_file: Path,
    api_context_file: Path,
    api_progress_file: Path,
    api_log_file: Path,
    api_criteria_file: Path,
):
    """Fixture that ensures all state files are created.

    This is a convenience fixture that depends on all the state file fixtures,
    ensuring a complete state directory is set up for API tests.

    Returns:
        The state directory path.
    """
    return api_state_dir


# =============================================================================
# API Request/Response Sample Data
# =============================================================================


@pytest.fixture
def sample_pause_request() -> dict:
    """Sample pause request payload."""
    return {"reason": "Need to review changes before continuing"}


@pytest.fixture
def sample_stop_request() -> dict:
    """Sample stop request payload."""
    return {"reason": "Critical bug detected, stopping execution"}


@pytest.fixture
def sample_config_update_request() -> dict:
    """Sample configuration update request payload."""
    return {
        "auto_merge": False,
        "max_sessions": 20,
        "pause_on_pr": True,
    }


@pytest.fixture
def sample_task_status_response() -> dict:
    """Sample task status response."""
    return {
        "status": "working",
        "goal": "Build a production-ready REST API",
        "current_task_index": 1,
        "session_count": 2,
        "current_pr": None,
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": 10,
            "pause_on_pr": False,
        },
    }
