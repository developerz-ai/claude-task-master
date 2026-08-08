"""Tests for CLI control commands - pause, stop, config-update."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.cli_commands import control
from claude_task_master.core.state import StateManager, TaskOptions

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_console():
    """Mock the rich console."""
    with patch.object(control, "console") as mock:
        yield mock


@pytest.fixture
def control_state_dir(temp_dir: Path) -> Path:
    """Create a state directory for control command tests."""
    state_dir = temp_dir / ".claude-task-master"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture
def control_state_manager(control_state_dir: Path) -> StateManager:
    """Create a StateManager instance for control tests."""
    return StateManager(control_state_dir)


@pytest.fixture
def task_options():
    """Create sample task options."""
    return TaskOptions(
        auto_merge=True,
        max_sessions=None,
        pause_on_pr=False,
        enable_checkpointing=False,
        log_level="normal",
        log_format="text",
        pr_per_task=False,
    )


def _use_state_dir(state_dir: Path):
    """Patch StateManager to use a specific state directory."""
    return patch.object(StateManager, "STATE_DIR", state_dir)


# =============================================================================
# Pause Command Tests
# =============================================================================


class TestPauseCommand:
    """Tests for the pause command."""

    def test_pause_command_registered(
        self, cli_runner: CliRunner, isolated_filesystem: Path
    ) -> None:
        """Test that pause command is registered."""
        result = cli_runner.invoke(app, ["pause", "--help"])
        assert result.exit_code == 0
        assert "Pause a running task" in result.stdout

    def test_pause_with_no_task(self, cli_runner: CliRunner, isolated_filesystem: Path) -> None:
        """Test pause command when no task exists."""
        result = cli_runner.invoke(app, ["pause"])
        assert result.exit_code == 1
        assert "No active task found" in result.stdout

    def test_pause_with_reason(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test pause command with reason option."""
        # Create a temporary task state
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["pause", "--reason", "Testing pause"])
            assert result.exit_code == 0
            assert "Task paused successfully" in result.stdout
            assert "Reason: Testing pause" in result.stdout

        # Verify state was updated
        updated_state = control_state_manager.load_state()
        assert updated_state.status == "paused"

        # Verify progress was updated
        progress = control_state_manager.load_progress()
        assert progress is not None
        assert "Paused" in progress
        assert "Testing pause" in progress

    def test_pause_without_reason(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test pause command without reason."""
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["pause"])
            assert result.exit_code == 0
            assert "Task paused successfully" in result.stdout

    def test_pause_short_option(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test pause command with short option."""
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["pause", "-r", "Short reason"])
            assert result.exit_code == 0
            assert "Task paused successfully" in result.stdout


# =============================================================================
# Stop Command Tests
# =============================================================================


