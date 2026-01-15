"""CLI entry point for Claude Task Master."""

from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown

from .core.agent import AgentWrapper, ModelType
from .core.context_accumulator import ContextAccumulator
from .core.credentials import CredentialManager
from .core.logger import TaskLogger
from .core.orchestrator import WorkLoopOrchestrator
from .core.planner import Planner
from .core.state import StateManager, StateResumeValidationError, TaskOptions
from .utils.doctor import SystemDoctor

app = typer.Typer(
    name="claude-task-master",
    help="""Autonomous task orchestration system using Claude Agent SDK.

Claude Task Master keeps Claude working until a goal is achieved by:
- Breaking down goals into actionable tasks
- Executing tasks with appropriate tools
- Creating and managing GitHub PRs
- Waiting for CI and addressing reviews

Quick start:
  claudetm start "Your goal here"
  claudetm status
  claudetm clean -f

For more info, see: https://github.com/sebyx07/claude-task-master-py
""",
    add_completion=False,
)
console = Console()


@app.command()
def start(
    goal: str = typer.Argument(..., help="The goal to achieve (e.g., 'Add user authentication')"),
    model: str = typer.Option(
        "sonnet",
        "--model",
        "-m",
        help="Model: sonnet (balanced), opus (smartest), haiku (fastest)",
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
) -> None:
    """Start a new task with the given goal.

    Examples:
        claudetm start "Add dark mode toggle"
        claudetm start "Fix bug #123" -m opus --no-auto-merge
        claudetm start "Refactor auth" -n 5 --pause-on-pr
    """
    console.print(f"[bold green]Starting new task:[/bold green] {goal}")
    console.print(f"Model: {model}, Auto-merge: {auto_merge}")

    try:
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
        )
        state = state_manager.initialize(goal=goal, model=model, options=options)

        # Initialize components
        working_dir = Path.cwd()
        agent = AgentWrapper(access_token, model_type, str(working_dir))
        planner = Planner(agent, state_manager)
        ContextAccumulator(state_manager)

        # Initialize logger
        log_file = state_manager.get_log_file(state.run_id)
        logger = TaskLogger(log_file)

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
        orchestrator = WorkLoopOrchestrator(agent, state_manager, planner)

        exit_code = orchestrator.run()

        if exit_code == 0:
            console.print("\n[bold green]✓ Task completed successfully![/bold green]")
        elif exit_code == 2:
            console.print("\n[yellow]Task paused. Use 'resume' to continue.[/yellow]")
        else:
            console.print("\n[red]Task blocked or failed.[/red]")

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


@app.command()
def resume() -> None:
    """Resume a paused or interrupted task.

    Use this to continue a task that was:
    - Paused by pressing Escape
    - Interrupted by Ctrl+C
    - Blocked and waiting for intervention

    Examples:
        claudetm resume
    """
    console.print("[bold blue]Resuming task...[/bold blue]")

    try:
        # Check if state exists
        state_manager = StateManager()
        if not state_manager.exists():
            console.print("[red]Error: No task found to resume.[/red]")
            console.print("Use 'start' to begin a new task.")
            raise typer.Exit(1)

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

        # Initialize components
        working_dir = Path.cwd()
        agent = AgentWrapper(access_token, model_type, str(working_dir))
        planner = Planner(agent, state_manager)
        ContextAccumulator(state_manager)

        # Initialize logger
        log_file = state_manager.get_log_file(state.run_id)
        TaskLogger(log_file)

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
        orchestrator = WorkLoopOrchestrator(agent, state_manager, planner)

        exit_code = orchestrator.run()

        if exit_code == 0:
            console.print("\n[bold green]✓ Task completed successfully![/bold green]")
        elif exit_code == 2:
            console.print("\n[yellow]Task paused. Use 'resume' to continue.[/yellow]")
        else:
            console.print("\n[red]Task blocked or failed.[/red]")

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


@app.command()
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

        if state.current_pr:
            console.print(f"[cyan]Current PR:[/cyan] #{state.current_pr}")

        console.print("\n[cyan]Options:[/cyan]")
        console.print(f"  Auto-merge: {state.options.auto_merge}")
        console.print(f"  Max sessions: {state.options.max_sessions or 'unlimited'}")
        console.print(f"  Pause on PR: {state.options.pause_on_pr}")

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


@app.command()
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


@app.command()
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


@app.command()
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


@app.command()
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


@app.command()
def comments(
    pr: int | None = typer.Option(None, "--pr", "-p", help="PR number to show comments for"),
) -> None:
    """Display PR review comments.

    Shows review comments for the current task's PR or a specified PR.

    Examples:
        claudetm comments
        claudetm comments -p 123
    """
    console.print("[bold blue]PR Comments[/bold blue]")
    # TODO: Implement comments logic
    raise typer.Exit(1)


@app.command()
def pr() -> None:
    """Display current PR status and CI checks.

    Shows the status of the PR associated with the current task.

    Examples:
        claudetm pr
    """
    console.print("[bold blue]PR Status[/bold blue]")
    # TODO: Implement pr logic
    raise typer.Exit(1)


