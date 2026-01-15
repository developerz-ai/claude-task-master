"""Doctor command - Check system requirements and authentication."""

import subprocess
from pathlib import Path

from rich.console import Console


class SystemDoctor:
    """Checks system requirements."""

    def __init__(self) -> None:
        """Initialize doctor."""
        self.console = Console()
        self.checks_passed = True

    def run_checks(self) -> bool:
        """Run all system checks."""
        self.console.print("[bold blue]Running system checks...[/bold blue]\n")

        self._check_gh_cli()
        self._check_credentials()
        self._check_python_version()

        if self.checks_passed:
            self.console.print("\n[bold green]✓ All checks passed![/bold green]")
        else:
            self.console.print("\n[bold red]✗ Some checks failed[/bold red]")

        return self.checks_passed

    def _check_gh_cli(self) -> None:
        """Check if gh CLI is installed and authenticated."""
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                check=False,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                self.console.print("[green]✓[/green] gh CLI installed and authenticated")
            else:
                self.console.print("[red]✗[/red] gh CLI not authenticated")
                self.console.print("  Run: [cyan]gh auth login[/cyan]")
                self.checks_passed = False

        except FileNotFoundError:
            self.console.print("[red]✗[/red] gh CLI not installed")
            self.console.print("  Install from: https://cli.github.com/")
            self.checks_passed = False

    def _check_credentials(self) -> None:
        """Check if Claude credentials exist."""
        creds_path = Path.home() / ".claude" / ".credentials.json"

        if creds_path.exists():
            self.console.print("[green]✓[/green] Claude credentials found")
        else:
            self.console.print("[red]✗[/red] Claude credentials not found")
            self.console.print(f"  Expected at: {creds_path}")
            self.console.print("  Run Claude CLI once to authenticate")
            self.checks_passed = False

    def _check_python_version(self) -> None:
        """Check Python version."""
        import sys

        version = sys.version_info
        if version >= (3, 10):
            self.console.print(
                f"[green]✓[/green] Python {version.major}.{version.minor}.{version.micro}"
            )
        else:
            self.console.print(
                f"[red]✗[/red] Python {version.major}.{version.minor}.{version.micro}"
            )
            self.console.print("  Requires Python 3.10 or higher")
            self.checks_passed = False
