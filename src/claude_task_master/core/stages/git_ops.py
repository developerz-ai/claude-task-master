"""GitOpsMixin — git branch/checkout/delete helpers for WorkflowStageHandler."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .. import console
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
                    return head_branch
            except Exception as e:
                console.warning(f"Could not determine PR head branch: {e}")
        return self._get_current_branch()

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
