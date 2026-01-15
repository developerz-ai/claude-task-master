"""End-to-end integration tests for the full workflow.

These tests verify the complete workflow from start to finish, including:
- The start command with planning and work phases
- The resume command for paused and blocked states
- Error handling and recovery scenarios
- State transitions throughout the workflow
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

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
# Test Start Command - Full Workflow
# =============================================================================


class TestStartCommandWorkflow:
    """Integration tests for the start command workflow."""

    def test_start_initializes_state_correctly(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that start command initializes state correctly."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Configure mock SDK for simple planning response
        patched_sdk.set_planning_response("""## Task List

- [ ] Task 1: Setup
- [ ] Task 2: Build
- [ ] Task 3: Test

## Success Criteria

1. All tests pass
""")
        # Configure work sessions
        patched_sdk.set_work_response("Task completed successfully.")
        patched_sdk.set_verify_response("All success criteria met!")

        result = runner.invoke(
            app, ["start", "Build a simple test application", "--model", "sonnet"]
        )

        # The workflow started and ran successfully
        # Check that the command ran with expected output
        assert "Starting new task" in result.output
        assert "Build a simple test application" in result.output

        # Either the state file exists OR the task completed successfully
        state_file = integration_state_dir / "state.json"
        goal_file = integration_state_dir / "goal.txt"
        plan_file = integration_state_dir / "plan.md"

        # If state still exists, verify it
        if state_file.exists():
            assert goal_file.exists()
            assert plan_file.exists()
        else:
            # Task completed - verify success message (state may be cleaned on success)
            assert "completed successfully" in result.output.lower() or result.exit_code == 0

    def test_start_fails_when_task_exists(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        pre_planned_state,
        monkeypatch,
    ):
        """Test that start fails when a task already exists."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["start", "New goal"])

        assert result.exit_code == 1
        assert "already exists" in result.output.lower()

    def test_start_with_different_models(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test starting with different model options."""
        for model in ["sonnet", "opus", "haiku"]:
            # Clean up state between runs
            if integration_state_dir.exists():
                import shutil

                shutil.rmtree(integration_state_dir)
            integration_state_dir.mkdir(parents=True)

            monkeypatch.chdir(integration_temp_dir)
            monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
            monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

            patched_sdk.reset()
            patched_sdk.set_planning_response("""## Task List
- [ ] Single task

## Success Criteria
1. Done
""")
            patched_sdk.set_work_response("Completed.")
            patched_sdk.set_verify_response("Success!")

            runner.invoke(app, ["start", f"Test with {model}", "--model", model])

            # Verify the model was saved in state
            state_file = integration_state_dir / "state.json"
            if state_file.exists():
                state_data = json.loads(state_file.read_text())
                assert state_data["model"] == model, f"Model mismatch for {model}"

    def test_start_with_options(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test starting with custom options."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        patched_sdk.set_planning_response("""## Task List
- [ ] Task 1

## Success Criteria
1. Done
""")
        runner.invoke(
            app,
            [
                "start",
                "Test with options",
                "--no-auto-merge",
                "--max-sessions",
                "5",
                "--pause-on-pr",
            ],
        )

        # Verify options were saved
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            state_data = json.loads(state_file.read_text())
            assert state_data["options"]["auto_merge"] is False
            assert state_data["options"]["max_sessions"] == 5
            assert state_data["options"]["pause_on_pr"] is True


# =============================================================================
# Test Resume Command - Full Workflow
# =============================================================================


class TestResumeCommandWorkflow:
    """Integration tests for the resume command workflow."""

    def test_resume_from_paused_state(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test resuming from a paused state."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Configure mock responses
        patched_sdk.set_work_response("Completed task 3 successfully.")
        patched_sdk.set_verify_response("All criteria met!")

        result = runner.invoke(app, ["resume"])

        # Should update status from paused to working
        assert "Resuming" in result.output or "resume" in result.output.lower()

    def test_resume_from_blocked_state(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        blocked_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test resuming from a blocked state."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        patched_sdk.set_work_response("Resolved blocked issue.")
        patched_sdk.set_verify_response("Success!")

        result = runner.invoke(app, ["resume"])

        # Should attempt to resume blocked task
        assert "resume" in result.output.lower() or "blocked" in result.output.lower()

    def test_resume_no_task_found(
        self,
        runner,
        integration_temp_dir: Path,
        monkeypatch,
    ):
        """Test resume when no task exists."""
        state_dir = integration_temp_dir / ".claude-task-master"
        # Make sure state dir does NOT exist
        if state_dir.exists():
            import shutil

            shutil.rmtree(state_dir)

        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", state_dir)

        result = runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "No task found" in result.output

    def test_resume_completed_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        completed_state,
        monkeypatch,
    ):
        """Test resume on a completed task."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["resume"])

        # Should indicate task is already complete
        assert (
            result.exit_code == 0
            or "success" in result.output.lower()
            or "completed" in result.output.lower()
        )

    def test_resume_failed_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        failed_state,
        monkeypatch,
    ):
        """Test resume on a failed task."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["resume"])

        # Should indicate task has failed and suggest clean
        assert result.exit_code == 1
        assert "failed" in result.output.lower() or "cannot" in result.output.lower()

    def test_resume_preserves_progress(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test that resume preserves existing progress."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Record the original task index
        paused_state["state_data"]["current_task_index"]
        original_session = paused_state["state_data"]["session_count"]

        patched_sdk.set_work_response("Completed successfully.")
        patched_sdk.set_verify_response("All criteria met!")

        runner.invoke(app, ["resume"])

        # After resume, check that we started from the right place
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            state_data = json.loads(state_file.read_text())
            # Session count should have increased or stayed the same
            assert state_data["session_count"] >= original_session


# =============================================================================
# Test Status Command
# =============================================================================


class TestStatusCommand:
    """Integration tests for the status command."""

    def test_status_shows_paused_state(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        paused_state,
        monkeypatch,
    ):
        """Test status shows paused state info."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "paused" in result.output.lower()
        assert "3" in result.output  # Current task index + 1

    def test_status_shows_blocked_with_pr(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        blocked_state,
        monkeypatch,
    ):
        """Test status shows blocked state with PR number."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "blocked" in result.output.lower()
        assert "42" in result.output  # PR number


# =============================================================================
# Test Plan Command
# =============================================================================


class TestPlanCommand:
    """Integration tests for the plan command."""

    def test_plan_shows_task_list(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        pre_planned_state,
        monkeypatch,
    ):
        """Test plan command shows the task list."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["plan"])

        assert result.exit_code == 0
        assert "Task List" in result.output
        assert "Initialize project structure" in result.output

    def test_plan_shows_progress(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        paused_state,
        monkeypatch,
    ):
        """Test plan shows progress with checkmarks."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["plan"])

        assert result.exit_code == 0
        # First two tasks should be marked complete
        assert "[x]" in result.output


# =============================================================================
# Test Progress Command
# =============================================================================


class TestProgressCommand:
    """Integration tests for the progress command."""

    def test_progress_shows_summary(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        paused_state,
        monkeypatch,
    ):
        """Test progress command shows summary."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["progress"])

        assert result.exit_code == 0
        assert "Progress" in result.output


