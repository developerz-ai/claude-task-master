"""OrchestratorLoop — main task execution loop extracted from orchestrator.py.

``WorkLoopOrchestrator.run()`` delegates its entire body here, keeping the
orchestrator file under 500 LOC while centralising all loop / stage / verification
/ fix-PR logic in one place.
"""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime
from typing import TYPE_CHECKING

from . import console
from .agent import ModelType
from .agent_exceptions import AgentError, ConsecutiveFailuresError, ContentFilterError
from .circuit_breaker import CircuitBreakerError
from .config_loader import get_config
from .key_listener import (
    get_cancellation_reason,
    is_cancellation_requested,
    reset_escape,
    start_listening,
    stop_listening,
)
from .orchestrator_errors import MaxSessionsReachedError, OrchestratorError
from .plan_parsing import count_completed_tasks, is_task_complete, parse_task_descriptions
from .shutdown import (
    interruptible_sleep,
    register_handlers,
    reset_shutdown,
    set_durable_stop_check,
    unregister_handlers,
)
from .state import StateError, StateValidationError, TaskState
from .task_runner import NoPlanFoundError, NoTasksFoundError, WorkSessionError

if TYPE_CHECKING:
    from .orchestrator import WorkLoopOrchestrator

logger = logging.getLogger(__name__)


