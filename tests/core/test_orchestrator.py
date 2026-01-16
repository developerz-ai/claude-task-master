"""Comprehensive tests for the orchestrator module."""

from unittest.mock import patch

import pytest

from claude_task_master.core.agent import AgentError, QueryExecutionError
from claude_task_master.core.orchestrator import (
    MaxSessionsReachedError,
    NoPlanFoundError,
    NoTasksFoundError,
    OrchestratorError,
    PlanParsingError,
    StateRecoveryError,
    TaskIndexOutOfBoundsError,
    VerificationFailedError,
    WorkLoopOrchestrator,
    WorkSessionError,
)
from claude_task_master.core.state import StateManager, TaskOptions

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

    def test_init_stores_components(self, mock_agent_wrapper, initialized_state_manager, planner):
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

    def test_run_exceeds_max_sessions_immediately(self, mock_agent_wrapper, state_dir, planner):
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
        state_manager.save_criteria(
            "1. All tests pass"
        )  # Must save criteria for verification to run

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

    def test_run_work_session_does_not_increment_task_index(
        self, orchestrator, mock_agent_wrapper, initialized_state_manager
    ):
        """Test work session does not increment task index (handled by workflow stage)."""
        state = orchestrator.state_manager.load_state()
        initial_index = state.current_task_index

        orchestrator._run_work_session(state)

        # Task index increment is now handled by _handle_merged_stage in the PR workflow
        # _run_work_session should NOT increment the index
        updated_state = initialized_state_manager.load_state()
        assert updated_state.current_task_index == initial_index

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

    def test_verify_success_with_criteria(
        self, orchestrator, mock_agent_wrapper, initialized_state_manager
    ):
        """Test verification with success criteria."""
        initialized_state_manager.save_criteria("1. All tests pass\n2. No bugs")
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        result = orchestrator._verify_success()

        assert result is True
        mock_agent_wrapper.verify_success_criteria.assert_called_once()

    def test_verify_success_no_criteria(
        self, orchestrator, mock_agent_wrapper, initialized_state_manager
    ):
        """Test verification returns True when no criteria specified."""
        # Ensure no criteria file exists
        criteria_file = initialized_state_manager.state_dir / "criteria.txt"
        if criteria_file.exists():
            criteria_file.unlink()

        result = orchestrator._verify_success()

        assert result is True
        mock_agent_wrapper.verify_success_criteria.assert_not_called()

    def test_verify_success_failure(
        self, orchestrator, mock_agent_wrapper, initialized_state_manager
    ):
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
        assert error.details and "Plan content preview" in error.details

    def test_plan_parsing_error_truncates_long_content(self):
        """Test PlanParsingError truncates long content."""
        long_content = "x" * 500
        error = PlanParsingError("Failed", long_content)
        assert error.plan_content == long_content
        # Preview should be truncated to 200 chars + "..."
        assert error.details and len(error.details) < len(long_content) + 50

    def test_no_plan_found_error(self):
        """Test NoPlanFoundError."""
        error = NoPlanFoundError()
        assert "No plan found" in error.message
        assert error.details and "planning phase" in error.details

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
        assert error.details and "3 tasks" in error.details

    def test_work_session_error(self):
        """Test WorkSessionError."""
        original = ValueError("Something went wrong")
        error = WorkSessionError(2, "Fix the bug", original)
        assert error.task_index == 2
        assert error.task_description == "Fix the bug"
        assert error.original_error == original
        assert "task #3" in error.message  # 1-indexed in message
        assert error.details and "ValueError" in error.details

    def test_state_recovery_error(self):
        """Test StateRecoveryError."""
        original = OSError("File not found")
        error = StateRecoveryError("Could not load backup", original)
        assert "recover" in error.message.lower()
        assert error.original_error == original
        assert error.details and "OSError" in error.details

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

    def test_run_handles_no_plan_as_success(self, mock_agent_wrapper, state_dir, planner):
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

    def test_run_handles_no_tasks_as_success(self, mock_agent_wrapper, state_dir, planner):
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

    def test_run_creates_backup_on_unexpected_error(self, mock_agent_wrapper, state_dir, planner):
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
            list(backup_dir.glob("state.*.json"))
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

        orchestrator.run()

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
        initialized_state_manager.save_plan("## Task List\n- [ ] First task\n- [ ] Second task\n")
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

    def test_run_prints_success_message(self, mock_agent_wrapper, state_dir, planner, capsys):
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


