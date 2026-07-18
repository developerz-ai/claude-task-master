"""Tests for StateManager backup creation, rotation, and staleness guards.

This module contains tests for backup *creation* functionality including:
- State backup creation and validation
- Backup-on-every-save behavior and rotation to the cap
- Staleness-guarded restore (refusing materially stale backups)

Recovery from corrupted state lives in ``test_state_backup_recovery.py``;
``cleanup_on_success`` and log rotation live in ``test_state_cleanup.py``.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta

import pytest

from claude_task_master.core.state import (
    StateCorruptedError,
    StateManager,
    TaskOptions,
    TaskState,
)

# =============================================================================
# State Backup Tests
# =============================================================================


class TestStateBackupCreation:
    """Tests for state backup creation functionality."""

    def test_create_backup_returns_path(self, initialized_state_manager):
        """Test create_state_backup returns the backup path."""
        backup_path = initialized_state_manager.create_state_backup()
        assert backup_path is not None
        assert backup_path.exists()

    def test_backup_contains_state_data(self, initialized_state_manager):
        """Test that backup contains valid state data."""
        backup_path = initialized_state_manager.create_state_backup()

        with open(backup_path) as f:
            data = json.load(f)

        assert "status" in data
        assert "run_id" in data

    def test_multiple_backups_have_unique_names(self, initialized_state_manager):
        """Test that multiple backups have unique names."""
        time.sleep(0.01)  # Ensure different timestamps
        backup1 = initialized_state_manager.create_state_backup()
        time.sleep(1.1)  # Ensure different timestamp in seconds
        backup2 = initialized_state_manager.create_state_backup()

        assert backup1 != backup2
        assert backup1.exists()
        assert backup2.exists()

    def test_backup_no_file_returns_none(self, temp_dir):
        """Test create_state_backup returns None when no state file."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        manager = StateManager(state_dir)

        result = manager.create_state_backup()
        assert result is None

    def test_backup_directory_created(self, initialized_state_manager):
        """Test that backup directory is created automatically."""
        backup_path = initialized_state_manager.create_state_backup()
        assert initialized_state_manager.backup_dir.exists()
        assert backup_path.parent == initialized_state_manager.backup_dir

    def test_backup_preserves_all_state_fields(self, initialized_state_manager):
        """Test that backup preserves all state fields accurately."""
        # Modify state
        state = initialized_state_manager.load_state()
        state.status = "working"
        state.session_count = 5
        state.current_task_index = 2
        initialized_state_manager.save_state(state)

        # Create backup
        backup_path = initialized_state_manager.create_state_backup()

        # Verify backup content
        with open(backup_path) as f:
            backup_data = json.load(f)

        assert backup_data["status"] == "working"
        assert backup_data["session_count"] == 5
        assert backup_data["current_task_index"] == 2

    def test_backup_file_naming_format(self, initialized_state_manager):
        """Test that backup files have correct naming format."""
        backup_path = initialized_state_manager.create_state_backup()

        # Should be state.{timestamp}.json
        assert backup_path.name.startswith("state.")
        assert backup_path.suffix == ".json"
        # Timestamp format: YYYYMMDD-HHMMSS
        timestamp_part = backup_path.stem.split(".")[1]
        assert len(timestamp_part) == 15  # YYYYMMDD-HHMMSS
        assert "-" in timestamp_part

    def test_backup_returns_none_on_error(self, initialized_state_manager, monkeypatch):
        """Test _create_backup returns None when an error occurs."""
        import shutil

        # Mock shutil.copy2 to raise an exception
        def mock_copy2(*args, **kwargs):
            raise PermissionError("Cannot copy file")

        monkeypatch.setattr(shutil, "copy2", mock_copy2)

        # Backup should return None instead of raising
        result = initialized_state_manager.create_state_backup()
        assert result is None


# =============================================================================
# Backup-on-every-save Tests
# =============================================================================


def _regular_backups(manager: StateManager) -> list:
    """Return the manager's non-corrupted state backups."""
    return [p for p in manager.backup_dir.glob("state.*.json") if ".corrupted." not in p.name]


class TestBackupOnEverySave:
    """Tests that save_state creates a rotating backup on every write."""

    def test_initialize_creates_backup(self, initialized_state_manager):
        """initialize() saves state, which leaves a regular backup behind."""
        assert _regular_backups(initialized_state_manager)

    def test_save_state_creates_backup(self, initialized_state_manager):
        """Each successful save_state produces a regular backup."""
        # Clear backups written during initialize to isolate this save.
        for backup in _regular_backups(initialized_state_manager):
            backup.unlink()

        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        assert _regular_backups(initialized_state_manager)

    def test_invalid_transition_creates_no_backup(self, initialized_state_manager):
        """A rejected transition raises before writing, so no backup appears."""
        for backup in _regular_backups(initialized_state_manager):
            backup.unlink()

        state = initialized_state_manager.load_state()
        state.status = "success"  # planning -> success is invalid

        from claude_task_master.core.state import InvalidStateTransitionError

        with pytest.raises(InvalidStateTransitionError):
            initialized_state_manager.save_state(state)

        assert not _regular_backups(initialized_state_manager)


