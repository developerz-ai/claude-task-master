"""Tests for task_runner module - critical execution path.

This module tests the TaskRunner class which executes individual tasks from the plan.
Tests cover:
- TaskRunner initialization and caching
- Task parsing and completion detection
- Work session execution
- Progress tracking
- PR group management
- Error handling
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.task_runner import (
    NoPlanFoundError,
    NoTasksFoundError,
    TaskRunner,
    TaskRunnerError,
    WorkSessionError,
    get_current_branch,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_agent():
    """Create a mock agent wrapper."""
    agent = MagicMock()
    agent.run_work_session = MagicMock(
        return_value={"output": "Task completed successfully", "success": True}
    )
    return agent


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    logger = MagicMock()
    logger.log_prompt = MagicMock()
    logger.log_response = MagicMock()
    logger.log_error = MagicMock()
    return logger


@pytest.fixture
def task_runner(mock_agent, state_manager):
    """Create a TaskRunner instance with mocks."""
    return TaskRunner(
        agent=mock_agent,
        state_manager=state_manager,
        logger=None,
    )


@pytest.fixture
def task_runner_with_logger(mock_agent, state_manager, mock_logger):
    """Create a TaskRunner instance with mock logger."""
    return TaskRunner(
        agent=mock_agent,
        state_manager=state_manager,
        logger=mock_logger,
    )


@pytest.fixture
def basic_task_state(sample_task_options):
    """Create a basic task state for testing."""
    now = datetime.now().isoformat()
    options = TaskOptions(**sample_task_options)
    return TaskState(
        status="working",
        current_task_index=0,
        session_count=1,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=options,
    )


@pytest.fixture
def basic_plan():
    """Basic plan with unchecked tasks."""
    return """## Task List

- [ ] Task 1: Set up project structure
- [ ] Task 2: Implement core functionality
- [ ] Task 3: Add unit tests
"""


@pytest.fixture
def plan_with_completed_tasks():
    """Plan with some completed tasks."""
    return """## Task List

- [x] Task 1: Set up project structure
- [x] Task 2: Implement core functionality
- [ ] Task 3: Add unit tests
- [ ] Task 4: Write documentation
"""


@pytest.fixture
def plan_with_pr_groups():
    """Plan with PR group structure."""
    return """## Task List

### PR 1: Setup Changes

- [ ] `[coding]` Create project structure
- [ ] `[coding]` Add configuration files

### PR 2: Core Implementation

- [ ] `[coding]` Implement main feature
- [ ] `[quick]` Fix typo in README
- [ ] `[general]` Add tests
"""


# =============================================================================
# Test TaskRunnerError Exceptions
# =============================================================================


class TestTaskRunnerError:
    """Tests for TaskRunnerError and its subclasses."""

    def test_task_runner_error_basic(self):
        """Should create error with message only."""
        error = TaskRunnerError("Something went wrong")
        assert error.message == "Something went wrong"
        assert error.details is None
        assert str(error) == "Something went wrong"

    def test_task_runner_error_with_details(self):
        """Should create error with message and details."""
        error = TaskRunnerError("Failed operation", "More info here")
        assert error.message == "Failed operation"
        assert error.details == "More info here"
        assert "Failed operation" in str(error)
        assert "More info here" in str(error)


class TestNoPlanFoundError:
    """Tests for NoPlanFoundError."""

    def test_no_plan_found_error(self):
        """Should create appropriate error message."""
        error = NoPlanFoundError()
        assert "No plan found" in error.message
        assert error.details is not None
        assert "planning phase" in error.details


class TestNoTasksFoundError:
    """Tests for NoTasksFoundError."""

    def test_no_tasks_found_error_without_content(self):
        """Should create error without plan preview."""
        error = NoTasksFoundError()
        assert "No tasks found" in error.message
        assert error.details is None

    def test_no_tasks_found_error_with_short_content(self):
        """Should include full short plan content in details."""
        error = NoTasksFoundError("Short plan content")
        assert "No tasks found" in error.message
        assert error.details is not None
        assert "Short plan content" in error.details

    def test_no_tasks_found_error_with_long_content(self):
        """Should truncate long plan content."""
        long_content = "x" * 300
        error = NoTasksFoundError(long_content)
        assert error.details is not None
        assert "..." in error.details
        assert len(error.details) < 250  # Truncated


class TestWorkSessionError:
    """Tests for WorkSessionError."""

    def test_work_session_error(self):
        """Should capture task info and original error."""
        original = ValueError("Original error")
        error = WorkSessionError(2, "Test task description", original)

        assert error.task_index == 2
        assert error.task_description == "Test task description"
        assert error.original_error is original
        assert "#3" in error.message  # task_index + 1
        assert "Test task description" in error.message
        assert error.details is not None
        assert "ValueError" in error.details


# =============================================================================
# Test get_current_branch Function
# =============================================================================


class TestGetCurrentBranch:
    """Tests for get_current_branch utility function."""

    def test_get_current_branch_success(self):
        """Should return branch name on success."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="feature/my-branch\n")
            branch = get_current_branch()
            assert branch == "feature/my-branch"

    def test_get_current_branch_empty(self):
        """Should return None for empty output (detached HEAD)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            branch = get_current_branch()
            assert branch is None

    def test_get_current_branch_error(self):
        """Should return None on error."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Git not available")
            branch = get_current_branch()
            assert branch is None


