"""Profile commands - manage named authentication profiles.

Profiles let claudetm run under isolated credentials so multiple Claude
subscriptions (or a custom Anthropic-compatible endpoint such as z.ai) can be
used without colliding on the global ``~/.claude/.credentials.json``.

Commands:
- add:    Create a profile (oauth or api-key)
- list:   List all profiles and show the active one
- use:    Set the active profile
- show:   Show a profile's details
- remove: Delete a profile
- login:  Authenticate an oauth profile (runs `claude` in its isolated dir)
"""

from __future__ import annotations

import os
import subprocess

import typer
from rich.console import Console
from rich.table import Table

from ..core.profiles import (
    PROFILE_ENV_VAR,
    Profile,
    ProfileError,
    ProfileManager,
)

console = Console()

profile_app = typer.Typer(
    name="profile",
    help="🔀 Manage authentication profiles (multi-account / custom endpoints).",
    no_args_is_help=True,
)


def _mask(secret: str | None) -> str:
    """Mask a secret for display, keeping a short prefix/suffix."""
    if not secret:
        return "[dim](none)[/dim]"
    if len(secret) <= 10:
        return "***"
    return f"{secret[:6]}…{secret[-4:]}"


@profile_app.command(name="add")
def profile_add(
    name: str = typer.Argument(..., help="Unique profile name"),
    profile_type: str = typer.Option(
        "oauth", "--type", "-t", help="Profile type: 'oauth' or 'api-key'"
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="Anthropic-compatible base URL (api-key profiles)"
    ),
) -> None:
    """➕ Add a new profile.

    For api-key profiles the key is read from the CLAUDETM_API_KEY environment
    variable, or prompted for securely (never passed as a CLI flag, which would
    leak it into shell history and process listings).

    Examples:
        claudetm profile add work                       # oauth (Claude sub)
        claudetm profile add zai --type api-key \\
            --base-url https://api.z.ai/api/anthropic   # prompts for the key
    """
    if profile_type not in ("oauth", "api-key"):
        console.print(f"[red]Invalid --type '{profile_type}'. Use 'oauth' or 'api-key'.[/red]")
        raise typer.Exit(1)

    api_key: str | None = None
    if profile_type == "api-key":
        api_key = os.environ.get("CLAUDETM_API_KEY") or typer.prompt("API key", hide_input=True)

    manager = ProfileManager()
    try:
        profile = manager.add(
            name=name,
            profile_type=profile_type,  # type: ignore[arg-type]
            api_key=api_key,
            base_url=base_url,
        )
    except ProfileError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    console.print(f"[green]✅ Created {profile.type} profile:[/green] {profile.name}")
    if profile.type == "oauth":
        console.print(f"[dim]Config dir:[/dim] {profile.config_dir}")
        console.print(
            f"[yellow]Next:[/yellow] authenticate this profile with "
            f"[cyan]claudetm profile login {name}[/cyan]"
        )
    if manager.active_name() == name:
        console.print(f"[dim]'{name}' is now the active profile.[/dim]")


@profile_app.command(name="list")
def profile_list() -> None:
    """📋 List all profiles (the active one is marked)."""
    manager = ProfileManager()
    profiles = manager.list()
    active = manager.active_name()

    if not profiles:
        console.print("[dim]No profiles yet. Create one with 'claudetm profile add <name>'.[/dim]")
        return

    table = Table(title="Profiles")
    table.add_column("", style="green", width=2)
    table.add_column("Name", style="cyan")
    table.add_column("Type")
    table.add_column("Detail", style="dim")

    for p in profiles:
        marker = "→" if p.name == active else ""
        detail = p.config_dir if p.type == "oauth" else (p.base_url or "api.anthropic.com")
        table.add_row(marker, p.name, p.type, detail or "")

    console.print(table)


@profile_app.command(name="use")
def profile_use(
    name: str = typer.Argument(..., help="Profile name to activate"),
) -> None:
    """✅ Set the active profile.

    The active profile applies to subsequent runs. Override per-run with the
    CLAUDETM_PROFILE environment variable.
    """
    manager = ProfileManager()
    try:
        manager.use(name)
    except ProfileError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]✅ Active profile:[/green] {name}")


@profile_app.command(name="show")
def profile_show(
    name: str | None = typer.Argument(None, help="Profile name (defaults to active)"),
) -> None:
    """🔎 Show a profile's details (secrets masked)."""
    manager = ProfileManager()
    target = name or manager.active_name()
    if not target:
        console.print("[yellow]No profile specified and none active.[/yellow]")
        raise typer.Exit(1)
    try:
        profile = manager.get(target)
    except ProfileError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    _print_profile(profile, active=(profile.name == manager.active_name()))


def _print_profile(profile: Profile, active: bool) -> None:
    """Render a single profile's fields."""
    console.print(
        f"[bold cyan]{profile.name}[/bold cyan]" + (" [green](active)[/green]" if active else "")
    )
    console.print(f"  [dim]type:[/dim]       {profile.type}")
    if profile.type == "oauth":
        console.print(f"  [dim]config_dir:[/dim] {profile.config_dir}")
    else:
        console.print(f"  [dim]base_url:[/dim]   {profile.base_url or 'https://api.anthropic.com'}")
        console.print(f"  [dim]api_key:[/dim]    {_mask(profile.api_key)}")


@profile_app.command(name="remove")
def profile_remove(
    name: str = typer.Argument(..., help="Profile name to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """🗑️  Remove a profile (its config dir is left on disk)."""
    manager = ProfileManager()
    if not force and not typer.confirm(f"Remove profile '{name}'?"):
        console.print("[yellow]Cancelled[/yellow]")
        raise typer.Exit(0)
    try:
        manager.remove(name)
    except ProfileError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]✅ Removed profile:[/green] {name}")


@profile_app.command(name="login")
def profile_login(
    name: str = typer.Argument(..., help="oauth profile to authenticate"),
) -> None:
    """🔑 Authenticate an oauth profile by running `claude` in its isolated dir.

    Launches the bundled `claude` CLI with CLAUDE_CONFIG_DIR pointed at the
    profile's directory so its login/credentials stay isolated. Run `/login`
    inside, then exit.
    """
    manager = ProfileManager()
    try:
        profile = manager.get(name)
    except ProfileError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    if profile.type != "oauth" or not profile.config_dir:
        console.print(f"[red]Profile '{name}' is not an oauth profile.[/red]")
        raise typer.Exit(1)

    console.print(
        f"[cyan]Launching claude for profile '{name}'.[/cyan] "
        "Run [bold]/login[/bold] to authenticate, then exit."
    )
    env = {**os.environ, "CLAUDE_CONFIG_DIR": profile.config_dir}
    try:
        result = subprocess.run(["claude"], env=env)
    except FileNotFoundError:
        console.print("[red]`claude` CLI not found on PATH.[/red]")
        raise typer.Exit(1) from None
    raise typer.Exit(result.returncode)


def register_profile_commands(app: typer.Typer) -> None:
    """Register the profile command group with the Typer app."""
    app.add_typer(profile_app, name="profile")


__all__ = ["register_profile_commands", "PROFILE_ENV_VAR"]
