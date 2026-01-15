"""Tests for state manager."""

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from claude_task_master.core.state import (
    RESUMABLE_STATUSES,
    TERMINAL_STATUSES,
    VALID_STATUSES,
    VALID_TRANSITIONS,
    InvalidStateTransitionError,
    StateCorruptedError,
    StateError,
    StateLockError,
    StateManager,
    StateNotFoundError,
    StatePermissionError,
    StateResumeValidationError,
    StateValidationError,
    TaskOptions,
    TaskState,
    file_lock,
)

# =============================================================================
# TaskOptions Tests
# =============================================================================


class TestTaskOptions:
    """Tests for TaskOptions model."""

    def test_default_values(self):
        """Test TaskOptions default values."""
        options = TaskOptions()
        assert options.auto_merge is True
        assert options.max_sessions is None
        assert options.pause_on_pr is False

    def test_custom_values(self):
        """Test TaskOptions with custom values."""
        options = TaskOptions(auto_merge=False, max_sessions=5, pause_on_pr=True)
        assert options.auto_merge is False
        assert options.max_sessions == 5
        assert options.pause_on_pr is True

    def test_partial_custom_values(self):
        """Test TaskOptions with partial custom values."""
        options = TaskOptions(max_sessions=10)
        assert options.auto_merge is True
        assert options.max_sessions == 10
        assert options.pause_on_pr is False

    def test_model_dump(self):
        """Test TaskOptions model dump."""
        options = TaskOptions(auto_merge=False, max_sessions=3)
        dump = options.model_dump()
        assert dump == {
            "auto_merge": False,
            "max_sessions": 3,
            "pause_on_pr": False,
            "enable_checkpointing": False,
        }


# =============================================================================
# TaskState Tests
# =============================================================================


class TestTaskState:
    """Tests for TaskState model."""

    def test_task_state_creation(self, sample_task_options):
        """Test TaskState creation with all fields."""
        timestamp = datetime.now().isoformat()
        state = TaskState(
            status="planning",
            current_task_index=0,
            session_count=0,
            current_pr=None,
            created_at=timestamp,
            updated_at=timestamp,
            run_id="20250115-120000",
            model="sonnet",
            options=TaskOptions(**sample_task_options),
        )
        assert state.status == "planning"
        assert state.current_task_index == 0
        assert state.session_count == 0
        assert state.current_pr is None
        assert state.run_id == "20250115-120000"
        assert state.model == "sonnet"

    def test_task_state_with_pr(self, sample_task_options):
        """Test TaskState with current PR."""
        timestamp = datetime.now().isoformat()
        state = TaskState(
            status="blocked",
            current_task_index=1,
            session_count=2,
            current_pr=123,
            created_at=timestamp,
            updated_at=timestamp,
            run_id="20250115-120000",
            model="opus",
            options=TaskOptions(**sample_task_options),
        )
        assert state.current_pr == 123
        assert state.status == "blocked"
        assert state.session_count == 2

    def test_task_state_model_dump(self, sample_task_options):
        """Test TaskState model dump."""
        timestamp = "2025-01-15T12:00:00"
        state = TaskState(
            status="working",
            current_task_index=2,
            session_count=3,
            current_pr=456,
            created_at=timestamp,
            updated_at=timestamp,
            run_id="20250115-120000",
            model="sonnet",
            options=TaskOptions(**sample_task_options),
        )
        dump = state.model_dump()
        assert dump["status"] == "working"
        assert dump["current_task_index"] == 2
        assert dump["current_pr"] == 456
        assert "options" in dump


# =============================================================================
# StateManager Initialization Tests
# =============================================================================


class TestStateManagerInitialization:
    """Tests for StateManager initialization."""

    def test_state_manager_default_dir(self):
        """Test StateManager with default state directory."""
        manager = StateManager()
        assert manager.state_dir == Path(".claude-task-master")
        assert manager.logs_dir == Path(".claude-task-master") / "logs"

    def test_state_manager_custom_dir(self, temp_dir):
        """Test StateManager with custom state directory."""
        custom_dir = temp_dir / "custom-state"
        manager = StateManager(custom_dir)
        assert manager.state_dir == custom_dir
        assert manager.logs_dir == custom_dir / "logs"

    def test_initialize_creates_directories(self, temp_dir):
        """Test initialize creates necessary directories."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        options = TaskOptions()
        manager.initialize(goal="Test goal", model="sonnet", options=options)

        assert state_dir.exists()
        assert (state_dir / "logs").exists()

    def test_initialize_creates_state_file(self, temp_dir):
        """Test initialize creates state.json."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        options = TaskOptions()
        manager.initialize(goal="Test goal", model="sonnet", options=options)

        assert (state_dir / "state.json").exists()

    def test_initialize_creates_goal_file(self, temp_dir):
        """Test initialize creates goal.txt."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        options = TaskOptions()
        manager.initialize(goal="Test goal", model="sonnet", options=options)

        assert (state_dir / "goal.txt").exists()
        assert (state_dir / "goal.txt").read_text() == "Test goal"

    def test_initialize_returns_task_state(self, temp_dir):
        """Test initialize returns TaskState."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        options = TaskOptions(auto_merge=True, max_sessions=10)
        state = manager.initialize(goal="Test goal", model="sonnet", options=options)

        assert isinstance(state, TaskState)
        assert state.status == "planning"
        assert state.current_task_index == 0
        assert state.session_count == 0
        assert state.model == "sonnet"
        assert state.options.auto_merge is True
        assert state.options.max_sessions == 10

    def test_initialize_run_id_format(self, temp_dir):
        """Test initialize creates run_id with correct format."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        options = TaskOptions()
        state = manager.initialize(goal="Test goal", model="sonnet", options=options)

        # Run ID should be in format YYYYMMDD-HHMMSS
        assert len(state.run_id) == 15
        assert state.run_id[8] == "-"


# =============================================================================
# StateManager State Save/Load Tests
# =============================================================================


class TestStateManagerStatePersistence:
    """Tests for state save/load operations."""

    def test_save_load_roundtrip(self, initialized_state_manager):
        """Test save and load state roundtrip."""
        original_state = initialized_state_manager.load_state()
        original_state.status = "working"
        original_state.session_count = 5
        initialized_state_manager.save_state(original_state)

        loaded_state = initialized_state_manager.load_state()
        assert loaded_state.status == "working"
        assert loaded_state.session_count == 5

    def test_save_updates_timestamp(self, initialized_state_manager):
        """Test save_state updates the updated_at timestamp."""
        original_state = initialized_state_manager.load_state()
        original_updated_at = original_state.updated_at

        time.sleep(0.01)  # Small delay to ensure different timestamp
        initialized_state_manager.save_state(original_state)

        loaded_state = initialized_state_manager.load_state()
        assert loaded_state.updated_at != original_updated_at

    def test_load_state_no_file_raises(self, temp_dir):
        """Test load_state raises when no state file exists."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir()
        manager = StateManager(state_dir)

        with pytest.raises(StateNotFoundError):
            manager.load_state()

    def test_load_state_preserves_all_fields(self, initialized_state_manager):
        """Test load_state preserves all fields."""
        original_state = initialized_state_manager.load_state()
        # First transition to working (valid from planning)
        original_state.status = "working"
        initialized_state_manager.save_state(original_state)

        # Then transition to blocked (valid from working)
        original_state = initialized_state_manager.load_state()
        original_state.status = "blocked"
        original_state.current_task_index = 3
        original_state.session_count = 7
        original_state.current_pr = 456
        initialized_state_manager.save_state(original_state)

        loaded_state = initialized_state_manager.load_state()
        assert loaded_state.status == "blocked"
        assert loaded_state.current_task_index == 3
        assert loaded_state.session_count == 7
        assert loaded_state.current_pr == 456

    def test_state_file_is_valid_json(self, initialized_state_manager):
        """Test state file contains valid JSON."""
        state_file = initialized_state_manager.state_dir / "state.json"
        with open(state_file) as f:
            data = json.load(f)

        assert "status" in data
        assert "run_id" in data
        assert "options" in data