# =============================================================================
# Test TaskRunner Initialization
# =============================================================================


class TestTaskRunnerInit:
    """Tests for TaskRunner initialization."""

    def test_init_basic(self, mock_agent, state_manager):
        """Should initialize with required arguments."""
        runner = TaskRunner(agent=mock_agent, state_manager=state_manager)
        assert runner.agent is mock_agent
        assert runner.state_manager is state_manager
        assert runner.logger is None

    def test_init_with_logger(self, mock_agent, state_manager, mock_logger):
        """Should initialize with optional logger."""
        runner = TaskRunner(agent=mock_agent, state_manager=state_manager, logger=mock_logger)
        assert runner.logger is mock_logger

    def test_init_cache_empty(self, task_runner):
        """Should have empty caches on init."""
        assert task_runner._parsed_tasks_cache is None
        assert task_runner._parsed_groups_cache is None
        assert task_runner._plan_hash is None


# =============================================================================
# Test Task Parsing
# =============================================================================


class TestParseTasksMethod:
    """Tests for parse_tasks method."""

    def test_parse_basic_tasks(self, task_runner, basic_plan):
        """Should parse unchecked tasks."""
        tasks = task_runner.parse_tasks(basic_plan)
        assert len(tasks) == 3
        assert "Task 1" in tasks[0]
        assert "Task 2" in tasks[1]
        assert "Task 3" in tasks[2]

    def test_parse_completed_tasks(self, task_runner, plan_with_completed_tasks):
        """Should parse both checked and unchecked tasks."""
        tasks = task_runner.parse_tasks(plan_with_completed_tasks)
        assert len(tasks) == 4

    def test_parse_empty_plan(self, task_runner):
        """Should return empty list for empty plan."""
        tasks = task_runner.parse_tasks("")
        assert tasks == []

    def test_parse_plan_without_tasks(self, task_runner):
        """Should return empty list for plan without tasks."""
        plan = "## Some Header\n\nSome content without tasks."
        tasks = task_runner.parse_tasks(plan)
        assert tasks == []


# =============================================================================
# Test Task Completion Detection
# =============================================================================


class TestIsTaskComplete:
    """Tests for is_task_complete method."""

    def test_task_not_complete(self, task_runner, basic_plan):
        """Should return False for unchecked task."""
        assert not task_runner.is_task_complete(basic_plan, 0)
        assert not task_runner.is_task_complete(basic_plan, 1)
        assert not task_runner.is_task_complete(basic_plan, 2)

    def test_task_complete(self, task_runner, plan_with_completed_tasks):
        """Should return True for checked task."""
        assert task_runner.is_task_complete(plan_with_completed_tasks, 0)
        assert task_runner.is_task_complete(plan_with_completed_tasks, 1)
        assert not task_runner.is_task_complete(plan_with_completed_tasks, 2)

    def test_task_index_out_of_range(self, task_runner, basic_plan):
        """Should return False for out-of-range index."""
        assert not task_runner.is_task_complete(basic_plan, 99)


