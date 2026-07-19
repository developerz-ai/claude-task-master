"""Tests for ControlManager - runtime control operations."""

import logging

import pytest

from claude_task_master.core import control as control_module
from claude_task_master.core.control import (
    ControlError,
    ControlManager,
    ControlOperationNotAllowedError,
    ControlResult,
    NoActiveTaskError,
)
from claude_task_master.core.control_channel import ControlChannel
from claude_task_master.core.state import StateManager, TaskState
from claude_task_master.mailbox.storage import MailboxStorage

# =============================================================================
# ControlResult Tests
# =============================================================================


class TestControlResult:
    """Tests for ControlResult dataclass."""

    def test_result_creation(self):
        """Test ControlResult creation with all fields."""
        result = ControlResult(
            success=True,
            operation="pause",
            previous_status="working",
            new_status="paused",
            message="Task paused",
            details={"reason": "user request"},
        )
        assert result.success is True
        assert result.operation == "pause"
        assert result.previous_status == "working"
        assert result.new_status == "paused"
        assert result.message == "Task paused"
        assert result.details == {"reason": "user request"}

    def test_result_defaults(self):
        """Test ControlResult with default values."""
        result = ControlResult(
            success=True,
            operation="status",
            previous_status=None,
            new_status=None,
            message="Status retrieved",
        )
        assert result.details is None


# =============================================================================
# ControlError Tests
# =============================================================================


class TestControlErrors:
    """Tests for control exception classes."""

    def test_control_error_base(self):
        """Test ControlError base exception."""
        error = ControlError("Test error")
        assert error.message == "Test error"
        assert error.details is None
        assert str(error) == "Test error"

    def test_control_error_with_details(self):
        """Test ControlError with details."""
        error = ControlError("Test error", "Additional info")
        assert error.message == "Test error"
        assert error.details == "Additional info"
        assert "Additional info" in str(error)

    def test_control_operation_not_allowed_error(self):
        """Test ControlOperationNotAllowedError exception."""
        error = ControlOperationNotAllowedError(
            "pause",
            "success",
            frozenset(["planning", "working"]),
        )
        assert error.operation == "pause"
        assert error.current_status == "success"
        assert error.allowed_statuses == frozenset(["planning", "working"])
        assert "Cannot pause" in str(error)
        assert "success" in str(error)

    def test_control_operation_not_allowed_without_allowed_statuses(self):
        """Test ControlOperationNotAllowedError without allowed statuses."""
        error = ControlOperationNotAllowedError("stop", "failed")
        assert error.allowed_statuses is None
        assert "Cannot stop" in str(error)
        assert "failed" in str(error)

    def test_no_active_task_error(self):
        """Test NoActiveTaskError exception."""
        error = NoActiveTaskError("pause")
        assert error.operation == "pause"
        assert "Cannot pause" in str(error)
        assert "no active task" in str(error)


# =============================================================================
# ControlManager Initialization Tests
# =============================================================================


class TestControlManagerInit:
    """Tests for ControlManager initialization."""

    def test_init_with_state_manager(self, temp_dir):
        """Test initialization with provided StateManager."""
        state_manager = StateManager(temp_dir / ".claude-task-master")
        control = ControlManager(state_manager=state_manager)
        assert control.state_manager is state_manager

    def test_init_with_state_dir(self, temp_dir):
        """Test initialization with state directory path."""
        state_dir = temp_dir / ".claude-task-master"
        control = ControlManager(state_dir=state_dir)
        assert control.state_manager.state_dir == state_dir

    def test_init_creates_default_state_manager(self):
        """Test initialization creates default StateManager."""
        control = ControlManager()
        assert control.state_manager is not None
        assert isinstance(control.state_manager, StateManager)

    def test_init_uses_global_shutdown_manager(self):
        """Test initialization uses global ShutdownManager."""
        control = ControlManager()
        assert control.shutdown_manager is not None


# =============================================================================
# ControlManager.pause() Tests
# =============================================================================


