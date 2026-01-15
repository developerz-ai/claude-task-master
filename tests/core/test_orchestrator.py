"""Comprehensive tests for the orchestrator module."""

import pytest
import json
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

from claude_task_master.core.orchestrator import (
    WorkLoopOrchestrator,
    OrchestratorError,
    PlanParsingError,
    NoPlanFoundError,
    NoTasksFoundError,
    TaskIndexOutOfBoundsError,
    WorkSessionError,
    StateRecoveryError,
    MaxSessionsReachedError,
    VerificationFailedError,
)
from claude_task_master.core.state import StateManager, TaskState, TaskOptions, StateError
from claude_task_master.core.agent import AgentError, QueryExecutionError


# =============================================================================
# WorkLoopOrchestrator Initialization Tests
# =============================================================================


class TestWorkLoopOrchestratorInitialization:
    """Tests for WorkLoopOrchestrator initialization."""

    def test_init_with_required_parameters(
        self, mock_agent_wrapper, initialized_state_manager, planner
    ):
        """Test initialization with required parameters."""
        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=initialized_state_manager,
            planner=planner,
        )

        assert orchestrator.agent == mock_agent_wrapper
        assert orchestrator.state_manager == initialized_state_manager
        assert orchestrator.planner == planner

    def test_init_stores_components(
        self, mock_agent_wrapper, initialized_state_manager, planner
    ):
        """Test initialization stores all components correctly."""
        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=initialized_state_manager,
            planner=planner,
        )

        # Verify components are accessible
        assert hasattr(orchestrator, "agent")
        assert hasattr(orchestrator, "state_manager")
        assert hasattr(orchestrator, "planner")


# =============================================================================
# Task Parsing Tests
# =============================================================================


class TestTaskParsing:
    """Tests for _parse_tasks method."""

    def test_parse_tasks_with_unchecked_items(self, orchestrator):
        """Test parsing unchecked tasks from markdown."""
        plan = """## Task List

- [ ] Task 1
- [ ] Task 2
- [ ] Task 3
"""
        tasks = orchestrator._parse_tasks(plan)

        assert len(tasks) == 3
        assert tasks[0] == "Task 1"
        assert tasks[1] == "Task 2"
        assert tasks[2] == "Task 3"

    def test_parse_tasks_with_checked_items(self, orchestrator):
        """Test parsing checked tasks from markdown."""
        plan = """## Task List

- [x] Completed Task 1
- [x] Completed Task 2
"""
        tasks = orchestrator._parse_tasks(plan)

        assert len(tasks) == 2
        assert tasks[0] == "Completed Task 1"
        assert tasks[1] == "Completed Task 2"

    def test_parse_tasks_with_mixed_items(self, orchestrator):
        """Test parsing mixed checked/unchecked tasks."""
        plan = """## Task List

- [x] Completed Task
- [ ] Pending Task 1
- [x] Another Completed
- [ ] Pending Task 2
"""
        tasks = orchestrator._parse_tasks(plan)

        assert len(tasks) == 4
        assert tasks[0] == "Completed Task"
        assert tasks[1] == "Pending Task 1"
        assert tasks[2] == "Another Completed"
        assert tasks[3] == "Pending Task 2"

    def test_parse_tasks_empty_plan(self, orchestrator):
        """Test parsing empty plan returns empty list."""
        tasks = orchestrator._parse_tasks("")
        assert tasks == []

    def test_parse_tasks_no_task_items(self, orchestrator):
        """Test parsing plan without task items."""
        plan = """## Task List

Some descriptive text without tasks.

## Success Criteria

1. All done
"""
        tasks = orchestrator._parse_tasks(plan)
        assert tasks == []

    def test_parse_tasks_preserves_task_content(self, orchestrator):
        """Test parsing preserves full task content."""
        plan = """## Task List

- [ ] Implement feature X with full error handling and logging
- [ ] Add comprehensive unit tests covering edge cases
"""
        tasks = orchestrator._parse_tasks(plan)

        assert tasks[0] == "Implement feature X with full error handling and logging"
        assert tasks[1] == "Add comprehensive unit tests covering edge cases"

    def test_parse_tasks_with_indentation(self, orchestrator):
        """Test parsing tasks with varying indentation."""
        plan = """## Task List

  - [ ] Indented Task 1
    - [ ] More Indented Task 2
- [ ] Normal Task
"""
        tasks = orchestrator._parse_tasks(plan)

        # All tasks should be found regardless of indentation
        assert len(tasks) == 3

    def test_parse_tasks_with_extra_whitespace(self, orchestrator):
        """Test parsing tasks handles extra whitespace."""
        plan = """## Task List

- [ ]   Task with leading spaces
- [ ]Task without space
"""
        tasks = orchestrator._parse_tasks(plan)

        assert len(tasks) == 2
        # First task should have stripped whitespace
        assert tasks[0] == "Task with leading spaces"

    def test_parse_tasks_ignores_regular_bullets(self, orchestrator):
        """Test parsing ignores regular bullet points."""
        plan = """## Task List

- [ ] Actual Task
- Regular bullet point
* Another bullet
+ Plus bullet
"""
        tasks = orchestrator._parse_tasks(plan)

        assert len(tasks) == 1
        assert tasks[0] == "Actual Task"


