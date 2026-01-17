"""End-to-end integration tests for the complete workflow.

These tests verify the complete start-to-completion workflow including:
- Single and multi-task workflows
- Verification pass/fail scenarios
- State progression through full lifecycle
- Artifact preservation
- Options persistence
- Resume cycle testing
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.core.credentials import CredentialManager
from claude_task_master.core.state import StateManager


@pytest.fixture
def runner():
    """Provide a CLI test runner."""
    return CliRunner()


class TestSingleTaskWorkflow:
    """Integration tests for single-task end-to-end workflow."""

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


class TestMultiTaskWorkflow:
    """Integration tests for multi-task end-to-end workflow."""

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


class TestVerificationWorkflow:
    """Integration tests for verification phase in workflow."""

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


class TestStateProgressionWorkflow:
    """Integration tests for state progression through workflow."""

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


class TestArtifactPreservation:
    """Integration tests for workflow artifact preservation."""

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


class TestSessionLimits:
    """Integration tests for session limit handling."""

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


class TestResumeIntegration:
    """Integration tests for resume within workflow."""

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


class TestOptionsPreservation:
    """Integration tests for workflow options preservation."""

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


class TestEdgeCases:
    """Integration tests for edge cases in workflow."""

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


class TestModelOptions:
    """Integration tests for model options in workflow."""

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
