"""Tests for StateManager file operations.

This module contains tests for file read/write operations including:
- Goal save/load
- Plan save/load
- Criteria save/load
- Progress save/load
- Context save/load
- Log file operations
- Edge cases for content handling
- Atomic write operations
"""

import json
import time

from claude_task_master.core.state import (
    StateManager,
    TaskOptions,
)

# =============================================================================
# Goal File Operations Tests
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
# Plan File Operations Tests
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
# Criteria File Operations Tests
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
# Progress File Operations Tests
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
# Context File Operations Tests
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
# Log File Operations Tests
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
# Edge Cases for File Content Tests
# =============================================================================


class TestStateManagerFileContentEdgeCases:
    """Edge case tests for StateManager file content handling."""

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
# State File Persistence Tests
# =============================================================================


class TestStateFilePersistence:
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

    def test_concurrent_saves(self, initialized_state_manager):
        """Test that multiple saves don't corrupt state."""
        for i in range(10):
            state = initialized_state_manager.load_state()
            state.session_count = i
            initialized_state_manager.save_state(state)

        final_state = initialized_state_manager.load_state()
        assert final_state.session_count == 9
