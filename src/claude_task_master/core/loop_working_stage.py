"""Working-stage handler mixin for OrchestratorLoop.

Mixin providing ``_handle_working_stage`` — the logic for implementing
the current task via an agent work session and transitioning state.
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime
from typing import TYPE_CHECKING

from . import console
from .config_loader import get_config
from .state import TaskState
from .usage_limit import detect_usage_limit

if TYPE_CHECKING:
    from .orchestrator import WorkLoopOrchestrator

#: Max consecutive re-runs of the same task when its session ended without
#: satisfying the work contract (cut off by the SDK, or uncommitted changes left
#: behind). After this the task is checked off anyway and the PR stages take over
#: — ``_PRRecovery`` can still finish and ship a dirty tree, so a stubborn task
#: must not deadlock the run here.
MAX_TASK_FINISH_ATTEMPTS = 2


class _LoopWorkingStageMixin:
    """Mixin that provides the working-stage handler to OrchestratorLoop.

    Cross-mixin calls to ``_accumulate_context``, ``_get_current_branch``,
    ``_get_total_tasks``, ``_get_completed_tasks``, and ``_emit_status_changed``
    are resolved at runtime via MRO on the concrete ``OrchestratorLoop`` class.
    """

    _orc: WorkLoopOrchestrator  # set by OrchestratorLoop.__init__

    # ------------------------------------------------------------------

    def _session_unfinished_reason(self, session_result: str | None) -> str | None:
        """Return why the just-finished work session didn't satisfy its contract.

        Two independent signals, because neither alone catches both failures:

        - ``"ran_incomplete"`` — the SDK's terminal result was an error (max
          turns, budget cap, error_during_execution). The agent was cut off.
        - a dirty working tree — the session's own contract is "commit your
          work", so leftover changes mean it stopped mid-task even when the SDK
          reported a clean end_turn (an agent that ends its turn waiting on a
          background check looks perfectly healthy to the SDK). The state dir is
          git-excluded at init, so it never shows up here.

        Returns:
            A short reason string, or None when the session finished properly.
        """
        if session_result == "ran_incomplete":
            return "session was cut off"
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                # The project tree the run operates on — not the process cwd,
                # which a caller may have moved.
                cwd=str(self._orc.state_manager.state_dir.parent),
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            # Can't tell (no git, timeout, not a repo) — never invent an
            # unfinished session out of a failed probe.
            return None
        if result.stdout.strip():
            return "uncommitted changes left behind"
        return None

    def _ship_group_if_skipped_task_closed_it(self, state: TaskState, skipped_index: int) -> None:
        """Route to the PR stage when the task just skipped closed its PR group.

        A task already checked off in ``plan.md`` runs no session — but its
        group still has to ship. Its commits can already be on the branch (a
        resume after the session that did the work, a task checked off by the
        finish-attempt budget), and the PR stage is the only thing that opens a
        PR. Skipping straight into the next group strands them: the run keeps
        committing locally and never opens anything.

        ``run_work_session`` has already advanced the index past the skipped
        task, so rewind it — the PR stages act on the *last* task of the group,
        and ``handle_merged_stage`` advances past it once the PR lands. When
        nothing is shippable, ``_PRRecovery`` closes the group out without an
        agent session, so an all-complete plan still walks through cheaply.

        Args:
            state: Current mutable task state (index already advanced).
            skipped_index: Index of the task that was skipped.
        """
        orc = self._orc
        closes_group = state.options.pr_per_task or orc.task_runner.is_last_task_in_group(
            state, task_index=skipped_index
        )
        if not closes_group:
            return
        # Sitting on the base branch means no group work was committed here —
        # and the PR stage blocks on a base branch it cannot open a PR from.
        base = get_config().git.target_branch
        branch = self._get_current_branch()  # type: ignore[attr-defined]
        if not branch or branch == base:
            return
        console.info(
            f"Task #{skipped_index + 1} closed its PR group - checking the group has shipped"
        )
        state.current_task_index = skipped_index
        state.workflow_stage = "pr_created"
        state.task_start_time = None

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
            self._ship_group_if_skipped_task_closed_it(state, completed_task_index)
            orc.state_manager.save_state_merged(state)
            return None

        if session_result == "no_tasks_remaining":
            # The index is past the end of the plan — no session ran, so there is
            # nothing to check off and nothing to ship.
            console.detail("No tasks remaining in plan")
            orc.state_manager.save_state_merged(state)
            return None

        # A usage-limit refusal is an account condition, not a task failure:
        # the session never got to run, so nothing may be charged to the task.
        # The agent layer already waits limits out (usage_limit.
        # run_query_riding_out_usage_limits); a refusal that still reaches
        # here means that wait was interrupted or its budget ran out. Burning
        # ``task_finish_attempts`` on it once cascaded through a whole plan in
        # ninety seconds, checking off four untouched tasks as complete — so
        # the task simply re-enters the working stage instead. The heartbeat
        # matters: the progress clock was stamped at session *start*, which
        # may be hours ago if the agent layer waited inside the session.
        if session_result == "ran_incomplete":
            notice = detect_usage_limit(getattr(orc.task_runner, "last_session_output", "") or "")
            if notice is not None:
                console.warning(
                    f"Task #{completed_task_index + 1} session was refused by a usage limit "
                    f"({notice.message}) — not counted against the task; it will re-run"
                )
                orc.tracker.record_heartbeat()
                state.workflow_stage = "working"
                orc.state_manager.save_state_merged(state)
                return None

        unfinished = self._session_unfinished_reason(session_result)
        if unfinished and state.task_finish_attempts < MAX_TASK_FINISH_ATTEMPTS:
            state.task_finish_attempts += 1
            state.session_count += 1
            state.pr_active_work_seconds += session_duration
            console.warning(
                f"Task #{completed_task_index + 1} not finished ({unfinished}) — "
                f"retrying it (attempt {state.task_finish_attempts}/{MAX_TASK_FINISH_ATTEMPTS})"
            )
            state.workflow_stage = "working"
            orc.state_manager.save_state_merged(state)
            return None
        if unfinished:
            console.warning(
                f"Task #{completed_task_index + 1} still unfinished ({unfinished}) after "
                f"{state.task_finish_attempts} retries — moving on; the PR stage will "
                "finish and ship what is on the branch"
            )

        state.task_finish_attempts = 0
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