class TestControlManagerPause:
    """Tests for ControlManager.pause() method."""

    def test_pause_working_task(self, initialized_state_manager):
        """Test pausing a working task."""
        # First transition to working
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        result = control.pause()

        assert result.success is True
        assert result.operation == "pause"
        assert result.previous_status == "working"
        assert result.new_status == "paused"
        assert "paused successfully" in result.message

        # Verify state was updated
        state = initialized_state_manager.load_state()
        assert state.status == "paused"

    def test_pause_planning_task(self, initialized_state_manager):
        """Test pausing a task in planning phase."""
        control = ControlManager(state_manager=initialized_state_manager)
        result = control.pause()

        assert result.success is True
        assert result.previous_status == "planning"
        assert result.new_status == "paused"

        state = initialized_state_manager.load_state()
        assert state.status == "paused"

    def test_pause_with_reason(self, initialized_state_manager):
        """Test pausing with a reason."""
        control = ControlManager(state_manager=initialized_state_manager)
        result = control.pause(reason="Need to review")

        assert result.success is True
        assert result.details == {"reason": "Need to review"}

        # Verify reason was saved to progress
        progress = initialized_state_manager.load_progress()
        assert "Paused" in progress
        assert "Need to review" in progress

    def test_pause_already_paused_raises_error(self, initialized_state_manager):
        """Test pausing an already paused task raises error."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "paused"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)

        with pytest.raises(ControlOperationNotAllowedError) as exc_info:
            control.pause()

        assert exc_info.value.current_status == "paused"
        assert exc_info.value.operation == "pause"

    def test_pause_blocked_task_raises_error(self, initialized_state_manager):
        """Test pausing a blocked task raises error."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "blocked"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)

        with pytest.raises(ControlOperationNotAllowedError):
            control.pause()

    def test_pause_success_task_raises_error(self, initialized_state_manager):
        """Test pausing a successful task raises error."""
        state = initialized_state_manager.load_state()
        state.status = "success"
        initialized_state_manager.save_state(state, validate_transition=False)

        control = ControlManager(state_manager=initialized_state_manager)

        with pytest.raises(ControlOperationNotAllowedError) as exc_info:
            control.pause()

        assert exc_info.value.current_status == "success"

    def test_pause_no_active_task_raises_error(self, temp_dir):
        """Test pausing without active task raises error."""
        state_dir = temp_dir / ".claude-task-master"
        control = ControlManager(state_dir=state_dir)

        with pytest.raises(NoActiveTaskError) as exc_info:
            control.pause()

        assert exc_info.value.operation == "pause"


# =============================================================================
# ControlManager.resume() Tests
# =============================================================================


