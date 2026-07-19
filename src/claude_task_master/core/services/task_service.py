"""Transport-neutral task operations shared by the REST API and MCP server.

Both the REST routes (:mod:`claude_task_master.api.routes`) and the MCP tools
(:mod:`claude_task_master.mcp.tools`) expose the same task operations -- read
status/plan/logs/progress/context, initialize, clean, and the control
transitions (pause/stop/resume/update-config). Before this service existed each
transport re-implemented the existence checks, state loading, and control
exception handling, then the REST layer string-sniffed error text to choose an
HTTP status code.

:class:`TaskService` owns that logic exactly once. Every method returns a
:class:`~claude_task_master.core.services.results.ServiceResult`; the REST layer
maps its :class:`~claude_task_master.core.services.results.ServiceOutcome` to an
HTTP status code and typed response model, and the MCP layer maps it to a plain
``dict``. Presentation strings that legitimately differ between the two
transports (e.g. MCP's "No active task found. Nothing to stop.") are supplied by
each adapter, not baked in here.
"""

from __future__ import annotations

import shutil
from collections import deque
from typing import TYPE_CHECKING

from claude_task_master.core.control import (
    ControlManager,
    ControlOperationNotAllowedError,
    NoActiveTaskError,
)
from claude_task_master.core.services.results import ServiceResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from claude_task_master.core.control import ControlResult
    from claude_task_master.core.state import StateManager, TaskOptions


