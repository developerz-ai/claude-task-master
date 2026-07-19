"""Unit tests for the transport-neutral :class:`TaskService`.

These exercise the service directly against a real ``StateManager`` on a
temporary directory (no transport), asserting the ``ServiceOutcome`` each
operation returns. Both the REST and MCP adapters translate those outcomes, so
covering them here is what keeps the two surfaces in lock-step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from claude_task_master.core.services.results import ServiceOutcome
from claude_task_master.core.services.task_service import TaskService
from claude_task_master.core.state import TaskOptions

if TYPE_CHECKING:
    from typing import Any

    from claude_task_master.core.state import StateManager


class TestReadOperationsWithoutTask:
    """Every read operation reports NOT_FOUND when no task exists."""

    @pytest.mark.parametrize(
        "method",
        [
            "get_status",
            "get_plan",
            "get_logs",
            "get_progress",
            "get_context",
            "list_tasks",
            "delete_coding_style",
        ],
    )
    def test_returns_not_found(self, state_manager: StateManager, method: str) -> None:
        """A read on an empty state dir maps to NOT_FOUND (transport -> 404)."""
        result = getattr(TaskService(state_manager), method)()
        assert result.outcome is ServiceOutcome.NOT_FOUND
        assert result.success is False


class TestGetStatus:
    """Loading task status and goal."""

    def test_ok_returns_state_and_goal(
        self, initialized_state_manager: StateManager, sample_goal: str
    ) -> None:
        """A live task returns OK carrying the loaded state and goal."""
        result = TaskService(initialized_state_manager).get_status()
        assert result.outcome is ServiceOutcome.OK
        assert result.data["goal"] == sample_goal
        assert result.data["state"].status == "planning"

    def test_load_failure_maps_to_error(
        self, initialized_state_manager: StateManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unexpected load failure maps to ERROR (transport -> 500)."""
        monkeypatch.setattr(
            initialized_state_manager,
            "load_state",
            MagicMock(side_effect=RuntimeError("boom")),
        )
        result = TaskService(initialized_state_manager).get_status()
        assert result.outcome is ServiceOutcome.ERROR
        assert result.error == "boom"


class TestGetPlan:
    """Loading the plan markdown."""

    def test_no_plan_yet_is_not_found_with_message(
        self, initialized_state_manager: StateManager
    ) -> None:
        """A task with no plan returns NOT_FOUND tagged ``"No plan found"``."""
        result = TaskService(initialized_state_manager).get_plan()
        assert result.outcome is ServiceOutcome.NOT_FOUND
        assert result.message == "No plan found"

    def test_ok_returns_plan(
        self, initialized_state_manager: StateManager, sample_plan: str
    ) -> None:
        """A saved plan is returned verbatim as ``data["plan"]``."""
        initialized_state_manager.save_plan(sample_plan)
        result = TaskService(initialized_state_manager).get_plan()
        assert result.outcome is ServiceOutcome.OK
        assert result.data["plan"] == sample_plan


class TestGetLogs:
    """Reading trailing log lines."""

    def test_tail_below_one_is_invalid(self, state_manager: StateManager) -> None:
        """``tail < 1`` is rejected as INVALID before any state access."""
        result = TaskService(state_manager).get_logs(tail=0)
        assert result.outcome is ServiceOutcome.INVALID
        assert result.error == "tail must be >= 1"

    def test_no_log_file_is_not_found_with_message(
        self, initialized_state_manager: StateManager
    ) -> None:
        """A task that has not logged yet returns NOT_FOUND ``"No log file found"``."""
        result = TaskService(initialized_state_manager).get_logs()
        assert result.outcome is ServiceOutcome.NOT_FOUND
        assert result.message == "No log file found"

    def test_ok_returns_only_the_trailing_window(
        self, initialized_state_manager: StateManager
    ) -> None:
        """``get_logs`` returns exactly the last ``tail`` lines of the run log."""
        state = initialized_state_manager.load_state()
        log_file = initialized_state_manager.get_log_file(state.run_id)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("".join(f"line-{i}\n" for i in range(250)))

        result = TaskService(initialized_state_manager).get_logs(tail=10)
        assert result.outcome is ServiceOutcome.OK
        assert result.data["log_content"] == "".join(f"line-{i}\n" for i in range(240, 250))
        assert result.data["log_file"] == str(log_file)


