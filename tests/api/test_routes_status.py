"""Tests for status endpoints: GET /status, GET /plan, GET /logs, GET /progress, GET /context, GET /health.

Tests the read-only info endpoints that provide information about the current task state.
"""

import json
from datetime import datetime

# =============================================================================
# GET /status Tests
# =============================================================================


def test_get_status_success(api_client, api_complete_state, api_state_file, api_goal_file):
    """Test successful status retrieval via GET /status."""
    # Update state file to include all fields
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "workflow_stage": "pr_created",
        "current_task_index": 2,
        "session_count": 3,
        "current_pr": 123,
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

    # Send status request
    response = api_client.get("/status")

    # Check response
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["goal"] == "Build a production-ready REST API"
    assert data["status"] == "working"
    assert data["model"] == "sonnet"
    assert data["current_task_index"] == 2
    assert data["session_count"] == 3
    assert data["run_id"] == "20250118-120000"
    assert data["current_pr"] == 123
    assert data["workflow_stage"] == "pr_created"
    assert data["options"]["auto_merge"] is True
    assert data["options"]["max_sessions"] == 10
    assert data["options"]["pause_on_pr"] is False
    assert data["options"]["enable_checkpointing"] is False
    assert data["options"]["log_level"] == "normal"
    assert data["options"]["log_format"] == "text"
    assert data["options"]["pr_per_task"] is False
    assert "created_at" in data
    assert "updated_at" in data


def test_get_status_with_tasks(api_client, api_complete_state, api_plan_file, api_state_file):
    """Test status endpoint includes task progress when plan exists."""
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

    response = api_client.get("/status")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["tasks"] is not None
    assert data["tasks"]["completed"] == 1
    assert data["tasks"]["total"] == 4
    assert data["tasks"]["progress"] == "1/4"


def test_get_status_no_task(api_client, temp_dir):
    """Test that status request returns 404 when no task exists."""
    # Don't create any state files
    response = api_client.get("/status")

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"
    assert "No active task found" in data["message"]
    assert "suggestion" in data


def test_get_status_different_statuses(api_client, api_complete_state, api_state_file):
    """Test status endpoint with different task statuses."""
    statuses = ["planning", "working", "paused", "stopped", "blocked"]

    for status in statuses:
        # Update state to each status
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
                "enable_checkpointing": False,
                "log_level": "normal",
                "log_format": "text",
                "pr_per_task": False,
            },
        }
        api_state_file.write_text(json.dumps(state_data))

        response = api_client.get("/status")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["status"] == status


def test_get_status_invalid_status_enum(api_client, api_complete_state, api_state_file):
    """Test status endpoint handles invalid status value gracefully."""
    # Write state with invalid status
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "invalid_status",
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

    response = api_client.get("/status")

    # Should return 500 due to invalid status enum
    assert response.status_code == 500
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "internal_error"
    # Error message should mention invalid structure or validation
    assert "invalid" in data["detail"].lower() or "validation" in data["detail"].lower()


def test_get_status_no_workflow_stage(api_client, api_complete_state, api_state_file):
    """Test status endpoint when workflow_stage is None."""
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

    response = api_client.get("/status")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["workflow_stage"] is None


def test_get_status_with_workflow_stage(api_client, api_complete_state, api_state_file):
    """Test status endpoint with various workflow stages."""
    stages = ["working", "pr_created", "waiting_ci"]

    for stage in stages:
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "working",
            "workflow_stage": stage,
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

        response = api_client.get("/status")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["workflow_stage"] == stage


def test_get_status_no_plan(api_client, api_complete_state, api_plan_file, api_state_file):
    """Test status endpoint when plan file doesn't exist."""
    # Remove plan file
    api_plan_file.unlink()

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

    response = api_client.get("/status")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    # tasks should be None when plan doesn't exist
    assert data["tasks"] is None


# =============================================================================
# GET /plan Tests
# =============================================================================


def test_get_plan_success(api_client, api_complete_state, api_plan_file):
    """Test successful plan retrieval via GET /plan."""
    response = api_client.get("/plan")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "## Task List" in data["plan"]
    assert "- [x] Task 1: Design API endpoints" in data["plan"]
    assert "- [ ] Task 2: Implement REST routes" in data["plan"]
    assert "- [ ] Task 3: Add authentication" in data["plan"]
    assert "- [ ] Task 4: Write API tests" in data["plan"]


