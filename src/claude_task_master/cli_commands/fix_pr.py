"""Fix PR command - Iteratively fix CI failures and address review comments."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

from ..core import console
from ..core.agent import AgentWrapper, ModelType
from ..core.credentials import CredentialManager
from ..core.pr_context import PRContextManager
from ..core.state import StateManager

if TYPE_CHECKING:
    from ..github import GitHubClient, PRStatus

# Polling intervals
CI_POLL_INTERVAL = 10  # seconds between CI checks (matches orchestrator)
CI_START_WAIT = 30  # seconds to wait for CI to start after push


def _get_current_branch() -> str | None:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


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


def _is_check_pending(check: dict[str, Any]) -> bool:
    """Check if a CI check or status is still pending.

    Handles both CheckRun (GitHub Actions) and StatusContext (external services like CodeRabbit).

    CheckRun states:
        - status: QUEUED, IN_PROGRESS, COMPLETED
        - conclusion: success, failure, etc. (only set when COMPLETED)

    StatusContext states:
        - state: PENDING, EXPECTED, SUCCESS, FAILURE, ERROR
        - Maps to both status and conclusion in our normalized format

    Args:
        check: Normalized check detail dictionary.

    Returns:
        True if the check is still pending, False if complete.
    """
    status = (check.get("status") or "").upper()
    conclusion = check.get("conclusion")

    # StatusContext with PENDING or EXPECTED state is still waiting
    # (These get mapped to both status and conclusion)
    if status in ("PENDING", "EXPECTED"):
        return True

    # CheckRun is pending if not completed or has no conclusion yet
    if status not in ("COMPLETED",) and conclusion is None:
        return True

    return False


def _wait_for_ci_complete(github_client: GitHubClient, pr_number: int) -> PRStatus:
    """Wait for all CI checks to complete.

    Fetches required checks from branch protection and waits for all of them
    to report, even if they haven't started yet (like CodeRabbit).

    Args:
        github_client: GitHub client for API calls.
        pr_number: PR number to check.

    Returns:
        Final PRStatus after all checks complete.
    """
    console.info(f"Waiting for CI checks on PR #{pr_number}...")

    # Get required checks from branch protection (once at start)
    status = github_client.get_pr_status(pr_number)
    required_checks = set(github_client.get_required_status_checks(status.base_branch))

    while True:
        status = github_client.get_pr_status(pr_number)

        # Get reported check names
        reported = {check.get("name", "") for check in status.check_details}

        # Find required checks that haven't reported yet
        missing = required_checks - reported

        # Count pending checks (in progress or not yet complete)
        pending = [
            check.get("name", "unknown")
            for check in status.check_details
            if _is_check_pending(check)
        ]

        # All pending = running checks + missing required checks
        all_waiting = list(missing) + pending

        if not all_waiting:
            # All checks reported - verify no conflicts
            if status.mergeable == "CONFLICTING":
                console.warning("⚠ PR has merge conflicts")
            return status

        # Build status summary
        passed = status.checks_passed
        failed = status.checks_failed
        status_parts = []
        if passed:
            status_parts.append(f"{passed} passed")
        if failed:
            status_parts.append(f"{failed} failed")
        status_summary = f" ({', '.join(status_parts)})" if status_parts else ""

        # Show what we're waiting for
        console.info(
            f"⏳ Waiting for {len(all_waiting)} check(s): "
            f"{', '.join(all_waiting[:3])}{'...' if len(all_waiting) > 3 else ''}"
            f"{status_summary}"
        )

        time.sleep(CI_POLL_INTERVAL)


def _run_fix_session(
    agent: AgentWrapper,
    github_client: GitHubClient,
    state_manager: StateManager,
    pr_context: PRContextManager,
    pr_number: int,
    ci_failed: bool,
    comment_count: int,
    has_conflicts: bool = False,
) -> bool:
    """Run agent session to fix CI failures, comments, and/or merge conflicts.

    Downloads both CI failures and comments (if present) so the agent can
    address everything in one session.

    Args:
        agent: Agent wrapper for running work sessions.
        github_client: GitHub client for API calls.
        state_manager: State manager for persistence.
        pr_context: PR context manager for saving CI logs and comments.
        pr_number: PR number being fixed.
        ci_failed: Whether CI has failed.
        comment_count: Number of unresolved comments.
        has_conflicts: Whether there are merge conflicts.

    Returns:
        True if agent ran, False if nothing actionable was found.
    """
    pr_dir = state_manager.get_pr_dir(pr_number)
    task_sections = []
    has_actionable_work = False

    # Handle merge conflicts
    if has_conflicts:
        console.error("Merge Conflicts - Agent will resolve...")
        task_sections.append("""## Merge Conflicts

This PR has merge conflicts that need to be resolved.

