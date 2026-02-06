"""CLI entry point for Claude Task Master."""

import asyncio

import typer
from rich.console import Console

from . import __version__
from .cli_commands.config import register_config_commands
from .cli_commands.control import register_control_commands
from .cli_commands.fix_pr import register_fix_pr_command
from .cli_commands.github import register_github_commands
from .cli_commands.info import register_info_commands
from .cli_commands.mailbox import register_mailbox_commands
from .cli_commands.workflow import register_workflow_commands
from .core.state import StateManager
from .utils.debug_claude_md import debug_claude_md_detection
from .utils.doctor import SystemDoctor


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console = Console()
        console.print(f"Claude Task Master v{__version__}")
        raise typer.Exit(0)


app = typer.Typer(
    name="claude-task-master",
    help="""Autonomous task orchestration system using Claude Agent SDK.

Claude Task Master keeps Claude working until a goal is achieved by:
- Breaking down goals into actionable tasks
- Executing tasks with appropriate tools
- Creating and managing GitHub PRs
- Waiting for CI and addressing reviews

Quick start:
  claudetm start "Your goal here"
  claudetm status
  claudetm clean -f

For more info, see: https://github.com/developerz-ai/claude-task-master
""",
    add_completion=False,
)
console = Console()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Claude Task Master - Autonomous task orchestration."""
    pass


# Register commands from submodules
register_workflow_commands(app)  # start, resume (resume accepts optional message for plan updates)
register_info_commands(app)  # status, plan, logs, context, progress
register_github_commands(app)  # ci-status, ci-logs, pr-comments, pr-status
register_config_commands(app)  # config init, config show, config path
register_control_commands(app)  # pause, stop, config-update
register_fix_pr_command(app)  # fix-pr
register_mailbox_commands(app)  # mailbox, mailbox send, mailbox clear


@app.command()
def comments(
    pr_number: int | None = typer.Option(None, "--pr", "-p", help="PR number to show comments for"),
    all_comments: bool = typer.Option(
        False, "--all", "-a", help="Show all comments including resolved ones"
    ),
) -> None:
    """Display PR review comments.

    Shows review comments for the current task's PR or a specified PR.
    By default, only shows unresolved comments.

    Examples:
        claudetm comments           # Show unresolved comments for current PR
        claudetm comments -p 123    # Show unresolved comments for PR #123
        claudetm comments -a        # Show all comments including resolved
    """
    from .github.client import GitHubClient
    from .github.exceptions import GitHubError

    # Determine which PR to check
    if pr_number is None:
        # Try to get from task state first
        state_manager = StateManager()
        if state_manager.exists():
            try:
                state = state_manager.load_state()
                pr_number = state.current_pr
            except Exception:
                pass  # Ignore state loading errors

        # If no PR in state, try to get from current branch
        if pr_number is None:
            try:
                gh_client = GitHubClient()
                pr_number = gh_client.get_pr_for_current_branch()
            except GitHubError as e:
                console.print(f"[red]Error checking current branch: {e}[/red]")
                raise typer.Exit(1) from None

        if pr_number is None:
            console.print("[yellow]No PR found for current branch or task.[/yellow]")
            raise typer.Exit(1)

    # Get PR comments
    try:
        gh_client = GitHubClient()

        # Get PR info for display
        import json
        import subprocess

        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--json", "title,url"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            pr_info = json.loads(result.stdout)
            pr_title = pr_info.get("title", "Unknown")
            pr_url = pr_info.get("url", "")
        else:
            pr_title = "Unknown"
            pr_url = ""

        # Get comments using the GitHub client
        only_unresolved = not all_comments
        comments_text = gh_client.get_pr_comments(pr_number, only_unresolved=only_unresolved)

    except GitHubError as e:
        console.print(f"[red]Error fetching PR comments: {e}[/red]")
        raise typer.Exit(1) from None

    # Display header
    console.print("\n[bold blue]PR Review Comments[/bold blue]\n")
    console.print(f"[cyan]PR:[/cyan] #{pr_number}")
    console.print(f"[cyan]Title:[/cyan] {pr_title}")
    if pr_url:
        console.print(f"[cyan]URL:[/cyan] {pr_url}")

    filter_msg = "all" if all_comments else "unresolved"
    console.print(f"[cyan]Filter:[/cyan] {filter_msg}")

    # Display comments
    console.print("\n[bold]Comments[/bold]\n")

    if not comments_text.strip():
        if all_comments:
            console.print("[dim]No review comments on this PR.[/dim]")
        else:
            console.print("[green]✓ No unresolved review comments.[/green]")
    else:
        # Parse and display comments in a more readable format
        from rich.markdown import Markdown
        from rich.panel import Panel

        # Split comments by the separator used in _format_pr_comments_from_rest
        comment_blocks = comments_text.split("\n---\n\n")

        for i, block in enumerate(comment_blocks, 1):
            if block.strip():
                # Create a panel for each comment
                console.print(
                    Panel(Markdown(block.strip()), title=f"Comment {i}", border_style="dim")
                )
                console.print()  # Add spacing between comments

    raise typer.Exit(0)


@app.command()
def pr(
    pr_number: int | None = typer.Option(None, "--pr", "-p", help="PR number to check"),
) -> None:
    """Display current PR status and CI checks.

    Shows the status of the PR associated with the current task, or a specified PR.
    Displays PR number, URL, title, CI status, review status, and merge status.

    Examples:
        claudetm pr          # Show status for current task's PR
        claudetm pr -p 123   # Show status for PR #123
    """
    from .github.client import GitHubClient
    from .github.exceptions import GitHubError

    # Determine which PR to check
    if pr_number is None:
        # Try to get from task state first
        state_manager = StateManager()
        if state_manager.exists():
            try:
                state = state_manager.load_state()
                pr_number = state.current_pr
            except Exception:
                pass  # Ignore state loading errors

        # If no PR in state, try to get from current branch
        if pr_number is None:
            try:
                gh_client = GitHubClient()
                pr_number = gh_client.get_pr_for_current_branch()
            except GitHubError as e:
                console.print(f"[red]Error checking current branch: {e}[/red]")
                raise typer.Exit(1) from None

        if pr_number is None:
            console.print("[yellow]No PR found for current branch or task.[/yellow]")
            raise typer.Exit(1)

    # Get PR status
    try:
        gh_client = GitHubClient()
        pr_status = gh_client.get_pr_status(pr_number)

        # Get additional PR info (title, URL) using gh pr view
        import json
        import subprocess

        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--json", "title,url,state,isDraft"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            pr_info = json.loads(result.stdout)
            pr_title = pr_info.get("title", "Unknown")
            pr_url = pr_info.get("url", "")
            is_draft = pr_info.get("isDraft", False)
        else:
            pr_title = "Unknown"
            pr_url = ""
            is_draft = False

    except GitHubError as e:
        console.print(f"[red]Error fetching PR status: {e}[/red]")
        raise typer.Exit(1) from None

    # Display PR info
    console.print("\n[bold blue]PR Status[/bold blue]\n")
    console.print(f"[cyan]PR:[/cyan] #{pr_number}")
    console.print(f"[cyan]Title:[/cyan] {pr_title}")
    if is_draft:
        console.print("[cyan]Draft:[/cyan] [yellow]Yes[/yellow]")
    if pr_url:
        console.print(f"[cyan]URL:[/cyan] {pr_url}")

    # PR State
    state_color = {
        "OPEN": "green",
        "CLOSED": "red",
        "MERGED": "magenta",
    }.get(pr_status.state, "white")
    console.print(f"[cyan]State:[/cyan] [{state_color}]{pr_status.state}[/{state_color}]")

    # CI Status
    console.print("\n[bold]CI Status[/bold]")
    ci_color = {
        "SUCCESS": "green",
        "PENDING": "yellow",
        "FAILURE": "red",
        "ERROR": "red",
    }.get(pr_status.ci_state, "white")
    console.print(f"  [cyan]Overall:[/cyan] [{ci_color}]{pr_status.ci_state}[/{ci_color}]")

    if pr_status.checks_passed or pr_status.checks_failed or pr_status.checks_pending:
        console.print(
            f"  [green]✓ Passed:[/green] {pr_status.checks_passed}  "
            f"[red]✗ Failed:[/red] {pr_status.checks_failed}  "
            f"[yellow]⏳ Pending:[/yellow] {pr_status.checks_pending}"
        )
        if pr_status.checks_skipped:
            console.print(f"  [dim]Skipped:[/dim] {pr_status.checks_skipped}")

    # Show check details if there are failures
    if pr_status.checks_failed > 0:
        console.print("\n  [bold red]Failed Checks:[/bold red]")
        for check in pr_status.check_details:
            conclusion = (check.get("conclusion") or "").upper()
            if conclusion in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT"):
                name = check.get("name", "Unknown")
                url = check.get("url", "")
                console.print(f"    [red]✗[/red] {name}")
                if url:
                    console.print(f"      [dim]{url}[/dim]")

    # Review Status
    console.print("\n[bold]Review Status[/bold]")
    if pr_status.total_threads > 0:
        console.print(f"  [cyan]Threads:[/cyan] {pr_status.total_threads} total")
        if pr_status.unresolved_threads > 0:
            console.print(f"  [yellow]⚠ Unresolved:[/yellow] {pr_status.unresolved_threads}")
        if pr_status.resolved_threads > 0:
            console.print(f"  [green]✓ Resolved:[/green] {pr_status.resolved_threads}")
    else:
        console.print("  [dim]No review comments[/dim]")

    # Merge Status
    console.print("\n[bold]Merge Status[/bold]")
    mergeable_color = {
        "MERGEABLE": "green",
        "CONFLICTING": "red",
        "UNKNOWN": "yellow",
    }.get(pr_status.mergeable, "white")
    console.print(
        f"  [cyan]Mergeable:[/cyan] [{mergeable_color}]{pr_status.mergeable}[/{mergeable_color}]"
    )

    merge_state_color = {
        "CLEAN": "green",
        "BLOCKED": "red",
        "BEHIND": "yellow",
        "DIRTY": "red",
        "HAS_HOOKS": "yellow",
        "UNKNOWN": "dim",
        "UNSTABLE": "yellow",
    }.get(pr_status.merge_state_status, "white")
    console.print(
        f"  [cyan]Merge State:[/cyan] [{merge_state_color}]{pr_status.merge_state_status}[/{merge_state_color}]"
    )
    console.print(f"  [cyan]Base Branch:[/cyan] {pr_status.base_branch}")

    raise typer.Exit(0)


@app.command()
def clean(force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")) -> None:
    """Clean up task state directory.

    Removes all state files (.claude-task-master/) to start fresh.
    Use this after completing a task or to abandon a stuck task.

    Examples:
        claudetm clean       # Prompts for confirmation
        claudetm clean -f    # Force without confirmation
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No task state found.[/yellow]")
        raise typer.Exit(0)

    # Check if another session is active
    if state_manager.is_session_active():
        console.print("[bold red]Warning: Another claudetm session is active![/bold red]")
        if not force:
            confirm = typer.confirm("Force cleanup anyway? This may crash the running session")
            if not confirm:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(1)
        console.print("[yellow]Forcing cleanup of active session...[/yellow]")

    if not force:
        confirm = typer.confirm("Are you sure you want to clean all task state?")
        if not confirm:
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    console.print("[bold red]Cleaning task state...[/bold red]")

    import shutil

    # Release any session lock before deletion
    state_manager.release_session_lock()

    if state_manager.state_dir.exists():
        shutil.rmtree(state_manager.state_dir)
        console.print("[green]✓ Task state cleaned[/green]")

    raise typer.Exit(0)