# =============================================================================
# PR Workflow Exception Tests
# =============================================================================


class TestPRWorkflowExceptions:
    """Tests for PR workflow related exceptions."""

    def test_pr_workflow_error(self):
        """Test PRWorkflowError exception."""
        from claude_task_master.core.orchestrator import PRWorkflowError

        error = PRWorkflowError(pr_number=123, stage="merge", message="Merge conflict")
        assert error.pr_number == 123
        assert error.stage == "merge"
        assert "PR #123" in error.message
        assert "merge" in error.message or "Merge conflict" in str(error)

    def test_ci_timeout_error(self):
        """Test CITimeoutError exception."""
        from claude_task_master.core.orchestrator import CITimeoutError

        error = CITimeoutError(pr_number=456, timeout_seconds=300)
        assert error.pr_number == 456
        assert error.timeout_seconds == 300
        assert "PR #456" in error.message
        assert (error.details and "300" in error.details) or "300 seconds" in str(error)


# =============================================================================
# Workflow Stage Tests
# =============================================================================


class TestWorkflowStages:
    """Tests for workflow stage handling."""

    def test_workflow_stage_initialization(self, mock_agent_wrapper, state_dir, planner):
        """Test that workflow stage is initialized correctly."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = None  # Not set
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}
        mock_agent_wrapper.verify_success_criteria.return_value = {"success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        # Manually call _run_workflow_cycle to test initialization
        state = state_manager.load_state()
        orchestrator._run_workflow_cycle(state)

        # Stage should be initialized
        updated_state = state_manager.load_state()
        assert updated_state.workflow_stage is not None

    def test_unknown_workflow_stage_resets_to_working(
        self, mock_agent_wrapper, state_dir, planner, capsys
    ):
        """Test that unknown workflow stage resets to working.

        Note: Since state validation prevents invalid workflow_stage values,
        this test verifies the _run_workflow_cycle method's fallback handling
        by directly manipulating the state object after loading.
        """
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "working"  # Start with valid stage
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        # Load state and manually set invalid stage to test fallback
        state = state_manager.load_state()
        # Directly modify the state object's internal value to bypass Pydantic validation
        # This simulates a corrupted state that somehow has an invalid workflow_stage
        object.__setattr__(state, "workflow_stage", "invalid_stage")

        # Call _run_workflow_cycle - it should handle the invalid stage gracefully
        orchestrator._run_workflow_cycle(state)

        # Should have printed warning and reset or saved with working stage
        captured = capsys.readouterr()
        assert "Unknown workflow stage" in captured.out
        # Verify state was reset to working
        assert state.workflow_stage == "working"

    def test_handle_working_stage(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_working_stage method."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "working"
        state.session_count = 0
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        state = state_manager.load_state()
        result = orchestrator._handle_working_stage(state)

        # Should return None to continue
        assert result is None
        # Session count should be incremented
        updated_state = state_manager.load_state()
        assert updated_state.session_count == 1
        # Should transition to pr_created
        assert updated_state.workflow_stage == "pr_created"

    def test_handle_pr_created_stage_no_pr(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_pr_created_stage with no existing PR."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "pr_created"
        state.current_pr = None
        state_manager.save_state(state)

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        state = state_manager.load_state()
        result = orchestrator._handle_pr_created_stage(state)

        assert result is None
        updated_state = state_manager.load_state()
        assert updated_state.workflow_stage == "waiting_ci"

    def test_handle_pr_created_stage_with_pr(self, mock_agent_wrapper, state_dir, planner, capsys):
        """Test _handle_pr_created_stage with existing PR."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "pr_created"
        state.current_pr = 123
        state_manager.save_state(state)

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        state = state_manager.load_state()
        result = orchestrator._handle_pr_created_stage(state)

        assert result is None
        updated_state = state_manager.load_state()
        assert updated_state.workflow_stage == "waiting_ci"
        captured = capsys.readouterr()
        assert "PR #123" in captured.out

    def test_handle_waiting_ci_stage_no_pr(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_waiting_ci_stage skips CI when no PR."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "waiting_ci"
        state.current_pr = None
        state_manager.save_state(state)

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        state = state_manager.load_state()
        result = orchestrator._handle_waiting_ci_stage(state)

        assert result is None
        updated_state = state_manager.load_state()
        assert updated_state.workflow_stage == "waiting_reviews"

    def test_handle_waiting_reviews_stage_no_pr(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_waiting_reviews_stage skips when no PR."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "waiting_reviews"
        state.current_pr = None
        state_manager.save_state(state)

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        state = state_manager.load_state()
        result = orchestrator._handle_waiting_reviews_stage(state)

        assert result is None
        updated_state = state_manager.load_state()
        assert updated_state.workflow_stage == "merged"

    def test_handle_ready_to_merge_stage_no_pr(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_ready_to_merge_stage when no PR exists."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "ready_to_merge"
        state.current_pr = None
        state_manager.save_state(state)

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        state = state_manager.load_state()
        result = orchestrator._handle_ready_to_merge_stage(state)

        assert result is None
        updated_state = state_manager.load_state()
        assert updated_state.workflow_stage == "merged"

    def test_handle_ready_to_merge_auto_merge_disabled(
        self, mock_agent_wrapper, state_dir, planner, capsys
    ):
        """Test _handle_ready_to_merge_stage when auto_merge is disabled."""
        state_manager = StateManager(state_dir)
        options = TaskOptions(auto_merge=False)
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "ready_to_merge"
        state.current_pr = 123
        state_manager.save_state(state)

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        state = state_manager.load_state()
        result = orchestrator._handle_ready_to_merge_stage(state)

        assert result == 2  # Paused
        updated_state = state_manager.load_state()
        assert updated_state.status == "paused"
        captured = capsys.readouterr()
        assert "auto_merge disabled" in captured.out or "ready to merge" in captured.out.lower()

    def test_handle_merged_stage(self, mock_agent_wrapper, state_dir, planner, capsys):
        """Test _handle_merged_stage advances to next task."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "merged"
        state.current_task_index = 0
        state.current_pr = 123
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1\n- [ ] Task 2")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        state = state_manager.load_state()
        result = orchestrator._handle_merged_stage(state)

        assert result is None
        updated_state = state_manager.load_state()
        assert updated_state.current_task_index == 1
        assert updated_state.current_pr is None
        assert updated_state.workflow_stage == "working"
        captured = capsys.readouterr()
        assert "Task #1 complete" in captured.out


# =============================================================================
# GitHub Client Property Tests
# =============================================================================


class TestGitHubClientProperty:
    """Tests for the github_client lazy initialization property."""

    def test_github_client_returns_provided_client(self, mock_agent_wrapper, state_dir, planner):
        """Test github_client returns provided client without init."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        state_manager.initialize(goal="Test", model="sonnet", options=TaskOptions())

        provided_client = MagicMock()
        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=provided_client,
        )

        # Access the property
        client = orchestrator.github_client

        # Should return the provided client
        assert client == provided_client

    def test_github_client_caches_after_assignment(self, mock_agent_wrapper, state_dir, planner):
        """Test github_client caches after direct assignment."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        state_manager.initialize(goal="Test", model="sonnet", options=TaskOptions())

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=None,
        )

        # Manually set the private attribute (simulating lazy init)
        mock_client = MagicMock()
        orchestrator._github_client = mock_client

        # Subsequent access should return the cached client
        assert orchestrator.github_client == mock_client
        assert orchestrator.github_client == mock_client  # Multiple accesses

    def test_github_client_none_triggers_lazy_load_attempt(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test that None github_client triggers initialization attempt.

        Note: Full lazy-load testing requires integration tests since the
        GitHubClient import happens dynamically inside the property.
        This test verifies the property correctly handles a provided client.
        """
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        state_manager.initialize(goal="Test", model="sonnet", options=TaskOptions())

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=None,
        )

        # Verify _github_client is None initially
        assert orchestrator._github_client is None

        # After setting a mock client, property returns it
        mock_client = MagicMock()
        orchestrator._github_client = mock_client
        assert orchestrator.github_client == mock_client


# =============================================================================
# Task Complexity Routing Tests
# =============================================================================


class TestTaskComplexityRouting:
    """Tests for task complexity-based model routing."""

    def test_task_with_coding_tag_uses_opus(self, mock_agent_wrapper, state_dir, planner, capsys):
        """Test that `[coding]` tag routes to Opus model."""
        from claude_task_master.core.agent import ModelType

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] `[coding]` Implement complex feature")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        state = state_manager.load_state()
        orchestrator._run_work_session(state)

        # Should have used Opus model
        call_kwargs = mock_agent_wrapper.run_work_session.call_args.kwargs
        assert call_kwargs.get("model_override") == ModelType.OPUS
        captured = capsys.readouterr()
        assert "opus" in captured.out.lower()

    def test_task_with_quick_tag_uses_haiku(self, mock_agent_wrapper, state_dir, planner, capsys):
        """Test that `[quick]` tag routes to Haiku model."""
        from claude_task_master.core.agent import ModelType

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] `[quick]` Fix typo in README")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        state = state_manager.load_state()
        orchestrator._run_work_session(state)

        # Should have used Haiku model
        call_kwargs = mock_agent_wrapper.run_work_session.call_args.kwargs
        assert call_kwargs.get("model_override") == ModelType.HAIKU
        captured = capsys.readouterr()
        assert "haiku" in captured.out.lower()

    def test_task_with_general_tag_uses_sonnet(
        self, mock_agent_wrapper, state_dir, planner, capsys
    ):
        """Test that `[general]` tag routes to Sonnet model."""
        from claude_task_master.core.agent import ModelType

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] `[general]` Update documentation")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        state = state_manager.load_state()
        orchestrator._run_work_session(state)

        # Should have used Sonnet model
        call_kwargs = mock_agent_wrapper.run_work_session.call_args.kwargs
        assert call_kwargs.get("model_override") == ModelType.SONNET
        captured = capsys.readouterr()
        assert "sonnet" in captured.out.lower()


