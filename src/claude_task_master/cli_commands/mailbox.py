"""Mailbox CLI commands for Claude Task Master.

This module provides CLI commands for interacting with the mailbox:
- mailbox (status) - show mailbox status
- mailbox send - send a message to the mailbox
- mailbox clear - clear all messages
"""

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ..core.state import StateManager
from ..mailbox.models import Priority
from ..mailbox.storage import MailboxStorage

console = Console()


def get_mailbox_storage() -> MailboxStorage:
    """Get mailbox storage instance using state manager's directory.

    Returns:
        MailboxStorage instance configured for the current project.
    """
    state_manager = StateManager()
    return MailboxStorage(state_dir=state_manager.state_dir)


def mailbox_status() -> None:
    """Show mailbox status.

    Displays the number of pending messages and their previews.

    Examples:
        claudetm mailbox
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No active task found.[/yellow]")
        console.print("[dim]Start a task first with 'claudetm start'.[/dim]")
        raise typer.Exit(1)

    try:
        mailbox = get_mailbox_storage()
        status = mailbox.get_status()

        console.print("\n[bold blue]Mailbox Status[/bold blue]\n")

        # Show summary
        count = status["count"]
        if count == 0:
            console.print("[dim]No pending messages.[/dim]")
        else:
            console.print(f"[cyan]Pending messages:[/cyan] {count}")

        # Show last checked
        if status["last_checked"]:
            console.print(f"[cyan]Last checked:[/cyan] {status['last_checked']}")

        # Show total received
        console.print(f"[cyan]Total received:[/cyan] {status['total_messages_received']}")

        # Show message previews if any
        if status["previews"]:
            console.print()
            table = Table(title="Messages")
            table.add_column("Priority", style="cyan", width=8)
            table.add_column("Sender", style="green", width=15)
            table.add_column("Content", style="white")
            table.add_column("Time", style="dim", width=20)

            priority_names = {0: "LOW", 1: "NORMAL", 2: "HIGH", 3: "URGENT"}
            priority_styles = {0: "dim", 1: "white", 2: "yellow", 3: "red bold"}

            for preview in status["previews"]:
                prio = preview["priority"]
                prio_name = priority_names.get(prio, str(prio))
                prio_style = priority_styles.get(prio, "white")

                table.add_row(
                    f"[{prio_style}]{prio_name}[/{prio_style}]",
                    preview["sender"],
                    preview["content_preview"],
                    preview["timestamp"][:19].replace("T", " "),  # Truncate and format datetime
                )

            console.print(table)

        raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def mailbox_send(
    message: Annotated[str, typer.Argument(help="Message content to send")],
    sender: Annotated[
        str,
        typer.Option("--sender", "-s", help="Sender identifier"),
    ] = "cli",
    priority: Annotated[
        int,
        typer.Option("--priority", "-p", help="Priority level (0=low, 1=normal, 2=high, 3=urgent)"),
    ] = 1,
) -> None:
    """Send a message to the mailbox.

    Adds a new message that will be processed after the current task completes.
    The orchestrator checks the mailbox after each task and updates the plan
    if messages are present.

    Examples:
        claudetm mailbox send "Please also update the README"
        claudetm mailbox send "Fix the auth bug first" --priority 3
        claudetm mailbox send "Low priority cleanup" -p 0 -s "supervisor"
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No active task found.[/yellow]")
        console.print("[dim]Start a task first with 'claudetm start'.[/dim]")
        raise typer.Exit(1)

    # Validate priority
    if priority < 0 or priority > 3:
        console.print("[red]Error: Priority must be between 0 and 3.[/red]")
        console.print("[dim]0=low, 1=normal, 2=high, 3=urgent[/dim]")
        raise typer.Exit(1)

    try:
        mailbox = get_mailbox_storage()
        message_id = mailbox.add_message(
            content=message,
            sender=sender,
            priority=Priority(priority),
        )

        priority_names = {0: "LOW", 1: "NORMAL", 2: "HIGH", 3: "URGENT"}
        console.print("[green]Message sent to mailbox.[/green]")
        console.print(f"[dim]ID: {message_id}[/dim]")
        console.print(f"[dim]Priority: {priority_names.get(priority, str(priority))}[/dim]")
        console.print(f"[dim]Sender: {sender}[/dim]")
        console.print()
        console.print(
            "[dim]The orchestrator will process this message after the current task.[/dim]"
        )

        raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def mailbox_clear(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
) -> None:
    """Clear all messages from the mailbox.

    Removes all pending messages. This is useful to cancel pending plan updates
    or start fresh.

    Examples:
        claudetm mailbox clear
        claudetm mailbox clear -f
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No active task found.[/yellow]")
        console.print("[dim]Start a task first with 'claudetm start'.[/dim]")
        raise typer.Exit(1)

    try:
        mailbox = get_mailbox_storage()
        count = mailbox.count()

        if count == 0:
            console.print("[dim]Mailbox is already empty.[/dim]")
            raise typer.Exit(0)

        # Confirm unless forced
        if not force:
            confirm = typer.confirm(f"Clear {count} message(s) from mailbox?")
            if not confirm:
                console.print("[yellow]Cancelled.[/yellow]")
                raise typer.Exit(0)

        cleared = mailbox.clear()
        console.print(f"[green]Cleared {cleared} message(s) from mailbox.[/green]")

        raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


# Create the mailbox subcommand group
mailbox_app = typer.Typer(
    name="mailbox",
    help="""Manage the mailbox for inter-instance communication.

The mailbox allows external systems (MCP, REST API, other claudetm instances)
to send messages that will be processed by the orchestrator after each task.

Commands:
  (no subcommand)  Show mailbox status
  send             Send a message to the mailbox
  clear            Clear all messages

Examples:
    claudetm mailbox                              # Show status
    claudetm mailbox send "Update the README"     # Send a message
    claudetm mailbox send "Urgent fix" -p 3       # High priority message
    claudetm mailbox clear                        # Clear messages
""",
    add_completion=False,
    invoke_without_command=True,
)


@mailbox_app.callback(invoke_without_command=True)
def mailbox_callback(ctx: typer.Context) -> None:
    """Show mailbox status when called without subcommand."""
    if ctx.invoked_subcommand is None:
        mailbox_status()


@mailbox_app.command("send")
def mailbox_send_command(
    message: Annotated[str, typer.Argument(help="Message content to send")],
    sender: Annotated[
        str,
        typer.Option("--sender", "-s", help="Sender identifier"),
    ] = "cli",
    priority: Annotated[
        int,
        typer.Option("--priority", "-p", help="Priority level (0=low, 1=normal, 2=high, 3=urgent)"),
    ] = 1,
) -> None:
    """Send a message to the mailbox.

    Adds a new message that will be processed after the current task completes.
    The orchestrator checks the mailbox after each task and updates the plan
    if messages are present.

    Examples:
        claudetm mailbox send "Please also update the README"
        claudetm mailbox send "Fix the auth bug first" --priority 3
        claudetm mailbox send "Low priority cleanup" -p 0 -s "supervisor"
    """
    mailbox_send(message, sender, priority)


@mailbox_app.command("clear")
def mailbox_clear_command(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
) -> None:
    """Clear all messages from the mailbox.

    Removes all pending messages. This is useful to cancel pending plan updates
    or start fresh.

    Examples:
        claudetm mailbox clear
        claudetm mailbox clear -f
    """
    mailbox_clear(force)


def register_mailbox_commands(app: typer.Typer) -> None:
    """Register mailbox commands with the main Typer app.

    Args:
        app: The main Typer application.
    """
    app.add_typer(mailbox_app, name="mailbox")