# =============================================================================
# StateManager Goal Tests
# =============================================================================


class TestStateManagerGoal:
    """Tests for goal save/load operations."""

    def test_save_load_goal(self, state_manager):
        """Test save and load goal."""
        state_manager.state_dir.mkdir(exist_ok=True)

        goal = "This is a test goal"
        state_manager.save_goal(goal)

        loaded_goal = state_manager.load_goal()
        assert loaded_goal == goal

    def test_goal_with_multiline(self, state_manager):
        """Test goal with multiple lines."""
        state_manager.state_dir.mkdir(exist_ok=True)

        goal = """This is a multi-line goal.

It has several paragraphs.

And special characters: @#$%^&*()"""
        state_manager.save_goal(goal)

        loaded_goal = state_manager.load_goal()
        assert loaded_goal == goal

    def test_goal_with_unicode(self, state_manager):
        """Test goal with unicode characters."""
        state_manager.state_dir.mkdir(exist_ok=True)

        goal = "Implement a feature with emoji 🚀 and unicode: 日本語"
        state_manager.save_goal(goal)

        loaded_goal = state_manager.load_goal()
        assert loaded_goal == goal

    def test_goal_overwrite(self, state_manager):
        """Test that saving goal overwrites previous goal."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_goal("First goal")
        state_manager.save_goal("Second goal")

        assert state_manager.load_goal() == "Second goal"


# =============================================================================
# StateManager Plan Tests
# =============================================================================


class TestStateManagerPlan:
    """Tests for plan save/load operations."""

    def test_save_load_plan(self, state_manager):
        """Test save and load plan."""
        state_manager.state_dir.mkdir(exist_ok=True)

        plan = """## Task List

- [ ] Task 1
- [ ] Task 2
- [x] Task 3
"""
        state_manager.save_plan(plan)

        loaded_plan = state_manager.load_plan()
        assert loaded_plan == plan

    def test_load_plan_no_file(self, state_manager):
        """Test load_plan returns None when file doesn't exist."""
        state_manager.state_dir.mkdir(exist_ok=True)

        result = state_manager.load_plan()
        assert result is None

    def test_plan_with_complex_markdown(self, state_manager):
        """Test plan with complex markdown content."""
        state_manager.state_dir.mkdir(exist_ok=True)

        plan = """# Task Plan

## Phase 1: Setup

- [ ] Initialize project
- [ ] Configure environment

## Phase 2: Implementation

1. First step
   - Sub-step 1
   - Sub-step 2
2. Second step

## Code Example

```python
def example():
    return "Hello"
```

## Success Criteria

| Metric | Target |
|--------|--------|
| Coverage | >80% |
| Tests | Pass |
"""
        state_manager.save_plan(plan)

        loaded_plan = state_manager.load_plan()
        assert loaded_plan == plan

    def test_plan_file_path(self, state_manager):
        """Test plan is saved to correct file path."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_plan("Test plan")

        plan_file = state_manager.state_dir / "plan.md"
        assert plan_file.exists()


# =============================================================================
# StateManager Criteria Tests
# =============================================================================


class TestStateManagerCriteria:
    """Tests for criteria save/load operations."""

    def test_save_load_criteria(self, state_manager):
        """Test save and load criteria."""
        state_manager.state_dir.mkdir(exist_ok=True)

        criteria = """1. All tests pass
2. Coverage > 80%
3. No critical bugs
"""
        state_manager.save_criteria(criteria)

        loaded_criteria = state_manager.load_criteria()
        assert loaded_criteria == criteria

    def test_load_criteria_no_file(self, state_manager):
        """Test load_criteria returns None when file doesn't exist."""
        state_manager.state_dir.mkdir(exist_ok=True)

        result = state_manager.load_criteria()
        assert result is None

    def test_criteria_with_checkmarks(self, state_manager):
        """Test criteria with checkmark symbols."""
        state_manager.state_dir.mkdir(exist_ok=True)

        criteria = """✓ First criterion met
✓ Second criterion met
✗ Third criterion failed
"""
        state_manager.save_criteria(criteria)

        loaded_criteria = state_manager.load_criteria()
        assert loaded_criteria == criteria

    def test_criteria_file_path(self, state_manager):
        """Test criteria is saved to correct file path."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_criteria("Test criteria")

        criteria_file = state_manager.state_dir / "criteria.txt"
        assert criteria_file.exists()


# =============================================================================
# StateManager Progress Tests
# =============================================================================


class TestStateManagerProgress:
    """Tests for progress save/load operations."""

    def test_save_load_progress(self, state_manager):
        """Test save and load progress."""
        state_manager.state_dir.mkdir(exist_ok=True)

        progress = """# Progress Update

Session: 3
Task: 2 of 5