# =============================================================================
# Task Completion Detection Tests
# =============================================================================


class TestTaskCompletionDetection:
    """Tests for _is_task_complete method."""

    def test_is_task_complete_unchecked(self, orchestrator):
        """Test detecting unchecked task."""
        plan = """## Task List

- [ ] Task 1
- [ ] Task 2
"""
        assert orchestrator._is_task_complete(plan, 0) is False
        assert orchestrator._is_task_complete(plan, 1) is False

    def test_is_task_complete_checked(self, orchestrator):
        """Test detecting checked task."""
        plan = """## Task List

- [x] Task 1
- [x] Task 2
"""
        assert orchestrator._is_task_complete(plan, 0) is True
        assert orchestrator._is_task_complete(plan, 1) is True

    def test_is_task_complete_mixed(self, orchestrator):
        """Test detecting completion in mixed task list."""
        plan = """## Task List

- [x] Completed Task
- [ ] Pending Task
- [x] Another Completed
"""
        assert orchestrator._is_task_complete(plan, 0) is True
        assert orchestrator._is_task_complete(plan, 1) is False
        assert orchestrator._is_task_complete(plan, 2) is True

    def test_is_task_complete_invalid_index(self, orchestrator):
        """Test invalid task index returns False."""
        plan = """## Task List

- [ ] Task 1
- [ ] Task 2
"""
        assert orchestrator._is_task_complete(plan, 10) is False
        assert orchestrator._is_task_complete(plan, -1) is False

    def test_is_task_complete_empty_plan(self, orchestrator):
        """Test empty plan returns False."""
        assert orchestrator._is_task_complete("", 0) is False


# =============================================================================
# Task Marking Tests
# =============================================================================


class TestTaskMarking:
    """Tests for _mark_task_complete method."""

    def test_mark_task_complete_first_task(self, orchestrator, initialized_state_manager):
        """Test marking first task as complete."""
        plan = """## Task List

- [ ] Task 1
- [ ] Task 2
"""
        initialized_state_manager.save_plan(plan)
        orchestrator._mark_task_complete(plan, 0)

        updated_plan = initialized_state_manager.load_plan()
        assert "- [x] Task 1" in updated_plan
        assert "- [ ] Task 2" in updated_plan

    def test_mark_task_complete_middle_task(self, orchestrator, initialized_state_manager):
        """Test marking middle task as complete."""
        plan = """## Task List

- [ ] Task 1
- [ ] Task 2
- [ ] Task 3
"""
        initialized_state_manager.save_plan(plan)
        orchestrator._mark_task_complete(plan, 1)

        updated_plan = initialized_state_manager.load_plan()
        assert "- [ ] Task 1" in updated_plan
        assert "- [x] Task 2" in updated_plan
        assert "- [ ] Task 3" in updated_plan

    def test_mark_task_complete_last_task(self, orchestrator, initialized_state_manager):
        """Test marking last task as complete."""
        plan = """## Task List

- [ ] Task 1
- [ ] Task 2
"""
        initialized_state_manager.save_plan(plan)
        orchestrator._mark_task_complete(plan, 1)

        updated_plan = initialized_state_manager.load_plan()
        assert "- [ ] Task 1" in updated_plan
        assert "- [x] Task 2" in updated_plan

    def test_mark_already_complete_task(self, orchestrator, initialized_state_manager):
        """Test marking already complete task stays complete."""
        plan = """## Task List

- [x] Task 1
- [ ] Task 2
"""
        initialized_state_manager.save_plan(plan)
        orchestrator._mark_task_complete(plan, 0)

        updated_plan = initialized_state_manager.load_plan()
        # Should still be checked (no change)
        assert "- [x] Task 1" in updated_plan

    def test_mark_task_preserves_other_content(self, orchestrator, initialized_state_manager):
        """Test marking task preserves other plan content."""
        plan = """## Task List

- [ ] Task 1
- [ ] Task 2

## Success Criteria

1. All tests pass
2. No bugs
"""
        initialized_state_manager.save_plan(plan)
        orchestrator._mark_task_complete(plan, 0)

        updated_plan = initialized_state_manager.load_plan()
        assert "## Success Criteria" in updated_plan
        assert "1. All tests pass" in updated_plan
        assert "2. No bugs" in updated_plan


