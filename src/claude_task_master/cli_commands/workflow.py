"""Workflow commands for Claude Task Master - start and resume."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown

from ..core.agent import AgentWrapper, ModelType
from ..core.config_loader import initialize_config
from ..core.context_accumulator import ContextAccumulator
from ..core.credentials import CredentialManager
from ..core.logger import LogFormat, LogLevel, TaskLogger
from ..core.orchestrator import WorkLoopOrchestrator
from ..core.planner import Planner
from ..core.state import StateManager, StateResumeValidationError, TaskOptions

console = Console()


def _initialize_logger(
    state_manager: StateManager,
    run_id: str,
    log_level: LogLevel,
    log_format: LogFormat,
) -> TaskLogger:
    """Initialize the task logger with configured level and format."""
    log_file = state_manager.get_log_file(run_id)
    if log_format == LogFormat.JSON:
        log_file = log_file.with_suffix(".json")
    return TaskLogger(log_file, level=log_level, log_format=log_format)


def _initialize_components(
    access_token: str,
    model_type: ModelType,
    working_dir: Path,
    state_manager: StateManager,
    logger: TaskLogger,
) -> tuple[AgentWrapper, Planner]:
    """Initialize the agent and planner components."""
    agent = AgentWrapper(access_token, model_type, str(working_dir), logger=logger)
    planner = Planner(agent, state_manager)
    ContextAccumulator(state_manager)
    return agent, planner


def _run_work_loop(
    agent: AgentWrapper,
    state_manager: StateManager,
    planner: Planner,
    logger: TaskLogger,
) -> int:
    """Run the work loop and return exit code."""
    orchestrator = WorkLoopOrchestrator(agent, state_manager, planner, logger=logger)
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


def start(
    goal: str = typer.Argument(..., help="The goal to achieve (e.g., 'Add user authentication')"),
    model: str = typer.Option(
        "opus",
        "--model",
        "-m",
        help="Model: opus (smartest, default), sonnet (balanced), haiku (fastest)",
    ),
    auto_merge: bool = typer.Option(
        True,
        "--auto-merge/--no-auto-merge",
        help="Automatically merge PRs when CI passes and approved",
    ),
    max_sessions: int | None = typer.Option(
        None,
        "--max-sessions",
        "-n",
        help="Max work sessions before pausing (default: unlimited)",
    ),
    pause_on_pr: bool = typer.Option(
        False,
        "--pause-on-pr",
        help="Pause after creating PR for manual review",
    ),
    enable_checkpointing: bool = typer.Option(
        False,
        "--checkpointing",
        help="Enable file checkpointing for safe rollbacks",
    ),
    log_level: str = typer.Option(
        "normal",
        "--log-level",
        "-l",
        help="Logging level: quiet (errors only), normal (default), verbose (all tool calls)",
    ),
    log_format: str = typer.Option(
        "text",
        "--log-format",
        help="Log output format: text (human-readable, default), json (structured)",
    ),
    pr_per_task: bool = typer.Option(
        False,
        "--pr-per-task",
        help="Create a PR for each task (default: one PR per PR group in plan)",
    ),
) -> None:
    """Start a new task with the given goal.

    Examples:
        claudetm start "Add dark mode toggle"
        claudetm start "Fix bug #123" -m opus --no-auto-merge
        claudetm start "Refactor auth" -n 5 --pause-on-pr
        claudetm start "Debug issue" -l verbose --log-format json
    """
    log_level_enum, log_format_enum = _validate_log_options(log_level, log_format)

    console.print(f"[bold green]Starting new task:[/bold green] {goal}")
    console.print(f"Model: {model}, Auto-merge: {auto_merge}, Log: {log_level}/{log_format}")

    try:
        # Initialize configuration (creates config.json with defaults if missing)
        working_dir = Path.cwd()
        _config = initialize_config(working_dir)  # noqa: F841 - loaded for side effects
        console.print(
            f"[dim]Config loaded from: {working_dir / '.claude-task-master' / 'config.json'}[/dim]"
        )

        # Check if state already exists
        state_manager = StateManager()
        if state_manager.exists():
            console.print(
                "[red]Error: Task already exists. Use 'resume' to continue or 'clean' to start fresh.[/red]"
            )
            raise typer.Exit(1)

        # Load credentials
        console.print("Loading credentials...")
        cred_manager = CredentialManager()
        access_token = cred_manager.get_valid_token()

        # Parse model type
        model_type = ModelType(model)

        # Initialize state
        console.print("Initializing task state...")
        options = TaskOptions(
            auto_merge=auto_merge,
            max_sessions=max_sessions,
            pause_on_pr=pause_on_pr,
            enable_checkpointing=enable_checkpointing,
            log_level=log_level.lower(),
            log_format=log_format.lower(),
            pr_per_task=pr_per_task,
        )
        state = state_manager.initialize(goal=goal, model=model, options=options)

        # Initialize logger with configured level and format
        logger = _initialize_logger(state_manager, state.run_id, log_level_enum, log_format_enum)

        # Initialize components with logger (working_dir already defined above)
        agent, planner = _initialize_components(
            access_token, model_type, working_dir, state_manager, logger
        )

        # Run planning phase
        console.print("\n[bold cyan]Phase 1: Planning[/bold cyan]")
        logger.start_session(0, "planning")

        try:
            plan_result = planner.create_plan(goal)
            logger.log_response(plan_result.get("raw_output", ""))
            logger.end_session("completed")

            # Display plan
            console.print("\n[bold green]Plan created:[/bold green]")
            plan = state_manager.load_plan()
            if plan:
                console.print(Markdown(plan))

            # Update state to working
            state.status = "working"
            state_manager.save_state(state)

        except Exception as e:
            logger.log_error(str(e))
            logger.end_session("failed")
            console.print(f"\n[red]Planning failed: {e}[/red]")
            raise typer.Exit(1) from None

        # Run work loop
        console.print("\n[bold cyan]Phase 2: Execution[/bold cyan]")
        exit_code = _run_work_loop(agent, state_manager, planner, logger)
        _display_exit_message(exit_code)
        raise typer.Exit(exit_code)

    except typer.Exit:
        raise
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("Run 'claude-task-master doctor' to check your setup.")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def resume(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Force resume from failed/blocked state"),
    ] = False,
) -> None:
    """Resume a paused or interrupted task.

    Use this to continue a task that was:
    - Paused by pressing Escape
    - Interrupted by Ctrl+C
    - Blocked and waiting for intervention

    Use --force to recover from a failed state.

    Examples:
        claudetm resume
        claudetm resume --force  # Recover from failed state
    """
    console.print("[bold blue]Resuming task...[/bold blue]")

    try:
        # Initialize configuration (loads existing config.json or uses defaults)
        working_dir = Path.cwd()
        initialize_config(working_dir)

        # Check if state exists
        state_manager = StateManager()
        if not state_manager.exists():
            console.print("[red]Error: No task found to resume.[/red]")
            console.print("Use 'start' to begin a new task.")
            raise typer.Exit(1)

        # Force reset status if requested - detect real state from GitHub
        if force:
            state = state_manager.load_state()
            if state.status in ("failed", "blocked"):
                console.print(f"[yellow]Force recovery from '{state.status}'...[/yellow]")

                from ..core.state_recovery import StateRecovery

                recovery = StateRecovery()
                recovered = recovery.apply_recovery(state)

                console.print(f"[cyan]{recovered.message}[/cyan]")
                console.print(f"[dim]Stage: {recovered.workflow_stage}[/dim]")

                state_manager.save_state(state, validate_transition=False)

        # Load state and validate it's resumable using comprehensive validation
        try:
            state = state_manager.validate_for_resume()
        except StateResumeValidationError as e:
            # Handle terminal states with appropriate exit codes
            if e.status == "success":
                console.print(f"[green]{e.message}[/green]")
                if e.suggestion:
                    console.print(f"[dim]{e.suggestion}[/dim]")
                raise typer.Exit(0) from None
            elif e.status == "failed":
                console.print(f"[red]{e.message}[/red]")
                if e.suggestion:
                    console.print(f"[dim]{e.suggestion}[/dim]")
                raise typer.Exit(1) from None
            else:
                # Other validation errors
                console.print(f"[red]Error: {e.message}[/red]")
                if e.details:
                    console.print(f"[dim]{e.details}[/dim]")
                raise typer.Exit(1) from None

        # Display current status
        goal = state_manager.load_goal()
        console.print(f"\n[cyan]Goal:[/cyan] {goal}")
        console.print(f"[cyan]Status:[/cyan] {state.status}")
        console.print(f"[cyan]Current Task:[/cyan] {state.current_task_index + 1}")
        console.print(f"[cyan]Session Count:[/cyan] {state.session_count}")

        # Load credentials
        console.print("\nLoading credentials...")
        cred_manager = CredentialManager()
        access_token = cred_manager.get_valid_token()

        # Parse model type
        model_type = ModelType(state.model)

        # Get logging options from saved state
        log_level_enum = LogLevel(state.options.log_level)
        log_format_enum = LogFormat(state.options.log_format)

        # Initialize components (working_dir already defined above)
        logger = _initialize_logger(state_manager, state.run_id, log_level_enum, log_format_enum)
        agent, planner = _initialize_components(
            access_token, model_type, working_dir, state_manager, logger
        )

        # Update state to working if it was paused
        if state.status == "paused":
            state.status = "working"
            state_manager.save_state(state)
            console.print("\n[cyan]Status updated from 'paused' to 'working'[/cyan]")

        # If blocked, attempt to resume anyway (user may have fixed the issue)
        if state.status == "blocked":
            state.status = "working"
            state_manager.save_state(state)
            console.print("\n[yellow]Attempting to resume blocked task...[/yellow]")

        # Run work loop
        console.print("\n[bold cyan]Resuming Execution[/bold cyan]")
        exit_code = _run_work_loop(agent, state_manager, planner, logger)
        _display_exit_message(exit_code)
        raise typer.Exit(exit_code)

    except typer.Exit:
        raise
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("Run 'claude-task-master doctor' to check your setup.")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def register_workflow_commands(app: typer.Typer) -> None:
    """Register workflow commands with the Typer app."""
    app.command()(start)
    app.command()(resume)
