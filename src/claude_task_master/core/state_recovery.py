"""State Recovery - Detect and recover real workflow state from GitHub."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .state import WorkflowStageType

if TYPE_CHECKING:
    from ..github.client import GitHubClient
    from .state import TaskState


@dataclass
class RecoveredState:
    """Result of state recovery detection."""

    workflow_stage: WorkflowStageType
    current_pr: int | None
    message: str


class StateRecovery:
    """Detects real workflow state from GitHub for recovery scenarios."""

    def __init__(self, github_client: GitHubClient | None = None):
        """Initialize state recovery.

        Args:
            github_client: Optional GitHub client. Created lazily if not provided.
        """
        self._github_client = github_client

    @property
    def github_client(self) -> GitHubClient:
        """Get or lazily initialize GitHub client."""
        if self._github_client is None:
            from ..github.client import GitHubClient

            self._github_client = GitHubClient()
        return self._github_client

    def detect_real_state(self, cwd: str | None = None) -> RecoveredState:
        """Detect the real workflow state by checking GitHub.

        Args:
            cwd: Working directory (project root).

        Returns:
            RecoveredState with detected workflow stage and PR number.
        """
        cwd = cwd or os.getcwd()

        try:
            # Check for open PR on current branch
            pr_number = self.github_client.get_pr_for_current_branch(cwd=cwd)

            if not pr_number:
                return RecoveredState(
                    workflow_stage="working",
                    current_pr=None,
                    message="No open PR found - resuming work",
                )

            # Get PR status
            pr_status = self.github_client.get_pr_status(pr_number)

            # Determine workflow stage based on PR state
            if pr_status.ci_state in ("FAILURE", "ERROR"):
                return RecoveredState(
                    workflow_stage="ci_failed",
                    current_pr=pr_number,
                    message=f"PR #{pr_number} has CI failure",
                )

            if pr_status.ci_state == "PENDING":
                return RecoveredState(
                    workflow_stage="waiting_ci",
                    current_pr=pr_number,
                    message=f"PR #{pr_number} CI is pending",
                )

            if pr_status.unresolved_threads > 0:
                return RecoveredState(
                    workflow_stage="addressing_reviews",
                    current_pr=pr_number,
                    message=f"PR #{pr_number} has {pr_status.unresolved_threads} unresolved reviews",
                )

            # CI passed, no unresolved reviews
            return RecoveredState(
                workflow_stage="ready_to_merge",
                current_pr=pr_number,
                message=f"PR #{pr_number} is ready to merge",
            )

        except Exception as e:
            return RecoveredState(
                workflow_stage="working",
                current_pr=None,
                message=f"Could not detect PR state: {e}",
            )

    def apply_recovery(self, state: TaskState, cwd: str | None = None) -> RecoveredState:
        """Detect and apply recovered state.

        Args:
            state: The TaskState to update.
            cwd: Working directory.

        Returns:
            The RecoveredState that was applied.
        """
        recovered = self.detect_real_state(cwd)

        state.workflow_stage = recovered.workflow_stage
        state.current_pr = recovered.current_pr
        state.status = "working"

        return recovered
