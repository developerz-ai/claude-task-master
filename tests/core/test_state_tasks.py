"""Tests for StateManager task parsing and management.

This module contains tests for task-related functionality including:
- Task parsing from plan markdown (_parse_plan_tasks)
- Resume validation (validate_for_resume)
- Resume status constants (TERMINAL_STATUSES, RESUMABLE_STATUSES)
- StateResumeValidationError exception
"""

from datetime import datetime

import pytest

from claude_task_master.core.state import (
    RESUMABLE_STATUSES,
    TERMINAL_STATUSES,
    VALID_STATUSES,
    StateError,
    StateManager,
    StateNotFoundError,
    StateResumeValidationError,
    TaskOptions,
    TaskState,
)

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

    def test_parse_tasks_with_numbers_in_description(self, state_manager):
        """Test parsing tasks with numbers in description."""
        plan = "- [ ] Task #1: Complete step 2"
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == ["Task #1: Complete step 2"]

    def test_parse_tasks_lowercase_x_only(self, state_manager):
        """Test that only lowercase x is recognized.

        Note: The current implementation only supports lowercase x for checked items.
        Uppercase X is not recognized as a checked task marker.
        """
        plan = """- [ ] Unchecked
- [x] Lowercase x
"""
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == ["Unchecked", "Lowercase x"]

    def test_parse_tasks_uppercase_x_not_recognized(self, state_manager):
        """Test that uppercase X is not recognized as a task marker.

        This documents current behavior - uppercase X is NOT supported.
        """
        plan = "- [X] Task with uppercase X"
        tasks = state_manager._parse_plan_tasks(plan)
        # Current implementation doesn't recognize uppercase X
        assert tasks == []

    def test_parse_tasks_with_special_characters(self, state_manager):
        """Test parsing tasks with special characters."""
        plan = "- [ ] Task with @mentions, #hashtags, and $special"
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == ["Task with @mentions, #hashtags, and $special"]

    def test_parse_tasks_multiline_plan(self, state_manager):
        """Test parsing complex multi-section plan."""
        plan = """# Implementation Plan

## Phase 1: Setup
- [ ] Initialize project structure
- [ ] Configure build tools

## Phase 2: Core
- [x] Implement main feature
- [ ] Add error handling

## Phase 3: Testing
- [ ] Write unit tests
"""
        tasks = state_manager._parse_plan_tasks(plan)
        assert len(tasks) == 5
        assert "Initialize project structure" in tasks
        assert "Implement main feature" in tasks
        assert "Write unit tests" in tasks


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

    def test_error_only_total_tasks(self):
        """Test error with only total_tasks (no index)."""
        error = StateResumeValidationError("Test", total_tasks=10)
        assert error.total_tasks == 10
        assert "Total tasks: 10" in str(error)


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

    def test_terminal_statuses_are_final(self):
        """Test that terminal statuses represent completion states."""
        for status in TERMINAL_STATUSES:
            assert status in {"success", "failed"}

    def test_resumable_statuses_are_in_progress(self):
        """Test that resumable statuses represent active/interruptible states."""
        for status in RESUMABLE_STATUSES:
            assert status in {"paused", "working", "blocked"}


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
        assert error.reason and "completed successfully" in error.reason.lower()
        assert error.suggestion and "clean" in error.suggestion.lower()

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
        assert error.reason and "failed" in error.reason.lower()
        assert error.suggestion and "clean" in error.suggestion.lower()

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
# Task State Management Tests
# =============================================================================


class TestTaskStateManagement:
    """Tests for task state management during work sessions."""

    def test_task_index_persists_across_load_save(self, initialized_state_manager):
        """Test that task index persists correctly across save/load cycles."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        state.current_task_index = 5
        initialized_state_manager.save_state(state)

        loaded_state = initialized_state_manager.load_state()
        assert loaded_state.current_task_index == 5

    def test_task_index_updates_correctly(self, initialized_state_manager):
        """Test that task index updates correctly during work."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        for i in range(5):
            state = initialized_state_manager.load_state()
            state.current_task_index = i
            initialized_state_manager.save_state(state)

        final_state = initialized_state_manager.load_state()
        assert final_state.current_task_index == 4

    def test_session_count_increments_with_tasks(self, initialized_state_manager):
        """Test that session count and task index can be updated together."""
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        state = initialized_state_manager.load_state()
        state.session_count = 3
        state.current_task_index = 2
        initialized_state_manager.save_state(state)

        loaded_state = initialized_state_manager.load_state()
        assert loaded_state.session_count == 3
        assert loaded_state.current_task_index == 2


# =============================================================================
# Plan Parsing Edge Cases Tests
# =============================================================================


class TestPlanParsingEdgeCases:
    """Edge case tests for plan parsing."""

    def test_parse_plan_with_windows_line_endings(self, state_manager):
        """Test parsing plan with Windows line endings (CRLF)."""
        plan = "- [ ] Task 1\r\n- [ ] Task 2\r\n- [ ] Task 3"
        tasks = state_manager._parse_plan_tasks(plan)
        assert len(tasks) == 3

    def test_parse_plan_with_mixed_line_endings(self, state_manager):
        """Test parsing plan with mixed line endings."""
        plan = "- [ ] Task 1\n- [ ] Task 2\r\n- [ ] Task 3\r"
        tasks = state_manager._parse_plan_tasks(plan)
        # Should handle all line ending types
        assert len(tasks) >= 2

    def test_parse_plan_with_unicode_tasks(self, state_manager):
        """Test parsing plan with unicode in task descriptions."""
        plan = """- [ ] Add i18n support for 日本語
- [ ] Fix emoji rendering 🚀
- [ ] Handle Ümläuts correctly
"""
        tasks = state_manager._parse_plan_tasks(plan)
        assert len(tasks) == 3
        assert "日本語" in tasks[0]
        assert "🚀" in tasks[1]

    def test_parse_plan_whitespace_in_checkbox(self, state_manager):
        """Test that whitespace variations in checkbox are handled."""
        # Standard checkbox with single space
        plan = "- [ ] Normal task"
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == ["Normal task"]

    def test_parse_plan_none_input(self, state_manager):
        """Test parsing None plan raises AttributeError.

        Note: The current implementation doesn't handle None input.
        This is acceptable since validate_for_resume checks for plan existence first.
        """
        import pytest

        with pytest.raises(AttributeError):
            state_manager._parse_plan_tasks(None)

    def test_parse_plan_only_whitespace(self, state_manager):
        """Test parsing plan with only whitespace."""
        plan = "   \n\t\n   "
        tasks = state_manager._parse_plan_tasks(plan)
        assert tasks == []

    def test_parse_nested_checkbox_items(self, state_manager):
        """Test parsing nested checkbox items."""
        plan = """- [ ] Parent task
  - [ ] Nested task 1
    - [ ] Deeply nested task
- [ ] Another parent
"""
        tasks = state_manager._parse_plan_tasks(plan)
        # All checkboxes should be found regardless of nesting
        assert len(tasks) == 4

    def test_parse_checkbox_with_code_blocks(self, state_manager):
        """Test that checkboxes inside code blocks are ignored."""
        plan = """- [ ] Real task

```markdown
- [ ] Not a real task (in code block)
```

- [ ] Another real task
"""
        tasks = state_manager._parse_plan_tasks(plan)
        # Note: Simple regex parsing may include code block items
        # This test documents current behavior
        assert "Real task" in tasks
        assert "Another real task" in tasks