class OrchestratorLoop:
    """Drives the main work loop for :class:`WorkLoopOrchestrator`.

    Instantiated fresh on each :meth:`WorkLoopOrchestrator.run` call so it
    carries no mutable state between runs on the same orchestrator instance.
    All persistent state lives on the injected ``orc`` reference.
    """

    def __init__(self, orc: WorkLoopOrchestrator) -> None:
        self._orc = orc

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Run the main work loop until completion or blocked.

        Returns:
            0: Success - all tasks completed and verified.
            1: Blocked/Failed - max sessions reached or error.
            2: Paused - user interrupted.
        """
        orc = self._orc
        run_start_time = time.time()

        # Load state with recovery.  A StateValidationError signals deliberate
        # schema incompatibility — surfaced directly rather than silently
        # restoring an older backup (which would destroy forward-schema fields).
        try:
            state = orc.state_manager.load_state()
        except StateValidationError:
            raise
        except StateError as e:
            console.warning(f"State loading error: {e.message}")
            # Route through orc.* so patch.object on orchestrator intercepts it.
            recovered = orc._attempt_state_recovery()
            if recovered:
                console.success("State recovered from backup")
                state = recovered
            else:
                from .orchestrator_errors import StateRecoveryError

                raise StateRecoveryError("State file corrupted", e) from e

        # Reset CI poll timer when resuming a paused run mid-CI-wait so the
        # timeout doesn't fire immediately (timer restarts on next stage entry).
        if state.workflow_stage in ("waiting_ci", "waiting_reviews") and (
            state.ci_poll_start_time is not None
        ):
            state.ci_poll_start_time = None
            orc.state_manager.save_state_merged(state)

        # Check max sessions before doing anything else.
        if state.options.max_sessions and state.session_count >= state.options.max_sessions:
            console.warning(
                MaxSessionsReachedError(state.options.max_sessions, state.session_count).message
            )
            self._emit_run_completed(state, 1, "blocked", run_start_time, "Max sessions reached")
            orc._drain_webhooks()
            return 1

        # Emit run.started.
        is_resumed = state.session_count > 0
        pr_mode = "per-task" if state.options.pr_per_task else "per-group"
        goal = ""
        try:
            goal = orc.state_manager.load_goal()
        except Exception:
            pass
        working_directory = str(orc.state_manager.state_dir.parent)

        orc.webhook_emitter.emit(
            "run.started",
            goal=goal,
            working_directory=working_directory,
            max_sessions=state.options.max_sessions,
            auto_merge=state.options.auto_merge,
            pr_mode=pr_mode,
            resumed=is_resumed,
        )

        # Setup signal handlers and key listener.
        register_handlers()
        reset_shutdown()
        start_listening()
        console.detail("Press [Escape] to pause, [Ctrl+C] to interrupt")

        set_durable_stop_check(orc.control_channel.stop_requested)

        def _handle_pause(reason: str) -> int:
            stop_listening()
            unregister_handlers()
            console.newline()
            console.warning(f"{reason} - pausing...")
            orc.tracker.end_session(outcome="cancelled")
            previous_status = state.status
            state.status = "paused"
            self._emit_status_changed(previous_status, "paused", state, reason)
            orc.state_manager.save_state_merged(state)
            console.newline()
            console.info(orc.tracker.get_cost_report())
            console.info("Use 'claudetm resume' to continue")
            self._emit_run_completed(state, 2, "interrupted", run_start_time, reason)
            return 2

        def _handle_stop(reason: str) -> int:
            stop_listening()
            unregister_handlers()
            console.newline()
            console.warning(f"{reason} - stopping...")
            orc.tracker.end_session(outcome="cancelled")
            previous_status = state.status
            state.status = "stopped"
            self._emit_status_changed(previous_status, "stopped", state, reason)
            orc.state_manager.save_state_merged(state)
            console.newline()
            console.info(orc.tracker.get_cost_report())
            console.info("Use 'claudetm resume' to continue")
            self._emit_run_completed(state, 2, "interrupted", run_start_time, reason)
            return 2

        try:
            console.detail(
                f"Checking completion: task_index={state.current_task_index}, "
                f"is_all_complete={orc.task_runner.is_all_complete(state)}"
            )
            while not orc.task_runner.is_all_complete(state):
                # Durable cross-process control check.
                control_request = orc.control_channel.read()
                if control_request is not None:
                    orc.control_channel.clear()
                    if control_request.action == "stop":
                        return _handle_stop(control_request.reason or "Stop requested")
                    return _handle_pause(control_request.reason or "Pause requested")

                # In-process cancellation (Escape / SIGINT / durable stop).
                if is_cancellation_requested():
                    if orc.control_channel.stop_requested():
                        orc.control_channel.clear()
                        return _handle_stop(get_cancellation_reason() or "Stop requested")
                    reason = get_cancellation_reason() or "Cancellation requested"
                    if reason == "escape":
                        reason = "Escape pressed"
                    return _handle_pause(reason)

                # Stall check.
                should_abort, abort_reason = orc.tracker.should_abort()
                if should_abort:
                    console.warning(f"Execution issue: {abort_reason}")
                    previous_status = state.status
                    state.status = "blocked"
                    self._emit_status_changed(previous_status, "blocked", state, abort_reason)
                    orc.state_manager.save_state_merged(state)
                    stop_listening()
                    unregister_handlers()
                    console.info(orc.tracker.get_cost_report())
                    self._emit_run_completed(state, 1, "blocked", run_start_time, abort_reason)
                    return 1

                # Route through orc.* so patch.object on orchestrator intercepts it.
                result = orc._run_workflow_cycle(state)
                if result is not None:
                    stop_listening()
                    unregister_handlers()
                    console.info(orc.tracker.get_cost_report())
                    result_str = {0: "success", 2: "interrupted"}.get(result, "blocked")
                    self._emit_run_completed(state, result, result_str, run_start_time)
                    return result

                console.detail(
                    f"After cycle: task_index={state.current_task_index}, "
                    f"stage={state.workflow_stage}, "
                    f"is_all_complete={orc.task_runner.is_all_complete(state)}"
                )

                # Session limit check.
                if (
                    state.options.max_sessions
                    and state.session_count >= state.options.max_sessions
                ):
                    console.warning(f"Max sessions ({state.options.max_sessions}) reached")
                    previous_status = state.status
                    state.status = "blocked"
                    self._emit_status_changed(
                        previous_status, "blocked", state, "Max sessions reached"
                    )
                    orc.state_manager.save_state_merged(state)
                    stop_listening()
                    unregister_handlers()
                    console.info(orc.tracker.get_cost_report())
                    self._emit_run_completed(
                        state, 1, "blocked", run_start_time, "Max sessions reached"
                    )
                    return 1

            # ---- All tasks complete ----
            stop_listening()
            unregister_handlers()

            if not state.options.enable_verification:
                self._checkout_to_main()
                previous_status = state.status
                state.status = "success"
                self._emit_status_changed(
                    previous_status,
                    "success",
                    state,
                    "All tasks completed (final verification disabled)",
                )
                orc.state_manager.save_state_merged(state)
                console.success(
                    "All tasks completed! (Final verification skipped — pass --verify to enable.)"
                )
                console.info(orc.tracker.get_cost_report())
                self._emit_run_completed(state, 0, "success", run_start_time)
                orc.state_manager.cleanup_on_success(state.run_id)
                return 0

            max_fix_attempts = 3
            fix_attempt = 0

            while fix_attempt <= max_fix_attempts:
                verification = self._verify_success(state)

                if verification["success"]:
                    self._checkout_to_main()
                    previous_status = state.status
                    state.status = "success"
                    self._emit_status_changed(
                        previous_status, "success", state, "All tasks completed successfully"
                    )
                    orc.state_manager.save_state_merged(state)
                    console.success("All tasks completed successfully!")
                    console.info(orc.tracker.get_cost_report())
                    self._emit_run_completed(state, 0, "success", run_start_time)
                    orc.state_manager.cleanup_on_success(state.run_id)
                    return 0

                console.warning("Success criteria verification failed")

                if fix_attempt >= max_fix_attempts:
                    console.error(f"Max fix attempts ({max_fix_attempts}) reached")
                    previous_status = state.status
                    state.status = "blocked"
                    self._emit_status_changed(
                        previous_status, "blocked", state, "Max fix attempts reached"
                    )
                    orc.state_manager.save_state_merged(state)
                    console.info(orc.tracker.get_cost_report())
                    self._emit_run_completed(
                        state, 1, "blocked", run_start_time, "Max fix attempts reached"
                    )
                    return 1

                console.info(f"Attempting fix {fix_attempt + 1}/{max_fix_attempts}...")

                if not self._run_verification_fix(str(verification["details"]), state):
                    console.error("Fix attempt failed")
                    previous_status = state.status
                    state.status = "blocked"
                    self._emit_status_changed(
                        previous_status, "blocked", state, "Verification fix failed"
                    )
                    orc.state_manager.save_state_merged(state)
                    console.info(orc.tracker.get_cost_report())
                    self._emit_run_completed(
                        state, 1, "failed", run_start_time, "Verification fix failed"
                    )
                    return 1

                if not self._wait_for_fix_pr_merge(state):
                    console.error("Fix PR merge failed")
                    previous_status = state.status
                    state.status = "blocked"
                    self._emit_status_changed(
                        previous_status, "blocked", state, "Fix PR merge failed"
                    )
                    orc.state_manager.save_state_merged(state)
                    console.info(orc.tracker.get_cost_report())
                    self._emit_run_completed(
                        state, 1, "blocked", run_start_time, "Fix PR merge failed"
                    )
                    return 1

                fix_attempt += 1
                console.info("Fix PR merged - re-verifying...")

            # Should not reach here.
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(
                previous_status, "blocked", state, "Unexpected exit from verification loop"
            )
            orc.state_manager.save_state_merged(state)
            console.info(orc.tracker.get_cost_report())
            self._emit_run_completed(
                state, 1, "blocked", run_start_time, "Unexpected exit from verification loop"
            )
            return 1

        except KeyboardInterrupt:
            return _handle_pause("Interrupted (Ctrl+C)")
        except OrchestratorError as e:
            stop_listening()
            unregister_handlers()
            console.error(f"Orchestrator error: {e.message}")
            previous_status = state.status
            state.status = "failed"
            self._emit_status_changed(previous_status, "failed", state, e.message)
            try:
                orc.state_manager.save_state_merged(state)
            except Exception:
                pass
            self._emit_run_completed(state, 1, "failed", run_start_time, e.message)
            return 1
        except Exception as e:
            stop_listening()
            unregister_handlers()
            console.error(f"Unexpected error: {type(e).__name__}: {e}")
            previous_status = state.status
            state.status = "failed"
            error_message = f"{type(e).__name__}: {e}"
            self._emit_status_changed(previous_status, "failed", state, error_message)
            try:
                orc.state_manager.save_state_merged(state)
            except Exception:
                pass
            self._emit_run_completed(state, 1, "failed", run_start_time, error_message)
            return 1
        finally:
            set_durable_stop_check(None)
            orc._drain_webhooks()

    # ------------------------------------------------------------------
    # Workflow cycle
    # ------------------------------------------------------------------

    def _run_workflow_cycle(self, state: TaskState) -> int | None:
        """Run one cycle of the PR workflow."""
        orc = self._orc
        if state.workflow_stage is None:
            state.workflow_stage = "working"
            orc.state_manager.save_state_merged(state)

        stage = state.workflow_stage

        try:
            if stage == "working":
                # Route through orc.* so patch.object on orchestrator intercepts it.
                return orc._handle_working_stage(state)
            elif stage == "pr_created":
                pr_before = state.current_pr
                result = orc.stage_handler.handle_pr_created_stage(state)
                if state.current_pr and state.current_pr != pr_before:
                    self._emit_pr_created_event(state)
                return result
            elif stage == "waiting_ci":
                return orc.stage_handler.handle_waiting_ci_stage(state)
            elif stage == "ci_failed":
                return orc.stage_handler.handle_ci_failed_stage(state)
            elif stage == "waiting_reviews":
                return orc.stage_handler.handle_waiting_reviews_stage(state)
            elif stage == "addressing_reviews":
                return orc.stage_handler.handle_addressing_reviews_stage(state)
            elif stage == "ready_to_merge":
                stage_before = state.workflow_stage
                result = orc.stage_handler.handle_ready_to_merge_stage(state)
                if state.workflow_stage == "merged" and stage_before == "ready_to_merge":
                    self._emit_pr_merged_event(state)
                return result
            elif stage == "merged":
                return orc.stage_handler.handle_merged_stage(
                    state,
                    orc.task_runner.mark_task_complete,
                    self._emit_pr_merged_event,
                )
            elif stage == "releasing":
                return orc.stage_handler.handle_releasing_stage(state)
            elif stage == "release_fix":
                return orc.stage_handler.handle_release_fix_stage(state)
            else:
                console.warning(f"Unknown stage: {stage}, resetting")
                state.workflow_stage = "working"
                orc.state_manager.save_state_merged(state)
                return None

        except NoPlanFoundError as e:
            console.error(e.message)
            previous_status = state.status
            state.status = "failed"
            self._emit_status_changed(previous_status, "failed", state, e.message)
            orc.state_manager.save_state_merged(state)
            return 1
        except NoTasksFoundError:
            return None
        except ContentFilterError as e:
            console.error(f"Content filter: {e.message}")
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(
                previous_status, "blocked", state, f"Content filter: {e.message}"
            )
            orc.state_manager.save_state_merged(state)
            return 1
        except CircuitBreakerError as e:
            console.warning(f"Circuit breaker: {e.message}")
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(
                previous_status, "blocked", state, f"Circuit breaker: {e.message}"
            )
            orc.state_manager.save_state_merged(state)
            return 1
        except ConsecutiveFailuresError as e:
            console.error(f"Consecutive failures: {e.message}")
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(
                previous_status, "blocked", state, f"Consecutive failures: {e.message}"
            )
            orc.state_manager.save_state_merged(state)
            return 1
        except AgentError as e:
            console.error(f"Agent error: {e.message}")
            raise WorkSessionError(
                state.current_task_index,
                orc.task_runner.get_current_task_description(state),
                e,
            ) from e

    # ------------------------------------------------------------------
    # Working stage
    # ------------------------------------------------------------------

    def _handle_working_stage(self, state: TaskState) -> int | None:
        """Handle the working stage — implement the current task."""
        orc = self._orc
        task_desc = orc.task_runner.get_current_task_description(state)
        total_tasks = self._get_total_tasks(state)
        current_branch = self._get_current_branch()
        session_start_time = time.time()

        if state.task_start_time is None:
            state.task_start_time = datetime.now()
            orc.state_manager.save_state_merged(state)

        orc.tracker.start_session(
            session_id=state.session_count + 1,
            task_index=state.current_task_index,
            task_description=task_desc,
        )

        if orc.logger:
            orc.logger.start_session(state.session_count + 1, "working")

        orc.webhook_emitter.emit(
            "session.started",
            session_number=state.session_count + 1,
            max_sessions=state.options.max_sessions,
            task_index=state.current_task_index,
            task_description=task_desc,
            phase="working",
        )

        orc.webhook_emitter.emit(
            "task.started",
            task_index=state.current_task_index,
            task_description=task_desc,
            total_tasks=total_tasks,
            branch=current_branch,
        )

        outcome = "completed"
        error_message = None
        error_type = None
        completed_task_index = state.current_task_index
        session_result: str | None = None
        try:
            session_result = orc.task_runner.run_work_session(state)
        except Exception as e:
            outcome = "failed"
            error_message = str(e)
            error_type = type(e).__name__
            orc.tracker.record_error()
            raise
        finally:
            session_duration = time.time() - session_start_time
            if session_result == "skipped_already_complete":
                outcome = "skipped"
            mp = getattr(orc.agent, "_message_processor", None)
            if mp is not None:
                cost_usd = getattr(mp, "last_total_cost_usd", None)
                if isinstance(cost_usd, float):
                    orc.tracker.record_cost(
                        cost_usd=cost_usd,
                        tokens_in=int(getattr(mp, "last_input_tokens", 0) or 0),
                        tokens_out=int(getattr(mp, "last_output_tokens", 0) or 0),
                    )
            orc.tracker.end_session(outcome=outcome)
            if orc.logger:
                orc.logger.end_session(outcome)

            orc.webhook_emitter.emit(
                "session.completed",
                session_number=state.session_count + 1,
                max_sessions=state.options.max_sessions,
                task_index=state.current_task_index,
                task_description=task_desc,
                phase="working",
                duration_seconds=session_duration,
                result=outcome,
            )

            if outcome == "failed":
                orc.webhook_emitter.emit(
                    "task.failed",
                    task_index=state.current_task_index,
                    task_description=task_desc,
                    error_message=error_message or "Unknown error",
                    error_type=error_type,
                    duration_seconds=session_duration,
                    branch=current_branch,
                    recoverable=True,
                )

        if session_result == "skipped_already_complete":
            console.info(f"Task #{completed_task_index + 1} already complete - skipping")
            orc.state_manager.save_state_merged(state)
            return None

        orc.tracker.record_task_progress(state.current_task_index)
        reset_escape()

        state.session_count += 1
        state.pr_active_work_seconds += session_duration

        plan = orc.state_manager.load_plan()
        if plan:
            orc.task_runner.mark_task_complete(plan, completed_task_index)
            console.success(f"Task #{completed_task_index + 1} marked complete in plan.md")

        if state.task_start_time:
            task_duration_seconds = (datetime.now() - state.task_start_time).total_seconds()
        else:
            task_duration_seconds = session_duration

        if orc.logger:
            orc.logger.log_task_timing(state.current_task_index, task_duration_seconds)
        console.info(
            f"Task #{completed_task_index + 1} took {task_duration_seconds / 60:.1f} minutes"
        )

        self._accumulate_context(state)

        completed_tasks = self._get_completed_tasks(state)
        orc.webhook_emitter.emit(
            "task.completed",
            task_index=state.current_task_index,
            task_description=task_desc,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            duration_seconds=task_duration_seconds if state.task_start_time else session_duration,
            branch=current_branch,
        )

        logger.debug("Checking mailbox after task %d completion", state.current_task_index)
        plan_updated = orc._check_and_process_mailbox(state)
        if plan_updated:
            old_total = total_tasks
            total_tasks = self._get_total_tasks(state)
            logger.info(
                "Plan updated from mailbox: old_total_tasks=%d, new_total_tasks=%d",
                old_total,
                total_tasks,
            )
            console.detail(f"Plan updated - new total tasks: {total_tasks}")

        if state.options.pr_per_task:
            state.workflow_stage = "pr_created"
        else:
            if orc.task_runner.is_last_task_in_group(state):
                state.workflow_stage = "pr_created"
            else:
                console.info("More tasks in PR group - continuing without creating PR")
                state.current_task_index += 1
                state.workflow_stage = "working"
                state.task_start_time = None

        orc.task_runner.update_progress(state)
        orc.state_manager.save_state_merged(state)

        should_abort, abort_reason = orc.tracker.should_abort()
        if should_abort:
            console.warning(f"Execution issue: {abort_reason}")
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(previous_status, "blocked", state, abort_reason)
            orc.state_manager.save_state_merged(state)
            return 1

        return None

    # ------------------------------------------------------------------
    # State recovery
    # ------------------------------------------------------------------

    def _attempt_state_recovery(self) -> TaskState | None:
        """Attempt to recover state from the newest non-stale backup.

        Returns:
            The recovered TaskState, or None if no fresh-enough backup exists.
        """
        orc = self._orc
        try:
            reference_time: datetime | None = None
            state_file = orc.state_manager.state_file
            if state_file.exists():
                try:
                    reference_time = datetime.fromtimestamp(state_file.stat().st_mtime)
                except OSError:
                    reference_time = None
            return orc.state_manager.find_recoverable_state(reference_time)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Verification helpers
    # ------------------------------------------------------------------

    def _verify_success(self, state: TaskState) -> dict[str, object]:
        """Verify success criteria are met.

        Args:
            state: Current task state (used to summarise completed tasks/PRs).

        Returns:
            Dict with ``'success'`` (bool) and ``'details'`` (str) keys.
        """
        orc = self._orc
        criteria = orc.state_manager.load_criteria()
        if not criteria:
            return {"success": True, "details": "No criteria specified"}

        context = orc.state_manager.load_context()
        tasks_summary = self._build_completed_tasks_summary(state)
        result = orc.agent.verify_success_criteria(
            criteria=criteria, context=context, tasks_summary=tasks_summary
        )
        return {
            "success": bool(result.get("success", False)),
            "details": result.get("details", ""),
        }

    def _get_target_branch(self) -> str:
        """Return the configured target branch (main/master/etc.)."""
        config = get_config()
        return config.git.target_branch

    def _checkout_to_main(self) -> bool:
        """Checkout to the configured target branch.

        Returns:
            True if checkout succeeded, False otherwise.
        """
        target_branch = self._get_target_branch()
        console.info(f"Checking out to {target_branch}...")
        try:
            subprocess.run(
                ["git", "checkout", target_branch],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "pull"],
                check=True,
                capture_output=True,
                text=True,
            )
            console.success(f"Switched to {target_branch}")
            return True
        except subprocess.CalledProcessError as e:
            console.warning(f"Failed to checkout to {target_branch}: {e}")
            return False

    def _run_verification_fix(self, verification_details: str, state: TaskState) -> bool:
        """Run agent to fix verification failures and create a PR.

        Args:
            verification_details: Details of what failed during verification.
            state: Current task state.

        Returns:
            True if fix was attempted (PR created or at least committed).
        """
        orc = self._orc
        console.info("Running agent to fix verification failures...")
        criteria = orc.state_manager.load_criteria() or ""
        context = orc.state_manager.load_context()

        task_description = f"""Verification of success criteria has FAILED.