class TestControlManagerResume:
    """Tests for ControlManager.resume() method."""

    def test_resume_paused_task(self, initialized_state_manager):
        """Test resuming a paused task."""
        # Transition to paused
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "paused"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        result = control.resume()

        assert result.success is True
        assert result.operation == "resume"
        assert result.previous_status == "paused"
        assert result.new_status == "working"
        assert "resumed successfully" in result.message

        # Verify state was updated
        state = initialized_state_manager.load_state()
        assert state.status == "working"

    def test_resume_blocked_task(self, initialized_state_manager):
        """Test resuming a blocked task."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "blocked"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        result = control.resume()

        assert result.success is True
        assert result.previous_status == "blocked"
        assert result.new_status == "working"

        state = initialized_state_manager.load_state()
        assert state.status == "working"

    def test_resume_working_task(self, initialized_state_manager):
        """Test resuming a working task (already working)."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        result = control.resume()

        assert result.success is True
        assert result.previous_status == "working"
        assert result.new_status == "working"

    def test_resume_updates_progress(self, initialized_state_manager):
        """Test resuming updates progress file."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "paused"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        control.resume()

        progress = initialized_state_manager.load_progress()
        assert "Resumed" in progress
        assert "paused" in progress

    def test_resume_planning_task_raises_error(self, initialized_state_manager):
        """Test resuming a planning task raises error."""
        control = ControlManager(state_manager=initialized_state_manager)

        with pytest.raises(ControlOperationNotAllowedError) as exc_info:
            control.resume()

        assert exc_info.value.current_status == "planning"

    def test_resume_success_task_raises_error(self, initialized_state_manager):
        """Test resuming a successful task raises error."""
        state = initialized_state_manager.load_state()
        state.status = "success"
        initialized_state_manager.save_state(state, validate_transition=False)

        control = ControlManager(state_manager=initialized_state_manager)

        with pytest.raises(ControlOperationNotAllowedError) as exc_info:
            control.resume()

        assert exc_info.value.current_status == "success"

    def test_resume_failed_task_raises_error(self, initialized_state_manager):
        """Test resuming a failed task raises error."""
        state = initialized_state_manager.load_state()
        state.status = "failed"
        initialized_state_manager.save_state(state, validate_transition=False)

        control = ControlManager(state_manager=initialized_state_manager)

        with pytest.raises(ControlOperationNotAllowedError):
            control.resume()

    def test_resume_no_active_task_raises_error(self, temp_dir):
        """Test resuming without active task raises error."""
        state_dir = temp_dir / ".claude-task-master"
        control = ControlManager(state_dir=state_dir)

        with pytest.raises(NoActiveTaskError) as exc_info:
            control.resume()

        assert exc_info.value.operation == "resume"


# =============================================================================
# ControlManager.stop() Tests
# =============================================================================


class TestControlManagerStop:
    """Tests for ControlManager.stop() method."""

    def test_stop_working_task(self, initialized_state_manager):
        """Test stopping a working task."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        result = control.stop()

        assert result.success is True
        assert result.operation == "stop"
        assert result.previous_status == "working"
        assert result.new_status == "stopped"
        assert "stopped successfully" in result.message

        # Verify state was updated
        state = initialized_state_manager.load_state()
        assert state.status == "stopped"

    def test_stop_planning_task(self, initialized_state_manager):
        """Test stopping a task in planning phase."""
        control = ControlManager(state_manager=initialized_state_manager)
        result = control.stop()

        assert result.success is True
        assert result.previous_status == "planning"

    def test_stop_paused_task(self, initialized_state_manager):
        """Test stopping a paused task."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "paused"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        result = control.stop()

        assert result.success is True
        assert result.previous_status == "paused"

    def test_stop_blocked_task(self, initialized_state_manager):
        """Test stopping a blocked task."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "blocked"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        result = control.stop()

        assert result.success is True
        assert result.previous_status == "blocked"

    def test_stop_with_reason(self, initialized_state_manager):
        """Test stopping with a reason."""
        control = ControlManager(state_manager=initialized_state_manager)
        result = control.stop(reason="User cancelled")

        assert result.success is True
        assert result.details is not None
        assert result.details["reason"] == "User cancelled"

        progress = initialized_state_manager.load_progress()
        assert "Stopped" in progress
        assert "User cancelled" in progress

    def test_stop_with_cleanup(self, initialized_state_manager):
        """Test stopping with cleanup."""
        control = ControlManager(state_manager=initialized_state_manager)
        result = control.stop(cleanup=True)

        assert result.success is True
        assert result.details is not None
        assert result.details["cleanup"] is True

        # Verify state was cleaned up
        assert not initialized_state_manager.exists()

    def test_stop_cleanup_logs_dropped_mailbox_count(self, initialized_state_manager, caplog):
        """stop(cleanup=True) logs and reports pending mailbox messages it drops."""
        mailbox = MailboxStorage(initialized_state_manager.state_dir)
        mailbox.add_message("update the plan")
        mailbox.add_message("also add rate limiting")

        control = ControlManager(state_manager=initialized_state_manager)
        with caplog.at_level(logging.WARNING):
            result = control.stop(cleanup=True)

        assert result.details is not None
        assert result.details["cleanup"] is True
        assert result.details["dropped_mailbox_messages"] == 2
        assert any("2 pending mailbox" in message for message in caplog.messages)
        assert not initialized_state_manager.exists()

    def test_stop_cleanup_no_mailbox_omits_dropped_count(self, initialized_state_manager):
        """No pending messages → no dropped-count key and no spurious warning."""
        control = ControlManager(state_manager=initialized_state_manager)
        result = control.stop(cleanup=True)

        assert result.details is not None
        assert result.details["cleanup"] is True
        assert "dropped_mailbox_messages" not in result.details

    def test_stop_cleanup_skipped_when_session_active(
        self, initialized_state_manager, caplog, monkeypatch
    ):
        """Cleanup is skipped (state preserved) if a live session never releases."""
        monkeypatch.setattr(control_module, "SESSION_RELEASE_TIMEOUT_SEC", 0.05)
        monkeypatch.setattr(control_module, "SESSION_RELEASE_POLL_INTERVAL_SEC", 0.01)
        monkeypatch.setattr(initialized_state_manager, "is_session_active", lambda: True)

        control = ControlManager(state_manager=initialized_state_manager)
        with caplog.at_level(logging.WARNING):
            result = control.stop(cleanup=True)

        assert result.success is True
        assert result.details is not None
        assert result.details["cleanup"] is False
        assert result.details["cleanup_skipped"] == "session still active"
        assert any("skipping cleanup" in message for message in caplog.messages)
        # State survives — never clobber a live run.
        assert initialized_state_manager.exists()

    def test_stop_cleanup_proceeds_after_session_releases(
        self, initialized_state_manager, monkeypatch
    ):
        """Cleanup runs once a still-active session releases within the timeout."""
        monkeypatch.setattr(control_module, "SESSION_RELEASE_TIMEOUT_SEC", 5.0)
        monkeypatch.setattr(control_module, "SESSION_RELEASE_POLL_INTERVAL_SEC", 0.01)

        calls = {"n": 0}

        def fake_active() -> bool:
            calls["n"] += 1
            return calls["n"] < 3  # active for the first two probes, then released

        monkeypatch.setattr(initialized_state_manager, "is_session_active", fake_active)

        control = ControlManager(state_manager=initialized_state_manager)
        result = control.stop(cleanup=True)

        assert result.details is not None
        assert result.details["cleanup"] is True
        assert calls["n"] >= 3
        assert not initialized_state_manager.exists()

    def test_wait_for_session_release_immediate_when_inactive(self, initialized_state_manager):
        """Helper returns True without waiting when no other session is active."""
        control = ControlManager(state_manager=initialized_state_manager)
        assert control._wait_for_session_release() is True

    def test_stop_success_task_raises_error(self, initialized_state_manager):
        """Test stopping a successful task raises error."""
        state = initialized_state_manager.load_state()
        state.status = "success"
        initialized_state_manager.save_state(state, validate_transition=False)

        control = ControlManager(state_manager=initialized_state_manager)

        with pytest.raises(ControlOperationNotAllowedError):
            control.stop()

    def test_stop_failed_task_raises_error(self, initialized_state_manager):
        """Test stopping an already failed task raises error."""
        state = initialized_state_manager.load_state()
        state.status = "failed"
        initialized_state_manager.save_state(state, validate_transition=False)

        control = ControlManager(state_manager=initialized_state_manager)

        with pytest.raises(ControlOperationNotAllowedError):
            control.stop()

    def test_stop_no_active_task_raises_error(self, temp_dir):
        """Test stopping without active task raises error."""
        state_dir = temp_dir / ".claude-task-master"
        control = ControlManager(state_dir=state_dir)

        with pytest.raises(NoActiveTaskError):
            control.stop()


