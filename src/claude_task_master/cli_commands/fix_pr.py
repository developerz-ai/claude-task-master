"""Merge PR command - Wait for CI, fix failures, handle comments, and merge."""

from __future__ import annotations

import re
import time
from pathlib import Path

import typer

from ..core import console
from ..core.agent import AgentWrapper, ModelType
from ..core.credentials import CredentialManager
from ..core.pr_context import PRContextManager
from ..core.state import StateManager
from .ci_helpers import CI_POLL_INTERVAL, CI_START_WAIT, wait_for_ci_complete
from .fix_session import get_current_branch, run_fix_session

DEFAULT_BRANCHES = {"main", "master", "develop", "development"}


def _validate_not_default_branch() -> None:
    """Error if currently on a default branch (main, master, etc.)."""
    branch = get_current_branch()
    if branch and branch in DEFAULT_BRANCHES:
        console.error(f"Cannot run merge-pr from default branch '{branch}'.")
        console.info("Checkout the PR branch first: git checkout <branch>")
        raise typer.Exit(1)


def _parse_pr_input(pr_input: str | None) -> int | None:
    """Parse PR number from input (number or URL).

    Args:
        pr_input: PR number as string, or GitHub PR URL, or None.

    Returns:
        PR number as int, or None if not provided.
    """
    if pr_input is None:
        return None

    # Try as plain number
    if pr_input.isdigit():
        return int(pr_input)

    # Try to extract from URL (e.g., https://github.com/owner/repo/pull/123)
    match = re.search(r"/pull/(\d+)", pr_input)
    if match:
        return int(match.group(1))

    # Try as number with # prefix
    if pr_input.startswith("#") and pr_input[1:].isdigit():
        return int(pr_input[1:])

    return None


def merge_pr(
    pr: str | None = typer.Argument(
        None, help="PR number or URL. If not provided, uses current branch's PR."
    ),
    max_iterations: int = typer.Option(
        10, "--max-iterations", "-m", help="Maximum fix iterations before giving up."
    ),
    no_merge: bool = typer.Option(
        False, "--no-merge", help="Don't merge after fixing, just make it ready."
    ),
) -> None:
    """Monitor a PR, fix CI failures and review comments, then merge.

    Waits for CI checks, fixes any failures using Claude, addresses review
    comments, resolves merge conflicts, and merges the PR. Loops until
    everything is green.

    Examples:
        claudetm merge-pr              # Merge PR for current branch
        claudetm merge-pr 52           # Merge PR #52
        claudetm merge-pr https://github.com/owner/repo/pull/52
        claudetm merge-pr 52 -m 5      # Max 5 fix iterations
        claudetm merge-pr 52 --no-merge # Fix but don't merge
    """
    # Lazy import to avoid circular imports
    from ..github import GitHubClient

    # Validate not on default branch (when no explicit PR given)
    if pr is None:
        _validate_not_default_branch()

    try:
        # Initialize GitHub client
        github_client = GitHubClient()

        # Get PR number
        pr_number = _parse_pr_input(pr)

        # Fail fast if user provided invalid PR input
        if pr is not None and pr_number is None:
            console.error(f"Invalid PR input '{pr}'.")
            console.info("Use a PR number or PR URL, e.g. claudetm merge-pr 123")
            raise typer.Exit(1)

        if pr_number is None:
            # Try to detect from current branch (only when no PR input provided)
            pr_number = github_client.get_pr_for_current_branch()
            if pr_number is None:
                console.error("No PR found for current branch.")
                console.info("Specify a PR number: claudetm merge-pr 123")
                raise typer.Exit(1)
            console.success(f"Detected PR #{pr_number} for current branch")

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

        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            console.info(f"Iteration {iteration}/{max_iterations}")

            # Wait for all CI checks to complete
            status = wait_for_ci_complete(github_client, pr_number)

            # Determine what needs fixing
            ci_failed = status.ci_state in ("FAILURE", "ERROR")
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

            # If anything needs fixing, download both and run combined session
            if ci_failed or has_comments or has_conflicts:
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

                # Wait for CI to start after push
                console.info(f"Waiting {CI_START_WAIT}s for CI to start...")
                time.sleep(CI_START_WAIT)
                continue

            # All done!
            console.success("✓ CI passed and all comments resolved!")

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
                console.info(
                    f"⏳ Waiting for mergeable status... ({merge_attempts}/{max_merge_attempts})"
                )
                time.sleep(CI_POLL_INTERVAL)
                status = github_client.get_pr_status(pr_number)

            # Check if ready to merge
            if status.mergeable == "MERGEABLE":
                console.info(f"Merging PR #{pr_number}...")
                try:
                    github_client.merge_pr(pr_number)
                    console.success(f"✓ PR #{pr_number} merged successfully!")
                except Exception as e:
                    console.error(f"Merge failed: {e}")
                    console.info("You can merge manually.")
                    state_manager.release_session_lock()
                    raise typer.Exit(1) from None
            elif status.mergeable == "CONFLICTING":
                console.warning(f"PR #{pr_number} has merge conflicts - manual resolution required")
                state_manager.release_session_lock()
                raise typer.Exit(1)
            elif status.mergeable is None:
                console.warning(f"PR #{pr_number} mergeability unknown - please check GitHub")
                console.info("You can merge manually once GitHub computes the status.")
                state_manager.release_session_lock()
                raise typer.Exit(1)
            else:
                console.warning(
                    f"PR #{pr_number} mergeable status: {status.mergeable} after {max_merge_attempts} attempts"
                )
                console.info("You can merge manually.")
                state_manager.release_session_lock()
                raise typer.Exit(1)

            state_manager.release_session_lock()
            raise typer.Exit(0)

        # Max iterations reached
        console.error(f"Max iterations ({max_iterations}) reached without success.")
        console.info("Check the PR manually for remaining issues.")
        state_manager.release_session_lock()
        raise typer.Exit(1)

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
