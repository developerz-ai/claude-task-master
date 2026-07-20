"""Webhook-emit helpers for OrchestratorLoop.

Mixin providing ``_emit_pr_created_event``, ``_emit_pr_merged_event``,
``_emit_status_changed``, and ``_emit_run_completed``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .state import TaskState

if TYPE_CHECKING:
    from .orchestrator import WorkLoopOrchestrator


class _LoopEmitterMixin:
    """Mixin that provides webhook-emit helpers to OrchestratorLoop.

    Cross-mixin calls to ``_get_current_branch``, ``_get_total_tasks``, and
    ``_get_completed_tasks`` are resolved at runtime via MRO on the concrete
    ``OrchestratorLoop`` class (which inherits from ``_LoopContextMixin``).
    """

    _orc: WorkLoopOrchestrator  # set by OrchestratorLoop.__init__

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
            branch=self._get_current_branch() or "",  # type: ignore[attr-defined]
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
            branch=self._get_current_branch() or "",  # type: ignore[attr-defined]
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

        total_tasks = self._get_total_tasks(state)  # type: ignore[attr-defined]
        completed_tasks = self._get_completed_tasks(state)  # type: ignore[attr-defined]
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


__all__ = ["_LoopEmitterMixin"]
