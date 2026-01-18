"""Integration tests for CLI control commands (pause, stop, config-update).

These tests verify the end-to-end behavior of the CLI control commands
that manage task execution state through the ControlManager.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


@pytest.fixture
def runner():
    """Provide a CLI test runner."""
    return CliRunner()


@pytest.fixture
def working_state(
    integration_state_dir: Path,
    sample_plan_content: str,
    sample_goal: str,
) -> dict:
    """Create a working state for testing pause/stop operations."""
    timestamp = datetime.now().isoformat()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    state_data = {
        "status": "working",
        "workflow_stage": "working",
        "current_task_index": 1,
        "session_count": 2,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": run_id,
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": None,
            "pause_on_pr": False,
            "enable_checkpointing": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }

    # Write state file
    state_file = integration_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data, indent=2))

    # Write goal file
    goal_file = integration_state_dir / "goal.txt"
    goal_file.write_text(sample_goal)

    # Write plan file
    plan_file = integration_state_dir / "plan.md"
    plan_file.write_text(sample_plan_content)

    # Create logs directory
    logs_dir = integration_state_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    return {
        "state_file": state_file,
        "goal_file": goal_file,
        "plan_file": plan_file,
        "run_id": run_id,
        "state_data": state_data,
    }


@pytest.fixture
def stopped_state(
    integration_state_dir: Path,
    sample_plan_content: str,
    sample_goal: str,
) -> dict:
    """Create a stopped state for testing resume operations."""
    timestamp = datetime.now().isoformat()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    state_data = {
        "status": "stopped",
        "workflow_stage": "working",
        "current_task_index": 1,
        "session_count": 2,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": run_id,
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": None,
            "pause_on_pr": False,
            "enable_checkpointing": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }

    # Write state file
    state_file = integration_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data, indent=2))

    # Write goal file
    goal_file = integration_state_dir / "goal.txt"
    goal_file.write_text(sample_goal)

    # Write plan file
    plan_file = integration_state_dir / "plan.md"
    plan_file.write_text(sample_plan_content)

    # Write progress file with stop info
    progress_file = integration_state_dir / "progress.md"
    progress_file.write_text("## Progress\n\n## Stopped\n\nReason: Test stop")

    # Create logs directory
    logs_dir = integration_state_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    return {
        "state_file": state_file,
        "goal_file": goal_file,
        "plan_file": plan_file,
        "progress_file": progress_file,
        "run_id": run_id,
        "state_data": state_data,
    }


# =============================================================================
# Test Pause Command
# =============================================================================


class TestPauseCommand:
    """Integration tests for the pause command."""

    def test_pause_working_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test pausing a task in working status."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["pause"])

        assert result.exit_code == 0
        assert "paused successfully" in result.output.lower()

        # Verify state was updated
        state_manager = StateManager()
        state = state_manager.load_state()
        assert state.status == "paused"

    def test_pause_with_reason(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test pausing a task with a reason."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        reason = "Taking a lunch break"
        result = runner.invoke(app, ["pause", "--reason", reason])

        assert result.exit_code == 0
        assert "paused successfully" in result.output.lower()
        assert reason in result.output

        # Verify reason was saved to progress
        state_manager = StateManager()
        progress = state_manager.load_progress()
        assert progress is not None
        assert reason in progress

    def test_pause_no_active_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test pause command when no task exists."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Ensure no state exists
        import shutil

        if integration_state_dir.exists():
            shutil.rmtree(integration_state_dir)
        integration_state_dir.mkdir(parents=True)

        result = runner.invoke(app, ["pause"])

        assert result.exit_code == 1
        assert "no active task" in result.output.lower()

    def test_pause_already_paused_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        paused_state: dict,
        monkeypatch,
    ):
        """Test pause command on already paused task."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["pause"])

        assert result.exit_code == 1
        assert "cannot pause" in result.output.lower()

    def test_pause_completed_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test pause command on completed task."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Update state to success
        state_manager = StateManager()
        state = state_manager.load_state()
        state.status = "success"
        state_manager.save_state(state, validate_transition=False)

        result = runner.invoke(app, ["pause"])

        assert result.exit_code == 1
        assert "cannot pause" in result.output.lower()


# =============================================================================
# Test Stop Command
# =============================================================================