# =============================================================================
# Test Mark Task Complete
# =============================================================================


class TestMarkTaskComplete:
    """Tests for mark_task_complete method."""

    def test_mark_task_complete(self, task_runner, state_manager, basic_plan):
        """Should update plan to mark task complete."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        task_runner.mark_task_complete(basic_plan, 0)

        updated_plan = state_manager.load_plan()
        assert task_runner.is_task_complete(updated_plan, 0)

    def test_mark_middle_task_complete(self, task_runner, state_manager, basic_plan):
        """Should mark correct task when not first."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        task_runner.mark_task_complete(basic_plan, 1)

        updated_plan = state_manager.load_plan()
        assert not task_runner.is_task_complete(updated_plan, 0)
        assert task_runner.is_task_complete(updated_plan, 1)
        assert not task_runner.is_task_complete(updated_plan, 2)


# =============================================================================
# Test Is All Complete
# =============================================================================


class TestIsAllComplete:
    """Tests for is_all_complete method."""

    def test_not_all_complete(self, task_runner, state_manager, basic_task_state, basic_plan):
        """Should return False when tasks remain."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        assert not task_runner.is_all_complete(basic_task_state)

    def test_all_complete_when_index_exceeds_tasks(
        self, task_runner, state_manager, basic_task_state, basic_plan
    ):
        """Should return True when index >= task count."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        basic_task_state.current_task_index = 10  # Beyond task count
        assert task_runner.is_all_complete(basic_task_state)

    def test_all_complete_no_plan(self, task_runner, basic_task_state):
        """Should return True when no plan exists."""
        # Don't save any plan
        assert task_runner.is_all_complete(basic_task_state)


# =============================================================================
# Test Get Current Task Description
# =============================================================================


class TestGetCurrentTaskDescription:
    """Tests for get_current_task_description method."""

    def test_get_task_description_valid_index(
        self, task_runner, state_manager, basic_task_state, basic_plan
    ):
        """Should return task description for valid index."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        desc = task_runner.get_current_task_description(basic_task_state)
        assert "Task 1" in desc

    def test_get_task_description_second_task(
        self, task_runner, state_manager, basic_task_state, basic_plan
    ):
        """Should return correct task for non-zero index."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        basic_task_state.current_task_index = 1
        desc = task_runner.get_current_task_description(basic_task_state)
        assert "Task 2" in desc

    def test_get_task_description_out_of_range(
        self, task_runner, state_manager, basic_task_state, basic_plan
    ):
        """Should return placeholder for out-of-range index."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        basic_task_state.current_task_index = 99
        desc = task_runner.get_current_task_description(basic_task_state)
        assert "task index 99" in desc

    def test_get_task_description_no_plan(self, task_runner, basic_task_state):
        """Should return placeholder when no plan."""
        desc = task_runner.get_current_task_description(basic_task_state)
        assert desc == "<unknown task>"


# =============================================================================
# Test Caching Behavior
# =============================================================================


class TestCaching:
    """Tests for parsed tasks caching."""

    def test_cache_on_first_parse(self, task_runner, plan_with_pr_groups):
        """Should cache results on first parse."""
        tasks, groups = task_runner._get_parsed_tasks(plan_with_pr_groups)

        assert task_runner._parsed_tasks_cache is not None
        assert task_runner._parsed_groups_cache is not None
        assert task_runner._plan_hash is not None
        assert len(tasks) == 5
        assert len(groups) == 2

    def test_cache_reuse_same_plan(self, task_runner, plan_with_pr_groups):
        """Should reuse cache for same plan."""
        task_runner._get_parsed_tasks(plan_with_pr_groups)
        original_hash = task_runner._plan_hash

        # Call again with same plan
        task_runner._get_parsed_tasks(plan_with_pr_groups)
        assert task_runner._plan_hash == original_hash

    def test_cache_invalidate_different_plan(self, task_runner, plan_with_pr_groups, basic_plan):
        """Should invalidate cache for different plan."""
        task_runner._get_parsed_tasks(plan_with_pr_groups)
        original_hash = task_runner._plan_hash

        task_runner._get_parsed_tasks(basic_plan)
        assert task_runner._plan_hash != original_hash

    def test_manual_cache_invalidate(self, task_runner, plan_with_pr_groups):
        """Should clear cache on invalidate_cache call."""
        task_runner._get_parsed_tasks(plan_with_pr_groups)
        assert task_runner._parsed_tasks_cache is not None

        task_runner._invalidate_cache()

        assert task_runner._parsed_tasks_cache is None
        assert task_runner._parsed_groups_cache is None
        assert task_runner._plan_hash is None


# =============================================================================
# Test Get Group Context (Internal Helper)
# =============================================================================


class TestGetGroupContext:
    """Tests for _get_group_context internal helper method.

    This method consolidates PR group logic used by both run_work_session()
    and is_last_task_in_group() to avoid code duplication.
    """

    def test_get_group_context_single_task(self, task_runner, state_manager, basic_task_state):
        """Should return correct context for single-task PR."""
        single_task_plan = """## Task List

