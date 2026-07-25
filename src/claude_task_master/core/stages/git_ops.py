"""GitOpsMixin — git branch/checkout/delete helpers for WorkflowStageHandler."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .. import console
from ..shutdown import interruptible_sleep
from .base import StageHandlerBase

if TYPE_CHECKING:
    from ..state import TaskState


class _GitOps(StageHandlerBase):
    """Mixin: low-level git operations used by the PR workflow stages."""

    @staticmethod
    def _get_check_name(check: dict) -> str:
        """Get check name from either CheckRun or StatusContext.

        CheckRun has 'name' field, StatusContext has 'context' field.
        """
        return str(check.get("name") or check.get("context", "unknown"))

    def _get_pr_head_branch(self, state: TaskState) -> str | None:
        """Resolve the branch a fix session must run on, preferring the PR head ref.

        After a resume the local checkout may be back on the target branch (e.g.
        main), so the current branch is not reliable. Fetches the PR head branch
        and checks it out (without pulling — PR branches must not be pulled over
        local state). Falls back to the current branch on any failure.

        Args:
            state: Current task state.

        Returns:
            Branch name the agent must work on, or None if unknown.
        """
        if state.current_pr is not None:
            try:
                pr_status = self.github_client.get_pr_status(state.current_pr)
                head_branch = pr_status.head_branch
                if head_branch:
                    current = self._get_current_branch()
                    if head_branch != current:
                        try:
                            subprocess.run(
                                ["git", "checkout", head_branch],
                                check=True,
                                capture_output=True,
                                text=True,
                                timeout=30,
                            )
                            console.info(f"Checked out PR branch {head_branch}")
                        except subprocess.CalledProcessError as e:
                            console.warning(
                                f"Could not checkout PR branch {head_branch}: "
                                f"{e.stderr.strip() or e}"
                            )
                            # Checkout failed — the worktree is still on the
                            # previous branch. Report where we ACTUALLY are, not
                            # the intended head: required_branch only reaches the
                            # session via the prompt, so returning head_branch
                            # here would let a push-only fix session commit/push
                            # on the wrong local branch (e.g. straight to main).
                            return self._get_current_branch()
                    return head_branch
            except Exception as e:
                console.warning(f"Could not determine PR head branch: {e}")
        return self._get_current_branch()

    def _project_dir(self) -> str:
        """The working tree the run operates on (the state dir's parent)."""
        return str(self.state_manager.state_dir.parent)

    def _porcelain_status(self) -> str | None:
        """``git status --porcelain`` for the project tree, or None if unreadable.

        The three-way answer matters: callers that must fail *closed* (don't
        push or merge when you can't tell) and callers that must fail *open*
        (don't loop re-running a session over a repo you cannot measure) need to
        distinguish "clean" from "unknown", which a bool cannot express.
        """
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self._project_dir(),
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            return None
        # rstrip only: a leading space is the status column (" M path"), and
        # stripping it misaligns the first line against every other one. A clean
        # tree still yields "" so emptiness checks are unaffected.
        return result.stdout.rstrip()

    def _has_uncommitted_changes(self) -> bool:
        """True when the tree is dirty **or** cannot be read (fail closed).

        Used where acting on a wrong answer is costly — pushing a branch or
        opening a PR from a tree of unknown state.
        """
        status = self._porcelain_status()
        return status is None or bool(status)

    def _uncommitted_summary(self, max_lines: int = 40) -> str:
        """Short pending-changes listing, for injecting into a prompt or log.

        Best-effort context only: an empty string when git cannot be read, so a
        failure here degrades the message rather than the caller.
        """
        status = self._porcelain_status()
        if not status:
            return ""
        lines = status.splitlines()
        if len(lines) > max_lines:
            extra = len(lines) - max_lines
            lines = lines[:max_lines] + [f"... and {extra} more"]
        return "\n".join(lines)

    def _unpushed_commit_count(self, branch: str) -> int | None:
        """Commits on HEAD that ``origin/<branch>`` does not have.

        Measured in the project tree (:meth:`_project_dir`), not the process
        cwd — the answer is meaningless if it comes from a different repository
        than the one the run is working on.

        Returns None when the comparison cannot be made — no upstream yet, a
        failed fetch, a detached HEAD. Callers must treat that as "unknown" and
        never as proof that the branch was pushed.
        """
        cwd = self._project_dir()
        try:
            subprocess.run(
                ["git", "fetch", "origin", branch],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            result = subprocess.run(
                ["git", "rev-list", "--count", f"origin/{branch}..HEAD"],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return int(result.stdout.strip())
        except Exception:
            return None

    def _fix_session_unfinished_reason(self, branch: str | None) -> str | None:
        """Return why a push-only fix session didn't satisfy its contract.

        A CI-fix, review-fix or conflict session promises the same two things:
        commit the work, then push it so CI re-runs against the fix. Neither is
        verified by the agent's own report — an agent that ends its turn waiting
        on a backgrounded check looks like a clean success — so the orchestrator
        checks the repository instead:

        - **uncommitted changes** — the session stopped mid-fix. Beyond being
          wrong, it also breaks the merge: ``gh pr merge`` checks branches out
          and refuses to on a dirty tree.
        - **unpushed commits** — the fix exists locally only. CI would then be
          re-read as green from the *previous* push and the PR merged without
          the fix ever running through it.

        An unknown push state (no upstream, failed fetch) is not treated as a
        violation: the caller would otherwise loop on a repo it cannot measure.

        Args:
            branch: The PR head branch the session was told to work on.

        Returns:
            A short reason string, or None when the session finished properly.
        """
        if self._porcelain_status():
            return "uncommitted changes left behind"
        if branch:
            unpushed = self._unpushed_commit_count(branch)
            if unpushed:
                return f"{unpushed} commit(s) never pushed"
        return None

    def _retry_transient(
        self,
        state: TaskState,
        key: str,
        reason: str,
        hint: str | None = None,
    ) -> int | None:
        """Retry an operation that failed for a reason time may fix, then block.

        claudetm is built to run unattended for hours, so ending a run on the
        first flaky API call — a GitHub 5xx, a rate limit, a branch momentarily
        locked, mergeability still recomputing — is a bug: the operation would
        very likely succeed a minute later, and instead a human has to come back
        and type ``claudetm resume``. Equally, a permanent failure (branch
        protection refusing the merge) must not spin forever, so the budget is
        small and the block still happens, just later and with the failure count
        attached.

        The caller leaves ``workflow_stage`` untouched, so returning None simply
        re-enters the same stage on the next cycle.

        Args:
            state: Current task state.
            key: Identifies the operation being retried (its own budget).
            reason: What failed, shown on every attempt.
            hint: Optional guidance printed only when the budget is spent.

        Returns:
            None to retry on the next cycle, 1 once the budget is spent.
        """
        attempt = self._transient_attempts.get(key, 0) + 1
        self._transient_attempts[key] = attempt

        if attempt > self.MAX_TRANSIENT_RETRIES:
            console.error(f"{reason} — still failing after {attempt - 1} retries, blocking")
            if hint:
                console.detail(hint)
            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1

        delay = min(self.CI_POLL_INTERVAL * attempt, self.TRANSIENT_RETRY_MAX_DELAY)
        console.warning(f"{reason} — retry {attempt}/{self.MAX_TRANSIENT_RETRIES} in {delay}s")
        self.state_manager.save_state(state)
        interruptible_sleep(delay)
        return None

    def _clear_transient(self, key: str) -> None:
        """Forget a transient-retry budget after the operation succeeded."""
        self._transient_attempts.pop(key, None)

    def _handle_unfinished_fix(self, state: TaskState, reason: str, stage: str) -> int | None:
        """Keep an undelivered fix in its own stage instead of advancing on it.

        Advancing would be actively harmful, not merely optimistic: the next
        ``waiting_ci`` poll reads the *previous* push's green CI as the fix's,
        and the PR merges without the fix. So the stage repeats — bounded, since
        a session that cannot deliver twice will not deliver on the third try.

        Args:
            state: Current task state.
            reason: Why the session didn't finish (from
                :meth:`_fix_session_unfinished_reason`).
            stage: The stage to stay in so the session re-runs.

        Returns:
            None to continue the loop in ``stage``, 1 when the budget is spent.
        """
        if state.fix_finish_attempts >= self.MAX_FIX_FINISH_ATTEMPTS:
            console.error(
                f"Fix session left work undelivered ({reason}) after "
                f"{state.fix_finish_attempts} attempt(s) — blocking"
            )
            console.detail("Commit and push the pending changes, then: claudetm resume")
            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1

        state.fix_finish_attempts += 1
        state.session_count += 1
        console.warning(
            f"Fix session left work undelivered ({reason}) — re-running it "
            f"(attempt {state.fix_finish_attempts}/{self.MAX_FIX_FINISH_ATTEMPTS})"
        )
        state.workflow_stage = stage  # type: ignore[assignment]
        self.state_manager.save_state(state)
        return None

    @staticmethod
    def _get_current_branch() -> str | None:
        """Get the current git branch name."""
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.stdout.strip() or None
        except Exception:
            return None

    @staticmethod
    def _checkout_branch(branch: str, allow_recovery: bool = True) -> bool:
        """Checkout to a branch with optional recovery from dirty state.

        Args:
            branch: Branch name to checkout.
            allow_recovery: If True, attempts recovery on failure (stash changes).
                The stash ref is logged loudly after a successful stash, and a failed
                stash aborts the checkout instead of losing track of local work.

        Returns:
            True if successful, False otherwise.
        """
        try:
            subprocess.run(
                ["git", "checkout", branch],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            subprocess.run(
                ["git", "pull"],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return True
        except subprocess.CalledProcessError as e:
            if not allow_recovery:
                console.warning(f"Failed to checkout {branch}: {e}")
                return False

            # Try recovery: stash any local changes and retry
            console.info("Checkout failed, attempting recovery...")
            try:
                # Check if there are uncommitted changes
                status = subprocess.run(
                    ["git", "status", "--porcelain"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if status.stdout.strip():
                    console.info("Stashing uncommitted changes...")
                    try:
                        subprocess.run(
                            ["git", "stash", "push", "-m", "claudetm: auto-stash before checkout"],
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                    except subprocess.CalledProcessError as stash_error:
                        console.warning(f"Failed to stash uncommitted changes: {stash_error}")
                        console.warning(f"Aborting checkout of {branch} to avoid losing work")
                        return False
                    stash_ref = subprocess.run(
                        ["git", "stash", "list", "-1", "--format=%gd:%s"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    ).stdout.strip()
                    console.warning(
                        f"Uncommitted changes were STASHED as "
                        f"{stash_ref or 'stash@{0}: claudetm: auto-stash before checkout'} — "
                        "run `git stash pop` to restore them"
                    )

                # Retry checkout
                subprocess.run(
                    ["git", "checkout", branch],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                subprocess.run(
                    ["git", "pull"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                console.success("Recovery successful (changes stashed)")
                return True
            except subprocess.CalledProcessError as recovery_error:
                console.warning(f"Failed to checkout {branch} after recovery: {recovery_error}")
                return False

    @staticmethod
    def _delete_local_branch(branch: str) -> None:
        """Delete a local branch (best effort)."""
        try:
            subprocess.run(
                ["git", "branch", "-D", branch],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            console.success(f"Deleted local branch {branch}")
        except subprocess.CalledProcessError as e:
            console.warning(f"Could not delete local branch {branch}: {e.stderr.strip() or e}")