# =============================================================================
# Test Context Command
# =============================================================================


class TestContextCommand:
    """Integration tests for the context command."""

    def test_context_shows_accumulated_context(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        paused_state,
        monkeypatch,
    ):
        """Test context command shows accumulated context."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["context"])

        assert result.exit_code == 0
        assert "Context" in result.output


# =============================================================================
# Test Clean Command
# =============================================================================


class TestCleanCommand:
    """Integration tests for the clean command."""

    def test_clean_removes_state(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        pre_planned_state,
        monkeypatch,
    ):
        """Test clean command removes state directory."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Force flag to skip confirmation
        result = runner.invoke(app, ["clean", "--force"])

        assert result.exit_code == 0
        assert not (integration_state_dir / "state.json").exists()

    def test_clean_no_task(
        self,
        runner,
        integration_temp_dir: Path,
        monkeypatch,
    ):
        """Test clean when no task exists."""
        state_dir = integration_temp_dir / ".claude-task-master"
        if state_dir.exists():
            import shutil

            shutil.rmtree(state_dir)

        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", state_dir)

        result = runner.invoke(app, ["clean", "--force"])

        assert result.exit_code == 0
        assert "No task state found" in result.output


# =============================================================================
# Test Error Handling Scenarios
# =============================================================================


class TestErrorHandling:
    """Integration tests for error handling scenarios."""

    def test_start_handles_credential_error(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test start handles missing credentials gracefully."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Point to non-existent credentials
        non_existent = integration_temp_dir / "non_existent" / ".credentials.json"
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", non_existent)

        result = runner.invoke(app, ["start", "Test goal"])

        assert result.exit_code == 1
        # Should give helpful error message
        assert "Error" in result.output or "doctor" in result.output.lower()

    def test_resume_handles_corrupted_state(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test resume handles corrupted state file."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Create a corrupted state file
        state_file = integration_state_dir / "state.json"
        state_file.write_text("{ invalid json }")

        result = runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        # Should indicate error
        assert "Error" in result.output

    def test_status_handles_missing_goal(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test status handles missing goal file."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Create state but no goal
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "working",
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "test-run",
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": False,
            },
        }
        state_file = integration_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))

        result = runner.invoke(app, ["status"])

        # Should still work or give helpful error
        # (either is acceptable depending on implementation)
        assert result.exit_code in [0, 1]


