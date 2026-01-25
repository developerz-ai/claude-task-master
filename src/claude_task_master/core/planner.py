"""Planner - Orchestrates initial planning phase (read-only tools)."""

from typing import Any

from . import console
from .agent import AgentWrapper
from .state import StateManager


class Planner:
    """Handles the initial planning phase."""

    def __init__(self, agent: AgentWrapper, state_manager: StateManager):
        """Initialize planner."""
        self.agent = agent
        self.state_manager = state_manager

    def ensure_coding_style(self) -> str | None:
        """Ensure coding style guide exists, generating it if needed.

        Checks if coding-style.md exists. If not, generates it by analyzing
        CLAUDE.md and convention files in the codebase.

        Returns:
            The coding style guide content, or None if generation failed.
        """
        # Check if coding style already exists
        coding_style = self.state_manager.load_coding_style()
        if coding_style:
            console.info("Using existing coding style guide")
            return coding_style

        # Generate coding style by analyzing codebase
        console.info("Generating coding style guide from codebase...")
        result = self.agent.generate_coding_style()

        coding_style_content: str = result.get("coding_style", "")
        if coding_style_content:
            self.state_manager.save_coding_style(coding_style_content)
            console.success("Coding style guide generated and saved")
            return coding_style_content

        console.warning("Could not generate coding style guide")
        return None

    def create_plan(self, goal: str) -> dict[str, Any]:
        """Create initial task plan using read-only tools.

        First generates coding style guide if it doesn't exist, then
        runs planning phase with the coding style injected.
        """
        # Ensure coding style exists (generate if needed)
        coding_style = self.ensure_coding_style()

        # Load any existing context
        context = self.state_manager.load_context()

        # Run planning phase with Claude (with coding style)
        result = self.agent.run_planning_phase(
            goal=goal, context=context, coding_style=coding_style
        )

        # Extract plan and criteria from result
        plan = result.get("plan", "")
        criteria = result.get("criteria", "")

        # Save to state
        if plan:
            self.state_manager.save_plan(plan)
        if criteria:
            self.state_manager.save_criteria(criteria)

        return result

    def update_plan_progress(self, task_index: int, completed: bool) -> None:
        """Update task completion status in plan."""
        plan = self.state_manager.load_plan()
        if not plan:
            return

        # TODO: Parse markdown checkboxes and update status
        # This will require parsing the plan.md file and toggling checkboxes

        self.state_manager.save_plan(plan)