class TaskService:
    """Business logic for task operations, independent of transport.

    Bound to a single :class:`~claude_task_master.core.state.StateManager` (and
    therefore a single state directory). A fresh instance is cheap to construct
    per request; it holds no mutable state of its own.

    Attributes:
        state_manager: The state manager all operations read from and write to.
    """

    def __init__(self, state_manager: StateManager) -> None:
        """Bind the service to a state manager.

        Args:
            state_manager: The state manager whose directory this service
                operates on.
        """
        self.state_manager = state_manager

    def _control_manager(self) -> ControlManager:
        """Build a control manager for the bound state directory."""
        return ControlManager(state_manager=self.state_manager)

    # -------------------------------------------------------------------------
    # Read operations
    # -------------------------------------------------------------------------

    def get_status(self) -> ServiceResult:
        """Load the current task state and goal.

        Returns:
            ``OK`` with ``data={"state", "goal"}`` when a task exists,
            ``NOT_FOUND`` when there is no task, or ``ERROR`` if the state
            cannot be loaded. The caller renders ``state`` into its own shape
            (REST enum-validates and enriches; MCP dumps the options).
        """
        if not self.state_manager.exists():
            return ServiceResult.not_found()

        try:
            state = self.state_manager.load_state()
            goal = self.state_manager.load_goal()
            return ServiceResult.ok(data={"state": state, "goal": goal})
        except Exception as e:
            return ServiceResult.failed(error=str(e))

    def get_plan(self) -> ServiceResult:
        """Load the task plan markdown.

        Returns:
            ``OK`` with ``data={"plan"}``; ``NOT_FOUND`` (message
            ``"No plan found"`` when the task exists but has no plan yet, empty
            otherwise); or ``ERROR`` on a load failure.
        """
        if not self.state_manager.exists():
            return ServiceResult.not_found()

        try:
            plan = self.state_manager.load_plan()
            if not plan:
                return ServiceResult.not_found(message="No plan found")
            return ServiceResult.ok(data={"plan": plan})
        except Exception as e:
            return ServiceResult.failed(error=str(e))

    def get_logs(self, tail: int = 100) -> ServiceResult:
        """Read the last ``tail`` lines of the current run's log file.

        Args:
            tail: Number of trailing lines to return. Must be >= 1.

        Returns:
            ``OK`` with ``data={"log_content", "log_file"}``; ``INVALID`` when
            ``tail < 1``; ``NOT_FOUND`` (message ``"No log file found"`` when the
            task exists but has not logged yet); or ``ERROR`` on a read failure.
        """
        if tail < 1:
            return ServiceResult.invalid(message="tail must be >= 1", error="tail must be >= 1")

        if not self.state_manager.exists():
            return ServiceResult.not_found()

        try:
            state = self.state_manager.load_state()
            log_file = self.state_manager.get_log_file(state.run_id)
            if not log_file.exists():
                return ServiceResult.not_found(message="No log file found")

            # deque(maxlen=tail) keeps only the trailing window in memory.
            with open(log_file) as f:
                lines = deque(f, maxlen=tail)

            return ServiceResult.ok(data={"log_content": "".join(lines), "log_file": str(log_file)})
        except Exception as e:
            return ServiceResult.failed(error=str(e))

    def get_progress(self) -> ServiceResult:
        """Load the human-readable progress summary.

        Returns:
            ``OK`` with ``data={"progress"}`` (``None`` and message
            ``"No progress recorded yet"`` when nothing is recorded);
            ``NOT_FOUND`` when there is no task; or ``ERROR`` on failure.
        """
        if not self.state_manager.exists():
            return ServiceResult.not_found()

        try:
            progress = self.state_manager.load_progress()
            if not progress:
                return ServiceResult.ok(data={"progress": None}, message="No progress recorded yet")
            return ServiceResult.ok(data={"progress": progress})
        except Exception as e:
            return ServiceResult.failed(error=str(e))

    def get_context(self) -> ServiceResult:
        """Load the accumulated context/learnings.

        Returns:
            ``OK`` with ``data={"context"}`` (the raw value, possibly falsy --
            each transport renders "empty" differently); ``NOT_FOUND`` when there
            is no task; or ``ERROR`` on failure.
        """
        if not self.state_manager.exists():
            return ServiceResult.not_found()

        try:
            context = self.state_manager.load_context()
            return ServiceResult.ok(data={"context": context})
        except Exception as e:
            return ServiceResult.failed(error=str(e))

    def list_tasks(self) -> ServiceResult:
        """Parse the plan into a task list with completion counts.

        Returns:
            ``OK`` with ``data={"tasks", "total", "completed", "current_index"}``;
            ``NOT_FOUND`` (message ``"No plan found"`` when the task exists but
            has no plan); or ``ERROR`` on failure.
        """
        if not self.state_manager.exists():
            return ServiceResult.not_found()

        try:
            plan = self.state_manager.load_plan()
            if not plan:
                return ServiceResult.not_found(message="No plan found")

            from claude_task_master.core.task_group import parse_tasks_with_groups

            parsed_tasks, _ = parse_tasks_with_groups(plan)
            tasks = [
                {
                    "task": t.description,
                    "completed": t.is_complete,
                    "context": t.context_lines,
                    "group": t.group_name,
                }
                for t in parsed_tasks
            ]
            state = self.state_manager.load_state()
            return ServiceResult.ok(
                data={
                    "tasks": tasks,
                    "total": len(tasks),
                    "completed": sum(1 for t in tasks if t["completed"]),
                    "current_index": state.current_task_index,
                }
            )
        except Exception as e:
            return ServiceResult.failed(error=str(e))

    # -------------------------------------------------------------------------
    # Lifecycle operations
    # -------------------------------------------------------------------------

    def delete_coding_style(self) -> ServiceResult:
        """Delete the cached ``coding-style.md`` guide.

        Returns:
            ``OK`` with ``data={"deleted": bool}`` (whether a file was removed);
            ``NOT_FOUND`` when there is no task; or ``ERROR`` on failure.
        """
        if not self.state_manager.exists():
            return ServiceResult.not_found()

        try:
            deleted = self.state_manager.delete_coding_style()
            return ServiceResult.ok(data={"deleted": deleted})
        except Exception as e:
            return ServiceResult.failed(error=str(e))

    def init_task(self, goal: str, model: str, options: TaskOptions) -> ServiceResult:
        """Initialize a new task.

        The caller is responsible for any transport-specific validation (model
        name, credentials) before calling this; the service only enforces the
        "no task already exists" invariant and performs the initialization.

        Args:
            goal: The goal to achieve.
            model: The model identifier to persist.
            options: Fully-constructed task options.

        Returns:
            ``OK`` with ``data={"state"}`` on success; ``CONFLICT`` when a task
            already exists; or ``ERROR`` on failure.
        """
        if self.state_manager.exists():
            return ServiceResult.conflict()

        try:
            state = self.state_manager.initialize(goal=goal, model=model, options=options)
            return ServiceResult.ok(data={"state": state})
        except Exception as e:
            return ServiceResult.failed(error=str(e))

    def clean(self, force: bool = False) -> ServiceResult:
        """Remove the task state directory.

        Args:
            force: Delete even when a session lock is held. Callers that always
                delete (e.g. the REST ``DELETE /task`` route) pass ``True``.

        Returns:
            ``OK`` with ``data={"files_removed": bool}`` on success; ``NOT_FOUND``
            when there is nothing to clean; ``INVALID`` when a session is active
            and ``force`` is not set; or ``ERROR`` on failure.
        """
        if not self.state_manager.exists():
            return ServiceResult.not_found()

        if self.state_manager.is_session_active() and not force:
            return ServiceResult.invalid(
                message="Another claudetm session is active. Use force=True to override."
            )

        try:
            # Release the lock first so the rmtree does not race a live holder.
            self.state_manager.release_session_lock()
            state_dir = self.state_manager.state_dir
            if state_dir.exists():
                shutil.rmtree(state_dir)
                return ServiceResult.ok(data={"files_removed": True})
            return ServiceResult.ok(
                data={"files_removed": False}, message="State directory did not exist"
            )
        except Exception as e:
            return ServiceResult.failed(error=str(e))

    # -------------------------------------------------------------------------
    # Control operations
    #
    # ``ControlManager`` raises typed exceptions; catching them here is the one
    # place the exception -> outcome mapping lives, so neither transport has to
    # re-derive it (REST previously matched substrings of the message text).
    # -------------------------------------------------------------------------

    def pause(self, reason: str | None = None) -> ServiceResult:
        """Pause a running task.

        Args:
            reason: Optional reason recorded with the pause.

        Returns:
            ``OK`` (``data={"result": ControlResult}``), ``NOT_FOUND`` when no
            task exists, ``INVALID`` when the transition is not allowed
            (``data={"previous_status"}``), or ``ERROR`` on failure.
        """
        return self._run_control("pause", lambda cm: cm.pause(reason=reason))

    def stop(self, reason: str | None = None, cleanup: bool = False) -> ServiceResult:
        """Stop a task and trigger graceful shutdown.

        Args:
            reason: Optional reason recorded with the stop.
            cleanup: Whether to also remove state files after stopping.

        Returns:
            See :meth:`pause` for the outcome contract.
        """
        return self._run_control("stop", lambda cm: cm.stop(reason=reason, cleanup=cleanup))

    def resume(self) -> ServiceResult:
        """Resume a paused, blocked, or stopped task.

        Returns:
            See :meth:`pause` for the outcome contract.
        """
        return self._run_control("resume", lambda cm: cm.resume())

    def update_config(self, **kwargs: object) -> ServiceResult:
        """Update runtime task options.

        Args:
            **kwargs: The option fields to change (only non-``None`` values).

        Returns:
            ``OK`` (``data={"result": ControlResult}``) on success; ``INVALID``
            when no options are supplied or a value is rejected; ``NOT_FOUND``
            when no task exists; or ``ERROR`` on failure.
        """
        if not kwargs:
            return ServiceResult.invalid(
                message="No configuration options provided",
                error="At least one configuration option must be specified",
            )

        try:
            result = self._control_manager().update_config(**kwargs)
            return ServiceResult.ok(data={"result": result}, message=result.message)
        except NoActiveTaskError as e:
            return ServiceResult.not_found(message=e.message, error=str(e))
        except ValueError as e:
            return ServiceResult.invalid(message=str(e), error=str(e))
        except Exception as e:
            return ServiceResult.failed(error=str(e))

    def _run_control(
        self,
        operation: str,
        action: Callable[[ControlManager], ControlResult],
    ) -> ServiceResult:
        """Execute a control transition and map its outcome.

        Args:
            operation: The operation name (for error messages -- unused here but
                keeps call sites self-documenting).
            action: Callback invoking the desired ``ControlManager`` method.

        Returns:
            The mapped :class:`ServiceResult`.
        """
        try:
            result = action(self._control_manager())
            return ServiceResult.ok(data={"result": result}, message=result.message)
        except NoActiveTaskError as e:
            return ServiceResult.not_found(message=e.message, error=str(e))
        except ControlOperationNotAllowedError as e:
            return ServiceResult.invalid(
                message=e.message,
                error=str(e),
                data={"previous_status": e.current_status},
            )
        except Exception as e:
            return ServiceResult.failed(error=str(e))