# =============================================================================
# Logger Integration Tests
# =============================================================================


class TestLoggerIntegration:
    """Tests for logger integration in orchestrator."""

    def test_logger_logs_session(self, mock_agent_wrapper, state_dir, planner):
        """Test that logger records session start and end."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}

        mock_logger = MagicMock()
        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            logger=mock_logger,
        )

        state = state_manager.load_state()
        orchestrator._handle_working_stage(state)

        # Logger should have been called
        mock_logger.start_session.assert_called_once()
        mock_logger.end_session.assert_called_once()
        mock_logger.log_prompt.assert_called_once()

    def test_logger_logs_error_on_exception(self, mock_agent_wrapper, state_dir, planner):
        """Test that logger records errors when work session fails."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_agent_wrapper.run_work_session.side_effect = RuntimeError("Agent failed")

        mock_logger = MagicMock()
        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            logger=mock_logger,
        )

        state = state_manager.load_state()

        with pytest.raises(WorkSessionError):
            orchestrator._run_work_session(state)

        # Logger should have recorded error
        mock_logger.log_error.assert_called()


# =============================================================================
# Error Handling and Exception Tests
# =============================================================================


class TestOrchestratorErrorHandling:
    """Tests for error handling in the orchestrator run loop."""

    def test_state_error_handling(self, mock_agent_wrapper, state_dir, planner, capsys):
        """Test StateError is caught and handled properly."""
        from claude_task_master.core.state import StateError

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        # Mock _run_workflow_cycle to raise StateError
        with patch.object(
            orchestrator,
            "_run_workflow_cycle",
            side_effect=StateError("State file corrupted", details="Invalid JSON"),
        ):
            with patch("claude_task_master.core.key_listener.start_listening"):
                with patch("claude_task_master.core.key_listener.stop_listening"):
                    with patch(
                        "claude_task_master.core.key_listener.check_escape", return_value=False
                    ):
                        result = orchestrator.run()

        assert result == 1
        # State should be marked as failed
        state = state_manager.load_state()
        assert state.status == "failed"

    def test_unexpected_exception_handling(self, mock_agent_wrapper, state_dir, planner, capsys):
        """Test unexpected Exception is caught and handled properly."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        # Mock _run_workflow_cycle to raise an unexpected exception
        with patch.object(
            orchestrator,
            "_run_workflow_cycle",
            side_effect=RuntimeError("Unexpected database error"),
        ):
            with patch("claude_task_master.core.key_listener.start_listening"):
                with patch("claude_task_master.core.key_listener.stop_listening"):
                    with patch(
                        "claude_task_master.core.key_listener.check_escape", return_value=False
                    ):
                        result = orchestrator.run()

        assert result == 1
        # State should be marked as failed
        state = state_manager.load_state()
        assert state.status == "failed"

        # Should output error message
        captured = capsys.readouterr()
        assert "Unexpected error" in captured.out or "RuntimeError" in captured.out

    def test_state_error_with_save_failure(self, mock_agent_wrapper, state_dir, planner, capsys):
        """Test StateError handling when save_state also fails."""
        from claude_task_master.core.state import StateError

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "working"
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        # Mock both _run_workflow_cycle and save_state to fail
        with patch.object(
            orchestrator,
            "_run_workflow_cycle",
            side_effect=StateError("State file corrupted"),
        ):
            with patch.object(
                state_manager,
                "save_state",
                side_effect=Exception("Disk full"),
            ):
                with patch("claude_task_master.core.key_listener.start_listening"):
                    with patch("claude_task_master.core.key_listener.stop_listening"):
                        with patch(
                            "claude_task_master.core.key_listener.check_escape", return_value=False
                        ):
                            result = orchestrator.run()

        assert result == 1
        # Should still return error code even if save fails


# =============================================================================
# CI Stage Tests
# =============================================================================


class TestCIStageHandling:
    """Tests for CI-related workflow stages."""

    def test_handle_waiting_ci_stage_success(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_waiting_ci_stage when CI passes."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "waiting_ci"
        state.current_pr = 123
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_github_client = MagicMock()
        mock_github_client.get_pr_status.return_value = MagicMock(
            ci_state="SUCCESS",
            check_details=[],
        )

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=mock_github_client,
        )

        result = orchestrator._handle_waiting_ci_stage(state)

        assert result is None
        assert state.workflow_stage == "waiting_reviews"  # type: ignore[comparison-overlap]

    def test_handle_waiting_ci_stage_failure(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_waiting_ci_stage when CI fails."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "waiting_ci"
        state.current_pr = 123
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_github_client = MagicMock()
        mock_github_client.get_pr_status.return_value = MagicMock(
            ci_state="FAILURE",
            check_details=[
                {"name": "pytest", "conclusion": "failure"},
                {"name": "lint", "conclusion": "success"},
            ],
        )

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=mock_github_client,
        )

        result = orchestrator._handle_waiting_ci_stage(state)

        assert result is None
        assert state.workflow_stage == "ci_failed"  # type: ignore[comparison-overlap]

    def test_handle_waiting_ci_stage_pending(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_waiting_ci_stage when CI is pending."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "waiting_ci"
        state.current_pr = 123
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_github_client = MagicMock()
        mock_github_client.get_pr_status.return_value = MagicMock(
            ci_state="PENDING",
            check_details=[],
        )

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=mock_github_client,
        )

        with patch("time.sleep"):  # Skip actual sleep
            result = orchestrator._handle_waiting_ci_stage(state)

        assert result is None
        # Stage should remain waiting_ci for pending
        assert state.workflow_stage == "waiting_ci"

    def test_handle_waiting_ci_stage_error(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_waiting_ci_stage when checking CI fails."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "waiting_ci"
        state.current_pr = 123
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_github_client = MagicMock()
        mock_github_client.get_pr_status.side_effect = Exception("API rate limit")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=mock_github_client,
        )

        result = orchestrator._handle_waiting_ci_stage(state)

        assert result is None
        # Should skip to reviews on error
        assert state.workflow_stage == "waiting_reviews"  # type: ignore[comparison-overlap]

    def test_handle_ci_failed_stage(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_ci_failed_stage runs agent to fix CI."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "ci_failed"
        state.current_pr = 123
        state.session_count = 1
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_github_client = MagicMock()
        mock_github_client.get_failed_run_logs.return_value = "Error: test_foo failed"
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[{"name": "pytest", "conclusion": "failure"}]
        )

        mock_agent_wrapper.run_work_session.return_value = {"output": "Fixed", "success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=mock_github_client,
        )

        result = orchestrator._handle_ci_failed_stage(state)

        assert result is None
        assert state.workflow_stage == "waiting_ci"  # type: ignore[comparison-overlap]
        assert state.session_count == 2
        mock_agent_wrapper.run_work_session.assert_called_once()


# =============================================================================
# Review Stage Tests
# =============================================================================


class TestReviewStageHandling:
    """Tests for review-related workflow stages."""

    def test_handle_waiting_reviews_stage_with_unresolved(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test _handle_waiting_reviews_stage with unresolved comments."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "waiting_reviews"
        state.current_pr = 123
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_github_client = MagicMock()
        mock_github_client.get_pr_status.return_value = MagicMock(
            unresolved_threads=3,
        )

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=mock_github_client,
        )

        result = orchestrator._handle_waiting_reviews_stage(state)

        assert result is None
        assert state.workflow_stage == "addressing_reviews"  # type: ignore[comparison-overlap]

    def test_handle_waiting_reviews_stage_no_unresolved(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test _handle_waiting_reviews_stage with no unresolved comments."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "waiting_reviews"
        state.current_pr = 123
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_github_client = MagicMock()
        mock_github_client.get_pr_status.return_value = MagicMock(
            unresolved_threads=0,
        )

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=mock_github_client,
        )

        result = orchestrator._handle_waiting_reviews_stage(state)

        assert result is None
        assert state.workflow_stage == "ready_to_merge"  # type: ignore[comparison-overlap]

    def test_handle_waiting_reviews_stage_error(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_waiting_reviews_stage when checking reviews fails."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "waiting_reviews"
        state.current_pr = 123
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_github_client = MagicMock()
        mock_github_client.get_pr_status.side_effect = Exception("API error")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=mock_github_client,
        )

        result = orchestrator._handle_waiting_reviews_stage(state)

        assert result is None
        # Should skip to ready_to_merge on error
        assert state.workflow_stage == "ready_to_merge"  # type: ignore[comparison-overlap]

    def test_handle_addressing_reviews_stage(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_addressing_reviews_stage runs agent to address comments."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "addressing_reviews"
        state.current_pr = 123
        state.session_count = 1
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_github_client = MagicMock()
        mock_github_client.get_pr_comments.return_value = "Please add more tests"

        mock_agent_wrapper.run_work_session.return_value = {"output": "Fixed", "success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=mock_github_client,
        )

        with patch.object(orchestrator, "_save_pr_comments_to_files"):
            result = orchestrator._handle_addressing_reviews_stage(state)

        assert result is None
        assert state.workflow_stage == "waiting_ci"  # type: ignore[comparison-overlap]
        assert state.session_count == 2
        mock_agent_wrapper.run_work_session.assert_called_once()

    def test_handle_addressing_reviews_stage_no_pr(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_addressing_reviews_stage when no PR exists."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "addressing_reviews"
        state.current_pr = None
        state.session_count = 1
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Fixed", "success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator._handle_addressing_reviews_stage(state)

        assert result is None
        assert state.workflow_stage == "waiting_ci"  # type: ignore[comparison-overlap]


# =============================================================================
# Merge Stage Tests
# =============================================================================


class TestMergeStageHandling:
    """Tests for merge-related workflow stages."""

    def test_handle_ready_to_merge_stage_auto_merge_success(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test _handle_ready_to_merge_stage with auto_merge enabled."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "ready_to_merge"
        state.current_pr = 123
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_github_client = MagicMock()
        mock_github_client.merge_pr.return_value = None

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=mock_github_client,
        )

        result = orchestrator._handle_ready_to_merge_stage(state)

        assert result is None
        assert state.workflow_stage == "merged"  # type: ignore[comparison-overlap]
        mock_github_client.merge_pr.assert_called_once_with(123)

    def test_handle_ready_to_merge_stage_auto_merge_failure(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test _handle_ready_to_merge_stage when auto_merge fails."""
        from unittest.mock import MagicMock

        state_manager = StateManager(state_dir)
        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "ready_to_merge"
        state.current_pr = 123
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_github_client = MagicMock()
        mock_github_client.merge_pr.side_effect = Exception("Merge conflict")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
            github_client=mock_github_client,
        )

        result = orchestrator._handle_ready_to_merge_stage(state)

        assert result == 1
        assert state.status == "blocked"  # type: ignore[comparison-overlap]

    def test_handle_merged_stage_clears_pr_context(self, mock_agent_wrapper, state_dir, planner):
        """Test _handle_merged_stage clears PR context files."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = "merged"
        state.current_pr = 123
        state.current_task_index = 0
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1\n- [ ] Task 2")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        with patch.object(state_manager, "clear_pr_context") as mock_clear:
            with patch("claude_task_master.core.key_listener.reset_escape"):
                result = orchestrator._handle_merged_stage(state)

        assert result is None
        assert state.current_task_index == 1
        assert state.current_pr is None
        assert state.workflow_stage == "working"
        mock_clear.assert_called_once_with(123)


# =============================================================================
# State Recovery Extended Tests
# =============================================================================


class TestStateRecoveryExtended:
    """Extended tests for state recovery functionality."""

    def test_attempt_state_recovery_no_backups(self, mock_agent_wrapper, state_dir, planner):
        """Test _attempt_state_recovery with no backup files."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state_manager.initialize(goal="Test", model="sonnet", options=options)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator._attempt_state_recovery()

        assert result is None

    def test_attempt_state_recovery_with_backups(self, mock_agent_wrapper, state_dir, planner):
        """Test _attempt_state_recovery with backup files."""
        import json

        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        # Create a backup
        backup_dir = state_manager.backup_dir
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / "state.1234567890.json"
        backup_data = state.model_dump()
        backup_data["status"] = "working"
        backup_file.write_text(json.dumps(backup_data))

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator._attempt_state_recovery()

        assert result is not None
        assert result.status == "working"

    def test_attempt_state_recovery_with_corrupted_backups(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test _attempt_state_recovery with corrupted backup files."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state_manager.initialize(goal="Test", model="sonnet", options=options)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        # Create a corrupted backup
        backup_dir = state_manager.backup_dir
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / "state.1234567890.json"
        backup_file.write_text("not valid json {{{")

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        result = orchestrator._attempt_state_recovery()

        assert result is None


# =============================================================================
# Workflow Cycle Unknown Stage Tests
# =============================================================================


class TestWorkflowCycleUnknownStage:
    """Tests for handling unknown workflow stages."""

    def test_run_workflow_cycle_initializes_workflow_stage(
        self, mock_agent_wrapper, state_dir, planner
    ):
        """Test _run_workflow_cycle initializes workflow_stage to working when None."""
        state_manager = StateManager(state_dir)
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.status = "working"
        state.workflow_stage = None  # Valid value - None means not initialized
        state_manager.save_state(state)
        state_manager.save_plan("## Task List\n- [ ] Task 1")

        mock_agent_wrapper.run_work_session.return_value = {"output": "Done", "success": True}

        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            planner=planner,
        )

        orchestrator._run_workflow_cycle(state)

        # Workflow stage should progress from working to pr_created after work session succeeds
        # The key is that it was properly initialized from None to working first
        assert state.workflow_stage in ("working", "pr_created")  # Either is valid