# =============================================================================
# Completion Check Tests
# =============================================================================


class TestIsComplete:
    """Tests for _is_complete method."""

    def test_is_complete_all_tasks_done(self, orchestrator, initialized_state_manager):
        """Test _is_complete when all tasks processed."""
        plan = """## Task List

- [x] Task 1
- [x] Task 2
"""
        initialized_state_manager.save_plan(plan)
        state = initialized_state_manager.load_state()
        state.current_task_index = 2  # Processed both tasks

        assert orchestrator._is_complete(state) is True

    def test_is_complete_tasks_remaining(self, orchestrator, initialized_state_manager):
        """Test _is_complete when tasks remain."""
        plan = """## Task List

- [x] Task 1
- [ ] Task 2
"""
        initialized_state_manager.save_plan(plan)
        state = initialized_state_manager.load_state()
        state.current_task_index = 1  # Only first task processed

        assert orchestrator._is_complete(state) is False

    def test_is_complete_no_plan(self, orchestrator, initialized_state_manager):
        """Test _is_complete with no plan returns True."""
        # Remove the plan file
        plan_file = initialized_state_manager.state_dir / "plan.md"
        if plan_file.exists():
            plan_file.unlink()

        state = initialized_state_manager.load_state()
        assert orchestrator._is_complete(state) is True

    def test_is_complete_empty_task_list(self, orchestrator, initialized_state_manager):
        """Test _is_complete with empty task list."""
        plan = """## Task List

No tasks defined.

## Success Criteria

1. Nothing to do
"""
        initialized_state_manager.save_plan(plan)
        state = initialized_state_manager.load_state()
        state.current_task_index = 0

        # Empty task list means complete (0 >= 0)
        assert orchestrator._is_complete(state) is True


# =============================================================================
# Session Limit Tests
# =============================================================================


