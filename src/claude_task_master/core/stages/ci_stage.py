"""CIStageMixin — CI polling, PR-creation detection, and emit helpers."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .. import console
from ..shutdown import interruptible_sleep
from .git_ops import _GitOps

if TYPE_CHECKING:
    from ..state import TaskState


class _CIStage(_GitOps):
    """Mixin: CI polling, PR-creation detection, CI-event emission."""

    def _emit_ci_event(
        self,
        event_type: str,
        pr_number: int | None,
        branch: str,
        failure_reason: str | None = None,
    ) -> None:
        """Emit a CI webhook event (ci.passed or ci.failed).

        Args:
            event_type: The event type ("ci.passed" or "ci.failed").
            pr_number: The PR number.
            branch: The branch name.
            failure_reason: Optional failure reason (for ci.failed events).
        """
        if self.webhook_emitter is None:
            return

        # Import EventType only when needed
        from ...webhooks.events import EventType

        try:
            if event_type == "ci.passed":
                self.webhook_emitter.emit(
                    EventType.CI_PASSED,
                    pr_number=pr_number or 0,
                    branch=branch,
                )
            elif event_type == "ci.failed":
                self.webhook_emitter.emit(
                    EventType.CI_FAILED,
                    pr_number=pr_number or 0,
                    branch=branch,
                    failure_reason=failure_reason,
                )
        except Exception:
            # Webhooks should never block the workflow
            pass

    def handle_pr_created_stage(self, state: TaskState) -> int | None:
        """Handle PR creation - detect PR from current branch.

        The agent worker should have already created the PR. This stage detects
        the PR and moves to CI waiting.

        If no PR is found, it means the agent failed to create one despite being
        instructed to. In this case, we block and require manual intervention.
        """
        console.info("Checking PR status...")

        # Try to detect PR number from current branch if not already set
        if state.current_pr is None:
            try:
                pr_number = self.github_client.get_pr_for_current_branch(cwd=os.getcwd())
                if pr_number:
                    from datetime import datetime

                    console.success(f"Detected PR #{pr_number} for current branch")
                    state.current_pr = pr_number
                    # Start PR timing when PR is first detected (avoid overwriting on resume)
                    if state.pr_start_time is None:
                        state.pr_start_time = datetime.now()
                    self.state_manager.save_state(state)
                    self._sanitize_pr_body(pr_number)
                else:
                    # No PR found - agent failed to create one
                    console.error("No PR found for current branch!")
                    console.error("The agent was instructed to create a PR but didn't.")
                    console.detail("Manual intervention required:")
                    console.detail("  1. Push the branch: git push -u origin HEAD")
                    console.detail("  2. Create a PR: gh pr create --title 'feat: description'")
                    console.detail("  3. Resume: claudetm resume")
                    state.status = "blocked"
                    self.state_manager.save_state(state)
                    return 1
            except Exception as e:
                console.warning(f"Could not detect PR: {e}")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1

        console.detail(f"PR #{state.current_pr} - moving to CI check")
        state.workflow_stage = "waiting_ci"
        # Start CI poll timer
        if state.ci_poll_start_time is None:
            from datetime import datetime

            state.ci_poll_start_time = datetime.now()
        self.state_manager.save_state(state)
        return None

    def _sanitize_pr_body(self, pr_number: int) -> None:
        """Strip decorative glyphs (e.g. ✓) the agent may have left in the PR body.

        Best-effort: any failure is logged and swallowed so it never blocks the workflow.
        """
        try:
            from ...github.pr_body_sanitizer import strip_decorative_glyphs

            body = self.github_client.get_pr_body(pr_number)
            cleaned = strip_decorative_glyphs(body)
            if cleaned != body:
                self.github_client.update_pr_body(pr_number, cleaned)
                console.detail("Stripped decorative glyphs from PR body")
        except Exception as e:
            console.warning(f"Could not sanitize PR body: {e}")

    def _is_ci_poll_timed_out(self, state: TaskState) -> bool:
        """Check if CI polling has exceeded the timeout."""
        if state.ci_poll_start_time is None:
            return False
        from datetime import datetime

        elapsed = (datetime.now() - state.ci_poll_start_time).total_seconds()
        return elapsed > self.CI_POLL_TIMEOUT

    def _clear_ci_poll_timer(self, state: TaskState) -> None:
        """Clear CI poll timer (called when leaving CI polling stages)."""
        state.ci_poll_start_time = None

    def _no_ci_confirmed(self, state: TaskState) -> bool:
        """Check whether the no-CI fast path may be trusted yet.

        GitHub can take a moment to register checks right after a push, so an
        empty check list on the first poll is not proof that no CI is configured.
        Only trust it once the poll timer has been running for at least
        NO_CI_MIN_ELAPSED seconds or at least NO_CI_MIN_POLLS polls have run.

        Args:
            state: Current task state (uses ci_poll_start_time as the timer).

        Returns:
            True if the no-CI fast path is safe to take, False to keep waiting.
        """
        if state.ci_poll_start_time is None:
            return False
        from datetime import datetime

        elapsed = (datetime.now() - state.ci_poll_start_time).total_seconds()
        polls = int(elapsed // self.CI_POLL_INTERVAL) + 1
        return polls >= self.NO_CI_MIN_POLLS or elapsed >= self.NO_CI_MIN_ELAPSED

    def _ci_timeout_action(self, state: TaskState, reason: str) -> int | None:
        """Decide what to do when CI polling times out.

        Merging a PR whose CI never completed is unsafe, so by default we block
        (error out) and let a human intervene. Admin runs (--admin) force-advance
        to the review stage, treating the timeout as a policy override.

        Returns 1 to block the run, or None to keep the loop going after advancing.
        """
        self._clear_ci_poll_timer(state)
        if state.options.admin_merge:
            console.warning(f"{reason} - advancing anyway (--admin override)")
            state.workflow_stage = "waiting_reviews"
            self.state_manager.save_state(state)
            return None
        console.error(f"{reason} - blocking (re-run with --admin to advance anyway)")
        state.status = "blocked"
        self.state_manager.save_state(state)
        return 1

    def handle_waiting_ci_stage(self, state: TaskState) -> int | None:
        """Handle waiting for CI - poll CI status."""
        if state.current_pr is None:
            self._clear_ci_poll_timer(state)
            state.workflow_stage = "waiting_reviews"
            self.state_manager.save_state(state)
            return None

        console.info(f"Checking CI status for PR #{state.current_pr}...")

        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)

            # Check if PR was already merged (e.g., manually)
            if pr_status.state == "MERGED":
                console.success(
                    f"PR #{state.current_pr} was already merged - skipping to next task"
                )
                self._clear_ci_poll_timer(state)
                state.workflow_stage = "merged"
                self.state_manager.save_state(state)
                return None

            # Check if PR was closed without merging
            if pr_status.state == "CLOSED":
                console.warning(f"PR #{state.current_pr} was closed without merging")
                self._clear_ci_poll_timer(state)
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1

            # Get required checks from branch protection (cached per base branch).
            # Fetch failures raise (GitHubError/GitHubTimeoutError) rather than
            # returning an empty list, and the except below treats that as
            # "unknown — keep waiting" instead of "zero required checks".
            # Branch-protection rules don't change during a CI wait, so we only
            # fetch once per base branch to avoid one `gh api` call per poll.
            base_branch = pr_status.base_branch
            if base_branch not in self._required_checks_cache:
                self._required_checks_cache[base_branch] = set(
                    self.github_client.get_required_status_checks(base_branch)
                )
            required_checks = self._required_checks_cache[base_branch]
            # Use _get_check_name to handle both CheckRun (name) and StatusContext (context)
            reported_checks = {
                self._get_check_name(check)
                for check in pr_status.check_details
                if self._get_check_name(check) != "unknown"
            }
            missing_required = required_checks - reported_checks

            # No CI configured: no required checks AND no checks reported AND
            # GitHub hasn't computed a CI state yet (ci_state is None or empty).
            # Only trust this after the poll has run for a minimum time — right
            # after a push GitHub may not have registered any checks yet.
            if (
                not required_checks
                and not pr_status.check_details
                and pr_status.ci_state not in ("SUCCESS", "FAILURE", "ERROR")
            ):
                if not self._no_ci_confirmed(state):
                    if state.ci_poll_start_time is None:
                        from datetime import datetime

                        state.ci_poll_start_time = datetime.now()
                        self.state_manager.save_state(state)
                    console.info(
                        "No CI checks reported yet - waiting to confirm no CI is configured"
                    )
                    console.detail(f"Next check in {self.CI_POLL_INTERVAL}s...")
                    if not interruptible_sleep(self.CI_POLL_INTERVAL):
                        return None
                    return None
                console.info("No CI checks configured - skipping CI wait")
                self._clear_ci_poll_timer(state)
                state.workflow_stage = "waiting_reviews"
                self.state_manager.save_state(state)
                return None

            # If required checks haven't reported yet, keep waiting (with timeout)
            if missing_required:
                if self._is_ci_poll_timed_out(state):
                    return self._ci_timeout_action(
                        state,
                        f"CI polling timed out after {self.CI_POLL_TIMEOUT}s - "
                        f"required checks never reported: {', '.join(missing_required)}",
                    )
                console.info(f"Waiting for required checks: {', '.join(missing_required)}")
                console.detail(f"Next check in {self.CI_POLL_INTERVAL}s...")
                if not interruptible_sleep(self.CI_POLL_INTERVAL):
                    return None
                return None

            # Check for merge conflicts
            if pr_status.mergeable == "CONFLICTING":
                console.warning("PR has merge conflicts - needs manual resolution")
                self._clear_ci_poll_timer(state)
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1  # Exit with error

            if pr_status.ci_state == "SUCCESS":
                console.success(
                    f"CI passed! ({pr_status.checks_passed} passed, "
                    f"{pr_status.checks_skipped} skipped)"
                )
                self._clear_ci_poll_timer(state)
                # Emit ci.passed webhook
                self._emit_ci_event(
                    event_type="ci.passed",
                    pr_number=state.current_pr,
                    branch=self._get_current_branch() or "",
                )
                # Wait for GitHub to publish reviews before checking
                console.detail(f"Waiting {self.REVIEW_DELAY}s for reviews to be published...")
                if not interruptible_sleep(self.REVIEW_DELAY):
                    return None
                state.workflow_stage = "waiting_reviews"
                self.state_manager.save_state(state)
                return None
            elif pr_status.ci_state in ("FAILURE", "ERROR"):
                # Wait for ALL checks to complete before handling failure (with timeout)
                if pr_status.checks_pending > 0:
                    if self._is_ci_poll_timed_out(state):
                        console.warning(
                            f"CI polling timed out after {self.CI_POLL_TIMEOUT}s - "
                            f"treating incomplete CI as failure"
                        )
                    else:
                        console.warning(
                            f"CI has failures but {pr_status.checks_pending} checks still pending..."
                        )
                        console.detail("Waiting for all checks to complete...")
                        if not interruptible_sleep(self.CI_POLL_INTERVAL):
                            return None
                        return None  # Retry on next cycle

                self._clear_ci_poll_timer(state)
                console.warning(
                    f"CI failed: {pr_status.checks_failed} failed, {pr_status.checks_passed} passed"
                )
                # Collect failed check names for webhook
                failed_checks = []
                for check in pr_status.check_details:
                    conclusion = (check.get("conclusion") or "").upper()
                    if conclusion in ("FAILURE", "ERROR"):
                        check_name = self._get_check_name(check)
                        console.detail(f"  ✗ {check_name}: {conclusion}")
                        failed_checks.append(check_name)
                # Emit ci.failed webhook
                self._emit_ci_event(
                    event_type="ci.failed",
                    pr_number=state.current_pr,
                    branch=self._get_current_branch() or "",
                    failure_reason=f"Failed checks: {', '.join(failed_checks)}"
                    if failed_checks
                    else None,
                )
                state.workflow_stage = "ci_failed"
                self.state_manager.save_state(state)
                return None
            else:
                # CI still pending - check timeout
                if self._is_ci_poll_timed_out(state):
                    return self._ci_timeout_action(
                        state,
                        f"CI polling timed out after {self.CI_POLL_TIMEOUT}s with "
                        f"{pr_status.checks_pending} pending checks",
                    )

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
            # Check timeout even on errors
            if self._is_ci_poll_timed_out(state):
                return self._ci_timeout_action(
                    state,
                    f"CI polling timed out after {self.CI_POLL_TIMEOUT}s while errors "
                    f"kept interrupting status checks",
                )
            console.detail("Will retry on next cycle...")
            # Stay in waiting_ci and retry - do NOT fall through to merge
            if not interruptible_sleep(self.CI_POLL_INTERVAL):
                return None
            return None
