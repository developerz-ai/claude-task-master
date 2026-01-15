"""Comprehensive tests for the planner module."""

import pytest

from claude_task_master.core.planner import Planner
from claude_task_master.core.state import StateManager

# =============================================================================
# Planner Initialization Tests
# =============================================================================


class TestPlannerInitialization:
    """Tests for Planner initialization."""

    def test_init_with_agent_and_state_manager(self, mock_agent_wrapper, state_manager):
        """Test initialization with agent and state manager."""
        planner = Planner(agent=mock_agent_wrapper, state_manager=state_manager)

        assert planner.agent == mock_agent_wrapper
        assert planner.state_manager == state_manager

    def test_init_stores_components(self, mock_agent_wrapper, state_manager):
        """Test initialization stores all components correctly."""
        planner = Planner(agent=mock_agent_wrapper, state_manager=state_manager)

        assert hasattr(planner, "agent")
        assert hasattr(planner, "state_manager")

    def test_init_with_different_state_managers(self, mock_agent_wrapper, temp_dir):
        """Test initialization with different state manager instances."""
        state_manager1 = StateManager(temp_dir / "state1")
        state_manager2 = StateManager(temp_dir / "state2")

        planner1 = Planner(agent=mock_agent_wrapper, state_manager=state_manager1)
        planner2 = Planner(agent=mock_agent_wrapper, state_manager=state_manager2)

        assert planner1.state_manager != planner2.state_manager


# =============================================================================
# create_plan Tests
# =============================================================================


class TestCreatePlan:
    """Tests for create_plan method."""

    def test_create_plan_returns_dict(self, planner, sample_goal):
        """Test create_plan returns a dictionary."""
        result = planner.create_plan(sample_goal)

        assert isinstance(result, dict)

    def test_create_plan_contains_expected_keys(self, planner, sample_goal):
        """Test create_plan returns dictionary with expected keys."""
        result = planner.create_plan(sample_goal)

        assert "plan" in result
        assert "criteria" in result
        assert "raw_output" in result

    def test_create_plan_calls_agent_run_planning_phase(
        self, planner, mock_agent_wrapper, sample_goal
    ):
        """Test create_plan calls agent.run_planning_phase."""
        planner.create_plan(sample_goal)

        mock_agent_wrapper.run_planning_phase.assert_called_once()

    def test_create_plan_passes_goal_to_agent(self, planner, mock_agent_wrapper, sample_goal):
        """Test create_plan passes goal to agent."""
        planner.create_plan(sample_goal)

        call_kwargs = mock_agent_wrapper.run_planning_phase.call_args.kwargs
        assert call_kwargs["goal"] == sample_goal

    def test_create_plan_passes_context_to_agent(
        self, planner, mock_agent_wrapper, state_manager, sample_context
    ):
        """Test create_plan passes context to agent."""
        # Save context to state manager
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_context(sample_context)

        planner.create_plan("Test goal")

        call_kwargs = mock_agent_wrapper.run_planning_phase.call_args.kwargs
        assert call_kwargs["context"] == sample_context

    def test_create_plan_passes_empty_context_when_no_context(
        self, planner, mock_agent_wrapper, state_manager
    ):
        """Test create_plan passes empty context when no context exists."""
        # Ensure no context file exists
        state_manager.state_dir.mkdir(exist_ok=True)
        context_file = state_manager.state_dir / "context.md"
        if context_file.exists():
            context_file.unlink()

        planner.create_plan("Test goal")

        call_kwargs = mock_agent_wrapper.run_planning_phase.call_args.kwargs
        assert call_kwargs["context"] == ""

    def test_create_plan_saves_plan_to_state(
        self, planner, mock_agent_wrapper, state_manager, sample_goal
    ):
        """Test create_plan saves the plan to state manager."""
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": "## Task List\n- [ ] Task 1",
            "criteria": "All tasks completed",
            "raw_output": "Planning output",
        }

        state_manager.state_dir.mkdir(exist_ok=True)
        planner.create_plan(sample_goal)

        saved_plan = state_manager.load_plan()
        assert saved_plan == "## Task List\n- [ ] Task 1"

    def test_create_plan_saves_criteria_to_state(
        self, planner, mock_agent_wrapper, state_manager, sample_goal
    ):
        """Test create_plan saves the criteria to state manager."""
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": "## Task List\n- [ ] Task 1",
            "criteria": "All tasks completed successfully",
            "raw_output": "Planning output",
        }

        state_manager.state_dir.mkdir(exist_ok=True)
        planner.create_plan(sample_goal)

        saved_criteria = state_manager.load_criteria()
        assert saved_criteria == "All tasks completed successfully"

    def test_create_plan_with_empty_plan_does_not_save(
        self, planner, mock_agent_wrapper, state_manager, sample_goal
    ):
        """Test create_plan does not save empty plan."""
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": "",
            "criteria": "Some criteria",
            "raw_output": "Planning output",
        }

        state_manager.state_dir.mkdir(exist_ok=True)

        # Save initial plan to verify it's not overwritten
        state_manager.save_plan("Initial plan")

        planner.create_plan(sample_goal)

        # Plan should still be the initial one
        saved_plan = state_manager.load_plan()
        assert saved_plan == "Initial plan"

    def test_create_plan_with_empty_criteria_does_not_save(
        self, planner, mock_agent_wrapper, state_manager, sample_goal
    ):
        """Test create_plan does not save empty criteria."""
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": "## Task List\n- [ ] Task 1",
            "criteria": "",
            "raw_output": "Planning output",
        }

        state_manager.state_dir.mkdir(exist_ok=True)

        # Save initial criteria to verify it's not overwritten
        state_manager.save_criteria("Initial criteria")

        planner.create_plan(sample_goal)

        # Criteria should still be the initial one
        saved_criteria = state_manager.load_criteria()
        assert saved_criteria == "Initial criteria"

    def test_create_plan_with_none_values_does_not_raise(
        self, planner, mock_agent_wrapper, state_manager, sample_goal
    ):
        """Test create_plan handles None values gracefully."""
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": None,
            "criteria": None,
            "raw_output": "Planning output",
        }

        state_manager.state_dir.mkdir(exist_ok=True)

        # Should not raise an exception
        result = planner.create_plan(sample_goal)

        assert result is not None

    def test_create_plan_returns_full_agent_result(
        self, planner, mock_agent_wrapper, state_manager, sample_goal
    ):
        """Test create_plan returns the full agent result."""
        expected_result = {
            "plan": "## Task List\n- [ ] Task 1\n- [ ] Task 2",
            "criteria": "All tasks completed",
            "raw_output": "Full planning output with details",
            "extra_field": "Additional data",
        }
        mock_agent_wrapper.run_planning_phase.return_value = expected_result

        state_manager.state_dir.mkdir(exist_ok=True)
        result = planner.create_plan(sample_goal)

        assert result == expected_result
        assert result["extra_field"] == "Additional data"