### PR 1: Single Task

- [ ] `[coding]` Only task
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(single_task_plan)

        basic_task_state.current_task_index = 0
        context = task_runner._get_group_context(basic_task_state)

        assert context is not None
        assert context["group_id"] == "pr_1"
        assert context["group_name"] == "Single Task"
        assert context["is_last_in_group"] is True
        assert context["remaining_in_group"] == 0
        assert context["completed_tasks"] == []
        assert len(context["tasks_in_group"]) == 1

    def test_get_group_context_multi_task_first(
        self, task_runner, state_manager, basic_task_state, plan_with_pr_groups
    ):
        """Should return correct context for first task in multi-task PR."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(plan_with_pr_groups)

        basic_task_state.current_task_index = 0
        context = task_runner._get_group_context(basic_task_state)

        assert context is not None
        assert context["group_id"] == "pr_1"
        assert context["is_last_in_group"] is False
        assert context["remaining_in_group"] == 1  # 1 more task in PR 1

    def test_get_group_context_multi_task_last(
        self, task_runner, state_manager, basic_task_state, plan_with_pr_groups
    ):
        """Should return correct context for last task in multi-task PR."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(plan_with_pr_groups)

        basic_task_state.current_task_index = 1  # Last task in PR 1
        context = task_runner._get_group_context(basic_task_state)

        assert context is not None
        assert context["is_last_in_group"] is True
        assert context["remaining_in_group"] == 0

    def test_get_group_context_no_plan(self, task_runner, basic_task_state):
        """Should return None when no plan exists."""
        context = task_runner._get_group_context(basic_task_state)
        assert context is None

    def test_get_group_context_out_of_range(
        self, task_runner, state_manager, basic_task_state, basic_plan
    ):
        """Should return None for out-of-range task index."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        basic_task_state.current_task_index = 99
        context = task_runner._get_group_context(basic_task_state)
        assert context is None

    def test_get_group_context_with_completed_tasks(
        self, task_runner, state_manager, basic_task_state
    ):
        """Should include completed tasks in context."""
        plan_with_completed = """## Task List

### PR 1: Mixed Tasks