def test_get_plan_no_task(api_client, temp_dir):
    """Test that plan request returns 404 when no task exists."""
    response = api_client.get("/plan")

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"
    assert "No active task found" in data["message"]


def test_get_plan_no_plan_file(api_client, api_complete_state, api_plan_file):
    """Test that plan request returns 404 when plan file doesn't exist."""
    # Remove plan file
    api_plan_file.unlink()

    response = api_client.get("/plan")

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"
    assert "No plan found" in data["message"]
    assert "suggestion" in data


def test_get_plan_empty_plan(api_client, api_complete_state, api_plan_file):
    """Test plan endpoint with empty plan file."""
    # Write empty plan
    api_plan_file.write_text("")

    response = api_client.get("/plan")

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"


def test_get_plan_with_unicode(api_client, api_complete_state, api_plan_file):
    """Test plan endpoint with unicode content."""
    # Write plan with unicode
    api_plan_file.write_text(
        "# Plan with Unicode\n\n- [x] Task 1: 设置中文支持\n- [ ] Task 2: Add emoji support 🎉\n- [ ] Task 3: Test with special characters ñ\n"
    )

    response = api_client.get("/plan")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "设置中文支持" in data["plan"]
    assert "🎉" in data["plan"]
    assert "ñ" in data["plan"]


def test_get_plan_large_content(api_client, api_complete_state, api_plan_file):
    """Test plan endpoint with large plan content."""
    # Create a large plan with many tasks
    lines = ["# Large Plan\n\n"]
    for i in range(1000):
        checkbox = "[x]" if i < 100 else "[ ]"
        lines.append(f"- {checkbox} Task {i + 1}: Description of task {i + 1}\n")

    api_plan_file.write_text("".join(lines))

    response = api_client.get("/plan")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["plan"]) > 0
    assert "Task 1:" in data["plan"]
    assert "Task 1000:" in data["plan"]


# =============================================================================
# GET /logs Tests
# =============================================================================


def test_get_logs_success(api_client, api_complete_state, api_log_file, api_state_file):
    """Test successful log retrieval via GET /logs."""
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

    response = api_client.get("/logs")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "log_content" in data
    assert "log_file" in data
    assert "Task started" in data["log_content"]
    assert "Planning phase complete" in data["log_content"]
    assert data["log_file"].endswith("run-20250118-120000.txt")


def test_get_logs_with_tail(api_client, api_complete_state, api_log_file, api_state_file):
    """Test logs endpoint with tail parameter."""
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

    # Request last 2 lines
    response = api_client.get("/logs?tail=2")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    lines = data["log_content"].strip().split("\n")
    assert len(lines) == 2
    # Should contain last 2 lines
    assert "session 2" in lines[0] or "session 2" in lines[1]


def test_get_logs_tail_one(api_client, api_complete_state, api_log_file, api_state_file):
    """Test logs endpoint with tail=1."""
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

    response = api_client.get("/logs?tail=1")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    lines = data["log_content"].strip().split("\n")
    assert len(lines) == 1


def test_get_logs_tail_max(api_client, api_complete_state, api_log_file, api_state_file):
    """Test logs endpoint with maximum tail value (10000)."""
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

    response = api_client.get("/logs?tail=10000")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


def test_get_logs_tail_invalid(api_client, api_complete_state, api_state_file):
    """Test logs endpoint with invalid tail parameter."""
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

    # tail=0 should fail validation
    response = api_client.get("/logs?tail=0")

    assert response.status_code == 422  # Validation error


def test_get_logs_no_task(api_client, temp_dir):
    """Test that logs request returns 404 when no task exists."""
    response = api_client.get("/logs")

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"
    assert "No active task found" in data["message"]


def test_get_logs_no_log_file(api_client, api_complete_state, api_log_file, api_state_file):
    """Test that logs request returns 404 when log file doesn't exist."""
    # Remove log file
    api_log_file.unlink()

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

    response = api_client.get("/logs")

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"
    assert "No log file found" in data["message"]


