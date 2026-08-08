"""Merge PR command - Wait for CI, fix failures, handle comments, and merge."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from ..core import console
from ..core.agent import AgentWrapper, ModelType
from ..core.credentials import CredentialManager
from ..core.pr_context import PRContextManager
from ..core.state import StateManager
from .ci_helpers import (
    CI_POLL_INTERVAL,
    CI_START_WAIT,
    REVIEW_COMMENTS_GRACE,
    GitHubCITimeoutError,
    wait_for_ci_complete,
)
from .fix_session import pending_changes_summary, run_fix_session
from .merge_finalize import (
    checkout_and_pull,
    delete_merged_branch,
    merge_failure_hint,
    verify_merged,
)
from .pr_resolution import (
    DEFAULT_BRANCHES,
    parse_pr_input,
    resolve_pr_number,
    validate_not_default_branch,
)

if TYPE_CHECKING:
    from ..github import GitHubClient, PRStatus

# Re-exported for callers/tests that reach for them through this module.
__all__ = ["DEFAULT_BRANCHES", "merge_pr", "parse_pr_input", "register_fix_pr_command"]


def _wait_ci(
    github_client: GitHubClient,
    pr_number: int,
    admin: bool,
    state_manager: StateManager,
) -> PRStatus:
    """Wait for CI to complete, treating a timeout as a merge blocker unless --admin.

    Args:
        github_client: GitHub client for API calls.
        pr_number: PR number to check.
        admin: Whether --admin was passed (timeout only warns and continues).
        state_manager: State manager used to release the session lock on failure.

    Returns:
        Final PRStatus after all checks complete.

    Raises:
        typer.Exit: If CI times out and --admin was not passed.
    """
    try:
        return wait_for_ci_complete(github_client, pr_number, raise_on_timeout=True)
    except GitHubCITimeoutError:
        if admin:
            console.warning(f"CI timed out on PR #{pr_number}, but continuing due to --admin.")
            # Fresh status so the caller can keep evaluating the current state.
            return github_client.get_pr_status(pr_number)
        console.error(f"CI timed out on PR #{pr_number}.")
        console.info("Re-run the command to keep waiting, or use --admin to merge anyway.")
        state_manager.release_session_lock()
        raise typer.Exit(1) from None


def _merge_and_verify(
    github_client: GitHubClient,
    pr_number: int,
    status: PRStatus,
    admin: bool,
    state_manager: StateManager,
) -> None:
    """Merge the PR, confirm it against GitHub, then clean up its head branch.

    Nothing local is touched until GitHub reports the PR merged: ``gh pr merge``
    can fail outright, and ``--auto`` can succeed while only *scheduling* a merge
    a branch policy then blocks. Both used to read as success (#152), and the
    cleanup that followed deleted the wrong branch (#153).

    Args:
        github_client: GitHub client for API calls.
        pr_number: PR number to merge.
        status: Latest known PR status (used as a fallback for branch names).
        admin: Whether to pass ``--admin`` to override base-branch policy.
        state_manager: State manager, so the session lock is released on exit.

    Raises:
        typer.Exit: 1 if the merge failed or could not be confirmed.
    """
    console.info(f"Merging PR #{pr_number}...")
    try:
        github_client.merge_pr(pr_number, admin=admin)
    except Exception as e:
        console.error(f"Merge failed: {e}")
        hint = merge_failure_hint(str(e), admin, pr_number)
        if hint:
            console.info(hint)
        console.info(f"PR #{pr_number} was left untouched; no branch was deleted.")
        state_manager.release_session_lock()
        raise typer.Exit(1) from None

    verification = verify_merged(github_client, pr_number)
    if not verification.merged:
        console.error(f"PR #{pr_number} was NOT merged: {verification.detail}")
        hint = merge_failure_hint(
            f"{verification.detail} {verification.state or ''}", admin, pr_number
        )
        if hint is None and not admin and verification.state == "OPEN":
            # Still open right after a merge that reported no error is almost
            # always a policy block; --admin is the documented remedy here.
            console.info(
                f"If the base branch requires an approving review, re-run with --admin: "
                f"claudetm merge-pr {pr_number} --admin"
            )
        elif hint:
            console.info(hint)
        console.info("No branch was deleted — the local branch still holds the PR's work.")
        state_manager.release_session_lock()
        raise typer.Exit(1) from None

    console.success(f"PR #{pr_number} merged successfully!")

    base_branch = verification.base_branch or getattr(status, "base_branch", None) or "main"
    if not isinstance(base_branch, str):
        base_branch = "main"
    head_branch = verification.head_branch
    if not isinstance(head_branch, str):
        head_branch = None

    console.info(f"Checking out to {base_branch}...")
    if not checkout_and_pull(base_branch):
        console.warning(f"Skipping local branch cleanup — could not switch to {base_branch}")
        return
    console.success(f"Switched to {base_branch}")
    delete_merged_branch(head_branch, base_branch, pr_number)


def merge_pr(
    pr: str | None = typer.Argument(
        None, help="PR number or URL. If not provided, uses current branch's PR."
    ),
    max_iterations: int = typer.Option(
        30, "--max-iterations", "-m", help="Maximum fix iterations before giving up."
    ),
    no_merge: bool = typer.Option(
        False, "--no-merge", help="Don't merge after fixing, just make it ready."
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Use 'gh pr merge --admin' to override base-branch policy when merging.",
    ),
    create_pr: bool = typer.Option(
        False,
        "--create-pr",
        help="If the current branch has no PR yet, push it and open one before merging.",
    ),
) -> None:
    """Monitor a PR, fix CI failures and review comments, then merge.

    Waits for CI checks, fixes any failures using Claude, addresses review
    comments, resolves merge conflicts, and merges the PR. Loops until
    everything is green. After a *verified* merge it switches back to the base
    branch and deletes the merged PR's head branch (only when nothing local
    would be lost).

    Examples:
        claudetm merge-pr              # Merge PR for current branch
        claudetm merge-pr 52           # Merge PR #52
        claudetm merge-pr https://github.com/owner/repo/pull/52
        claudetm merge-pr 52 -m 5      # Max 5 fix iterations
        claudetm merge-pr 52 --no-merge # Fix but don't merge
        claudetm merge-pr 52 --admin   # Force-merge past base-branch policy
        claudetm merge-pr --create-pr  # Open a PR for this branch, then merge it
    """
    # Lazy import to avoid circular imports
    from ..github import GitHubClient

    # Validate not on default branch (when no explicit PR given)
    if pr is None:
        validate_not_default_branch()

    try:
        # Initialize GitHub client
        github_client = GitHubClient()

        # Which PR are we operating on? (explicit, current branch, or a new one)
        pr_number = resolve_pr_number(github_client, pr, create_pr=create_pr)

        # Initialize credentials and agent
        cred_manager = CredentialManager()
        access_token = cred_manager.get_valid_token()

        # Initialize state manager (uses default .claude-task-master directory)
        working_dir = Path.cwd()
        state_manager = StateManager()

        # Check for concurrent sessions before proceeding
        if state_manager.is_session_active():
            console.error("Another claudetm session is active.")
            console.info("Wait for it to complete or use 'claudetm clean -f' to force cleanup.")
            raise typer.Exit(1)

        # Acquire session lock
        if not state_manager.acquire_session_lock():
            console.error("Could not acquire session lock.")
            raise typer.Exit(1)

        state_manager.state_dir.mkdir(parents=True, exist_ok=True)

        # Initialize agent
        agent = AgentWrapper(
            access_token=access_token,
            model=ModelType.OPUS,
            working_dir=str(working_dir),
        )

        # Initialize PR context manager
        pr_context = PRContextManager(state_manager, github_client)

        console.info(f"Starting merge-pr loop for PR #{pr_number}")
        console.info(f"Max iterations: {max_iterations}")
        console.info("-" * 40)

        review_grace_done = False

        for iteration in range(1, max_iterations + 1):
            console.info(f"Iteration {iteration}/{max_iterations}")

            # Wait for all CI checks to complete
            status = _wait_ci(github_client, pr_number, admin, state_manager)

            # Determine what needs fixing
            ci_failed = status.ci_state in ("FAILURE", "ERROR")

            # Review bots (CodeRabbit) post their comments a little *after* CI completes rather than
            # as a blocking status check. The first time CI comes back green, give them a grace
            # window to land, then loop to re-poll — otherwise we'd trust a premature "no comments"
            # verdict and merge ahead of the review.
            if not ci_failed and not review_grace_done:
                review_grace_done = True
                console.info(
                    f"Waiting {REVIEW_COMMENTS_GRACE}s for review bots "
                    "(CodeRabbit) to post comments..."
                )
                time.sleep(REVIEW_COMMENTS_GRACE)
                continue
            has_comments = status.unresolved_threads > 0
            has_conflicts = status.mergeable == "CONFLICTING"

            # Show status
            if ci_failed:
                console.error(f"CI: {status.ci_state} ({status.checks_failed} failed)")
            else:
                console.success(f"CI: PASSED ({status.checks_passed} passed)")

            if has_comments:
                console.warning(f"Comments: {status.unresolved_threads} unresolved")

            if has_conflicts:
                console.error("Conflicts: merge conflicts detected")

            # Nothing needs fixing - ready to merge
            if not ci_failed and not has_comments and not has_conflicts:
                break

            # Run agent to fix issues
            agent_ran = run_fix_session(
                agent,
                github_client,
                state_manager,
                pr_context,
                pr_number,
                ci_failed=ci_failed,
                comment_count=status.unresolved_threads,
                has_conflicts=has_conflicts,
            )

            if not agent_ran and not ci_failed:
                # No actionable work and CI passed - unresolved threads need manual review
                console.warning("Exiting: unresolved threads need manual review.")
                state_manager.release_session_lock()
                raise typer.Exit(1)

            if agent_ran:
                # A fresh push means review bots will re-review, so the grace
                # window must run again before trusting a "no comments" verdict.
                review_grace_done = False

            # Wait for CI to start after push
            console.info(f"Waiting {CI_START_WAIT}s for CI to start...")
            time.sleep(CI_START_WAIT)
        else:
            # for-loop exhausted without break = max iterations used up
            # Do one final CI check - the last fix may have resolved everything
            console.info("Max iterations reached - checking final CI status...")
            status = _wait_ci(github_client, pr_number, admin, state_manager)
            ci_failed = status.ci_state in ("FAILURE", "ERROR")
            has_comments = status.unresolved_threads > 0
            has_conflicts = status.mergeable == "CONFLICTING"

            if ci_failed or has_comments or has_conflicts:
                console.error(f"Max iterations ({max_iterations}) reached with issues remaining.")
                console.info("Check the PR manually for remaining issues.")
                state_manager.release_session_lock()
                raise typer.Exit(1)

        # All done - CI passed and comments resolved
        console.success("CI passed and all comments resolved!")

        if no_merge:
            console.success(f"PR #{pr_number} is ready to merge (--no-merge specified)")
            state_manager.release_session_lock()
            raise typer.Exit(0)

        # Wait for mergeable status if UNKNOWN or None (GitHub needs time to compute)
        merge_attempts = 0
        max_merge_attempts = 6  # 60 seconds total
        while (
            status.mergeable == "UNKNOWN" or status.mergeable is None
        ) and merge_attempts < max_merge_attempts:
            merge_attempts += 1
            console.info(f"Waiting for mergeable status... ({merge_attempts}/{max_merge_attempts})")
            time.sleep(CI_POLL_INTERVAL)
            status = github_client.get_pr_status(pr_number)

        # Merge the PR
        if status.mergeable == "MERGEABLE":
            # `gh pr merge` checks branches out, so a dirty tree aborts it with a
            # raw git error after everything has been reported ready.
            pending = pending_changes_summary()
            if pending:
                console.error(
                    f"Refusing to merge PR #{pr_number}: the working tree has uncommitted "
                    "changes, and merging checks branches out"
                )
                for line in pending.splitlines():
                    console.detail(f"  {line}")
                console.detail("Commit, stash or discard them, then re-run.")
                state_manager.release_session_lock()
                raise typer.Exit(1)

            _merge_and_verify(github_client, pr_number, status, admin, state_manager)
        elif status.mergeable == "CONFLICTING":
            console.warning(f"PR #{pr_number} has merge conflicts - manual resolution required")
            state_manager.release_session_lock()
            raise typer.Exit(1)
        else:
            console.warning(f"PR #{pr_number} mergeable status: {status.mergeable}")
            console.info("You can merge manually.")
            state_manager.release_session_lock()
            raise typer.Exit(1)

        state_manager.release_session_lock()
        raise typer.Exit(0)

    except KeyboardInterrupt:
        console.warning("Interrupted by user")
        # Release lock if state_manager was initialized
        try:
            state_manager.release_session_lock()
        except NameError:
            pass  # state_manager wasn't created yet
        raise typer.Exit(2) from None
    except typer.Exit:
        # Re-raise Exit exceptions without modification
        raise
    except Exception as e:
        console.error(f"Error: {e}")
        # Release lock if state_manager was initialized
        try:
            state_manager.release_session_lock()
        except NameError:
            pass  # state_manager wasn't created yet
        raise typer.Exit(1) from None


def register_fix_pr_command(app: typer.Typer) -> None:
    """Register merge-pr command (and fix-pr alias) with the Typer app."""
    app.command(name="merge-pr")(merge_pr)
    app.command(name="fix-pr", hidden=True)(merge_pr)  # backwards compat alias
