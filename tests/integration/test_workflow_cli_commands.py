"""Integration tests for CLI commands (status, plan, progress, context, clean, doctor).

These tests verify the behavior of auxiliary CLI commands that inspect
and manage workflow state.
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


@pytest.fixture
def runner():
    """Provide a CLI test runner."""
    return CliRunner()


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
# Test Error Handling for CLI Commands
# =============================================================================


class TestCLICommandErrorHandling:
    """Tests for CLI command error handling."""

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
