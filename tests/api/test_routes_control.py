"""Tests for control endpoints: POST /control/stop, POST /control/resume, PATCH /config.

Tests the runtime control endpoints that allow stopping, resuming tasks,
and updating configuration during task execution.
"""

import json
from datetime import datetime

from claude_task_master.api.models import StopRequest

# =============================================================================
# POST /control/stop Tests
# =============================================================================


def test_post_control_stop_success(api_client, api_complete_state, api_state_file):
    """Test successful task stop via POST /control/stop."""
    # Update state to working status
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    # Send stop request
    response = api_client.post(
        "/control/stop",
        json={"reason": "User requested stop", "cleanup": False},
    )

    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["operation"] == "stop"
    assert "stopped successfully" in data["message"]
    assert data["previous_status"] == "working"
    assert data["new_status"] == "stopped"
    assert data["details"]["reason"] == "User requested stop"
    assert data["details"]["cleanup"] is False

    # Verify state was persisted
    updated_state = json.loads(api_state_file.read_text())
    assert updated_state["status"] == "stopped"


def test_post_control_stop_with_cleanup(
    api_client, api_complete_state, api_state_file, api_state_dir
):
    """Test task stop with cleanup enabled."""
    # Update state to working status
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    # Create logs directory
    logs_dir = api_state_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Send stop request with cleanup
    response = api_client.post(
        "/control/stop",
        json={"reason": "Task completed", "cleanup": True},
    )

    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["details"]["cleanup"] is True

    # Note: cleanup removes state files, so we can't check the file afterward
    # Just verify the response was successful


