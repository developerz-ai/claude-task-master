"""Working-stage handler mixin for OrchestratorLoop.

Mixin providing ``_handle_working_stage`` — the logic for implementing
the current task via an agent work session and transitioning state.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING

from . import console
from .state import TaskState

if TYPE_CHECKING:
    from .orchestrator import WorkLoopOrchestrator


class _LoopWorkingStageMixin:
    """Mixin that provides the working-stage handler to OrchestratorLoop.

    Cross-mixin calls to ``_accumulate_context``, ``_get_current_branch``,
    ``_get_total_tasks``, ``_get_completed_tasks``, and ``_emit_status_changed``
    are resolved at runtime via MRO on the concrete ``OrchestratorLoop`` class.
    """

    _orc: WorkLoopOrchestrator  # set by OrchestratorLoop.__init__

    # ------------------------------------------------------------------

    def _handle_working_stage(self, state: TaskState) -> int | None:
        """Handle the working stage — implement the current task.

        Args:
            state: Current mutable task state.

        Returns:
            1 if the run should be aborted (stall detected), None to continue.
        """
        orc = self._orc
        task_desc = orc.task_runner.get_current_task_description(state)
        total_tasks = self._get_total_tasks(state)  # type: ignore[attr-defined]
        current_branch = self._get_current_branch()  # type: ignore[attr-defined]
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
        # Import deferred to avoid circular imports; allows tests to patch
        # claude_task_master.core.orchestrator_loop.reset_escape correctly.
        import claude_task_master.core.orchestrator_loop as _oloop  # noqa: PLC0415

        _oloop.reset_escape()

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

        self._accumulate_context(state)  # type: ignore[attr-defined]

        completed_tasks = self._get_completed_tasks(state)  # type: ignore[attr-defined]
        orc.webhook_emitter.emit(
            "task.completed",
            task_index=state.current_task_index,
            task_description=task_desc,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            duration_seconds=task_duration_seconds if state.task_start_time else session_duration,
            branch=current_branch,
        )

        import logging

        logger = logging.getLogger(__name__)
        logger.debug("Checking mailbox after task %d completion", state.current_task_index)
        plan_updated = orc._check_and_process_mailbox(state)
        if plan_updated:
            old_total = total_tasks
            total_tasks = self._get_total_tasks(state)  # type: ignore[attr-defined]
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
            self._emit_status_changed(previous_status, "blocked", state, abort_reason)  # type: ignore[attr-defined]
            orc.state_manager.save_state_merged(state)
            return 1

        return None


__all__ = ["_LoopWorkingStageMixin"]