- [x] `[coding]` Completed task one
- [x] `[coding]` Completed task two
- [ ] `[coding]` Pending task
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(plan_with_completed)

        basic_task_state.current_task_index = 2  # The pending task
        context = task_runner._get_group_context(basic_task_state)

        assert context is not None
        assert len(context["completed_tasks"]) == 2
        assert "Completed task one" in context["completed_tasks"][0]
        assert "Completed task two" in context["completed_tasks"][1]

    def test_get_group_context_with_plan_argument(
        self, task_runner, state_manager, basic_task_state
    ):
        """Should use provided plan instead of loading from state manager."""
        # Save a different plan to state manager
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("## No tasks here")

        # Provide a different plan as argument
        custom_plan = """## Task List

### PR 1: Custom

- [ ] `[coding]` Custom task
"""
        basic_task_state.current_task_index = 0
        context = task_runner._get_group_context(basic_task_state, plan=custom_plan)

        assert context is not None
        assert context["group_name"] == "Custom"


# =============================================================================
# Test Is Last Task In Group
# =============================================================================


class TestIsLastTaskInGroup:
    """Tests for is_last_task_in_group method."""

    def test_is_last_in_group_true(
        self, task_runner, state_manager, basic_task_state, plan_with_pr_groups
    ):
        """Should return True for last task in group."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(plan_with_pr_groups)

        # Index 1 is the last task in PR 1 (0-indexed)
        basic_task_state.current_task_index = 1
        assert task_runner.is_last_task_in_group(basic_task_state)

    def test_is_last_in_group_false(
        self, task_runner, state_manager, basic_task_state, plan_with_pr_groups
    ):
        """Should return False for non-last task in group."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(plan_with_pr_groups)

        # Index 0 is NOT the last task in PR 1
        basic_task_state.current_task_index = 0
        assert not task_runner.is_last_task_in_group(basic_task_state)

    def test_is_last_in_group_no_plan(self, task_runner, basic_task_state):
        """Should return True when no plan exists."""
        assert task_runner.is_last_task_in_group(basic_task_state)

    def test_is_last_in_group_out_of_range(
        self, task_runner, state_manager, basic_task_state, plan_with_pr_groups
    ):
        """Should return True for out-of-range index."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(plan_with_pr_groups)

        basic_task_state.current_task_index = 99
        assert task_runner.is_last_task_in_group(basic_task_state)

    def test_is_last_in_group_single_task_pr(self, task_runner, state_manager, basic_task_state):
        """Should return True for PR with single task.

        This is a critical edge case where a PR group contains only one task.
        The formula: remaining = len(tasks_in_group) - current_task_in_group_idx - 1
        For 1 task: remaining = 1 - 0 - 1 = 0, so should return True.

        This test ensures that single-task PRs trigger the PR creation workflow
        correctly instead of waiting for more tasks.
        """
        single_task_pr_plan = """## Task List

### PR 1: Single Task PR

- [ ] `[coding]` The only task in this PR group

### PR 2: Multi Task PR