class TestGetProgressAndContext:
    """Loading progress and accumulated context."""

    def test_progress_absent_is_ok_with_none(self, initialized_state_manager: StateManager) -> None:
        """No recorded progress returns OK with ``progress=None`` and a message."""
        result = TaskService(initialized_state_manager).get_progress()
        assert result.outcome is ServiceOutcome.OK
        assert result.data["progress"] is None
        assert result.message == "No progress recorded yet"

    def test_progress_present_is_returned(self, initialized_state_manager: StateManager) -> None:
        """Saved progress is returned as ``data["progress"]``."""
        initialized_state_manager.save_progress("halfway there")
        result = TaskService(initialized_state_manager).get_progress()
        assert result.outcome is ServiceOutcome.OK
        assert result.data["progress"] == "halfway there"

    def test_context_returns_raw_value(self, initialized_state_manager: StateManager) -> None:
        """``get_context`` returns the raw stored value untouched."""
        initialized_state_manager.save_context("learned X")
        result = TaskService(initialized_state_manager).get_context()
        assert result.outcome is ServiceOutcome.OK
        assert result.data["context"] == "learned X"


class TestListTasks:
    """Parsing the plan into a task list with counts."""

    def test_no_plan_is_not_found(self, initialized_state_manager: StateManager) -> None:
        """Listing with no plan maps to NOT_FOUND."""
        result = TaskService(initialized_state_manager).list_tasks()
        assert result.outcome is ServiceOutcome.NOT_FOUND
        assert result.message == "No plan found"

    def test_ok_counts_tasks_and_completion(
        self, initialized_state_manager: StateManager, sample_plan: str
    ) -> None:
        """The parsed list reports total, completed count and current index."""
        initialized_state_manager.save_plan(sample_plan)
        result = TaskService(initialized_state_manager).list_tasks()
        assert result.outcome is ServiceOutcome.OK
        assert result.data["total"] == 4
        assert result.data["completed"] == 1
        assert result.data["current_index"] == 0
        assert len(result.data["tasks"]) == 4


class TestInitTask:
    """Initializing a new task."""

    def test_ok_creates_state(
        self,
        state_manager: StateManager,
        sample_goal: str,
        sample_task_options: dict[str, Any],
    ) -> None:
        """Init on an empty dir succeeds and persists state."""
        options = TaskOptions(**sample_task_options)
        result = TaskService(state_manager).init_task(sample_goal, "sonnet", options)
        assert result.outcome is ServiceOutcome.OK
        assert result.data["state"].status == "planning"
        assert state_manager.exists()
        assert state_manager.load_goal() == sample_goal

    def test_existing_task_is_conflict(
        self,
        initialized_state_manager: StateManager,
        sample_goal: str,
        sample_task_options: dict[str, Any],
    ) -> None:
        """Init when a task already exists maps to CONFLICT (transport -> 400)."""
        options = TaskOptions(**sample_task_options)
        result = TaskService(initialized_state_manager).init_task(sample_goal, "sonnet", options)
        assert result.outcome is ServiceOutcome.CONFLICT


