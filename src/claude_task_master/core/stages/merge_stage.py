"""MergeStageMixin — merge readiness, merge execution, and post-merge cleanup."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from .. import console
from ..git_branch import delete_merged_branch
from ..shutdown import interruptible_sleep
from .merge_cleanup import _MergeCleanup

if TYPE_CHECKING:
    from ...github.client_pr_models import PRStatus
    from ..state import TaskState

#: Sentinel returned by :meth:`_MergeStage._handle_stale_branch` when the branch
#: is current and the merge should proceed. ``None`` already means "continue the
#: loop", so it cannot double as "not stale".
_NOT_STALE = object()


class _MergeStage(_MergeCleanup):
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

    def _handle_requested_changes(self, state: TaskState, pr_status: PRStatus) -> int | None:
        """Refuse to auto-merge a PR a reviewer has requested changes on.

        The real auto-merge gate is "CI green + no unresolved review threads" —
        it has never included an approval, and it must not start: this repo's own
        ``main`` requires one approving review that no unattended run can obtain,
        which is exactly why ``--admin`` exists. ``CHANGES_REQUESTED`` is the one
        review state that is different: a human actively pushed back, so it only
        fires when someone acted, and merging over it is wrong.

        ``--admin`` deliberately does *not* override this. ``--admin`` is passed
        on every run here to get past branch protection, so honouring it would
        delete the gate. The condition lives on GitHub, not in the working tree,
        so a human clears it by dismissing the review or approving — after which
        the next cycle proceeds on its own (unlike a local, deterministic block,
        which ``resume --force`` could never clear).

        ``APPROVED`` / ``REVIEW_REQUIRED`` / no decision at all behave exactly as
        before, as does an unreadable decision: the field degrades to ``None``
        rather than wedging a merge, matching ``get_pr_behind_by``.

        **A review bot is not "a human actively pushed back".** ``reviewDecision``
        reports CHANGES_REQUESTED identically whether a person or a GitHub App
        submitted it, and reading only that field made this gate permanent for
        the bot case: claudetm answers a bot's comments and resolves its threads
        (``addressing_reviews``), but no bot comes back to dismiss its own review
        afterwards, so a green, fully-addressed PR blocked forever — three did in
        one night, two of them on a CodeRabbit review whose body was a *quota
        notice*, the same condition already discounted on the CI axis
        (:mod:`~...github.check_tolerance`). Every reviewer being a bot therefore
        discounts the decision, logged like a tolerated check. One human among
        them still blocks: that is the case the gate was written for.

        Not knowing who requested changes is not the same as nobody having: an
        empty reviewer list (older GitHub Enterprise, a partial response) falls
        back to blocking. This half fails **closed** on purpose, unlike the
        decision field itself — the cost of a wrong block here is a resume, the
        cost of a wrong merge is an unreviewed change on main.

        Args:
            state: Current task state.
            pr_status: Freshly fetched status for the PR.

        Returns:
            1 if the run was blocked, None to continue toward the merge.
        """
        if not state.options.auto_merge:
            return None
        decision = pr_status.review_decision
        if not isinstance(decision, str) or decision.upper() != "CHANGES_REQUESTED":
            return None

        reviewers = list(pr_status.changes_requested_by)
        bots = set(pr_status.changes_requested_bots)
        humans = [name for name in reviewers if name not in bots]
        if reviewers and not humans:
            console.detail(
                f"~ CHANGES_REQUESTED from {', '.join(reviewers)} ignored — "
                "a review bot is not a human pushing back, and its comments were "
                "addressed and resolved before this stage"
            )
            return None

        console.error(
            f"PR #{state.current_pr} has changes requested by "
            f"{', '.join(humans) if humans else 'a reviewer'} - "
            "refusing to auto-merge over an active review"
        )
        console.detail(
            "Address the review and have the reviewer approve, or dismiss the "
            "review on GitHub, then: claudetm resume"
        )
        state.status = "blocked"
        self.state_manager.save_state(state)
        return 1

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

        # A reviewer pressing "Request changes" is the one review state that must
        # stop an auto-merge. Checked before the sync below so a PR that cannot
        # merge does not first spend an agent session and a CI round chasing its
        # base.
        requested_changes = self._handle_requested_changes(state, pr_status)
        if requested_changes is not None:
            return requested_changes

        # Mergeable and reviewed — but is it merging the *current* base? A PR that
        # went green against a base that has since moved can still break main.
        stale = self._handle_stale_branch(state, pr_status)
        if stale is not _NOT_STALE:
            return cast("int | None", stale)

        if state.options.auto_merge:
            # `gh pr merge` checks branches out, so a dirty tree aborts it with a
            # raw git error ("Your local changes would be overwritten by
            # checkout") after the PR has already been reported ready. The
            # orchestrator must not commit unreviewed leftovers into a PR that is
            # one call away from landing — but it must not dead-end on them
            # either (the condition is local and deterministic, so a blocked run
            # re-blocks on `resume --force` forever). An agent judges them:
            # see _MergeCleanup.
            # Only a *definite* dirty tree diverts: an unreadable repo is left to
            # `gh` rather than stalling every merge behind a failed probe.
            pending = self._uncommitted_summary(max_lines=20)
            if pending:
                return self._handle_dirty_before_merge(
                    state, pr_number, pending, pr_status.base_branch or "main"
                )

            console.info(f"Merging PR #{pr_number}...")
            try:
                self.github_client.merge_pr(pr_number, admin=state.options.admin_merge)
            except Exception as e:
                # Merge failures split into two kinds that look identical here:
                # transient (GitHub 5xx, rate limit, mergeability recomputing,
                # a check that flipped between the poll and the call) and
                # permanent (branch protection refusing a solo-authored PR
                # without --admin). Retrying costs a few polls and rescues the
                # first kind; the second still blocks, just with the attempt
                # count attached instead of on the first try.
                return self._retry_transient(
                    state,
                    f"merge_pr:{pr_number}",
                    f"Auto-merge failed for PR #{pr_number}: {e}",
                    hint=(
                        "If the base branch policy requires a review, re-run with --admin; "
                        f"otherwise merge PR #{pr_number} manually, then: claudetm resume"
                    ),
                )
            # Confirm the merge actually landed - merge_pr may have enabled
            # auto-merge instead, which only merges once checks pass.
            merged = self._confirm_pr_merged(pr_number)
            if merged:
                console.success(f"PR #{pr_number} merged!")
                self._clear_transient(f"merge_pr:{pr_number}")
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

    def _delete_merged_pr_branch(
        self,
        pr_number: int,
        head_branch: str | None,
        base_branch: str,
        merge_confirmed: bool,
    ) -> None:
        """Clean up the merged PR's local head branch, if that is safe.

        Was "delete whatever branch we happen to be on, with ``git branch -D``"
        — the defect issue #153 reported against the ``merge-pr`` command, where
        it destroyed an *unrelated open PR's* branch. The orchestrator is
        normally sitting on the PR's own branch, which is why this never bit
        here; "normally" is not a safety property, and ``-D`` discards unmerged
        commits with nothing but the reflog to recover them.

        The policy itself is not restated here: it is
        :func:`core.git_branch.delete_merged_branch`, one decision point for both
        callers — this stage and ``claudetm merge-pr`` (try ``git branch -d`` and
        let git refuse; force only when the branch is squash-merged *and* fully
        published; keep it and print git's reason otherwise; refuse the base
        branch; a branch that is not checked out locally is a no-op, never an
        error).

        Args:
            pr_number: The merged PR, for messages.
            head_branch: The PR's head branch, from GitHub. None when it could
                not be identified — nothing is deleted then.
            base_branch: The PR's base branch, which is never deleted.
            merge_confirmed: Whether GitHub reports the PR as MERGED. Deleting
                on anything less is deleting a branch whose work may still be
                the only copy.
        """
        if not merge_confirmed:
            console.detail(
                f"PR #{pr_number} is not confirmed merged - leaving local branches alone"
            )
            return

        delete_merged_branch(head_branch, base_branch, pr_number)

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
            # The branch to clean up is the PR's *head* branch, read from GitHub
            # along with the base — never "whatever we happen to be on" (#153).
            # The same fetch answers whether the PR really merged, which is what
            # licenses deleting anything at all; a failed fetch leaves all three
            # unknown, so nothing is deleted.
            base_branch = "main"
            head_branch: str | None = None
            merge_confirmed = False
            try:
                # Get base branch from PR before clearing
                pr_status = self.github_client.get_pr_status(state.current_pr)
                base_branch = pr_status.base_branch
                head_branch = pr_status.head_branch or None
                merge_confirmed = pr_status.state == "MERGED"
            except Exception:
                pass  # Use default main

            try:
                self.state_manager.clear_pr_context(state.current_pr)
            except Exception:
                pass  # Best effort cleanup

            # Checkout to base branch to avoid conflicts on next task
            console.info(f"Checking out to {base_branch}...")
            if not self._checkout_branch(base_branch):
                # The PR is already merged — the work landed. A checkout that
                # fails here is usually momentary (an index lock, a concurrent
                # git process), so retry rather than stranding a finished merge
                # behind a manual resume. Continuing on the old branch is NOT an
                # option: the next task would commit onto a merged branch.
                return self._retry_transient(
                    state,
                    f"checkout_base:{base_branch}",
                    f"Could not checkout {base_branch} after merging PR #{state.current_pr}",
                    hint=(
                        f"Run: git stash && git checkout {base_branch} && git pull, "
                        "then: claudetm resume"
                    ),
                )

            self._clear_transient(f"checkout_base:{base_branch}")
            console.success(f"Switched to {base_branch}")

            self._delete_merged_pr_branch(
                state.current_pr, head_branch, base_branch, merge_confirmed
            )

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
        state.ci_rerun_attempts = 0
        state.conflict_fix_attempts = 0
        state.branch_sync_attempts = 0
        state.pr_finish_attempts = 0
        state.merge_cleanup_attempts = 0
        state.task_finish_attempts = 0
        state.fix_finish_attempts = 0
        state.in_release_fix = False
        state.ci_poll_start_time = None
        self.state_manager.save_state(state)