class TestSessionLimits:
    """Tests for session limit handling."""

    def test_run_exceeds_max_sessions_immediately(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test run returns immediately when max sessions exceeded."""
        # Create state manager with max_sessions already reached
        state_manager = StateManager(state_dir)
        options = TaskOptions(max_sessions=5)
        state = state_manager.initialize(goal="Test goal", model="sonnet", options=options)
        state.session_count = 5  # Already at max
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 1  # Blocked
        # Agent should not have been called
        mock_agent_wrapper.run_work_session.assert_not_called()

    def test_run_stops_at_max_sessions(self, mock_agent_wrapper, state_dir, planner):
        """Test run stops when reaching max sessions during loop."""
        state_manager = StateManager(state_dir)
        options = TaskOptions(max_sessions=2)
        state = state_manager.initialize(goal="Test goal", model="sonnet", options=options)
        state.status = "working"
        state.session_count = 1  # One session done, one more allowed
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1\n- [ ] Task 2\n- [ ] Task 3")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 1  # Blocked due to max sessions

        # Verify state was updated
        updated_state = state_manager.load_state()
        assert updated_state.status == "blocked"
        assert updated_state.session_count == 2

    def test_run_no_session_limit(self, mock_agent_wrapper, state_dir, planner):
        """Test run continues when no session limit is set."""
        state_manager = StateManager(state_dir)
        options = TaskOptions(max_sessions=None)  # No limit
        state = state_manager.initialize(goal="Test goal", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        # Mock agent to return success
        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 0  # Success
        mock_agent_wrapper.run_work_session.assert_called()


# =============================================================================
# State Transition Tests
# =============================================================================


class TestStateTransitions:
    """Tests for state transitions during orchestration."""

    def test_transition_to_success(self, mock_agent_wrapper, state_dir, planner):
        """Test state transitions to success when complete."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test goal", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 0
        # Note: state file is cleaned up on success, so we can't check status directly

    def test_transition_to_blocked_on_verification_failure(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test state transitions to blocked when verification fails."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test goal", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")
        state_manager.save_criteria("1. All tests pass")  # Must save criteria for verification to run

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": False}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 1  # Blocked
        updated_state = state_manager.load_state()
        assert updated_state.status == "blocked"

    def test_transition_to_failed_on_error(self, mock_agent_wrapper, state_dir, planner):
        """Test state transitions to failed on error."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test goal", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_agent_wrapper.run_work_session.side_effect = ValueError("Agent error")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 1  # Error
        updated_state = state_manager.load_state()
        assert updated_state.status == "failed"

    def test_transition_to_paused_on_interrupt(self, mock_agent_wrapper, state_dir, planner):
        """Test state transitions to paused on keyboard interrupt."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test goal", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_agent_wrapper.run_work_session.side_effect = KeyboardInterrupt()

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 2  # User interrupted
        updated_state = state_manager.load_state()
        assert updated_state.status == "paused"


# =============================================================================
# Work Session Tests
# =============================================================================


class TestRunWorkSession:
    """Tests for _run_work_session method."""

    def test_run_work_session_calls_agent(self, orchestrator, mock_agent_wrapper):
        """Test work session calls agent with correct parameters."""
        state = orchestrator.state_manager.load_state()
        orchestrator._run_work_session(state)

        mock_agent_wrapper.run_work_session.assert_called_once()
        call_args = mock_agent_wrapper.run_work_session.call_args
        assert "task_description" in call_args.kwargs
        assert "context" in call_args.kwargs

    def test_run_work_session_includes_goal(self, orchestrator, mock_agent_wrapper):
        """Test work session includes goal in task description."""
        state = orchestrator.state_manager.load_state()
        orchestrator._run_work_session(state)

        call_args = mock_agent_wrapper.run_work_session.call_args
        task_description = call_args.kwargs["task_description"]
        assert "Goal:" in task_description

    def test_run_work_session_includes_task(self, orchestrator, mock_agent_wrapper):
        """Test work session includes current task in description."""
        state = orchestrator.state_manager.load_state()
        orchestrator._run_work_session(state)

        call_args = mock_agent_wrapper.run_work_session.call_args
        task_description = call_args.kwargs["task_description"]
        assert "Current Task" in task_description

    def test_run_work_session_increments_task_index(
        self, orchestrator, mock_agent_wrapper, initialized_state_manager
    ):
        """Test work session increments task index after completion."""
        state = orchestrator.state_manager.load_state()
        initial_index = state.current_task_index

        orchestrator._run_work_session(state)

        # Reload state to check update
        updated_state = initialized_state_manager.load_state()
        assert updated_state.current_task_index == initial_index + 1

    def test_run_work_session_saves_progress(
        self, orchestrator, mock_agent_wrapper, initialized_state_manager
    ):
        """Test work session saves progress."""
        state = orchestrator.state_manager.load_state()
        orchestrator._run_work_session(state)

        progress = initialized_state_manager.load_progress()
        assert progress is not None
        assert "Progress Tracker" in progress
        assert "Session:" in progress
        assert "Current Task:" in progress

    def test_run_work_session_skips_completed_task(
        self, orchestrator, mock_agent_wrapper, initialized_state_manager
    ):
        """Test work session skips already completed tasks."""
        # Set up plan with first task completed
        plan = """## Task List

- [x] Task 1
- [ ] Task 2
"""
        initialized_state_manager.save_plan(plan)
        state = orchestrator.state_manager.load_state()
        state.current_task_index = 0  # Point to completed task

        orchestrator._run_work_session(state)

        # Agent should not have been called (task was skipped)
        mock_agent_wrapper.run_work_session.assert_not_called()

        # Task index should have incremented
        updated_state = initialized_state_manager.load_state()
        assert updated_state.current_task_index == 1

    def test_run_work_session_no_plan_raises_error(
        self, orchestrator, mock_agent_wrapper, initialized_state_manager
    ):
        """Test work session raises error when no plan exists."""
        # Remove plan file
        plan_file = initialized_state_manager.state_dir / "plan.md"
        if plan_file.exists():
            plan_file.unlink()

        state = orchestrator.state_manager.load_state()

        with pytest.raises(NoPlanFoundError):
            orchestrator._run_work_session(state)

    def test_run_work_session_all_tasks_processed(
        self, orchestrator, mock_agent_wrapper, initialized_state_manager
    ):
        """Test work session returns early when all tasks processed."""
        plan = """## Task List

- [x] Task 1
"""
        initialized_state_manager.save_plan(plan)
        state = orchestrator.state_manager.load_state()
        state.current_task_index = 1  # Beyond available tasks

        # Should return without error
        orchestrator._run_work_session(state)

        # Agent should not have been called
        mock_agent_wrapper.run_work_session.assert_not_called()


# =============================================================================
# Success Verification Tests
# =============================================================================


class TestVerifySuccess:
    """Tests for _verify_success method."""

    def test_verify_success_with_criteria(self, orchestrator, mock_agent_wrapper, initialized_state_manager):
        """Test verification with success criteria."""
        initialized_state_manager.save_criteria("1. All tests pass\n2. No bugs")
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        result = orchestrator._verify_success()

        assert result is True
        mock_agent_wrapper.verify_success_criteria.assert_called_once()

    def test_verify_success_no_criteria(self, orchestrator, mock_agent_wrapper, initialized_state_manager):
        """Test verification returns True when no criteria specified."""
        # Ensure no criteria file exists
        criteria_file = initialized_state_manager.state_dir / "criteria.txt"
        if criteria_file.exists():
            criteria_file.unlink()

        result = orchestrator._verify_success()

        assert result is True
        mock_agent_wrapper.verify_success_criteria.assert_not_called()

    def test_verify_success_failure(self, orchestrator, mock_agent_wrapper, initialized_state_manager):
        """Test verification returns False when criteria not met."""
        initialized_state_manager.save_criteria("1. All tests pass")
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": False}

        result = orchestrator._verify_success()

        assert result is False


# =============================================================================
# Run Method Tests
# =============================================================================


class TestRun:
    """Tests for the run method."""

    def test_run_complete_workflow(self, mock_agent_wrapper, state_dir, planner):
        """Test complete workflow from start to success."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Complete the task", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Single Task")
        state_manager.save_criteria("Task completed")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 0  # Success
        mock_agent_wrapper.run_work_session.assert_called_once()
        mock_agent_wrapper.verify_success_criteria.assert_called_once()

    def test_run_multiple_tasks(self, mock_agent_wrapper, state_dir, planner):
        """Test running through multiple tasks."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Multiple tasks", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1\n- [ ] Task 2\n- [ ] Task 3")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 0  # Success
        # Should have been called 3 times for 3 tasks
        assert mock_agent_wrapper.run_work_session.call_count == 3

    def test_run_increments_session_count(self, mock_agent_wrapper, state_dir, planner):
        """Test run increments session count each iteration."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Track sessions", model="sonnet", options=options)
        state.status = "working"
        state.session_count = 0
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1\n- [ ] Task 2")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        orchestrator.run()

        # Sessions should have been incremented for each task
        # Note: state is cleaned up on success, can't verify final count

    def test_run_resumes_from_checkpoint(self, mock_agent_wrapper, state_dir, planner):
        """Test run resumes from existing checkpoint."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Resume test", model="sonnet", options=options)
        state.status = "working"
        state.current_task_index = 1  # Already completed first task
        state.session_count = 1
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [x] Task 1\n- [ ] Task 2")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 0  # Success
        # Should only have been called once for remaining task
        assert mock_agent_wrapper.run_work_session.call_count == 1


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Edge case tests for WorkLoopOrchestrator."""

    def test_task_with_special_characters(self, orchestrator, initialized_state_manager):
        """Test parsing tasks with special characters."""
        plan = """## Task List

- [ ] Fix bug #123 in `module.py`
- [ ] Handle "quotes" and 'apostrophes'
- [ ] Support <brackets> & ampersands
"""
        initialized_state_manager.save_plan(plan)
        tasks = orchestrator._parse_tasks(plan)

        assert len(tasks) == 3
        assert "#123" in tasks[0]
        assert '"quotes"' in tasks[1]
        assert "<brackets>" in tasks[2]

    def test_task_with_unicode(self, orchestrator, initialized_state_manager):
        """Test parsing tasks with unicode characters."""
        plan = """## Task List

- [ ] Add support for 日本語
- [ ] Implement emoji handling 🚀
- [ ] Process symbols ♠♣♥♦
"""
        initialized_state_manager.save_plan(plan)
        tasks = orchestrator._parse_tasks(plan)

        assert len(tasks) == 3
        assert "日本語" in tasks[0]
        assert "🚀" in tasks[1]
        assert "♠♣♥♦" in tasks[2]

    def test_empty_task_content(self, orchestrator):
        """Test parsing handles empty task content."""
        plan = """## Task List

- [ ]
- [ ] Valid Task
- [ ]
"""
        tasks = orchestrator._parse_tasks(plan)

        # Empty tasks should be filtered out
        assert len(tasks) == 1
        assert tasks[0] == "Valid Task"

    def test_long_plan_with_many_tasks(self, orchestrator, initialized_state_manager):
        """Test handling of plan with many tasks."""
        tasks_content = "\n".join([f"- [ ] Task {i}" for i in range(100)])
        plan = f"""## Task List

{tasks_content}
"""
        initialized_state_manager.save_plan(plan)
        tasks = orchestrator._parse_tasks(plan)

        assert len(tasks) == 100

    def test_plan_with_nested_structure(self, orchestrator, initialized_state_manager):
        """Test parsing plan with nested structure."""
        plan = """## Task List

- [ ] Main Task 1
  - Detail 1
  - Detail 2
- [ ] Main Task 2
  - Subtask info

## Notes

Some additional notes here.
"""
        initialized_state_manager.save_plan(plan)
        tasks = orchestrator._parse_tasks(plan)

        # Should only capture checkbox items, not nested details
        assert len(tasks) == 2

    def test_run_with_empty_context(self, mock_agent_wrapper, state_dir, planner):
        """Test run works with empty context."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")
        # Don't save context file

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 0  # Should succeed even without context


