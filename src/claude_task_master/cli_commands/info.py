"""Info commands for Claude Task Master - status and read-only operations."""

import typer
from rich.console import Console
from rich.markdown import Markdown

from ..core.agent_models import get_tools_for_phase
from ..core.state import StateManager

console = Console()


def status() -> None:
    """Show current status of the task.

    Displays goal, current task, session count, and configuration options.

    Examples:
        claudetm status
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No active task found.[/yellow]")
        raise typer.Exit(1)

    try:
        state = state_manager.load_state()
        goal = state_manager.load_goal()

        console.print("\n[bold blue]Task Status[/bold blue]\n")
        console.print(f"[cyan]Goal:[/cyan] {goal}")
        console.print(f"[cyan]Status:[/cyan] {state.status}")
        console.print(f"[cyan]Model:[/cyan] {state.model}")
        console.print(f"[cyan]Current Task:[/cyan] {state.current_task_index + 1}")
        console.print(f"[cyan]Sessions:[/cyan] {state.session_count}")
        console.print(f"[cyan]Run ID:[/cyan] {state.run_id}")

        # Show tools based on current phase/status. Derive from config so the
        # display stays in sync with the actual restricted phase defaults.
        if state.status == "planning":
            planning_tools = get_tools_for_phase("planning")
            tools_display = ", ".join(planning_tools) if planning_tools else "All"
            console.print(f"[cyan]Tools:[/cyan] {tools_display} (read-only mode)")
        elif state.status == "working":
            console.print("[cyan]Tools:[/cyan] All (bypassPermissions mode)")
        else:
            # For blocked, paused, stopped, success, failed - show what was last used
            console.print("[cyan]Tools:[/cyan] All (bypassPermissions mode)")

        if state.current_pr:
            console.print(f"[cyan]Current PR:[/cyan] #{state.current_pr}")

        console.print("\n[cyan]Options:[/cyan]")
        console.print(f"  Auto-merge: {state.options.auto_merge}")
        console.print(f"  Release phase: {state.options.enable_release}")
        console.print(f"  Final verification: {state.options.enable_verification}")
        console.print(f"  Max sessions: {state.options.max_sessions or 'unlimited'}")
        console.print(f"  Pause on PR: {state.options.pause_on_pr}")
        console.print(f"  Log level: {state.options.log_level}")
        console.print(f"  Log format: {state.options.log_format}")

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def plan() -> None:
    """Display the current task plan.

    Shows the markdown task list with checkboxes indicating completion status.

    Examples:
        claudetm plan
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No active task found.[/yellow]")
        raise typer.Exit(1)

    try:
        plan_content = state_manager.load_plan()

        if not plan_content:
            console.print("[yellow]No plan found.[/yellow]")
            raise typer.Exit(1)

        console.print("\n[bold blue]Task Plan[/bold blue]\n")
        console.print(Markdown(plan_content))

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def logs(
    session: int | None = typer.Option(None, help="Show specific session number"),
    tail: int = typer.Option(100, "--tail", "-n", help="Number of lines to show"),
) -> None:
    """Display logs from the current run.

    Shows Claude's output, tool usage, and execution details.

    Examples:
        claudetm logs
        claudetm logs -n 50
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No active task found.[/yellow]")
        raise typer.Exit(1)

    try:
        state = state_manager.load_state()
        log_file = state_manager.get_log_file(state.run_id)

        if not log_file.exists():
            console.print("[yellow]No log file found.[/yellow]")
            raise typer.Exit(1)

        console.print(f"\n[bold blue]Logs[/bold blue] ({log_file})\n")

        with open(log_file) as f:
            lines = f.readlines()

        # Show last N lines
        for line in lines[-tail:]:
            print(line, end="")

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def context() -> None:
    """Display accumulated context and learnings.

    Shows insights gathered during execution that help inform future sessions.

    Examples:
        claudetm context
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No active task found.[/yellow]")
        raise typer.Exit(1)

    try:
        context_content = state_manager.load_context()

        if not context_content:
            console.print("[yellow]No context accumulated yet.[/yellow]")
            return

        console.print("\n[bold blue]Accumulated Context[/bold blue]\n")
        console.print(Markdown(context_content))

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def progress() -> None:
    """Display human-readable progress summary.

    Shows what has been accomplished and what remains to be done.

    Examples:
        claudetm progress
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No active task found.[/yellow]")
        raise typer.Exit(1)

    try:
        progress_content = state_manager.load_progress()

        if not progress_content:
            console.print("[yellow]No progress recorded yet.[/yellow]")
            return

        console.print("\n[bold blue]Progress Summary[/bold blue]\n")
        console.print(Markdown(progress_content))

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def register_info_commands(app: typer.Typer) -> None:
    """Register info commands with the Typer app."""
    app.command()(status)
    app.command()(plan)
    app.command()(logs)
    app.command()(context)
    app.command()(progress)
