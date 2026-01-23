"""Integration tests for single-task PR workflow.

These tests verify that PRs with only 1 task work correctly:
- Single task → PR creation → CI pass → merge → completion
- Single task correctly triggers is_last_task_in_group()
- Workflow stage transitions work for 1-task PR groups
- Task completion properly detected after merge

This is a critical edge case where the formula:
  remaining = len(tasks_in_group) - current_task_in_group_idx - 1
For 1 task: remaining = 1 - 0 - 1 = 0, should return True.
"""

from pathlib import Path
from unittest.mock import MagicMock

from claude_task_master.core.state import StateManager, TaskOptions
from claude_task_master.core.task_runner import TaskRunner
from claude_task_master.core.workflow_stages import WorkflowStageHandler

# =============================================================================
# Single-Task PR Detection Tests
# =============================================================================


class TestSingleTaskPRDetection:
    """Tests for detecting single-task PR groups."""

    def test_is_last_task_in_group_single_task(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
    ):
        """Test is_last_task_in_group returns True for PR with 1 task.

        This is the critical test ensuring single-task PRs trigger the PR workflow.
        """
        state_manager = StateManager(integration_state_dir)
        task_runner = TaskRunner(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            logger=None,
        )

        # Plan with a single task in a PR group
        single_task_plan = """## Task List

### PR 1: Single Task Feature

- [ ] `[coding]` Implement the only feature in this PR

### PR 2: Multi Task Feature

- [ ] `[coding]` First task of second PR
- [ ] `[coding]` Second task of second PR
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(single_task_plan)

        # Create task state at task index 0 (the single task in PR 1)
        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(
            goal="Test single task PR", model="sonnet", options=options
        )
        state.current_task_index = 0

        # Should return True because it's the only task in the group
        assert task_runner.is_last_task_in_group(state) is True

    def test_is_last_task_in_group_first_of_multi(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
    ):
        """Test is_last_task_in_group returns False for first task of multi-task PR."""
        state_manager = StateManager(integration_state_dir)
        task_runner = TaskRunner(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            logger=None,
        )

        single_task_plan = """## Task List

### PR 1: Single Task Feature

- [ ] `[coding]` Only task in PR 1

### PR 2: Multi Task Feature

- [ ] `[coding]` First task of PR 2
- [ ] `[coding]` Second task of PR 2
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(single_task_plan)

        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Test multi task PR", model="sonnet", options=options)
        # Task index 1 is the first task of PR 2
        state.current_task_index = 1

        # Should return False - more tasks remain in PR 2
        assert task_runner.is_last_task_in_group(state) is False


# =============================================================================
# Workflow Stage Transition Tests for Single-Task PRs
# =============================================================================


class TestSingleTaskWorkflowStageTransitions:
    """Tests for workflow stage transitions with single-task PRs."""

    def test_single_task_transitions_to_pr_created(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
        mock_github_client,
        monkeypatch,
    ):
        """Test that completing a single task transitions to pr_created stage."""
        monkeypatch.chdir(integration_temp_dir)

        state_manager = StateManager(integration_state_dir)
        task_runner = TaskRunner(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            logger=None,
        )

        single_task_plan = """## Task List

### PR 1: Single Task Feature

- [ ] `[coding]` The only task
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(single_task_plan)
        state_manager.save_goal("Implement single task feature")

        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Single task", model="sonnet", options=options)
        state.current_task_index = 0
        state.workflow_stage = "working"

        # Verify this is the last task in its group
        assert task_runner.is_last_task_in_group(state) is True

        # After completing the task, the orchestrator should set workflow_stage to "pr_created"
        # because is_last_task_in_group returns True
        #
        # This mimics what happens in orchestrator._handle_working_stage()
        if task_runner.is_last_task_in_group(state):
            state.workflow_stage = "pr_created"
        else:
            state.current_task_index += 1
            state.workflow_stage = "working"

        assert state.workflow_stage == "pr_created"

    def test_multi_task_first_stays_in_working(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
        monkeypatch,
    ):
        """Test that completing first task of multi-task PR stays in working stage."""
        monkeypatch.chdir(integration_temp_dir)

        state_manager = StateManager(integration_state_dir)
        task_runner = TaskRunner(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            logger=None,
        )

        multi_task_plan = """## Task List

### PR 1: Multi Task Feature

- [ ] `[coding]` First task
- [ ] `[coding]` Second task
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(multi_task_plan)

        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Multi task", model="sonnet", options=options)
        state.current_task_index = 0
        state.workflow_stage = "working"

        # First task should NOT be the last in group
        assert task_runner.is_last_task_in_group(state) is False

        # Mimic orchestrator logic
        if task_runner.is_last_task_in_group(state):
            state.workflow_stage = "pr_created"
        else:
            state.current_task_index += 1
            state.workflow_stage = "working"

        # Should stay in working stage and move to next task
        assert state.workflow_stage == "working"
        assert state.current_task_index == 1


# =============================================================================
# Full Single-Task PR Workflow Integration Tests
# =============================================================================


