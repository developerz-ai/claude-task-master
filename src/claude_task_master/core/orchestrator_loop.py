"""OrchestratorLoop — main task execution loop extracted from orchestrator.py.

``WorkLoopOrchestrator.run()`` delegates its entire body here. The class is
assembled from four mixins that live in their own modules:
  - _LoopContextMixin   — context accumulation + git helpers
  - _LoopEmitterMixin   — webhook emit helpers
  - _LoopVerificationMixin — verification + fix-PR helpers
  - _LoopWorkingStageMixin — working-stage handler
"""

from __future__ import annotations

import logging
import subprocess  # noqa: F401 — re-exported so tests can patch orchestrator_loop.subprocess
import time
from datetime import datetime
from typing import TYPE_CHECKING

from . import console  # noqa: F401 — re-exported so tests can patch orchestrator_loop.console
from .agent_exceptions import AgentError, ConsecutiveFailuresError, ContentFilterError
from .circuit_breaker import CircuitBreakerError
from .config_loader import (
    get_config,  # noqa: F401 — re-exported so tests can patch orchestrator_loop.get_config
)
from .key_listener import (
    get_cancellation_reason,
    is_cancellation_requested,
    reset_escape,  # noqa: F401 — re-exported so tests can patch orchestrator_loop.reset_escape
    start_listening,
    stop_listening,
)
from .loop_context import _LoopContextMixin
from .loop_emitter import _LoopEmitterMixin
from .loop_verification import _LoopVerificationMixin
from .loop_working_stage import _LoopWorkingStageMixin
from .orchestrator_errors import MaxSessionsReachedError, OrchestratorError
from .shutdown import (
    interruptible_sleep,  # noqa: F401 — re-exported for tests to patch
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


class OrchestratorLoop(
    _LoopContextMixin,
    _LoopEmitterMixin,
    _LoopVerificationMixin,
    _LoopWorkingStageMixin,
):
    """Drives the main work loop for :class:`WorkLoopOrchestrator`.

    Instantiated fresh on each :meth:`WorkLoopOrchestrator.run` call so it
    carries no mutable state between runs on the same orchestrator instance.
    All persistent state lives on the injected ``orc`` reference.
    """

    def __init__(self, orc: WorkLoopOrchestrator) -> None:
        self._orc = orc

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