# =============================================================================
# ControlManager.update_config() Tests
# =============================================================================


class TestControlManagerUpdateConfig:
    """Tests for ControlManager.update_config() method."""

    def test_update_single_option(self, initialized_state_manager):
        """Test updating a single configuration option."""
        control = ControlManager(state_manager=initialized_state_manager)
        result = control.update_config(auto_merge=False)

        assert result.success is True
        assert result.operation == "update_config"
        assert result.details is not None
        assert result.details["updated"] == {"auto_merge": False}

        state = initialized_state_manager.load_state()
        assert state.options.auto_merge is False

    def test_update_multiple_options(self, initialized_state_manager):
        """Test updating multiple configuration options."""
        control = ControlManager(state_manager=initialized_state_manager)
        # Note: sample_task_options sets max_sessions=10 and auto_merge=True
        # So we use max_sessions=20 to ensure a change is detected
        result = control.update_config(
            auto_merge=False,
            max_sessions=20,
            pause_on_pr=True,
        )

        assert result.success is True
        assert result.details is not None
        assert "auto_merge" in result.details["updated"]
        assert "max_sessions" in result.details["updated"]
        assert "pause_on_pr" in result.details["updated"]

        state = initialized_state_manager.load_state()
        assert state.options.auto_merge is False
        assert state.options.max_sessions == 20
        assert state.options.pause_on_pr is True

    def test_update_no_changes(self, initialized_state_manager):
        """Test update with no actual changes."""
        control = ControlManager(state_manager=initialized_state_manager)

        # First update
        control.update_config(auto_merge=True)  # default value

        # Same value again
        result = control.update_config(auto_merge=True)

        assert result.success is True
        assert result.details is not None
        assert result.details["updated"] == {}
        assert "No configuration changes" in result.message

    def test_update_log_level(self, initialized_state_manager):
        """Test updating log level option."""
        control = ControlManager(state_manager=initialized_state_manager)
        result = control.update_config(log_level="verbose")

        assert result.success is True
        assert result.details is not None
        assert result.details["updated"] == {"log_level": "verbose"}

        state = initialized_state_manager.load_state()
        assert state.options.log_level == "verbose"

    def test_update_invalid_option_raises_error(self, initialized_state_manager):
        """Test updating with invalid option raises error."""
        control = ControlManager(state_manager=initialized_state_manager)

        with pytest.raises(ValueError) as exc_info:
            control.update_config(invalid_option=True)

        assert "invalid_option" in str(exc_info.value)
        assert "Invalid configuration options" in str(exc_info.value)

    def test_update_multiple_invalid_options(self, initialized_state_manager):
        """Test updating with multiple invalid options."""
        control = ControlManager(state_manager=initialized_state_manager)

        with pytest.raises(ValueError) as exc_info:
            control.update_config(foo="bar", baz=123)

        assert "foo" in str(exc_info.value) or "baz" in str(exc_info.value)

    def test_update_preserves_existing_values(self, initialized_state_manager):
        """Test that update preserves unspecified option values."""
        # Set initial values
        state = initialized_state_manager.load_state()
        state.options.max_sessions = 5
        state.options.pause_on_pr = True
        initialized_state_manager.save_state(state, validate_transition=False)

        control = ControlManager(state_manager=initialized_state_manager)
        control.update_config(auto_merge=False)

        state = initialized_state_manager.load_state()
        assert state.options.auto_merge is False
        assert state.options.max_sessions == 5
        assert state.options.pause_on_pr is True

    def test_update_no_active_task_raises_error(self, temp_dir):
        """Test updating config without active task raises error."""
        state_dir = temp_dir / ".claude-task-master"
        control = ControlManager(state_dir=state_dir)

        with pytest.raises(NoActiveTaskError):
            control.update_config(auto_merge=False)

    def test_update_returns_current_config(self, initialized_state_manager):
        """Test that update returns current configuration."""
        control = ControlManager(state_manager=initialized_state_manager)
        result = control.update_config(max_sessions=15)

        assert result.details is not None
        assert "current" in result.details
        assert result.details["current"]["max_sessions"] == 15


