"""Tests for PR state management in StateManager.

This module tests PR state tracking (current_pr field in TaskState)
and PR-related options (pause_on_pr, pr_per_task in TaskOptions).

For PR context storage tests (comments, CI failures, threads), see test_state_pr_context.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from claude_task_master.core.state import StateManager, TaskOptions, TaskState

# Note: state_manager and initialized_state_manager fixtures are provided
# by the root conftest.py


# =============================================================================
# TaskOptions PR-related Tests
# =============================================================================


class TestTaskOptionsPRFields:
    """Tests for PR-related fields in TaskOptions."""

    def test_pause_on_pr_default(self) -> None:
        """Test pause_on_pr defaults to False."""
        options = TaskOptions()
        assert options.pause_on_pr is False

    def test_pause_on_pr_enabled(self) -> None:
        """Test pause_on_pr can be enabled."""
        options = TaskOptions(pause_on_pr=True)
        assert options.pause_on_pr is True

    def test_pr_per_task_default(self) -> None:
        """Test pr_per_task defaults to False."""
        options = TaskOptions()
        assert options.pr_per_task is False

    def test_pr_per_task_enabled(self) -> None:
        """Test pr_per_task can be enabled."""
        options = TaskOptions(pr_per_task=True)
        assert options.pr_per_task is True

    def test_both_pr_options_enabled(self) -> None:
        """Test both pause_on_pr and pr_per_task can be enabled."""
        options = TaskOptions(pause_on_pr=True, pr_per_task=True)
        assert options.pause_on_pr is True
        assert options.pr_per_task is True

    def test_pr_options_in_model_dump(self) -> None:
        """Test PR options appear in model dump."""
        options = TaskOptions(pause_on_pr=True, pr_per_task=True)
        dump = options.model_dump()
        assert dump["pause_on_pr"] is True
        assert dump["pr_per_task"] is True

    def test_pr_options_preserve_other_defaults(self) -> None:
        """Test setting PR options doesn't affect other defaults."""
        options = TaskOptions(pause_on_pr=True)
        assert options.auto_merge is True  # Default preserved
        assert options.max_sessions is None  # Default preserved


# =============================================================================
# TaskState current_pr Tests
# =============================================================================


class TestTaskStateCurrentPR:
    """Tests for current_pr field in TaskState."""

    def _make_state(self, **kwargs: Any) -> TaskState:
        """Helper to create a TaskState with defaults."""
        defaults: dict[str, Any] = {
            "status": "working",
            "current_task_index": 0,
            "session_count": 0,
            "current_pr": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "run_id": "test-run",
            "model": "sonnet",
            "options": TaskOptions(),
        }
        defaults.update(kwargs)
        return TaskState(**defaults)

    def test_current_pr_default_none(self) -> None:
        """Test current_pr defaults to None."""
        state = self._make_state()
        assert state.current_pr is None

    def test_current_pr_set_value(self) -> None:
        """Test current_pr can be set to a PR number."""
        state = self._make_state(current_pr=123)
        assert state.current_pr == 123

    def test_current_pr_in_model_dump(self) -> None:
        """Test current_pr appears in model dump."""
        state = self._make_state(current_pr=456)
        dump = state.model_dump()
        assert dump["current_pr"] == 456

    def test_current_pr_none_in_model_dump(self) -> None:
        """Test current_pr=None appears in model dump."""
        state = self._make_state(current_pr=None)
        dump = state.model_dump()
        assert dump["current_pr"] is None

    def test_current_pr_large_number(self) -> None:
        """Test current_pr handles large PR numbers."""
        state = self._make_state(current_pr=99999)
        assert state.current_pr == 99999

    def test_current_pr_with_blocked_status(self) -> None:
        """Test current_pr with blocked status (common use case)."""
        state = self._make_state(status="blocked", current_pr=789)
        assert state.status == "blocked"
        assert state.current_pr == 789


# =============================================================================
# StateManager PR State Persistence Tests
# =============================================================================


class TestStateManagerPRPersistence:
    """Tests for PR state persistence via StateManager."""

    def test_save_load_state_with_pr(self, initialized_state_manager: StateManager) -> None:
        """Test PR number is preserved through save/load cycle."""
        # Set current_pr on the state
        state = initialized_state_manager.load_state()
        assert state is not None
        state.current_pr = 123
        initialized_state_manager.save_state(state)

        # Load and verify
        loaded_state = initialized_state_manager.load_state()
        assert loaded_state is not None
        assert loaded_state.current_pr == 123

    def test_save_load_state_pr_none(self, initialized_state_manager: StateManager) -> None:
        """Test None PR is preserved through save/load cycle."""
        state = initialized_state_manager.load_state()
        assert state is not None
        state.current_pr = None
        initialized_state_manager.save_state(state)

        loaded_state = initialized_state_manager.load_state()
        assert loaded_state is not None
        assert loaded_state.current_pr is None

    def test_pr_state_survives_update(self, initialized_state_manager: StateManager) -> None:
        """Test PR state survives other state updates."""
        state = initialized_state_manager.load_state()
        assert state is not None
        state.current_pr = 456
        state.session_count = 5
        initialized_state_manager.save_state(state)

        # Update other fields
        state = initialized_state_manager.load_state()
        assert state is not None
        state.current_task_index = 3
        initialized_state_manager.save_state(state)

        # PR should still be there
        loaded_state = initialized_state_manager.load_state()
        assert loaded_state is not None
        assert loaded_state.current_pr == 456
        assert loaded_state.current_task_index == 3

    def test_pr_state_cleared(self, initialized_state_manager: StateManager) -> None:
        """Test PR state can be cleared."""
        state = initialized_state_manager.load_state()
        assert state is not None
        state.current_pr = 789
        initialized_state_manager.save_state(state)

        # Clear PR
        state = initialized_state_manager.load_state()
        assert state is not None
        state.current_pr = None
        initialized_state_manager.save_state(state)

        # Verify cleared
        loaded_state = initialized_state_manager.load_state()
        assert loaded_state is not None
        assert loaded_state.current_pr is None


