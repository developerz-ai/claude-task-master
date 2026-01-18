"""Control commands for Claude Task Master - pause, stop, resume, config."""

from typing import Annotated, Any

import typer
from rich.console import Console

from ..core.control import ControlManager
from ..core.state import StateManager

console = Console()


def pause(
    reason: Annotated[
        str | None,
        typer.Option("--reason", "-r", help="Reason for pausing the task"),
    ] = None,
) -> None:
    """Pause a running task.

    Pauses the current task, which can be resumed later using 'resume'.
    Task must be in planning or working status to be paused.

    Examples:
        claudetm pause
        claudetm pause --reason "Taking a break"
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No active task found.[/yellow]")
        console.print("Use 'start' to begin a new task.")
        raise typer.Exit(1)

    try:
        control = ControlManager(state_manager)

        # Check if task can be paused
        if not control.can_pause():
            state = state_manager.load_state()
            console.print(f"[red]Cannot pause task in '{state.status}' status.[/red]")
            console.print("[dim]Task must be in 'planning' or 'working' status to pause.[/dim]")
            raise typer.Exit(1)

        # Pause the task
        result = control.pause(reason)

        console.print(f"[green]✓ {result.message}[/green]")

        if result.details and result.details.get("reason"):
            console.print(f"[dim]Reason: {result.details['reason']}[/dim]")
        console.print("[dim]Use 'resume' to continue the task.[/dim]")

        raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def stop(
    reason: Annotated[
        str | None,
        typer.Option("--reason", "-r", help="Reason for stopping the task"),
    ] = None,
    cleanup: Annotated[
        bool,
        typer.Option("--cleanup", "-c", help="Cleanup state files after stopping"),
    ] = False,
) -> None:
    """Stop a running task.

    Stops the current task. The task enters 'stopped' status and can be
    resumed if needed. Use --cleanup to remove state files entirely.

    Examples:
        claudetm stop
        claudetm stop --reason "Task completed"
        claudetm stop --cleanup
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No active task found.[/yellow]")
        raise typer.Exit(1)

    try:
        control = ControlManager(state_manager)

        # Check if task can be stopped
        if not control.can_stop():
            state = state_manager.load_state()
            console.print(f"[red]Cannot stop task in '{state.status}' status.[/red]")
            console.print(
                "[dim]Task must be in 'planning', 'working', 'blocked', or 'paused' status to stop.[/dim]"
            )
            raise typer.Exit(1)

        # Stop the task
        result = control.stop(reason, cleanup)

        console.print(f"[green]✓ {result.message}[/green]")

        if result.details:
            if result.details.get("reason"):
                console.print(f"[dim]Reason: {result.details['reason']}[/dim]")
            if result.details.get("cleanup"):
                console.print("[dim]State files cleaned up.[/dim]")

        raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def config_update(
    auto_merge: bool | None = typer.Option(
        None, "--auto-merge/--no-auto-merge", help="Set auto-merge option"
    ),
    max_sessions: int | None = typer.Option(None, "--max-sessions", "-n", help="Set max sessions"),
    pause_on_pr: bool | None = typer.Option(
        None, "--pause-on-pr/--no-pause-on-pr", help="Set pause on PR"
    ),
) -> None:
    """Update task configuration at runtime.

    Updates configuration options for the current task. Only specified
    options are updated; others retain their current values.

    Examples:
        claudetm config-update --auto-merge
        claudetm config-update --no-auto-merge --max-sessions 10
        claudetm config-update --pause-on-pr
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No active task found.[/yellow]")
        raise typer.Exit(1)

    # Check if any options were provided
    if all(v is None for v in [auto_merge, max_sessions, pause_on_pr]):
        console.print("[yellow]No configuration options specified.[/yellow]")
        console.print("Use --help to see available options.")
        raise typer.Exit(1)

    try:
        control = ControlManager(state_manager)

        # Build kwargs with only provided options
        kwargs: dict[str, Any] = {}
        if auto_merge is not None:
            kwargs["auto_merge"] = auto_merge
        if max_sessions is not None:
            kwargs["max_sessions"] = max_sessions
        if pause_on_pr is not None:
            kwargs["pause_on_pr"] = pause_on_pr

        # Update configuration
        result = control.update_config(**kwargs)

        console.print(f"[green]✓ {result.message}[/green]")

        # Show current configuration
        if result.details and result.details.get("current"):
            current = result.details["current"]
            console.print("\n[cyan]Current Configuration:[/cyan]")
            console.print(f"  Auto-merge: {current.get('auto_merge')}")
            console.print(f"  Max sessions: {current.get('max_sessions') or 'unlimited'}")
            console.print(f"  Pause on PR: {current.get('pause_on_pr')}")

        raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def register_control_commands(app: typer.Typer) -> None:
    """Register control commands with the Typer app."""
    app.command()(pause)
    app.command()(stop)
    app.command()(config_update)
