"""Plan Updater - Updates existing plans based on change requests.

This module handles the plan update workflow when a change request is
received via `claudetm resume "message"` or from the mailbox system.
"""

from typing import TYPE_CHECKING, Any

from .agent_phases import run_async_with_cleanup
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

    def update_plan(self, change_request: str) -> dict[str, Any]:
        """Update the plan based on a change request.

        This method:
        1. Loads the current plan from state
        2. Loads optional goal and context
        3. Runs Claude to analyze and update the plan
        4. Saves the updated plan
        5. Returns the result

        Args:
            change_request: The change request message describing what to update.

        Returns:
            Dict with keys:
            - 'success': bool - whether the update succeeded
            - 'plan': str - the updated plan content
            - 'raw_output': str - the raw response from Claude
            - 'changes_made': bool - whether the plan was actually modified

        Raises:
            ValueError: If no current plan exists to update.
        """
        # Load current plan
        current_plan = self.state_manager.load_plan()
        if not current_plan:
            raise ValueError("No plan exists to update. Use 'start' to create a new plan.")

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

        # Check if plan actually changed
        changes_made = updated_plan.strip() != current_plan.strip()

        # Save the updated plan if changes were made
        if changes_made:
            self.state_manager.save_plan(updated_plan)
            if self.logger:
                self.logger.log_response("Plan updated and saved")
        else:
            if self.logger:
                self.logger.log_response("No changes needed to plan")

        return {
            "success": True,
            "plan": updated_plan,
            "raw_output": result,
            "changes_made": changes_made,
        }

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