## Latest
Completed feature implementation.
"""
        state_manager.save_progress(progress)

        loaded_progress = state_manager.load_progress()
        assert loaded_progress == progress

    def test_load_progress_no_file(self, state_manager):
        """Test load_progress returns None when file doesn't exist."""
        state_manager.state_dir.mkdir(exist_ok=True)

        result = state_manager.load_progress()
        assert result is None

    def test_progress_update_overwrites(self, state_manager):
        """Test progress update overwrites previous progress."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_progress("Progress 1")
        state_manager.save_progress("Progress 2")

        assert state_manager.load_progress() == "Progress 2"

    def test_progress_file_path(self, state_manager):
        """Test progress is saved to correct file path."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_progress("Test progress")

        progress_file = state_manager.state_dir / "progress.md"
        assert progress_file.exists()


# =============================================================================
# StateManager Context Tests
# =============================================================================


class TestStateManagerContext:
    """Tests for context save/load operations."""

    def test_save_load_context(self, state_manager):
        """Test save and load context."""
        state_manager.state_dir.mkdir(exist_ok=True)

        context = """# Accumulated Context

## Session 1
Initial exploration done.

## Session 2
Implementation started.
"""
        state_manager.save_context(context)

        loaded_context = state_manager.load_context()
        assert loaded_context == context

    def test_load_context_no_file_returns_empty(self, state_manager):
        """Test load_context returns empty string when file doesn't exist."""
        state_manager.state_dir.mkdir(exist_ok=True)

        result = state_manager.load_context()
        assert result == ""

    def test_context_large_content(self, state_manager):
        """Test context with large content."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Create large context
        context = "# Context\n\n" + "\n".join([f"Line {i}" for i in range(1000)])
        state_manager.save_context(context)

        loaded_context = state_manager.load_context()
        assert loaded_context == context

    def test_context_file_path(self, state_manager):
        """Test context is saved to correct file path."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_context("Test context")

        context_file = state_manager.state_dir / "context.md"
        assert context_file.exists()


# =============================================================================
# StateManager Log File Tests
# =============================================================================


class TestStateManagerLogFiles:
    """Tests for log file operations."""

    def test_get_log_file_path(self, state_manager):
        """Test get_log_file returns correct path."""
        log_file = state_manager.get_log_file("20250115-120000")

        expected_path = state_manager.logs_dir / "run-20250115-120000.txt"
        assert log_file == expected_path

    def test_get_log_file_different_run_ids(self, state_manager):
        """Test get_log_file with different run IDs."""
        log1 = state_manager.get_log_file("20250115-100000")
        log2 = state_manager.get_log_file("20250115-110000")

        assert log1 != log2
        assert "20250115-100000" in str(log1)
        assert "20250115-110000" in str(log2)

    def test_log_file_can_be_written(self, state_manager):
        """Test log file path can be written to."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.logs_dir.mkdir(exist_ok=True)

        log_file = state_manager.get_log_file("test-run")
        log_file.write_text("Log content")

        assert log_file.exists()
        assert log_file.read_text() == "Log content"


# =============================================================================
# StateManager Exists Tests
# =============================================================================


class TestStateManagerExists:
    """Tests for exists method."""

    def test_exists_returns_false_no_dir(self, temp_dir):
        """Test exists returns False when directory doesn't exist."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        assert manager.exists() is False

    def test_exists_returns_false_no_state_file(self, temp_dir):
        """Test exists returns False when state.json doesn't exist."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir()
        manager = StateManager(state_dir)

        assert manager.exists() is False

    def test_exists_returns_true_with_state_file(self, initialized_state_manager):
        """Test exists returns True when state is initialized."""
        assert initialized_state_manager.exists() is True

    def test_exists_after_cleanup_returns_false(self, initialized_state_manager):
        """Test exists returns False after cleanup."""
        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        assert initialized_state_manager.exists() is False


# =============================================================================
# StateManager Cleanup Tests
# =============================================================================


class TestStateManagerCleanup:
    """Tests for cleanup operations."""

    def test_cleanup_removes_state_files(self, initialized_state_manager):
        """Test cleanup removes state files."""
        # Add additional state files
        initialized_state_manager.save_plan("Test plan")
        initialized_state_manager.save_criteria("Test criteria")
        initialized_state_manager.save_progress("Test progress")
        initialized_state_manager.save_context("Test context")

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        state_dir = initialized_state_manager.state_dir
        assert not (state_dir / "state.json").exists()
        assert not (state_dir / "goal.txt").exists()
        assert not (state_dir / "plan.md").exists()
        assert not (state_dir / "criteria.txt").exists()
        assert not (state_dir / "progress.md").exists()
        assert not (state_dir / "context.md").exists()

    def test_cleanup_preserves_logs_dir(self, initialized_state_manager):
        """Test cleanup preserves logs directory."""
        run_id = initialized_state_manager.load_state().run_id

        # Create a log file
        log_file = initialized_state_manager.get_log_file(run_id)
        log_file.write_text("Test log")

        initialized_state_manager.cleanup_on_success(run_id)

        assert initialized_state_manager.logs_dir.exists()

    def test_cleanup_preserves_recent_logs(self, initialized_state_manager):
        """Test cleanup preserves recent log files."""
        logs_dir = initialized_state_manager.logs_dir
        # Create 5 log files (under the limit of 10)
        for i in range(5):
            log_file = logs_dir / f"run-test-{i:02d}.txt"
            log_file.write_text(f"Log {i}")
            time.sleep(0.01)

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        # All 5 logs should be preserved
        log_files = list(logs_dir.glob("run-*.txt"))
        assert len(log_files) == 5

    def test_cleanup_old_logs_removes_excess(self, initialized_state_manager):
        """Test cleanup removes old log files when over limit."""
        logs_dir = initialized_state_manager.logs_dir

        # Create 15 log files
        for i in range(15):
            log_file = logs_dir / f"run-2025011{i:02d}-120000.txt"
            log_file.write_text(f"Log content for session {i}")
            time.sleep(0.01)  # Small delay to ensure different mtime

        run_id = initialized_state_manager.load_state().run_id

        # Verify we have 15 log files
        assert len(list(logs_dir.glob("run-*.txt"))) == 15

        initialized_state_manager.cleanup_on_success(run_id)

        # Should only keep 10 most recent
        log_files = list(logs_dir.glob("run-*.txt"))
        assert len(log_files) == 10

    def test_cleanup_old_logs_keeps_newest(self, initialized_state_manager):
        """Test cleanup keeps the newest log files."""
        logs_dir = initialized_state_manager.logs_dir

        # Create 15 log files with distinct timestamps
        log_files_created = []
        for i in range(15):
            log_file = logs_dir / f"run-2025011{i:02d}-120000.txt"
            log_file.write_text(f"Log {i}")
            time.sleep(0.01)
            log_files_created.append(log_file)

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        # Get remaining log files
        remaining = {f.name for f in logs_dir.glob("run-*.txt")}

        # The 10 most recent (last 10 created) should remain
        for i in range(5, 15):
            expected_name = f"run-2025011{i:02d}-120000.txt"
            assert expected_name in remaining, f"Expected {expected_name} to be preserved"

    def test_cleanup_handles_no_logs_dir(self, state_manager):
        """Test cleanup handles missing logs directory gracefully."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Initialize state without logs dir
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)

        # Remove logs dir
        import shutil

        if state_manager.logs_dir.exists():
            shutil.rmtree(state_manager.logs_dir)

        # Cleanup should not raise
        state_manager.cleanup_on_success(state.run_id)

    def test_cleanup_removes_nested_directories(self, initialized_state_manager):
        """Test cleanup removes nested directories."""
        # Create a nested directory
        nested_dir = initialized_state_manager.state_dir / "nested" / "deep"
        nested_dir.mkdir(parents=True)
        (nested_dir / "file.txt").write_text("content")

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        assert not (initialized_state_manager.state_dir / "nested").exists()