def test_get_logs_default_tail(api_client, api_complete_state, api_log_file, api_state_file):
    """Test logs endpoint uses default tail=100 when not specified."""
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

    response = api_client.get("/logs")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    # Our fixture has 6 lines, should return all with default tail=100
    assert "Task started" in data["log_content"]


def test_get_logs_with_multiline_entries(
    api_client, api_complete_state, api_log_file, api_state_file
):
    """Test logs endpoint with multiline log entries."""
    # Write log with multiline entries
    log_content = """[2025-01-18 12:00:00] Task started
[2025-01-18 12:00:05] Planning phase complete
Generated plan with 4 tasks:
- Task 1: Design API
- Task 2: Implement routes
- Task 3: Add tests
- Task 4: Documentation
[2025-01-18 12:05:00] Work session started
"""
    api_log_file.write_text(log_content)

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

    response = api_client.get("/logs")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Task 1: Design API" in data["log_content"]


# =============================================================================
# GET /progress Tests
# =============================================================================


def test_get_progress_success(api_client, api_complete_state, api_progress_file):
    """Test successful progress retrieval via GET /progress."""
    response = api_client.get("/progress")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["progress"] is not None
    assert "Progress Update" in data["progress"]
    assert "Session: 2" in data["progress"]
    assert "Current Task: 2 of 4" in data["progress"]
    assert "Implement REST routes" in data["progress"]


def test_get_progress_no_task(api_client, temp_dir):
    """Test that progress request returns 404 when no task exists."""
    response = api_client.get("/progress")

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"
    assert "No active task found" in data["message"]


def test_get_progress_no_progress_file(api_client, api_complete_state, api_progress_file):
    """Test progress endpoint when progress file doesn't exist."""
    # Remove progress file
    api_progress_file.unlink()

    response = api_client.get("/progress")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["progress"] is None
    assert "No progress recorded yet" in data["message"]


def test_get_progress_empty_file(api_client, api_complete_state, api_progress_file):
    """Test progress endpoint with empty progress file."""
    api_progress_file.write_text("")

    response = api_client.get("/progress")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["progress"] is None


def test_get_progress_with_markdown(api_client, api_complete_state, api_progress_file):
    """Test progress endpoint with markdown formatted content."""
    progress_content = """# Progress Summary

## Current Status
Working on task 3 of 5

## Completed Tasks
1. ✅ Task 1: Initial setup
2. ✅ Task 2: API design

## Current Work
### Task 3: Implementation
- Implemented GET /status
- Implemented GET /plan
- Working on GET /logs

## Next Steps
- Complete GET /logs
- Add error handling
"""
    api_progress_file.write_text(progress_content)

    response = api_client.get("/progress")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Progress Summary" in data["progress"]
    assert "Working on task 3 of 5" in data["progress"]
    assert "✅ Task 1: Initial setup" in data["progress"]


def test_get_progress_large_content(api_client, api_complete_state, api_progress_file):
    """Test progress endpoint with large progress content."""
    # Create large progress file
    lines = ["# Large Progress Report\n\n"]
    for i in range(500):
        lines.append(f"## Session {i + 1}\n\nCompleted work on task {i + 1}.\n\n")

    api_progress_file.write_text("".join(lines))

    response = api_client.get("/progress")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Session 1" in data["progress"]
    assert "Session 500" in data["progress"]


def test_get_progress_with_unicode(api_client, api_complete_state, api_progress_file):
    """Test progress endpoint with unicode content."""
    progress_content = """# 进度报告

## 当前状态
Working on API implementation

## 已完成
1. ✅ Initial setup
2. ✅ API design

## emoji support 🎉
Progress with special characters: ñ, é, 中文
"""
    api_progress_file.write_text(progress_content)

    response = api_client.get("/progress")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "进度报告" in data["progress"]
    assert "🎉" in data["progress"]
    assert "中文" in data["progress"]


# =============================================================================
# GET /context Tests
# =============================================================================


def test_get_context_success(api_client, api_complete_state, api_context_file):
    """Test successful context retrieval via GET /context."""
    response = api_client.get("/context")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["context"] is not None
    assert "Accumulated Context" in data["context"]
    assert "Session 1" in data["context"]
    assert "Session 2" in data["context"]
    assert "FastAPI provides excellent automatic documentation" in data["context"]


