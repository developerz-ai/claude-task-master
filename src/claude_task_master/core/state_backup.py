"""Backup and Recovery Operations for State Manager.

This module provides methods for managing state backups, recovery from
corruption, and cleanup operations.

These methods are mixed into the StateManager class via the BackupRecoveryMixin.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

if TYPE_CHECKING:
    from claude_task_master.core.state import TaskState

logger = logging.getLogger(__name__)


class BackupRecoveryMixin:
    """Mixin providing backup and recovery methods for StateManager.

    This mixin adds methods to handle state backups, recovery from corruption,
    and cleanup operations.

    Requires (provided by StateManager):
        - self.state_dir: Path to the state directory
        - self.state_file: Path property to the state.json file
        - self.backup_dir: Path property to the backup directory
        - self.logs_dir: Path to the logs directory
        - self.release_session_lock(): Method to release session lock
        - self._atomic_write_json(): Method to atomically write JSON
    """

    # Type annotations for attributes provided by StateManager
    state_dir: Path
    logs_dir: Path

    # Backup rotation + staleness policy (overridable per class/instance).
    #: Most-recent regular backups to retain; older ones are pruned on save.
    MAX_STATE_BACKUPS: int = 10
    #: Refuse to restore a backup older than the corrupt state file by more
    #: than this many seconds (silently rolling back merged tasks / created
    #: PRs is worse than surfacing the corruption for manual intervention).
    STALE_BACKUP_THRESHOLD_SECONDS: float = 3600.0

    @property
    def state_file(self) -> Path:
        """Path to the state.json file - provided by StateManager."""
        raise NotImplementedError("Provided by StateManager")

    @property
    def backup_dir(self) -> Path:
        """Path to the backup directory - provided by StateManager."""
        raise NotImplementedError("Provided by StateManager")

    def release_session_lock(self) -> None:
        """Release session lock - provided by StateManager."""
        raise NotImplementedError("Provided by StateManager")

    def _atomic_write_json(self, path: Path, data: dict) -> None:
        """Atomically write JSON data - provided by StateManager."""
        raise NotImplementedError("Provided by StateManager")

    def _attempt_recovery(self, original_error: Exception) -> TaskState | None:
        """Recover state from the newest backup that is not stale.

        Preserves the corrupt file as a ``.corrupted`` backup for diagnostics,
        then restores the newest valid backup via :meth:`find_recoverable_state`.
        Recovery is refused (returns ``None``) when the freshest backup is
        materially older than the corrupt state file, so a crash mid-write never
        silently rolls back completed work (merged tasks, created PRs, ``--prs``
        counters).

        On success this writes the healed state back to ``state.json`` via
        :meth:`_atomic_write_json`, so the caller MUST hold the exclusive state
        lock. Both call sites reach it through ``_load_state_internal`` under
        ``file_lock``.

        Args:
            original_error: The error that triggered recovery (logged only).

        Returns:
            The recovered TaskState if a fresh-enough backup exists, else None.
        """
        logger.debug("Attempting state recovery after: %s", original_error)

        reference_time: datetime | None = None
        if self.state_file.exists():
            try:
                reference_time = datetime.fromtimestamp(self.state_file.stat().st_mtime)
            except OSError:
                reference_time = None
            # Preserve the corrupt file for diagnostics before overwriting it.
            self._create_backup(self.state_file, suffix=".corrupted")

        recovered = self.find_recoverable_state(reference_time)
        if recovered is not None:
            self._atomic_write_json(self.state_file, recovered.model_dump(mode="json"))
        return recovered

    def find_recoverable_state(self, reference_time: datetime | None = None) -> TaskState | None:
        """Return the newest valid backup state, refusing stale ones.

        Scans regular backups newest-first and returns the first that parses
        into a valid TaskState — unless that backup's ``updated_at`` predates
        ``reference_time`` by more than :attr:`STALE_BACKUP_THRESHOLD_SECONDS`,
        in which case a loud warning is logged and ``None`` is returned rather
        than silently rolling back completed work. Performs no writes; callers
        decide whether to persist the result.

        Args:
            reference_time: Last-known-good write time (typically the corrupt
                state file's mtime) to measure staleness against. ``None`` skips
                the staleness check when there is nothing to compare against.

        Returns:
            The recovered TaskState, or ``None`` if no valid backup exists or the
            newest valid one is too stale to trust.
        """
        # Import here to avoid a circular import at module load time.
        from claude_task_master.core.state import TaskState

        for backup_file in self._regular_backups():
            try:
                with open(backup_file) as f:
                    data = json.load(f)
                state = TaskState(**data)
            except (OSError, json.JSONDecodeError, ValidationError):
                continue

            staleness = self._backup_staleness_seconds(state, reference_time)
            if staleness is not None and staleness > self.STALE_BACKUP_THRESHOLD_SECONDS:
                logger.warning(
                    "Refusing to restore stale state backup %s: it is %.0fs older than "
                    "the last write to the corrupt state file (threshold %.0fs). Restoring "
                    "it would roll back completed work (merged tasks, created PRs). Manual "
                    "intervention required — inspect %s and its backups.",
                    backup_file.name,
                    staleness,
                    self.STALE_BACKUP_THRESHOLD_SECONDS,
                    self.state_file,
                )
                return None
            return state

        return None

    @staticmethod
    def _backup_staleness_seconds(
        state: TaskState, reference_time: datetime | None
    ) -> float | None:
        """Seconds by which a backup predates ``reference_time``.

        Args:
            state: The candidate backup state.
            reference_time: The last-known-good write time to compare against.

        Returns:
            Positive seconds when the backup is older than ``reference_time``,
            zero/negative when it is newer, or ``None`` when staleness cannot be
            determined (no reference, or an unparseable/timezone-aware
            ``updated_at``).
        """
        if reference_time is None:
            return None
        try:
            backup_time = datetime.fromisoformat(state.updated_at)
            return (reference_time - backup_time).total_seconds()
        except (ValueError, TypeError):
            return None

    def _create_backup(self, file_path: Path, suffix: str = "") -> Path | None:
        """Create a backup of a file with a collision-free name.

        Because a backup is taken on every ``save_state`` (potentially several
        within the same second), the second-resolution timestamp is not unique
        on its own; a ``.NNN`` disambiguator is appended when the base name is
        already taken so back-to-back saves never clobber each other's backup.

        Args:
            file_path: The file to backup.
            suffix: Optional suffix to add to backup name (e.g. ``.corrupted``).

        Returns:
            Path to the backup file, or None if backup failed.
        """
        if not file_path.exists():
            return None

        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = (
                self.backup_dir / f"{file_path.stem}.{timestamp}{suffix}{file_path.suffix}"
            )
            seq = 1
            while backup_path.exists():
                backup_path = (
                    self.backup_dir
                    / f"{file_path.stem}.{timestamp}.{seq:03d}{suffix}{file_path.suffix}"
                )
                seq += 1
            shutil.copy2(file_path, backup_path)
            return backup_path
        except Exception:
            return None

    def create_state_backup(self) -> Path | None:
        """Create a rotating backup of the current state file.

        Copies ``state.json`` into the backup directory, then prunes old regular
        backups down to :attr:`MAX_STATE_BACKUPS` (diagnostic ``.corrupted``
        backups are never pruned). Best-effort: rotation failures never
        propagate, so a save that already succeeded is not undone by a cleanup
        hiccup.

        Returns:
            Path to the backup file, or None if there is no state file to back
            up or the copy failed.
        """
        backup_path = self._create_backup(self.state_file)
        if backup_path is not None:
            self._rotate_backups(self.MAX_STATE_BACKUPS)
        return backup_path

    def _regular_backups(self) -> list[Path]:
        """Return regular state backups, newest first.

        Excludes diagnostic ``.corrupted`` backups. Files that vanish mid-scan
        (a concurrent rotation or cleanup) are skipped rather than raising.

        Returns:
            Backup paths sorted by modification time, newest first.
        """
        if not self.backup_dir.exists():
            return []
        candidates = [
            p for p in self.backup_dir.glob("state.*.json") if ".corrupted." not in p.name
        ]

        def _mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return -1.0

        return sorted(candidates, key=_mtime, reverse=True)

    def _rotate_backups(self, keep: int) -> None:
        """Prune old regular backups, retaining the newest ``keep``.

        Best-effort: any error (a race with a concurrent writer, a vanishing
        file) is swallowed so rotation can never break a state save. Diagnostic
        ``.corrupted`` backups are never pruned.

        Args:
            keep: Number of most-recent regular backups to retain.
        """
        if keep < 0:
            return
        for backup_file in self._regular_backups()[keep:]:
            try:
                backup_file.unlink()
            except OSError:
                continue

    def cleanup_on_success(self, run_id: str) -> None:
        """Clean up all state files except logs, coding-style.md, and release.md on success.

        Preserves:
        - logs/ directory (keeps last 10 log files)
        - coding-style.md (reusable across runs to save tokens)
        - release.md (reusable across runs to save tokens)

        Args:
            run_id: The run ID (used for identifying which log file belongs to this run).
        """
        # Release session lock first
        self.release_session_lock()

        # Files to preserve (besides logs/ directory)
        preserved_files = {"coding-style.md", "release.md"}

        # Delete all files in state directory except preserved ones and logs/
        for item in self.state_dir.iterdir():
            if item.is_file():
                if item.name not in preserved_files:
                    item.unlink()
            elif item.is_dir() and item != self.logs_dir:
                shutil.rmtree(item)

        # Keep only the last 10 log files
        self._cleanup_old_logs(max_logs=10)

    def _cleanup_old_logs(self, max_logs: int = 10) -> None:
        """Keep only the most recent log files.

        Args:
            max_logs: Maximum number of log files to keep.
        """
        if not self.logs_dir.exists():
            return

        # Get all log files sorted by modification time (newest first)
        log_files = sorted(
            self.logs_dir.glob("run-*.txt"), key=lambda p: p.stat().st_mtime, reverse=True
        )

        # Delete older logs
        for log_file in log_files[max_logs:]:
            log_file.unlink()
