"""Backup and Recovery Operations for State Manager.

This module provides methods for managing state backups, recovery from
corruption, and cleanup operations.

These methods are mixed into the StateManager class via the BackupRecoveryMixin.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError


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

    def _attempt_recovery(self, original_error: Exception) -> Any:
        """Attempt to recover state from backup.

        Args:
            original_error: The error that triggered recovery.

        Returns:
            TaskState if recovery successful, None otherwise.
        """
        # Import here to avoid circular dependency at module level
        from claude_task_master.core.state import TaskState

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

    def cleanup_on_success(self, run_id: str) -> None:
        """Clean up all state files except logs on success.

        Args:
            run_id: The run ID (used for identifying which log file belongs to this run).
        """
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
