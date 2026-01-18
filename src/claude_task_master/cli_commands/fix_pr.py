"""Fix PR command - Iteratively fix CI failures and address review comments."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

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
CI_POLL_INTERVAL = 15  # seconds between CI checks
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


def _wait_for_ci_complete(github_client: GitHubClient, pr_number: int) -> PRStatus:
    """Wait for all CI checks to complete.

    Args:
        github_client: GitHub client for API calls.
        pr_number: PR number to check.

    Returns:
        Final PRStatus after all checks complete.
    """
    console.print(f"[bold]Waiting for CI checks on PR #{pr_number}...[/bold]")

    while True:
        status = github_client.get_pr_status(pr_number)

        # Count pending checks
        pending = [
            check.get("name", "unknown")
            for check in status.check_details
            if check.get("status", "").upper() not in ("COMPLETED",)
            and check.get("conclusion") is None
        ]

        if not pending:
            # All checks complete
            return status

        # Show progress
        console.print(
            f"  ⏳ Waiting for {len(pending)} check(s): "
            f"{', '.join(pending[:3])}{'...' if len(pending) > 3 else ''}"
        )
        time.sleep(CI_POLL_INTERVAL)


def _run_ci_fix_session(
    agent: AgentWrapper,
    github_client: GitHubClient,
    state_manager: StateManager,
    pr_context: PRContextManager,
    pr_number: int,
) -> None:
    """Run agent session to fix CI failures.

    Args:
        agent: Agent wrapper for running work sessions.
        github_client: GitHub client for API calls.
        state_manager: State manager for persistence.
        pr_context: PR context manager for saving CI logs.
        pr_number: PR number being fixed.
    """
    console.print("\n[bold red]CI Failed[/bold red] - Running agent to fix...")

    # Save CI failure logs
    pr_context.save_ci_failures(pr_number)

    # Build fix prompt
    pr_dir = state_manager.get_pr_dir(pr_number)
    ci_path = f"{pr_dir}/ci/"

    task_description = f"""CI has failed for PR #{pr_number}.

**Read the CI failure logs from:** `{ci_path}`

Use Glob to find all .txt files, then Read each one to understand the errors.

**IMPORTANT:** Fix ALL CI failures, even if they seem unrelated to your current work.
Your job is to keep CI green. Pre-existing issues, flaky tests, lint errors - fix them all.

Please:
1. Read ALL files in the ci/ directory
2. Understand ALL error messages (lint, tests, types, etc.)
3. Fix everything that's failing - don't skip anything
4. Run tests/lint locally to verify ALL passes
5. Commit and push the fixes

After fixing, end with: TASK COMPLETE"""

    current_branch = _get_current_branch()
    agent.run_work_session(
        task_description=task_description,
        context="",
        model_override=ModelType.OPUS,
        required_branch=current_branch,
    )


def _run_comments_fix_session(
    agent: AgentWrapper,
    github_client: GitHubClient,
    state_manager: StateManager,
    pr_context: PRContextManager,
    pr_number: int,
    comment_count: int,
) -> bool:
    """Run agent session to address review comments.

    Args:
        agent: Agent wrapper for running work sessions.
        github_client: GitHub client for API calls.
        state_manager: State manager for persistence.
        pr_context: PR context manager for saving comments.
        pr_number: PR number being fixed.
        comment_count: Number of unresolved comments.

    Returns:
        True if agent ran and made changes, False if no actionable comments found.
    """
    console.print(
        f"\n[bold yellow]{comment_count} unresolved comment(s)[/bold yellow] - Running agent to address..."
    )

    # Save PR comments
    saved_count = pr_context.save_pr_comments(pr_number)
    console.print(f"  Saved {saved_count} actionable comment(s) for review")

    # Guard against loops when no actionable comments are found
    if saved_count == 0:
        console.print(
            "[yellow]  No actionable comments to address (may be bot status updates or already addressed).[/yellow]"
        )
        console.print("[yellow]  Unresolved threads may need manual review on GitHub.[/yellow]")
        return False

    # Build fix prompt
    pr_dir = state_manager.get_pr_dir(pr_number)
    comments_path = f"{pr_dir}/comments/"
    resolve_json_path = f"{pr_dir}/resolve-comments.json"

    task_description = f"""PR #{pr_number} has review comments to address.

**Read the review comments from:** `{comments_path}`

Use Glob to find all .txt files, then Read each one to understand the feedback.

Please:
1. Read ALL comment files in the comments/ directory
2. For each comment:
   - Make the requested change, OR
   - Explain why it's not needed
3. Run tests to verify
4. Commit and push the fixes
5. Create a resolution summary file at: `{resolve_json_path}`

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
The orchestrator will handle thread resolution automatically after you create the resolution file.
Your job is to: fix the code, run tests, commit, push, and create the resolution JSON file.

After addressing ALL comments and creating the resolution file, end with: TASK COMPLETE"""

    current_branch = _get_current_branch()
    agent.run_work_session(
        task_description=task_description,
        context="",
        model_override=ModelType.OPUS,
        required_branch=current_branch,
    )

    # Post replies to comments using resolution file
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

            # Check CI status
            if status.ci_state in ("FAILURE", "ERROR"):
                console.print(f"  CI: [red]{status.ci_state}[/red] ({status.checks_failed} failed)")
                _run_ci_fix_session(agent, github_client, state_manager, pr_context, pr_number)

                # Wait for CI to start after push
                console.print(f"\nWaiting {CI_START_WAIT}s for CI to start...")
                time.sleep(CI_START_WAIT)
                continue

            # CI passed - check for unresolved comments
            console.print(f"  CI: [green]PASSED[/green] ({status.checks_passed} passed)")

            if status.unresolved_threads > 0:
                agent_ran = _run_comments_fix_session(
                    agent,
                    github_client,
                    state_manager,
                    pr_context,
                    pr_number,
                    status.unresolved_threads,
                )

                if not agent_ran:
                    # No actionable comments - break to avoid infinite loop
                    console.print(
                        "\n[yellow]Exiting: unresolved threads need manual review.[/yellow]"
                    )
                    state_manager.release_session_lock()
                    raise typer.Exit(1)

                # Wait for CI to start after push (comments fix might have changed code)
                console.print(f"\nWaiting {CI_START_WAIT}s for CI to start...")
                time.sleep(CI_START_WAIT)
                continue

            # All done!
            console.print("\n[bold green]✓ CI passed and all comments resolved![/bold green]")

            # Check if ready to merge
            if status.mergeable == "MERGEABLE" or status.mergeable is None:
                if no_merge:
                    console.print(
                        f"\n[green]PR #{pr_number} is ready to merge (--no-merge specified)[/green]"
                    )
                else:
                    console.print(f"\n[bold]Merging PR #{pr_number}...[/bold]")
                    try:
                        github_client.merge_pr(pr_number)
                        console.print(
                            f"[bold green]✓ PR #{pr_number} merged successfully![/bold green]"
                        )
                    except Exception as e:
                        console.print(f"[red]Merge failed: {e}[/red]")
                        console.print("You can merge manually.")
            elif status.mergeable == "CONFLICTING":
                console.print(
                    f"\n[yellow]PR #{pr_number} has merge conflicts - manual resolution required[/yellow]"
                )
            else:
                console.print(
                    f"\n[yellow]PR #{pr_number} mergeable status: {status.mergeable}[/yellow]"
                )

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