@app.command()
def clean(force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")) -> None:
    """Clean up task state directory.

    Removes all state files (.claude-task-master/) to start fresh.
    Use this after completing a task or to abandon a stuck task.

    Examples:
        claudetm clean       # Prompts for confirmation
        claudetm clean -f    # Force without confirmation
    """
    state_manager = StateManager()

    if not state_manager.exists():
        console.print("[yellow]No task state found.[/yellow]")
        raise typer.Exit(0)

    if not force:
        confirm = typer.confirm("Are you sure you want to clean all task state?")
        if not confirm:
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    console.print("[bold red]Cleaning task state...[/bold red]")

    import shutil

    if state_manager.state_dir.exists():
        shutil.rmtree(state_manager.state_dir)
        console.print("[green]✓ Task state cleaned[/green]")

    raise typer.Exit(0)


@app.command()
def doctor() -> None:
    """Check system requirements and authentication.

    Verifies:
    - Claude CLI is installed and accessible
    - OAuth credentials exist and are valid
    - Git is configured properly
    - GitHub CLI (gh) is available

    Examples:
        claudetm doctor
    """
    sys_doctor = SystemDoctor()
    success = sys_doctor.run_checks()
    raise typer.Exit(0 if success else 1)


@app.command(name="ci-status")
def ci_status(
    run_id: int | None = typer.Option(None, "--run-id", "-r", help="Specific workflow run ID"),
    limit: int = typer.Option(5, "--limit", "-l", help="Number of recent runs to show"),
) -> None:
    """Show GitHub Actions workflow run status.

    Lists recent CI runs with their status (success/failure/pending).

    Examples:
        claudetm ci-status
        claudetm ci-status -l 10
        claudetm ci-status -r 12345678
    """
    from .github.client import GitHubClient

    try:
        gh = GitHubClient()

        if run_id:
            # Show specific run status
            status = gh.get_workflow_run_status(run_id)
            console.print(status)
        else:
            # Show recent runs
            runs = gh.get_workflow_runs(limit=limit)
            if not runs:
                console.print("[yellow]No workflow runs found.[/yellow]")
                raise typer.Exit(0)

            console.print("[bold]Recent Workflow Runs:[/bold]\n")
            for run in runs:
                emoji = (
                    "✓"
                    if run.conclusion == "success"
                    else "✗"
                    if run.conclusion == "failure"
                    else "⏳"
                )
                console.print(
                    f"{emoji} [bold]#{run.id}[/bold] {run.name} "
                    f"({run.status}/{run.conclusion or 'pending'}) - {run.head_branch}"
                )

    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


@app.command(name="ci-logs")
def ci_logs(
    run_id: int | None = typer.Option(None, "--run-id", "-r", help="Specific workflow run ID"),
    lines: int = typer.Option(100, "--lines", "-n", help="Maximum lines to show"),
) -> None:
    """Show logs from failed CI runs.

    Useful for debugging CI failures without leaving the terminal.

    Examples:
        claudetm ci-logs
        claudetm ci-logs -r 12345678
        claudetm ci-logs -n 200
    """
    from .github.client import GitHubClient

    try:
        gh = GitHubClient()
        logs = gh.get_failed_run_logs(run_id, max_lines=lines)
        if logs:
            console.print(logs)
        else:
            console.print("[green]No failed runs found.[/green]")

    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


@app.command(name="pr-comments")
def pr_comments(
    pr_number: int = typer.Argument(..., help="PR number"),
    all_comments: bool = typer.Option(False, "--all", "-a", help="Include resolved comments"),
) -> None:
    """Show PR review comments formatted for addressing.

    Displays reviewer feedback grouped by file for easy reference.

    Examples:
        claudetm pr-comments 123
        claudetm pr-comments 123 --all
    """
    from .github.client import GitHubClient

    try:
        gh = GitHubClient()
        comments = gh.get_pr_comments(pr_number, only_unresolved=not all_comments)

        if comments:
            console.print(f"[bold]Review Comments for PR #{pr_number}:[/bold]\n")
            console.print(comments)
        else:
            console.print(
                f"[green]No {'unresolved ' if not all_comments else ''}comments on PR #{pr_number}.[/green]"
            )

    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


@app.command(name="pr-status")
def pr_status_cmd(
    pr_number: int = typer.Argument(..., help="PR number"),
) -> None:
    """Show PR status including CI and review comments.

    Displays CI check results and count of unresolved review threads.

    Examples:
        claudetm pr-status 123
    """
    from .github.client import GitHubClient

    try:
        gh = GitHubClient()
        status = gh.get_pr_status(pr_number)

        ci_emoji = (
            "✓"
            if status.ci_state == "SUCCESS"
            else "✗"
            if status.ci_state in ("FAILURE", "ERROR")
            else "⏳"
        )

        console.print(f"[bold]PR #{pr_number} Status:[/bold]")
        console.print(f"  {ci_emoji} CI: {status.ci_state}")
        console.print(f"  💬 Unresolved comments: {status.unresolved_threads}")

        if status.check_details:
            console.print("\n[bold]Checks:[/bold]")
            for check in status.check_details:
                check_emoji = (
                    "✓"
                    if check.get("conclusion") == "success"
                    else "✗"
                    if check.get("conclusion") == "failure"
                    else "⏳"
                )
                console.print(
                    f"  {check_emoji} {check['name']}: {check.get('conclusion') or check.get('status', 'pending')}"
                )

    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
