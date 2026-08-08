"""Tests for PATCH /config endpoint.

Tests the configuration update endpoint that allows runtime modification
of task options.
"""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from claude_task_master.api.models import ConfigUpdateRequest, LogFormat, LogLevel

# =============================================================================
# PATCH /config Tests
# =============================================================================


def test_patch_config_success(api_client, api_complete_state, api_state_file, api_state_dir):
    """Test successful configuration update via PATCH /config."""
    # Update the state file to include all option fields
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "workflow_stage": None,
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
            "enable_checkpointing": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    # Send config update request
    response = api_client.patch(
        "/config",
        json={
            "auto_merge": False,
            "max_sessions": 20,
            "pause_on_pr": True,
        },
    )

    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["operation"] == "update_config"
    assert "auto_merge" in data["message"]
    assert "max_sessions" in data["message"]
    assert data["previous_status"] == "working"
    assert data["new_status"] == "working"
    assert data["details"]["updated"]["auto_merge"] is False
    assert data["details"]["updated"]["max_sessions"] == 20
    assert data["details"]["updated"]["pause_on_pr"] is True

    # Verify state was persisted
    updated_state = json.loads(api_state_file.read_text())
    assert updated_state["options"]["auto_merge"] is False
    assert updated_state["options"]["max_sessions"] == 20
    assert updated_state["options"]["pause_on_pr"] is True
    # Other options should remain unchanged
    assert updated_state["options"]["enable_checkpointing"] is False
    assert updated_state["options"]["log_level"] == "normal"


def test_patch_config_single_field(api_client, api_complete_state, api_state_file):
    """Test updating a single configuration field."""
    # Update state file to include all option fields
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "workflow_stage": None,
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
            "enable_checkpointing": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    # Update only log_level
    response = api_client.patch("/config", json={"log_level": "verbose"})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["details"]["updated"]["log_level"] == "verbose"

    # Verify only log_level changed
    updated_state = json.loads(api_state_file.read_text())
    assert updated_state["options"]["log_level"] == "verbose"
    assert updated_state["options"]["auto_merge"] is True  # Unchanged
    assert updated_state["options"]["max_sessions"] == 10  # Unchanged


def test_patch_config_no_updates(api_client, api_complete_state):
    """Test that empty config update request returns 400 error."""
    response = api_client.patch("/config", json={})

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "invalid_request"
    assert "No configuration updates provided" in data["message"]


def test_patch_config_no_task(api_client, temp_dir):
    """Test that config update returns 404 when no task exists."""
    # Don't create any state files
    response = api_client.patch("/config", json={"auto_merge": False})

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"
    assert "No active task found" in data["message"]


def test_patch_config_with_enum_values(api_client, api_complete_state, api_state_file):
    """Test config update with enum values (log_level, log_format)."""
    # Update state file to include all option fields
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "workflow_stage": None,
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
            "enable_checkpointing": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.patch("/config", json={"log_level": "quiet", "log_format": "json"})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["details"]["updated"]["log_level"] == "quiet"
    assert data["details"]["updated"]["log_format"] == "json"

    # Verify state was persisted with enum string values
    updated_state = json.loads(api_state_file.read_text())
    assert updated_state["options"]["log_level"] == "quiet"
    assert updated_state["options"]["log_format"] == "json"


def test_patch_config_invalid_max_sessions(api_client, api_complete_state, api_state_file):
    """Test that invalid max_sessions value is rejected."""
    # Update state file to include all option fields
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "workflow_stage": None,
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
            "enable_checkpointing": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    # Test with max_sessions below minimum
    response = api_client.patch("/config", json={"max_sessions": 0})

    # Should fail validation (max_sessions must be >= 1)
    assert response.status_code == 422  # Validation error


