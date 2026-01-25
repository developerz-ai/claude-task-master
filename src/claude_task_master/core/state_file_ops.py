"""File Operations for State Manager.

This module provides methods for managing file-based state data,
including goal, criteria, plan, progress, context files and plan parsing.

These methods are mixed into the StateManager class via the FileOperationsMixin.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class FileOperationsMixin:
    """Mixin providing file operations methods for StateManager.

    This mixin adds methods to handle reading and writing of various
    text-based state files (goal, criteria, plan, progress, context).

    Requires:
        - self.state_dir: Path to the state directory
    """

    # This will be set by StateManager
    state_dir: Path

    def save_goal(self, goal: str) -> None:
        """Save goal to goal.txt.

        Args:
            goal: The task goal description.
        """
        goal_file = self.state_dir / "goal.txt"
        goal_file.write_text(goal)

    def load_goal(self) -> str:
        """Load goal from goal.txt.

        Returns:
            The task goal description.
        """
        goal_file = self.state_dir / "goal.txt"
        return goal_file.read_text()

    def save_criteria(self, criteria: str) -> None:
        """Save success criteria to criteria.txt.

        Args:
            criteria: The success criteria text.
        """
        criteria_file = self.state_dir / "criteria.txt"
        criteria_file.write_text(criteria)

    def load_criteria(self) -> str | None:
        """Load success criteria from criteria.txt.

        Returns:
            The success criteria text, or None if not found.
        """
        criteria_file = self.state_dir / "criteria.txt"
        if criteria_file.exists():
            return criteria_file.read_text()
        return None

    def save_plan(self, plan: str) -> None:
        """Save task plan to plan.md.

        Args:
            plan: The task plan in markdown format.
        """
        plan_file = self.state_dir / "plan.md"
        plan_file.write_text(plan)

    def load_plan(self) -> str | None:
        """Load task plan from plan.md.

        Returns:
            The task plan content, or None if not found.
        """
        plan_file = self.state_dir / "plan.md"
        if plan_file.exists():
            return plan_file.read_text()
        return None

    def save_progress(self, progress: str) -> None:
        """Save progress summary to progress.md.

        Args:
            progress: The progress summary in markdown format.
        """
        progress_file = self.state_dir / "progress.md"
        progress_file.write_text(progress)

    def load_progress(self) -> str | None:
        """Load progress summary from progress.md.

        Returns:
            The progress summary content, or None if not found.
        """
        progress_file = self.state_dir / "progress.md"
        if progress_file.exists():
            return progress_file.read_text()
        return None

    def save_context(self, context: str) -> None:
        """Save accumulated context to context.md.

        Args:
            context: The accumulated context in markdown format.
        """
        context_file = self.state_dir / "context.md"
        context_file.write_text(context)

    def load_context(self) -> str:
        """Load accumulated context from context.md.

        Returns:
            The accumulated context, or empty string if not found.
        """
        context_file = self.state_dir / "context.md"
        if context_file.exists():
            return context_file.read_text()
        return ""

    def save_coding_style(self, coding_style: str) -> None:
        """Save coding style guide to coding-style.md.

        Args:
            coding_style: The coding style guide content.
        """
        coding_style_file = self.state_dir / "coding-style.md"
        coding_style_file.write_text(coding_style)

    def load_coding_style(self) -> str | None:
        """Load coding style guide from coding-style.md.

        Returns:
            The coding style guide content, or None if not found.
        """
        coding_style_file = self.state_dir / "coding-style.md"
        if coding_style_file.exists():
            return coding_style_file.read_text()
        return None

    def _parse_plan_tasks(self, plan: str) -> list[str]:
        """Parse tasks from plan markdown.

        Extracts task descriptions from markdown checkbox lines.

        Args:
            plan: The plan content in markdown format.

        Returns:
            List of task descriptions extracted from the plan.
        """
        tasks = []
        for line in plan.split("\n"):
            # Look for markdown checkbox lines
            stripped = line.strip()
            if stripped.startswith("- [ ]") or stripped.startswith("- [x]"):
                task = stripped[5:].strip()  # Remove "- [ ]" or "- [x]"
                if task:
                    tasks.append(task)
        return tasks
