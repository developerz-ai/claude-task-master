"""MergeStageMixin — merge readiness, merge execution, and post-merge cleanup."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from .. import console
from ..shutdown import interruptible_sleep
from .review_stage import _ReviewStage

if TYPE_CHECKING:
    from ...github.client_pr_models import PRStatus
    from ..state import TaskState

#: Sentinel returned by :meth:`_MergeStage._handle_stale_branch` when the branch
#: is current and the merge should proceed. ``None`` already means "continue the
#: loop", so it cannot double as "not stale".
_NOT_STALE = object()


class _MergeStage(_ReviewStage):
    """Mixin: ready-to-merge, merge execution, post-merge cleanup, task advance."""

    def _merge_status_retry(self, state: TaskState, reason: str) -> int | None:
        """Handle a merge-status check failure with bounded backoff.

        Never falls through to merge: retries with linear backoff (capped at
        60s) and blocks after MAX_MERGE_UNKNOWN_ATTEMPTS consecutive failures.

        Args:
            state: Current task state.
            reason: Human-readable description of the failure.

        Returns:
            1 if blocked, None to retry on the next cycle.
        """
        attempt = self._merge_unknown_attempts.get(state.current_pr or 0, 0)
        if attempt >= self.MAX_MERGE_UNKNOWN_ATTEMPTS:
            console.error(
                f"Merge status unavailable after {attempt} attempts ({reason}) - "
                "blocking, manual intervention required"
            )
            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1
        delay = min(self.CI_POLL_INTERVAL * attempt, 60)
        console.warning(f"{reason} - retry {attempt}/{self.MAX_MERGE_UNKNOWN_ATTEMPTS} in {delay}s")
        if not interruptible_sleep(delay):
            return None
        return None

    def _handle_stale_branch(self, state: TaskState, pr_status: PRStatus) -> int | None | object:
        """Route a PR whose branch is behind its base to the sync agent session.

        Opt-in (``--sync-before-merge``), because a behind-but-clean PR is the
        normal case and merges fine. When enabled: "CI is green" only proves the
        branch passed against the base as it stood when CI ran, so the branch is
        rebased onto the live base, the tests re-run, and CI verifies the combined
        tree before the merge goes through. A PR that actually conflicts takes the
        same session whether or not this is on.

        Args:
            state: Current task state.
            pr_status: Freshly fetched status for the PR.

        Returns:
            :data:`_NOT_STALE` when the branch is current (or the check is
            disabled/exhausted) and the merge should proceed, otherwise the loop
            result to return from the merge stage.
        """
        if not state.options.sync_before_merge or state.current_pr is None:
            return _NOT_STALE

        try:
            raw = self.github_client.get_pr_behind_by(
                state.current_pr, pr_status.base_branch, pr_status.head_branch
            )
        except Exception:
            raw = 0
        # Anything but a real int means the comparison could not be made (the
        # client already swallows API errors into 0). Treat it as "unknown" and
        # fall through to mergeStateStatus rather than wedging the merge — being
        # unable to measure staleness must never stop a green PR from landing.
        behind = raw if isinstance(raw, int) and not isinstance(raw, bool) else 0
        if behind <= 0 and pr_status.merge_state_status != "BEHIND":
            return _NOT_STALE

        if state.branch_sync_attempts >= self.MAX_BRANCH_SYNC_ATTEMPTS:
            # The base is moving faster than this PR can chase it. Merging a
            # slightly-stale-but-green PR beats never merging at all; branch
            # protection, if it requires up-to-date branches, still has the
            # final say.
            console.warning(
                f"PR #{state.current_pr} still behind {pr_status.base_branch} after "
                f"{state.branch_sync_attempts} sync attempts - merging as-is"
            )
            return _NOT_STALE

        console.info(
            f"PR #{state.current_pr} is {behind or 'some'} commits behind "
            f"{pr_status.base_branch} - syncing before merge"
        )
        state.branch_sync_attempts += 1
        state.workflow_stage = "resolving_conflicts"
        self.state_manager.save_state(state)
        return None

    def _confirm_pr_merged(self, pr_number: int) -> bool | None:
        """Poll GitHub to confirm a PR actually merged after merge_pr succeeds.

        merge_pr can enable auto-merge instead of merging immediately, leaving
        the PR open until checks pass, so the success return is not proof of
        merge. Polls get_pr_status up to MERGE_CONFIRM_POLLS times at
        CI_POLL_INTERVAL seconds apart.

        Args:
            pr_number: The PR number to confirm.

        Returns:
            True if merged, False if still open (auto-merge scheduled), None if
            the status could not be fetched.
        """
        for _ in range(self.MERGE_CONFIRM_POLLS):
            try:
                confirm_status = self.github_client.get_pr_status(pr_number)
            except Exception as e:
                console.warning(f"Could not confirm merge of PR #{pr_number}: {e}")
                return None
            if confirm_status.state == "MERGED":
                return True
            if not interruptible_sleep(self.CI_POLL_INTERVAL):
                return False
        return False

    def handle_ready_to_merge_stage(self, state: TaskState) -> int | None:
        """Handle ready to merge - merge the PR if auto_merge enabled."""
        if state.current_pr is None:
            state.workflow_stage = "merged"
            self.state_manager.save_state(state)
            return None

        pr_number = state.current_pr

        # Check PR status before attempting merge
        try:
            pr_status = self.github_client.get_pr_status(pr_number)

            # Check if PR was already merged (e.g., manually)
            if pr_status.state == "MERGED":
                console.success(f"PR #{pr_number} was already merged - skipping to next task")
                self._merge_unknown_attempts.pop(pr_number, None)
                state.workflow_stage = "merged"
                self.state_manager.save_state(state)
                return None

            # Check if PR was closed without merging
            if pr_status.state == "CLOSED":
                console.warning(f"PR #{pr_number} was closed without merging")
                self._merge_unknown_attempts.pop(pr_number, None)
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1

            if pr_status.mergeable == "CONFLICTING":
                console.warning(f"PR #{pr_number} has merge conflicts!")
                self._merge_unknown_attempts.pop(pr_number, None)
                return self._handle_conflicting_pr(state, pr_number)
            elif pr_status.mergeable == "UNKNOWN":
                attempt = self._merge_unknown_attempts.get(pr_number, 0) + 1
                self._merge_unknown_attempts[pr_number] = attempt
                return self._merge_status_retry(
                    state, "Waiting for GitHub to calculate mergeable status"
                )
            # Mergeability resolved - reset the UNKNOWN/error counter
            self._merge_unknown_attempts.pop(pr_number, None)
        except Exception as e:
            attempt = self._merge_unknown_attempts.get(pr_number, 0) + 1
            self._merge_unknown_attempts[pr_number] = attempt
            return self._merge_status_retry(state, f"Error checking mergeable status: {e}")

        # Mergeable and reviewed — but is it merging the *current* base? A PR that
        # went green against a base that has since moved can still break main.
        stale = self._handle_stale_branch(state, pr_status)
        if stale is not _NOT_STALE:
            return cast("int | None", stale)

        if state.options.auto_merge:
            console.info(f"Merging PR #{pr_number}...")
            try:
                self.github_client.merge_pr(pr_number, admin=state.options.admin_merge)
            except Exception as e:
                console.warning(f"Auto-merge failed: {e}")
                console.detail("PR may need manual merge or have merge conflicts")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1
            # Confirm the merge actually landed - merge_pr may have enabled
            # auto-merge instead, which only merges once checks pass.
            merged = self._confirm_pr_merged(pr_number)
            if merged:
                console.success(f"PR #{pr_number} merged!")
                self._merge_unknown_attempts.pop(pr_number, None)
                state.workflow_stage = "merged"
                self.state_manager.save_state(state)
                return None
            if merged is False:
                console.info(
                    f"Auto-merge scheduled for PR #{pr_number} - will complete when checks pass"
                )
            # Keep stage ready_to_merge; the next cycle's get_pr_status sees
            # MERGED and advances via the already-merged check above.
            self.state_manager.save_state(state)
            return None
        else:
            console.info(f"PR #{pr_number} ready to merge (auto_merge disabled)")
            console.detail("Use 'claudetm resume' after manual merge")
            state.status = "paused"
            self.state_manager.save_state(state)
            return 2

    def handle_merged_stage(
        self,
        state: TaskState,
        mark_task_complete_fn: Callable[[str, int], None],
        pr_merged_event_fn: Callable[[TaskState], None] | None = None,
    ) -> int | None:
        """Handle merged state - move to next task.

        Args:
            state: Current task state.
            mark_task_complete_fn: Function to mark task complete in plan.
            pr_merged_event_fn: Optional idempotent callback that emits the pr.merged
                event (gated by state.last_counted_pr_merged in the orchestrator),
                so externally-merged PRs also emit the event.
        """
        if pr_merged_event_fn is not None:
            pr_merged_event_fn(state)

        console.success(f"Task #{state.current_task_index + 1} complete!")

        # Mark task as complete in plan
        plan = self.state_manager.load_plan()
        if plan:
            mark_task_complete_fn(plan, state.current_task_index)

        # Log PR timing if we have timing data
        if state.current_pr is not None and state.pr_start_time is not None:
            from datetime import datetime

            pr_total_seconds = (datetime.now() - state.pr_start_time).total_seconds()
            pr_active_work_seconds = state.pr_active_work_seconds
            ci_wait_seconds = pr_total_seconds - pr_active_work_seconds

            # Log to logger if available
            if hasattr(self, "logger") and self.logger:
                self.logger.log_pr_timing(
                    state.current_pr,
                    pr_total_seconds,
                    pr_active_work_seconds,
                    ci_wait_seconds,
                )

            # Log to console
            console.info(
                f"PR #{state.current_pr} timing - "
                f"Total: {pr_total_seconds / 60:.1f}m, "
                f"Active work: {pr_active_work_seconds / 60:.1f}m, "
                f"CI wait: {ci_wait_seconds / 60:.1f}m"
            )

        # Clear PR context files and checkout to base branch (only if PR was merged)
        if state.current_pr is not None:
            # Capture the PR branch before we switch away so we can delete it
            merged_branch = self._get_current_branch()

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
            if not self._checkout_branch(base_branch):
                # Checkout failed even after recovery - block and require manual intervention
                console.error(f"Could not checkout to {base_branch} after PR merge")
                console.detail("Manual intervention required:")
                console.detail(f"  1. Run: git stash && git checkout {base_branch} && git pull")
                console.detail("  2. Then run: claudetm resume")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1

            console.success(f"Switched to {base_branch}")

            # Delete the merged local branch (best effort, skip if same as base)
            if merged_branch and merged_branch != base_branch:
                self._delete_local_branch(merged_branch)

        # Check if we should run release verification
        # (auto_merge + enable_release + release guide exists)
        release_guide = self.state_manager.load_release_guide()
        if state.options.auto_merge and state.options.enable_release and release_guide:
            # Check if the release guide has actual checks (not just "no verification available")
            if "no release verification available" not in release_guide.lower():
                console.info("Starting release verification...")
                state.workflow_stage = "releasing"
                # Only reset the release-fix counter when the merged PR was NOT a
                # release-fix PR — otherwise the attempt cap becomes unreachable.
                if not state.in_release_fix:
                    state.release_fix_attempts = 0
                self.state_manager.save_state(state)
                return None

        # No release phase — move to next task
        self._advance_to_next_task(state)
        return None

    def _advance_to_next_task(self, state: TaskState) -> None:
        """Move to next task and reset timing/fix-attempt fields."""
        state.current_task_index += 1
        state.current_pr = None
        state.workflow_stage = "working"
        state.task_start_time = None
        state.pr_start_time = None
        state.pr_active_work_seconds = 0.0
        state.release_fix_attempts = 0
        state.release_fix_details = None
        state.ci_fix_attempts = 0
        state.conflict_fix_attempts = 0
        state.branch_sync_attempts = 0
        state.in_release_fix = False
        state.ci_poll_start_time = None
        self.state_manager.save_state(state)
