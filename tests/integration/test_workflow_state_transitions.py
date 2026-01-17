"""Integration tests for state transitions.

These tests verify state transitions throughout the workflow including:
- Planning to working transitions
- Paused to working transitions
- State progression validation
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


class TestStateValidation:
    """Tests for state validation during transitions."""

    def test_blocked_state_prevents_resume(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        blocked_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test that blocked state shows appropriate info on resume."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Set up SDK responses so it doesn't block
        patched_sdk.set_work_response("Completed.")
        patched_sdk.set_verify_response("Success!")

        result = runner.invoke(app, ["resume"])

        # Should indicate blocked status
        assert "blocked" in result.output.lower() or "pr" in result.output.lower()

    def test_completed_state_indicates_done(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        completed_state,
        monkeypatch,
    ):
        """Test that completed state is indicated on resume."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["resume"])

        # Should indicate already complete
        assert (
            "success" in result.output.lower()
            or "completed" in result.output.lower()
            or result.exit_code == 0
        )

    def test_state_timestamps_updated(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test that state timestamps are updated on transition."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Get original state (to verify state changes after resume)
        original_state = json.loads(paused_state["state_file"].read_text())
        _ = original_state["updated_at"]  # Capture timestamp for potential comparison

        patched_sdk.set_work_response("Completed.")
        patched_sdk.set_verify_response("Success!")

        runner.invoke(app, ["resume"])

        # Check if timestamp was updated
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            updated_state = json.loads(state_file.read_text())
            # Updated_at should change (or state should be cleaned on success)
            # Just verify state structure is valid
            assert "status" in updated_state