class TestSingleTaskPRFullWorkflow:
    """Full integration tests for single-task PR workflow."""

    def test_single_task_pr_workflow_pr_created_to_waiting_ci(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
        mock_github_client,
        monkeypatch,
    ):
        """Test single-task PR transitions from pr_created to waiting_ci."""
        monkeypatch.chdir(integration_temp_dir)

        state_manager = StateManager(integration_state_dir)
        pr_context_mock = MagicMock()

        handler = WorkflowStageHandler(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            github_client=mock_github_client,
            pr_context=pr_context_mock,
        )

        # Set up state in pr_created stage
        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Single task PR", model="sonnet", options=options)
        state.current_task_index = 0
        state.workflow_stage = "pr_created"
        state.current_pr = None  # No PR yet detected
        state_manager.save_state(state)

        # Mock GitHub client to return PR number
        mock_github_client.get_pr_for_current_branch.return_value = 123

        # Handle pr_created stage
        result = handler.handle_pr_created_stage(state)

        # Should transition to waiting_ci with PR number set
        assert state.current_pr == 123
        assert state.workflow_stage == "waiting_ci"
        assert result is None  # No exit, continue

    def test_single_task_pr_workflow_waiting_ci_to_ready_to_merge(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
        mock_github_client,
        monkeypatch,
    ):
        """Test single-task PR transitions from waiting_ci to ready_to_merge when CI passes."""
        monkeypatch.chdir(integration_temp_dir)

        state_manager = StateManager(integration_state_dir)
        pr_context_mock = MagicMock()

        handler = WorkflowStageHandler(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            github_client=mock_github_client,
            pr_context=pr_context_mock,
        )

        # Set up state in waiting_ci stage with a PR
        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Single task PR", model="sonnet", options=options)
        state.current_task_index = 0
        state.workflow_stage = "waiting_ci"
        state.current_pr = 123
        state_manager.save_state(state)

        # Mock GitHub client to return passing CI
        mock_pr_status = MagicMock()
        mock_pr_status.ci_state = "SUCCESS"
        mock_pr_status.checks_pending = 0
        mock_pr_status.merged = False
        mock_pr_status.unresolved_threads = 0
        mock_github_client.get_pr_status.return_value = mock_pr_status

        # Handle waiting_ci stage
        result = handler.handle_waiting_ci_stage(state)

        # Should transition to ready_to_merge (or waiting_reviews if configured)
        # The actual stage depends on whether there are unresolved threads
        assert state.workflow_stage in ["ready_to_merge", "waiting_reviews"]
        assert result is None

    def test_single_task_pr_workflow_merge_completes_workflow(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
        mock_github_client,
        monkeypatch,
    ):
        """Test single-task PR merge completes the workflow correctly."""
        monkeypatch.chdir(integration_temp_dir)

        state_manager = StateManager(integration_state_dir)
        pr_context_mock = MagicMock()
        task_runner = TaskRunner(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            logger=None,
        )

        handler = WorkflowStageHandler(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            github_client=mock_github_client,
            pr_context=pr_context_mock,
        )

        # Set up plan with single task
        single_task_plan = """## Task List

### PR 1: Single Task Feature

- [ ] `[coding]` The only task
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(single_task_plan)

        # Set up state in merged stage
        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Single task PR", model="sonnet", options=options)
        state.current_task_index = 0
        state.workflow_stage = "merged"
        state.current_pr = 123
        state_manager.save_state(state)

        # Mock PR status for checkout
        mock_pr_status = MagicMock()
        mock_pr_status.base_branch = "main"
        mock_github_client.get_pr_status.return_value = mock_pr_status

        # Handle merged stage
        handler.handle_merged_stage(state, task_runner.mark_task_complete)

        # Task index should be incremented to 1
        assert state.current_task_index == 1
        # PR should be cleared
        assert state.current_pr is None
        # Should go back to working stage
        assert state.workflow_stage == "working"

        # After merge, is_all_complete should return True since task_index=1 exceeds task count=1
        assert task_runner.is_all_complete(state) is True


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestSingleTaskPREdgeCases:
    """Edge case tests for single-task PR workflow."""

    def test_single_task_no_pr_group_header(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
    ):
        """Test single task without explicit PR group header still works."""
        state_manager = StateManager(integration_state_dir)
        task_runner = TaskRunner(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            logger=None,
        )

        # Plan without PR group headers (all tasks in one implicit group)
        flat_plan = """## Task List