# =============================================================================
# StateManager Integration Tests
# =============================================================================


class TestStateManagerIntegration:
    """Integration tests for StateManager."""

    def test_full_workflow(self, temp_dir):
        """Test complete workflow from init to cleanup."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        # Initialize
        options = TaskOptions(auto_merge=True, max_sessions=5)
        state = manager.initialize(goal="Complete the task", model="sonnet", options=options)

        assert state.status == "planning"

        # Save plan
        manager.save_plan("## Tasks\n- [ ] Task 1")
        assert manager.load_plan() is not None

        # Save criteria
        manager.save_criteria("All tests pass")
        assert manager.load_criteria() is not None

        # Update state
        state = manager.load_state()
        state.status = "working"
        state.session_count = 1
        manager.save_state(state)

        # Verify state persisted
        loaded_state = manager.load_state()
        assert loaded_state.status == "working"
        assert loaded_state.session_count == 1

        # Save progress and context
        manager.save_progress("Task 1 completed")
        manager.save_context("Learned about codebase structure")

        # Create log file
        log_file = manager.get_log_file(state.run_id)
        log_file.write_text("Session log content")

        assert manager.exists() is True

        # Cleanup
        manager.cleanup_on_success(state.run_id)

        assert manager.exists() is False
        assert manager.logs_dir.exists()

    def test_multiple_sessions_workflow(self, temp_dir):
        """Test workflow with multiple sessions."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        options = TaskOptions()
        state = manager.initialize(goal="Test", model="sonnet", options=options)

        # Simulate multiple sessions
        for session in range(1, 4):
            state = manager.load_state()
            state.session_count = session
            state.current_task_index = session - 1
            manager.save_state(state)

            manager.save_progress(f"Session {session} progress")
            manager.save_context(f"Session {session} context")

            log_file = manager.get_log_file(f"session-{session}")
            log_file.write_text(f"Log for session {session}")

        final_state = manager.load_state()
        assert final_state.session_count == 3
        assert final_state.current_task_index == 2

    def test_state_survives_crash_recovery(self, initialized_state_manager):
        """Test state can be recovered after simulated crash."""
        # Modify state
        state = initialized_state_manager.load_state()
        state.status = "working"
        state.session_count = 3
        state.current_task_index = 2
        initialized_state_manager.save_state(state)
        initialized_state_manager.save_plan("Important plan")
        initialized_state_manager.save_progress("Important progress")

        run_id = state.run_id
        state_dir = initialized_state_manager.state_dir

        # Create new manager instance (simulating restart)
        new_manager = StateManager(state_dir)

        # Verify state is recovered
        recovered_state = new_manager.load_state()
        assert recovered_state.status == "working"
        assert recovered_state.session_count == 3
        assert recovered_state.current_task_index == 2
        assert recovered_state.run_id == run_id

        assert new_manager.load_plan() == "Important plan"
        assert new_manager.load_progress() == "Important progress"


# =============================================================================
# StateManager Edge Cases Tests
# =============================================================================


class TestStateManagerEdgeCases:
    """Edge case tests for StateManager."""

    def test_empty_goal(self, state_manager):
        """Test saving and loading empty goal."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_goal("")
        assert state_manager.load_goal() == ""

    def test_empty_plan(self, state_manager):
        """Test saving and loading empty plan."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_plan("")
        assert state_manager.load_plan() == ""

    def test_whitespace_only_content(self, state_manager):
        """Test saving and loading whitespace-only content."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_context("   \n\t\n   ")
        assert state_manager.load_context() == "   \n\t\n   "

    def test_special_characters_in_content(self, state_manager):
        """Test content with special characters."""
        state_manager.state_dir.mkdir(exist_ok=True)

        special_content = "Content with \"quotes\", <tags>, & ampersands, and 'apostrophes'"
        state_manager.save_criteria(special_content)
        assert state_manager.load_criteria() == special_content

    def test_very_long_content(self, state_manager):
        """Test saving and loading very long content."""
        state_manager.state_dir.mkdir(exist_ok=True)

        long_content = "X" * 100000  # 100KB of content
        state_manager.save_progress(long_content)
        assert state_manager.load_progress() == long_content

    def test_state_dir_path_with_spaces(self, temp_dir):
        """Test state manager with path containing spaces."""
        # Create the parent directory first since initialize doesn't use parents=True
        parent_dir = temp_dir / "path with spaces"
        parent_dir.mkdir(parents=True)

        state_dir = parent_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        options = TaskOptions()
        state = manager.initialize(goal="Test", model="sonnet", options=options)

        assert manager.exists() is True
        loaded_state = manager.load_state()
        assert loaded_state.run_id == state.run_id

    def test_concurrent_saves(self, initialized_state_manager):
        """Test that multiple saves don't corrupt state."""
        for i in range(10):
            state = initialized_state_manager.load_state()
            state.session_count = i
            initialized_state_manager.save_state(state)

        final_state = initialized_state_manager.load_state()
        assert final_state.session_count == 9

    def test_cleanup_idempotent(self, initialized_state_manager):
        """Test cleanup can be called multiple times safely."""
        run_id = initialized_state_manager.load_state().run_id

        # First cleanup
        initialized_state_manager.cleanup_on_success(run_id)

        # Second cleanup should not raise
        initialized_state_manager.cleanup_on_success(run_id)

        assert initialized_state_manager.logs_dir.exists()


# =============================================================================
# Exception Classes Tests
# =============================================================================


