"""Task Runner - Execute individual tasks from the plan.

Supports task grouping for conversation reuse. Tasks in the same group share
a single conversation, allowing Claude to remember context from previous tasks.

See `task_group` module for plan parsing and `conversation` module for
multi-turn conversation management.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from . import console
from .agent import ModelType
from .agent_exceptions import AgentError
from .config_loader import get_config
from .console import clear_task_context, set_task_context
from .task_group import (
    ParsedTask,
    TaskComplexity,
    TaskGroup,
    get_group_for_task,
    parse_task_complexity,
    parse_tasks_with_groups,
)

# Re-export for backwards compatibility
__all__ = [
    "ParsedTask",
    "TaskGroup",
    "TaskRunner",
    "TaskRunnerError",
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


class TaskRunnerError(Exception):
    """Base exception for task runner errors."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class NoPlanFoundError(TaskRunnerError):
    """Raised when no plan file exists."""

    def __init__(self) -> None:
        super().__init__(
            "No plan found",
            "The plan file does not exist. Please run the planning phase first.",
        )


class NoTasksFoundError(TaskRunnerError):
    """Raised when the plan contains no tasks."""

    def __init__(self, plan_content: str | None = None):
        details = None
        if plan_content:
            preview = plan_content[:200] + "..." if len(plan_content) > 200 else plan_content
            details = f"Plan content preview: {preview}"
        super().__init__("No tasks found in plan", details)


class WorkSessionError(TaskRunnerError):
    """Raised when a work session fails."""

    def __init__(self, task_index: int, task_description: str, original_error: Exception):
        self.task_index = task_index
        self.task_description = task_description
        self.original_error = original_error
        super().__init__(
            f"Work session failed for task #{task_index + 1}: {task_description}",
            f"Error: {type(original_error).__name__}: {original_error}",
        )


class TaskRunner:
    """Executes individual tasks from the plan.

    Supports two execution modes:
    1. **Single-turn mode** (default): Each task runs in isolation using AgentWrapper
    2. **Conversation mode**: Tasks in same PR share a conversation via ConversationManager

    Conversation mode is faster and provides better context continuity within PRs.
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

    def run_work_session(self, state: TaskState) -> None:
        """Run a single work session.

        If a ConversationManager is available, uses conversation mode for tasks
        within the same PR. Otherwise, falls back to single-turn mode.

        Args:
            state: Current task state.

        Raises:
            NoPlanFoundError: If no plan file exists.
            NoTasksFoundError: If the plan contains no tasks.
            WorkSessionError: If the work session fails.
        """
        # Get current task from plan
        plan = self.state_manager.load_plan()
        if not plan:
            raise NoPlanFoundError()

        try:
            tasks = self.parse_tasks(plan)
        except Exception as e:
            raise TaskRunnerError(f"Failed to parse plan: {e}") from e

        if not tasks:
            raise NoTasksFoundError(plan)

        if state.current_task_index >= len(tasks):
            # All tasks processed
            return

        current_task = tasks[state.current_task_index]

        # Check if task is already complete
        if self.is_task_complete(plan, state.current_task_index):
            console.newline()
            console.success(
                f"Task #{state.current_task_index + 1} already complete: {current_task}"
            )
            state.current_task_index += 1
            self.state_manager.save_state(state)
            return

        # Parse task complexity to determine which model to use
        complexity, cleaned_task = parse_task_complexity(current_task)
        target_model = TaskComplexity.get_model_for_complexity(complexity)

        # Get PR/group context for this task (reuses _get_group_context for DRY)
        group_context = self._get_group_context(state, plan)
        if group_context:
            pr_name = group_context["group_name"]
            is_last_in_group = group_context["is_last_in_group"]
            remaining_in_group = group_context["remaining_in_group"]
            completed_in_group = group_context["completed_tasks"]
        else:
            # Fallback for edge cases (shouldn't happen in normal operation)
            pr_name = "Default"
            is_last_in_group = True
            remaining_in_group = 0
            completed_in_group = []

        # Load context safely
        try:
            context = self.state_manager.load_context()
        except Exception as e:
            console.warning(f"Could not load context: {e}")
            context = ""

        # Build task description
        try:
            goal = self.state_manager.load_goal()
        except Exception as e:
            console.warning(f"Could not load goal: {e}")
            goal = "Complete the assigned task"

        task_description = f"""Goal: {goal}