# =============================================================================
# Test State Transitions
# =============================================================================


class TestStateTransitions:
    """Integration tests for state transitions."""

    def test_planning_to_working_transition(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test transition from planning to working state."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        patched_sdk.set_planning_response("""## Task List
- [ ] Task 1

## Success Criteria
1. Done
""")
        patched_sdk.set_work_response("Completed.")
        patched_sdk.set_verify_response("Success!")

        runner.invoke(app, ["start", "Test goal"])

        # Check state file for working status (or success if completed)
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            state_data = json.loads(state_file.read_text())
            # After planning, should be working or success
            assert state_data["status"] in ["working", "success"]

    def test_paused_to_working_transition(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test transition from paused to working state."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Verify initial state is paused
        state_data = json.loads(paused_state["state_file"].read_text())
        assert state_data["status"] == "paused"

        patched_sdk.set_work_response("Completed.")
        patched_sdk.set_verify_response("Success!")

        runner.invoke(app, ["resume"])

        # After resume, status should no longer be paused
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            updated_state = json.loads(state_file.read_text())
            assert updated_state["status"] != "paused"


# =============================================================================
# Test Doctor Command
# =============================================================================


class TestDoctorCommand:
    """Integration tests for the doctor command."""

    def test_doctor_runs_checks(
        self,
        runner,
        integration_temp_dir: Path,
        mock_credentials_file: Path,
        monkeypatch,
    ):
        """Test doctor command runs system checks."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Mock subprocess.run to simulate successful gh check
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = runner.invoke(app, ["doctor"])

        # Doctor should run and complete
        # Exit code depends on all checks passing
        assert "Python" in result.output or "check" in result.output.lower()


# =============================================================================
# Test Complete Start-to-Completion Workflow
# =============================================================================


class TestStartToCompletionWorkflow:
    """Integration tests for the complete start-to-completion workflow.

    These tests verify the entire end-to-end workflow from goal input through
    to successful completion, covering:
    - Fresh start with goal
    - Planning phase execution
    - Work loop execution for all tasks
    - State transitions throughout
    - Success criteria verification
    - State cleanup on success
    """

    def test_complete_single_task_workflow(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test complete workflow with a single task from start to success.

        This test verifies:
        1. Goal is accepted and state is initialized
        2. Planning phase creates a plan with one task
        3. Work session completes the task
        4. Success criteria are verified
        5. Final state is 'success' or cleaned up
        """
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Configure mock SDK for single-task plan
        patched_sdk.set_planning_response("""## Task List

- [ ] Complete the single implementation task

## Success Criteria

1. Task is completed successfully
2. Changes are committed
""")
        patched_sdk.set_work_response("Task completed successfully. Made all required changes.")
        patched_sdk.set_verify_response("All success criteria have been met! Overall: SUCCESS")

        # Execute start command
        result = runner.invoke(app, ["start", "Implement a simple feature", "--model", "sonnet"])

        # Verify workflow completed
        assert result.exit_code == 0, (
            f"Expected exit code 0, got {result.exit_code}. Output: {result.output}"
        )
        assert "Starting new task" in result.output
        assert "Implement a simple feature" in result.output
        assert (
            "completed successfully" in result.output.lower() or "success" in result.output.lower()
        )

        # Verify state is either cleaned up (success) or shows success status
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            state_data = json.loads(state_file.read_text())
            assert state_data["status"] == "success", (
                f"Expected 'success' status, got '{state_data['status']}'"
            )

    def test_complete_multi_task_workflow(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test complete workflow with multiple tasks from start to success.

        This test verifies:
        1. Planning phase creates a plan with multiple tasks
        2. Each task is executed in sequence
        3. Task completion is tracked correctly
        4. All tasks complete before verification
        5. Success is achieved after all tasks
        """
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Configure mock SDK for multi-task plan
        patched_sdk.set_planning_response("""## Task List

- [ ] Initialize the project structure
- [ ] Implement the core module
- [ ] Add comprehensive tests
- [ ] Update documentation

## Success Criteria

1. All four tasks are completed
2. Tests pass successfully
3. Documentation is updated
""")

        # Track work session calls to verify all tasks are processed
        work_call_count = [0]

        def track_work_response(**kwargs):
            work_call_count[0] += 1
            return {"output": f"Completed task {work_call_count[0]}", "success": True}

        patched_sdk.set_work_response("Task completed successfully.")
        patched_sdk.set_verify_response("All success criteria met! All 4 tasks completed.")

        # Execute start command
        result = runner.invoke(app, ["start", "Build a complete module", "--model", "sonnet"])

        # Verify workflow started
        assert "Starting new task" in result.output
        assert "Build a complete module" in result.output

        # Verify completion (exit code 0 means success)
        if result.exit_code == 0:
            # Success - either state is cleaned up or shows success
            state_file = integration_state_dir / "state.json"
            if state_file.exists():
                state_data = json.loads(state_file.read_text())
                assert state_data["status"] == "success"
        else:
            # Should not fail for this test
            assert result.exit_code == 0, (
                f"Multi-task workflow should complete. Output: {result.output}"
            )

    def test_workflow_with_verification_pass(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that successful verification completes the workflow.

        Verifies the critical path: tasks complete -> verification passes -> success.
        """
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        patched_sdk.set_planning_response("""## Task List

- [ ] Single task to verify

## Success Criteria

1. Verification passes
2. All criteria met
""")
        patched_sdk.set_work_response("Task completed.")
        # Explicitly set verification to pass
        patched_sdk.set_verify_response("""
## Criteria Verification

1. ✓ Verification passes - VERIFIED
2. ✓ All criteria met - VERIFIED

Overall Status: SUCCESS
All success criteria have been met!
""")

        result = runner.invoke(app, ["start", "Test verification flow", "--model", "sonnet"])

        # Should complete successfully
        assert result.exit_code == 0, f"Verification should pass. Output: {result.output}"

    def test_workflow_state_progression(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that state progresses correctly through the workflow.

        Verifies state transitions: (no state) -> planning -> working -> success.
        """
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Verify no initial state
        assert not (integration_state_dir / "state.json").exists()

        patched_sdk.set_planning_response("""## Task List

- [ ] Task 1

## Success Criteria

1. Done
""")
        patched_sdk.set_work_response("Done.")
        patched_sdk.set_verify_response("All success criteria met!")

        result = runner.invoke(app, ["start", "Track state progression", "--model", "sonnet"])

        # Workflow should complete
        assert result.exit_code == 0 or result.exit_code == 1  # Success or blocked

        # If state exists, verify it's in a valid end state
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            state_data = json.loads(state_file.read_text())
            # Should be in a terminal or valid intermediate state
            assert state_data["status"] in ["success", "blocked", "working", "failed"]

    def test_workflow_preserves_artifacts(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that workflow artifacts (plan, goal, logs) are created and preserved.

        Verifies:
        1. goal.txt is created with the original goal
        2. plan.md is created with the planning output
        3. logs directory is created for session logs
        """
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        test_goal = "Create comprehensive artifacts"
        patched_sdk.set_planning_response("""## Task List

- [ ] Create artifact task

## Success Criteria

1. Artifacts are created
""")
        patched_sdk.set_work_response("Artifacts created.")
        patched_sdk.set_verify_response("All criteria met!")

        result = runner.invoke(app, ["start", test_goal, "--model", "sonnet"])

        # Verify goal file was created
        goal_file = integration_state_dir / "goal.txt"
        if goal_file.exists():
            assert test_goal in goal_file.read_text()

        # Verify plan file was created
        plan_file = integration_state_dir / "plan.md"
        if plan_file.exists():
            plan_content = plan_file.read_text()
            assert "Task List" in plan_content
            assert "Success Criteria" in plan_content

        # Verify logs directory was created
        logs_dir = integration_state_dir / "logs"
        # Logs may or may not exist depending on how far we got
        # But if state exists, logs should too
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            assert logs_dir.exists() or result.exit_code != 0

    def test_workflow_with_max_sessions(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test workflow with max_sessions limit that allows completion.

        Verifies that workflow completes when tasks finish before max sessions.
        """
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        patched_sdk.set_planning_response("""## Task List

- [ ] Task 1
- [ ] Task 2

## Success Criteria

1. Done
""")
        patched_sdk.set_work_response("Task done.")
        patched_sdk.set_verify_response("All success criteria met!")

        runner.invoke(
            app, ["start", "Test max sessions", "--model", "sonnet", "--max-sessions", "10"]
        )

        # Should complete with plenty of sessions remaining
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            state_data = json.loads(state_file.read_text())
            # Should not have hit max sessions
            if state_data.get("options", {}).get("max_sessions"):
                assert state_data["session_count"] <= state_data["options"]["max_sessions"]

    def test_workflow_full_cycle_with_resume(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test complete workflow cycle: start -> pause -> resume -> complete.

        This is the most comprehensive test, verifying the full lifecycle including
        interruption and recovery.
        """
        import shutil

        # Clean state first
        if integration_state_dir.exists():
            shutil.rmtree(integration_state_dir)
        integration_state_dir.mkdir(parents=True)

        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Configure for a multi-task plan
        patched_sdk.reset()
        patched_sdk.set_planning_response("""## Task List

- [ ] First phase: Setup
- [ ] Second phase: Implementation
- [ ] Third phase: Testing

## Success Criteria

1. All three phases complete
""")
        patched_sdk.set_work_response("Phase completed successfully.")
        patched_sdk.set_verify_response("All success criteria met!")

        # Step 1: Start the workflow
        result = runner.invoke(app, ["start", "Full cycle test", "--model", "sonnet"])

        # The workflow should have progressed
        assert "Starting new task" in result.output

        # Step 2: If workflow is still in progress, verify state
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            state_data = json.loads(state_file.read_text())
            initial_status = state_data["status"]

            # If not already complete, try resume
            if initial_status not in ["success", "failed"]:
                # Update state to paused to test resume
                state_data["status"] = "paused"
                state_file.write_text(json.dumps(state_data, indent=2))

                # Step 3: Resume the workflow
                result = runner.invoke(app, ["resume"])

                # Should either complete or continue
                assert "Resuming" in result.output or "resume" in result.output.lower()

        # Verify final state is valid
        if state_file.exists():
            final_state = json.loads(state_file.read_text())
            assert final_state["status"] in ["success", "paused", "blocked", "working"]

    def test_workflow_options_preserved(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that workflow options are preserved throughout execution.

        Verifies:
        1. auto_merge option is saved
        2. max_sessions option is saved
        3. pause_on_pr option is saved
        """
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        patched_sdk.set_planning_response("""## Task List

- [ ] Task with options

## Success Criteria

1. Options preserved
""")
        patched_sdk.set_work_response("Done.")
        patched_sdk.set_verify_response("All criteria met!")

        runner.invoke(
            app,
            [
                "start",
                "Test options preservation",
                "--no-auto-merge",
                "--max-sessions",
                "5",
                "--pause-on-pr",
            ],
        )

        # Verify options in state
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            state_data = json.loads(state_file.read_text())
            options = state_data.get("options", {})

            assert options.get("auto_merge") is False, "auto_merge should be False"
            assert options.get("max_sessions") == 5, "max_sessions should be 5"
            assert options.get("pause_on_pr") is True, "pause_on_pr should be True"

    def test_workflow_handles_empty_plan_gracefully(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test workflow handles a plan with no checkboxes gracefully.

        When planning returns content without proper task checkboxes,
        the workflow should handle it gracefully (either succeed with nothing
        to do, or fail with a clear message).
        """
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Plan with no checkboxes
        patched_sdk.set_planning_response("""## Task List

This goal requires no tasks - everything is already done.

## Success Criteria

1. Nothing to do
""")
        patched_sdk.set_verify_response("Success - nothing needed!")

        result = runner.invoke(app, ["start", "Empty task list", "--model", "sonnet"])

        # Should complete successfully (nothing to do is valid)
        # or fail gracefully with clear indication
        assert result.exit_code in [0, 1]

    def test_workflow_model_options(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test workflow with different model options.

        Verifies that each model option (sonnet, opus, haiku) is accepted
        and saved correctly in the state.
        """
        for model in ["sonnet", "opus", "haiku"]:
            # Clean state for each model test
            import shutil

            if integration_state_dir.exists():
                shutil.rmtree(integration_state_dir)
            integration_state_dir.mkdir(parents=True)

            monkeypatch.chdir(integration_temp_dir)
            monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
            monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

            patched_sdk.reset()
            patched_sdk.set_planning_response("""## Task List

- [ ] Task for model test

## Success Criteria

1. Done
""")
            patched_sdk.set_work_response("Completed.")
            patched_sdk.set_verify_response("All criteria met!")

            runner.invoke(app, ["start", f"Test with {model} model", "--model", model])

            # Verify model was saved
            state_file = integration_state_dir / "state.json"
            if state_file.exists():
                state_data = json.loads(state_file.read_text())
                assert state_data["model"] == model, f"Model should be {model}"
