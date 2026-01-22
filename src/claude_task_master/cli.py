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
    pr: int | None = typer.Option(None, "--pr", "-p", help="PR number to show comments for"),
) -> None:
    """Display PR review comments.

    Shows review comments for the current task's PR or a specified PR.

    Examples:
        claudetm comments
        claudetm comments -p 123
    """
    console.print("[bold blue]PR Comments[/bold blue]")
    # TODO: Implement comments logic
    raise typer.Exit(1)


@app.command()
def pr() -> None:
    """Display current PR status and CI checks.

    Shows the status of the PR associated with the current task.

    Examples:
        claudetm pr
    """
    console.print("[bold blue]PR Status[/bold blue]")
    # TODO: Implement pr logic
    raise typer.Exit(1)


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
