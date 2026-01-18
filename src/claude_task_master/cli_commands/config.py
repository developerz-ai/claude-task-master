"""Config commands for Claude Task Master - configuration management.

Provides commands to manage the .claude-task-master/config.json file:
- init: Create default config file
- show: Display current configuration
- path: Show path to config file
"""

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax

from ..core.config_loader import (
    config_file_exists,
    generate_default_config_file,
    get_config,
    get_config_file_path,
    get_env_overrides,
)

console = Console()

# Create the config command group (sub-app)
config_app = typer.Typer(
    name="config",
    help="📋 Manage configuration settings.",
    no_args_is_help=True,
)


@config_app.command(name="init")
def config_init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config"),
    show: bool = typer.Option(False, "--show", "-s", help="Show config after creation"),
) -> None:
    """🚀 Initialize configuration file with default values.

    Creates .claude-task-master/config.json with sensible defaults.
    Use --force to overwrite an existing configuration file.

    Examples:
        claudetm config init
        claudetm config init --force
        claudetm config init --show
    """
    config_path = get_config_file_path()

    if config_file_exists() and not force:
        console.print(f"[yellow]⚠️  Config file already exists:[/yellow] {config_path}")
        console.print("[dim]Use --force to overwrite.[/dim]")
        raise typer.Exit(1)

    try:
        generate_default_config_file(config_path, overwrite=force)
        console.print(f"[green]✅ Config file created:[/green] {config_path}")

        if show:
            console.print()
            _display_config()

    except Exception as e:
        console.print(f"[red]❌ Error creating config: {e}[/red]")
        raise typer.Exit(1) from None


@config_app.command(name="show")
def config_show(
    raw: bool = typer.Option(False, "--raw", "-r", help="Show raw JSON without formatting"),
    env: bool = typer.Option(False, "--env", "-e", help="Show environment variable overrides"),
) -> None:
    """📖 Display current configuration.

    Shows the active configuration including any environment variable overrides.
    Use --raw for machine-readable JSON output.

    Examples:
        claudetm config show
        claudetm config show --raw
        claudetm config show --env
    """
    if env:
        _display_env_overrides()
        return

    _display_config(raw=raw)


@config_app.command(name="path")
def config_path(
    check: bool = typer.Option(False, "--check", "-c", help="Check if file exists"),
) -> None:
    """📍 Show path to configuration file.

    Useful for scripting or editing config directly.
    Use --check to also verify if the file exists.

    Examples:
        claudetm config path
        claudetm config path --check
        cat $(claudetm config path)
    """
    path = get_config_file_path()

    if check:
        exists = config_file_exists()
        if exists:
            console.print(f"[green]✅ {path}[/green]")
        else:
            console.print(f"[yellow]⚠️  {path}[/yellow] [dim](not found)[/dim]")
            raise typer.Exit(1)
    else:
        # Plain output for piping
        console.print(str(path))


def _display_config(raw: bool = False) -> None:
    """Display the current configuration.

    Args:
        raw: If True, output raw JSON without formatting.
    """
    try:
        config = get_config()
        config_json = config.model_dump_json(indent=2)

        if raw:
            print(config_json)
        else:
            config_path = get_config_file_path()
            exists = config_file_exists()

            if exists:
                console.print(f"[bold blue]📋 Configuration[/bold blue] ({config_path})\n")
            else:
                console.print(
                    "[bold blue]📋 Configuration[/bold blue] [dim](defaults, no file)[/dim]\n"
                )

            # Display as syntax-highlighted JSON
            syntax = Syntax(config_json, "json", theme="monokai", line_numbers=False)
            console.print(syntax)

            # Show env var overrides hint
            overrides = get_env_overrides()
            if overrides:
                console.print(
                    f"\n[dim]📎 {len(overrides)} environment variable override(s) applied[/dim]"
                )
                console.print("[dim]   Use 'claudetm config show --env' to see them[/dim]")

    except Exception as e:
        console.print(f"[red]❌ Error loading config: {e}[/red]")
        raise typer.Exit(1) from None


def _display_env_overrides() -> None:
    """Display active environment variable overrides."""
    overrides = get_env_overrides()

    console.print("[bold blue]🔧 Environment Variable Overrides[/bold blue]\n")

    if not overrides:
        console.print("[dim]No environment variable overrides are currently set.[/dim]\n")
        console.print("[bold]Available environment variables:[/bold]")
        env_vars_md = """
| Variable | Config Path | Description |
|----------|-------------|-------------|
| `ANTHROPIC_API_KEY` | `api.anthropic_api_key` | Anthropic API key |
| `ANTHROPIC_BASE_URL` | `api.anthropic_base_url` | Anthropic API URL |
| `OPENROUTER_API_KEY` | `api.openrouter_api_key` | OpenRouter API key |
| `OPENROUTER_BASE_URL` | `api.openrouter_base_url` | OpenRouter API URL |
| `CLAUDETM_MODEL_SONNET` | `models.sonnet` | Sonnet model name |
| `CLAUDETM_MODEL_OPUS` | `models.opus` | Opus model name |
| `CLAUDETM_MODEL_HAIKU` | `models.haiku` | Haiku model name |
| `CLAUDETM_TARGET_BRANCH` | `git.target_branch` | Target branch for PRs |
"""
        console.print(Markdown(env_vars_md))
        return

    console.print("[bold]Active overrides:[/bold]\n")
    for env_var, value in overrides.items():
        # Mask sensitive values
        if "key" in env_var.lower() or "secret" in env_var.lower():
            masked = value[:8] + "..." if len(value) > 8 else "***"
            console.print(f"  [cyan]{env_var}[/cyan] = [dim]{masked}[/dim]")
        else:
            console.print(f"  [cyan]{env_var}[/cyan] = {value}")


def register_config_commands(app: typer.Typer) -> None:
    """Register config command group with the Typer app.

    Args:
        app: The main Typer application.
    """
    app.add_typer(config_app, name="config")