# =============================================================================
# ControlManager.get_status() Tests
# =============================================================================


class TestControlManagerGetStatus:
    """Tests for ControlManager.get_status() method."""

    def test_get_status_basic(self, initialized_state_manager):
        """Test getting basic status."""
        control = ControlManager(state_manager=initialized_state_manager)
        result = control.get_status()

        assert result.success is True
        assert result.operation == "get_status"
        assert result.previous_status == "planning"
        assert result.new_status == "planning"
        assert "planning" in result.message

    def test_get_status_includes_details(self, initialized_state_manager):
        """Test status includes detailed information."""
        # Set up task with plan
        initialized_state_manager.save_plan("- [ ] Task 1\n- [ ] Task 2")

        control = ControlManager(state_manager=initialized_state_manager)
        result = control.get_status()

        assert result.details is not None
        assert "status" in result.details
        assert "session_count" in result.details
        assert "current_task_index" in result.details
        assert "options" in result.details
        assert "tasks" in result.details

    def test_get_status_shows_task_progress(self, initialized_state_manager):
        """Test status shows task progress."""
        initialized_state_manager.save_plan(
            "- [x] Task 1\n- [x] Task 2\n- [ ] Task 3\n- [ ] Task 4"
        )
        state = initialized_state_manager.load_state()
        state.current_task_index = 2
        initialized_state_manager.save_state(state, validate_transition=False)

        control = ControlManager(state_manager=initialized_state_manager)
        result = control.get_status()

        assert result.details is not None
        assert result.details["tasks"]["completed"] == 2
        assert result.details["tasks"]["total"] == 4
        assert result.details["tasks"]["progress"] == "2/4"

    def test_get_status_no_active_task_raises_error(self, temp_dir):
        """Test getting status without active task raises error."""
        state_dir = temp_dir / ".claude-task-master"
        control = ControlManager(state_dir=state_dir)

        with pytest.raises(NoActiveTaskError):
            control.get_status()