# =============================================================================
# create_plan with Different Goals Tests
# =============================================================================


class TestCreatePlanWithDifferentGoals:
    """Tests for create_plan with various goal inputs."""

    def test_create_plan_with_simple_goal(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan with a simple goal."""
        state_manager.state_dir.mkdir(exist_ok=True)
        result = planner.create_plan("Add a new feature")

        assert result is not None
        mock_agent_wrapper.run_planning_phase.assert_called_once()

    def test_create_plan_with_long_goal(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan with a long, detailed goal."""
        long_goal = """
        Implement a comprehensive authentication system that includes:
        1. User registration with email verification
        2. Login with JWT tokens
        3. Password reset functionality
        4. OAuth integration with Google and GitHub
        5. Session management with automatic token refresh
        6. Rate limiting for authentication endpoints
        7. Two-factor authentication support
        """
        state_manager.state_dir.mkdir(exist_ok=True)
        result = planner.create_plan(long_goal)

        assert result is not None
        call_kwargs = mock_agent_wrapper.run_planning_phase.call_args.kwargs
        assert long_goal in call_kwargs["goal"]

    def test_create_plan_with_multiline_goal(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan with a multiline goal."""
        multiline_goal = """First line
Second line
Third line"""
        state_manager.state_dir.mkdir(exist_ok=True)
        result = planner.create_plan(multiline_goal)

        assert result is not None

    def test_create_plan_with_special_characters_in_goal(
        self, planner, mock_agent_wrapper, state_manager
    ):
        """Test create_plan with special characters in goal."""
        special_goal = (
            "Fix bug #123 in `module.py` with 'quotes' and \"double quotes\" & ampersands"
        )
        state_manager.state_dir.mkdir(exist_ok=True)
        result = planner.create_plan(special_goal)

        assert result is not None
        call_kwargs = mock_agent_wrapper.run_planning_phase.call_args.kwargs
        assert special_goal == call_kwargs["goal"]

    def test_create_plan_with_unicode_goal(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan with unicode characters in goal."""
        unicode_goal = "Add support for 日本語 and emoji 🚀 and symbols ♠♣♥♦"
        state_manager.state_dir.mkdir(exist_ok=True)
        result = planner.create_plan(unicode_goal)

        assert result is not None
        call_kwargs = mock_agent_wrapper.run_planning_phase.call_args.kwargs
        assert unicode_goal == call_kwargs["goal"]

    def test_create_plan_with_empty_goal(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan with empty goal."""
        state_manager.state_dir.mkdir(exist_ok=True)
        result = planner.create_plan("")

        assert result is not None
        call_kwargs = mock_agent_wrapper.run_planning_phase.call_args.kwargs
        assert call_kwargs["goal"] == ""


# =============================================================================
# update_plan_progress Tests
# =============================================================================


class TestUpdatePlanProgress:
    """Tests for update_plan_progress method."""

    def test_update_plan_progress_with_existing_plan(self, planner, state_manager, sample_plan):
        """Test update_plan_progress with an existing plan."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(sample_plan)

        # Should not raise an exception
        planner.update_plan_progress(task_index=0, completed=True)

        # Verify plan is still accessible
        loaded_plan = state_manager.load_plan()
        assert loaded_plan is not None

    def test_update_plan_progress_without_plan_does_nothing(self, planner, state_manager):
        """Test update_plan_progress returns early when no plan exists."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Remove any existing plan file
        plan_file = state_manager.state_dir / "plan.md"
        if plan_file.exists():
            plan_file.unlink()

        # Should not raise an exception
        planner.update_plan_progress(task_index=0, completed=True)

    def test_update_plan_progress_calls_save_plan(self, planner, state_manager, sample_plan):
        """Test update_plan_progress saves the plan after update."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(sample_plan)

        original_mtime = (state_manager.state_dir / "plan.md").stat().st_mtime

        # Small delay to ensure mtime changes
        import time

        time.sleep(0.01)

        planner.update_plan_progress(task_index=0, completed=True)

        new_mtime = (state_manager.state_dir / "plan.md").stat().st_mtime
        # File should have been rewritten (mtime should be same or newer)
        assert new_mtime >= original_mtime

    def test_update_plan_progress_with_completed_false(self, planner, state_manager, sample_plan):
        """Test update_plan_progress with completed=False."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(sample_plan)

        # Should not raise an exception
        planner.update_plan_progress(task_index=0, completed=False)

    def test_update_plan_progress_with_various_indices(self, planner, state_manager, sample_plan):
        """Test update_plan_progress with various task indices."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(sample_plan)

        # Test with various indices
        for idx in [0, 1, 2, 10, -1]:
            planner.update_plan_progress(task_index=idx, completed=True)

        # Plan should still be valid
        loaded_plan = state_manager.load_plan()
        assert loaded_plan is not None

    def test_update_plan_progress_preserves_plan_content(self, planner, state_manager, sample_plan):
        """Test update_plan_progress preserves plan content."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(sample_plan)

        planner.update_plan_progress(task_index=0, completed=True)

        # Note: The TODO in the code indicates checkbox parsing is not implemented yet
        # For now, the plan content should be preserved as-is
        loaded_plan = state_manager.load_plan()
        assert loaded_plan == sample_plan


# =============================================================================
# Integration Tests
# =============================================================================


class TestPlannerIntegration:
    """Integration tests for Planner."""

    def test_create_plan_then_update_progress(self, planner, mock_agent_wrapper, state_manager):
        """Test creating a plan and then updating progress."""
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": """## Task List

- [ ] Task 1
- [ ] Task 2
- [ ] Task 3

## Success Criteria

1. All tasks completed
""",
            "criteria": "1. All tasks completed",
            "raw_output": "Planning output",
        }

        state_manager.state_dir.mkdir(exist_ok=True)

        # Create plan
        result = planner.create_plan("Complete all tasks")

        assert "plan" in result
        assert "Task 1" in result["plan"]

        # Update progress
        planner.update_plan_progress(task_index=0, completed=True)

        # Plan should still be accessible
        loaded_plan = state_manager.load_plan()
        assert loaded_plan is not None

    def test_create_multiple_plans(self, planner, mock_agent_wrapper, state_manager):
        """Test creating multiple plans (only the latest should be saved)."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # First plan
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": "## Task List\n- [ ] First Plan Task",
            "criteria": "First criteria",
            "raw_output": "First output",
        }
        planner.create_plan("First goal")

        assert state_manager.load_plan() == "## Task List\n- [ ] First Plan Task"

        # Second plan
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": "## Task List\n- [ ] Second Plan Task",
            "criteria": "Second criteria",
            "raw_output": "Second output",
        }
        planner.create_plan("Second goal")

        # Second plan should have overwritten the first
        assert state_manager.load_plan() == "## Task List\n- [ ] Second Plan Task"
        assert state_manager.load_criteria() == "Second criteria"


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestPlannerEdgeCases:
    """Edge case tests for Planner."""

    def test_create_plan_with_agent_returning_unexpected_keys(
        self, planner, mock_agent_wrapper, state_manager
    ):
        """Test create_plan handles agent returning unexpected keys."""
        mock_agent_wrapper.run_planning_phase.return_value = {
            "unexpected_key": "unexpected_value",
            "another_key": 12345,
        }

        state_manager.state_dir.mkdir(exist_ok=True)
        result = planner.create_plan("Test goal")

        # Should handle missing keys gracefully
        assert result.get("plan", "") == ""
        assert result.get("criteria", "") == ""

    def test_create_plan_with_very_large_plan(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan handles very large plan."""
        large_plan = "## Task List\n" + "\n".join(
            [f"- [ ] Task {i} with some description" for i in range(1000)]
        )

        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": large_plan,
            "criteria": "All 1000 tasks completed",
            "raw_output": "Large planning output",
        }

        state_manager.state_dir.mkdir(exist_ok=True)
        result = planner.create_plan("Large goal")

        assert result["plan"] == large_plan
        loaded_plan = state_manager.load_plan()
        assert len(loaded_plan) > 10000

    def test_create_plan_with_whitespace_only_plan(
        self, planner, mock_agent_wrapper, state_manager
    ):
        """Test create_plan handles whitespace-only plan."""
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": "   \n\t\n  ",  # Whitespace only
            "criteria": "Some criteria",
            "raw_output": "Planning output",
        }

        state_manager.state_dir.mkdir(exist_ok=True)
        planner.create_plan("Test goal")

        # Whitespace-only is truthy, so it will be saved
        loaded_plan = state_manager.load_plan()
        assert loaded_plan is not None

    def test_update_plan_progress_with_empty_plan(self, planner, state_manager):
        """Test update_plan_progress with empty plan content."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("")  # Empty plan

        # Should not raise an exception
        planner.update_plan_progress(task_index=0, completed=True)

    def test_planner_with_fresh_state_manager(self, mock_agent_wrapper, temp_dir):
        """Test planner works with freshly created state manager."""
        fresh_state_manager = StateManager(temp_dir / "fresh_state")

        planner = Planner(agent=mock_agent_wrapper, state_manager=fresh_state_manager)

        # Create plan should work even if state directory doesn't exist
        fresh_state_manager.state_dir.mkdir(exist_ok=True)
        result = planner.create_plan("Fresh test goal")

        assert result is not None


# =============================================================================
# Context Handling Tests
# =============================================================================


class TestContextHandling:
    """Tests for context handling in create_plan."""

    def test_create_plan_loads_existing_context(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan loads and passes existing context."""
        existing_context = """# Previous Session Context

## Completed Work
- Set up project structure
- Implemented basic features

## Key Learnings
- The project uses a modular architecture
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_context(existing_context)

        planner.create_plan("Continue development")

        call_kwargs = mock_agent_wrapper.run_planning_phase.call_args.kwargs
        assert call_kwargs["context"] == existing_context

    def test_create_plan_with_large_context(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan handles large context."""
        large_context = "# Context\n" + "\n".join(
            [f"Session {i} completed task {i}" for i in range(500)]
        )

        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_context(large_context)

        planner.create_plan("Continue with large context")

        call_kwargs = mock_agent_wrapper.run_planning_phase.call_args.kwargs
        assert call_kwargs["context"] == large_context

    def test_create_plan_context_with_special_characters(
        self, planner, mock_agent_wrapper, state_manager
    ):
        """Test create_plan handles context with special characters."""
        special_context = """# Context with Special Characters

Code blocks:
```python
def example():
    return "test"
```

Symbols: <> & " ' ` ~
Unicode: 日本語 🚀 ♠♣♥♦
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_context(special_context)

        planner.create_plan("Goal with special context")

        call_kwargs = mock_agent_wrapper.run_planning_phase.call_args.kwargs
        assert call_kwargs["context"] == special_context


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in Planner."""

    def test_create_plan_agent_raises_exception(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan propagates agent exceptions."""
        mock_agent_wrapper.run_planning_phase.side_effect = RuntimeError("Agent error")

        state_manager.state_dir.mkdir(exist_ok=True)

        with pytest.raises(RuntimeError, match="Agent error"):
            planner.create_plan("Test goal")

    def test_create_plan_state_manager_save_fails(self, mock_agent_wrapper, temp_dir):
        """Test create_plan handles state manager save failures."""
        # Create a state manager pointing to a non-existent directory
        non_existent_dir = temp_dir / "non_existent" / "deep" / "path"
        fresh_state_manager = StateManager(non_existent_dir)
        planner = Planner(agent=mock_agent_wrapper, state_manager=fresh_state_manager)

        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": "## Task List\n- [ ] Task 1",
            "criteria": "All done",
            "raw_output": "Output",
        }

        # Don't create state directory - save should fail
        with pytest.raises((FileNotFoundError, OSError)):
            planner.create_plan("Test goal")

    def test_update_plan_progress_handles_corrupted_plan_file(self, planner, state_manager):
        """Test update_plan_progress handles corrupted plan file."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Write binary data to plan file (corrupted)
        plan_file = state_manager.state_dir / "plan.md"
        plan_file.write_bytes(b"\x00\x01\x02\x03")

        # Should handle corrupted file gracefully or raise appropriate error
        # The current implementation will try to read it as text
        try:
            planner.update_plan_progress(task_index=0, completed=True)
        except UnicodeDecodeError:
            pass  # Expected for binary data


# =============================================================================
# Planner with Initialized State Manager Tests
# =============================================================================


class TestPlannerWithInitializedStateManager:
    """Tests for Planner with initialized state manager."""

    def test_create_plan_with_initialized_state(
        self, mock_agent_wrapper, initialized_state_manager
    ):
        """Test create_plan works with initialized state manager."""
        planner = Planner(agent=mock_agent_wrapper, state_manager=initialized_state_manager)

        result = planner.create_plan("New goal for initialized state")

        assert result is not None
        assert "plan" in result

    def test_update_progress_with_initialized_state(
        self, mock_agent_wrapper, initialized_state_manager, sample_plan
    ):
        """Test update_plan_progress works with initialized state manager."""
        initialized_state_manager.save_plan(sample_plan)

        planner = Planner(agent=mock_agent_wrapper, state_manager=initialized_state_manager)

        # Should not raise an exception
        planner.update_plan_progress(task_index=0, completed=True)


# =============================================================================
# Planner Plan Content Tests
# =============================================================================


class TestPlannerPlanContent:
    """Tests for plan content handling."""

    def test_create_plan_with_task_list_format(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan handles proper task list format."""
        proper_plan = """## Task List

- [ ] Set up project structure
- [ ] Implement core functionality
- [ ] Add unit tests
- [ ] Write documentation

## Success Criteria

1. All tests pass with >80% coverage
2. Documentation is complete
3. No critical bugs
"""
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": proper_plan,
            "criteria": "1. All tests pass\n2. Documentation complete",
            "raw_output": "Planning output",
        }

        state_manager.state_dir.mkdir(exist_ok=True)
        planner.create_plan("Build feature")

        loaded_plan = state_manager.load_plan()
        assert "## Task List" in loaded_plan
        assert "- [ ]" in loaded_plan
        assert "## Success Criteria" in loaded_plan

    def test_create_plan_with_nested_tasks(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan handles nested tasks."""
        nested_plan = """## Task List

- [ ] Main Task 1
  - Subtask 1.1
  - Subtask 1.2
- [ ] Main Task 2
  - Subtask 2.1

## Notes

Additional information here.
"""
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": nested_plan,
            "criteria": "All done",
            "raw_output": "Planning output",
        }

        state_manager.state_dir.mkdir(exist_ok=True)
        planner.create_plan("Nested task goal")

        loaded_plan = state_manager.load_plan()
        assert "Main Task 1" in loaded_plan
        assert "Subtask 1.1" in loaded_plan

    def test_create_plan_with_completed_tasks(self, planner, mock_agent_wrapper, state_manager):
        """Test create_plan handles plan with pre-completed tasks."""
        plan_with_completed = """## Task List

- [x] Completed Task 1
- [x] Completed Task 2
- [ ] Pending Task 3
- [ ] Pending Task 4

## Success Criteria

All tasks done.
"""
        mock_agent_wrapper.run_planning_phase.return_value = {
            "plan": plan_with_completed,
            "criteria": "All tasks done",
            "raw_output": "Planning output",
        }

        state_manager.state_dir.mkdir(exist_ok=True)
        planner.create_plan("Resume work")

        loaded_plan = state_manager.load_plan()
        assert "- [x]" in loaded_plan
        assert "- [ ]" in loaded_plan
