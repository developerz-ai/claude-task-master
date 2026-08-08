"""Local git branch helpers: name validation, inspection, safe post-merge deletion.

Two things live here, both about a branch as a *local* object:

1. **Name validation** — mirrors the constraints of `git check-ref-format --branch`
   closely enough to reject names git itself would refuse, so a bad `--branch` value
   fails fast at the CLI rather than deep inside a work session.
2. **The branch-cleanup policy** (:func:`delete_merged_branch`) — the single decision
   point for "may this local branch be deleted now that its PR merged?", used by both
   ``claudetm merge-pr`` (``cli_commands.merge_finalize``) and the orchestrator's
   merged stage (``core.stages.merge_stage``).

The policy sits in ``core/`` rather than in the CLI module that first grew it because
the entry layers (``cli_commands``/``api``/``mcp``) delegate *into* core, never the
reverse: with it in ``cli_commands`` the orchestrator had to import upward through a
function-local import to dodge the cycle, which hid the inverted dependency instead
of removing it — and made a CLI-layer rename able to break the orchestrator.
"""

from __future__ import annotations

import subprocess

from . import console

# Characters git forbids anywhere in a ref component, plus whitespace.
_FORBIDDEN = set(" \t\n\r~^:?*[\\")


def is_valid_branch_name(name: str) -> bool:
    """Return True if `name` is a syntactically valid git branch name.

    Rejects the cases git's ref-format check rejects: empty, leading '-', a component
    starting with '.', '..', '@{', trailing '/' or '.lock', a bare '@', consecutive
    slashes, control characters, and the forbidden character set above.
    """
    if not name or name == "@":
        return False
    if name.startswith("-") or name.startswith("/") or name.endswith("/"):
        return False
    if name.endswith("."):
        return False
    if ".." in name or "@{" in name or "//" in name:
        return False
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        return False
    if any(ch in _FORBIDDEN for ch in name):
        return False
    # Every slash-separated component: non-empty, not starting with a dot (e.g. `foo/.bar`),
    # and not ending in `.lock` (git reserves that suffix even on nested components).
    return all(
        comp and not comp.startswith(".") and not comp.endswith(".lock") for comp in name.split("/")
    )


# --------------------------------------------------------------------------- #
# Running git
# --------------------------------------------------------------------------- #


def run_git(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str] | None:
    """Run a git command, returning None when it could not run at all."""
    try:
        return subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def git_failure(result: subprocess.CompletedProcess[str] | None) -> str:
    """Human-readable reason from a failed git command."""
    if result is None:
        return "git could not be run"
    return (result.stderr or result.stdout or "").strip() or f"git exited {result.returncode}"


# --------------------------------------------------------------------------- #
# Local branch inspection
# --------------------------------------------------------------------------- #


def current_branch() -> str | None:
    """The checked-out branch name, or None on a detached HEAD/unreadable repo."""
    result = run_git("branch", "--show-current", timeout=15)
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def local_branch_exists(branch: str) -> bool:
    """Whether ``refs/heads/<branch>`` exists locally."""
    result = run_git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", timeout=15)
    return result is not None and result.returncode == 0


def _is_fully_published(branch: str) -> bool:
    """True when the local branch tip is already on its remote-tracking ref.

    ``git branch -d`` refuses a squash-merged branch — the squash commit is not
    an ancestor of the branch — which would make cleanup a no-op for this
    repo's own merge strategy. This is the narrow question that makes forcing
    safe *after a verified merge*: is there anything on the local branch that
    was never pushed? If the remote-tracking ref contains the local tip, no
    work can be lost. Anything unreadable answers False, and the branch stays.
    """
    remote_ref = f"refs/remotes/origin/{branch}"
    exists = run_git("rev-parse", "--verify", "--quiet", remote_ref, timeout=15)
    if exists is None or exists.returncode != 0:
        return False
    ahead = run_git("rev-list", "--count", f"origin/{branch}..{branch}", timeout=30)
    if ahead is None or ahead.returncode != 0:
        return False
    count = ahead.stdout.strip()
    return count.isdigit() and int(count) == 0


# --------------------------------------------------------------------------- #
# The cleanup policy
# --------------------------------------------------------------------------- #


def delete_merged_branch(head_branch: str | None, base_branch: str, pr_number: int) -> None:
    """Delete the merged PR's local head branch, if it is safe to do so.

    The branch deleted is the one GitHub names as the PR's head — never
    "whatever we happen to be checked out on" (issue #153, where cleanup
    destroyed an unrelated *open* PR's branch) — and only after the caller has
    confirmed the merge actually landed.

    Every refusal here is a no-op with an explanation, never an error: the
    branch is a local convenience, and keeping one too many costs nothing next
    to deleting one that still holds work.

    Args:
        head_branch: The merged PR's head branch (from GitHub). None/empty means
            it could not be identified, and nothing is deleted.
        base_branch: The PR's base branch, which is never deleted.
        pr_number: PR number, for messages.
    """
    if not head_branch:
        console.warning(
            f"Could not identify the head branch of PR #{pr_number} — leaving local branches alone"
        )
        return

    if head_branch == base_branch:
        console.warning(f"Refusing to delete base branch {base_branch}")
        return

    if not local_branch_exists(head_branch):
        console.detail(f"No local branch {head_branch} — nothing to delete")
        return

    if current_branch() == head_branch:
        console.warning(f"Still on {head_branch} — skipping local branch cleanup")
        return

    result = run_git("branch", "-d", head_branch, timeout=15)
    if result is not None and result.returncode == 0:
        console.success(f"Deleted local branch {head_branch}")
        return

    reason = git_failure(result)
    if _is_fully_published(head_branch):
        forced = run_git("branch", "-D", head_branch, timeout=15)
        if forced is not None and forced.returncode == 0:
            console.success(
                f"Deleted local branch {head_branch} "
                f"(squash-merged; every commit was already pushed)"
            )
            return
        reason = git_failure(forced)

    console.warning(f"Kept local branch {head_branch}: {reason}")
    console.detail(f"Delete it yourself once you are sure: git branch -D {head_branch}")
