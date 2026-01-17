"""Workflow Stage Handlers - Handle each stage of the PR workflow."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING

from . import console
from .agent import ModelType
from .shutdown import interruptible_sleep

if TYPE_CHECKING:
    from ..github.client import GitHubClient
    from .agent import AgentWrapper
    from .orchestrator import TaskState
    from .pr_context import PRContextManager
    from .state import StateManager


class WorkflowStageHandler:
    """Handles individual workflow stages in the PR lifecycle.

    Workflow stages:
    1. working → Implement tasks
    2. pr_created → Create/update PR
    3. waiting_ci → Poll CI status
    4. ci_failed → Fix CI failures
    5. waiting_reviews → Wait for reviews
    6. addressing_reviews → Address review feedback
    7. ready_to_merge → Merge PR
    8. merged → Move to next task
    """

    # CI polling configuration
    CI_POLL_INTERVAL = 10  # seconds between CI status checks

    @staticmethod
    def _get_check_name(check: dict) -> str:
        """Get check name from either CheckRun or StatusContext.

        CheckRun has 'name' field, StatusContext has 'context' field.
        """
        return str(check.get("name") or check.get("context", "unknown"))

    @staticmethod
    def _get_current_branch() -> str | None:
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

    @staticmethod
    def _checkout_branch(branch: str) -> bool:
        """Checkout to a branch.

        Args:
            branch: Branch name to checkout.

        Returns:
            True if successful, False otherwise.
        """
        try:
            subprocess.run(
                ["git", "checkout", branch],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "pull"],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            console.warning(f"Failed to checkout {branch}: {e}")
            return False

    def __init__(
        self,
        agent: AgentWrapper,
        state_manager: StateManager,
        github_client: GitHubClient,
        pr_context: PRContextManager,
    ):
        """Initialize stage handler.

        Args:
            agent: The agent wrapper for running queries.
            state_manager: The state manager for persistence.
            github_client: GitHub client for PR operations.
            pr_context: PR context manager for comments/CI logs.
        """
        self.agent = agent
        self.state_manager = state_manager
        self.github_client = github_client
        self.pr_context = pr_context

    def handle_pr_created_stage(self, state: TaskState) -> int | None:
        """Handle PR creation - detect PR from current branch."""
        console.info("Checking PR status...")

        # Try to detect PR number from current branch if not already set
        if state.current_pr is None:
            try:
                pr_number = self.github_client.get_pr_for_current_branch(cwd=os.getcwd())
                if pr_number:
                    console.success(f"Detected PR #{pr_number} for current branch")
                    state.current_pr = pr_number
                    self.state_manager.save_state(state)
                else:
                    console.detail("No PR found for current branch - skipping CI wait")
                    state.workflow_stage = "merged"  # Skip to next task
                    self.state_manager.save_state(state)
                    return None
            except Exception as e:
                console.warning(f"Could not detect PR: {e}")
                state.workflow_stage = "merged"  # Skip to next task
                self.state_manager.save_state(state)
                return None

        console.detail(f"PR #{state.current_pr} - moving to CI check")
        state.workflow_stage = "waiting_ci"
        self.state_manager.save_state(state)
        return None

    def handle_waiting_ci_stage(self, state: TaskState) -> int | None:
        """Handle waiting for CI - poll CI status."""
        if state.current_pr is None:
            state.workflow_stage = "waiting_reviews"
            self.state_manager.save_state(state)
            return None

        console.info(f"Checking CI status for PR #{state.current_pr}...")

        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)

            if pr_status.ci_state == "SUCCESS":
                console.success(
                    f"CI passed! ({pr_status.checks_passed} passed, "
                    f"{pr_status.checks_skipped} skipped)"
                )
                state.workflow_stage = "waiting_reviews"
                self.state_manager.save_state(state)
                return None
            elif pr_status.ci_state in ("FAILURE", "ERROR"):
                # Wait for ALL checks to complete before handling failure
                if pr_status.checks_pending > 0:
                    console.warning(
                        f"CI has failures but {pr_status.checks_pending} checks still pending..."
                    )
                    console.detail("Waiting for all checks to complete...")
                    if not interruptible_sleep(self.CI_POLL_INTERVAL):
                        return None
                    return None  # Retry on next cycle

                console.warning(
                    f"CI failed: {pr_status.checks_failed} failed, {pr_status.checks_passed} passed"
                )
                for check in pr_status.check_details:
                    conclusion = (check.get("conclusion") or "").upper()
                    if conclusion in ("FAILURE", "ERROR"):
                        check_name = self._get_check_name(check)
                        console.detail(f"  ✗ {check_name}: {conclusion}")
                state.workflow_stage = "ci_failed"
                self.state_manager.save_state(state)
                return None
            else:
                console.info(
                    f"Waiting for CI... ({pr_status.checks_pending} pending, "
                    f"{pr_status.checks_passed} passed)"
                )
                # Show individual check statuses if available
                for check in pr_status.check_details:
                    status = (check.get("status") or "").upper()
                    check_name = self._get_check_name(check)
                    if status in ("IN_PROGRESS", "PENDING"):
                        console.detail(f"  ⏳ {check_name}: running")
                    elif status == "QUEUED":
                        console.detail(f"  ⏸ {check_name}: queued")
                console.detail(f"Next check in {self.CI_POLL_INTERVAL}s...")
                if not interruptible_sleep(self.CI_POLL_INTERVAL):
                    return None  # Let main loop handle cancellation
                return None

        except Exception as e:
            console.warning(f"Error checking CI: {e}")
            console.detail("Will retry on next cycle...")
            # Stay in waiting_ci and retry - do NOT fall through to merge
            if not interruptible_sleep(self.CI_POLL_INTERVAL):
                return None
            return None

    def handle_ci_failed_stage(self, state: TaskState) -> int | None:
        """Handle CI failure - run agent to fix issues."""
        console.info("CI failed - running agent to fix...")

        # Save CI failure logs
        self.pr_context.save_ci_failures(state.current_pr)

        # Build fix prompt
        pr_dir = self.state_manager.get_pr_dir(state.current_pr) if state.current_pr else None
        ci_path = f"{pr_dir}/ci/" if pr_dir else ".claude-task-master/debugging/"

        task_description = f"""CI has failed for PR #{state.current_pr}.