Current Task (#{state.current_task_index + 1}): {cleaned_task}

Please complete this task."""

        console.newline()
        console.info(f"Working on task #{state.current_task_index + 1}: {cleaned_task}")
        console.detail(f"PR: {pr_name} | Complexity: {complexity.value} → Model: {target_model}")
        if not is_last_in_group:
            console.detail(f"   ({remaining_in_group} more task(s) in this PR group)")

        # Log the prompt
        if self.logger:
            self.logger.log_prompt(task_description)

        # Get current branch to pass to agent
        current_branch = get_current_branch()

        # Build PR group info for agent context (always provide for better task execution)
        pr_group_info = {
            "name": pr_name,
            "branch": current_branch,
            "completed_tasks": completed_in_group,
            "remaining_tasks": remaining_in_group,
        }

        # Determine if agent should create PR
        # pr_per_task=True: always create PR after each task
        # pr_per_task=False (default): only create PR on last task in group
        should_create_pr = state.options.pr_per_task or is_last_in_group

        # Set task context for Claude prefix display [claude HH:MM:SS N/M]
        set_task_context(state.current_task_index + 1, len(tasks))

        # Run work session with model routing based on task complexity
        try:
            # Convert string model name to ModelType enum
            model_type = ModelType(target_model)
            # Get target branch from config for rebase instructions
            config = get_config()
            target_branch = config.git.target_branch
            result = self.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=model_type,
                required_branch=current_branch,
                create_pr=should_create_pr,
                pr_group_info=pr_group_info,
                target_branch=target_branch,
            )
        except AgentError:
            if self.logger:
                self.logger.log_error("Agent error during work session")
            raise
        except Exception as e:
            if self.logger:
                self.logger.log_error(str(e))
            raise WorkSessionError(
                state.current_task_index,
                current_task,
                e,
            ) from e
        finally:
            # Clear task context after work session completes
            clear_task_context()

        # Log the response
        if self.logger and result.get("output"):
            self.logger.log_response(result.get("output", ""))

    def update_progress(
        self,
        state: TaskState,
        result: dict | None = None,
    ) -> None:
        """Update progress tracker after task completion.

        Reloads plan from disk to get latest completion status.

        Args:
            state: Current task state.
            result: Optional result dict with output from work session.
        """
        # Reload plan from disk to get latest [x] markers
        plan = self.state_manager.load_plan()
        if not plan:
            return

        tasks = self.parse_tasks(plan)
        if not tasks:
            return

        current_task = (
            tasks[state.current_task_index] if state.current_task_index < len(tasks) else ""
        )

        progress_lines = [
            "# Progress Tracker\n",
            f"**Session:** {state.session_count}",
            f"**Current Task:** {state.current_task_index + 1} of {len(tasks)}\n",
            "## Task List\n",
        ]

        # Add all tasks with their status
        for i, task in enumerate(tasks):
            is_complete = self.is_task_complete(plan, i)
            is_current = i == state.current_task_index

            if is_complete:
                status = "✓"
                marker = "[x]"
            elif is_current:
                status = "→"
                marker = "[ ]"
            else:
                status = " "
                marker = "[ ]"

            progress_lines.append(f"- {status} {marker} **Task {i + 1}:** {task}")

        # Add latest result if available
        if result and result.get("output"):
            progress_lines.extend(
                [
                    "\n## Latest Completed",
                    f"**Task {state.current_task_index + 1}:** {current_task}\n",
                    "### Summary",
                    result.get("output", "Completed"),
                ]
            )

        progress = "\n".join(progress_lines)

        try:
            self.state_manager.save_progress(progress)
        except Exception as e:
            console.warning(f"Could not save progress: {e}")

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
        tasks = []
        for line in plan.split("\n"):
            if line.strip().startswith("- [ ]") or line.strip().startswith("- [x]"):
                task = line.strip()[5:].strip()  # Remove "- [ ]" or "- [x]"
                if task:
                    tasks.append(task)
        return tasks

    def is_task_complete(self, plan: str, task_index: int) -> bool:
        """Check if a task is already marked as complete.

        Args:
            plan: The plan markdown content.
            task_index: Index of the task to check.

        Returns:
            True if task is complete, False otherwise.
        """
        lines = plan.split("\n")
        task_count = -1

        for line in lines:
            if line.strip().startswith("- [ ]") or line.strip().startswith("- [x]"):
                task_count += 1
                if task_count == task_index:
                    return line.strip().startswith("- [x]")

        return False

    def mark_task_complete(self, plan: str, task_index: int) -> None:
        """Mark a task as complete in the plan.

        Args:
            plan: The plan markdown content.
            task_index: Index of the task to mark complete.
        """
        lines = plan.split("\n")
        task_count = -1

        for i, line in enumerate(lines):
            if line.strip().startswith("- [ ]") or line.strip().startswith("- [x]"):
                task_count += 1
                if task_count == task_index:
                    lines[i] = line.replace("- [ ]", "- [x]", 1)
                    break

        updated_plan = "\n".join(lines)
        self.state_manager.save_plan(updated_plan)

    def is_all_complete(self, state: TaskState) -> bool:
        """Check if all tasks are complete.

        Args:
            state: Current task state.

        Returns:
            True if all tasks are processed.
        """
        plan = self.state_manager.load_plan()
        if not plan:
            return True

        tasks = self.parse_tasks(plan)
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