def test_get_context_no_task(api_client, temp_dir):
    """Test that context request returns 404 when no task exists."""
    response = api_client.get("/context")

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "not_found"
    assert "No active task found" in data["message"]


def test_get_context_no_context_file(api_client, api_complete_state, api_context_file):
    """Test context endpoint when context file doesn't exist."""
    # Remove context file
    api_context_file.unlink()

    response = api_client.get("/context")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    # Context can be None if file doesn't exist
    assert data["context"] is None


def test_get_context_empty_file(api_client, api_complete_state, api_context_file):
    """Test context endpoint with empty context file."""
    api_context_file.write_text("")

    response = api_client.get("/context")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["context"] is None


def test_get_context_with_learnings(api_client, api_complete_state, api_context_file):
    """Test context endpoint with learnings section."""
    context_content = """# Context

## Sessions
Session 1: Initial planning

## Learnings
- Key insight 1
- Key insight 2

## Decisions
- Decision 1
"""
    api_context_file.write_text(context_content)

    response = api_client.get("/context")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Learnings" in data["context"]
    assert "Key insight 1" in data["context"]


# =============================================================================
# GET /health Tests
# =============================================================================


def test_get_healthy_status(api_client, api_complete_state, api_state_file):
    """Test health endpoint returns healthy status for working task."""
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

    response = api_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["server_name"] == "claude-task-master-api"
    assert "version" in data
    assert "uptime_seconds" in data
    assert "active_tasks" in data


def test_get_health_degraded_status(api_client, api_complete_state, api_state_file):
    """Test health endpoint returns degraded status for blocked task."""
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
            "enable_checkpointing": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    api_state_file.write_text(json.dumps(state_data))

    response = api_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"


def test_get_health_no_task(api_client, temp_dir):
    """Test health endpoint returns healthy when no task exists."""
    response = api_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["active_tasks"] == 0


def test_get_health_failed_status(api_client, api_complete_state, api_state_file):
    """Test health endpoint returns degraded status for failed task."""
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "failed",
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

    response = api_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"


def test_get_health_with_uptime(api_client, api_complete_state):
    """Test health endpoint includes uptime."""
    response = api_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert "uptime_seconds" in data
    # Should be a positive number
    assert data["uptime_seconds"] >= 0


def test_get_health_includes_version(api_client, api_complete_state):
    """Test health endpoint includes version information."""
    response = api_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    # Version should be a string
    assert isinstance(data["version"], str)
    assert len(data["version"]) > 0


# =============================================================================
# Integration Tests
# =============================================================================


def test_all_info_endpoints_together(api_client, api_complete_state, api_state_file):
    """Test that all info endpoints work together."""
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "workflow_stage": "working",
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

    # Test all endpoints
    status_response = api_client.get("/status")
    plan_response = api_client.get("/plan")
    logs_response = api_client.get("/logs")
    progress_response = api_client.get("/progress")
    context_response = api_client.get("/context")
    health_response = api_client.get("/health")

    # All should succeed
    assert status_response.status_code == 200
    assert plan_response.status_code == 200
    assert logs_response.status_code == 200
    assert progress_response.status_code == 200
    assert context_response.status_code == 200
    assert health_response.status_code == 200

    # Verify data consistency
    status_data = status_response.json()
    health_data = health_response.json()

    assert status_data["status"] == "working"
    assert health_data["status"] == "healthy"


def test_status_and_plan_consistency(api_client, api_complete_state, api_plan_file, api_state_file):
    """Test that status task count matches plan checkboxes."""
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

    # Get status which includes task count
    status_response = api_client.get("/status")
    status_data = status_response.json()

    # Get plan directly
    plan_response = api_client.get("/plan")
    plan_content = plan_response.json()["plan"]

    # Count checkboxes in plan
    completed = plan_content.count("- [x]")
    total = plan_content.count("- [x]") + plan_content.count("- [ ]")

    # Verify status matches plan
    assert status_data["tasks"]["completed"] == completed
    assert status_data["tasks"]["total"] == total
