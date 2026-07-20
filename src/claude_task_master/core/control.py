"""Control Manager - Runtime control operations for task execution.

This module provides the ControlManager class for managing runtime control
operations like pause, stop, resume, and config updates. It coordinates
between StateManager and ShutdownManager to handle graceful state transitions.

Implementation split across focused sub-modules:
- :mod:`.control_types` — constants, exceptions, :class:`ControlResult`
- :mod:`.control_ops` — main operation methods mixin

Example usage:
    ```python
    from claude_task_master.core.control import ControlManager
    from claude_task_master.core.state import StateManager

    state_manager = StateManager()
    control = ControlManager(state_manager)

    # Pause a running task
    result = control.pause("User requested pause")

    # Resume a paused task
    result = control.resume()

    # Update configuration
    result = control.update_config(max_sessions=10, auto_merge=False)

    # Stop and cleanup
    result = control.stop("Task completed")
    ```
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from claude_task_master.core.control_channel import ControlChannel
from claude_task_master.core.shutdown import (
    ShutdownManager,
    get_shutdown_manager,
)
from claude_task_master.core.state import (
    StateManager,
    StateNotFoundError,
)
from claude_task_master.core.state_exceptions import RESUMABLE_STATUSES
from claude_task_master.mailbox.storage import MailboxStorage

from .control_ops import _ControlOpsMixin
from .control_types import (  # noqa: F401 — re-exported for backwards compat
    SESSION_RELEASE_POLL_INTERVAL_SEC,
    SESSION_RELEASE_TIMEOUT_SEC,
    ControlError,
    ControlOperationNotAllowedError,
    ControlResult,
    NoActiveTaskError,
)

if TYPE_CHECKING:
    from pathlib import Path


class ControlManager(_ControlOpsMixin):
    """Manages runtime control operations for task execution.

    This class provides methods for pausing, stopping, resuming, and updating
    configuration of running tasks. It coordinates with StateManager for
    state persistence and ShutdownManager for graceful shutdown handling.

    Attributes:
        state_manager: The StateManager instance for state operations.
        shutdown_manager: The ShutdownManager instance for shutdown coordination.
    """

    # Statuses that can be paused
    PAUSABLE_STATUSES = frozenset(["planning", "working"])

    # Statuses that can be resumed
    RESUMABLE_STATUSES = RESUMABLE_STATUSES

    # Statuses that can be stopped
    STOPPABLE_STATUSES = frozenset(["planning", "working", "blocked", "paused"])

    def __init__(
        self,
        state_manager: StateManager | None = None,
        shutdown_manager: ShutdownManager | None = None,
        state_dir: Path | None = None,
    ):
        """Initialize control manager.

        Args:
            state_manager: StateManager instance. If None, creates a new one.
            shutdown_manager: ShutdownManager instance. If None, uses global instance.
            state_dir: State directory path for StateManager. Only used if
                state_manager is None.
        """
        self.state_manager = state_manager or StateManager(state_dir)
        self.shutdown_manager = shutdown_manager or get_shutdown_manager()
        # Durable cross-process control channel (control.json). Written here on
        # stop/pause so a signal from another process (server/MCP/CLI) reaches a
        # running orchestrator, which the process-local shutdown Event cannot.
        self.control_channel = ControlChannel(self.state_manager.state_dir)

    def _ensure_task_exists(self, operation: str) -> None:
        """Ensure an active task exists.

        Args:
            operation: The operation being attempted (for error message).

        Raises:
            NoActiveTaskError: If no task state exists.
        """
        if not self.state_manager.exists():
            raise NoActiveTaskError(operation)

    def _wait_for_session_release(self) -> bool:
        """Wait (bounded) for any *other* live session to release the state dir.

        A stop request written from one process can reach an orchestrator
        running in another process that is still mid-cycle and holding the
        session lock. Cleaning up the state directory underneath it races its
        next ``save_state``, which would recreate a half-populated directory.
        This polls :meth:`StateManager.is_session_active` until it reports no
        live session or :data:`SESSION_RELEASE_TIMEOUT_SEC` elapses.

        A same-process caller (or one with no active session) returns
        immediately without sleeping.

        Returns:
            True if no *other* live session holds the state dir (safe to clean
            up), False if the timeout elapsed with a session still active.
        """
        deadline = time.monotonic() + SESSION_RELEASE_TIMEOUT_SEC
        while self.state_manager.is_session_active():
            if time.monotonic() >= deadline:
                return False
            time.sleep(SESSION_RELEASE_POLL_INTERVAL_SEC)
        return True

    def _count_pending_mailbox_messages(self) -> int:
        """Count mailbox messages that state cleanup is about to discard.

        Returns:
            Number of pending messages in ``mailbox.json``; ``0`` if the mailbox
            is empty, absent, or unreadable (best-effort — never blocks stop).
        """
        try:
            return MailboxStorage(self.state_manager.state_dir).count()
        except OSError:
            return 0

    def can_pause(self) -> bool:
        """Check if the current task can be paused.

        Returns:
            bool: True if the task can be paused, False otherwise.
        """
        if not self.state_manager.exists():
            return False
        try:
            state = self.state_manager.load_state()
            return state.status in self.PAUSABLE_STATUSES
        except StateNotFoundError:
            return False

    def can_resume(self) -> bool:
        """Check if the current task can be resumed.

        Returns:
            bool: True if the task can be resumed, False otherwise.
        """
        if not self.state_manager.exists():
            return False
        try:
            state = self.state_manager.load_state()
            return state.status in self.RESUMABLE_STATUSES
        except StateNotFoundError:
            return False

    def can_stop(self) -> bool:
        """Check if the current task can be stopped.

        Returns:
            bool: True if the task can be stopped, False otherwise.
        """
        if not self.state_manager.exists():
            return False
        try:
            state = self.state_manager.load_state()
            return state.status in self.STOPPABLE_STATUSES
        except StateNotFoundError:
            return False


__all__ = [
    "SESSION_RELEASE_TIMEOUT_SEC",
    "SESSION_RELEASE_POLL_INTERVAL_SEC",
    "ControlError",
    "ControlOperationNotAllowedError",
    "NoActiveTaskError",
    "ControlResult",
    "ControlManager",
]
