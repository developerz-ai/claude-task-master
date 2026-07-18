"""State Manager - All persistence to .claude-task-master/ directory."""

import fcntl
import json
import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Literal

from pydantic import BaseModel, ValidationError

# Import single-instance session-lock helpers
from claude_task_master.core import session_lock

# Import shared durable atomic-write helper
from claude_task_master.core.atomic_io import atomic_write_json

# Import backup/recovery mixin
from claude_task_master.core.state_backup import BackupRecoveryMixin

# Import exceptions and state constants from dedicated module
from claude_task_master.core.state_exceptions import (
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

# Import PR context mixin
from claude_task_master.core.state_pr import PRContextMixin

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
# Models
# =============================================================================


class TaskOptions(BaseModel):
    """Options for task execution."""

    auto_merge: bool = True
    admin_merge: bool = False  # Use `gh pr merge --admin` to override base-branch policy
    enable_release: bool = False
    enable_verification: bool = False
    max_sessions: int | None = None
    max_prs: int | None = None
    pause_on_pr: bool = False
    enable_checkpointing: bool = False
    log_level: str = "normal"  # quiet, normal, verbose
    log_format: str = "text"  # text, json
    pr_per_task: bool = False  # If True, create PR per task; if False, PR per group
    branch_override: str | None = None  # Explicit branch name for the run (prevents collisions)
    webhook_url: str | None = None  # URL to receive webhook notifications
    webhook_secret: str | None = None  # HMAC secret for signing webhook payloads
    max_budget_usd: float | None = None  # Per-session spending cap in USD


# Status type alias for type checking
StatusType = Literal["planning", "working", "blocked", "paused", "stopped", "success", "failed"]


# Workflow stage type alias
WorkflowStageType = Literal[
    "working",
    "pr_created",
    "waiting_ci",
    "ci_failed",
    "waiting_reviews",
    "addressing_reviews",
    "ready_to_merge",
    "merged",
    "releasing",
    "release_fix",
]


# =============================================================================
# State schema versioning
# =============================================================================

#: Current on-disk state schema version. Bump by one whenever a change to
#: :class:`TaskState` cannot be absorbed by pydantic defaults alone (a renamed
#: or removed field, or a field whose meaning changed) and register the matching
#: upgrade step in :data:`_STATE_MIGRATIONS`.
CURRENT_SCHEMA_VERSION = 1

#: Ordered state migrations keyed by *source* version: ``_STATE_MIGRATIONS[n]``
#: takes a raw version-``n`` state dict and returns a version-``n+1`` dict.
#: :meth:`StateManager._migrate_state` applies them in sequence from the on-disk
#: version up to :data:`CURRENT_SCHEMA_VERSION`. Empty at version 1 — there is no
#: earlier format to upgrade from yet.
_STATE_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


class TaskState(BaseModel):
    """Machine-readable state."""

    # On-disk schema version, written on every save and checked on load by
    # ``StateManager._migrate_state``. State from an older version is migrated
    # forward; state from a newer version is rejected rather than letting
    # pydantic silently drop its unknown fields and then destroy them on save.
    schema_version: int = CURRENT_SCHEMA_VERSION
    status: StatusType  # planning|working|blocked|paused|stopped|success|failed
    workflow_stage: WorkflowStageType | None = None  # PR lifecycle stage
    current_task_index: int = 0
    session_count: int = 0
    current_pr: int | None = None
    created_at: str
    updated_at: str
    run_id: str
    model: str
    options: TaskOptions
    # Mailbox integration fields
    mailbox_enabled: bool = True  # Whether mailbox checking is enabled
    last_mailbox_check: datetime | None = None  # Last time mailbox was checked
    # PR tracking fields
    prs_created: int = 0  # Total number of PRs created during this run
    prs_merged: int = 0  # Total number of PRs merged during this run
    last_counted_pr_created: int | None = None  # Last PR number counted for creation
    last_counted_pr_merged: int | None = None  # Last PR number counted for merge
    # Timing fields
    task_start_time: datetime | None = None  # When current task started
    pr_start_time: datetime | None = None  # When current PR was created
    pr_active_work_seconds: float = 0.0  # Accumulated work time for current PR (excluding CI wait)
    # CI polling fields
    ci_poll_start_time: datetime | None = None  # When CI polling started for current PR
    ci_fix_attempts: int = 0  # Number of CI-fix agent sessions for current PR
    # Release phase fields
    release_fix_attempts: int = 0  # Number of release fix attempts for current PR
    in_release_fix: bool = False  # True while current PR is a release-fix PR


# =============================================================================
# File Lock Context Manager
# =============================================================================


@contextmanager
def file_lock(
    lock_path: Path, timeout: float = 5.0, exclusive: bool = True
) -> Generator[IO[str], None, None]:
    """Context manager for file locking with timeout.

    Args:
        lock_path: Path to the lock file (will be created if it doesn't exist).
        timeout: Maximum time to wait for lock acquisition.
        exclusive: If True, acquire exclusive lock; otherwise shared lock.

    Yields:
        The file handle for the lock file.

    Raises:
        StateLockError: If the lock cannot be acquired within the timeout.
    """
    import time

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = None
    start_time = time.time()

    try:
        lock_file = open(lock_path, "w")
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH

        while True:
            try:
                fcntl.flock(lock_file.fileno(), lock_type | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() - start_time > timeout:
                    raise StateLockError(lock_path, timeout) from None
                time.sleep(0.1)

        yield lock_file
    finally:
        if lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass  # Ignore errors when unlocking
            lock_file.close()


# =============================================================================
# State Manager
# =============================================================================


class StateManager(PRContextMixin, FileOperationsMixin, BackupRecoveryMixin):
    """Manages all state persistence.

    Inherits PR context methods from PRContextMixin.
    Inherits file operations methods from FileOperationsMixin.
    Inherits backup/recovery methods from BackupRecoveryMixin.
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
        payload = session_lock.serialize_owner(session_lock.current_owner())

        # Initial create plus one stale-lock reclaim. Because the whole section
        # runs under the exclusive state lock, one retry always suffices: no
        # other process can recreate the file between our removal and re-create.
        for _ in range(2):
            try:
                fd = os.open(self._pid_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                owner = session_lock.read_owner(self._pid_file)
                if owner is not None and owner.pid == os.getpid():
                    return True  # We already hold the lock.
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

    def save_state(self, state: TaskState, validate_transition: bool = True) -> None:
        """Save state to state.json with file locking.

        The transition check, the atomic write, and the rotating backup all run
        under a single exclusive lock. The current state is read for validation
        *inside* the lock (not before acquiring it) so a concurrent writer cannot
        change the on-disk status between the check and the write
        (time-of-check-to-time-of-use). On success a rotating backup of the
        written state is created (best-effort) so a later corruption can be
        recovered from the most recent good state.

        Args:
            state: The TaskState to save.
            validate_transition: If True, validates state transition (default True).

        Raises:
            InvalidStateTransitionError: If the state transition is invalid.
            StatePermissionError: If the file cannot be written.
            StateLockError: If the file lock cannot be acquired.
        """
        with file_lock(self._lock_file, timeout=self.LOCK_TIMEOUT):
            # Validate the transition while holding the exclusive lock so no
            # other writer can slip a status change in between the read and the
            # write (TOCTOU). _load_state_internal may heal a corrupt file via
            # recovery, which is safe here because we hold the exclusive lock.
            if validate_transition and self.state_file.exists():
                try:
                    current_state = self._load_state_internal()
                    self._validate_transition(current_state.status, state.status)
                except (StateNotFoundError, StateCorruptedError):
                    # If we can't load current state, allow the save.
                    pass

            state.updated_at = datetime.now().isoformat()

            try:
                # Use atomic write with temp file.
                # Use mode='json' to serialize datetime fields as ISO strings.
                self._atomic_write_json(self.state_file, state.model_dump(mode="json"))
            except PermissionError as e:
                raise StatePermissionError(self.state_file, "writing", e) from e

            # Keep a rotating backup of every durable write so a later
            # corruption can be recovered from the most recent good state.
            # Best-effort: a backup failure must never fail the save itself.
            self.create_state_backup()

    def load_state(self) -> TaskState:
        """Load state from state.json with error recovery.

        Acquires the *exclusive* lock rather than a shared one: on a corrupt
        state file :meth:`_load_state_internal` triggers recovery, which heals
        ``state.json`` by writing the newest good backup back to disk. Writing
        under a shared lock would let two concurrent readers recover-and-write at
        the same time; the exclusive lock serializes them. The state file is
        tiny, so serializing reads costs nothing measurable.

        Returns:
            TaskState: The loaded task state.

        Raises:
            StateNotFoundError: If the state file does not exist.
            StateCorruptedError: If the state file is corrupted and cannot be recovered.
            StateValidationError: If the state data fails validation.
            StatePermissionError: If the file cannot be read.
            StateLockError: If the file lock cannot be acquired.
        """
        with file_lock(self._lock_file, timeout=self.LOCK_TIMEOUT):
            return self._load_state_internal()

    def _load_state_internal(self) -> TaskState:
        """Load and parse state without acquiring the lock.

        The caller MUST already hold the exclusive state lock: on corruption
        this delegates to :meth:`_attempt_recovery`, which writes the healed
        state back to ``state.json``. Both callers (:meth:`load_state` and
        :meth:`save_state`) invoke it inside ``file_lock``.
        """
        if not self.state_file.exists():
            raise StateNotFoundError(self.state_file)

        try:
            with open(self.state_file) as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError as e:
                    # Attempt recovery from backup
                    recovered_state: TaskState | None = self._attempt_recovery(e)
                    if recovered_state:
                        return recovered_state
                    raise StateCorruptedError(
                        self.state_file,
                        f"JSON parse error at line {e.lineno}, column {e.colno}: {e.msg}",
                        recoverable=False,
                    ) from e
        except PermissionError as e:
            raise StatePermissionError(self.state_file, "reading", e) from e

        # Handle empty JSON
        if not data:
            recovered_state_empty: TaskState | None = self._attempt_recovery(
                ValueError("Empty JSON object")
            )
            if recovered_state_empty:
                return recovered_state_empty
            raise StateCorruptedError(
                self.state_file,
                "State file is empty or contains an empty JSON object",
                recoverable=False,
            )

        # Migrate the raw dict to the current schema version before pydantic
        # validation. Older state is upgraded in place; state from a newer
        # version is rejected here rather than having its unknown fields
        # silently dropped and then destroyed on the next save.
        data = self._migrate_state(data)

        # Validate and parse the state data
        try:
            return TaskState(**data)
        except ValidationError as e:
            # Extract meaningful error messages
            missing_fields = []
            invalid_fields = []
            for error in e.errors():
                field = ".".join(str(loc) for loc in error["loc"])
                if error["type"] == "missing":
                    missing_fields.append(field)
                else:
                    invalid_fields.append(f"{field}: {error['msg']}")

            raise StateValidationError(
                "State file has invalid structure",
                missing_fields=missing_fields if missing_fields else None,
                invalid_fields=invalid_fields if invalid_fields else None,
            ) from e

    @staticmethod
    def _migrate_state(data: dict[str, Any]) -> dict[str, Any]:
        """Migrate a raw state dict to the current schema version.

        Applies the steps in :data:`_STATE_MIGRATIONS` in sequence from the
        on-disk ``schema_version`` up to :data:`CURRENT_SCHEMA_VERSION`, then
        stamps the current version onto the result. State written before schema
        versioning existed (no ``schema_version`` key), or with a missing or
        malformed marker, is treated as version 1 — the initial schema.

        Rejecting state written by a *newer* version is deliberate: pydantic
        would otherwise silently drop the unknown fields and then destroy them
        on the next save, so a forward-incompatible resume must fail loudly.

        Args:
            data: The raw state dict parsed from ``state.json``.

        Returns:
            The migrated state dict, tagged with the current schema version.

        Raises:
            StateValidationError: If the state was written by a newer schema
                version, or no migration path exists from the on-disk version.
        """
        # Non-mapping JSON (a bare list/number/string) is left untouched so the
        # downstream ``TaskState(**data)`` surfaces the corruption as it would
        # without migration, instead of an AttributeError on ``.get`` here.
        if not isinstance(data, dict):
            return data

        raw_version = data.get("schema_version", 1)
        # A missing or garbled marker is treated as the initial schema rather
        # than aborting the load: the field simply did not exist before this.
        version = raw_version if isinstance(raw_version, int) and raw_version >= 1 else 1

        if version > CURRENT_SCHEMA_VERSION:
            raise StateValidationError(
                f"State schema version {version} is newer than the supported "
                f"version {CURRENT_SCHEMA_VERSION}",
                invalid_fields=[
                    "schema_version: written by a newer claude-task-master; "
                    "upgrade it or run 'clean' to start fresh"
                ],
            )

        while version < CURRENT_SCHEMA_VERSION:
            migrate = _STATE_MIGRATIONS.get(version)
            if migrate is None:
                raise StateValidationError(
                    f"No migration path from state schema version {version} to "
                    f"{CURRENT_SCHEMA_VERSION}",
                    invalid_fields=["schema_version: unmigratable state"],
                )
            data = migrate(data)
            version += 1

        data["schema_version"] = CURRENT_SCHEMA_VERSION
        return data

    def _validate_transition(self, current_status: str, new_status: str) -> None:
        """Validate that a state transition is allowed.

        Args:
            current_status: The current status value.
            new_status: The new status value.

        Raises:
            InvalidStateTransitionError: If the transition is not allowed.
        """
        # Same status is always allowed (no actual transition)
        if current_status == new_status:
            return

        valid_next_states = VALID_TRANSITIONS.get(current_status, frozenset())
        if new_status not in valid_next_states:
            raise InvalidStateTransitionError(current_status, new_status)

    def _atomic_write_json(self, path: Path, data: dict) -> None:
        """Atomically and durably write JSON data to a file.

        Delegates to the shared :func:`atomic_write_json` helper, which writes
        to a temp file, fsyncs it, renames it over the target, then fsyncs the
        parent directory so a crash cannot leave a truncated ``state.json``.

        Args:
            path: The target file path.
            data: The data to write as JSON.
        """
        atomic_write_json(path, data)

    # Backup/recovery methods (_attempt_recovery, _create_backup, create_state_backup,
    # cleanup_on_success, _cleanup_old_logs) are inherited from BackupRecoveryMixin

    # File operations methods (save_goal, load_goal, save_criteria, load_criteria,
    # save_plan, load_plan, save_progress, load_progress, save_context, load_context)
    # are inherited from FileOperationsMixin

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

    # _parse_plan_tasks is inherited from FileOperationsMixin; it delegates to
    # claude_task_master.core.plan_parsing.parse_task_descriptions (single parser)

    # PR Context Methods are inherited from PRContextMixin:
    # - get_pr_dir(pr_number: int) -> Path
    # - save_pr_comments(pr_number: int, comments: list[dict]) -> None
    # - save_ci_failure(pr_number: int, check_name: str, logs: str) -> None
    # - load_pr_context(pr_number: int) -> str
    # - clear_pr_context(pr_number: int) -> None

    # File Operations Methods are inherited from FileOperationsMixin:
    # - save_goal(goal: str) -> None
    # - load_goal() -> str
    # - save_criteria(criteria: str) -> None
    # - load_criteria() -> str | None
    # - save_plan(plan: str) -> None
    # - load_plan() -> str | None
    # - save_progress(progress: str) -> None
    # - load_progress() -> str | None
    # - save_context(context: str) -> None
    # - load_context() -> str
    # - _parse_plan_tasks(plan: str) -> list[str]

    # Backup/Recovery Methods are inherited from BackupRecoveryMixin:
    # - _attempt_recovery(original_error: Exception) -> TaskState | None
    # - find_recoverable_state(reference_time: datetime | None = None) -> TaskState | None
    # - _create_backup(file_path: Path, suffix: str = "") -> Path | None
    # - create_state_backup() -> Path | None
    # - _regular_backups() -> list[Path]
    # - _rotate_backups(keep: int) -> None
    # - cleanup_on_success(run_id: str) -> None
    # - _cleanup_old_logs(max_logs: int = 10) -> None

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
