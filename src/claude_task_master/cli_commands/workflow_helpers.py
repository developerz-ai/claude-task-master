"""Shared helpers for the start and resume workflow commands."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console

from ..core.agent import AgentWrapper, ModelType
from ..core.logger import LogFormat, LogLevel, TaskLogger
from ..core.orchestrator import WorkLoopOrchestrator
from ..core.planner import Planner
from ..core.state import StateManager
from ..webhooks import WebhookClient

if TYPE_CHECKING:
    pass

console = Console()


def auto_merge_notice(auto_merge: bool) -> str | None:
    """Banner text shown before a run when auto-merge is active.

    claudetm merges its own PRs via a ``gh`` subprocess, outside Claude Code's tool
    boundary, so a host repo's git-guard hook cannot intercept it. Make the default
    explicit and point at the off switch. Returns None when auto-merge is off.
    """
    if not auto_merge:
        return None
    return (
        "auto-merge is ON — every PR will be merged automatically when CI passes.\n"
        "  PR merges run via `gh`, outside Claude Code's tool boundary, so host "
        "git-guard hooks cannot intercept them.\n"
        "  Pass --no-auto-merge for this run, or `claudetm config-update --no-auto-merge` "
        "to disable it by default."
    )


def _initialize_logger(
    state_manager: StateManager,
    run_id: str,
    log_level: LogLevel,
    log_format: LogFormat,
) -> TaskLogger:
    """Initialize the task logger with configured level and format."""
    log_file = state_manager.get_log_file(run_id)
    if log_format == LogFormat.JSON:
        # JSON logs are written as JSON Lines (one entry per line), appended on
        # the fly — name the file accordingly.
        log_file = log_file.with_suffix(".jsonl")
    return TaskLogger(log_file, level=log_level, log_format=log_format)


def _initialize_components(
    access_token: str,
    model_type: ModelType,
    working_dir: Path,
    state_manager: StateManager,
    logger: TaskLogger,
    max_budget_usd: float | None = None,
) -> tuple[AgentWrapper, Planner]:
    """Initialize the agent and planner components."""
    agent = AgentWrapper(
        access_token, model_type, str(working_dir), logger=logger, max_budget_usd=max_budget_usd
    )
    planner = Planner(agent, state_manager)
    return agent, planner


def _run_work_loop(
    agent: AgentWrapper,
    state_manager: StateManager,
    planner: Planner,
    logger: TaskLogger,
    webhook_client: WebhookClient | None = None,
) -> int:
    """Run the work loop and return exit code."""
    orchestrator = WorkLoopOrchestrator(
        agent, state_manager, planner, logger=logger, webhook_client=webhook_client
    )
    return orchestrator.run()


def _display_exit_message(exit_code: int) -> None:
    """Display appropriate message based on exit code."""
    if exit_code == 0:
        console.print("\n[bold green]Task completed successfully![/bold green]")
    elif exit_code == 2:
        console.print("\n[yellow]Task paused. Use 'resume' to continue.[/yellow]")
    else:
        console.print("\n[red]Task blocked or failed.[/red]")


def _validate_log_options(log_level: str, log_format: str) -> tuple[LogLevel, LogFormat]:
    """Validate and convert log level and format strings to enums."""
    try:
        log_level_enum = LogLevel(log_level.lower())
    except ValueError:
        console.print(
            f"[red]Error: Invalid log level '{log_level}'. "
            f"Valid options: quiet, normal, verbose[/red]"
        )
        raise typer.Exit(1) from None

    try:
        log_format_enum = LogFormat(log_format.lower())
    except ValueError:
        console.print(
            f"[red]Error: Invalid log format '{log_format}'. Valid options: text, json[/red]"
        )
        raise typer.Exit(1) from None

    return log_level_enum, log_format_enum


def _validate_goal(value: str) -> str:
    """Reject an empty or whitespace-only goal at parse time.

    Args:
        value: The goal argument as parsed from the CLI.

    Returns:
        The original value if non-empty.

    Raises:
        typer.BadParameter: If the goal is empty or only whitespace.
    """
    if not value.strip():
        raise typer.BadParameter("goal must not be empty")
    return value


def _validate_budget(value: float | None) -> float | None:
    """Reject a non-positive per-session budget at parse time.

    A zero or negative budget would otherwise block the run on the first token.

    Args:
        value: The budget in USD, or None when unset.

    Returns:
        The original value if positive or None.

    Raises:
        typer.BadParameter: If the budget is zero or negative.
    """
    if value is not None and value <= 0:
        raise typer.BadParameter("must be greater than 0 (USD per session)")
    return value


__all__ = [
    "console",
    "auto_merge_notice",
    "_initialize_logger",
    "_initialize_components",
    "_run_work_loop",
    "_display_exit_message",
    "_validate_log_options",
    "_validate_goal",
    "_validate_budget",
]
