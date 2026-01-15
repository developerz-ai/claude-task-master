"""PR Cycle Manager - Handles create → CI wait → address comments → merge cycle."""

import time

from ..core.agent import AgentWrapper
from ..core.state import StateManager, TaskState
from .client import GitHubClient, PRStatus


class PRCycleManager:
    """Manages the PR lifecycle."""

    def __init__(
        self,
        github_client: GitHubClient,
        state_manager: StateManager,
        agent: AgentWrapper,
    ):
        """Initialize PR cycle manager."""
        self.github = github_client
        self.state_manager = state_manager
        self.agent = agent

    def create_or_update_pr(self, title: str, body: str, state: TaskState) -> int:
        """Create a new PR or update existing one."""
        if state.current_pr:
            # TODO: Update existing PR
            return state.current_pr

        # Create new PR
        pr_number = self.github.create_pr(title=title, body=body)
        state.current_pr = pr_number
        self.state_manager.save_state(state)

        return pr_number

    def wait_for_pr_ready(
        self, pr_number: int, state: TaskState, poll_interval: int = 30
    ) -> tuple[bool, str]:
        """
        Wait for PR to be ready to merge.

        Returns:
            (ready: bool, reason: str)
        """
        while True:
            status = self.github.get_pr_status(pr_number)

            # Check CI status
            if status.ci_state == "PENDING":
                print(f"CI checks pending, waiting {poll_interval}s...")
                time.sleep(poll_interval)
                continue

            if status.ci_state == "FAILURE" or status.ci_state == "ERROR":
                return False, self._format_ci_failure(status)

            # Check for unresolved comments
            if status.unresolved_threads > 0:
                return False, "unresolved_comments"

            # PR is ready!
            return True, "success"

    def handle_pr_cycle(self, pr_number: int, state: TaskState) -> bool:
        """
        Handle full PR cycle until merged or blocked.

        Returns:
            True if merged, False if blocked
        """
        while True:
            ready, reason = self.wait_for_pr_ready(pr_number, state)

            if ready:
                # Try to merge
                if state.options.auto_merge:
                    self.github.merge_pr(pr_number)
                    state.current_pr = None
                    self.state_manager.save_state(state)
                    return True
                else:
                    # Manual merge required
                    print(f"PR #{pr_number} ready but auto_merge disabled")
                    return False

            # PR not ready - handle the issue
            if reason == "unresolved_comments":
                # Get comments and create fix session
                comments = self.github.get_pr_comments(pr_number)
                self._run_fix_session(state, f"Address PR comments:\n\n{comments}")

            elif reason.startswith("ci_failure:"):
                # Run fix session for CI failure
                self._run_fix_session(state, f"Fix CI failures:\n\n{reason}")

            else:
                # Unknown issue
                print(f"PR blocked: {reason}")
                return False

            # Check session limit
            if state.options.max_sessions and state.session_count >= state.options.max_sessions:
                return False

    def _run_fix_session(self, state: TaskState, issue_description: str) -> None:
        """Run a work session to fix an issue."""
        context = self.state_manager.load_context()

        # Run agent to address the issue
        self.agent.run_work_session(
            task_description=issue_description,
            context=context,
        )

        # Increment session count
        state.session_count += 1
        self.state_manager.save_state(state)

        # TODO: Log the session

    def _format_ci_failure(self, status: PRStatus) -> str:
        """Format CI failure details for Claude."""
        lines = ["ci_failure:"]

        for check in status.check_details:
            if check["conclusion"] in ("FAILURE", "ERROR"):
                lines.append(f"- {check['name']}: {check['conclusion']}")
                if check.get("url"):
                    lines.append(f"  URL: {check['url']}")

        return "\n".join(lines)