class TestStopCommand:
    """Integration tests for the stop command."""

    def test_stop_working_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test stopping a task in working status."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["stop"])

        assert result.exit_code == 0
        assert "stopped successfully" in result.output.lower()

        # Verify state was updated
        state_manager = StateManager()
        state = state_manager.load_state()
        assert state.status == "stopped"

    def test_stop_with_reason(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test stopping a task with a reason."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        reason = "Task no longer needed"
        result = runner.invoke(app, ["stop", "--reason", reason])

        assert result.exit_code == 0
        assert "stopped successfully" in result.output.lower()
        assert reason in result.output

        # Verify reason was saved to progress
        state_manager = StateManager()
        progress = state_manager.load_progress()
        assert progress is not None
        assert reason in progress

    def test_stop_with_cleanup(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test stopping a task with cleanup flag."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["stop", "--cleanup"])

        assert result.exit_code == 0
        assert "stopped successfully" in result.output.lower()
        assert "cleaned up" in result.output.lower() or "cleanup" in result.output.lower()

    def test_stop_no_active_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test stop command when no task exists."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Ensure no state exists
        import shutil

        if integration_state_dir.exists():
            shutil.rmtree(integration_state_dir)
        integration_state_dir.mkdir(parents=True)

        result = runner.invoke(app, ["stop"])

        assert result.exit_code == 1
        assert "no active task" in result.output.lower()

    def test_stop_paused_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        paused_state: dict,
        monkeypatch,
    ):
        """Test stopping a paused task."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["stop"])

        assert result.exit_code == 0
        assert "stopped successfully" in result.output.lower()

        # Verify state was updated
        state_manager = StateManager()
        state = state_manager.load_state()
        assert state.status == "stopped"

    def test_stop_blocked_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        blocked_state: dict,
        monkeypatch,
    ):
        """Test stopping a blocked task."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["stop"])

        assert result.exit_code == 0
        assert "stopped successfully" in result.output.lower()

        # Verify state was updated
        state_manager = StateManager()
        state = state_manager.load_state()
        assert state.status == "stopped"


# =============================================================================
# Test Config-Update Command
# =============================================================================


class TestConfigUpdateCommand:
    """Integration tests for the config-update command."""

    def test_config_update_auto_merge(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test updating auto_merge configuration."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["config-update", "--no-auto-merge"])

        assert result.exit_code == 0
        assert "configuration updated" in result.output.lower()

        # Verify state was updated
        state_manager = StateManager()
        state = state_manager.load_state()
        assert state.options.auto_merge is False

    def test_config_update_max_sessions(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test updating max_sessions configuration."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["config-update", "--max-sessions", "5"])

        assert result.exit_code == 0
        assert "configuration updated" in result.output.lower()

        # Verify state was updated
        state_manager = StateManager()
        state = state_manager.load_state()
        assert state.options.max_sessions == 5

    def test_config_update_pause_on_pr(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test updating pause_on_pr configuration."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["config-update", "--pause-on-pr"])

        assert result.exit_code == 0
        assert "configuration updated" in result.output.lower()

        # Verify state was updated
        state_manager = StateManager()
        state = state_manager.load_state()
        assert state.options.pause_on_pr is True

    def test_config_update_multiple_options(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test updating multiple configuration options at once."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(
            app,
            ["config-update", "--no-auto-merge", "--max-sessions", "10", "--pause-on-pr"],
        )

        assert result.exit_code == 0
        assert "configuration updated" in result.output.lower()

        # Verify all state options were updated
        state_manager = StateManager()
        state = state_manager.load_state()
        assert state.options.auto_merge is False
        assert state.options.max_sessions == 10
        assert state.options.pause_on_pr is True

    def test_config_update_no_options(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test config-update command without any options."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["config-update"])

        assert result.exit_code == 1
        assert "no configuration options" in result.output.lower()

    def test_config_update_no_active_task(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test config-update command when no task exists."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Ensure no state exists
        import shutil

        if integration_state_dir.exists():
            shutil.rmtree(integration_state_dir)
        integration_state_dir.mkdir(parents=True)

        result = runner.invoke(app, ["config-update", "--auto-merge"])

        assert result.exit_code == 1
        assert "no active task" in result.output.lower()

    def test_config_update_shows_current_config(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test that config-update shows current configuration."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["config-update", "--max-sessions", "15"])

        assert result.exit_code == 0
        assert "current configuration" in result.output.lower()
        # Should show the updated value
        assert "15" in result.output


# =============================================================================
# Test Integration Between Commands
# =============================================================================


class TestControlCommandsIntegration:
    """Integration tests for workflows involving multiple control commands."""

    def test_pause_then_resume_workflow(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test pausing a task and then resuming it."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Pause the task
        pause_result = runner.invoke(app, ["pause", "--reason", "Test pause"])
        assert pause_result.exit_code == 0

        # Verify paused state
        state_manager = StateManager()
        state = state_manager.load_state()
        assert state.status == "paused"

        # Resume should work (but we're not testing full resume workflow here,
        # just that the state is resumable)
        assert state.status in ["paused"]

    def test_stop_then_status(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test stopping a task and then checking status."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Stop the task
        stop_result = runner.invoke(app, ["stop", "--reason", "Task complete"])
        assert stop_result.exit_code == 0

        # Check status
        status_result = runner.invoke(app, ["status"])
        assert status_result.exit_code == 0
        assert "stopped" in status_result.output.lower()

    def test_config_update_then_pause(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        working_state: dict,
        monkeypatch,
    ):
        """Test updating config and then pausing."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Update config
        config_result = runner.invoke(app, ["config-update", "--max-sessions", "20"])
        assert config_result.exit_code == 0

        # Pause the task
        pause_result = runner.invoke(app, ["pause"])
        assert pause_result.exit_code == 0

        # Verify both operations succeeded
        state_manager = StateManager()
        state = state_manager.load_state()
        assert state.status == "paused"
        assert state.options.max_sessions == 20

    def test_pause_stop_on_stopped_state(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        stopped_state: dict,
        monkeypatch,
    ):
        """Test that pause fails on stopped state."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Try to pause stopped task (should fail)
        pause_result = runner.invoke(app, ["pause"])
        assert pause_result.exit_code == 1
        assert "cannot pause" in pause_result.output.lower()

        # Verify state is still stopped
        state_manager = StateManager()
        state = state_manager.load_state()
        assert state.status == "stopped"
