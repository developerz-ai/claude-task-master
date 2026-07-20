"""Task Runner - Execute individual tasks from the plan.

Supports task grouping for conversation reuse. Tasks in the same group share
a single conversation, allowing Claude to remember context from previous tasks.

See `task_group` module for plan parsing and `conversation` module for
multi-turn conversation management.

Implementation split across focused sub-modules:
- :mod:`.task_runner_errors` — exception hierarchy
- :mod:`.task_runner_session` — :meth:`run_work_session`, :meth:`update_progress`
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .plan_parsing import (
    is_task_complete as plan_is_task_complete,
)
from .plan_parsing import (
    mark_task_complete as plan_mark_task_complete,
)
from .plan_parsing import parse_task_descriptions
from .task_group import (
    ParsedTask,
    TaskGroup,
    get_group_for_task,
    parse_tasks_with_groups,
)
from .task_runner_errors import (  # noqa: F401 — re-exported for backwards compat
    NoPlanFoundError,
    NoTasksFoundError,
    TaskRunnerError,
    WorkSessionError,
)
from .task_runner_session import _TaskRunnerSessionMixin

# Re-export for backwards compatibility
__all__ = [
    "ParsedTask",
    "TaskGroup",
    "TaskRunner",
    "TaskRunnerError",
    "NoPlanFoundError",
    "NoTasksFoundError",
    "WorkSessionError",
    "get_group_for_task",
    "parse_tasks_with_groups",
]


def get_current_branch() -> str | None:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


if TYPE_CHECKING:
    from .agent import AgentWrapper
    from .logger import TaskLogger
    from .state import StateManager, TaskState


class TaskRunner(_TaskRunnerSessionMixin):
    """Executes individual tasks from the plan.

    Supports single-turn mode: each task runs in isolation using AgentWrapper.
    """

    def __init__(
        self,
        agent: AgentWrapper,
        state_manager: StateManager,
        logger: TaskLogger | None = None,
    ):
        """Initialize task runner.

        Args:
            agent: The agent wrapper for running work sessions.
            state_manager: The state manager for persistence.
            logger: Optional logger for recording activity.
        """
        self.agent = agent
        self.state_manager = state_manager
        self.logger = logger

        # Cache for parsed tasks with group info
        self._parsed_tasks_cache: list[ParsedTask] | None = None
        self._parsed_groups_cache: list[TaskGroup] | None = None
        self._plan_hash: int | None = None

        # Raw text output of the most recent work session, exposed so the
        # orchestrator can extract accumulated context.md learnings from it.
        # "" when no session has run yet or the session produced no output.
        self.last_session_output: str = ""

    def _get_parsed_tasks(self, plan: str) -> tuple[list[ParsedTask], list[TaskGroup]]:
        """Get parsed tasks and groups, with caching.

        Args:
            plan: The plan markdown content.

        Returns:
            Tuple of (parsed tasks, groups).
        """
        plan_hash = hash(plan)
        if self._plan_hash != plan_hash or self._parsed_tasks_cache is None:
            self._parsed_tasks_cache, self._parsed_groups_cache = parse_tasks_with_groups(plan)
            self._plan_hash = plan_hash
        return self._parsed_tasks_cache, self._parsed_groups_cache or []

    def _invalidate_cache(self) -> None:
        """Invalidate the parsed tasks cache."""
        self._parsed_tasks_cache = None
        self._parsed_groups_cache = None
        self._plan_hash = None

    def _get_group_context(self, state: TaskState, plan: str | None = None) -> dict | None:
        """Get PR group context for the current task.

        Computes information about the current task's PR group including:
        - Group name and ID
        - Whether this is the last task in the group
        - Remaining tasks in the group
        - Completed tasks in the group

        Args:
            state: Current task state.
            plan: Optional plan content. If not provided, loads from state manager.

        Returns:
            Dict with group context, or None if no plan or task out of range.
            Keys: group_id, group_name, is_last_in_group, remaining_in_group,
                  completed_tasks, tasks_in_group
        """
        if plan is None:
            plan = self.state_manager.load_plan()
        if not plan:
            return None

        parsed_tasks, _ = self._get_parsed_tasks(plan)
        if state.current_task_index >= len(parsed_tasks):
            return None

        current_task = parsed_tasks[state.current_task_index]
        group_id = current_task.group_id
        group_name = current_task.group_name

        # Get all tasks in this group
        tasks_in_group = [t for t in parsed_tasks if t.group_id == group_id]

        # Find the current task's position within the group
        current_task_in_group_idx = next(
            (i for i, t in enumerate(tasks_in_group) if t.index == state.current_task_index),
            0,
        )

        # Calculate remaining tasks
        remaining_in_group = len(tasks_in_group) - current_task_in_group_idx - 1
        is_last_in_group = remaining_in_group == 0

        # Get completed tasks in this group (for context)
        completed_tasks = [t.cleaned_description for t in tasks_in_group if t.is_complete]

        return {
            "group_id": group_id,
            "group_name": group_name,
            "is_last_in_group": is_last_in_group,
            "remaining_in_group": remaining_in_group,
            "completed_tasks": completed_tasks,
            "tasks_in_group": tasks_in_group,
        }

    def get_current_task_description(self, state: TaskState) -> str:
        """Get the description of the current task.

        Args:
            state: Current task state.

        Returns:
            Task description string or placeholder if not found.
        """
        try:
            plan = self.state_manager.load_plan()
            if not plan:
                return "<unknown task>"

            tasks = self.parse_tasks(plan)
            if state.current_task_index < len(tasks):
                return tasks[state.current_task_index]
            return f"<task index {state.current_task_index}>"
        except Exception:
            return "<unknown task>"

    def parse_tasks(self, plan: str) -> list[str]:
        """Parse tasks from plan markdown.

        Args:
            plan: The plan markdown content.

        Returns:
            List of task descriptions.
        """
        return parse_task_descriptions(plan)

    def is_task_complete(self, plan: str, task_index: int) -> bool:
        """Check if a task is already marked as complete.

        Args:
            plan: The plan markdown content.
            task_index: Index of the task to check.

        Returns:
            True if task is complete, False otherwise.
        """
        return plan_is_task_complete(plan, task_index)

    def mark_task_complete(self, plan: str, task_index: int) -> None:
        """Mark a task as complete in the plan.

        Args:
            plan: The plan markdown content.
            task_index: Index of the task to mark complete. If out of range,
                the plan is saved unchanged.
        """
        updated_plan = plan_mark_task_complete(plan, task_index)
        self.state_manager.save_plan(updated_plan)
        self._invalidate_cache()

    def is_all_complete(self, state: TaskState) -> bool:
        """Check if all tasks are complete.

        Args:
            state: Current task state.

        Returns:
            True if all tasks are processed.

        Raises:
            NoPlanFoundError: If no plan file exists.
        """
        plan = self.state_manager.load_plan()
        if not plan:
            raise NoPlanFoundError()

        tasks = parse_task_descriptions(plan)
        return state.current_task_index >= len(tasks)

    def is_last_task_in_group(self, state: TaskState) -> bool:
        """Check if the current task is the last in its PR group.

        Used by orchestrator to determine whether to trigger PR workflow
        or continue to next task in the same group.

        Args:
            state: Current task state.

        Returns:
            True if this is the last task in the PR group.
        """
        group_context = self._get_group_context(state)
        if group_context is None:
            # No plan or task out of range - treat as last task
            return True
        return bool(group_context["is_last_in_group"])