class TestClean:
    """Removing the state directory."""

    def test_nothing_to_clean_is_not_found(self, state_manager: StateManager) -> None:
        """Cleaning an empty dir maps to NOT_FOUND."""
        assert TaskService(state_manager).clean().outcome is ServiceOutcome.NOT_FOUND

    def test_active_session_without_force_is_invalid(
        self, initialized_state_manager: StateManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An active session blocks an unforced clean (INVALID); the dir survives."""
        monkeypatch.setattr(initialized_state_manager, "is_session_active", lambda: True)
        result = TaskService(initialized_state_manager).clean(force=False)
        assert result.outcome is ServiceOutcome.INVALID
        assert initialized_state_manager.exists()

    def test_force_removes_directory(self, initialized_state_manager: StateManager) -> None:
        """``force=True`` releases the lock and removes the tree."""
        result = TaskService(initialized_state_manager).clean(force=True)
        assert result.outcome is ServiceOutcome.OK
        assert result.data["files_removed"] is True
        assert not initialized_state_manager.exists()


class TestControlOperations:
    """Pause / stop / resume outcome mapping."""

    def test_pause_no_task_is_not_found(self, state_manager: StateManager) -> None:
        """Pausing with no task maps NoActiveTaskError -> NOT_FOUND."""
        assert TaskService(state_manager).pause().outcome is ServiceOutcome.NOT_FOUND

    def test_pause_planning_task_is_ok(self, initialized_state_manager: StateManager) -> None:
        """Pausing a planning task succeeds and carries the ControlResult."""
        result = TaskService(initialized_state_manager).pause(reason="lunch")
        assert result.outcome is ServiceOutcome.OK
        assert result.data["result"].new_status == "paused"
        assert result.message == result.data["result"].message

    def test_pause_terminal_task_is_invalid_with_previous_status(
        self, initialized_state_manager: StateManager
    ) -> None:
        """A disallowed transition maps to INVALID and reports the prior status."""
        state = initialized_state_manager.load_state()
        state.status = "success"
        initialized_state_manager.save_state(state, validate_transition=False)

        result = TaskService(initialized_state_manager).pause()
        assert result.outcome is ServiceOutcome.INVALID
        assert result.data["previous_status"] == "success"

    def test_resume_paused_task_is_ok(self, initialized_state_manager: StateManager) -> None:
        """Resuming a paused task succeeds."""
        service = TaskService(initialized_state_manager)
        service.pause()
        result = service.resume()
        assert result.outcome is ServiceOutcome.OK

    def test_stop_task_is_ok(self, initialized_state_manager: StateManager) -> None:
        """Stopping a live task succeeds without cleanup."""
        result = TaskService(initialized_state_manager).stop(reason="done", cleanup=False)
        assert result.outcome is ServiceOutcome.OK

    def test_control_generic_failure_maps_to_error(
        self, initialized_state_manager: StateManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unexpected control error maps to ERROR, not INVALID/NOT_FOUND."""
        service = TaskService(initialized_state_manager)
        broken = MagicMock()
        broken.pause.side_effect = RuntimeError("kaboom")
        monkeypatch.setattr(service, "_control_manager", lambda: broken)
        result = service.pause()
        assert result.outcome is ServiceOutcome.ERROR
        assert result.error == "kaboom"


class TestUpdateConfig:
    """Runtime option updates."""

    def test_no_options_is_invalid(self, initialized_state_manager: StateManager) -> None:
        """An empty update is rejected before touching the control manager."""
        result = TaskService(initialized_state_manager).update_config()
        assert result.outcome is ServiceOutcome.INVALID
        assert result.message == "No configuration options provided"

    def test_valid_update_is_ok(self, initialized_state_manager: StateManager) -> None:
        """A valid option update succeeds and echoes the control message."""
        result = TaskService(initialized_state_manager).update_config(auto_merge=False)
        assert result.outcome is ServiceOutcome.OK
        assert result.message == result.data["result"].message

    def test_unknown_option_is_invalid(self, initialized_state_manager: StateManager) -> None:
        """An unknown option raises ValueError -> INVALID."""
        result = TaskService(initialized_state_manager).update_config(nonsense=True)
        assert result.outcome is ServiceOutcome.INVALID

    def test_no_task_is_not_found(self, state_manager: StateManager) -> None:
        """Updating config with no task maps NoActiveTaskError -> NOT_FOUND."""
        result = TaskService(state_manager).update_config(auto_merge=False)
        assert result.outcome is ServiceOutcome.NOT_FOUND