**Read the CI failure logs from:** `{ci_path}`

Use Glob to find all .txt files, then Read each one to understand the errors.

**IMPORTANT:** Fix ALL CI failures, even if they seem unrelated to your current work.
Your job is to keep CI green. Pre-existing issues, flaky tests, lint errors - fix them all.

Please:
1. Read ALL files in the ci/ directory
2. Understand ALL error messages (lint, tests, types, etc.)
3. Fix everything that's failing - don't skip anything
4. Run tests/lint locally to verify ALL passes
5. Commit and push the fixes

After fixing, end with: TASK COMPLETE"""

        # Run agent with Opus for complex debugging
        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        current_branch = self._get_current_branch()
        self.agent.run_work_session(
            task_description=task_description,
            context=context,
            model_override=ModelType.OPUS,
            required_branch=current_branch,
        )

        # Wait for CI to start after push
        console.info("Waiting 30s for CI to start...")
        if not interruptible_sleep(30):
            return None

        state.workflow_stage = "waiting_ci"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None

    def handle_waiting_reviews_stage(self, state: TaskState) -> int | None:
        """Handle waiting for reviews - check for review comments."""
        if state.current_pr is None:
            state.workflow_stage = "merged"
            self.state_manager.save_state(state)
            return None

        console.info(f"Checking reviews for PR #{state.current_pr}...")

        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)

            # Check if ANY checks are still pending (CI, review bots, etc)
            pending_checks = [
                self._get_check_name(check)
                for check in pr_status.check_details
                if check.get("status", "").upper()
                not in ("COMPLETED", "SUCCESS", "FAILURE", "ERROR", "SKIPPED")
                or check.get("conclusion") is None
                and check.get("status", "").upper() != "COMPLETED"
            ]

            if pending_checks:
                console.info(f"Waiting for checks to finish: {', '.join(pending_checks[:3])}...")
                if not interruptible_sleep(self.CI_POLL_INTERVAL):
                    return None
                return None  # Will re-check on next cycle

            if pr_status.unresolved_threads > 0:
                console.warning(
                    f"Found {pr_status.unresolved_threads} unresolved / "
                    f"{pr_status.total_threads} total review comments"
                )
                state.workflow_stage = "addressing_reviews"
                self.state_manager.save_state(state)
                return None
            else:
                if pr_status.total_threads > 0:
                    console.success(f"All {pr_status.resolved_threads} review comments resolved!")
                else:
                    console.success("No review comments!")
                state.workflow_stage = "ready_to_merge"
                self.state_manager.save_state(state)
                return None

        except Exception as e:
            console.warning(f"Error checking reviews: {e}")
            console.detail("Will retry on next cycle...")
            # Stay in waiting_reviews and retry - do NOT fall through to merge
            if not interruptible_sleep(self.CI_POLL_INTERVAL):
                return None
            return None

    def handle_addressing_reviews_stage(self, state: TaskState) -> int | None:
        """Handle addressing reviews - run agent to fix review comments."""
        console.info("Addressing review comments...")

        # Save comments to files
        self.pr_context.save_pr_comments(state.current_pr)

        # Build fix prompt
        pr_dir = self.state_manager.get_pr_dir(state.current_pr) if state.current_pr else None
        comments_path = f"{pr_dir}/comments/" if pr_dir else ".claude-task-master/debugging/"
        resolve_json_path = (
            f"{pr_dir}/resolve-comments.json"
            if pr_dir
            else ".claude-task-master/debugging/resolve-comments.json"
        )

        task_description = f"""PR #{state.current_pr} has review comments to address.

