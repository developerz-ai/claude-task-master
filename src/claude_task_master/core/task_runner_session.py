"""Session execution and progress update mixin for TaskRunner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import console
from .agent_exceptions import AgentError
from .agent_models import TaskComplexity, parse_task_complexity
from .config_loader import get_config
from .console import clear_task_context, set_task_context
from .task_runner_errors import WorkSessionError

if TYPE_CHECKING:
    from .agent import AgentWrapper
    from .logger import TaskLogger
    from .state import StateManager, TaskState
    from .task_group import ParsedTask, TaskGroup


class _TaskRunnerSessionMixin:
    """Mixin providing run_work_session and update_progress to TaskRunner.

    Concrete attribute stubs allow mypy to type-check cross-mixin references;
    their real values are set by TaskRunner.__init__.
    """

    # Attribute stubs — real values provided by TaskRunner.__init__
    agent: AgentWrapper
    state_manager: StateManager
    logger: TaskLogger | None
    last_session_output: str

    # Method stubs — real implementations in TaskRunner
    def parse_tasks(self, plan: str) -> list[str]:
        """Parse tasks from plan markdown."""
        raise NotImplementedError

    def is_task_complete(self, plan: str, task_index: int) -> bool:
        """Check if a task is already marked as complete."""
        raise NotImplementedError

    def _get_group_context(
        self, state: TaskState, plan: str | None = None
    ) -> dict | None:
        """Get PR group context for the current task."""
        raise NotImplementedError

    def _get_parsed_tasks(
        self, plan: str
    ) -> tuple[list[ParsedTask], list[TaskGroup]]:
        """Get parsed tasks and groups, with caching."""
        raise NotImplementedError

    def run_work_session(self, state: TaskState) -> str:
        """Run a single work session.

        Runs the current task via the agent wrapper.

        Args:
            state: Current task state.

        Returns:
            Status string describing what happened:

            - ``"skipped_already_complete"``: the current task was already
              checked off in the plan; only the task index was advanced.
            - ``"ran"``: an agent work session executed to completion.
            - ``"no_tasks_remaining"``: the task index is past the end of the
              plan; no work was started. Distinct from ``"ran"`` so callers
              only mark tasks complete when work actually ran.

        Raises:
            NoPlanFoundError: If no plan file exists.
            NoTasksFoundError: If the plan contains no tasks.
            WorkSessionError: If the work session fails.
        """
        from .task_runner_errors import NoPlanFoundError, NoTasksFoundError  # noqa: PLC0415

        # Get current task from plan
        plan = self.state_manager.load_plan()
        if not plan:
            raise NoPlanFoundError()

        try:
            tasks = self.parse_tasks(plan)
        except Exception as e:
            from .task_runner_errors import TaskRunnerError  # noqa: PLC0415

            raise TaskRunnerError(f"Failed to parse plan: {e}") from e

        if not tasks:
            raise NoTasksFoundError(plan)

        if state.current_task_index >= len(tasks):
            # All tasks processed
            return "no_tasks_remaining"

        current_task = tasks[state.current_task_index]

        # Check if task is already complete
        if self.is_task_complete(plan, state.current_task_index):
            console.newline()
            console.success(
                f"Task #{state.current_task_index + 1} already complete: {current_task}"
            )
            state.current_task_index += 1
            self.state_manager.save_state(state)
            return "skipped_already_complete"

        # Parse task complexity to determine which model to use
        complexity, cleaned_task = parse_task_complexity(current_task)
        target_model = TaskComplexity.get_model_name_for_complexity(complexity)

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

        # Get context lines from parsed task if available
        parsed_tasks, _ = self._get_parsed_tasks(plan)
        context_refs = ""
        if state.current_task_index < len(parsed_tasks):
            parsed_task = parsed_tasks[state.current_task_index]
            if parsed_task.context_lines:
                context_refs = "\nReferences:\n"
                for ref in parsed_task.context_lines:
                    context_refs += f"  - {ref}\n"

        task_description = f"""Goal: {goal}

Current Task (#{state.current_task_index + 1}): {cleaned_task}
{context_refs}
Please complete this task."""

        console.newline()
        console.info(f"Working on task #{state.current_task_index + 1}: {cleaned_task}")
        console.detail(
            f"PR: {pr_name} | Complexity: {complexity.value} → Model: {target_model.value}"
        )
        if not is_last_in_group:
            console.detail(f"   ({remaining_in_group} more task(s) in this PR group)")

        # Log the prompt
        if self.logger:
            self.logger.log_prompt(task_description)

        # Get current branch to pass to agent. An explicit --branch override takes
        # precedence and is marked mandated, so the work prompt instructs the agent to
        # use that exact name instead of inventing one (prevents same-task PR collisions).
        from .task_runner import get_current_branch  # noqa: PLC0415

        branch_override = state.options.branch_override
        current_branch = get_current_branch()

        # Build PR group info for agent context (always provide for better task execution)
        pr_group_info = {
            "name": pr_name,
            "branch": branch_override or current_branch,
            "branch_mandated": branch_override is not None,
            "completed_tasks": completed_in_group,
            "remaining_tasks": remaining_in_group,
        }

        # Determine if agent should create PR
        # pr_per_task=True: always create PR after each task
        # pr_per_task=False (default): only create PR on last task in group
        should_create_pr = state.options.pr_per_task or is_last_in_group

        # Set task context for Claude prefix display [claude HH:MM:SS N/M]
        set_task_context(state.current_task_index + 1, len(tasks))

        # Load coding style guide for token-efficient style injection
        try:
            coding_style = self.state_manager.load_coding_style()
        except Exception as e:
            console.warning(f"Could not load coding style: {e}")
            coding_style = None

        # Run work session with model routing based on task complexity
        try:
            model_type = target_model
            # Get target branch from config for rebase instructions
            config = get_config()
            target_branch = config.git.target_branch
            result = self.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=model_type,
                # With an override, point required_branch at it too so the prompt is consistent
                # (no "you're on main → create a branch" line fighting the mandated branch).
                required_branch=branch_override or current_branch,
                create_pr=should_create_pr,
                pr_group_info=pr_group_info,
                target_branch=target_branch,
                coding_style=coding_style,
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

        # Expose the session output so the orchestrator can distil it into
        # accumulated context.md learnings after the task is marked complete.
        self.last_session_output = result.get("output", "") or ""

        return "ran"

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


__all__ = ["_TaskRunnerSessionMixin"]