**Success Criteria:**
{criteria}

**Verification Result:**
{verification_details}

**Your Task:**
1. Read the verification details carefully to understand what failed
2. Fix all issues identified in the verification
3. Run tests/lint locally to verify the fixes work
4. Commit your changes with a descriptive message
5. Push to a new branch and create a PR

IMPORTANT: You must fix ALL verification failures, not just some of them.
After fixing everything, run the tests again to confirm they pass.

After completing your fixes, end with: TASK COMPLETE"""

        try:
            coding_style = orc.state_manager.load_coding_style()
            orc.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=ModelType.OPUS,
                create_pr=True,
                coding_style=coding_style,
            )
            state.session_count += 1
            orc.state_manager.save_state_merged(state)
            return True
        except Exception as e:
            console.error(f"Fix session failed: {e}")
            return False

    def _wait_for_fix_pr_merge(self, state: TaskState) -> bool:
        """Wait for fix PR to pass CI and merge it.

        Attempts to fix CI failures (up to 2 retries) before giving up.

        Args:
            state: Current task state.

        Returns:
            True if PR was merged successfully.
        """
        orc = self._orc
        try:
            pr_number = orc.github_client.get_pr_for_current_branch()
            if not pr_number:
                console.warning("No PR found for fix branch")
                return False
            console.success(f"Fix PR #{pr_number} detected")
            state.current_pr = pr_number
            if state.pr_start_time is None:
                state.pr_start_time = datetime.now()
            orc.state_manager.save_state_merged(state)
        except Exception as e:
            console.warning(f"Could not detect fix PR: {e}")
            return False

        max_ci_fix_attempts = 2
        ci_fix_attempt = 0

        while ci_fix_attempt <= max_ci_fix_attempts:
            # Route through orc.* so patch.object on orchestrator intercepts it.
            ci_result = orc._poll_fix_pr_ci(pr_number, state)

            if ci_result == "success":
                break
            elif ci_result == "failure":
                ci_fix_attempt += 1
                if ci_fix_attempt > max_ci_fix_attempts:
                    console.error(f"Fix PR CI failed after {ci_fix_attempt - 1} fix attempts")
                    return False
                console.info(
                    f"Attempting to fix CI failure ({ci_fix_attempt}/{max_ci_fix_attempts})..."
                )
                # Route through orc.* so patch.object on orchestrator intercepts it.
                if not orc._fix_pr_ci_failure(pr_number, state):
                    console.error("Failed to fix CI issues")
                    return False
                console.info("Waiting 60s for CI to restart...")
                if not interruptible_sleep(60):
                    return False
            else:
                return False

        if state.options.auto_merge:
            try:
                console.info(f"Merging fix PR #{pr_number}...")
                orc.github_client.merge_pr(pr_number, admin=state.options.admin_merge)
                console.success(f"Fix PR #{pr_number} merged!")
                self._checkout_to_main()
                return True
            except Exception as e:
                console.error(f"Failed to merge fix PR: {e}")
                return False
        else:
            console.info(f"Fix PR #{pr_number} ready to merge (auto_merge disabled)")
            console.detail("Merge manually then run 'claudetm resume'")
            return False

    def _poll_fix_pr_ci(self, pr_number: int, state: TaskState) -> str:
        """Poll CI status for a fix PR.

        Args:
            pr_number: The PR number to check.
            state: Current task state.

        Returns:
            ``"success"``, ``"failure"``, or ``"interrupted"``.
        """
        orc = self._orc
        max_wait = 7200
        poll_interval = 10
        waited = 0

        while waited < max_wait:
            try:
                pr_status = orc.github_client.get_pr_status(pr_number)
                if pr_status.ci_state == "SUCCESS":
                    console.success("Fix PR CI passed!")
                    return "success"
                elif pr_status.ci_state in ("FAILURE", "ERROR"):
                    console.warning("Fix PR CI failed")
                    return "failure"
                else:
                    console.info(
                        f"Waiting for fix PR CI... ({pr_status.checks_pending} pending)"
                    )
                    if not interruptible_sleep(poll_interval):
                        return "interrupted"
                    waited += poll_interval
            except Exception as e:
                console.warning(f"Error checking CI: {e}")
                if not interruptible_sleep(poll_interval):
                    return "interrupted"
                waited += poll_interval

        console.warning("Timed out waiting for fix PR CI")
        return "interrupted"

    def _fix_pr_ci_failure(self, pr_number: int, state: TaskState) -> bool:
        """Fix CI failures on a fix PR.

        Args:
            pr_number: The PR number with failing CI.
            state: Current task state.

        Returns:
            True if fix session completed successfully.
        """
        orc = self._orc
        try:
            orc.pr_context.save_ci_failures(pr_number)
            has_ci, has_comments, pr_dir_path = orc.pr_context.get_combined_feedback(pr_number)

            if not has_ci and not has_comments:
                console.warning("No CI failures or comments found to fix")
                return False

            ci_path = (
                f"{pr_dir_path}/ci/" if pr_dir_path else ".claude-task-master/debugging/"
            )

            task_description = f"""
