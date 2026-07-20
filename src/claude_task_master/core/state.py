"""State Manager - All persistence to .claude-task-master/ directory."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

# Import single-instance session-lock helpers
from claude_task_master.core import session_lock

# Import the repo-local git-exclude helper (keeps state out of user commits)
from claude_task_master.core.git_exclude import ensure_state_dir_git_excluded

# Import backup/recovery mixin
from claude_task_master.core.state_backup import BackupRecoveryMixin

# Import exceptions and state constants from dedicated module
from claude_task_master.core.state_exceptions import (
    CONTROL_AUTHORITATIVE_STATUSES,
    RESUMABLE_STATUSES,
    TERMINAL_STATUSES,
    VALID_STATUSES,
    VALID_TRANSITIONS,
    WORKFLOW_STAGES,
    InvalidStateTransitionError,
    StateCorruptedError,
    StateError,
    StateLockError,
    StateNotFoundError,
    StatePermissionError,
    StateResumeValidationError,
    StateValidationError,
)

# Import file operations mixin
from claude_task_master.core.state_file_ops import FileOperationsMixin

# Import models, schema constants, and file-lock from dedicated module
# StatusType is exported for type-checking consumers
from claude_task_master.core.state_models import (
    _STATE_MIGRATIONS,  # noqa: F401 — re-exported so tests can patch state._STATE_MIGRATIONS
    CURRENT_SCHEMA_VERSION,
    StatusType,  # noqa: F401
    TaskOptions,
    TaskState,
    WorkflowStageType,  # noqa: F401
    file_lock,
)

# Import PR context mixin
from claude_task_master.core.state_pr import PRContextMixin

# Import save/load/migrate mixin
from claude_task_master.core.state_save_load import _StateSaveLoadMixin

# Re-export exceptions for backwards compatibility
__all__ = [
    # Exceptions
    "StateError",
    "StateNotFoundError",
    "StateCorruptedError",
    "StateValidationError",
    "InvalidStateTransitionError",
    "StatePermissionError",
    "StateLockError",
    "StateResumeValidationError",
    # Constants
    "VALID_STATUSES",
    "WORKFLOW_STAGES",
    "TERMINAL_STATUSES",
    "RESUMABLE_STATUSES",
    "CONTROL_AUTHORITATIVE_STATUSES",
    "VALID_TRANSITIONS",
    "CURRENT_SCHEMA_VERSION",
    # Classes
    "TaskOptions",
    "TaskState",
    "StateManager",
    "PRContextMixin",
    "FileOperationsMixin",
    "BackupRecoveryMixin",
    # Functions
    "file_lock",
]


# =============================================================================
# State Manager
# =============================================================================


class StateManager(PRContextMixin, FileOperationsMixin, _StateSaveLoadMixin, BackupRecoveryMixin):
    """Manages all state persistence.

    Inherits PR context methods from PRContextMixin.
    Inherits file operations methods from FileOperationsMixin.
    Inherits backup/recovery methods from BackupRecoveryMixin.
    Inherits save/load/migrate methods from _StateSaveLoadMixin.
    """

    STATE_DIR = Path(".claude-task-master")
    LOCK_TIMEOUT = 5.0  # seconds

    def __init__(self, state_dir: Path | None = None):
        """Initialize state manager."""
        self.state_dir = state_dir or self.STATE_DIR
        self.logs_dir = self.state_dir / "logs"
        self._lock_file = self.state_dir / ".state.lock"
        self._pid_file = self.state_dir / ".pid"

    @property
    def state_file(self) -> Path:
        """Get the path to the state.json file."""
        return self.state_dir / "state.json"

    @property
    def backup_dir(self) -> Path:
        """Get the path to the backup directory."""
        return self.state_dir / "backups"

    # ------------------------------------------------------------------
    # Session lock
    # ------------------------------------------------------------------

    def acquire_session_lock(self) -> bool:
        """Acquire the single-instance session lock.

        Atomically creates the ``.pid`` lock file with ``O_CREAT | O_EXCL`` so
        two concurrent ``claudetm`` processes can never both acquire it (the old
        check-then-write left a race window). The critical section is serialized
        under the state file lock so a stale lock left by a crashed process is
        reclaimed by at most one racer at a time. A recorded pid+start-time lets
        a lock held by a dead or PID-recycled process be reclaimed rather than
        blocking forever.

        Returns:
            True if the lock was acquired, False if another live session holds it
            (or the lock could not be written).
        """
        try:
            with file_lock(self._lock_file, timeout=self.LOCK_TIMEOUT):
                return self._acquire_session_lock_locked()
        except StateLockError:
            # Another process is actively holding the state lock — treat the
            # state directory as in use by another session.
            return False

    def _acquire_session_lock_locked(self) -> bool:
        """Acquire the PID lock while holding the state file lock.

        Returns:
            True if the lock was acquired, False otherwise.
        """
        self._pid_file.parent.mkdir(parents=True, exist_ok=True)
        current = session_lock.current_owner()
        payload = session_lock.serialize_owner(current)

        # Initial create plus one stale-lock reclaim. Because the whole section
        # runs under the exclusive state lock, one retry always suffices: no
        # other process can recreate the file between our removal and re-create.
        for _ in range(2):
            try:
                fd = os.open(self._pid_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                owner = session_lock.read_owner(self._pid_file)
                if owner is not None and owner.pid == current.pid:
                    if owner == current:
                        return True  # True re-entry: this exact process holds it.
                    # Same PID, different start time — the recorded owner is a
                    # dead predecessor whose PID the OS recycled onto us. Treating
                    # it as re-entry would leave the stale identity in place, so
                    # another starter reclaims it and runs concurrently. Reclaim.
                    self._remove_pid_file()
                    continue
                if owner is not None and session_lock.is_owner_running(owner):
                    return False  # Another live session holds it.
                # Stale, PID-recycled, or corrupt lock — remove it and retry.
                self._remove_pid_file()
                continue
            except OSError:
                return False

            try:
                with os.fdopen(fd, "w", encoding="ascii") as f:
                    f.write(payload)
            except OSError:
                self._remove_pid_file()
                return False
            return True
        return False

    def release_session_lock(self) -> None:
        """Release the session lock, only if this process still owns it."""
        owner = session_lock.read_owner(self._pid_file)
        # A live process's PID is unique, so a matching PID means the lock is
        # ours — never remove a lock a different (or recycled) process holds.
        if owner is not None and owner.pid == os.getpid():
            self._remove_pid_file()

    def is_session_active(self) -> bool:
        """Check if another live session is using this state directory.

        Returns:
            True if a *different* process holds a live lock. A missing, stale,
            PID-recycled, or corrupt lock reads as inactive. This is a read-only
            probe; stale locks are reclaimed by :meth:`acquire_session_lock`.
        """
        owner = session_lock.read_owner(self._pid_file)
        if owner is None or owner.pid == os.getpid():
            return False
        return session_lock.is_owner_running(owner)

    def _remove_pid_file(self) -> None:
        """Best-effort removal of the PID lock file."""
        try:
            self._pid_file.unlink(missing_ok=True)
        except OSError:
            pass  # Concurrent removal or permissions — best effort.

    def is_safe_to_delete(self) -> bool:
        """Check if state directory can be safely deleted.

        Returns:
            True if no active session is using this state.
        """
        return not self.is_session_active()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self, goal: str, model: str, options: TaskOptions) -> TaskState:
        """Initialize new task state.

        Args:
            goal: The task goal description.
            model: The model to use (e.g., 'sonnet', 'opus').
            options: Task execution options.

        Returns:
            TaskState: The initialized task state.

        Raises:
            StatePermissionError: If directories cannot be created.
            StateError: If another session is active.
        """
        try:
            self.state_dir.mkdir(exist_ok=True)
            self.logs_dir.mkdir(exist_ok=True)
        except PermissionError as e:
            raise StatePermissionError(self.state_dir, "creating directories", e) from e

        # Keep the state dir out of the user's git history: add it to the
        # repo-local .git/info/exclude. Best-effort — never blocks init.
        ensure_state_dir_git_excluded(self.state_dir)

        # Acquire session lock
        if not self.acquire_session_lock():
            raise StateError(
                "Another claudetm session is active",
                "Wait for the other session to complete or use 'clean -f' to force cleanup.",
            )

        timestamp = datetime.now().isoformat()
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

        state = TaskState(
            status="planning",
            created_at=timestamp,
            updated_at=timestamp,
            run_id=run_id,
            model=model,
            options=options,
        )

        self.save_state(state)
        self.save_goal(goal)

        return state

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def get_log_file(self, run_id: str) -> Path:
        """Get path to log file for run."""
        return self.logs_dir / f"run-{run_id}.txt"

    def exists(self) -> bool:
        """Check if state directory exists."""
        return self.state_dir.exists() and (self.state_dir / "state.json").exists()

    def validate_for_resume(self, state: TaskState | None = None) -> TaskState:
        """Validate that state is valid for resumption.

        This method performs comprehensive validation to ensure a task
        can be safely resumed, including:
        - State file exists and is valid
        - Status is resumable (not terminal)
        - Plan file exists
        - Current task index is within bounds

        Args:
            state: Optional TaskState to validate. If not provided, loads from disk.

        Returns:
            TaskState: The validated state object ready for resumption.

        Raises:
            StateNotFoundError: If no state file exists.
            StateResumeValidationError: If state is not valid for resumption.
            StateCorruptedError: If state file is corrupted.
            StateValidationError: If state data fails validation.
        """
        # Load state if not provided
        if state is None:
            if not self.exists():
                raise StateNotFoundError(self.state_file)
            state = self.load_state()

        # Check for terminal states
        if state.status in TERMINAL_STATUSES:
            suggestion = "Use 'clean' to remove state and start a new task."
            if state.status == "success":
                raise StateResumeValidationError(
                    "Task has already completed successfully",
                    status=state.status,
                    suggestion=suggestion,
                )
            else:  # failed
                raise StateResumeValidationError(
                    "Task has failed and cannot be resumed",
                    status=state.status,
                    suggestion=suggestion,
                )

        # Check for planning state - needs special handling
        if state.status == "planning":
            # Planning state can be resumed but needs a plan
            plan = self.load_plan()
            if not plan:
                raise StateResumeValidationError(
                    "Task is in planning phase but no plan exists",
                    status=state.status,
                    suggestion="Planning was interrupted. Consider using 'clean' and starting fresh.",
                )

        # Verify state is resumable
        if state.status not in RESUMABLE_STATUSES and state.status != "planning":
            raise StateResumeValidationError(
                f"Status '{state.status}' is not resumable",
                status=state.status,
                suggestion=f"Valid resumable statuses: {', '.join(sorted(RESUMABLE_STATUSES))}",
            )

        # Verify plan exists for non-planning states
        plan = self.load_plan()
        if not plan:
            raise StateResumeValidationError(
                "No plan file found",
                status=state.status,
                suggestion="Task state may be corrupted. Use 'clean' to start fresh.",
            )

        # Parse tasks and validate current_task_index
        tasks = self._parse_plan_tasks(plan)

        # Validate current_task_index is within bounds
        if state.current_task_index < 0:
            raise StateResumeValidationError(
                "Invalid task index (negative)",
                status=state.status,
                current_task_index=state.current_task_index,
                total_tasks=len(tasks),
                suggestion="Task state may be corrupted. Use 'clean' to start fresh.",
            )

        # Empty plan (no parsed tasks): any nonzero index is stale state
        if not tasks:
            if state.current_task_index != 0:
                raise StateResumeValidationError(
                    "Plan contains no tasks but task index is not zero",
                    status=state.status,
                    current_task_index=state.current_task_index,
                    total_tasks=0,
                    suggestion="Plan has no tasks. Use 'clean' to start fresh.",
                )
            return state

        # Allow index == len(tasks) since it means all tasks are complete
        if state.current_task_index > len(tasks):
            raise StateResumeValidationError(
                "Task index exceeds number of tasks in plan",
                status=state.status,
                current_task_index=state.current_task_index,
                total_tasks=len(tasks),
                suggestion="Task state may be out of sync with plan. Use 'clean' to start fresh.",
            )

        return state

    def update_options(
        self, **kwargs: bool | int | str | None
    ) -> dict[str, bool | int | str | None]:
        """Update task options at runtime.

        This method allows updating TaskOptions fields while preserving other
        option values. It validates that provided option names are valid and
        returns a dictionary of the changes that were applied.

        Supported options:
            - auto_merge: bool - Whether to auto-merge PRs
            - max_sessions: int | None - Maximum number of sessions
            - pause_on_pr: bool - Whether to pause on PR creation
            - enable_checkpointing: bool - Whether to enable checkpointing
            - log_level: str - Log level (quiet, normal, verbose)
            - log_format: str - Log format (text, json)
            - pr_per_task: bool - Whether to create PR per task
            - webhook_url: str | None - Webhook endpoint URL
            - webhook_secret: str | None - HMAC secret for signing webhook payloads

        Args:
            **kwargs: Configuration options to update. Only specified options
                are updated; others retain their current values.

        Returns:
            dict[str, Any]: Dictionary of options that were actually changed,
                with their new values.

        Raises:
            StateNotFoundError: If no state file exists.
            ValueError: If invalid configuration options are provided.
            StatePermissionError: If the file cannot be written.
            StateLockError: If the file lock cannot be acquired.

        Example:
            ```python
            state_manager = StateManager()
            changed = state_manager.update_options(
                max_sessions=10,
                auto_merge=False
            )
            print(changed)  # {'max_sessions': 10, 'auto_merge': False}
            ```
        """
        if not self.exists():
            raise StateNotFoundError(self.state_file)

        # Get valid option names from TaskOptions model
        valid_options = set(TaskOptions.model_fields.keys())
        provided_options = set(kwargs.keys())

        # Check for invalid options
        invalid_options = provided_options - valid_options
        if invalid_options:
            raise ValueError(
                f"Invalid configuration options: {', '.join(sorted(invalid_options))}. "
                f"Valid options: {', '.join(sorted(valid_options))}"
            )

        # Load current state
        state = self.load_state()

        # Get current options as dict
        current_options = state.options.model_dump()
        updated_options: dict[str, bool | int | str | None] = {}

        # Apply updates, tracking what actually changed
        for key, value in kwargs.items():
            if value is not None and current_options.get(key) != value:
                current_options[key] = value
                updated_options[key] = value

        # Only save if there were actual changes
        if updated_options:
            state.options = TaskOptions(**current_options)
            # Skip transition validation since status isn't changing
            self.save_state(state, validate_transition=False)

        return updated_options