def test_post_control_stop_from_planning(api_client, api_complete_state, api_state_file):
    """Test stopping a task from planning status."""
    # Update state to planning status
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "planning",
        "workflow_stage": None,  # planning status has no workflow_stage
        "current_task_index": 0,
        "session_count": 0,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "20250118-120000",
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": 10,
            "pause_on_pr": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.post("/control/stop", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["previous_status"] == "planning"
    assert data["new_status"] == "stopped"


def test_post_control_stop_from_blocked(api_client, api_complete_state, api_state_file):
    """Test stopping a task from blocked status."""
    # Update state to blocked status
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "blocked",
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.post("/control/stop", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["previous_status"] == "blocked"
    assert data["new_status"] == "stopped"


def test_post_control_stop_from_paused(api_client, api_complete_state, api_state_file):
    """Test stopping a task from paused status."""
    # Update state to paused status
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "paused",
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.post("/control/stop", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["previous_status"] == "paused"
    assert data["new_status"] == "stopped"


def test_post_control_stop_no_task(api_client, temp_dir):
    """Test that stop request returns 404 when no task exists."""
    # Don't create any state files
    response = api_client.post("/control/stop", json={})

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"
    assert "No active task found" in data["message"]


def test_post_control_stop_from_success(api_client, api_complete_state, api_state_file):
    """Test that stopping from success status returns 400."""
    # Update state to success status
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "success",
        "workflow_stage": None,
        "current_task_index": 5,
        "session_count": 5,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "20250118-120000",
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": 10,
            "pause_on_pr": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.post("/control/stop", json={})

    # Should return 400 because completed tasks can't be stopped
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "invalid_operation"
    assert "Cannot stop task" in data["message"]


def test_post_control_stop_from_failed(api_client, api_complete_state, api_state_file):
    """Test that stopping from failed status returns 400."""
    # Update state to failed status
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "failed",
        "workflow_stage": None,
        "current_task_index": 2,
        "session_count": 3,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "20250118-120000",
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": 10,
            "pause_on_pr": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.post("/control/stop", json={})

    # Should return 400 because failed tasks can't be stopped
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "invalid_operation"
    assert "Cannot stop task" in data["message"]


def test_post_control_stop_optional_fields(api_client, api_complete_state, api_state_file):
    """Test stop request with optional fields omitted."""
    # Update state to working status
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    # Send stop request with empty body (all fields optional)
    response = api_client.post("/control/stop", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["details"]["reason"] is None
    assert data["details"]["cleanup"] is False


# =============================================================================
# POST /control/resume Tests
# =============================================================================


def test_post_control_resume_from_paused(api_client, api_complete_state, api_state_file):
    """Test successful resume from paused status."""
    # Update state to paused status
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "paused",
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.post("/control/resume", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["operation"] == "resume"
    assert "resumed successfully" in data["message"]
    assert data["previous_status"] == "paused"
    assert data["new_status"] == "working"

    # Verify state was persisted
    updated_state = json.loads(api_state_file.read_text())
    assert updated_state["status"] == "working"


def test_post_control_resume_from_blocked(api_client, api_complete_state, api_state_file):
    """Test successful resume from blocked status."""
    # Update state to blocked status
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "blocked",
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.post("/control/resume", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["previous_status"] == "blocked"
    assert data["new_status"] == "working"


def test_post_control_resume_from_stopped(api_client, api_complete_state, api_state_file):
    """Test successful resume from stopped status."""
    # Update state to stopped status
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "stopped",
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.post("/control/resume", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["previous_status"] == "stopped"
    assert data["new_status"] == "working"


def test_post_control_resume_from_working(api_client, api_complete_state, api_state_file):
    """Test that resuming from working status is idempotent."""
    # Update state to working status
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.post("/control/resume", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["previous_status"] == "working"
    assert data["new_status"] == "working"


def test_post_control_resume_no_task(api_client, temp_dir):
    """Test that resume request returns 404 when no task exists."""
    # Don't create any state files
    response = api_client.post("/control/resume", json={})

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"
    assert "No active task found" in data["message"]


def test_post_control_resume_from_success(api_client, api_complete_state, api_state_file):
    """Test that resuming from success status returns 400."""
    # Update state to success status
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "success",
        "workflow_stage": None,
        "current_task_index": 5,
        "session_count": 5,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "20250118-120000",
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": 10,
            "pause_on_pr": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.post("/control/resume", json={})

    # Should return 400 because completed tasks can't be resumed
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "invalid_operation"
    assert "Cannot resume task" in data["message"]


def test_post_control_resume_from_failed(api_client, api_complete_state, api_state_file):
    """Test that resuming from failed status returns 400."""
    # Update state to failed status
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "failed",
        "workflow_stage": None,
        "current_task_index": 2,
        "session_count": 3,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "20250118-120000",
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": 10,
            "pause_on_pr": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.post("/control/resume", json={})

    # Should return 400 because failed tasks can't be resumed
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "invalid_operation"
    assert "Cannot resume task" in data["message"]


# =============================================================================
# PATCH /config Tests (additional coverage)
# =============================================================================


def test_patch_config_after_stop(api_client, api_complete_state, api_state_file):
    """Test that config can be updated after stopping a task."""
    # First stop the task
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    # Stop the task
    stop_response = api_client.post("/control/stop", json={})
    assert stop_response.status_code == 200

    # Update config after stop
    config_response = api_client.patch("/config", json={"max_sessions": 20})

    assert config_response.status_code == 200
    data = config_response.json()
    assert data["success"] is True
    assert data["details"]["updated"]["max_sessions"] == 20

    # Verify config was updated
    updated_state = json.loads(api_state_file.read_text())
    assert updated_state["status"] == "stopped"
    assert updated_state["options"]["max_sessions"] == 20


def test_patch_config_after_resume(api_client, api_complete_state, api_state_file):
    """Test that config can be updated after resuming a task."""
    # First pause the task
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "paused",
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    # Resume the task
    resume_response = api_client.post("/control/resume", json={})
    assert resume_response.status_code == 200

    # Update config after resume
    config_response = api_client.patch("/config", json={"auto_merge": False})

    assert config_response.status_code == 200
    data = config_response.json()
    assert data["success"] is True
    assert data["details"]["updated"]["auto_merge"] is False

    # Verify config was updated
    updated_state = json.loads(api_state_file.read_text())
    assert updated_state["status"] == "working"
    assert updated_state["options"]["auto_merge"] is False


# =============================================================================
# Integration Tests
# =============================================================================


def test_stop_and_resume_workflow(api_client, api_complete_state, api_state_file):
    """Test complete workflow: stop, then resume."""
    # Start with working status
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    # Stop the task
    stop_response = api_client.post("/control/stop", json={"reason": "Manual stop"})
    assert stop_response.status_code == 200
    stop_data = stop_response.json()
    assert stop_data["previous_status"] == "working"
    assert stop_data["new_status"] == "stopped"

    # Verify state
    state = json.loads(api_state_file.read_text())
    assert state["status"] == "stopped"

    # Resume the task
    resume_response = api_client.post("/control/resume", json={})
    assert resume_response.status_code == 200
    resume_data = resume_response.json()
    assert resume_data["previous_status"] == "stopped"
    assert resume_data["new_status"] == "working"

    # Verify final state
    final_state = json.loads(api_state_file.read_text())
    assert final_state["status"] == "working"


def test_pause_stop_resume_workflow(api_client, api_complete_state, api_state_file):
    """Test workflow: pause, stop, resume (stop overrides pause)."""
    # Start with working status
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
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    # Pause the task
    # Note: We can't test pause endpoint here as it's not implemented yet
    # So we'll manually set the status to paused
    state_data["status"] = "paused"
    api_state_file.write_text(json.dumps(state_data))

    # Stop from paused
    stop_response = api_client.post("/control/stop", json={})
    assert stop_response.status_code == 200
    stop_data = stop_response.json()
    assert stop_data["previous_status"] == "paused"
    assert stop_data["new_status"] == "stopped"

    # Resume from stopped
    resume_response = api_client.post("/control/resume", json={})
    assert resume_response.status_code == 200
    resume_data = resume_response.json()
    assert resume_data["previous_status"] == "stopped"
    assert resume_data["new_status"] == "working"

    # Verify final state
    final_state = json.loads(api_state_file.read_text())
    assert final_state["status"] == "working"


def test_config_update_preserves_status(api_client, api_complete_state, api_state_file):
    """Test that config updates don't change task status."""
    # Test with different statuses
    for status in ["working", "paused", "stopped", "blocked"]:
        # Set status
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": status,
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
                "log_level": "normal",
                "log_format": "text",
                "pr_per_task": False,
            },
        }
        api_state_file.write_text(json.dumps(state_data))

        # Update config
        response = api_client.patch("/config", json={"max_sessions": 15})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["previous_status"] == status
        assert data["new_status"] == status

        # Verify status unchanged
        updated_state = json.loads(api_state_file.read_text())
        assert updated_state["status"] == status
        assert updated_state["options"]["max_sessions"] == 15


# =============================================================================
# Model Validation Tests
# =============================================================================


def test_stop_request_model_validation():
    """Test StopRequest model validation."""
    # Valid request with all fields
    request = StopRequest(reason="Test reason", cleanup=True)
    assert request.reason == "Test reason"
    assert request.cleanup is True

    # Valid request with minimal fields
    request = StopRequest()
    assert request.reason is None
    assert request.cleanup is False

    # Valid request with only reason
    request = StopRequest(reason="Only reason")
    assert request.reason == "Only reason"
    assert request.cleanup is False

    # Valid request with only cleanup
    request = StopRequest(cleanup=True)
    assert request.reason is None
    assert request.cleanup is True
