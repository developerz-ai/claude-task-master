"""State Manager - All persistence to .claude-task-master/ directory."""

import fcntl
import json
import os
import shutil
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import IO, Literal

from pydantic import BaseModel, ValidationError

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
    max_sessions: int | None = None
    pause_on_pr: bool = False
    enable_checkpointing: bool = False
    log_level: str = "normal"  # quiet, normal, verbose
    log_format: str = "text"  # text, json
    pr_per_task: bool = False  # If True, create PR per task; if False, PR per group
    webhook_url: str | None = None  # URL to receive webhook notifications
    webhook_secret: str | None = None  # HMAC secret for signing webhook payloads


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
]


class TaskState(BaseModel):
    """Machine-readable state."""

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
        """Acquire session lock by writing PID file.

        Returns:
            True if lock acquired, False if another session is active.
        """
        if self.is_session_active():
            return False
        try:
            self._pid_file.parent.mkdir(parents=True, exist_ok=True)
            self._pid_file.write_text(str(os.getpid()))
            return True
        except OSError:
            return False

    def release_session_lock(self) -> None:
        """Release session lock by removing PID file."""
        try:
            if self._pid_file.exists():
                # Only remove if we own the lock
                try:
                    pid = int(self._pid_file.read_text().strip())
                    if pid == os.getpid():
                        self._pid_file.unlink()
                except (ValueError, OSError):
                    pass  # Ignore errors reading own PID - will be cleaned up
        except OSError:
            pass  # Ignore errors when PID file doesn't exist

    def is_session_active(self) -> bool:
        """Check if another session is actively using this state.

        Returns:
            True if another process is using this state directory.
        """
        if not self._pid_file.exists():
            return False
        try:
            pid = int(self._pid_file.read_text().strip())
            # Check if process is still running (signal 0 = existence check)
            os.kill(pid, 0)
            # Process exists - check if it's not us
            return pid != os.getpid()
        except (ValueError, OSError, ProcessLookupError):
            # Invalid PID or process not running - clean up stale PID file
            try:
                self._pid_file.unlink()
            except OSError:
                pass  # Stale PID file cleanup is best-effort
            return False

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

        Args:
            state: The TaskState to save.
            validate_transition: If True, validates state transition (default True).

        Raises:
            InvalidStateTransitionError: If the state transition is invalid.
            StatePermissionError: If the file cannot be written.
            StateLockError: If the file lock cannot be acquired.
        """
        # Validate state transition if there's an existing state
        if validate_transition and self.state_file.exists():
            try:
                current_state = self._load_state_internal()
                self._validate_transition(current_state.status, state.status)
            except (StateNotFoundError, StateCorruptedError):
                # If we can't load current state, allow the save
                pass

        state.updated_at = datetime.now().isoformat()

        with file_lock(self._lock_file, timeout=self.LOCK_TIMEOUT):
            try:
                # Use atomic write with temp file
                # Use mode='json' to ensure datetime fields are serialized as ISO strings
                self._atomic_write_json(self.state_file, state.model_dump(mode="json"))
            except PermissionError as e:
                raise StatePermissionError(self.state_file, "writing", e) from e

    def load_state(self) -> TaskState:
        """Load state from state.json with error recovery.

        Returns:
            TaskState: The loaded task state.

        Raises:
            StateNotFoundError: If the state file does not exist.
            StateCorruptedError: If the state file is corrupted and cannot be recovered.
            StateValidationError: If the state data fails validation.
            StatePermissionError: If the file cannot be read.
            StateLockError: If the file lock cannot be acquired.
        """
        with file_lock(self._lock_file, timeout=self.LOCK_TIMEOUT, exclusive=False):
            return self._load_state_internal()

    def _load_state_internal(self) -> TaskState:
        """Internal method to load state without locking.

        This is used by save_state to check transitions without deadlock.
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
        """Atomically write JSON data to a file using a temp file.

        Args:
            path: The target file path.
            data: The data to write as JSON.
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temp file in the same directory, then rename
        fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".json")
        try:
            with open(fd, "w") as f:
                json.dump(data, f, indent=2)
            # Atomic rename
            shutil.move(temp_path, path)
        except Exception:
            # Clean up temp file on error
            try:
                Path(temp_path).unlink()
            except Exception:
                pass  # Temp file cleanup is best-effort
            raise

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

        # Allow index == len(tasks) since it means all tasks are complete
        if tasks and state.current_task_index > len(tasks):
            raise StateResumeValidationError(
                "Task index exceeds number of tasks in plan",
                status=state.status,
                current_task_index=state.current_task_index,
                total_tasks=len(tasks),
                suggestion="Task state may be out of sync with plan. Use 'clean' to start fresh.",
            )

        return state

    # _parse_plan_tasks is inherited from FileOperationsMixin

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
    # - _create_backup(file_path: Path, suffix: str = "") -> Path | None
    # - create_state_backup() -> Path | None
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
