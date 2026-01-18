"""Fix PR command - Iteratively fix CI failures and address review comments."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console

from ..core.agent import AgentWrapper, ModelType
from ..core.credentials import CredentialManager
from ..core.pr_context import PRContextManager
from ..core.state import StateManager

if TYPE_CHECKING:
    from ..github import GitHubClient, PRStatus

console = Console()

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

    Checks required status checks from branch protection and waits for all
    of them to report, even if they haven't started yet (like CodeRabbit).

    Args:
        github_client: GitHub client for API calls.
        pr_number: PR number to check.

    Returns:
        Final PRStatus after all checks complete.
    """
    console.print(f"[bold]Waiting for CI checks on PR #{pr_number}...[/bold]")

    # Get required checks from branch protection (once)
    status = github_client.get_pr_status(pr_number)
    required_checks = github_client.get_required_status_checks(status.base_branch)
    if required_checks:
        console.print(f"  Required checks: {', '.join(required_checks)}")

    while True:
        status = github_client.get_pr_status(pr_number)

        # Get names of reported checks
        reported_check_names = {check.get("name", "") for check in status.check_details}

        # Find required checks that haven't reported yet
        missing_required = [rc for rc in required_checks if rc not in reported_check_names]

        # Count pending checks (both CheckRun and StatusContext)
        pending = [
            check.get("name", "unknown")
            for check in status.check_details
            if _is_check_pending(check)
        ]

        # Combine missing required checks with pending reported checks
        all_pending = pending + missing_required

        if not all_pending:
            # All checks complete (both reported and required)
            return status

        # Show progress
        if missing_required:
            console.print(
                f"  ⏳ Waiting for {len(all_pending)} check(s): "
                f"{', '.join(all_pending[:3])}{'...' if len(all_pending) > 3 else ''} "
                f"({len(missing_required)} not yet reported)"
            )
        else:
            console.print(
                f"  ⏳ Waiting for {len(pending)} check(s): "
                f"{', '.join(pending[:3])}{'...' if len(pending) > 3 else ''}"
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
) -> bool:
    """Run agent session to fix CI failures and/or address review comments.

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

    Returns:
        True if agent ran, False if nothing actionable was found.
    """
    pr_dir = state_manager.get_pr_dir(pr_number)
    task_sections = []
    has_actionable_work = False

    # Always download CI failures if CI failed
    if ci_failed:
        console.print("\n[bold red]CI Failed[/bold red] - Downloading failure logs...")
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
        console.print(
            f"\n[bold yellow]{comment_count} unresolved comment(s)[/bold yellow] - Downloading..."
        )
        saved_comment_count = pr_context.save_pr_comments(pr_number)
        console.print(f"  Saved {saved_comment_count} actionable comment(s) for review")

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
            console.print(
                "[yellow]  No actionable comments to address (may be bot status updates or already addressed).[/yellow]"
            )
            console.print("[yellow]  Unresolved threads may need manual review on GitHub.[/yellow]")
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

    console.print("\n[bold]Running agent to fix all issues...[/bold]")
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
            console.print(f"[red]Error: Invalid PR input '{pr}'.[/red]")
            console.print("Use a PR number or PR URL, e.g. claudetm fix-pr 123")
            raise typer.Exit(1)

        if pr_number is None:
            # Try to detect from current branch (only when no PR input provided)
            pr_number = github_client.get_pr_for_current_branch()
            if pr_number is None:
                console.print("[red]Error: No PR found for current branch.[/red]")
                console.print("Specify a PR number: claudetm fix-pr 123")
                raise typer.Exit(1)
            console.print(f"[green]Detected PR #{pr_number} for current branch[/green]")

        # Initialize credentials and agent
        cred_manager = CredentialManager()
        access_token = cred_manager.get_valid_token()

        # Initialize state manager (uses default .claude-task-master directory)
        working_dir = Path.cwd()
        state_manager = StateManager()

        # Check for concurrent sessions before proceeding
        if state_manager.is_session_active():
            console.print("[bold red]Another claudetm session is active.[/bold red]")
            console.print("Wait for it to complete or use 'claudetm clean -f' to force cleanup.")
            raise typer.Exit(1)

        # Acquire session lock
        if not state_manager.acquire_session_lock():
            console.print("[bold red]Could not acquire session lock.[/bold red]")
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

        console.print(f"\n[bold]Starting fix-pr loop for PR #{pr_number}[/bold]")
        console.print(f"Max iterations: {max_iterations}")
        console.print("-" * 40)

        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            console.print(f"\n[bold cyan]Iteration {iteration}/{max_iterations}[/bold cyan]")

            # Wait for all CI checks to complete
            status = _wait_for_ci_complete(github_client, pr_number)

            # Determine what needs fixing
            ci_failed = status.ci_state in ("FAILURE", "ERROR")
            has_comments = status.unresolved_threads > 0

            # Show status
            if ci_failed:
                console.print(f"  CI: [red]{status.ci_state}[/red] ({status.checks_failed} failed)")
            else:
                console.print(f"  CI: [green]PASSED[/green] ({status.checks_passed} passed)")

            if has_comments:
                console.print(
                    f"  Comments: [yellow]{status.unresolved_threads} unresolved[/yellow]"
                )

            # If anything needs fixing, download both and run combined session
            if ci_failed or has_comments:
                agent_ran = _run_fix_session(
                    agent,
                    github_client,
                    state_manager,
                    pr_context,
                    pr_number,
                    ci_failed=ci_failed,
                    comment_count=status.unresolved_threads,
                )

                if not agent_ran and not ci_failed:
                    # No actionable work and CI passed - unresolved threads need manual review
                    console.print(
                        "\n[yellow]Exiting: unresolved threads need manual review.[/yellow]"
                    )
                    state_manager.release_session_lock()
                    raise typer.Exit(1)

                # Wait for CI to start after push
                console.print(f"\nWaiting {CI_START_WAIT}s for CI to start...")
                time.sleep(CI_START_WAIT)
                continue

            # All done!
            console.print("\n[bold green]✓ CI passed and all comments resolved![/bold green]")

            if no_merge:
                console.print(
                    f"\n[green]PR #{pr_number} is ready to merge (--no-merge specified)[/green]"
                )
                state_manager.release_session_lock()
                raise typer.Exit(0)

            # Wait for mergeable status if UNKNOWN or None (GitHub needs time to compute)
            merge_attempts = 0
            max_merge_attempts = 6  # 60 seconds total
            while (
                status.mergeable == "UNKNOWN" or status.mergeable is None
            ) and merge_attempts < max_merge_attempts:
                merge_attempts += 1
                console.print(
                    f"  ⏳ Waiting for mergeable status... ({merge_attempts}/{max_merge_attempts})"
                )
                time.sleep(CI_POLL_INTERVAL)
                status = github_client.get_pr_status(pr_number)

            # Check if ready to merge
            if status.mergeable == "MERGEABLE":
                console.print(f"\n[bold]Merging PR #{pr_number}...[/bold]")
                try:
                    github_client.merge_pr(pr_number)
                    console.print(
                        f"[bold green]✓ PR #{pr_number} merged successfully![/bold green]"
                    )
                except Exception as e:
                    console.print(f"[red]Merge failed: {e}[/red]")
                    console.print("You can merge manually.")
                    state_manager.release_session_lock()
                    raise typer.Exit(1) from None
            elif status.mergeable == "CONFLICTING":
                console.print(
                    f"\n[yellow]PR #{pr_number} has merge conflicts - manual resolution required[/yellow]"
                )
                state_manager.release_session_lock()
                raise typer.Exit(1)
            elif status.mergeable is None:
                console.print(
                    f"\n[yellow]PR #{pr_number} mergeability unknown - please check GitHub[/yellow]"
                )
                console.print("You can merge manually once GitHub computes the status.")
                state_manager.release_session_lock()
                raise typer.Exit(1)
            else:
                console.print(
                    f"\n[yellow]PR #{pr_number} mergeable status: {status.mergeable} after {max_merge_attempts} attempts[/yellow]"
                )
                console.print("You can merge manually.")
                state_manager.release_session_lock()
                raise typer.Exit(1)

            state_manager.release_session_lock()
            raise typer.Exit(0)

        # Max iterations reached
        console.print(f"\n[red]Max iterations ({max_iterations}) reached without success.[/red]")
        console.print("Check the PR manually for remaining issues.")
        state_manager.release_session_lock()
        raise typer.Exit(1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
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
        console.print(f"[red]Error: {e}[/red]")
        # Release lock if state_manager was initialized
        try:
            state_manager.release_session_lock()
        except NameError:
            pass  # state_manager wasn't created yet
        raise typer.Exit(1) from None


def register_fix_pr_command(app: typer.Typer) -> None:
    """Register fix-pr command with the Typer app."""
    app.command(name="fix-pr")(fix_pr)