# =============================================================================
# PR Options Persistence Tests
# =============================================================================


class TestPROptionsPersistence:
    """Tests for PR options persistence via StateManager."""

    def test_pause_on_pr_persisted(self, state_manager: StateManager) -> None:
        """Test pause_on_pr option is persisted."""
        options = TaskOptions(pause_on_pr=True)
        state_manager.initialize(
            goal="Test goal",
            options=options,
            model="sonnet",
        )

        loaded_state = state_manager.load_state()
        assert loaded_state is not None
        assert loaded_state.options.pause_on_pr is True

    def test_pr_per_task_persisted(self, state_manager: StateManager) -> None:
        """Test pr_per_task option is persisted."""
        options = TaskOptions(pr_per_task=True)
        state_manager.initialize(
            goal="Test goal",
            options=options,
            model="sonnet",
        )

        loaded_state = state_manager.load_state()
        assert loaded_state is not None
        assert loaded_state.options.pr_per_task is True

    def test_all_pr_options_persisted(self, state_manager: StateManager) -> None:
        """Test all PR options are persisted together."""
        options = TaskOptions(pause_on_pr=True, pr_per_task=True)
        state_manager.initialize(
            goal="Test goal",
            options=options,
            model="sonnet",
        )

        loaded_state = state_manager.load_state()
        assert loaded_state is not None
        assert loaded_state.options.pause_on_pr is True
        assert loaded_state.options.pr_per_task is True

    def test_default_pr_options_persisted(self, state_manager: StateManager) -> None:
        """Test default PR options are persisted correctly."""
        options = TaskOptions()  # All defaults
        state_manager.initialize(
            goal="Test goal",
            options=options,
            model="sonnet",
        )

        loaded_state = state_manager.load_state()
        assert loaded_state is not None
        assert loaded_state.options.pause_on_pr is False
        assert loaded_state.options.pr_per_task is False


# =============================================================================
# PR State Transition Tests
# =============================================================================


class TestPRStateTransitions:
    """Tests for PR state transitions in workflow.

    Valid transitions:
    - planning -> working, failed, paused
    - working -> blocked, success, failed, working, paused
    - blocked -> working, failed, paused
    """

    def test_transition_to_blocked_with_pr(self, initialized_state_manager: StateManager) -> None:
        """Test transitioning to blocked status with a PR.

        Path: planning -> working -> blocked (with PR)
        """
        state = initialized_state_manager.load_state()
        assert state is not None

        # First transition: planning -> working
        state.status = "working"
        initialized_state_manager.save_state(state)

        # Second transition: working -> blocked (with PR)
        state = initialized_state_manager.load_state()
        assert state is not None
        state.status = "blocked"
        state.current_pr = 100
        initialized_state_manager.save_state(state)

        loaded = initialized_state_manager.load_state()
        assert loaded is not None
        assert loaded.status == "blocked"
        assert loaded.current_pr == 100

    def test_transition_from_blocked_to_working(
        self, initialized_state_manager: StateManager
    ) -> None:
        """Test transitioning from blocked (with PR) to working.

        Path: planning -> working -> blocked -> working
        """
        state = initialized_state_manager.load_state()
        assert state is not None

        # planning -> working
        state.status = "working"
        initialized_state_manager.save_state(state)

        # working -> blocked (with PR)
        state = initialized_state_manager.load_state()
        assert state is not None
        state.status = "blocked"
        state.current_pr = 200
        initialized_state_manager.save_state(state)

        # blocked -> working (PR stays active)
        state = initialized_state_manager.load_state()
        assert state is not None
        state.status = "working"
        initialized_state_manager.save_state(state)

        loaded = initialized_state_manager.load_state()
        assert loaded is not None
        assert loaded.status == "working"
        assert loaded.current_pr == 200  # PR still tracked

    def test_pr_cleared_on_success(self, initialized_state_manager: StateManager) -> None:
        """Test PR is typically cleared on task success.

        Path: planning -> working -> success
        """
        state = initialized_state_manager.load_state()
        assert state is not None

        # planning -> working
        state.status = "working"
        state.current_pr = 300
        initialized_state_manager.save_state(state)

        # working -> success, clear PR
        state = initialized_state_manager.load_state()
        assert state is not None
        state.status = "success"
        state.current_pr = None  # Cleared after merge
        initialized_state_manager.save_state(state)

        loaded = initialized_state_manager.load_state()
        assert loaded is not None
        assert loaded.status == "success"
        assert loaded.current_pr is None

    def test_multiple_pr_transitions(self, initialized_state_manager: StateManager) -> None:
        """Test multiple PR state transitions in a workflow.

        Path: planning -> working (with PR changes)
        """
        state = initialized_state_manager.load_state()
        assert state is not None

        # planning -> working with first PR
        state.status = "working"
        state.current_pr = 100
        initialized_state_manager.save_state(state)

        # First PR merged, second PR
        state = initialized_state_manager.load_state()
        assert state is not None
        state.current_pr = 200
        initialized_state_manager.save_state(state)

        # Second PR merged, third PR
        state = initialized_state_manager.load_state()
        assert state is not None
        state.current_pr = 300
        initialized_state_manager.save_state(state)

        # Final state
        loaded = initialized_state_manager.load_state()
        assert loaded is not None
        assert loaded.current_pr == 300