class TestStateExceptions:
    """Tests for state exception classes."""

    def test_state_error_base_class(self):
        """Test StateError base exception."""
        error = StateError("Test error message")
        assert error.message == "Test error message"
        assert error.details is None
        assert str(error) == "Test error message"

    def test_state_error_with_details(self):
        """Test StateError with details."""
        error = StateError("Test error", "Additional details here")
        assert error.message == "Test error"
        assert error.details == "Additional details here"
        assert "Additional details here" in str(error)

    def test_state_not_found_error(self, temp_dir):
        """Test StateNotFoundError exception."""
        path = temp_dir / "state.json"
        error = StateNotFoundError(path)
        assert error.path == path
        assert "No task state found" in str(error)
        assert "start" in str(error)

    def test_state_corrupted_error_recoverable(self, temp_dir):
        """Test StateCorruptedError for recoverable corruption."""
        path = temp_dir / "state.json"
        error = StateCorruptedError(path, "Invalid JSON", recoverable=True)
        assert error.path == path
        assert error.recoverable is True
        assert "corrupted" in str(error).lower()
        assert "backup" in str(error).lower()

    def test_state_corrupted_error_unrecoverable(self, temp_dir):
        """Test StateCorruptedError for unrecoverable corruption."""
        path = temp_dir / "state.json"
        error = StateCorruptedError(path, "Invalid JSON", recoverable=False)
        assert error.recoverable is False

    def test_state_validation_error_missing_fields(self):
        """Test StateValidationError with missing fields."""
        error = StateValidationError("Invalid state", missing_fields=["status", "run_id"])
        assert error.missing_fields == ["status", "run_id"]
        assert "status" in str(error)
        assert "run_id" in str(error)

    def test_state_validation_error_invalid_fields(self):
        """Test StateValidationError with invalid fields."""
        error = StateValidationError("Invalid state", invalid_fields=["status: invalid value"])
        assert error.invalid_fields == ["status: invalid value"]
        assert "invalid value" in str(error)

    def test_invalid_state_transition_error(self):
        """Test InvalidStateTransitionError exception."""
        error = InvalidStateTransitionError("success", "working")
        assert error.current_status == "success"
        assert error.new_status == "working"
        assert "Invalid state transition" in str(error)
        assert "success" in str(error)
        assert "working" in str(error)

    def test_state_permission_error(self, temp_dir):
        """Test StatePermissionError exception."""
        path = temp_dir / "state.json"
        original = PermissionError("Permission denied")
        error = StatePermissionError(path, "reading", original)
        assert error.path == path
        assert error.operation == "reading"
        assert error.original_error == original
        assert "Permission denied" in str(error)

    def test_state_lock_error(self, temp_dir):
        """Test StateLockError exception."""
        path = temp_dir / ".state.lock"
        error = StateLockError(path, 5.0)
        assert error.path == path
        assert error.timeout == 5.0
        assert "lock" in str(error).lower()
        assert "5.0" in str(error)


# =============================================================================
# State Transitions Tests
# =============================================================================


class TestStateTransitions:
    """Tests for state transition validation."""

    def test_valid_statuses_defined(self):
        """Test that valid statuses are properly defined."""
        expected = {"planning", "working", "blocked", "paused", "success", "failed"}
        assert VALID_STATUSES == expected

    def test_valid_transitions_from_planning(self):
        """Test valid transitions from planning status."""
        assert "working" in VALID_TRANSITIONS["planning"]
        assert "failed" in VALID_TRANSITIONS["planning"]
        assert "success" not in VALID_TRANSITIONS["planning"]
        assert "blocked" not in VALID_TRANSITIONS["planning"]

    def test_valid_transitions_from_working(self):
        """Test valid transitions from working status."""
        assert "blocked" in VALID_TRANSITIONS["working"]
        assert "success" in VALID_TRANSITIONS["working"]
        assert "failed" in VALID_TRANSITIONS["working"]
        assert "working" in VALID_TRANSITIONS["working"]  # Retry allowed
        assert "planning" not in VALID_TRANSITIONS["working"]

    def test_valid_transitions_from_blocked(self):
        """Test valid transitions from blocked status."""
        assert "working" in VALID_TRANSITIONS["blocked"]
        assert "failed" in VALID_TRANSITIONS["blocked"]
        assert "success" not in VALID_TRANSITIONS["blocked"]

    def test_valid_transitions_from_paused(self):
        """Test valid transitions from paused status."""
        assert "working" in VALID_TRANSITIONS["paused"]
        assert "failed" in VALID_TRANSITIONS["paused"]
        assert "success" not in VALID_TRANSITIONS["paused"]
        assert "blocked" not in VALID_TRANSITIONS["paused"]

    def test_terminal_states_have_no_transitions(self):
        """Test that terminal states have no valid transitions."""
        assert len(VALID_TRANSITIONS["success"]) == 0
        assert len(VALID_TRANSITIONS["failed"]) == 0

    def test_save_validates_transition(self, initialized_state_manager):
        """Test that save_state validates transitions."""
        state = initialized_state_manager.load_state()
        assert state.status == "planning"

        # Valid transition: planning -> working
        state.status = "working"
        initialized_state_manager.save_state(state)

        loaded = initialized_state_manager.load_state()
        assert loaded.status == "working"

    def test_invalid_transition_raises_error(self, initialized_state_manager):
        """Test that invalid transitions raise InvalidStateTransitionError."""
        state = initialized_state_manager.load_state()
        assert state.status == "planning"

        # Invalid transition: planning -> success (must go through working)
        state.status = "success"
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            initialized_state_manager.save_state(state)

        assert exc_info.value.current_status == "planning"
        assert exc_info.value.new_status == "success"

    def test_same_status_transition_allowed(self, initialized_state_manager):
        """Test that same-status transition is always allowed."""
        state = initialized_state_manager.load_state()
        state.status = "planning"  # Same status
        # Should not raise
        initialized_state_manager.save_state(state)

    def test_skip_transition_validation(self, initialized_state_manager):
        """Test skipping transition validation when requested."""
        state = initialized_state_manager.load_state()

        # Normally invalid: planning -> success
        state.status = "success"
        # Should not raise when validation is disabled
        initialized_state_manager.save_state(state, validate_transition=False)

        loaded = initialized_state_manager.load_state()
        assert loaded.status == "success"


# =============================================================================
# Corrupted State Recovery Tests
# =============================================================================


