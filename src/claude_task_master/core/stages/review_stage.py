"""ReviewStageMixin — waiting-for-reviews and addressing-reviews stages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import console
from ..agent import ModelType
from ..shutdown import interruptible_sleep
from .pr_fix_stage import _PRFixStage

if TYPE_CHECKING:
    from ..state import TaskState


class _ReviewStage(_PRFixStage):
    """Mixin: review-comment polling and agent-driven comment resolution."""

    def handle_waiting_reviews_stage(self, state: TaskState) -> int | None:
        """Handle waiting for reviews - check for review comments."""
        if state.current_pr is None:
            state.workflow_stage = "merged"
            self.state_manager.save_state(state)
            return None

        console.info(f"Checking reviews for PR #{state.current_pr}...")

        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)

            # Check if PR was already merged (e.g., manually)
            if pr_status.state == "MERGED":
                console.success(
                    f"PR #{state.current_pr} was already merged - skipping to next task"
                )
                state.workflow_stage = "merged"
                self.state_manager.save_state(state)
                return None

            # Check if PR was closed without merging
            if pr_status.state == "CLOSED":
                console.warning(f"PR #{state.current_pr} was closed without merging")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1

            # Check if ANY checks are still pending (CI, review bots, etc)
            # Local import: cli_commands/__init__ imports core.orchestrator,
            # so a top-level import here would be circular.
            from ...cli_commands.ci_helpers import is_check_pending

            pending_checks = [
                self._get_check_name(check)
                for check in pr_status.check_details
                if is_check_pending(check)
            ]

            if pending_checks:
                # Use ci_poll_start_time for timeout (shared with waiting_ci stage)
                if self._is_ci_poll_timed_out(state):
                    console.warning(
                        f"Review checks timed out after {self.CI_POLL_TIMEOUT}s - "
                        f"proceeding with {len(pending_checks)} checks still pending"
                    )
                    self._clear_ci_poll_timer(state)
                else:
                    # Start timer if not already running
                    if state.ci_poll_start_time is None:
                        from datetime import datetime

                        state.ci_poll_start_time = datetime.now()
                        self.state_manager.save_state(state)
                    console.info(
                        f"Waiting for checks to finish: {', '.join(pending_checks[:3])}..."
                    )
                    if not interruptible_sleep(self.CI_POLL_INTERVAL):
                        return None
                    return None  # Will re-check on next cycle

            # Get threads we've already addressed (to show accurate count)
            addressed_threads = self.state_manager.get_addressed_threads(state.current_pr)
            # Actionable = unresolved threads that we haven't already addressed
            actionable_threads = pr_status.unresolved_threads - len(
                [t for t in addressed_threads if t]  # Count non-empty addressed thread IDs
            )
            # Clamp to 0 in case addressed count is stale
            actionable_threads = max(0, actionable_threads)

            if actionable_threads > 0:
                console.warning(
                    f"Found {actionable_threads} actionable / "
                    f"{pr_status.total_threads} total review comments"
                )
                state.workflow_stage = "addressing_reviews"
                self.state_manager.save_state(state)
                return None
            elif pr_status.unresolved_threads > 0:
                # All unresolved threads are addressed but not yet resolved on GitHub
                # This can happen if resolution failed - retry
                console.info(
                    f"Found {pr_status.unresolved_threads} unresolved threads "
                    "(all previously addressed, will retry resolution)"
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

        # Save comments to files and get actual count of actionable comments
        saved_count = self.pr_context.save_pr_comments(state.current_pr)
        console.info(f"Saved {saved_count} actionable comment(s) for review")

        # If no actionable comments, just try to resolve already-addressed threads
        # This prevents infinite loops where threads were replied to but not resolved
        if saved_count == 0:
            resolved = self.pr_context.resolve_addressed_threads(state.current_pr)
            if resolved > 0:
                console.success(
                    f"Resolved {resolved} previously-addressed threads (no agent needed)"
                )
            else:
                console.info("No actionable comments and no threads to resolve")
                # Nothing changed on GitHub: without a pause, waiting_reviews
                # sends us straight back here and the two stages spin hot
                # against the API (observed when save_pr_comments raised).
                if not interruptible_sleep(self.CI_POLL_INTERVAL):
                    return None
            # Go back to waiting_reviews to re-check
            state.workflow_stage = "waiting_reviews"
            self.state_manager.save_state(state)
            return None

        # Build fix prompt
        pr_dir = self.state_manager.get_pr_dir(state.current_pr) if state.current_pr else None
        comments_path = f"{pr_dir}/comments/" if pr_dir else ".claude-task-master/debugging/"
        resolve_json_path = (
            f"{pr_dir}/resolve-comments.json"
            if pr_dir
            else ".claude-task-master/debugging/resolve-comments.json"
        )

        task_description = f"""PR #{state.current_pr} has review comments to address.

**Read comments from:** `{comments_path}` (Glob *.txt, then Read each)

For each comment: fix it or explain why not. Then:
1. Run tests
2. Commit with descriptive message
3. Push to update the PR: `git push origin HEAD` (do NOT rebase or force-push — it breaks review threads; if rejected: `git pull --rebase origin HEAD`, resolve, re-test, push)
4. Create resolution file at `{resolve_json_path}`:

```json
{{
  "pr": {state.current_pr},
  "resolutions": [
    {{
      "thread_id": "THREAD_ID_FROM_COMMENT_FILE",
      "action": "fixed|explained|skipped",
      "message": "Brief explanation (1 sentence)"
    }}
  ]
}}
```

**Keep resolution messages short and direct.** "Fixed: capped exponent with coerceAtMost(5)" not "I've addressed this by implementing a fix that caps the exponent value using coerceAtMost(5) to prevent overflow."

Copy Thread ID from each comment file. Do NOT resolve threads via GraphQL — orchestrator handles that.

End with: TASK COMPLETE"""

        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        required_branch = self._get_pr_head_branch(state)
        # Fix an EXISTING PR: push to re-trigger CI, never open a new PR or
        # rebase (push_only routes through _build_push_only_execution).
        self.agent.run_work_session(
            task_description=task_description,
            context=context,
            model_override=ModelType.OPUS,
            required_branch=required_branch,
            create_pr=False,
            push_only=True,
        )

        # Post replies to comments using resolution file
        self.pr_context.post_comment_replies(state.current_pr)

        # Wait for CI to start after push
        console.info("Waiting 60s for CI to start...")
        if not interruptible_sleep(60):
            return None

        state.workflow_stage = "waiting_ci"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None
