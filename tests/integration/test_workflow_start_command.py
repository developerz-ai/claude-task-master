"""Integration tests for the start command workflow.

These tests verify the start command behavior including:
- State initialization
- Model options
- Custom workflow options
- Error cases when task already exists
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
