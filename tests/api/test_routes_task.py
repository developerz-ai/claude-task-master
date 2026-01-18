"""Tests for task management endpoints POST /task/init and DELETE /task.

Tests the task lifecycle endpoints that allow initializing new tasks
and deleting existing tasks.
"""

import json

import pytest
from pydantic import ValidationError

from claude_task_master.api.models import TaskInitRequest

# =============================================================================
# POST /task/init Tests
# =============================================================================


def test_post_task_init_success(api_client_empty_state, api_empty_state_dir):
    """Test successful task initialization via POST /task/init."""
    # Ensure state directory doesn't exist
    assert not api_empty_state_dir.exists()

    # Send task init request
    response = api_client_empty_state.post(
        "/task/init",
        json={
            "goal": "Add user authentication",
            "model": "opus",
            "auto_merge": True,
            "max_sessions": 10,
            "pause_on_pr": False,
        },
    )

    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Task initialized successfully"
    assert "run_id" in data
    assert data["status"] == "planning"

    # Verify state was created
    state_file = api_empty_state_dir / "state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["model"] == "opus"
    assert state["status"] == "planning"
    assert state["options"]["auto_merge"] is True
    assert state["options"]["max_sessions"] == 10
    assert state["options"]["pause_on_pr"] is False

    # Verify goal was saved separately
    goal_file = api_empty_state_dir / "goal.txt"
    assert goal_file.exists()
    assert goal_file.read_text() == "Add user authentication"