class TestCorruptedStateRecovery:
    """Tests for corrupted state file recovery."""

    def test_load_corrupted_json_raises_error(self, temp_dir):
        """Test loading corrupted JSON raises StateCorruptedError."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        state_file.write_text("{ invalid json }")

        manager = StateManager(state_dir)

        with pytest.raises(StateCorruptedError) as exc_info:
            manager.load_state()

        assert exc_info.value.path == state_file

    def test_load_empty_json_raises_error(self, temp_dir):
        """Test loading empty JSON raises StateCorruptedError."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        state_file.write_text("{}")

        manager = StateManager(state_dir)

        with pytest.raises(StateCorruptedError):
            manager.load_state()

    def test_load_partial_state_raises_validation_error(self, temp_dir):
        """Test loading partial state raises StateValidationError."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        # Missing required fields
        state_file.write_text('{"status": "working"}')

        manager = StateManager(state_dir)

        with pytest.raises(StateValidationError) as exc_info:
            manager.load_state()

        assert len(exc_info.value.missing_fields) > 0

    def test_recovery_from_backup(self, temp_dir):
        """Test recovery from backup when state is corrupted."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        # Create valid initial state
        options = TaskOptions()
        original_state = manager.initialize(goal="Test", model="sonnet", options=options)

        # Create backup
        backup_path = manager.create_state_backup()
        assert backup_path is not None
        assert backup_path.exists()

        # Corrupt the state file
        manager.state_file.write_text("corrupted")

        # Load should recover from backup
        recovered_state = manager.load_state()
        assert recovered_state.run_id == original_state.run_id

    def test_corrupted_backup_creates_backup(self, temp_dir):
        """Test that corrupted file is backed up before recovery."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        # Create valid initial state
        options = TaskOptions()
        manager.initialize(goal="Test", model="sonnet", options=options)

        # Create backup for recovery
        manager.create_state_backup()

        # Corrupt the state file
        manager.state_file.write_text("corrupted content")

        # Load will attempt recovery
        manager.load_state()

        # Check that corrupted backup was created
        corrupted_backups = list(manager.backup_dir.glob("*.corrupted.json"))
        assert len(corrupted_backups) > 0

    def test_no_backup_available_raises_error(self, temp_dir):
        """Test that missing backup raises unrecoverable error."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        state_file.write_text("corrupted")

        manager = StateManager(state_dir)

        with pytest.raises(StateCorruptedError) as exc_info:
            manager.load_state()

        assert exc_info.value.recoverable is False


# =============================================================================
# File Locking Tests
# =============================================================================


class TestFileLocking:
    """Tests for file locking functionality."""

    def test_file_lock_creates_lock_file(self, temp_dir):
        """Test that file_lock creates the lock file."""
        lock_path = temp_dir / ".lock"

        with file_lock(lock_path):
            assert lock_path.exists()

    def test_file_lock_releases_on_exit(self, temp_dir):
        """Test that file lock is released when context exits."""
        lock_path = temp_dir / ".lock"

        with file_lock(lock_path):
            pass

        # Should be able to acquire lock again immediately
        with file_lock(lock_path):
            pass

    def test_file_lock_timeout_raises_error(self, temp_dir):
        """Test that lock timeout raises StateLockError."""
        lock_path = temp_dir / ".lock"
        lock_acquired = threading.Event()
        test_complete = threading.Event()

        def hold_lock():
            with file_lock(lock_path, timeout=10.0):
                lock_acquired.set()
                test_complete.wait(timeout=5.0)

        # Start thread holding the lock
        thread = threading.Thread(target=hold_lock)
        thread.start()
        lock_acquired.wait(timeout=2.0)

        try:
            # Try to acquire lock with short timeout
            with pytest.raises(StateLockError) as exc_info:
                with file_lock(lock_path, timeout=0.2):
                    pass

            assert exc_info.value.timeout == 0.2
        finally:
            test_complete.set()
            thread.join(timeout=2.0)

    def test_concurrent_state_access(self, temp_dir):
        """Test concurrent state access with locking."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        options = TaskOptions()
        manager.initialize(goal="Test", model="sonnet", options=options)

        results = []
        errors = []

        def update_state(session_num):
            try:
                state = manager.load_state()
                time.sleep(0.01)  # Simulate work
                state.session_count = session_num
                # Don't validate transition since status doesn't change
                manager.save_state(state, validate_transition=False)
                results.append(session_num)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=update_state, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert len(errors) == 0, f"Errors during concurrent access: {errors}"
        # All threads should have completed
        assert len(results) == 5


# =============================================================================
# Atomic Write Tests
# =============================================================================


class TestAtomicWrite:
    """Tests for atomic file writing."""

    def test_atomic_write_creates_file(self, initialized_state_manager):
        """Test that atomic write creates the state file."""
        assert initialized_state_manager.state_file.exists()

    def test_atomic_write_is_valid_json(self, initialized_state_manager):
        """Test that atomic write produces valid JSON."""
        content = initialized_state_manager.state_file.read_text()
        data = json.loads(content)
        assert "status" in data
        assert "run_id" in data

    def test_atomic_write_no_temp_files_left(self, temp_dir):
        """Test that no temporary files are left after atomic write."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        options = TaskOptions()
        manager.initialize(goal="Test", model="sonnet", options=options)

        # Check for temp files
        temp_files = list(state_dir.glob(".tmp_*"))
        assert len(temp_files) == 0


# =============================================================================
# Backup Tests
# =============================================================================


class TestStateBackup:
    """Tests for state backup functionality."""

    def test_create_backup_returns_path(self, initialized_state_manager):
        """Test create_state_backup returns the backup path."""
        backup_path = initialized_state_manager.create_state_backup()
        assert backup_path is not None
        assert backup_path.exists()

    def test_backup_contains_state_data(self, initialized_state_manager):
        """Test that backup contains valid state data."""
        backup_path = initialized_state_manager.create_state_backup()

        with open(backup_path) as f:
            data = json.load(f)

        assert "status" in data
        assert "run_id" in data

    def test_multiple_backups_have_unique_names(self, initialized_state_manager):
        """Test that multiple backups have unique names."""
        time.sleep(0.01)  # Ensure different timestamps
        backup1 = initialized_state_manager.create_state_backup()
        time.sleep(1.1)  # Ensure different timestamp in seconds
        backup2 = initialized_state_manager.create_state_backup()

        assert backup1 != backup2
        assert backup1.exists()
        assert backup2.exists()

    def test_backup_no_file_returns_none(self, temp_dir):
        """Test create_state_backup returns None when no state file."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        manager = StateManager(state_dir)

        result = manager.create_state_backup()
        assert result is None

    def test_backup_directory_created(self, initialized_state_manager):
        """Test that backup directory is created automatically."""
        backup_path = initialized_state_manager.create_state_backup()
        assert initialized_state_manager.backup_dir.exists()
        assert backup_path.parent == initialized_state_manager.backup_dir


# =============================================================================
# StateNotFoundError Tests
# =============================================================================


class TestStateNotFoundError:
    """Tests for state not found scenarios."""

    def test_load_state_no_file_raises_state_not_found(self, temp_dir):
        """Test load_state raises StateNotFoundError when file missing."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir()
        manager = StateManager(state_dir)

        with pytest.raises(StateNotFoundError) as exc_info:
            manager.load_state()

        assert exc_info.value.path == manager.state_file

    def test_state_not_found_error_inherits_from_state_error(self):
        """Test StateNotFoundError is a StateError."""
        error = StateNotFoundError(Path("/tmp/state.json"))
        assert isinstance(error, StateError)