# =============================================================================
# ControlManager Helper Method Tests
# =============================================================================


class TestControlManagerHelpers:
    """Tests for ControlManager helper methods."""

    def test_can_pause_working(self, initialized_state_manager):
        """Test can_pause returns True for working task."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        assert control.can_pause() is True

    def test_can_pause_planning(self, initialized_state_manager):
        """Test can_pause returns True for planning task."""
        control = ControlManager(state_manager=initialized_state_manager)
        assert control.can_pause() is True

    def test_can_pause_paused(self, initialized_state_manager):
        """Test can_pause returns False for paused task."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "paused"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        assert control.can_pause() is False

    def test_can_pause_no_task(self, temp_dir):
        """Test can_pause returns False when no task exists."""
        state_dir = temp_dir / ".claude-task-master"
        control = ControlManager(state_dir=state_dir)
        assert control.can_pause() is False

    def test_can_resume_paused(self, initialized_state_manager):
        """Test can_resume returns True for paused task."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "paused"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        assert control.can_resume() is True

    def test_can_resume_blocked(self, initialized_state_manager):
        """Test can_resume returns True for blocked task."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "blocked"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        assert control.can_resume() is True

    def test_can_resume_planning(self, initialized_state_manager):
        """Test can_resume returns False for planning task."""
        control = ControlManager(state_manager=initialized_state_manager)
        assert control.can_resume() is False

    def test_can_resume_no_task(self, temp_dir):
        """Test can_resume returns False when no task exists."""
        state_dir = temp_dir / ".claude-task-master"
        control = ControlManager(state_dir=state_dir)
        assert control.can_resume() is False

    def test_can_stop_working(self, initialized_state_manager):
        """Test can_stop returns True for working task."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        control = ControlManager(state_manager=initialized_state_manager)
        assert control.can_stop() is True

    def test_can_stop_planning(self, initialized_state_manager):
        """Test can_stop returns True for planning task."""
        control = ControlManager(state_manager=initialized_state_manager)
        assert control.can_stop() is True

    def test_can_stop_success(self, initialized_state_manager):
        """Test can_stop returns False for success task."""
        state = initialized_state_manager.load_state()
        state.status = "success"
        initialized_state_manager.save_state(state, validate_transition=False)

        control = ControlManager(state_manager=initialized_state_manager)
        assert control.can_stop() is False

    def test_can_stop_no_task(self, temp_dir):
        """Test can_stop returns False when no task exists."""
        state_dir = temp_dir / ".claude-task-master"
        control = ControlManager(state_dir=state_dir)
        assert control.can_stop() is False


# =============================================================================
# Integration Tests
# =============================================================================


class TestControlManagerIntegration:
    """Integration tests for ControlManager."""

    def test_full_workflow_pause_resume(self, initialized_state_manager):
        """Test full pause and resume workflow."""
        control = ControlManager(state_manager=initialized_state_manager)

        # Start working
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        # Pause
        result = control.pause(reason="Taking a break")
        assert result.success is True
        assert control.can_resume() is True

        # Resume
        result = control.resume()
        assert result.success is True
        assert control.can_pause() is True

        # Verify final state
        state = initialized_state_manager.load_state()
        assert state.status == "working"

    def test_config_update_persists_across_operations(self, initialized_state_manager):
        """Test config updates persist through pause/resume."""
        control = ControlManager(state_manager=initialized_state_manager)

        # Update config
        control.update_config(max_sessions=20, auto_merge=False)

        # Start working
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        # Pause and resume
        control.pause()
        control.resume()

        # Verify config persisted
        state = initialized_state_manager.load_state()
        assert state.options.max_sessions == 20
        assert state.options.auto_merge is False

    def test_status_after_multiple_operations(self, initialized_state_manager):
        """Test status reflects multiple operations."""
        initialized_state_manager.save_plan("- [ ] Task 1")
        control = ControlManager(state_manager=initialized_state_manager)

        # Do several operations
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        control.pause(reason="Break 1")
        control.resume()
        control.pause(reason="Break 2")

        # Check status
        result = control.get_status()
        assert result.details is not None
        assert result.details["status"] == "paused"

        # Check progress has both breaks logged
        progress = initialized_state_manager.load_progress()
        assert "Break 1" in progress
        assert "Break 2" in progress


# =============================================================================
# Cross-process reload-merge-save Tests
# =============================================================================


class TestControlManagerCrossProcessSaves:
    """A control write from one process must survive the orchestrator's next
    save from another process.

    The orchestrator holds one long-lived, stale in-memory TaskState and saves
    it dozens of times per run. A control operation from a *different* process
    (the REST server / MCP / a second CLI) writes an authoritative status or
    config to the same state dir. Simulated here with a second StateManager: the
    orchestrator's next merged save must not clobber the control write.
    """

    @staticmethod
    def _start_working(mgr: StateManager) -> TaskState:
        """Move the run to working and return the orchestrator's stale copy."""
        state = mgr.load_state()
        state.status = "working"
        mgr.save_state(state)
        return mgr.load_state()

    def test_external_stop_survives_orchestrator_save(self, initialized_state_manager):
        """ControlManager.stop() in one process is not clobbered by the
        orchestrator's next merged save in another."""
        orch_mgr = initialized_state_manager
        orch_state = self._start_working(orch_mgr)

        # A separate process (own StateManager on the same dir) stops the run.
        control = ControlManager(state_manager=StateManager(orch_mgr.state_dir))
        control.stop(reason="user requested")

        # The orchestrator's next routine save must preserve the stop.
        orch_mgr.save_state_merged(orch_state)
        assert orch_mgr.load_state().status == "stopped"

    def test_external_pause_survives_orchestrator_save(self, initialized_state_manager):
        """ControlManager.pause() in one process survives the orchestrator's
        next merged save in another."""
        orch_mgr = initialized_state_manager
        orch_state = self._start_working(orch_mgr)

        control = ControlManager(state_manager=StateManager(orch_mgr.state_dir))
        control.pause(reason="user requested")

        orch_mgr.save_state_merged(orch_state)
        assert orch_mgr.load_state().status == "paused"

    def test_config_patch_survives_orchestrator_save(self, initialized_state_manager):
        """update_config (PATCH /config) in one process survives — and is
        adopted by — the orchestrator's next merged save in another."""
        orch_mgr = initialized_state_manager
        orch_state = self._start_working(orch_mgr)
        assert orch_state.options.max_sessions == 10

        control = ControlManager(state_manager=StateManager(orch_mgr.state_dir))
        control.update_config(max_sessions=99, auto_merge=False)

        orch_mgr.save_state_merged(orch_state)
        reloaded = orch_mgr.load_state()
        assert reloaded.options.max_sessions == 99
        assert reloaded.options.auto_merge is False
        # Adopted in place so the running orchestrator uses the new options.
        assert orch_state.options.max_sessions == 99
        assert orch_state.options.auto_merge is False

    def test_resume_after_external_stop_then_orchestrator_save(self, initialized_state_manager):
        """An explicit resume clears the stop; the orchestrator's merged saves
        then persist working progress normally."""
        orch_mgr = initialized_state_manager
        orch_state = self._start_working(orch_mgr)

        control = ControlManager(state_manager=StateManager(orch_mgr.state_dir))
        control.stop(reason="pause the world")
        # Merged save keeps the stop (no clobber).
        orch_mgr.save_state_merged(orch_state)
        assert orch_mgr.load_state().status == "stopped"

        # Deliberate resume from the control plane.
        control.resume()

        # The orchestrator reloads and continues; merged progress saves persist.
        resumed_state = orch_mgr.load_state()
        assert resumed_state.status == "working"
        resumed_state.session_count += 1
        orch_mgr.save_state_merged(resumed_state)
        assert orch_mgr.load_state().status == "working"


