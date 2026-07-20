"""Resume command for Claude Task Master."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..core.agent import ModelType
from ..core.config_loader import initialize_config
from ..core.credentials import CredentialManager
from ..core.logger import LogFormat, LogLevel
from ..core.plan_updater import PlanUpdater
from ..core.state import StateManager, StateResumeValidationError
from ..webhooks import WebhookClient
from .workflow_helpers import (
    _display_exit_message,
    _initialize_components,
    _initialize_logger,
    _run_work_loop,
    console,
)


def resume(
    message: Annotated[
        str | None,
        typer.Argument(
            help="Optional change request to update the plan before resuming",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Force resume from failed/blocked state"),
    ] = False,
    admin: Annotated[
        bool | None,
        typer.Option(
            "--admin/--no-admin",
            help="Force-merge past base-branch policy with 'gh pr merge --admin'. "
            "Persists for the task; pass --no-admin to turn it back off.",
        ),
    ] = None,
) -> None:
    """Resume a paused or interrupted task.

    Use this to continue a task that was:
    - Paused by pressing Escape
    - Interrupted by Ctrl+C
    - Blocked and waiting for intervention

    Optionally provide a message to update the plan before resuming.
    This is useful when requirements change mid-task.

    Use --force to recover from a failed state. Use --admin to force-merge a PR
    that a base-branch protection policy would otherwise block.

    Examples:
        claudetm resume
        claudetm resume --force  # Recover from failed state
        claudetm resume --admin -f  # Force-merge past base-branch policy
        claudetm resume "Add authentication to the API"
        claudetm resume "Fix the bug in the login form instead"
    """
    console.print("[bold blue]Resuming task...[/bold blue]")

    # Acquired after validate_for_resume and always released in the finally,
    # even if setup fails before the lock is taken.
    state_manager: StateManager | None = None
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

                from ..core.state_recovery import StateRecovery  # noqa: PLC0415

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

        # Guard against concurrent runs: acquire the single-instance session lock
        # now that the task is known resumable. Placed after validation so a no-op
        # resume of an already-finished task exits cleanly without taking the lock.
        # Two concurrent resumes would otherwise both drive the work loop —
        # corrupting state, duplicating PRs, racing OAuth refresh-token rotation.
        # Held for the whole run and freed by the finally.
        if not state_manager.acquire_session_lock():
            console.print("[red]Error: Another claudetm session is active for this project.[/red]")
            console.print(
                "[dim]Wait for it to finish, or run 'claudetm clean -f' to force cleanup.[/dim]"
            )
            raise typer.Exit(1)

        # Toggle admin force-merge. It is persisted so the retry loop (each blocked-merge
        # cycle re-enters the merge stage and re-reads state) keeps the override active, but
        # because it applies to *every* later PR in the task, --no-admin is offered as an
        # explicit off switch. Only write when the user passed the flag (admin is not None).
        if admin is not None and admin != state.options.admin_merge:
            state.options.admin_merge = admin
            state_manager.save_state(state, validate_transition=False)
            if admin:
                console.print(
                    "[yellow]Admin force-merge enabled (overrides base-branch policy for all "
                    "PRs until --no-admin)[/yellow]"
                )
                if not state.options.auto_merge:
                    console.print(
                        "[yellow]Note: auto-merge is disabled, so --admin has no effect until "
                        "merging is re-enabled.[/yellow]"
                    )
            else:
                console.print("[cyan]Admin force-merge disabled[/cyan]")

        # Display current status
        goal = state_manager.load_goal()
        console.print(f"\n[cyan]Goal:[/cyan] {goal}")
        console.print(f"[cyan]Status:[/cyan] {state.status}")
        console.print(f"[cyan]Current Task:[/cyan] {state.current_task_index + 1}")
        console.print(f"[cyan]Session Count:[/cyan] {state.session_count}")

        # Load credentials
        console.print("\nLoading credentials...")
        cred_manager = CredentialManager()
        # Heal a stale oauth-profile copy before use (see start): re-seed from live ~/.claude when
        # the profile's refresh token was rotated out, so an unattended resume doesn't fail first-try.
        if cred_manager.resync_from_live():
            console.print("[dim]Re-seeded stale profile credentials from ~/.claude[/dim]")
        access_token = cred_manager.get_valid_token()

        # Parse model type
        model_type = ModelType(state.model)

        # Get logging options from saved state
        log_level_enum = LogLevel(state.options.log_level)
        log_format_enum = LogFormat(state.options.log_format)

        # Initialize components (working_dir already defined above)
        logger = _initialize_logger(state_manager, state.run_id, log_level_enum, log_format_enum)
        agent, planner = _initialize_components(
            access_token,
            model_type,
            working_dir,
            state_manager,
            logger,
            max_budget_usd=state.options.max_budget_usd,
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

        # If a message was provided, update the plan first
        if message:
            console.print("\n[bold cyan]Updating plan with change request...[/bold cyan]")
            console.print(
                f"[dim]Message: {message[:100]}{'...' if len(message) > 100 else ''}[/dim]"
            )

            plan_updater = PlanUpdater(agent, state_manager, logger=logger)
            try:
                update_result = plan_updater.update_plan(
                    message, current_task_index=state.current_task_index
                )
                if update_result["changes_made"]:
                    # Adopt the reconciled task index and persist it so the work
                    # loop (which reloads state from disk) resumes on the right
                    # task even if the update inserted/removed tasks above it.
                    reconciled_index = update_result.get("current_task_index")
                    if reconciled_index is not None:
                        state.current_task_index = reconciled_index
                        state_manager.save_state(state)
                    console.print("[green]Plan updated successfully[/green]")
                    # Display a brief summary of the updated plan
                    plan = state_manager.load_plan()
                    if plan:
                        # Count tasks
                        completed = plan.count("- [x]")
                        pending = plan.count("- [ ]")
                        console.print(f"[dim]Tasks: {completed} completed, {pending} pending[/dim]")
                else:
                    console.print("[yellow]No changes needed to plan[/yellow]")
            except Exception as e:
                console.print(f"[red]Error updating plan: {e}[/red]")
                console.print("[yellow]Continuing with existing plan...[/yellow]")

        # Create webhook client if URL was configured
        wh_client: WebhookClient | None = None
        if state.options.webhook_url:
            wh_client = WebhookClient(
                url=state.options.webhook_url, secret=state.options.webhook_secret
            )
            console.print("[dim]Webhook notifications enabled[/dim]")

        # Run work loop
        console.print("\n[bold cyan]Resuming Execution[/bold cyan]")
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
        # Release the session lock on every exit path. A no-op if we never
        # acquired it (e.g. a terminal-state resume) or the orchestrator's
        # cleanup_on_success already released it.
        if state_manager is not None:
            state_manager.release_session_lock()


__all__ = ["resume"]