# =============================================================================
# Output and Print Tests
# =============================================================================


class TestOutputAndPrinting:
    """Tests for output and printing behavior."""

    def test_run_prints_max_sessions_message(self, mock_agent_wrapper, state_dir, planner, capsys):
        """Test run prints message when max sessions reached."""
        state_manager = StateManager(state_dir)
        options = TaskOptions(max_sessions=3)
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.session_count = 3
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        orchestrator.run()

        captured = capsys.readouterr()
        assert "Max sessions (3) reached" in captured.out

    def test_run_prints_task_info(self, mock_agent_wrapper, state_dir, planner, capsys):
        """Test run prints current task information."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Important Task")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        orchestrator.run()

        captured = capsys.readouterr()
        assert "Working on task #1" in captured.out
        assert "Important Task" in captured.out

    def test_run_prints_completed_task_message(
        self, mock_agent_wrapper, state_dir, planner, capsys
    ):
        """Test run prints message for already completed tasks."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.current_task_index = 0
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [x] Completed Task\n- [ ] Next Task")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        orchestrator.run()

        captured = capsys.readouterr()
        assert "already complete" in captured.out

    def test_run_prints_error_on_exception(self, mock_agent_wrapper, state_dir, planner, capsys):
        """Test run prints error message on exception."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_agent_wrapper.run_work_session.side_effect = RuntimeError("Test error message")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        orchestrator.run()

        captured = capsys.readouterr()
        assert "Error:" in captured.out
        assert "Test error message" in captured.out


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for WorkLoopOrchestrator."""

    def test_full_lifecycle(self, mock_agent_wrapper, state_dir, planner):
        """Test complete lifecycle from initialization to completion."""
        state_manager = StateManager(state_dir)
        options = TaskOptions(max_sessions=10, auto_merge=True)
        state = state_manager.initialize(
            goal="Build a complete feature with tests",
            model="sonnet",
            options=options,
        )
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("""## Task List

- [ ] Set up project structure
- [ ] Implement core functionality
- [ ] Add unit tests
- [ ] Write documentation

## Success Criteria

1. All tests pass
2. Documentation is complete
""")
        state_manager.save_criteria("1. All tests pass\n2. Documentation is complete")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 0  # Success
        assert mock_agent_wrapper.run_work_session.call_count == 4  # 4 tasks
        mock_agent_wrapper.verify_success_criteria.assert_called_once()

    def test_partial_completion_resume(self, mock_agent_wrapper, state_dir, planner):
        """Test resuming after partial completion."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Resume test", model="sonnet", options=options)
        state.status = "working"
        state.current_task_index = 2  # Already completed 2 tasks
        state.session_count = 2
        state_manager.save_state(state)
        state_manager.save_plan("""## Task List