# =============================================================================
# Cross-process ControlChannel Tests
# =============================================================================


class TestControlChannelCrossProcess:
    """Cross-process control channel: stop/pause written by one process, polled
    by the orchestrator in *one* cycle.

    The orchestrator reads ``control.json`` once per work-loop iteration. These
    tests confirm that ControlManager writes are durable and immediately visible
    to a separate ControlChannel reader — i.e., the orchestrator will honour the
    signal in the very first poll after the write.
    """

    def test_stop_honored_in_one_cycle(self, initialized_state_manager):
        """stop() writes control.json; a single channel.read() returns 'stop'.

        Simulates the orchestrator's per-cycle poll: the stop is visible in
        exactly one read — no multi-cycle delay.
        """
        control = ControlManager(state_manager=initialized_state_manager)
        control.stop(reason="user halt")

        # Simulate the orchestrator's poll: one read() call, different channel object.
        channel = ControlChannel(initialized_state_manager.state_dir)
        req = channel.read()
        assert req is not None
        assert req.action == "stop"
        assert req.reason == "user halt"

    def test_pause_honored_in_one_cycle(self, initialized_state_manager):
        """pause() writes control.json; a single channel.read() returns 'pause'.

        The orchestrator's first poll after a cross-process pause picks it up.
        """
        control = ControlManager(state_manager=initialized_state_manager)
        control.pause(reason="review break")

        channel = ControlChannel(initialized_state_manager.state_dir)
        req = channel.read()
        assert req is not None
        assert req.action == "pause"
        assert req.reason == "review break"

    def test_resume_clears_channel(self, initialized_state_manager):
        """resume() clears any stale stop/pause so the fresh run isn't immediately halted."""
        # Write a stop to the channel first.
        control = ControlManager(state_manager=initialized_state_manager)
        control.stop(reason="old stop")

        # Transition to stopped so resume() is allowed.
        state = initialized_state_manager.load_state()
        assert state.status == "stopped"

        # Resume: should clear the channel.
        control.resume()

        channel = ControlChannel(initialized_state_manager.state_dir)
        assert channel.read() is None

    def test_stop_cleanup_no_race_with_second_state_manager(
        self, initialized_state_manager, monkeypatch, caplog
    ):
        """stop(cleanup=True) skips cleanup when a *second* StateManager sees a live session.

        Simulates the real cross-process scenario: the orchestrator runs in one
        process (holds the session lock) while the REST server calls
        stop(cleanup=True) with its own StateManager pointing to the same state
        directory.  Cleanup must be skipped to avoid clobbering the live run.
        """
        # The CONTROL process has its own StateManager (second instance, same dir).
        ctrl_mgr = StateManager(initialized_state_manager.state_dir)
        monkeypatch.setattr(control_module, "SESSION_RELEASE_TIMEOUT_SEC", 0.05)
        monkeypatch.setattr(control_module, "SESSION_RELEASE_POLL_INTERVAL_SEC", 0.01)
        # Simulate the orchestrator's session still being active from ctrl_mgr's perspective.
        monkeypatch.setattr(ctrl_mgr, "is_session_active", lambda: True)

        control = ControlManager(state_manager=ctrl_mgr)
        with caplog.at_level(logging.WARNING):
            result = control.stop(cleanup=True)

        assert result.success is True
        assert result.details is not None
        assert result.details["cleanup"] is False
        assert result.details["cleanup_skipped"] == "session still active"
        assert any("skipping cleanup" in msg for msg in caplog.messages)
        # The original state dir must be untouched — orchestrator is still live.
        assert initialized_state_manager.exists()

    def test_stop_cleanup_proceeds_with_second_state_manager_after_release(
        self, initialized_state_manager, monkeypatch
    ):
        """stop(cleanup=True) proceeds once the live session releases, using a second SM.

        After the orchestrator finishes (session lock released), the control
        process's cleanup runs normally.
        """
        ctrl_mgr = StateManager(initialized_state_manager.state_dir)
        monkeypatch.setattr(control_module, "SESSION_RELEASE_TIMEOUT_SEC", 5.0)
        monkeypatch.setattr(control_module, "SESSION_RELEASE_POLL_INTERVAL_SEC", 0.01)

        calls: dict[str, int] = {"n": 0}

        def fake_active() -> bool:
            """Active for the first two probes, then releases."""
            calls["n"] += 1
            return calls["n"] < 3

        monkeypatch.setattr(ctrl_mgr, "is_session_active", fake_active)

        control = ControlManager(state_manager=ctrl_mgr)
        result = control.stop(cleanup=True)

        assert result.details is not None
        assert result.details["cleanup"] is True
        assert calls["n"] >= 3
        # State dir cleaned up once the session released.
        assert not ctrl_mgr.exists()
