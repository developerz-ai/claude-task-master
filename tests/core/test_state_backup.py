"""Tests for StateManager backup and recovery operations.

This module contains tests for backup and recovery functionality including:
- State backup creation and validation
- Recovery from corrupted state files
- Cleanup operations (success cleanup, log rotation)
- Session lock management during cleanup
"""

import json
import shutil
import time

import pytest

from claude_task_master.core.state import (
    StateCorruptedError,
    StateManager,
    StateValidationError,
    TaskOptions,
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


# =============================================================================
# Corrupted State Recovery Tests
# =============================================================================


class TestCorruptedStateRecovery:
    """Tests for corrupted state file recovery."""

    def test_load_corrupted_json_raises_error(self, temp_dir):
        """Test loading corrupted JSON raises StateCorruptedError."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        state_file.write_text("{ invalid json }")

        manager = StateManager(state_dir)

        with pytest.raises(StateCorruptedError) as exc_info:
            manager.load_state()

        assert exc_info.value.path == state_file

    def test_load_empty_json_raises_error(self, temp_dir):
        """Test loading empty JSON raises StateCorruptedError."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        state_file.write_text("{}")

        manager = StateManager(state_dir)

        with pytest.raises(StateCorruptedError):
            manager.load_state()

    def test_load_partial_state_raises_validation_error(self, temp_dir):
        """Test loading partial state raises StateValidationError."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        # Missing required fields
        state_file.write_text('{"status": "working"}')

        manager = StateManager(state_dir)

        with pytest.raises(StateValidationError) as exc_info:
            manager.load_state()

        assert len(exc_info.value.missing_fields) > 0

    def test_recovery_from_backup(self, temp_dir):
        """Test recovery from backup when state is corrupted."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        # Create valid initial state
        options = TaskOptions()
        original_state = manager.initialize(goal="Test", model="sonnet", options=options)

        # Create backup
        backup_path = manager.create_state_backup()
        assert backup_path is not None
        assert backup_path.exists()

        # Corrupt the state file
        manager.state_file.write_text("corrupted")

        # Load should recover from backup
        recovered_state = manager.load_state()
        assert recovered_state.run_id == original_state.run_id

    def test_corrupted_backup_creates_backup(self, temp_dir):
        """Test that corrupted file is backed up before recovery."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        # Create valid initial state
        options = TaskOptions()
        manager.initialize(goal="Test", model="sonnet", options=options)

        # Create backup for recovery
        manager.create_state_backup()

        # Corrupt the state file
        manager.state_file.write_text("corrupted content")

        # Load will attempt recovery
        manager.load_state()

        # Check that corrupted backup was created
        corrupted_backups = list(manager.backup_dir.glob("*.corrupted.json"))
        assert len(corrupted_backups) > 0

    def test_no_backup_available_raises_error(self, temp_dir):
        """Test that missing backup raises unrecoverable error."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        state_file.write_text("corrupted")

        manager = StateManager(state_dir)

        with pytest.raises(StateCorruptedError) as exc_info:
            manager.load_state()

        assert exc_info.value.recoverable is False

    def test_recovery_uses_most_recent_backup(self, temp_dir):
        """Test that recovery uses the most recent valid backup."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        # Create initial state
        options = TaskOptions()
        manager.initialize(goal="Test", model="sonnet", options=options)

        # Create first backup
        manager.create_state_backup()
        time.sleep(0.1)

        # Update state and create second backup
        state = manager.load_state()
        state.session_count = 5
        manager.save_state(state)
        time.sleep(1.1)  # Ensure different timestamp
        manager.create_state_backup()

        # Corrupt state file
        manager.state_file.write_text("corrupted")

        # Recovery should use most recent backup (with session_count=5)
        recovered = manager.load_state()
        assert recovered.session_count == 5

    def test_recovery_skips_corrupted_backups(self, temp_dir):
        """Test that recovery skips corrupted backup files."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        # Create valid state and backup
        options = TaskOptions()
        original_state = manager.initialize(goal="Test", model="sonnet", options=options)
        manager.create_state_backup()
        time.sleep(1.1)

        # Create a newer but corrupted backup
        corrupted_backup = manager.backup_dir / "state.99991231-235959.json"
        corrupted_backup.write_text("corrupted backup")

        # Corrupt the main state
        manager.state_file.write_text("corrupted")

        # Should recover from the valid (older) backup
        recovered = manager.load_state()
        assert recovered.run_id == original_state.run_id


# =============================================================================
# Cleanup Operations Tests
# =============================================================================


class TestStateManagerCleanup:
    """Tests for cleanup operations."""

    def test_cleanup_removes_state_files(self, initialized_state_manager):
        """Test cleanup removes state files."""
        # Add additional state files
        initialized_state_manager.save_plan("Test plan")
        initialized_state_manager.save_criteria("Test criteria")
        initialized_state_manager.save_progress("Test progress")
        initialized_state_manager.save_context("Test context")

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        state_dir = initialized_state_manager.state_dir
        assert not (state_dir / "state.json").exists()
        assert not (state_dir / "goal.txt").exists()
        assert not (state_dir / "plan.md").exists()
        assert not (state_dir / "criteria.txt").exists()
        assert not (state_dir / "progress.md").exists()
        assert not (state_dir / "context.md").exists()

    def test_cleanup_preserves_logs_dir(self, initialized_state_manager):
        """Test cleanup preserves logs directory."""
        run_id = initialized_state_manager.load_state().run_id

        # Create a log file
        log_file = initialized_state_manager.get_log_file(run_id)
        log_file.write_text("Test log")

        initialized_state_manager.cleanup_on_success(run_id)

        assert initialized_state_manager.logs_dir.exists()

    def test_cleanup_preserves_recent_logs(self, initialized_state_manager):
        """Test cleanup preserves recent log files."""
        logs_dir = initialized_state_manager.logs_dir
        # Create 5 log files (under the limit of 10)
        for i in range(5):
            log_file = logs_dir / f"run-test-{i:02d}.txt"
            log_file.write_text(f"Log {i}")
            time.sleep(0.01)

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        # All 5 logs should be preserved
        log_files = list(logs_dir.glob("run-*.txt"))
        assert len(log_files) == 5

    def test_cleanup_removes_nested_directories(self, initialized_state_manager):
        """Test cleanup removes nested directories."""
        # Create a nested directory
        nested_dir = initialized_state_manager.state_dir / "nested" / "deep"
        nested_dir.mkdir(parents=True)
        (nested_dir / "file.txt").write_text("content")

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        assert not (initialized_state_manager.state_dir / "nested").exists()

    def test_cleanup_handles_no_logs_dir(self, state_manager):
        """Test cleanup handles missing logs directory gracefully."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Initialize state without logs dir
        options = TaskOptions()
        state = state_manager.initialize(goal="Test", model="sonnet", options=options)

        # Remove logs dir
        if state_manager.logs_dir.exists():
            shutil.rmtree(state_manager.logs_dir)

        # Cleanup should not raise
        state_manager.cleanup_on_success(state.run_id)

    def test_cleanup_idempotent(self, initialized_state_manager):
        """Test cleanup can be called multiple times safely."""
        run_id = initialized_state_manager.load_state().run_id

        # First cleanup
        initialized_state_manager.cleanup_on_success(run_id)

        # Second cleanup should not raise
        initialized_state_manager.cleanup_on_success(run_id)

        assert initialized_state_manager.logs_dir.exists()

    def test_cleanup_removes_backup_directory(self, initialized_state_manager):
        """Test cleanup removes backup directory."""
        # Create a backup
        initialized_state_manager.create_state_backup()
        assert initialized_state_manager.backup_dir.exists()

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        assert not initialized_state_manager.backup_dir.exists()


# =============================================================================
# Log Rotation Tests
# =============================================================================


class TestLogRotation:
    """Tests for log file rotation during cleanup."""

    def test_cleanup_old_logs_removes_excess(self, initialized_state_manager):
        """Test cleanup removes old log files when over limit."""
        logs_dir = initialized_state_manager.logs_dir

        # Create 15 log files
        for i in range(15):
            log_file = logs_dir / f"run-2025011{i:02d}-120000.txt"
            log_file.write_text(f"Log content for session {i}")
            time.sleep(0.01)  # Small delay to ensure different mtime

        run_id = initialized_state_manager.load_state().run_id

        # Verify we have 15 log files
        assert len(list(logs_dir.glob("run-*.txt"))) == 15

        initialized_state_manager.cleanup_on_success(run_id)

        # Should only keep 10 most recent
        log_files = list(logs_dir.glob("run-*.txt"))
        assert len(log_files) == 10

    def test_cleanup_old_logs_keeps_newest(self, initialized_state_manager):
        """Test cleanup keeps the newest log files."""
        logs_dir = initialized_state_manager.logs_dir

        # Create 15 log files with distinct timestamps
        log_files_created = []
        for i in range(15):
            log_file = logs_dir / f"run-2025011{i:02d}-120000.txt"
            log_file.write_text(f"Log {i}")
            time.sleep(0.01)
            log_files_created.append(log_file)

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        # Get remaining log files
        remaining = {f.name for f in logs_dir.glob("run-*.txt")}

        # The 10 most recent (last 10 created) should remain
        for i in range(5, 15):
            expected_name = f"run-2025011{i:02d}-120000.txt"
            assert expected_name in remaining, f"Expected {expected_name} to be preserved"

    def test_log_rotation_at_exact_limit(self, initialized_state_manager):
        """Test log rotation when exactly at the limit."""
        logs_dir = initialized_state_manager.logs_dir

        # Create exactly 10 log files
        for i in range(10):
            log_file = logs_dir / f"run-test-{i:02d}.txt"
            log_file.write_text(f"Log {i}")
            time.sleep(0.01)

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        # All 10 should remain
        log_files = list(logs_dir.glob("run-*.txt"))
        assert len(log_files) == 10

    def test_log_rotation_empty_logs_dir(self, initialized_state_manager):
        """Test log rotation with empty logs directory."""
        # Ensure logs dir is empty
        for f in initialized_state_manager.logs_dir.glob("*"):
            f.unlink()

        run_id = initialized_state_manager.load_state().run_id

        # Should not raise
        initialized_state_manager.cleanup_on_success(run_id)

        # Logs dir should still exist
        assert initialized_state_manager.logs_dir.exists()


# =============================================================================
# Session Lock During Cleanup Tests
# =============================================================================


class TestCleanupSessionLock:
    """Tests for session lock behavior during cleanup."""

    def test_cleanup_releases_session_lock(self, initialized_state_manager):
        """Test cleanup releases the session lock."""
        run_id = initialized_state_manager.load_state().run_id

        # Verify lock exists before cleanup
        pid_file = initialized_state_manager._pid_file
        assert pid_file.exists()

        initialized_state_manager.cleanup_on_success(run_id)

        # Lock should be released
        assert not pid_file.exists()

    def test_cleanup_allows_new_session_after(self, temp_dir):
        """Test new session can be started after cleanup."""
        state_dir = temp_dir / ".claude-task-master"
        manager1 = StateManager(state_dir)

        # First session
        options = TaskOptions()
        state = manager1.initialize(goal="Test", model="sonnet", options=options)
        manager1.cleanup_on_success(state.run_id)

        # New session should succeed
        manager2 = StateManager(state_dir)
        state2 = manager2.initialize(goal="Test 2", model="sonnet", options=options)
        assert state2.status == "planning"


# =============================================================================
# Recovery Integration Tests
# =============================================================================


class TestBackupRecoveryIntegration:
    """Integration tests for backup and recovery workflow."""

    def test_state_survives_crash_recovery(self, initialized_state_manager):
        """Test state can be recovered after simulated crash."""
        # Modify state
        state = initialized_state_manager.load_state()
        state.status = "working"
        state.session_count = 3
        state.current_task_index = 2
        initialized_state_manager.save_state(state)
        initialized_state_manager.save_plan("Important plan")
        initialized_state_manager.save_progress("Important progress")

        run_id = state.run_id
        state_dir = initialized_state_manager.state_dir

        # Create new manager instance (simulating restart)
        new_manager = StateManager(state_dir)

        # Verify state is recovered
        recovered_state = new_manager.load_state()
        assert recovered_state.status == "working"
        assert recovered_state.session_count == 3
        assert recovered_state.current_task_index == 2
        assert recovered_state.run_id == run_id

        assert new_manager.load_plan() == "Important plan"
        assert new_manager.load_progress() == "Important progress"

    def test_backup_then_modify_then_recover(self, temp_dir):
        """Test full backup-modify-corrupt-recover cycle."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        # Initialize
        options = TaskOptions()
        original_state = manager.initialize(goal="Test", model="sonnet", options=options)

        # Modify and backup
        state = manager.load_state()
        state.status = "working"
        state.session_count = 10
        manager.save_state(state)
        manager.create_state_backup()

        # Further modify
        state.current_task_index = 5
        manager.save_state(state)
        manager.create_state_backup()

        # Corrupt state
        manager.state_file.write_text("totally corrupted")

        # Recover - should get latest valid state
        recovered = manager.load_state()
        assert recovered.run_id == original_state.run_id
        assert recovered.session_count == 10
        assert recovered.current_task_index == 5

    def test_cleanup_after_successful_workflow(self, temp_dir):
        """Test cleanup after complete successful workflow."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        # Full workflow
        options = TaskOptions(auto_merge=True, max_sessions=5)
        manager.initialize(goal="Complete the task", model="sonnet", options=options)

        manager.save_plan("## Tasks\n- [x] Task 1")
        manager.save_criteria("All tests pass")
        manager.save_progress("Task 1 completed")
        manager.save_context("Learned about codebase structure")

        # Create backups during work
        manager.create_state_backup()

        # Update to working
        state = manager.load_state()
        state.status = "working"
        state.session_count = 1
        manager.save_state(state)

        # Create log
        log_file = manager.get_log_file(state.run_id)
        log_file.write_text("Session log content")

        # Cleanup
        manager.cleanup_on_success(state.run_id)

        # Verify cleanup
        assert not manager.exists()
        assert manager.logs_dir.exists()
        assert not manager.backup_dir.exists()
        assert log_file.exists()  # Log should be preserved
