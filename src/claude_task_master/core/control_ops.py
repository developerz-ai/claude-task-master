"""Control operation methods mixin for ControlManager (pause, resume, stop, etc.)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .control_types import (
    SESSION_RELEASE_TIMEOUT_SEC,
    ControlOperationNotAllowedError,
    ControlResult,
)

if TYPE_CHECKING:
    from .control_channel import ControlChannel
    from .shutdown import ShutdownManager
    from .state import StateManager

logger = logging.getLogger(__name__)


class _ControlOpsMixin:
    """Mixin providing pause, resume, stop, update_config, and get_status to ControlManager.

    Concrete attribute stubs satisfy mypy; values are provided by ControlManager.__init__.
    """

    state_manager: StateManager
    control_channel: ControlChannel
    shutdown_manager: ShutdownManager

    # Status-set stubs — concrete values defined on ControlManager
    PAUSABLE_STATUSES: frozenset[str]
    RESUMABLE_STATUSES: frozenset[str]
    STOPPABLE_STATUSES: frozenset[str]

    # Method stubs — real implementations in ControlManager
    def _ensure_task_exists(self, operation: str) -> None:
        """Ensure an active task exists."""
        raise NotImplementedError

    def _wait_for_session_release(self) -> bool:
        """Wait for session release before cleanup."""
        raise NotImplementedError

    def _count_pending_mailbox_messages(self) -> int:
        """Count pending mailbox messages."""
        raise NotImplementedError

    def pause(self, reason: str | None = None) -> ControlResult:
        """Pause a running task.

        Transitions the task from planning/working status to paused status.
        The task can be resumed later using the resume() method.

        Args:
            reason: Optional reason for pausing (stored in progress).

        Returns:
            ControlResult: The result of the pause operation.

        Raises:
            NoActiveTaskError: If no active task exists.
            ControlOperationNotAllowedError: If the task cannot be paused.
        """
        self._ensure_task_exists("pause")

        state = self.state_manager.load_state()
        previous_status = state.status

        # Check if task can be paused
        if previous_status not in self.PAUSABLE_STATUSES:
            raise ControlOperationNotAllowedError(
                "pause",
                previous_status,
                self.PAUSABLE_STATUSES,
            )

        # Transition to paused
        state.status = "paused"
        self.state_manager.save_state(state)

        # Durable cross-process signal: a running orchestrator (possibly another
        # process) polls control.json each cycle and honours the pause.
        self.control_channel.request("pause", reason=reason)

        # Append reason to progress if provided
        if reason:
            progress = self.state_manager.load_progress() or ""
            progress_update = f"\n\n## Paused\n\nReason: {reason}"
            self.state_manager.save_progress(progress + progress_update)

        return ControlResult(
            success=True,
            operation="pause",
            previous_status=previous_status,
            new_status="paused",
            message=f"Task paused successfully (was {previous_status})",
            details={"reason": reason} if reason else None,
        )

    def resume(self) -> ControlResult:
        """Resume a paused or blocked task.

        Transitions the task from paused/blocked status back to working status.

        Returns:
            ControlResult: The result of the resume operation.

        Raises:
            NoActiveTaskError: If no active task exists.
            ControlOperationNotAllowedError: If the task cannot be resumed.
        """
        self._ensure_task_exists("resume")

        state = self.state_manager.load_state()
        previous_status = state.status

        # Check if task can be resumed
        if previous_status not in self.RESUMABLE_STATUSES:
            raise ControlOperationNotAllowedError(
                "resume",
                previous_status,
                self.RESUMABLE_STATUSES,
            )

        # Transition to working
        state.status = "working"
        self.state_manager.save_state(state)

        # Clear any pending stop/pause signal so it does not immediately
        # re-trigger the freshly-resumed run.
        self.control_channel.clear()

        # Append resume note to progress
        progress = self.state_manager.load_progress() or ""
        progress_update = f"\n\n## Resumed\n\nResumed from {previous_status} status."
        self.state_manager.save_progress(progress + progress_update)

        return ControlResult(
            success=True,
            operation="resume",
            previous_status=previous_status,
            new_status="working",
            message=f"Task resumed successfully (was {previous_status})",
        )

    def stop(self, reason: str | None = None, cleanup: bool = False) -> ControlResult:
        """Stop a running task.

        Transitions the task to stopped status and optionally triggers
        shutdown of any running processes.

        Args:
            reason: Optional reason for stopping.
            cleanup: If True, also cleanup state files (like failed state).

        Returns:
            ControlResult: The result of the stop operation.

        Raises:
            NoActiveTaskError: If no active task exists.
            ControlOperationNotAllowedError: If the task cannot be stopped.
        """
        from .shutdown import request_shutdown  # noqa: PLC0415

        self._ensure_task_exists("stop")

        state = self.state_manager.load_state()
        previous_status = state.status

        # Check if task can be stopped
        if previous_status not in self.STOPPABLE_STATUSES:
            raise ControlOperationNotAllowedError(
                "stop",
                previous_status,
                self.STOPPABLE_STATUSES,
            )

        # Request shutdown to stop any running processes
        shutdown_reason = reason or "stop requested"
        request_shutdown(shutdown_reason)

        # Durable cross-process signal: request_shutdown only sets a
        # process-local Event (invisible to a CLI-launched orchestrator running
        # in another process). control.json crosses that boundary — the
        # orchestrator polls it each cycle and stops.
        self.control_channel.request("stop", reason=shutdown_reason)

        # Transition to stopped (can be resumed or failed from this state)
        state.status = "stopped"
        self.state_manager.save_state(state)

        # Append reason to progress if provided
        if reason:
            progress = self.state_manager.load_progress() or ""
            progress_update = f"\n\n## Stopped\n\nReason: {reason}"
            self.state_manager.save_progress(progress + progress_update)

        # Optionally cleanup state. A stop signal written from another process
        # may reach an orchestrator that is still mid-cycle and holding the
        # session lock; deleting the state dir underneath it would let its next
        # save_state recreate a half-populated dir (state.json without
        # goal/plan). Wait (bounded) for the session to release first, and skip
        # cleanup entirely if it never does — never clobber a live run.
        details: dict[str, Any] = {"reason": reason, "cleanup": cleanup}
        if cleanup:
            if self._wait_for_session_release():
                dropped = self._count_pending_mailbox_messages()
                if dropped:
                    logger.warning(
                        "stop(cleanup=True): dropping %d pending mailbox "
                        "message(s) while cleaning up %s",
                        dropped,
                        self.state_manager.state_dir,
                    )
                    details["dropped_mailbox_messages"] = dropped
                self.state_manager.cleanup_on_success(state.run_id)
            else:
                details["cleanup"] = False
                details["cleanup_skipped"] = "session still active"
                logger.warning(
                    "stop(cleanup=True): a live session still holds %s after "
                    "%.0fs; skipping cleanup to avoid clobbering active state",
                    self.state_manager.state_dir,
                    SESSION_RELEASE_TIMEOUT_SEC,
                )

        return ControlResult(
            success=True,
            operation="stop",
            previous_status=previous_status,
            new_status="stopped",
            message=f"Task stopped successfully (was {previous_status})",
            details=details,
        )

    def update_config(self, **kwargs: Any) -> ControlResult:
        """Update task configuration at runtime.

        Updates the TaskOptions stored in the task state. Only specified
        options are updated; others retain their current values.

        Supported options:
            - auto_merge: bool - Whether to auto-merge PRs
            - max_sessions: int | None - Maximum number of sessions
            - pause_on_pr: bool - Whether to pause on PR creation
            - enable_checkpointing: bool - Whether to enable checkpointing
            - log_level: str - Log level (quiet, normal, verbose)
            - log_format: str - Log format (text, json)
            - pr_per_task: bool - Whether to create PR per task

        Args:
            **kwargs: Configuration options to update.

        Returns:
            ControlResult: The result of the update operation.

        Raises:
            NoActiveTaskError: If no active task exists.
            ValueError: If invalid configuration options are provided.
        """
        self._ensure_task_exists("update_config")

        # Use StateManager.update_options() for the actual update
        updated_options = self.state_manager.update_options(**kwargs)

        # Load current state for response details
        state = self.state_manager.load_state()
        current_options = state.options.model_dump()

        if updated_options:
            message = f"Configuration updated: {', '.join(f'{k}={v}' for k, v in updated_options.items())}"
        else:
            message = "No configuration changes needed"

        return ControlResult(
            success=True,
            operation="update_config",
            previous_status=state.status,
            new_status=state.status,
            message=message,
            details={"updated": updated_options, "current": current_options},
        )

    def get_status(self) -> ControlResult:
        """Get current task status and information.

        Returns:
            ControlResult: Contains current task status and details.

        Raises:
            NoActiveTaskError: If no active task exists.
        """
        self._ensure_task_exists("get_status")

        state = self.state_manager.load_state()
        goal = self.state_manager.load_goal()
        plan = self.state_manager.load_plan()

        # Parse tasks from plan
        tasks = self.state_manager._parse_plan_tasks(plan or "")
        completed_tasks = sum(1 for _ in range(state.current_task_index))
        total_tasks = len(tasks)

        return ControlResult(
            success=True,
            operation="get_status",
            previous_status=state.status,
            new_status=state.status,
            message=f"Task is {state.status}",
            details={
                "goal": goal,
                "status": state.status,
                "workflow_stage": state.workflow_stage,
                "current_task_index": state.current_task_index,
                "session_count": state.session_count,
                "current_pr": state.current_pr,
                "model": state.model,
                "run_id": state.run_id,
                "created_at": state.created_at,
                "updated_at": state.updated_at,
                "options": state.options.model_dump(),
                "tasks": {
                    "completed": completed_tasks,
                    "total": total_tasks,
                    "progress": f"{completed_tasks}/{total_tasks}" if total_tasks else "No tasks",
                },
            },
        )


__all__ = ["_ControlOpsMixin"]
