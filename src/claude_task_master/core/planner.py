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

    def ensure_release_guide(self, auto_merge: bool = True) -> str | None:
        """Ensure release guide exists, generating it if needed.

        Checks if release.md exists. If not, generates it by probing the
        project's deploy infrastructure, monitoring, DB access, etc.

        The release guide is optional — if discovery finds nothing to
        verify, it saves a guide that says so and the release phase
        becomes a no-op.

        Args:
            auto_merge: Whether auto-merge is enabled. Skips generation if False.

        Returns:
            The release guide content, or None if generation failed.
        """
        # Check if release guide already exists
        release_guide = self.state_manager.load_release_guide()
        if release_guide:
            console.info("Using existing release guide")
            return release_guide

        # Only generate if auto_merge is enabled
        if not auto_merge:
            console.info("Auto-merge disabled — skipping release guide generation")
            return None

        # Generate release guide by probing infrastructure
        console.info("Discovering release infrastructure...")
        try:
            result = self.agent.generate_release_guide()
        except Exception as e:
            console.warning(f"Could not discover release infrastructure: {e}")
            return None

        release_content: str = result.get("release_guide", "")
        if release_content:
            self.state_manager.save_release_guide(release_content)
            console.success("Release guide generated and saved")
            return release_content

        console.warning("Could not generate release guide")
        return None

    def create_plan(self, goal: str) -> dict[str, Any]:
        """Create initial task plan using read-only tools.

        First generates coding style and release guides if they don't exist,
        then runs planning phase with both injected.
        """
        # Ensure coding style exists (generate if needed)
        coding_style = self.ensure_coding_style()

        # Load state options if available
        auto_merge = True
        max_prs = None
        if self.state_manager.state_file.exists():
            state = self.state_manager.load_state()
            auto_merge = state.options.auto_merge
            max_prs = state.options.max_prs

        # Ensure release guide exists (generate if needed, auto_merge only)
        release_guide = self.ensure_release_guide(auto_merge=auto_merge)

        # Load any existing context
        context = self.state_manager.load_context()

        # Run planning phase with Claude (with coding style, release guide, and max_prs)
        result = self.agent.run_planning_phase(
            goal=goal,
            context=context,
            coding_style=coding_style,
            max_prs=max_prs,
            release_guide=release_guide,
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

        # Note: Checkpoint persistence handles task completion tracking.
        # Plan markdown files serve as human-readable documentation.
        # Direct checkbox updates in plan.md could be added as a feature
        # if UI-level task tracking is needed.

        self.state_manager.save_plan(plan)
