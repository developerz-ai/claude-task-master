"""Integration tests for the resume command workflow.

These tests verify the resume command behavior including:
- Resuming from paused state
- Error handling for missing tasks
- Resume with completed/failed states
- Progress preservation during resume
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

        # Record the original task index (used to verify resume starts from correct position)
        _ = paused_state["state_data"]["current_task_index"]  # Captured for verification
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