def test_patch_config_all_fields(api_client, api_complete_state, api_state_file):
    """Test updating all configuration fields at once."""
    # Update state file to include all option fields
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "workflow_stage": None,
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
            "enable_checkpointing": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.patch(
        "/config",
        json={
            "auto_merge": False,
            "max_sessions": 50,
            "pause_on_pr": True,
            "enable_checkpointing": True,
            "log_level": "verbose",
            "log_format": "json",
            "pr_per_task": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["details"]["updated"]) == 7  # All fields updated

    # Verify all fields were updated
    updated_state = json.loads(api_state_file.read_text())
    assert updated_state["options"]["auto_merge"] is False
    assert updated_state["options"]["max_sessions"] == 50
    assert updated_state["options"]["pause_on_pr"] is True
    assert updated_state["options"]["enable_checkpointing"] is True
    assert updated_state["options"]["log_level"] == "verbose"
    assert updated_state["options"]["log_format"] == "json"
    assert updated_state["options"]["pr_per_task"] is True


def test_patch_config_none_values(api_client, api_complete_state, api_state_file):
    """Test that None values in request are ignored (not treated as updates)."""
    # Update state file to include all option fields
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "workflow_stage": None,
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
            "enable_checkpointing": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    # Send request with only None values (should be rejected)
    response = api_client.patch(
        "/config",
        json={"auto_merge": None, "max_sessions": None},
    )

    # Should return 400 because no actual updates were provided
    assert response.status_code == 400


# =============================================================================
# ConfigUpdateRequest Model Tests
# =============================================================================


def test_config_update_request_has_updates():
    """Test ConfigUpdateRequest.has_updates() method."""
    # Request with updates
    request = ConfigUpdateRequest(auto_merge=False, max_sessions=20)
    assert request.has_updates() is True

    # Request with all None fields
    request = ConfigUpdateRequest()
    assert request.has_updates() is False

    # Request with one field
    request = ConfigUpdateRequest(log_level=LogLevel.VERBOSE)
    assert request.has_updates() is True


def test_config_update_request_to_update_dict():
    """Test ConfigUpdateRequest.to_update_dict() method."""
    request = ConfigUpdateRequest(
        auto_merge=False,
        max_sessions=20,
        log_level=LogLevel.VERBOSE,
        log_format=LogFormat.JSON,
    )

    update_dict = request.to_update_dict()

    assert update_dict == {
        "auto_merge": False,
        "max_sessions": 20,
        "log_level": "verbose",  # Enum converted to string
        "log_format": "json",  # Enum converted to string
    }

    # Test with all None values
    request = ConfigUpdateRequest()
    update_dict = request.to_update_dict()
    assert update_dict == {}


def test_config_update_request_validation():
    """Test ConfigUpdateRequest field validation."""
    # Valid request
    request = ConfigUpdateRequest(
        auto_merge=False,
        max_sessions=100,
        pause_on_pr=True,
    )
    assert request.auto_merge is False
    assert request.max_sessions == 100
    assert request.pause_on_pr is True

    # Invalid max_sessions (too low)
    with pytest.raises(ValidationError):  # Pydantic validation error
        ConfigUpdateRequest(max_sessions=0)

    # Invalid max_sessions (too high)
    with pytest.raises(ValidationError):  # Pydantic validation error
        ConfigUpdateRequest(max_sessions=10000)


def test_patch_config_rejects_removed_parallel_tasks(api_client, api_complete_state):
    """The removed `parallel_tasks` name 422s instead of being silently dropped.

    `--parallel-tasks` became `--parallel` and the default flipped False -> True.
    Pydantic ignores unknown keys, so a client still sending `parallel_tasks:
    false` would otherwise get a 200 and the opposite of what it asked for.
    """
    response = api_client.patch("/config", json={"parallel_tasks": False})

    assert response.status_code == 422
    assert "parallel" in response.text


def test_config_update_request_rejects_removed_parallel_tasks():
    """The model itself raises, not just the route."""
    with pytest.raises(ValidationError, match="parallel_tasks"):
        ConfigUpdateRequest.model_validate({"parallel_tasks": False})


def test_config_update_request_still_ignores_other_unknown_fields():
    """Only *removed* names are rejected; pydantic's default stands otherwise."""
    request = ConfigUpdateRequest.model_validate({"auto_merge": False, "unrelated_key": 1})

    assert request.auto_merge is False
    assert request.to_update_dict() == {"auto_merge": False}