- [ ] `[coding]` First task in second PR
- [ ] `[coding]` Second task in second PR
"""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(single_task_pr_plan)

        # Task index 0 is the only task in PR 1
        basic_task_state.current_task_index = 0
        assert task_runner.is_last_task_in_group(basic_task_state)

        # Task index 1 is NOT the last task in PR 2 (first of two)
        basic_task_state.current_task_index = 1
        assert not task_runner.is_last_task_in_group(basic_task_state)

        # Task index 2 IS the last task in PR 2 (second of two)
        basic_task_state.current_task_index = 2
        assert task_runner.is_last_task_in_group(basic_task_state)


# =============================================================================
# Test Run Work Session
# =============================================================================


class TestRunWorkSession:
    """Tests for run_work_session method."""

    def test_run_work_session_no_plan(self, task_runner, basic_task_state):
        """Should raise NoPlanFoundError when no plan exists."""
        with pytest.raises(NoPlanFoundError):
            task_runner.run_work_session(basic_task_state)

    def test_run_work_session_empty_plan(self, task_runner, state_manager, basic_task_state):
        """Should raise NoTasksFoundError for empty plan."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("## No tasks here")

        with pytest.raises(NoTasksFoundError):
            task_runner.run_work_session(basic_task_state)

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    def test_run_work_session_skips_complete_task(
        self,
        mock_console,
        mock_branch,
        task_runner,
        state_manager,
        mock_agent,
        basic_task_state,
        plan_with_completed_tasks,
    ):
        """Should skip already completed tasks."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(plan_with_completed_tasks)
        state_manager.save_goal("Test goal")

        task_runner.run_work_session(basic_task_state)

        # Agent should NOT be called for completed task
        mock_agent.run_work_session.assert_not_called()
        # Task index should be incremented
        assert basic_task_state.current_task_index == 1

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    def test_run_work_session_calls_agent(
        self,
        mock_console,
        mock_branch,
        task_runner,
        state_manager,
        mock_agent,
        basic_task_state,
        basic_plan,
    ):
        """Should call agent for incomplete task."""
        mock_branch.return_value = "feature/test"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        task_runner.run_work_session(basic_task_state)

        # Agent should be called
        mock_agent.run_work_session.assert_called_once()

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    def test_run_work_session_all_tasks_done(
        self,
        mock_console,
        mock_branch,
        task_runner,
        state_manager,
        mock_agent,
        basic_task_state,
        basic_plan,
    ):
        """Should return early when all tasks processed."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        basic_task_state.current_task_index = 100  # Beyond task count

        task_runner.run_work_session(basic_task_state)

        # Agent should NOT be called
        mock_agent.run_work_session.assert_not_called()

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    def test_run_work_session_logs_with_logger(
        self,
        mock_console,
        mock_branch,
        task_runner_with_logger,
        state_manager,
        mock_logger,
        basic_task_state,
        basic_plan,
    ):
        """Should log prompt and response when logger provided."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        task_runner_with_logger.run_work_session(basic_task_state)

        mock_logger.log_prompt.assert_called_once()
        mock_logger.log_response.assert_called_once()

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    def test_run_work_session_handles_agent_error(
        self,
        mock_console,
        mock_branch,
        task_runner_with_logger,
        state_manager,
        mock_agent,
        mock_logger,
        basic_task_state,
        basic_plan,
    ):
        """Should handle and log agent errors."""
        from claude_task_master.core.agent_exceptions import AgentError

        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        mock_agent.run_work_session.side_effect = AgentError("Agent failed")

        with pytest.raises(AgentError):
            task_runner_with_logger.run_work_session(basic_task_state)

        mock_logger.log_error.assert_called_once()

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    def test_run_work_session_wraps_generic_error(
        self,
        mock_console,
        mock_branch,
        task_runner,
        state_manager,
        mock_agent,
        basic_task_state,
        basic_plan,
    ):
        """Should wrap generic errors in WorkSessionError."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        mock_agent.run_work_session.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(WorkSessionError) as exc_info:
            task_runner.run_work_session(basic_task_state)

        assert exc_info.value.task_index == 0
        assert isinstance(exc_info.value.original_error, RuntimeError)

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    def test_run_work_session_with_pr_group(
        self,
        mock_console,
        mock_branch,
        task_runner,
        state_manager,
        mock_agent,
        basic_task_state,
        plan_with_pr_groups,
    ):
        """Should pass PR group info to agent."""
        mock_branch.return_value = "feature/pr-1"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(plan_with_pr_groups)
        state_manager.save_goal("Test goal")

        task_runner.run_work_session(basic_task_state)

        # Verify agent was called with PR group info
        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        assert "pr_group_info" in call_kwargs
        assert call_kwargs["pr_group_info"]["name"] == "Setup Changes"

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    def test_run_work_session_pr_per_task(
        self,
        mock_console,
        mock_branch,
        task_runner,
        state_manager,
        mock_agent,
        basic_task_state,
        plan_with_pr_groups,
    ):
        """Should create PR per task when option enabled."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(plan_with_pr_groups)
        state_manager.save_goal("Test goal")

        basic_task_state.options.pr_per_task = True

        task_runner.run_work_session(basic_task_state)

        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        assert call_kwargs["create_pr"] is True


# =============================================================================
# Test Update Progress
# =============================================================================


class TestUpdateProgress:
    """Tests for update_progress method."""

    def test_update_progress_basic(self, task_runner, state_manager, basic_task_state, basic_plan):
        """Should update progress file."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        task_runner.update_progress(basic_task_state)

        progress = state_manager.load_progress()
        assert "Progress Tracker" in progress
        assert "Session:" in progress

    def test_update_progress_with_result(
        self, task_runner, state_manager, basic_task_state, basic_plan
    ):
        """Should include result summary in progress."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        result = {"output": "Task completed successfully"}
        task_runner.update_progress(basic_task_state, result)

        progress = state_manager.load_progress()
        assert "Latest Completed" in progress
        assert "Task completed successfully" in progress

    def test_update_progress_no_plan(self, task_runner, basic_task_state):
        """Should handle missing plan gracefully."""
        # Should not raise
        task_runner.update_progress(basic_task_state)

    def test_update_progress_marks_status(
        self, task_runner, state_manager, basic_task_state, plan_with_completed_tasks
    ):
        """Should mark correct task statuses with proper markdown format."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(plan_with_completed_tasks)

        task_runner.update_progress(basic_task_state)

        progress = state_manager.load_progress()
        # Check for completion markers with dash prefix and proper format
        # basic_task_state has current_task_index=0, so task 1 is current (but already complete)
        assert "- ✓ [x] **Task 1:**" in progress  # Completed task 1
        assert "- ✓ [x] **Task 2:**" in progress  # Completed task 2
        assert "-   [ ] **Task 3:**" in progress  # Pending task (3 spaces for status)
        assert "-   [ ] **Task 4:**" in progress  # Pending task (3 spaces for status)

    def test_update_progress_current_task_arrow(
        self, task_runner, state_manager, basic_task_state, basic_plan
    ):
        """Should mark current task with arrow symbol."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)

        # Set current task to second task (index 1)
        basic_task_state.current_task_index = 1
        task_runner.update_progress(basic_task_state)

        progress = state_manager.load_progress()
        # Check that task 2 (index 1) has the arrow symbol
        assert "- → [ ] **Task 2:**" in progress  # Current task with arrow


# =============================================================================
# Test Error Handling Edge Cases
# =============================================================================


class TestErrorHandling:
    """Tests for error handling edge cases."""

    def test_parse_tasks_error_wrapped(self, task_runner, state_manager, basic_task_state):
        """Should wrap parse errors in TaskRunnerError."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("valid plan content")

        # Mock parse_tasks to raise an exception
        with patch.object(task_runner, "parse_tasks", side_effect=ValueError("Parse error")):
            with pytest.raises(TaskRunnerError) as exc_info:
                task_runner.run_work_session(basic_task_state)

            assert "Failed to parse plan" in str(exc_info.value)

    @patch("claude_task_master.core.task_runner.console")
    def test_context_load_warning(
        self, mock_console, task_runner, state_manager, mock_agent, basic_task_state
    ):
        """Should warn on context load failure but continue."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Test task")
        state_manager.save_goal("Test goal")

        # Mock context loading to raise
        with (
            patch.object(state_manager, "load_context", side_effect=Exception("Context error")),
            patch("claude_task_master.core.task_runner.get_current_branch", return_value="main"),
        ):
            task_runner.run_work_session(basic_task_state)

        # Should still call agent
        mock_agent.run_work_session.assert_called_once()
        # Should log warning
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.task_runner.console")
    def test_goal_load_warning(
        self, mock_console, task_runner, state_manager, mock_agent, basic_task_state
    ):
        """Should use default goal on load failure."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Test task")

        # Mock goal loading to raise
        with (
            patch.object(state_manager, "load_goal", side_effect=Exception("Goal error")),
            patch("claude_task_master.core.task_runner.get_current_branch", return_value="main"),
        ):
            task_runner.run_work_session(basic_task_state)

        # Should still call agent with default goal
        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        assert "Complete the assigned task" in call_kwargs["task_description"]
