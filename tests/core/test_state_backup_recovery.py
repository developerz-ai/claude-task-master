"""Tests for recovering StateManager state from backups.

Covers recovery when the primary ``state.json`` is corrupted, plus end-to-end
backup/modify/corrupt/recover integration scenarios. Backup *creation* and
rotation live in ``test_state_backup.py``; ``cleanup_on_success`` and log
rotation live in ``test_state_cleanup.py``.

Note: this file is about recovery from on-disk *backups*. The separate
``test_state_recovery.py`` covers the unrelated ``StateRecovery`` module that
infers real progress from PR/CI status.
"""

import time

import pytest

from claude_task_master.core.state import (
    StateCorruptedError,
    StateManager,
    StateValidationError,
    TaskOptions,
)

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