# =============================================================================
# StateResumeValidationError Tests
# =============================================================================


class TestStateResumeValidationError:
    """Tests for StateResumeValidationError exception."""

    def test_basic_error(self):
        """Test basic error with just reason."""
        error = StateResumeValidationError("Test reason")
        assert error.reason == "Test reason"
        assert error.status is None
        assert error.current_task_index is None
        assert error.total_tasks is None
        assert error.suggestion is None
        assert "Cannot resume task: Test reason" in str(error)

    def test_error_with_status(self):
        """Test error with status information."""
        error = StateResumeValidationError("Test reason", status="failed")
        assert error.status == "failed"
        assert "Current status: failed" in str(error)

    def test_error_with_task_index(self):
        """Test error with task index information."""
        error = StateResumeValidationError("Test reason", current_task_index=5, total_tasks=3)
        assert error.current_task_index == 5
        assert error.total_tasks == 3
        assert "Task index: 5" in str(error)
        assert "Total tasks: 3" in str(error)

    def test_error_with_suggestion(self):
        """Test error with suggestion."""
        error = StateResumeValidationError("Test reason", suggestion="Try running 'clean' first")
        assert error.suggestion == "Try running 'clean' first"
        assert "Suggestion: Try running 'clean' first" in str(error)

    def test_error_with_all_fields(self):
        """Test error with all fields populated."""
        error = StateResumeValidationError(
            "Task has failed",
            status="failed",
            current_task_index=2,
            total_tasks=5,
            suggestion="Use 'clean' to start fresh",
        )
        assert error.reason == "Task has failed"
        assert error.status == "failed"
        assert error.current_task_index == 2
        assert error.total_tasks == 5
        assert error.suggestion == "Use 'clean' to start fresh"

        error_str = str(error)
        assert "Cannot resume task: Task has failed" in error_str
        assert "Current status: failed" in error_str
        assert "Task index: 2" in error_str
        assert "Total tasks: 5" in error_str
        assert "Use 'clean' to start fresh" in error_str

    def test_error_inherits_from_state_error(self):
        """Test StateResumeValidationError inherits from StateError."""
        error = StateResumeValidationError("Test")
        assert isinstance(error, StateError)

    def test_error_zero_task_index(self):
        """Test error with task index of 0."""
        error = StateResumeValidationError("Test", current_task_index=0)
        assert error.current_task_index == 0
        assert "Task index: 0" in str(error)


# =============================================================================
# Resume Status Constants Tests
# =============================================================================


class TestResumeStatusConstants:
    """Tests for resume-related status constants."""

    def test_terminal_statuses_defined(self):
        """Test that terminal statuses are properly defined."""
        expected = {"success", "failed"}
        assert TERMINAL_STATUSES == expected

    def test_resumable_statuses_defined(self):
        """Test that resumable statuses are properly defined."""
        expected = {"paused", "working", "blocked"}
        assert RESUMABLE_STATUSES == expected

    def test_terminal_and_resumable_are_disjoint(self):
        """Test that terminal and resumable statuses don't overlap."""
        assert len(TERMINAL_STATUSES & RESUMABLE_STATUSES) == 0

    def test_planning_is_neither_terminal_nor_resumable(self):
        """Test that planning is handled separately."""
        assert "planning" not in TERMINAL_STATUSES
        assert "planning" not in RESUMABLE_STATUSES

    def test_all_statuses_covered(self):
        """Test that all statuses are accounted for."""
        all_covered = TERMINAL_STATUSES | RESUMABLE_STATUSES | {"planning"}
        assert all_covered == VALID_STATUSES


# =============================================================================
# validate_for_resume Tests
# =============================================================================


