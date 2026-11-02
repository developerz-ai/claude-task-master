"""Doctor command - Check system requirements and authentication."""

import subprocess

from rich.console import Console

from ..core.credentials import CredentialError, CredentialManager
from ..github.gh_auth import CREDENTIAL_HINT, credential_source, gh_subprocess_env


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
        """Check the gh CLI and the agent's GitHub credential.

        The agent's GitHub credential is injected per run through the
        environment (``GH_TOKEN`` / ``CLAUDETM_GITHUB_TOKEN``). It is never
        read from disk and never printed: this check reports only whether one
        was injected and which variable carries it.

        A developer host that has its own ``gh`` login still passes: that
        login is the developer's own, not the agent's.
        """
        source = credential_source()
        if source is not None:
            self.console.print(
                f"[green]✓[/green] GitHub agent credential injected via "
                f"[cyan]{source}[/cyan] (value hidden)"
            )

        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                check=False,
                capture_output=True,
                text=True,
                env=gh_subprocess_env(),
            )
        except FileNotFoundError:
            self.console.print("[red]✗[/red] gh CLI not installed")
            self.console.print("  Install from: https://cli.github.com/")
            self.checks_passed = False
            return

        if result.returncode == 0:
            if source is None:
                self.console.print("[green]✓[/green] gh CLI installed and authenticated")
                self.console.print(
                    "  No agent credential injected — this host's gh login is "
                    f"used. [cyan]{CREDENTIAL_HINT}[/cyan]"
                )
            else:
                self.console.print(
                    "[green]✓[/green] gh CLI installed and authenticated "
                    "with the injected credential"
                )
        else:
            if source is None:
                self.console.print("[red]✗[/red] gh CLI not authenticated")
            else:
                self.console.print(
                    "[red]✗[/red] gh CLI could not authenticate with the injected credential"
                )
            self.console.print(f"  [cyan]{CREDENTIAL_HINT}[/cyan]")
            self.checks_passed = False

    def _check_credentials(self) -> None:
        """Check if Claude credentials exist (profile-aware)."""
        try:
            cred_manager = CredentialManager()
            cred_manager.verify_credentials()
            self.console.print("[green]✓[/green] Claude credentials found")
        except CredentialError as e:
            self.console.print(f"[red]✗[/red] Credentials check failed: {e.message}")
            if e.details:
                self.console.print(f"  {e.details}")
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
