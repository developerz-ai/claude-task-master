"""Merge execution, verification and safe branch cleanup for ``claudetm merge-pr``.

Two rules govern this module, both paid for in production:

1. **The repository decides whether the merge happened, not the command's own
   report** (issue #152). ``gh pr merge`` exits non-zero on a policy refusal,
   and ``gh pr merge --auto`` exits *zero* while merely scheduling a merge that
   a required-review rule then blocks forever. Both used to end in a clean exit
   and a success-shaped message on a PR that was still OPEN.
2. **Cleanup deletes the merged PR's head branch, never "whatever we were on"**
   (issue #153). ``merge-pr`` accepts a PR number or URL from any checkout, so
   the checked-out branch is frequently someone else's — in the reported case an
   unrelated *open* PR's branch, which was deleted while the merged PR's branch
   was left behind. And it deletes only after a verified merge, with git's own
   safety net, never blind ``-D``.

Rule 1 is this module's own; rule 2 is
:func:`core.git_branch.delete_merged_branch`, shared with the orchestrator's
merged stage and imported from there like every other entry-layer module reaches
into core. Only the *decision to run it* — a merge this command verified —
belongs to the CLI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..core import console
from ..core.git_branch import (
    delete_merged_branch,
    git_failure,
    local_branch_exists,
    run_git,
)
from .ci_helpers import CI_POLL_INTERVAL
from .fix_session import get_current_branch

if TYPE_CHECKING:
    from ..github import GitHubClient

# Bounded confirmation of the merge against GitHub (~60s at CI_POLL_INTERVAL).
MERGE_CONFIRM_POLLS = 6

# Substrings that identify a base-branch policy refusal, which `--admin`
# overrides. Matched case-insensitively against the merge error text.
POLICY_REFUSAL_MARKERS = (
    "base branch policy",
    "protected branch",
    "branch protection",
    "required status check",
    "changes requested",
    "review required",
    "approving review",
    "not authorized",
)

ADMIN_HINT = (
    "The base branch policy refused the merge. Re-run with --admin to override "
    "it (requires admin rights on the repo): claudetm merge-pr {pr} --admin"
)


def _text(value: object) -> str:
    """Return a stripped string, or "" for anything that is not one.

    Deliberately strict: PR fields arrive from JSON (and from mocks in tests),
    and treating a non-string as truthy is how an unverified merge would sneak
    past the confirmation below.
    """
    return value.strip() if isinstance(value, str) else ""


# --------------------------------------------------------------------------- #
# Merge verification
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MergeVerification:
    """Outcome of checking a PR's merge state against GitHub.

    Attributes:
        merged: True only when GitHub reports the PR as merged.
        state: Last observed PR state (``MERGED``/``OPEN``/``CLOSED``), or None
            when the state could never be read.
        head_branch: The PR's head branch, as GitHub reports it. The only
            branch cleanup is ever allowed to delete.
        base_branch: The PR's base branch.
        detail: Why the PR is not merged (empty when it is).
    """

    merged: bool
    state: str | None
    head_branch: str | None
    base_branch: str | None
    detail: str = ""


def verify_merged(
    github_client: GitHubClient,
    pr_number: int,
    polls: int = MERGE_CONFIRM_POLLS,
    interval: int = CI_POLL_INTERVAL,
) -> MergeVerification:
    """Confirm against GitHub that the PR is merged.

    Read errors are transient far more often than they are fatal, so they are
    retried within the same bounded window rather than ending the run on the
    first 502. A state that never becomes MERGED is reported as *not merged*
    with whatever detail is available — never as success, and never as a
    licence to delete anything.

    Args:
        github_client: GitHub client for API calls.
        pr_number: PR number to confirm.
        polls: Maximum status reads before giving up.
        interval: Seconds between reads.

    Returns:
        A MergeVerification describing the confirmed state.
    """
    last_error = ""
    state: str | None = None
    head: str = ""
    base: str = ""
    merge_state: str = ""

    for attempt in range(1, polls + 1):
        try:
            status = github_client.get_pr_status(pr_number)
        except Exception as e:  # transient GitHub/network failure — retry
            last_error = str(e)
            status = None

        if status is not None:
            state = _text(status.state) or state
            head = _text(status.head_branch) or head
            base = _text(status.base_branch) or base
            merge_state = _text(getattr(status, "merge_state_status", "")) or merge_state

            if state == "MERGED" or _text(getattr(status, "merged_at", "")):
                return MergeVerification(True, "MERGED", head or None, base or None)
            if state == "CLOSED":
                return MergeVerification(
                    False,
                    "CLOSED",
                    head or None,
                    base or None,
                    f"PR #{pr_number} is CLOSED without having been merged",
                )

        if attempt < polls:
            time.sleep(interval)

    if state is None:
        reason = last_error or "no response"
        detail = f"could not read the state of PR #{pr_number} ({reason})"
    else:
        detail = f"PR #{pr_number} is still {state} after the merge"
        if merge_state and merge_state != "UNKNOWN":
            detail += f" (merge state: {merge_state})"
    return MergeVerification(False, state, head or None, base or None, detail)


def merge_failure_hint(message: str, admin: bool, pr_number: int) -> str | None:
    """Actionable advice for a refused merge, or None when there is none.

    Args:
        message: The failure text from gh/GitHub.
        admin: Whether ``--admin`` was already used (no point suggesting it).
        pr_number: PR number, for a copy-pasteable command.

    Returns:
        A hint string, or None.
    """
    if admin:
        return None
    lowered = message.lower()
    if any(marker in lowered for marker in POLICY_REFUSAL_MARKERS):
        return ADMIN_HINT.format(pr=pr_number)
    return None


# --------------------------------------------------------------------------- #
# Local branch cleanup
# --------------------------------------------------------------------------- #


def checkout_and_pull(branch: str) -> bool:
    """Checkout a branch and pull latest changes. Returns True on success."""
    result = run_git("checkout", branch, timeout=30)
    if result is None or result.returncode != 0:
        console.warning(f"Could not checkout {branch}: {git_failure(result)}")
        return False
    pull = run_git("pull", timeout=120)
    if pull is None or pull.returncode != 0:
        console.warning(f"Could not pull {branch}: {git_failure(pull)}")
        return False
    return True


# Re-exported: this module is the CLI's merge/cleanup surface, and ``fix_pr`` and
# ``pr_resolution`` reach for the git helpers (and the cleanup policy) through it.
# The implementations live in ``core.git_branch`` — there is exactly one of each.
__all__ = [
    "MERGE_CONFIRM_POLLS",
    "MergeVerification",
    "checkout_and_pull",
    "delete_merged_branch",
    "get_current_branch",
    "git_failure",
    "local_branch_exists",
    "merge_failure_hint",
    "run_git",
    "verify_merged",
]
