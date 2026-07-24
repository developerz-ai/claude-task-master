"""Update command for Claude Task Master - self-update from PyPI.

`claudetm update` checks PyPI for the latest published version and reinstalls
the tool via `uv tool install --force --reinstall` (falling back to pipx when
uv is not available). The network check degrades gracefully: if PyPI cannot be
reached, the reinstall still runs and installs whatever PyPI serves.
"""

from __future__ import annotations

import shutil
import subprocess

import httpx
import typer
from rich.console import Console

from .. import __version__

console = Console()

PYPI_JSON_URL = "https://pypi.org/pypi/claude-task-master/json"


def get_latest_version() -> str | None:
    """Fetch the latest published version from PyPI.

    Returns:
        The latest version string, or None if PyPI is unreachable.
    """
    try:
        response = httpx.get(PYPI_JSON_URL, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        version = response.json()["info"]["version"]
        return str(version)
    except Exception:
        return None


def build_update_command() -> list[str] | None:
    """Build the reinstall command for whichever installer is available.

    Prefers uv (the documented install path), falls back to pipx.

    Returns:
        The command argv, or None when neither installer is on PATH.
    """
    if shutil.which("uv"):
        return ["uv", "tool", "install", "--force", "--reinstall", "claude-task-master"]
    if shutil.which("pipx"):
        return ["pipx", "install", "--force", "claude-task-master"]
    return None


def update(
    check: bool = typer.Option(
        False, "--check", help="Only check for a newer version, don't install"
    ),
) -> None:
    """Update claudetm to the latest version from PyPI.

    Examples:
        claudetm update
        claudetm update --check
    """
    console.print(f"[cyan]Current version:[/cyan] {__version__}")

    latest = get_latest_version()
    if latest is None:
        console.print("[yellow]Could not reach PyPI to check the latest version.[/yellow]")
    else:
        console.print(f"[cyan]Latest version:[/cyan]  {latest}")
        if latest == __version__:
            console.print("[green]Already up to date.[/green]")
            if not check:
                console.print(
                    "Reinstall anyway with: uv tool install --force --reinstall claude-task-master"
                )
            return

    if check:
        if latest is not None:
            console.print(f"[yellow]Update available:[/yellow] {__version__} → {latest}")
            console.print("Run [bold]claudetm update[/bold] to install it.")
        raise typer.Exit(0)

    command = build_update_command()
    if command is None:
        console.print(
            "[red]Neither 'uv' nor 'pipx' found on PATH.[/red]\n"
            "Install uv (https://docs.astral.sh/uv/) and run:\n"
            "  uv tool install --force --reinstall claude-task-master"
        )
        raise typer.Exit(1)

    console.print(f"[cyan]Running:[/cyan] {' '.join(command)}")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        console.print(f"[red]Update failed (exit code {result.returncode}).[/red]")
        raise typer.Exit(result.returncode)

    console.print("[green]Update complete.[/green] Run 'claudetm --version' to confirm.")


def register_update_command(app: typer.Typer) -> None:
    """Register the update command with the Typer app."""
    app.command()(update)
