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

    @staticmethod
    def _migrate_state(data: dict) -> dict:
        """Migrate a raw state dict to the current schema - provided by StateManager.

        Raises StateValidationError for state written by a newer, unsupported
        schema version.
        """
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
        from claude_task_master.core.state_exceptions import StateValidationError

        for backup_file in self._regular_backups():
            try:
                with open(backup_file) as f:
                    data = json.load(f)
                # Route the backup through the same schema-compatibility boundary
                # as the primary state file: older backups are migrated forward,
                # and a backup written by a *newer* schema raises
                # StateValidationError here and is skipped rather than loaded with
                # its unknown fields silently dropped.
                data = self._migrate_state(data)
                state = TaskState(**data)
            except (
                OSError,
                json.JSONDecodeError,
                ValidationError,
                StateValidationError,
                TypeError,
            ):
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
            # Compare via POSIX timestamps rather than subtracting the datetimes:
            # a timezone-aware ``updated_at`` minus the naive ``reference_time``
            # raises TypeError, which was swallowed and let a stale backup slip
            # past the guard. ``.timestamp()`` yields a comparable epoch for both
            # naive and aware datetimes.
            return reference_time.timestamp() - backup_time.timestamp()
        except (ValueError, TypeError, OSError, OverflowError):
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

    @staticmethod
    def _backup_order_key(path: Path) -> tuple[str, int, float]:
        """Deterministic creation-order sort key for a backup (newest = largest).

        Backups are named ``state.<ts>.json`` (the first write in a given
        second) or ``state.<ts>.NNN.json`` (later writes that second), where
        ``<ts>`` is a zero-padded ``%Y%m%d-%H%M%S`` stamp and ``NNN`` an
        incrementing disambiguator. Ordering by ``(timestamp, sequence)``
        reproduces creation order exactly.

        Modification time cannot: :func:`shutil.copy2` copies the *source*
        file's mtime onto the backup, so several backups of a ``state.json``
        written within one mtime tick collide on mtime and sort arbitrarily by
        glob order — which silently restored (or rotation-pruned) the wrong
        backup. mtime is retained only as a final tiebreak for any file whose
        name does not match the expected pattern.

        Args:
            path: A backup file path.

        Returns:
            ``(timestamp, sequence, mtime)`` — larger is newer.
        """
        stem = path.name[: -len(path.suffix)] if path.suffix else path.name
        parts = stem.split(".")  # ["state", "<ts>"] or ["state", "<ts>", "NNN"]
        timestamp = parts[1] if len(parts) >= 2 else ""
        sequence = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 0
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = -1.0
        return (timestamp, sequence, mtime)

    def _regular_backups(self) -> list[Path]:
        """Return regular state backups, newest first.

        Excludes diagnostic ``.corrupted`` backups. Files that vanish mid-scan
        (a concurrent rotation or cleanup) are skipped rather than raising.
        Ordering is by the filename-encoded creation timestamp and sequence
        (see :meth:`_backup_order_key`), which is deterministic even when
        several backups share an mtime.

        Returns:
            Backup paths in creation order, newest first.
        """
        if not self.backup_dir.exists():
            return []
        candidates = [
            p for p in self.backup_dir.glob("state.*.json") if ".corrupted." not in p.name
        ]
        return sorted(candidates, key=self._backup_order_key, reverse=True)

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

        # Files to preserve (besides logs/ directory).
        # Include lock/pid files so an interrupted cleanup doesn't leave the
        # session permanently locked if the process restarts before releasing.
        preserved_files = {"coding-style.md", "release.md", ".state.lock", ".pid"}

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

        # Get all log files sorted by modification time (newest first).
        # Guard against files that vanish between glob and stat (concurrent
        # rotation or cleanup) — treat missing files as oldest so they sort
        # to the tail and are pruned, rather than raising.
        def _log_mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return -1.0

        # JSON logging writes ``run-*.jsonl`` alongside the text ``run-*.txt``;
        # both formats must be pruned or structured logs accumulate forever.
        log_files = sorted(
            [
                *self.logs_dir.glob("run-*.txt"),
                *self.logs_dir.glob("run-*.jsonl"),
            ],
            key=_log_mtime,
            reverse=True,
        )

        # Delete older logs
        for log_file in log_files[max_logs:]:
            try:
                log_file.unlink()
            except OSError:
                continue  # Already gone — best effort