class TestValidateForResume:
    """Tests for StateManager.validate_for_resume method."""

    def test_validate_nonexistent_state_raises_error(self, temp_dir):
        """Test validate_for_resume raises error when state doesn't exist."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        with pytest.raises(StateNotFoundError):
            manager.validate_for_resume()

    def test_validate_success_state_raises_error(self, initialized_state_manager):
        """Test validate_for_resume raises error for success state."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "success"
        initialized_state_manager.save_state(state)
        initialized_state_manager.save_plan("- [ ] Task 1")

        with pytest.raises(StateResumeValidationError) as exc_info:
            initialized_state_manager.validate_for_resume()

        error = exc_info.value
        assert error.status == "success"
        assert "completed successfully" in error.reason.lower()
        assert "clean" in error.suggestion.lower()

    def test_validate_failed_state_raises_error(self, initialized_state_manager):
        """Test validate_for_resume raises error for failed state."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "failed"
        initialized_state_manager.save_state(state)
        initialized_state_manager.save_plan("- [ ] Task 1")

        with pytest.raises(StateResumeValidationError) as exc_info:
            initialized_state_manager.validate_for_resume()

        error = exc_info.value
        assert error.status == "failed"
        assert "failed" in error.reason.lower()
        assert "clean" in error.suggestion.lower()

    def test_validate_paused_state_succeeds(self, initialized_state_manager):
        """Test validate_for_resume succeeds for paused state with plan."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "paused"
        initialized_state_manager.save_state(state)
        initialized_state_manager.save_plan("- [ ] Task 1\n- [ ] Task 2")

        result = initialized_state_manager.validate_for_resume()
        assert result.status == "paused"

    def test_validate_working_state_succeeds(self, initialized_state_manager):
        """Test validate_for_resume succeeds for working state with plan."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        initialized_state_manager.save_plan("- [ ] Task 1")

        result = initialized_state_manager.validate_for_resume()
        assert result.status == "working"

    def test_validate_blocked_state_succeeds(self, initialized_state_manager):
        """Test validate_for_resume succeeds for blocked state with plan."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)
        state.status = "blocked"
        initialized_state_manager.save_state(state)
        initialized_state_manager.save_plan("- [ ] Task 1")

        result = initialized_state_manager.validate_for_resume()
        assert result.status == "blocked"

    def test_validate_planning_state_without_plan_raises_error(self, initialized_state_manager):
        """Test validate_for_resume raises error for planning state without plan."""
        # State is initialized with planning status, no plan file yet
        with pytest.raises(StateResumeValidationError) as exc_info:
            initialized_state_manager.validate_for_resume()

        error = exc_info.value
        assert error.status == "planning"
        assert "planning phase" in error.reason.lower()

    def test_validate_planning_state_with_plan_succeeds(self, initialized_state_manager):
        """Test validate_for_resume succeeds for planning state with plan."""
        initialized_state_manager.save_plan("- [ ] Task 1")

        result = initialized_state_manager.validate_for_resume()
        assert result.status == "planning"

    def test_validate_no_plan_raises_error(self, initialized_state_manager):
        """Test validate_for_resume raises error when no plan exists."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        with pytest.raises(StateResumeValidationError) as exc_info:
            initialized_state_manager.validate_for_resume()

        error = exc_info.value
        assert "No plan file found" in error.reason

    def test_validate_negative_task_index_raises_error(self, initialized_state_manager):
        """Test validate_for_resume raises error for negative task index."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        state.current_task_index = -1
        initialized_state_manager.save_state(state, validate_transition=False)
        initialized_state_manager.save_plan("- [ ] Task 1")

        with pytest.raises(StateResumeValidationError) as exc_info:
            initialized_state_manager.validate_for_resume()

        error = exc_info.value
        assert "negative" in error.reason.lower()
        assert error.current_task_index == -1

    def test_validate_task_index_exceeds_total_raises_error(self, initialized_state_manager):
        """Test validate_for_resume raises error when task index > total tasks."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        state.current_task_index = 10
        initialized_state_manager.save_state(state, validate_transition=False)
        initialized_state_manager.save_plan("- [ ] Task 1\n- [ ] Task 2")  # Only 2 tasks

        with pytest.raises(StateResumeValidationError) as exc_info:
            initialized_state_manager.validate_for_resume()

        error = exc_info.value
        assert "exceeds" in error.reason.lower()
        assert error.current_task_index == 10
        assert error.total_tasks == 2

    def test_validate_task_index_equals_total_succeeds(self, initialized_state_manager):
        """Test validate_for_resume succeeds when task index == total (all complete)."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        state.current_task_index = 2
        initialized_state_manager.save_state(state, validate_transition=False)
        initialized_state_manager.save_plan("- [x] Task 1\n- [x] Task 2")  # 2 tasks, all done

        result = initialized_state_manager.validate_for_resume()
        assert result.current_task_index == 2

    def test_validate_zero_task_index_succeeds(self, initialized_state_manager):
        """Test validate_for_resume succeeds for task index 0."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        state.current_task_index = 0
        initialized_state_manager.save_state(state)
        initialized_state_manager.save_plan("- [ ] Task 1")

        result = initialized_state_manager.validate_for_resume()
        assert result.current_task_index == 0

    def test_validate_with_provided_state(self, initialized_state_manager):
        """Test validate_for_resume uses provided state object."""
        initialized_state_manager.save_plan("- [ ] Task 1")

        timestamp = datetime.now().isoformat()
        provided_state = TaskState(
            status="paused",
            current_task_index=0,
            session_count=1,
            created_at=timestamp,
            updated_at=timestamp,
            run_id="test-run",
            model="sonnet",
            options=TaskOptions(),
        )

        result = initialized_state_manager.validate_for_resume(provided_state)
        assert result == provided_state

    def test_validate_empty_plan_allows_index_zero(self, initialized_state_manager):
        """Test validate_for_resume allows index 0 with empty plan."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        state.current_task_index = 0
        initialized_state_manager.save_state(state)
        initialized_state_manager.save_plan("# Plan\n\nNo tasks yet")  # No checkbox items

        result = initialized_state_manager.validate_for_resume()
        assert result.current_task_index == 0

    def test_validate_plan_with_mixed_task_status(self, initialized_state_manager):
        """Test validate_for_resume with plan containing completed and pending tasks."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        state.current_task_index = 2
        initialized_state_manager.save_state(state)

        plan = """# Plan
- [x] Task 1: Done
- [x] Task 2: Done
- [ ] Task 3: In progress
- [ ] Task 4: Pending
"""
        initialized_state_manager.save_plan(plan)

        result = initialized_state_manager.validate_for_resume()
        assert result.current_task_index == 2


# =============================================================================
# _parse_plan_tasks Tests
# =============================================================================


class TestParsePlanTasks:
    """Tests for StateManager._parse_plan_tasks method."""

    def test_parse_empty_plan(self, state_manager):
        """Test parsing empty plan returns empty list."""
        tasks = state_manager._parse_plan_tasks("")
        assert tasks == []

    def test_parse_plan_no_tasks(self, state_manager):
        """Test parsing plan with no checkbox items."""
        plan = "# Plan\n\nSome description text"
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == []

    def test_parse_single_unchecked_task(self, state_manager):
        """Test parsing single unchecked task."""
        plan = "- [ ] Task 1"
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == ["Task 1"]

    def test_parse_single_checked_task(self, state_manager):
        """Test parsing single checked task."""
        plan = "- [x] Task 1"
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == ["Task 1"]

    def test_parse_multiple_tasks(self, state_manager):
        """Test parsing multiple tasks."""
        plan = """# Plan
- [ ] Task 1
- [x] Task 2
- [ ] Task 3
"""
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == ["Task 1", "Task 2", "Task 3"]

    def test_parse_tasks_with_indentation(self, state_manager):
        """Test parsing tasks with leading whitespace."""
        plan = """# Plan
  - [ ] Task 1
    - [ ] Task 2
"""
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == ["Task 1", "Task 2"]

    def test_parse_tasks_ignores_other_list_items(self, state_manager):
        """Test that non-checkbox list items are ignored."""
        plan = """# Plan
- Not a task
- [ ] Real task
* Another non-task
- [x] Another real task
"""
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == ["Real task", "Another real task"]

    def test_parse_tasks_with_empty_descriptions(self, state_manager):
        """Test that tasks with empty descriptions are ignored."""
        plan = """# Plan
- [ ]
- [ ] Real task
- [x]
"""
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == ["Real task"]

    def test_parse_tasks_preserves_description_format(self, state_manager):
        """Test that task descriptions are preserved as-is."""
        plan = "- [ ] Task with **bold** and `code`"
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == ["Task with **bold** and `code`"]