**Read the review comments from:** `{comments_path}`

Use Glob to find all .txt files, then Read each one to understand the feedback.

Please:
1. Read ALL comment files in the comments/ directory
2. For each comment:
   - Make the requested change, OR
   - Explain why it's not needed
3. Run tests to verify
4. Commit and push the fixes
5. Create a resolution summary file at: `{resolve_json_path}`

**Resolution file format:**
```json
{{
  "pr": {state.current_pr},
  "resolutions": [
    {{
      "thread_id": "THREAD_ID_FROM_COMMENT_FILE",
      "action": "fixed|explained|skipped",
      "message": "Brief explanation of what was done"
    }}
  ]
}}
```

Copy the Thread ID from each comment file into the resolution JSON.

After addressing ALL comments and creating the resolution file, end with: TASK COMPLETE"""

        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        current_branch = self._get_current_branch()
        self.agent.run_work_session(
            task_description=task_description,
            context=context,
            model_override=ModelType.OPUS,
            required_branch=current_branch,
        )

        # Post replies to comments using resolution file
        self.pr_context.post_comment_replies(state.current_pr)

        # Wait for CI to start after push
        console.info("Waiting 30s for CI to start...")
        if not interruptible_sleep(30):
            return None

        state.workflow_stage = "waiting_ci"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None

    def handle_ready_to_merge_stage(self, state: TaskState) -> int | None:
        """Handle ready to merge - merge the PR if auto_merge enabled."""
        if state.current_pr is None:
            state.workflow_stage = "merged"
            self.state_manager.save_state(state)
            return None

        # Check if PR has conflicts
        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)
            if pr_status.mergeable == "CONFLICTING":
                console.warning(f"PR #{state.current_pr} has merge conflicts!")
                console.detail("Conflicts must be resolved before merging")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1
            elif pr_status.mergeable == "UNKNOWN":
                console.info("Waiting for GitHub to calculate mergeable status...")
                if not interruptible_sleep(self.CI_POLL_INTERVAL):
                    return None
                return None  # Retry on next cycle
        except Exception as e:
            console.warning(f"Error checking mergeable status: {e}")
            # Continue trying to merge anyway

        if state.options.auto_merge:
            console.info(f"Merging PR #{state.current_pr}...")
            try:
                self.github_client.merge_pr(state.current_pr)
                console.success(f"PR #{state.current_pr} merged!")
                state.workflow_stage = "merged"
                self.state_manager.save_state(state)
                return None
            except Exception as e:
                console.warning(f"Auto-merge failed: {e}")
                console.detail("PR may need manual merge or have merge conflicts")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1
        else:
            console.info(f"PR #{state.current_pr} ready to merge (auto_merge disabled)")
            console.detail("Use 'claudetm resume' after manual merge")
            state.status = "paused"
            self.state_manager.save_state(state)
            return 2

    def handle_merged_stage(
        self, state: TaskState, mark_task_complete_fn: Callable[[str, int], None]
    ) -> int | None:
        """Handle merged state - move to next task.

        Args:
            state: Current task state.
            mark_task_complete_fn: Function to mark task complete in plan.
        """
        console.success(f"Task #{state.current_task_index + 1} complete!")

        # Mark task as complete in plan
        plan = self.state_manager.load_plan()
        if plan:
            mark_task_complete_fn(plan, state.current_task_index)

        # Clear PR context files and checkout to base branch (only if PR was merged)
        if state.current_pr is not None:
            base_branch = "main"
            try:
                # Get base branch from PR before clearing
                pr_status = self.github_client.get_pr_status(state.current_pr)
                base_branch = pr_status.base_branch
            except Exception:
                pass  # Use default main

            try:
                self.state_manager.clear_pr_context(state.current_pr)
            except Exception:
                pass  # Best effort cleanup

            # Checkout to base branch to avoid conflicts on next task
            console.info(f"Checking out to {base_branch}...")
            if self._checkout_branch(base_branch):
                console.success(f"Switched to {base_branch}")
            else:
                console.warning(f"Could not checkout to {base_branch}, may need manual checkout")

        # Move to next task
        state.current_task_index += 1
        state.current_pr = None
        state.workflow_stage = "working"
        self.state_manager.save_state(state)

        return None
