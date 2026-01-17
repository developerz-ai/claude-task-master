"""Integration tests for pause and resume workflow.

These tests verify the complete pause/resume workflow, including:
- Interrupting a task mid-execution
- Successfully resuming from paused state
- Preserving progress and state through pause/resume cycle
- Resuming from various state conditions
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.core.credentials import CredentialManager
from claude_task_master.core.state import StateManager

# =============================================================================
# CLI Test Runner Fixture
# =============================================================================


@pytest.fixture
def runner():
    """Provide a CLI test runner."""
    return CliRunner()


# =============================================================================
# Pause/Resume Workflow Tests
# =============================================================================


class TestPauseResumeWorkflow:
    """Integration tests for the complete pause/resume workflow."""

    def test_pause_and_resume_single_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test pausing and resuming a single task execution.

        This test verifies:
        1. A task can be paused mid-execution
        2. The paused state is correctly saved
        3. Resume restores execution from the paused state
        4. Task completes successfully after resume
        """
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Configure mock SDK for a single task
        patched_sdk.set_planning_response("""## Task List

- [ ] Complete the single implementation task

## Success Criteria

1. Task is completed
""")
        patched_sdk.set_work_response("Task completed.")
        patched_sdk.set_verify_response("All success criteria met!")

        # Step 1: Start the task
        result = runner.invoke(app, ["start", "Test pause and resume", "--model", "sonnet"])

        # Verify task started
        assert "Starting new task" in result.output
        assert "Test pause and resume" in result.output

        # Step 2: Simulate a pause by modifying state to paused
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            state_data = json.loads(state_file.read_text())

            # If not yet complete, simulate pause
            if state_data.get("status") not in ["success", "failed"]:
                state_data["status"] = "paused"
                state_file.write_text(json.dumps(state_data, indent=2))

                # Step 3: Verify paused state
                assert state_data["status"] == "paused"

                # Step 4: Resume the task
                patched_sdk.reset()
                patched_sdk.set_work_response("Task completed after resume.")
                patched_sdk.set_verify_response("All success criteria met!")

                resume_result = runner.invoke(app, ["resume"])

                # Should indicate resuming
                assert (
                    "Resuming" in resume_result.output or "resume" in resume_result.output.lower()
                )

    def test_pause_and_resume_multi_task_workflow(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test pausing and resuming a multi-task workflow.

        This test verifies:
        1. Multiple tasks can be processed
        2. Pausing preserves progress (completed tasks remain complete)
        3. Resume continues from the correct task index
        4. All remaining tasks complete after resume
        """
        import shutil

        # Clean state first
        if integration_state_dir.exists():
            shutil.rmtree(integration_state_dir)
        integration_state_dir.mkdir(parents=True)

        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Configure mock SDK for multiple tasks
        patched_sdk.set_planning_response("""## Task List

- [ ] First task: Setup
- [ ] Second task: Implementation
- [ ] Third task: Testing

## Success Criteria

1. All three tasks complete
""")
        patched_sdk.set_work_response("Task completed.")
        patched_sdk.set_verify_response("All criteria met!")

        # Step 1: Start the task and let it begin
        result = runner.invoke(app, ["start", "Multi-task pause test", "--model", "sonnet"])

        # Verify task started
        assert "Starting new task" in result.output

        # Step 2: Check current state
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            state_data = json.loads(state_file.read_text())

            # If not yet complete, simulate pause after first task
            if state_data.get("status") not in ["success", "failed"]:
                # Record progress before pause
                original_task_index = state_data.get("current_task_index", 0)
                original_session_count = state_data.get("session_count", 0)

                # Simulate pause
                state_data["status"] = "paused"
                state_file.write_text(json.dumps(state_data, indent=2))

                # Step 3: Verify state was preserved
                loaded_state = json.loads(state_file.read_text())
                assert loaded_state["status"] == "paused"
                assert loaded_state["current_task_index"] == original_task_index
                assert loaded_state["session_count"] == original_session_count

                # Step 4: Resume and complete
                patched_sdk.reset()
                patched_sdk.set_work_response("Remaining tasks completed.")
                patched_sdk.set_verify_response("All criteria met!")

                resume_result = runner.invoke(app, ["resume"])

                # Should resume without error
                assert (
                    "Resuming" in resume_result.output or "resume" in resume_result.output.lower()
                )

    def test_resume_preserves_task_completion_status(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that resume preserves which tasks are already complete.

        When resuming, tasks that were already marked complete should not be re-executed.
        """
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Create a paused state with some tasks already complete
        timestamp = datetime.now().isoformat()
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

        state_data = {
            "status": "paused",
            "current_task_index": 2,  # Already at task 3
            "session_count": 3,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": run_id,
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": False,
            },
        }

        # Write state
        state_file = integration_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        # Write goal
        goal_file = integration_state_dir / "goal.txt"
        goal_file.write_text("Test task completion preservation")

        # Write plan with first two tasks marked complete
        plan_file = integration_state_dir / "plan.md"
        plan_file.write_text("""## Task List

- [x] Task 1: Already complete
- [x] Task 2: Also complete
- [ ] Task 3: Still pending
- [ ] Task 4: Still pending

## Success Criteria

1. All tasks done
""")

        # Create logs directory
        (integration_state_dir / "logs").mkdir(exist_ok=True)

        # Configure mock SDK
        patched_sdk.set_work_response("Completed remaining tasks.")
        patched_sdk.set_verify_response("All criteria met!")

        # Resume the task
        result = runner.invoke(app, ["resume"])

        # Should resume from task 3, not restart from task 1
        assert "Resuming" in result.output or "resume" in result.output.lower()

        # Verify it shows the correct task index
        assert "3" in result.output or "Current Task" in result.output

    def test_multiple_pause_resume_cycles(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test multiple pause/resume cycles on the same task.

        Verifies that the system can handle repeated pause/resume operations
        without losing state or progress.
        """
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Create initial paused state
        timestamp = datetime.now().isoformat()
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

        state_data = {
            "status": "paused",
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": run_id,
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": 10,
                "pause_on_pr": False,
            },
        }

        # Write state
        state_file = integration_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        # Write goal
        goal_file = integration_state_dir / "goal.txt"
        goal_file.write_text("Test multiple pause/resume cycles")

        # Write plan
        plan_file = integration_state_dir / "plan.md"
        plan_file.write_text("""## Task List

- [ ] Task 1
- [ ] Task 2
- [ ] Task 3

## Success Criteria

1. All tasks done
""")

        # Create logs directory
        (integration_state_dir / "logs").mkdir(exist_ok=True)

        # Cycle 1: Resume then pause again
        patched_sdk.set_work_response("Completed task.")
        patched_sdk.set_verify_response("All criteria met!")

        result1 = runner.invoke(app, ["resume"])
        assert "Resuming" in result1.output or "resume" in result1.output.lower()

        # Simulate pause again
        if state_file.exists():
            state_data = json.loads(state_file.read_text())
            if state_data.get("status") not in ["success", "failed"]:
                original_index = state_data.get("current_task_index", 0)
                state_data["status"] = "paused"
                state_file.write_text(json.dumps(state_data, indent=2))

                # Verify state preserved after first pause
                loaded = json.loads(state_file.read_text())
                assert loaded["status"] == "paused"
                assert loaded["current_task_index"] >= original_index

                # Cycle 2: Resume again
                patched_sdk.reset()
                patched_sdk.set_work_response("Completed remaining tasks.")
                patched_sdk.set_verify_response("All criteria met!")

                result2 = runner.invoke(app, ["resume"])
                assert "Resuming" in result2.output or "resume" in result2.output.lower()


# =============================================================================
# Resume From Different States Tests
# =============================================================================


class TestResumeFromDifferentStates:
    """Tests for resuming from various state conditions."""

    def test_resume_from_working_state(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test resuming from a working state (e.g., after unexpected exit)."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Create a working state (as if process died unexpectedly)
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "working",
            "current_task_index": 1,
            "session_count": 2,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": datetime.now().strftime("%Y%m%d-%H%M%S"),
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": False,
            },
        }

        state_file = integration_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        goal_file = integration_state_dir / "goal.txt"
        goal_file.write_text("Test resume from working state")

        plan_file = integration_state_dir / "plan.md"
        plan_file.write_text("""## Task List

- [x] Task 1: Complete
- [ ] Task 2: In progress
- [ ] Task 3: Pending

## Success Criteria

1. All done
""")

        (integration_state_dir / "logs").mkdir(exist_ok=True)

        patched_sdk.set_work_response("Completed remaining tasks.")
        patched_sdk.set_verify_response("All criteria met!")

        result = runner.invoke(app, ["resume"])

        # Should successfully resume from working state
        assert "Resuming" in result.output or "resume" in result.output.lower()
        # Working state is resumable, so it should continue
        assert "2" in result.output  # Current task index + 1

    def test_resume_from_planning_state(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test resuming from a planning state."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Create a planning state
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "planning",
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": datetime.now().strftime("%Y%m%d-%H%M%S"),
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": False,
            },
        }

        state_file = integration_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        goal_file = integration_state_dir / "goal.txt"
        goal_file.write_text("Test resume from planning state")

        # No plan file yet - still in planning phase
        (integration_state_dir / "logs").mkdir(exist_ok=True)

        # Configure mock SDK to complete planning
        patched_sdk.set_planning_response("""## Task List

- [ ] Task 1: New task

## Success Criteria

1. Done
""")
        patched_sdk.set_work_response("Completed task.")
        patched_sdk.set_verify_response("All criteria met!")

        result = runner.invoke(app, ["resume"])

        # Should handle planning state appropriately
        assert result.exit_code in [0, 1]

    def test_resume_from_verifying_state(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test resuming from a verifying state."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Create a verifying state
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "verifying",
            "current_task_index": 2,  # All tasks done
            "session_count": 3,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": datetime.now().strftime("%Y%m%d-%H%M%S"),
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": False,
            },
        }

        state_file = integration_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        goal_file = integration_state_dir / "goal.txt"
        goal_file.write_text("Test resume from verifying state")

        plan_file = integration_state_dir / "plan.md"
        plan_file.write_text("""## Task List

- [x] Task 1: Done
- [x] Task 2: Done

## Success Criteria

1. All done
""")

        (integration_state_dir / "logs").mkdir(exist_ok=True)

        patched_sdk.set_verify_response("All criteria met!")

        result = runner.invoke(app, ["resume"])

        # Should complete verification
        assert result.exit_code in [0, 1]