1. Run `git fetch origin` to get latest changes
2. Run `git merge origin/main` (or the base branch)
3. Resolve any conflicts in the affected files
4. Run tests to verify the merge didn't break anything
5. Commit the merge resolution""")
        has_actionable_work = True

    # Always download CI failures if CI failed
    if ci_failed:
        console.error("CI Failed - Downloading failure logs...")
        pr_context.save_ci_failures(pr_number)
        ci_path = f"{pr_dir}/ci/"
        task_sections.append(f"""## CI Failures

**Read the CI failure logs from:** `{ci_path}`

Use Glob to find all .txt files, then Read each one to understand the errors.

**IMPORTANT:** Fix ALL CI failures, even if they seem unrelated to your current work.
Your job is to keep CI green. Pre-existing issues, flaky tests, lint errors - fix them all.

- Read ALL files in the ci/ directory
- Understand ALL error messages (lint, tests, types, etc.)
- Fix everything that's failing - don't skip anything""")
        has_actionable_work = True

    # Always download comments if there are unresolved threads
    saved_comment_count = 0
    if comment_count > 0:
        console.warning(f"{comment_count} unresolved comment(s) - Downloading...")
        saved_comment_count = pr_context.save_pr_comments(pr_number)
        console.detail(f"Saved {saved_comment_count} actionable comment(s) for review")

        if saved_comment_count > 0:
            comments_path = f"{pr_dir}/comments/"
            resolve_json_path = f"{pr_dir}/resolve-comments.json"
            task_sections.append(f"""## Review Comments

**Read the review comments from:** `{comments_path}`

Use Glob to find all .txt files, then Read each one to understand the feedback.

For each comment:
- Make the requested change, OR
- Explain why it's not needed

After addressing comments, create a resolution summary file at: `{resolve_json_path}`

**Resolution file format:**
```json
{{
  "pr": {pr_number},
  "resolutions": [
    {{
      "thread_id": "THREAD_ID_FROM_COMMENT_FILE",
      "action": "fixed|explained|skipped",
      "message": "Brief explanation of what was done"
    }}
  ]
}}
```

Copy the Thread ID from each comment file into the resolution JSON.

**IMPORTANT: DO NOT resolve threads directly using GitHub GraphQL mutations.**
The orchestrator will handle thread resolution automatically after you create the resolution file.""")
            has_actionable_work = True

    # Guard against loops when nothing actionable
    if not has_actionable_work:
        if comment_count > 0 and saved_comment_count == 0:
            console.warning(
                "No actionable comments to address (may be bot status updates or already addressed)."
            )
            console.warning("Unresolved threads may need manual review on GitHub.")
        return False

    # Build combined task description
    task_description = f"""PR #{pr_number} needs fixes.

{chr(10).join(task_sections)}

## Instructions

1. Read ALL relevant files (CI logs and/or comments)
2. Fix ALL issues found
3. Run tests/lint locally to verify everything passes
4. Commit and push the fixes

After fixing everything, end with: TASK COMPLETE"""

    console.info("Running agent to fix all issues...")
    current_branch = _get_current_branch()
    agent.run_work_session(
        task_description=task_description,
        context="",
        model_override=ModelType.OPUS,
        required_branch=current_branch,
    )

    # Post replies to comments using resolution file (if comments were addressed)
    if saved_comment_count > 0:
        pr_context.post_comment_replies(pr_number)

    return True


def fix_pr(
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
    """Fix a PR by iteratively addressing CI failures and review comments.

    Loops until CI is green and all review comments are resolved.

    Examples:
        claudetm fix-pr              # Fix PR for current branch
        claudetm fix-pr 52           # Fix PR #52
        claudetm fix-pr https://github.com/owner/repo/pull/52
        claudetm fix-pr 52 -m 5      # Max 5 fix iterations
        claudetm fix-pr 52 --no-merge
    """
    # Lazy import to avoid circular imports
    from ..github import GitHubClient

    try:
        # Initialize GitHub client
        github_client = GitHubClient()

        # Get PR number
        pr_number = _parse_pr_input(pr)

        # Fail fast if user provided invalid PR input
        if pr is not None and pr_number is None:
            console.error(f"Invalid PR input '{pr}'.")
            console.info("Use a PR number or PR URL, e.g. claudetm fix-pr 123")
            raise typer.Exit(1)

        if pr_number is None:
            # Try to detect from current branch (only when no PR input provided)
            pr_number = github_client.get_pr_for_current_branch()
            if pr_number is None:
                console.error("No PR found for current branch.")
                console.info("Specify a PR number: claudetm fix-pr 123")
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

        console.info(f"Starting fix-pr loop for PR #{pr_number}")
        console.info(f"Max iterations: {max_iterations}")
        console.info("-" * 40)

        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            console.info(f"Iteration {iteration}/{max_iterations}")

            # Wait for all CI checks to complete
            status = _wait_for_ci_complete(github_client, pr_number)

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
                agent_ran = _run_fix_session(
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
    """Register fix-pr command with the Typer app."""
    app.command(name="fix-pr")(fix_pr)
