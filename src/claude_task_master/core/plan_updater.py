"""Plan Updater - Updates existing plans based on change requests.

This module handles the plan update workflow when a change request is
received via `claudetm resume "message"` or from the mailbox system.
"""

from typing import TYPE_CHECKING, Any

from .agent_phases import run_async_with_cleanup
from .plan_parsing import (
    count_completed_tasks,
    first_incomplete_task_index,
    parse_task_descriptions,
)
from .prompts_plan_update import build_plan_update_prompt

if TYPE_CHECKING:
    from .agent import AgentWrapper
    from .logger import TaskLogger
    from .state import StateManager


class PlanUpdater:
    """Handles updating existing plans based on change requests.

    This class orchestrates the plan update workflow:
    1. Load the current plan
    2. Run Claude with plan update prompt
    3. Extract and save the updated plan
    4. Update progress tracking
    """

    def __init__(
        self,
        agent: "AgentWrapper",
        state_manager: "StateManager",
        logger: "TaskLogger | None" = None,
    ):
        """Initialize the plan updater.

        Args:
            agent: The agent wrapper for running queries.
            state_manager: The state manager for loading/saving plans.
            logger: Optional logger for tracking operations.
        """
        self.agent = agent
        self.state_manager = state_manager
        self.logger = logger

    def update_plan(
        self, change_request: str, current_task_index: int | None = None
    ) -> dict[str, Any]:
        """Update the plan based on a change request.

        This method:
        1. Loads the current plan from state
        2. Loads optional goal and context
        3. Runs Claude to analyze and update the plan
        4. Validates the model's output, backs up plan.md, and saves the
           updated plan only if it is safe to do so
        5. Reconciles the positional task index against the rewritten plan
        6. Returns the result

        The model's raw response is never trusted blindly: a prose reply,
        refusal, or truncated plan would otherwise overwrite ``plan.md`` and
        destroy the task list (including ``[x]`` history). The extracted plan
        is applied only when it parses to a non-empty task list and does not
        drop any already-completed tasks; otherwise the existing plan is kept
        and ``changes_made`` is ``False``.

        Args:
            change_request: The change request message describing what to update.
            current_task_index: The run's current positional task index. When
                provided, the description of that task is captured before the
                update and re-located afterwards so an insertion or removal
                above it does not silently shift the pointer to a different
                task. Pass ``None`` (default) to skip index reconciliation.

        Returns:
            Dict with keys:
            - 'success': bool - whether the update succeeded
            - 'plan': str - the plan content now on disk (updated when changes
              were applied, otherwise the unchanged current plan)
            - 'raw_output': str - the raw response from Claude
            - 'changes_made': bool - whether the plan was actually modified
            - 'current_task_index': int | None - the reconciled task index when
              a change was applied and ``current_task_index`` was provided,
              else ``None``. Callers should adopt it into their in-memory
              state so a subsequent save does not clobber it.

        Raises:
            ValueError: If no current plan exists to update.
        """
        # Load current plan
        current_plan = self.state_manager.load_plan()
        if not current_plan:
            raise ValueError("No plan exists to update. Use 'start' to create a new plan.")

        # Capture the description of the task the run is currently on, so we can
        # re-locate it after the plan is rewritten (a positional index is
        # fragile when tasks are inserted or removed above it).
        current_task_desc = self._current_task_description(current_plan, current_task_index)

        # Load optional context
        goal = self.state_manager.load_goal()
        context = self.state_manager.load_context()

        # Build the update prompt
        prompt = build_plan_update_prompt(
            current_plan=current_plan,
            change_request=change_request,
            goal=goal if goal else None,
            context=context if context else None,
        )

        if self.logger:
            self.logger.log_prompt(f"Plan update request: {change_request[:100]}...")

        # Run the query using the agent's planning tools (read-only)
        result = self._run_plan_update_query(prompt)

        # Extract the updated plan from the result
        updated_plan = self._extract_updated_plan(result)

        # Validate before overwriting: only apply a genuinely-changed plan that
        # still parses to real tasks and keeps every completed task.
        changes_made = self._is_safe_update(current_plan, updated_plan)

        reconciled_index: int | None = None
        if changes_made:
            # Snapshot the pre-update plan so a bad overwrite is recoverable.
            self.state_manager.backup_plan()
            self.state_manager.save_plan(updated_plan)
            reconciled_index = self._relocate_task_index(
                updated_plan, current_task_desc, current_task_index
            )
            if self.logger:
                self.logger.log_response("Plan updated and saved")
        else:
            if self.logger:
                self.logger.log_response("No changes needed to plan")

        return {
            "success": True,
            "plan": updated_plan if changes_made else current_plan,
            "raw_output": result,
            "changes_made": changes_made,
            "current_task_index": reconciled_index,
        }

    def _is_safe_update(self, current_plan: str, updated_plan: str) -> bool:
        """Decide whether the extracted plan may overwrite ``plan.md``.

        Guards against the model returning prose, a refusal, or a truncated
        plan that would destroy the task list. The update is applied only when
        it differs from the current plan, parses to at least one task, and does
        not drop any already-completed task.

        Args:
            current_plan: The plan currently on disk.
            updated_plan: The plan extracted from the model response.

        Returns:
            True if the update is safe to persist, False otherwise.
        """
        # No meaningful change → nothing to do.
        if updated_plan.strip() == current_plan.strip():
            return False

        # A response with no parseable tasks is prose/refusal/truncation;
        # overwriting would wipe the task list.
        if not parse_task_descriptions(updated_plan):
            if self.logger:
                self.logger.log_response(
                    "Plan update rejected: response has no tasks; keeping existing plan"
                )
            return False

        # Never regress completed-task history (protects `[x]` markers).
        if count_completed_tasks(updated_plan) < count_completed_tasks(current_plan):
            if self.logger:
                self.logger.log_response(
                    "Plan update rejected: would drop completed tasks; keeping existing plan"
                )
            return False

        return True

    def _current_task_description(self, plan: str, task_index: int | None) -> str | None:
        """Return the description of the task at ``task_index`` in ``plan``.

        Args:
            plan: The plan markdown to read.
            task_index: The positional task index, or None to skip.

        Returns:
            The task description, or None if ``task_index`` is None or out of
            range (e.g. the run has advanced past the last task).
        """
        if task_index is None:
            return None
        tasks = parse_task_descriptions(plan)
        if 0 <= task_index < len(tasks):
            return tasks[task_index]
        return None

    def _relocate_task_index(
        self, updated_plan: str, task_desc: str | None, previous_index: int | None
    ) -> int | None:
        """Find the new position of the current task in the rewritten plan.

        Args:
            updated_plan: The saved, rewritten plan.
            task_desc: Description of the task the run was on, captured before
                the update, or None if there was no in-range current task.
            previous_index: The index passed to :meth:`update_plan`; when None,
                index reconciliation was not requested and None is returned.

        Returns:
            The index of ``task_desc`` in the updated plan; if that task no
            longer exists (removed or renamed), the first incomplete task
            index instead; or None when reconciliation was not requested.
        """
        if previous_index is None:
            return None
        if task_desc is not None:
            new_tasks = parse_task_descriptions(updated_plan)
            if task_desc in new_tasks:
                return new_tasks.index(task_desc)
        # The current task is gone (or there was none): resume from the first
        # unchecked task, which stays valid even when everything is complete.
        return first_incomplete_task_index(updated_plan)

    def _run_plan_update_query(self, prompt: str) -> str:
        """Run the plan update query using the agent.

        Args:
            prompt: The complete plan update prompt.

        Returns:
            The raw response from Claude.
        """
        from .agent_models import ModelType

        # Use the agent's query executor directly with planning tools
        # Always use Opus for plan updates (requires strategic thinking)
        result = run_async_with_cleanup(
            self.agent._query_executor.run_query(
                prompt=prompt,
                tools=self.agent.get_tools_for_phase("planning"),
                model_override=ModelType.OPUS,
                get_model_name_func=self.agent._get_model_name,
                get_agents_func=None,  # No subagents for plan update
                process_message_func=self.agent._message_processor.process_message,
            )
        )

        return result

    def _extract_updated_plan(self, result: str) -> str:
        """Extract the updated plan from the Claude response.

        Looks for the plan content between Task List header and the
        PLAN UPDATE COMPLETE marker.

        Args:
            result: The raw response from Claude.

        Returns:
            The extracted plan content.
        """
        # Try to find the plan content
        plan_content = result

        # Remove the PLAN UPDATE COMPLETE marker if present
        if "PLAN UPDATE COMPLETE" in plan_content:
            plan_content = plan_content.split("PLAN UPDATE COMPLETE")[0]

        # If response has Task List header, extract from there
        if "## Task List" in plan_content:
            # Find the start of the plan
            start_idx = plan_content.find("## Task List")
            plan_content = plan_content[start_idx:]

        return plan_content.strip()

    def update_plan_from_messages(self, messages: list[str]) -> dict[str, Any]:
        """Update the plan from multiple messages (e.g., from mailbox).

        Merges multiple messages into a single change request and updates
        the plan accordingly.

        Args:
            messages: List of message strings to process.

        Returns:
            Dict with update results (same as update_plan).

        Raises:
            ValueError: If no messages provided or no plan exists.
        """
        if not messages:
            raise ValueError("No messages provided for plan update")

        # Merge messages into a single change request
        if len(messages) == 1:
            change_request = messages[0]
        else:
            # Format multiple messages with clear separation
            merged_parts = []
            for i, msg in enumerate(messages, 1):
                merged_parts.append(f"### Change Request {i}\n{msg}")
            change_request = "\n\n".join(merged_parts)
            change_request = (
                f"**Multiple change requests received ({len(messages)} total):**\n\n"
                f"{change_request}\n\n"
                f"**Please address ALL of these change requests in the plan update.**"
            )

        return self.update_plan(change_request)
