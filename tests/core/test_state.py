"""Tests for state manager."""

import json
import pytest
import time
from pathlib import Path
from datetime import datetime

from claude_task_master.core.state import StateManager, TaskState, TaskOptions


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
        assert dump == {"auto_merge": False, "max_sessions": 3, "pause_on_pr": False}


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

        with pytest.raises(FileNotFoundError, match="No task state found"):
            manager.load_state()

    def test_load_state_preserves_all_fields(self, initialized_state_manager):
        """Test load_state preserves all fields."""
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
        remaining = set(f.name for f in logs_dir.glob("run-*.txt"))

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
        state = manager.initialize(
            goal="Complete the task",
            model="sonnet",
            options=options
        )

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

        special_content = 'Content with "quotes", <tags>, & ampersands, and \'apostrophes\''
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