def test_post_task_init_default_options(api_client_empty_state, api_empty_state_dir):
    """Test task initialization with default options."""
    assert not api_empty_state_dir.exists()

    response = api_client_empty_state.post(
        "/task/init",
        json={
            "goal": "Test task",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    # Verify defaults
    state_file = api_empty_state_dir / "state.json"
    state = json.loads(state_file.read_text())
    assert state["model"] == "opus"  # Default model
    assert state["options"]["auto_merge"] is True  # Default
    assert state["options"]["max_sessions"] is None  # Default (unlimited)
    assert state["options"]["pause_on_pr"] is False  # Default


def test_post_task_init_invalid_model(api_client_empty_state, api_empty_state_dir):
    """Test task initialization with invalid model."""
    assert not api_empty_state_dir.exists()

    response = api_client_empty_state.post(
        "/task/init",
        json={
            "goal": "Test task",
            "model": "invalid_model",
        },
    )

    # FastAPI returns 422 for validation errors
    assert response.status_code == 422


def test_post_task_init_already_exists(api_client, api_complete_state):
    """Test task initialization when task already exists."""
    response = api_client.post(
        "/task/init",
        json={
            "goal": "New task",
        },
    )

    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "task_exists"
    assert "already exists" in data["message"]
    assert "DELETE /task" in data["suggestion"]


def test_post_task_init_sonnet_model(api_client_empty_state, api_empty_state_dir):
    """Test task initialization with sonnet model."""
    assert not api_empty_state_dir.exists()

    response = api_client_empty_state.post(
        "/task/init",
        json={
            "goal": "Test with sonnet",
            "model": "sonnet",
        },
    )

    assert response.status_code == 200
    state_file = api_empty_state_dir / "state.json"
    state = json.loads(state_file.read_text())
    assert state["model"] == "sonnet"


def test_post_task_init_haiku_model(api_client_empty_state, api_empty_state_dir):
    """Test task initialization with haiku model."""
    assert not api_empty_state_dir.exists()

    response = api_client_empty_state.post(
        "/task/init",
        json={
            "goal": "Test with haiku",
            "model": "haiku",
        },
    )

    assert response.status_code == 200
    state_file = api_empty_state_dir / "state.json"
    state = json.loads(state_file.read_text())
    assert state["model"] == "haiku"


def test_post_task_init_with_pause_on_pr(api_client_empty_state, api_empty_state_dir):
    """Test task initialization with pause_on_pr enabled."""
    assert not api_empty_state_dir.exists()

    response = api_client_empty_state.post(
        "/task/init",
        json={
            "goal": "Test task",
            "pause_on_pr": True,
        },
    )

    assert response.status_code == 200
    state_file = api_empty_state_dir / "state.json"
    state = json.loads(state_file.read_text())
    assert state["options"]["pause_on_pr"] is True


# =============================================================================
# DELETE /task Tests
# =============================================================================


def test_delete_task_success(api_client, api_complete_state, api_state_dir):
    """Test successful task deletion via DELETE /task."""
    # Verify state exists
    assert api_state_dir.exists()

    # Send delete request
    response = api_client.delete("/task")

    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Task deleted successfully"
    assert data["files_removed"] is True

    # Verify state directory was removed
    assert not api_state_dir.exists()


def test_delete_task_no_task(api_client_empty_state, api_empty_state_dir):
    """Test task deletion when no task exists."""
    # Ensure state doesn't exist
    assert not api_empty_state_dir.exists()

    response = api_client_empty_state.delete("/task")

    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "not_found"
    assert "No active task found" in data["message"]


def test_delete_task_removes_all_files(api_client, api_complete_state, api_state_dir):
    """Test that task deletion removes all state files."""
    # Create additional state files
    (api_state_dir / "plan.md").write_text("# Plan\n- [ ] Task 1")
    (api_state_dir / "progress.md").write_text("# Progress")
    (api_state_dir / "context.md").write_text("# Context")

    # Verify files exist
    assert (api_state_dir / "state.json").exists()
    assert (api_state_dir / "plan.md").exists()
    assert (api_state_dir / "progress.md").exists()
    assert (api_state_dir / "context.md").exists()

    # Delete task
    response = api_client.delete("/task")
    assert response.status_code == 200

    # Verify entire directory was removed
    assert not api_state_dir.exists()


def test_delete_then_init(api_client, api_complete_state, api_state_dir):
    """Test deleting a task and then initializing a new one."""
    # Verify initial state exists
    assert api_state_dir.exists()

    # Delete task
    delete_response = api_client.delete("/task")
    assert delete_response.status_code == 200
    assert not api_state_dir.exists()

    # Initialize new task (using regular client since dir doesn't exist anymore)
    init_response = api_client.post(
        "/task/init",
        json={
            "goal": "New task after deletion",
        },
    )
    assert init_response.status_code == 200

    # Verify new state was created
    state_file = api_state_dir / "state.json"
    state = json.loads(state_file.read_text())
    assert state["status"] == "planning"

    # Verify goal was saved
    goal_file = api_state_dir / "goal.txt"
    assert goal_file.read_text() == "New task after deletion"


# =============================================================================
# Model Validation Tests
# =============================================================================


def test_task_init_request_model_validation():
    """Test TaskInitRequest model validation."""
    # Valid request
    request = TaskInitRequest(
        goal="Test goal",
        model="opus",
        auto_merge=True,
        max_sessions=10,
        pause_on_pr=False,
    )
    assert request.goal == "Test goal"
    assert request.model == "opus"
    assert request.auto_merge is True

    # Missing required field
    with pytest.raises(ValidationError):
        TaskInitRequest(model="opus")

    # Invalid model
    with pytest.raises(ValidationError):
        TaskInitRequest(goal="Test", model="invalid")

    # Invalid max_sessions (too low)
    with pytest.raises(ValidationError):
        TaskInitRequest(goal="Test", max_sessions=0)

    # Invalid max_sessions (too high)
    with pytest.raises(ValidationError):
        TaskInitRequest(goal="Test", max_sessions=1001)

    # Valid max_sessions boundaries
    request1 = TaskInitRequest(goal="Test", max_sessions=1)
    assert request1.max_sessions == 1
    request2 = TaskInitRequest(goal="Test", max_sessions=1000)
    assert request2.max_sessions == 1000