- [ ] `[coding]` The only task in the plan
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(flat_plan)

        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Flat plan", model="sonnet", options=options)
        state.current_task_index = 0

        # Should still return True as it's the only task
        assert task_runner.is_last_task_in_group(state) is True

    def test_single_task_with_pr_per_task_option(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
    ):
        """Test single task with pr_per_task option enabled."""
        state_manager = StateManager(integration_state_dir)
        task_runner = TaskRunner(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            logger=None,
        )

        multi_task_plan = """## Task List

- [ ] `[coding]` Task 1
- [ ] `[coding]` Task 2
- [ ] `[coding]` Task 3
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(multi_task_plan)

        # With pr_per_task, each task should trigger PR creation
        options = TaskOptions(auto_merge=True, pr_per_task=True)
        state = state_manager.initialize(goal="PR per task", model="sonnet", options=options)
        state.current_task_index = 0

        # With pr_per_task, the orchestrator skips is_last_task_in_group check
        # and always sets workflow_stage to "pr_created"
        # Mimic orchestrator logic for pr_per_task mode:
        if state.options.pr_per_task:
            state.workflow_stage = "pr_created"
        else:
            if task_runner.is_last_task_in_group(state):
                state.workflow_stage = "pr_created"
            else:
                state.workflow_stage = "working"

        assert state.workflow_stage == "pr_created"

    def test_single_task_completion_marks_plan(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
        mock_github_client,
        monkeypatch,
    ):
        """Test that completing single-task PR marks the task as complete in plan."""
        monkeypatch.chdir(integration_temp_dir)

        state_manager = StateManager(integration_state_dir)
        task_runner = TaskRunner(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            logger=None,
        )

        # Plan with single task
        single_task_plan = """## Task List

### PR 1: Single Task

- [ ] `[coding]` Complete this task
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(single_task_plan)

        # Mark task 0 as complete
        task_runner.mark_task_complete(single_task_plan, 0)

        # Verify the plan was updated
        updated_plan = state_manager.load_plan()
        assert "- [x]" in updated_plan
        assert task_runner.is_task_complete(updated_plan, 0) is True


# =============================================================================
# State Persistence Tests
# =============================================================================


class TestSingleTaskStatePersistence:
    """Tests for state persistence during single-task PR workflow."""

    def test_state_preserved_through_workflow_stages(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
        mock_github_client,
        monkeypatch,
    ):
        """Test that state is properly preserved through all workflow stages."""
        monkeypatch.chdir(integration_temp_dir)

        state_manager = StateManager(integration_state_dir)

        # Initialize state
        options = TaskOptions(auto_merge=True, max_sessions=10)
        state = state_manager.initialize(
            goal="Test state persistence", model="sonnet", options=options
        )

        # Simulate workflow progression
        stages = ["working", "pr_created", "waiting_ci", "ready_to_merge", "merged"]

        for stage in stages:
            state.workflow_stage = stage
            state_manager.save_state(state)

            # Reload and verify
            loaded_state = state_manager.load_state()
            assert loaded_state.workflow_stage == stage
            assert loaded_state.options.auto_merge is True
            assert loaded_state.options.max_sessions == 10

    def test_pr_number_preserved_through_stages(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_github_client,
        monkeypatch,
    ):
        """Test that PR number is preserved through CI and merge stages."""
        monkeypatch.chdir(integration_temp_dir)

        state_manager = StateManager(integration_state_dir)

        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(
            goal="Test PR persistence", model="sonnet", options=options
        )
        state.current_pr = 456
        state.workflow_stage = "waiting_ci"
        state_manager.save_state(state)

        # Reload and verify PR number
        loaded_state = state_manager.load_state()
        assert loaded_state.current_pr == 456

        # Change to ci_failed and verify PR preserved
        loaded_state.workflow_stage = "ci_failed"
        state_manager.save_state(loaded_state)

        reloaded_state = state_manager.load_state()
        assert reloaded_state.current_pr == 456


# =============================================================================
# is_all_complete Tests for Single-Task Scenarios
# =============================================================================


class TestIsAllCompleteForSingleTask:
    """Tests for is_all_complete with single-task plans."""

    def test_is_all_complete_false_before_task_done(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
    ):
        """Test is_all_complete returns False when single task not yet complete."""
        state_manager = StateManager(integration_state_dir)
        task_runner = TaskRunner(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            logger=None,
        )

        single_task_plan = """## Task List

- [ ] `[coding]` The only task
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(single_task_plan)

        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        state.current_task_index = 0

        # Not complete yet - task index is 0, task count is 1
        assert task_runner.is_all_complete(state) is False

    def test_is_all_complete_true_after_single_task_done(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
    ):
        """Test is_all_complete returns True after single task is done."""
        state_manager = StateManager(integration_state_dir)
        task_runner = TaskRunner(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            logger=None,
        )

        single_task_plan = """## Task List

- [ ] `[coding]` The only task
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(single_task_plan)

        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        # After merged stage, task_index is incremented to 1
        state.current_task_index = 1

        # Should be complete - task index (1) >= task count (1)
        assert task_runner.is_all_complete(state) is True

    def test_is_all_complete_works_with_task_marked_complete(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
    ):
        """Test is_all_complete works correctly when task is marked [x]."""
        state_manager = StateManager(integration_state_dir)
        task_runner = TaskRunner(
            agent=mock_agent_wrapper,
            state_manager=state_manager,
            logger=None,
        )

        # Plan with task already marked complete
        completed_plan = """## Task List

- [x] `[coding]` The only task (already done)
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(completed_plan)

        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)
        # Task index incremented after completion
        state.current_task_index = 1

        # Should be complete
        assert task_runner.is_all_complete(state) is True