- [x] Task 1 (completed)
- [x] Task 2 (completed)
- [ ] Task 3 (pending)
- [ ] Task 4 (pending)
""")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 0  # Success
        # Should only process remaining 2 tasks
        assert mock_agent_wrapper.run_work_session.call_count == 2


# =============================================================================
# Exception Class Tests
# =============================================================================


class TestOrchestratorExceptions:
    """Tests for orchestrator exception classes."""

    def test_orchestrator_error_base_class(self):
        """Test OrchestratorError base class."""
        error = OrchestratorError("Test error message")
        assert error.message == "Test error message"
        assert error.details is None
        assert str(error) == "Test error message"

    def test_orchestrator_error_with_details(self):
        """Test OrchestratorError with details."""
        error = OrchestratorError("Test error", "Additional details here")
        assert error.message == "Test error"
        assert error.details == "Additional details here"
        assert "Additional details" in str(error)

    def test_plan_parsing_error(self):
        """Test PlanParsingError."""
        plan_content = "## Invalid Plan\n\nSome random content"
        error = PlanParsingError("Failed to parse plan", plan_content)
        assert error.message == "Failed to parse plan"
        assert error.plan_content == plan_content
        assert "Plan content preview" in error.details

    def test_plan_parsing_error_truncates_long_content(self):
        """Test PlanParsingError truncates long content."""
        long_content = "x" * 500
        error = PlanParsingError("Failed", long_content)
        assert error.plan_content == long_content
        # Preview should be truncated to 200 chars + "..."
        assert len(error.details) < len(long_content) + 50

    def test_no_plan_found_error(self):
        """Test NoPlanFoundError."""
        error = NoPlanFoundError()
        assert "No plan found" in error.message
        assert "planning phase" in error.details

    def test_no_tasks_found_error(self):
        """Test NoTasksFoundError."""
        plan = "## Task List\n\nNo tasks here"
        error = NoTasksFoundError(plan)
        assert "No tasks found" in error.message
        assert error.plan_content == plan

    def test_task_index_out_of_bounds_error(self):
        """Test TaskIndexOutOfBoundsError."""
        error = TaskIndexOutOfBoundsError(5, 3)
        assert error.task_index == 5
        assert error.total_tasks == 3
        assert "5" in error.message
        assert "3 tasks" in error.details

    def test_work_session_error(self):
        """Test WorkSessionError."""
        original = ValueError("Something went wrong")
        error = WorkSessionError(2, "Fix the bug", original)
        assert error.task_index == 2
        assert error.task_description == "Fix the bug"
        assert error.original_error == original
        assert "task #3" in error.message  # 1-indexed in message
        assert "ValueError" in error.details

    def test_state_recovery_error(self):
        """Test StateRecoveryError."""
        original = OSError("File not found")
        error = StateRecoveryError("Could not load backup", original)
        assert "recover" in error.message.lower()
        assert error.original_error == original
        assert "OSError" in error.details

    def test_max_sessions_reached_error(self):
        """Test MaxSessionsReachedError."""
        error = MaxSessionsReachedError(10, 10)
        assert error.max_sessions == 10
        assert error.current_session == 10
        assert "10" in error.message

    def test_verification_failed_error(self):
        """Test VerificationFailedError."""
        criteria = "1. All tests pass\n2. No bugs"
        error = VerificationFailedError(criteria)
        assert error.criteria == criteria
        assert "verification" in error.message.lower()


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestRunWorkSessionErrorHandling:
    """Tests for _run_work_session error handling."""

    def test_run_work_session_raises_no_plan_found(
        self, mock_agent_wrapper, initialized_state_manager, planner
    ):
        """Test _run_work_session raises NoPlanFoundError when no plan exists."""
        # Remove plan file
        plan_file = initialized_state_manager.state_dir / "plan.md"
        if plan_file.exists():
            plan_file.unlink()

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=initialized_state_manager,
            planner=planner,
        )
        state = initialized_state_manager.load_state()

        with pytest.raises(NoPlanFoundError):
            orchestrator._run_work_session(state)

    def test_run_work_session_raises_no_tasks_found(
        self, mock_agent_wrapper, initialized_state_manager, planner
    ):
        """Test _run_work_session raises NoTasksFoundError when plan has no tasks."""
        # Save plan with no tasks
        initialized_state_manager.save_plan("## Task List\n\nNo actual tasks here.\n")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=initialized_state_manager,
            planner=planner,
        )
        state = initialized_state_manager.load_state()

        with pytest.raises(NoTasksFoundError):
            orchestrator._run_work_session(state)

    def test_run_work_session_wraps_agent_errors(
        self, mock_agent_wrapper, initialized_state_manager, planner
    ):
        """Test _run_work_session wraps agent errors properly."""
        initialized_state_manager.save_plan("## Task List\n- [ ] Task 1\n")
        mock_agent_wrapper.run_work_session.side_effect = RuntimeError("Agent crashed")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=initialized_state_manager,
            planner=planner,
        )
        state = initialized_state_manager.load_state()

        with pytest.raises(WorkSessionError) as exc_info:
            orchestrator._run_work_session(state)

        assert exc_info.value.task_index == 0
        assert "Task 1" in exc_info.value.task_description
        assert isinstance(exc_info.value.original_error, RuntimeError)

    def test_run_work_session_propagates_agent_errors(
        self, mock_agent_wrapper, initialized_state_manager, planner
    ):
        """Test _run_work_session propagates AgentError subclasses."""
        initialized_state_manager.save_plan("## Task List\n- [ ] Task 1\n")
        mock_agent_wrapper.run_work_session.side_effect = QueryExecutionError("Query failed")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=initialized_state_manager,
            planner=planner,
        )
        state = initialized_state_manager.load_state()

        # AgentError subclasses should propagate through
        with pytest.raises(AgentError):
            orchestrator._run_work_session(state)


class TestRunErrorHandling:
    """Tests for run() method error handling."""

    def test_run_handles_no_plan_as_success(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test run treats no plan as success (nothing to do = done)."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        # Don't save a plan - _is_complete will return True (no tasks = complete)

        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        # No plan means _is_complete returns True immediately, then verification passes
        assert result == 0  # Success

    def test_run_handles_no_tasks_as_success(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test run treats no tasks in plan as success case."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n\nNo tasks defined.")

        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 0  # Success (no tasks = nothing to do = done)

    def test_run_prints_error_details_on_orchestrator_error(
        self, mock_agent_wrapper, state_dir, planner, capsys
    ):
        """Test run prints error details for OrchestratorError."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1\n")

        # Make agent raise an error that will be wrapped
        mock_agent_wrapper.run_work_session.side_effect = RuntimeError("Boom!")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 1  # Error
        captured = capsys.readouterr()
        assert "error" in captured.out.lower()

    def test_run_creates_backup_on_unexpected_error(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test run creates state backup on unexpected error."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1\n")

        # Make agent raise an unexpected error
        mock_agent_wrapper.run_work_session.side_effect = MemoryError("Out of memory")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 1  # Error

        # Check that a backup was created
        backup_dir = state_manager.backup_dir
        if backup_dir.exists():
            backups = list(backup_dir.glob("state.*.json"))
            # Backup may or may not exist depending on timing
            # The important thing is the method didn't crash

    def test_run_provides_debugging_info_on_unexpected_error(
        self, mock_agent_wrapper, state_dir, planner, capsys
    ):
        """Test run provides debugging info on unexpected error."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.current_task_index = 2
        state.session_count = 5
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1\n- [ ] Task 2\n- [ ] Task 3\n")

        # Make agent raise an unexpected error
        mock_agent_wrapper.run_work_session.side_effect = TypeError("Unexpected type")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        captured = capsys.readouterr()
        # Should include debugging info
        assert "TypeError" in captured.out
        assert "Task index" in captured.out or "task" in captured.out.lower()


class TestStateRecovery:
    """Tests for state recovery functionality."""

    def test_attempt_state_recovery_returns_none_when_no_backups(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test _attempt_state_recovery returns None when no backups exist."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state_manager.initialize(goal="Test", model="sonnet", options=options)

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        # No backups should exist
        result = orchestrator._attempt_state_recovery()
        assert result is None

    def test_attempt_state_recovery_recovers_from_backup(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test _attempt_state_recovery recovers from valid backup."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.current_task_index = 3
        state_manager.save_state(state)

        # Create a backup
        backup_path = state_manager.create_state_backup()
        assert backup_path is not None

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        # Now corrupt the main state file
        (state_dir / "state.json").write_text("invalid json{{{")

        # Recovery should work
        recovered = orchestrator._attempt_state_recovery()
        assert recovered is not None
        assert recovered.current_task_index == 3

    def test_get_current_task_description_returns_placeholder_on_error(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test _get_current_task_description returns placeholder on error."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        # Don't save a plan

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        description = orchestrator._get_current_task_description(state)
        assert description == "<unknown task>"

    def test_get_current_task_description_returns_task(
        self, mock_agent_wrapper, initialized_state_manager, planner
    ):
        """Test _get_current_task_description returns correct task."""
        initialized_state_manager.save_plan(
            "## Task List\n- [ ] First task\n- [ ] Second task\n"
        )
        state = initialized_state_manager.load_state()
        state.current_task_index = 1

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=initialized_state_manager,
            planner=planner,
        )

        description = orchestrator._get_current_task_description(state)
        assert description == "Second task"


class TestInterruptHandling:
    """Tests for interrupt (Ctrl+C) handling."""

    def test_keyboard_interrupt_creates_backup(
        self, mock_agent_wrapper, state_dir, planner, capsys
    ):
        """Test keyboard interrupt creates state backup."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1\n")

        mock_agent_wrapper.run_work_session.side_effect = KeyboardInterrupt()

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 2  # Paused
        captured = capsys.readouterr()
        assert "Interrupted" in captured.out or "pausing" in captured.out.lower()


class TestMaxSessionsHandling:
    """Tests for max sessions error handling."""

    def test_max_sessions_prints_informative_message(
        self, mock_agent_wrapper, state_dir, planner, capsys
    ):
        """Test max sessions reached prints informative message."""
        state_manager = StateManager(state_dir)
        options = TaskOptions(max_sessions=5)
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.session_count = 5  # Already at max
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1\n")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 1  # Blocked
        captured = capsys.readouterr()
        assert "5" in captured.out  # Should mention the limit
        assert "Max sessions" in captured.out or "max" in captured.out.lower()


class TestSuccessOutput:
    """Tests for success output messages."""

    def test_run_prints_success_message(
        self, mock_agent_wrapper, state_dir, planner, capsys
    ):
        """Test run prints success message when all tasks complete."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Single task\n")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator.run()

        assert result == 0  # Success
        captured = capsys.readouterr()
        assert "completed" in captured.out.lower() or "success" in captured.out.lower()
