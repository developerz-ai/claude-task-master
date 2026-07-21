"""State data models, schema versioning, and the file-lock context manager.

This module provides the core data structures used throughout the state
management system:

- :class:`TaskOptions` — run-time task configuration
- :class:`TaskState` — machine-readable task state persisted to ``state.json``
- :data:`CURRENT_SCHEMA_VERSION` / :data:`_STATE_MIGRATIONS` — schema evolution
- :func:`file_lock` — cross-process exclusive/shared file-lock helper
"""

from __future__ import annotations

import fcntl
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Literal

from pydantic import BaseModel

from claude_task_master.core.state_exceptions import StateLockError

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
    # Hand a merge conflict to an agent session (merge base → resolve hunks → test →
    # commit → push) instead of blocking for manual resolution. Bounded by
    # MAX_CONFLICT_FIX_ATTEMPTS; an unresolved conflict still blocks.
    resolve_conflicts: bool = True
    # Require the PR branch to carry the latest base ("production") commits before
    # merging: when it is behind, an agent session merges the base in, re-runs the
    # tests, and pushes, so CI verifies the *combined* tree before the merge.
    sync_before_merge: bool = True


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
    "resolving_conflicts",
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
    # Conflict-resolution fields
    conflict_fix_attempts: int = 0  # Number of conflict-resolution agent sessions for current PR
    branch_sync_attempts: int = 0  # Number of base-sync agent sessions for current PR
    # Release phase fields
    release_fix_attempts: int = 0  # Number of release fix attempts for current PR
    in_release_fix: bool = False  # True while current PR is a release-fix PR
    # Release-check failure output captured on FAIL and injected into the next
    # release-fix session's prompt as "## Failed Checks" so the fix agent isn't
    # blind. Cleared on task advance. Optional/defaulted → no schema bump needed.
    release_fix_details: str | None = None


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


__all__ = [
    "TaskOptions",
    "StatusType",
    "WorkflowStageType",
    "CURRENT_SCHEMA_VERSION",
    "_STATE_MIGRATIONS",
    "TaskState",
    "file_lock",
]