class TestBackupRotation:
    """Tests that old backups are pruned to MAX_STATE_BACKUPS."""

    @staticmethod
    def _seed_backups(manager: StateManager, count: int, *, base: int = 1_000_000) -> list:
        """Create `count` fake regular backups with strictly increasing mtimes."""
        manager.backup_dir.mkdir(parents=True, exist_ok=True)
        for existing in manager.backup_dir.glob("state.*.json"):
            existing.unlink()
        created = []
        for i in range(count):
            path = manager.backup_dir / f"state.fake-{i:04d}.json"
            path.write_text("{}")
            os.utime(path, (base + i, base + i))
            created.append(path)
        return created

    def test_rotate_keeps_newest_n(self, state_manager):
        """_rotate_backups retains only the newest `keep` regular backups."""
        keep = state_manager.MAX_STATE_BACKUPS
        created = self._seed_backups(state_manager, keep + 5)

        state_manager._rotate_backups(keep)

        remaining = {p.name for p in _regular_backups(state_manager)}
        assert len(remaining) == keep
        # The newest `keep` created files survive; the oldest 5 are pruned.
        for path in created[-keep:]:
            assert path.name in remaining
        for path in created[:5]:
            assert path.name not in remaining

    def test_rotate_preserves_corrupted_backups(self, state_manager):
        """Diagnostic .corrupted backups are never pruned by rotation."""
        self._seed_backups(state_manager, state_manager.MAX_STATE_BACKUPS + 3)
        corrupted = state_manager.backup_dir / "state.20260101-000000.corrupted.json"
        corrupted.write_text("garbage")

        state_manager._rotate_backups(state_manager.MAX_STATE_BACKUPS)

        assert corrupted.exists()

    def test_rotate_noop_when_under_cap(self, state_manager):
        """Rotation keeps everything when the count is within the cap."""
        created = self._seed_backups(state_manager, 3)

        state_manager._rotate_backups(state_manager.MAX_STATE_BACKUPS)

        assert len(_regular_backups(state_manager)) == len(created)

    def test_create_state_backup_enforces_cap(self, initialized_state_manager):
        """create_state_backup copies state then prunes down to the cap."""
        manager = initialized_state_manager
        keep = manager.MAX_STATE_BACKUPS
        self._seed_backups(manager, keep + 4)

        manager.create_state_backup()

        assert len(_regular_backups(manager)) == keep

    def test_save_state_enforces_cap(self, initialized_state_manager):
        """Repeated saves never let regular backups exceed the cap."""
        manager = initialized_state_manager
        keep = manager.MAX_STATE_BACKUPS
        self._seed_backups(manager, keep + 6)

        state = manager.load_state()
        state.status = "working"
        manager.save_state(state)

        assert len(_regular_backups(manager)) == keep


# =============================================================================
# Staleness-guarded Restore Tests
# =============================================================================


class TestStalenessGuardedRestore:
    """Tests that recovery refuses to restore a materially stale backup."""

    @staticmethod
    def _write_backup(manager: StateManager, name: str, *, updated_at: str) -> None:
        """Write a valid TaskState backup with a chosen updated_at timestamp."""
        manager.backup_dir.mkdir(parents=True, exist_ok=True)
        state = TaskState(
            status="working",
            current_task_index=3,
            session_count=7,
            created_at=updated_at,
            updated_at=updated_at,
            run_id="run-x",
            model="sonnet",
            options=TaskOptions(),
        )
        (manager.backup_dir / name).write_text(json.dumps(state.model_dump(mode="json")))

    def test_fresh_backup_is_restored(self, state_manager):
        """A backup close to the reference time is restored."""
        now = datetime.now()
        self._write_backup(state_manager, "state.20260101-000000.json", updated_at=now.isoformat())

        result = state_manager.find_recoverable_state(reference_time=now)

        assert result is not None
        assert result.session_count == 7

    def test_stale_backup_is_refused(self, state_manager, caplog):
        """A backup far older than the reference time is refused, loudly."""
        now = datetime.now()
        stale = (now - timedelta(hours=2)).isoformat()
        self._write_backup(state_manager, "state.20260101-000000.json", updated_at=stale)

        with caplog.at_level(logging.WARNING):
            result = state_manager.find_recoverable_state(reference_time=now)

        assert result is None
        assert any("stale" in message.lower() for message in caplog.messages)

    def test_backup_just_under_threshold_is_restored(self, state_manager):
        """A backup within the staleness threshold is still restored."""
        now = datetime.now()
        recent = (
            now - timedelta(seconds=state_manager.STALE_BACKUP_THRESHOLD_SECONDS - 60)
        ).isoformat()
        self._write_backup(state_manager, "state.20260101-000000.json", updated_at=recent)

        result = state_manager.find_recoverable_state(reference_time=now)

        assert result is not None

    def test_no_reference_time_skips_staleness(self, state_manager):
        """Without a reference time, staleness cannot be judged → restore."""
        ancient = (datetime.now() - timedelta(days=5)).isoformat()
        self._write_backup(state_manager, "state.20260101-000000.json", updated_at=ancient)

        result = state_manager.find_recoverable_state(reference_time=None)

        assert result is not None

    def test_load_state_refuses_stale_backup(self, state_manager):
        """load_state raises unrecoverable when only a stale backup exists."""
        stale = (datetime.now() - timedelta(hours=6)).isoformat()
        self._write_backup(state_manager, "state.20260101-000000.json", updated_at=stale)

        state_manager.state_dir.mkdir(parents=True, exist_ok=True)
        state_manager.state_file.write_text("{ corrupt json")

        with pytest.raises(StateCorruptedError) as exc_info:
            state_manager.load_state()

        assert exc_info.value.recoverable is False

    def test_load_state_recovers_fresh_backup(self, state_manager):
        """load_state recovers when the newest backup is fresh vs the corrupt file."""
        fresh = datetime.now().isoformat()
        self._write_backup(state_manager, "state.20260101-000000.json", updated_at=fresh)

        state_manager.state_dir.mkdir(parents=True, exist_ok=True)
        state_manager.state_file.write_text("{ corrupt json")

        recovered = state_manager.load_state()

        assert recovered.session_count == 7
        assert recovered.run_id == "run-x"
