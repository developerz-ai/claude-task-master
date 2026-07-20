"""Start command for Claude Task Master."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markdown import Markdown

from ..core.agent import ModelType
from ..core.config_loader import initialize_config
from ..core.credentials import CredentialManager
from ..core.git_branch import is_valid_branch_name
from ..core.state import StateManager, TaskOptions
from ..webhooks import WebhookClient
from .workflow_helpers import (
    _display_exit_message,
    _initialize_components,
    _initialize_logger,
    _run_work_loop,
    _validate_budget,
    _validate_goal,
    _validate_log_options,
    auto_merge_notice,
    console,
)


def start(
    goal: str = typer.Argument(
        ...,
        callback=_validate_goal,
        help="The goal to achieve (e.g., 'Add user authentication')",
    ),
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
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Use 'gh pr merge --admin' to override base-branch policy when merging",
    ),
    enable_release: bool = typer.Option(
        False,
        "--release/--no-release",
        help="Run post-merge release verification (deploy/health/migration/error checks)",
    ),
    enable_verification: bool = typer.Option(
        False,
        "--verify/--no-verify",
        help="Run final success-criteria verification + fix loop after all tasks complete",
    ),
    max_sessions: int | None = typer.Option(
        None,
        "--max-sessions",
        "-n",
        min=1,
        help="Max work sessions before pausing (default: unlimited)",
    ),
    max_prs: int | None = typer.Option(
        None,
        "--prs",
        min=1,
        help="Max pull requests to create (default: unlimited)",
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
    branch: str | None = typer.Option(
        None,
        "--branch",
        "-b",
        help="Explicit branch name for this run (default: agent-chosen). Use distinct "
        "names for concurrent runs of the same task to avoid PR collisions.",
    ),
    webhook_url: str | None = typer.Option(
        None,
        "--webhook-url",
        envvar="CLAUDETM_WEBHOOK_URL",
        help="URL to receive webhook notifications for task lifecycle events (env: CLAUDETM_WEBHOOK_URL)",
    ),
    webhook_secret: str | None = typer.Option(
        None,
        "--webhook-secret",
        envvar="CLAUDETM_WEBHOOK_SECRET",
        help="HMAC secret for signing webhook payloads (env: CLAUDETM_WEBHOOK_SECRET)",
    ),
    budget: float | None = typer.Option(
        None,
        "--budget",
        envvar="CLAUDETM_BUDGET",
        callback=_validate_budget,
        help="Max spending per session in USD, must be > 0 (env: CLAUDETM_BUDGET)",
    ),
) -> None:
    """Start a new task with the given goal.

    Examples:
        claudetm start "Add dark mode toggle"
        claudetm start "Fix bug #123" -m opus --no-auto-merge
        claudetm start "Refactor auth" -n 5 --pause-on-pr
        claudetm start "Add user auth" --prs 1
        claudetm start "Implement dashboard" --prs 3 --max-sessions 10
        claudetm start "Debug issue" -l verbose --log-format json
        claudetm start "Deploy feature" --webhook-url https://example.com/hooks

    Environment Variables:
        CLAUDETM_WEBHOOK_URL: Set webhook URL (overridden by --webhook-url argument)
        CLAUDETM_WEBHOOK_SECRET: Set webhook secret (overridden by --webhook-secret argument)
    """
    log_level_enum, log_format_enum = _validate_log_options(log_level, log_format)

    if branch is not None and not is_valid_branch_name(branch):
        console.print(
            f"[red]Invalid --branch value: {branch!r} is not a valid git branch name.[/red]"
        )
        raise typer.Exit(1)

    console.print(f"[bold green]Starting new task:[/bold green] {goal}")
    console.print(f"Model: {model}, Auto-merge: {auto_merge}, Log: {log_level}/{log_format}")
    notice = auto_merge_notice(auto_merge)
    if notice:
        console.print(f"[yellow]⚠ {notice}[/yellow]")
    if budget is not None:
        console.print(f"Budget: ${budget:.2f}/session")

    # Validate and create webhook client early (before state initialization)
    # to avoid stuck resumes if the URL is invalid
    wh_client: WebhookClient | None = None
    if webhook_url:
        console.print(
            f"Webhook: {webhook_url} (secret: {'configured' if webhook_secret else 'none'})"
        )
        try:
            wh_client = WebhookClient(url=webhook_url, secret=webhook_secret)
        except ValueError as e:
            console.print(f"[red]Invalid webhook configuration: {e}[/red]")
            raise typer.Exit(1) from None

    # Acquired once the state dir is known (after the exists() check) and always
    # released in the finally, even if setup fails before the lock is taken.
    state_manager: StateManager | None = None
    try:
        # Initialize configuration (creates config.json with defaults if missing)
        working_dir = Path.cwd()
        initialize_config(working_dir)
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

        # Guard against concurrent runs: acquire the single-instance session lock
        # before loading credentials or touching shared state. Two simultaneous
        # `claudetm start` runs would otherwise corrupt state.json, duplicate PRs,
        # and race OAuth refresh-token rotation. Held for the whole run and freed
        # by the finally. (Pairs with the O_EXCL PID lock in core/state.py.)
        if not state_manager.acquire_session_lock():
            console.print("[red]Error: Another claudetm session is active for this project.[/red]")
            console.print(
                "[dim]Wait for it to finish, or run 'claudetm clean -f' to force cleanup.[/dim]"
            )
            raise typer.Exit(1)

        # Load credentials
        console.print("Loading credentials...")
        cred_manager = CredentialManager()
        # Heal a stale oauth-profile copy before use: if the profile's refresh token was rotated
        # out from under it (a common unattended-run failure), re-seed from live ~/.claude.
        if cred_manager.resync_from_live():
            console.print("[dim]Re-seeded stale profile credentials from ~/.claude[/dim]")
        access_token = cred_manager.get_valid_token()

        # Parse model type
        model_type = ModelType(model)

        # --admin only takes effect on the merge path, which is gated by auto_merge. Warn rather
        # than silently ignore the flag when merging is disabled.
        if admin and not auto_merge:
            console.print(
                "[yellow]Warning: --admin has no effect with --no-auto-merge "
                "(nothing is merged automatically).[/yellow]"
            )

        # Initialize state
        console.print("Initializing task state...")
        options = TaskOptions(
            auto_merge=auto_merge,
            admin_merge=admin,
            enable_release=enable_release,
            enable_verification=enable_verification,
            max_sessions=max_sessions,
            max_prs=max_prs,
            pause_on_pr=pause_on_pr,
            enable_checkpointing=enable_checkpointing,
            log_level=log_level.lower(),
            log_format=log_format.lower(),
            pr_per_task=pr_per_task,
            branch_override=branch,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            max_budget_usd=budget,
        )
        state = state_manager.initialize(goal=goal, model=model, options=options)

        # Initialize logger with configured level and format
        logger = _initialize_logger(state_manager, state.run_id, log_level_enum, log_format_enum)

        # Initialize components with logger (working_dir already defined above)
        agent, planner = _initialize_components(
            access_token, model_type, working_dir, state_manager, logger, max_budget_usd=budget
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

        # Print webhook notification status (client already created above)
        if wh_client:
            console.print("[dim]Webhook notifications enabled[/dim]")

        # Run work loop
        console.print("\n[bold cyan]Phase 2: Execution[/bold cyan]")
        exit_code = _run_work_loop(agent, state_manager, planner, logger, wh_client)
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
    finally:
        # Release the session lock on every exit path (success, pause, block,
        # error). A no-op if we never acquired it or the orchestrator's
        # cleanup_on_success already released it.
        if state_manager is not None:
            state_manager.release_session_lock()


__all__ = ["start"]