@app.command()
def debug_md(
    directory: str | None = typer.Argument(None, help="Directory to test (defaults to current)"),
) -> None:
    """Debug CLAUDE.md detection when changing directories for queries.

    Tests whether CLAUDE.md is properly detected by Claude when the SDK
    changes directories for a query. This is useful for verifying that
    project context is loaded correctly.

    The test will:
    1. Check if CLAUDE.md exists in the target directory
    2. Run a simple query from that directory
    3. Analyze Claude's response to detect project context indicators
    4. Report whether CLAUDE.md appears to be loaded

    Examples:
        claudetm debug-md
        claudetm debug-md /path/to/project
    """
    try:
        success = asyncio.run(debug_claude_md_detection(directory))
        raise typer.Exit(0 if success else 1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        raise typer.Exit(2) from None
    except Exception as e:
        console.print(f"[red]Error running debug: {e}[/red]")
        raise typer.Exit(1) from None


@app.command()
def doctor() -> None:
    """Check system requirements and authentication.

    Verifies:
    - Claude CLI is installed and accessible
    - OAuth credentials exist and are valid
    - Git is configured properly
    - GitHub CLI (gh) is available

    Examples:
        claudetm doctor
    """
    sys_doctor = SystemDoctor()
    success = sys_doctor.run_checks()
    raise typer.Exit(0 if success else 1)


if __name__ == "__main__":
    app()