Fix PR CI Failure

The CI checks have failed for this fix PR. Your task is to:

1. Read the CI failure logs in `{ci_path}`
2. Understand what tests/lints are failing
3. Fix the issues in the codebase
4. Run tests locally to verify fixes (check package.json, Makefile, or pyproject.toml for test commands)
5. Commit and push the fixes

Important:
- Only fix issues identified in the CI logs
- Run tests locally before committing
- Push changes to trigger a new CI run
"""

            context = orc.state_manager.load_context()
            coding_style = orc.state_manager.load_coding_style()
            # Route through orc.* so patch.object on orchestrator intercepts it.
            current_branch = orc._get_current_branch()

            head_branch = None
            try:
                head_branch = orc.github_client.get_pr_status(pr_number).head_branch
            except Exception as e:
                console.warning(f"Could not fetch PR head branch: {e}")

            if head_branch and head_branch != current_branch:
                try:
                    subprocess.run(
                        ["git", "checkout", head_branch],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    console.info(f"Checked out PR branch {head_branch}")
                except Exception as e:
                    console.warning(f"Failed to checkout {head_branch}: {e}")

            orc.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=ModelType.OPUS,
                required_branch=head_branch or current_branch,
                coding_style=coding_style,
                create_pr=False,
                push_only=True,
            )

            state.session_count += 1
            orc.state_manager.save_state_merged(state)
            return True

        except Exception as e:
            console.error(f"Failed to fix CI issues: {e}")
            return False

    # ------------------------------------------------------------------
    # Webhook emit helpers
    # ------------------------------------------------------------------

    def _emit_pr_created_event(self, state: TaskState) -> None:
        """Emit a pr.created webhook event and increment prs_created counter.

        Args:
            state: Current task state with PR information.
        """
        orc = self._orc
        if not state.current_pr:
            return
        if state.last_counted_pr_created == state.current_pr:
            return

        state.prs_created += 1
        state.last_counted_pr_created = state.current_pr
        orc.state_manager.save_state_merged(state)

        pr_url = ""
        pr_title = ""
        base_branch = "main"
        try:
            pr_status = orc.github_client.get_pr_status(state.current_pr)
            pr_url = pr_status.url
            pr_title = pr_status.title
            base_branch = pr_status.base_branch
        except Exception:
            pass

        orc.webhook_emitter.emit(
            "pr.created",
            pr_number=state.current_pr,
            pr_url=pr_url,
            pr_title=pr_title,
            branch=self._get_current_branch() or "",
            base_branch=base_branch,
            tasks_included=1,
        )

    def _emit_pr_merged_event(self, state: TaskState) -> None:
        """Emit a pr.merged webhook event and increment prs_merged counter.

        Args:
            state: Current task state with PR information.
        """
        orc = self._orc
        if not state.current_pr:
            return
        if state.last_counted_pr_merged == state.current_pr:
            return

        state.prs_merged += 1
        state.last_counted_pr_merged = state.current_pr
        orc.state_manager.save_state_merged(state)

        pr_url = ""
        pr_title = ""
        base_branch = "main"
        merged_at = None
        try:
            pr_status = orc.github_client.get_pr_status(state.current_pr)
            pr_url = pr_status.url
            pr_title = pr_status.title
            base_branch = pr_status.base_branch
            merged_at = getattr(pr_status, "merged_at", None)
        except Exception:
            pass

        orc.webhook_emitter.emit(
            "pr.merged",
            pr_number=state.current_pr,
            pr_url=pr_url,
            pr_title=pr_title,
            branch=self._get_current_branch() or "",
            base_branch=base_branch,
            merged_at=merged_at,
            auto_merged=state.options.auto_merge,
        )

    def _emit_status_changed(
        self,
        previous_status: str,
        new_status: str,
        state: TaskState,
        reason: str | None = None,
    ) -> None:
        """Emit a status.changed webhook event when status transitions.

        Args:
            previous_status: The status before the change.
            new_status: The status after the change.
            state: Current task state.
            reason: Optional reason for the status change.
        """
        if previous_status == new_status:
            return
        self._orc.webhook_emitter.emit(
            "status.changed",
            previous_status=previous_status,
            new_status=new_status,
            reason=reason,
            task_index=state.current_task_index,
            session_number=state.session_count,
        )

    def _emit_run_completed(
        self,
        state: TaskState,
        exit_code: int,
        result: str,
        run_start_time: float,
        error_message: str | None = None,
    ) -> None:
        """Emit a run.completed webhook event.

        Args:
            state: Current task state.
            exit_code: Exit code (0=success, 1=blocked, 2=interrupted).
            result: Outcome string.
            run_start_time: ``time.time()`` value when the run started.
            error_message: Error message if run failed.
        """
        orc = self._orc
        goal = ""
        try:
            goal = orc.state_manager.load_goal()
        except Exception:
            pass

        total_tasks = self._get_total_tasks(state)
        completed_tasks = self._get_completed_tasks(state)
        duration_seconds = time.time() - run_start_time if run_start_time > 0 else None

        orc.webhook_emitter.emit(
            "run.completed",
            goal=goal,
            result=result,
            exit_code=exit_code,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            total_sessions=state.session_count,
            duration_seconds=duration_seconds,
            prs_created=state.prs_created,
            prs_merged=state.prs_merged,
            final_status=state.status,
            error_message=error_message,
        )

    # ------------------------------------------------------------------
    # Data helpers used across multiple methods
    # ------------------------------------------------------------------

    def _get_total_tasks(self, state: TaskState) -> int:
        """Return total task count from the plan."""
        try:
            plan = self._orc.state_manager.load_plan()
            if plan:
                tasks = parse_task_descriptions(plan)
                return len(tasks)
        except Exception:
            pass
        return 0

    def _get_completed_tasks(self, state: TaskState) -> int:
        """Return completed task count from the plan.

        Falls back to ``state.current_task_index`` when the plan is unavailable.
        """
        try:
            plan = self._orc.state_manager.load_plan()
            if plan:
                return count_completed_tasks(plan)
        except Exception:
            pass
        return state.current_task_index

    def _accumulate_context(self, state: TaskState) -> None:
        """Distil the just-finished work session into context.md.

        Best-effort: failures are logged and swallowed. KeyboardInterrupt
        still propagates so Ctrl+C interrupts the run.

        Args:
            state: Current task state (``session_count`` already incremented).
        """
        orc = self._orc
        session_output = getattr(orc.task_runner, "last_session_output", "") or ""
        if not session_output.strip():
            return
        try:
            existing_context = orc.context_accumulator.get_context_for_prompt()
            learnings = orc.agent.extract_session_learnings(
                session_output=session_output,
                existing_context=existing_context,
            )
            if learnings.strip():
                orc.context_accumulator.add_session_summary(state.session_count, learnings.strip())
                console.detail(f"context.md updated from session {state.session_count}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.warning("Context accumulation failed (non-fatal): %s", e)
            console.detail(f"Context accumulation skipped (non-fatal): {e}")

    def _build_completed_tasks_summary(self, state: TaskState) -> str:
        """Summarise completed tasks + merged PRs for the verification prompt.

        Args:
            state: Current task state.

        Returns:
            Markdown bullet list, or ``""`` when nothing is available.
        """
        orc = self._orc
        lines: list[str] = []
        try:
            plan = orc.state_manager.load_plan()
            if plan:
                lines.extend(
                    f"- {desc}"
                    for index, desc in enumerate(parse_task_descriptions(plan))
                    if is_task_complete(plan, index)
                )
        except Exception:
            pass

        if state.prs_created or state.prs_merged:
            pr_line = f"- PRs: {state.prs_created} created, {state.prs_merged} merged"
            if state.last_counted_pr_merged is not None:
                pr_line += f" (last merged: #{state.last_counted_pr_merged})"
            lines.append(pr_line)

        return "\n".join(lines)

    @staticmethod
    def _get_current_branch() -> str | None:
        """Return the current git branch name, or None if not in a git repo."""
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() or None
        except Exception:
            return None
