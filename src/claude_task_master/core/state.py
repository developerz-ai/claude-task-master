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


# Status type alias for type checking
StatusType = Literal["planning", "working", "blocked", "paused", "success", "failed"]


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

    status: StatusType  # planning|working|blocked|paused|success|failed
    workflow_stage: WorkflowStageType | None = None  # PR lifecycle stage
    current_task_index: int = 0
    session_count: int = 0
    current_pr: int | None = None
    created_at: str
    updated_at: str
    run_id: str
    model: str
    options: TaskOptions


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


class StateManager:
    """Manages all state persistence."""

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
                    pass
        except OSError:
            pass

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
                pass
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
                self._atomic_write_json(self.state_file, state.model_dump())
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
                    recovered_state = self._attempt_recovery(e)
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
            recovered_state = self._attempt_recovery(ValueError("Empty JSON object"))
            if recovered_state:
                return recovered_state
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
                pass
            raise

    def _attempt_recovery(self, original_error: Exception) -> TaskState | None:
        """Attempt to recover state from backup.

        Args:
            original_error: The error that triggered recovery.

        Returns:
            TaskState if recovery successful, None otherwise.
        """
        # First, create a backup of the corrupted file
        if self.state_file.exists():
            self._create_backup(self.state_file, suffix=".corrupted")

        # Try to recover from backup
        if self.backup_dir.exists():
            # Get the most recent backup
            backups = sorted(
                self.backup_dir.glob("state.*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            for backup_file in backups:
                try:
                    with open(backup_file) as f:
                        data = json.load(f)
                    state = TaskState(**data)
                    # Restore from backup
                    self._atomic_write_json(self.state_file, data)
                    return state
                except (json.JSONDecodeError, ValidationError):
                    continue

        return None

    def _create_backup(self, file_path: Path, suffix: str = "") -> Path | None:
        """Create a backup of a file.

        Args:
            file_path: The file to backup.
            suffix: Optional suffix to add to backup name.

        Returns:
            Path to the backup file, or None if backup failed.
        """
        if not file_path.exists():
            return None

        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_name = f"{file_path.stem}.{timestamp}{suffix}{file_path.suffix}"
            backup_path = self.backup_dir / backup_name
            shutil.copy2(file_path, backup_path)
            return backup_path
        except Exception:
            return None

    def create_state_backup(self) -> Path | None:
        """Create a backup of the current state file.

        Returns:
            Path to the backup file, or None if backup failed.
        """
        return self._create_backup(self.state_file)

    def save_goal(self, goal: str) -> None:
        """Save goal to goal.txt."""
        goal_file = self.state_dir / "goal.txt"
        goal_file.write_text(goal)

    def load_goal(self) -> str:
        """Load goal from goal.txt."""
        goal_file = self.state_dir / "goal.txt"
        return goal_file.read_text()

    def save_criteria(self, criteria: str) -> None:
        """Save success criteria to criteria.txt."""
        criteria_file = self.state_dir / "criteria.txt"
        criteria_file.write_text(criteria)

    def load_criteria(self) -> str | None:
        """Load success criteria from criteria.txt."""
        criteria_file = self.state_dir / "criteria.txt"
        if criteria_file.exists():
            return criteria_file.read_text()
        return None

    def save_plan(self, plan: str) -> None:
        """Save task plan to plan.md."""
        plan_file = self.state_dir / "plan.md"
        plan_file.write_text(plan)

    def load_plan(self) -> str | None:
        """Load task plan from plan.md."""
        plan_file = self.state_dir / "plan.md"
        if plan_file.exists():
            return plan_file.read_text()
        return None

    def save_progress(self, progress: str) -> None:
        """Save progress summary to progress.md."""
        progress_file = self.state_dir / "progress.md"
        progress_file.write_text(progress)

    def load_progress(self) -> str | None:
        """Load progress summary from progress.md."""
        progress_file = self.state_dir / "progress.md"
        if progress_file.exists():
            return progress_file.read_text()
        return None

    def save_context(self, context: str) -> None:
        """Save accumulated context to context.md."""
        context_file = self.state_dir / "context.md"
        context_file.write_text(context)

    def load_context(self) -> str:
        """Load accumulated context from context.md."""
        context_file = self.state_dir / "context.md"
        if context_file.exists():
            return context_file.read_text()
        return ""

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

    def _parse_plan_tasks(self, plan: str) -> list[str]:
        """Parse tasks from plan markdown.

        Args:
            plan: The plan content in markdown format.

        Returns:
            List of task descriptions extracted from the plan.
        """
        tasks = []
        for line in plan.split("\n"):
            # Look for markdown checkbox lines
            stripped = line.strip()
            if stripped.startswith("- [ ]") or stripped.startswith("- [x]"):
                task = stripped[5:].strip()  # Remove "- [ ]" or "- [x]"
                if task:
                    tasks.append(task)
        return tasks

    def cleanup_on_success(self, run_id: str) -> None:
        """Clean up all state files except logs on success."""
        # Release session lock first
        self.release_session_lock()

        # Delete all files in state directory except logs/
        for item in self.state_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir() and item != self.logs_dir:
                shutil.rmtree(item)

        # Keep only the last 10 log files
        self._cleanup_old_logs(max_logs=10)

    def _cleanup_old_logs(self, max_logs: int = 10) -> None:
        """Keep only the most recent log files."""
        if not self.logs_dir.exists():
            return

        # Get all log files sorted by modification time (newest first)
        log_files = sorted(
            self.logs_dir.glob("run-*.txt"), key=lambda p: p.stat().st_mtime, reverse=True
        )

        # Delete older logs
        for log_file in log_files[max_logs:]:
            log_file.unlink()

    # =========================================================================
    # PR Context Methods - Store PR info to help Claude understand context
    # =========================================================================

    def get_pr_dir(self, pr_number: int) -> Path:
        """Get the directory for a specific PR's context.

        Structure: .claude-task-master/debugging/pr/{number}/
        """
        pr_dir = self.state_dir / "debugging" / "pr" / str(pr_number)
        pr_dir.mkdir(parents=True, exist_ok=True)
        return pr_dir

    def save_pr_comments(self, pr_number: int, comments: list[dict]) -> None:
        """Save PR comments to files for Claude to read.

        Each comment is saved to a separate file for easy reading.

        Args:
            pr_number: The PR number.
            comments: List of comment dicts with author, path, line, body.
        """
        pr_dir = self.get_pr_dir(pr_number)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(exist_ok=True)

        # Clear old comments
        for old_file in comments_dir.glob("*.txt"):
            old_file.unlink()

        # Save each comment to a separate file
        for i, comment in enumerate(comments, 1):
            thread_id = comment.get("thread_id", "")
            comment_id = comment.get("comment_id", "")
            author = comment.get("author", "unknown")
            path = comment.get("path", "general")
            line = comment.get("line", "N/A")
            body = comment.get("body", "")
            is_resolved = comment.get("is_resolved", False)

            # Create filename from sanitized path
            safe_path = path.replace("/", "_").replace("\\", "_") if path else "general"
            # Sanitize line number (could be "N/A" or None)
            safe_line = str(line).replace("/", "_").replace("\\", "_") if line else "0"
            filename = f"{i:03d}_{safe_path}_L{safe_line}.txt"

            content = f"""Thread ID: {thread_id}
Comment ID: {comment_id}
File: {path}
Line: {line}
Author: {author}
Status: {"Resolved" if is_resolved else "Unresolved"}

{body}
"""
            (comments_dir / filename).write_text(content)

        # Also save a summary file
        summary_file = pr_dir / "comments_summary.txt"
        summary_lines = [
            f"PR #{pr_number} Review Comments",
            f"Total: {len(comments)} comments",
            "",
            "Files with comments:",
        ]
        paths = {c.get("path", "general") for c in comments}
        for p in sorted(paths):
            summary_lines.append(f"  - {p}")

        summary_file.write_text("\n".join(summary_lines))

    def save_ci_failure(self, pr_number: int, check_name: str, logs: str) -> None:
        """Save CI failure logs for Claude to read.

        Args:
            pr_number: The PR number.
            check_name: Name of the failing check.
            logs: The failure logs.
        """
        pr_dir = self.get_pr_dir(pr_number)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(exist_ok=True)

        # Sanitize check name for filename
        safe_name = check_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
        filename = f"failed_{safe_name}.txt"

        content = f"""CI Check Failed: {check_name}
PR: #{pr_number}

{"=" * 60}
FAILURE LOGS:
{"=" * 60}

{logs}
"""
        (ci_dir / filename).write_text(content)

    def load_pr_context(self, pr_number: int) -> str:
        """Load all PR context (comments + CI failures) as a single string.

        This gives Claude all the context it needs to address issues.

        Args:
            pr_number: The PR number.

        Returns:
            Combined context string.
        """
        pr_dir = self.get_pr_dir(pr_number)
        if not pr_dir.exists():
            return ""

        sections = []

        # Load comments
        comments_dir = pr_dir / "comments"
        if comments_dir.exists():
            comment_files = sorted(comments_dir.glob("*.txt"))
            if comment_files:
                sections.append("## Review Comments\n")
                for cf in comment_files:
                    sections.append(f"### {cf.stem}\n{cf.read_text()}\n")

        # Load CI failures
        ci_dir = pr_dir / "ci"
        if ci_dir.exists():
            ci_files = sorted(ci_dir.glob("failed_*.txt"))
            if ci_files:
                sections.append("## CI Failures\n")
                for cf in ci_files:
                    sections.append(cf.read_text())

        return "\n".join(sections)

    def clear_pr_context(self, pr_number: int) -> None:
        """Clear PR context after PR is merged.

        Args:
            pr_number: The PR number.
        """
        # Use the same path structure as get_pr_dir
        pr_dir = self.state_dir / "debugging" / "pr" / str(pr_number)
        if pr_dir.exists():
            shutil.rmtree(pr_dir)