class TestStopCommand:
    """Tests for the stop command."""

    def test_stop_command_registered(
        self, cli_runner: CliRunner, isolated_filesystem: Path
    ) -> None:
        """Test that stop command is registered."""
        result = cli_runner.invoke(app, ["stop", "--help"])
        assert result.exit_code == 0
        assert "Stop a running task" in result.stdout

    def test_stop_with_no_task(self, cli_runner: CliRunner, isolated_filesystem: Path) -> None:
        """Test stop command when no task exists."""
        result = cli_runner.invoke(app, ["stop"])
        assert result.exit_code == 1
        assert "No active task found" in result.stdout

    def test_stop_with_reason(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test stop command with reason option."""
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["stop", "--reason", "Testing stop"])
            assert result.exit_code == 0
            assert "Task stopped successfully" in result.stdout
            assert "Reason: Testing stop" in result.stdout

        # Verify state was updated
        updated_state = control_state_manager.load_state()
        assert updated_state.status == "stopped"

    def test_stop_with_cleanup(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test stop command with cleanup option."""
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["stop", "--cleanup"])
            assert result.exit_code == 0
            assert "Task stopped successfully" in result.stdout
            assert "State files cleaned up" in result.stdout

    def test_stop_short_options(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test stop command with short options."""
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["stop", "-r", "Reason", "-c"])
            assert result.exit_code == 0


# =============================================================================
# Config Update Command Tests
# =============================================================================


class TestConfigUpdateCommand:
    """Tests for the config-update command."""

    def test_config_update_command_registered(
        self, cli_runner: CliRunner, isolated_filesystem: Path
    ) -> None:
        """Test that config-update command is registered."""
        result = cli_runner.invoke(app, ["config-update", "--help"])
        assert result.exit_code == 0
        assert "Update task configuration" in result.stdout

    def test_config_update_with_no_task(
        self, cli_runner: CliRunner, isolated_filesystem: Path
    ) -> None:
        """Test config-update when no task exists."""
        result = cli_runner.invoke(app, ["config-update", "--auto-merge"])
        assert result.exit_code == 1
        assert "No active task found" in result.stdout

    def test_config_update_no_options(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test config-update with no options specified."""
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["config-update"])
            assert result.exit_code == 1
            assert "No configuration options specified" in result.stdout

    def test_config_update_auto_merge(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test config-update with auto-merge option."""
        # Start with auto_merge=False so we can update it to True
        task_options.auto_merge = False
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["config-update", "--auto-merge"])
            assert result.exit_code == 0
            assert "Configuration updated" in result.stdout
            assert "Current Configuration:" in result.stdout

        # Verify config was updated
        state = control_state_manager.load_state()
        assert state.options.auto_merge is True

    def test_config_update_no_auto_merge(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test config-update with no-auto-merge option."""
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["config-update", "--no-auto-merge"])
            assert result.exit_code == 0

        # Verify config was updated
        state = control_state_manager.load_state()
        assert state.options.auto_merge is False

    def test_config_update_max_sessions(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test config-update with max-sessions option."""
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["config-update", "--max-sessions", "10"])
            assert result.exit_code == 0

        # Verify config was updated
        state = control_state_manager.load_state()
        assert state.options.max_sessions == 10

    def test_config_update_pause_on_pr(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test config-update with pause-on-pr option."""
        # Start with pause_on_pr=False (already set in fixture)
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["config-update", "--pause-on-pr"])
            assert result.exit_code == 0
            assert "Configuration updated" in result.stdout

        # Verify config was updated
        state = control_state_manager.load_state()
        assert state.options.pause_on_pr is True

    def test_config_update_parallel_tasks(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """config-update --parallel-tasks turns hive mode on mid-run."""
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)
        assert control_state_manager.load_state().options.parallel_tasks is False

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["config-update", "--parallel-tasks"])
            assert result.exit_code == 0
            assert "Configuration updated" in result.stdout

        state = control_state_manager.load_state()
        assert state.options.parallel_tasks is True

    def test_config_update_no_parallel_tasks(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """config-update --no-parallel-tasks turns hive mode back off."""
        task_options.parallel_tasks = True
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["config-update", "--no-parallel-tasks"])
            assert result.exit_code == 0

        state = control_state_manager.load_state()
        assert state.options.parallel_tasks is False

    def test_config_update_multiple_options(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test config-update with multiple options."""
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(
                app, ["config-update", "--auto-merge", "--max-sessions", "5", "--pause-on-pr"]
            )
            assert result.exit_code == 0

        # Verify all configs were updated
        state = control_state_manager.load_state()
        assert state.options.auto_merge is True
        assert state.options.max_sessions == 5
        assert state.options.pause_on_pr is True

    def test_config_update_short_option(
        self,
        cli_runner: CliRunner,
        control_state_dir: Path,
        control_state_manager: StateManager,
        task_options: TaskOptions,
        isolated_filesystem: Path,
    ) -> None:
        """Test config-update with short option for max-sessions."""
        control_state_manager.initialize(goal="Test task", model="opus", options=task_options)

        with _use_state_dir(control_state_dir):
            result = cli_runner.invoke(app, ["config-update", "-n", "15"])
            assert result.exit_code == 0

        # Verify config was updated
        state = control_state_manager.load_state()
        assert state.options.max_sessions == 15


# =============================================================================
# Register Function Tests
# =============================================================================


class TestRegisterControlCommands:
    """Tests for the register_control_commands function."""

    def test_register_control_commands(self) -> None:
        """Test that register_control_commands registers all commands."""
        from typer import Typer

        test_app = Typer()
        control.register_control_commands(test_app)

        # Verify commands are registered by checking if they can be invoked
        # Commands are registered as Typer Command objects
        assert len(test_app.registered_commands) >= 3

        # Verify the commands work by checking their help
        runner = CliRunner()
        for cmd_name in ["pause", "stop", "config-update"]:
            result = runner.invoke(test_app, [cmd_name, "--help"])
            assert result.exit_code == 0
            assert cmd_name in result.stdout or cmd_name.replace("-", "_") in result.stdout
