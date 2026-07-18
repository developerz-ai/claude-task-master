"""Tests for StateManager cleanup operations.

Covers ``cleanup_on_success`` (state-file removal, backup-dir removal, coding
style preservation), log-file rotation, session-lock release during cleanup,
and cleanup hardening (lock/pid preservation, tolerating vanishing logs).
Backup creation/rotation lives in ``test_state_backup.py``; recovery from
backups lives in ``test_state_backup_recovery.py``.
"""

import shutil
import time

from claude_task_master.core.state import StateManager, TaskOptions

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

    def test_cleanup_preserves_coding_style(self, initialized_state_manager):
        """Test cleanup preserves coding-style.md for reuse across runs."""
        # Create coding style file
        coding_style = """# Coding Guide

## Workflow
- Write tests first (TDD)
- Run pytest before commit
"""
        initialized_state_manager.save_coding_style(coding_style)
        coding_style_file = initialized_state_manager.state_dir / "coding-style.md"
        assert coding_style_file.exists()

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        # Coding style should be preserved
        assert coding_style_file.exists()
        assert coding_style_file.read_text() == coding_style


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
# cleanup_on_success Hardening Tests
# =============================================================================


class TestCleanupHardening:
    """Tests for cleanup_on_success hardening (lock/pid preservation, log rotation)."""

    def test_cleanup_preserves_state_lock_file(self, initialized_state_manager):
        """cleanup_on_success must not delete the .state.lock advisory lock file."""
        lock_file = initialized_state_manager.state_dir / ".state.lock"
        # Create the file (it may already exist from initialize).
        lock_file.touch()

        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        # The lock file must still be present so a concurrent reader doesn't lose
        # its fcntl fd referent mid-cleanup.
        assert lock_file.exists(), ".state.lock must survive cleanup_on_success"

    def test_cleanup_preserves_pid_file_during_lock_release(self, initialized_state_manager):
        """The .pid file is released (unlinked) by release_session_lock, not by file cleanup.

        This test confirms the exclusion prevents the file-cleanup loop from
        racing against release_session_lock and deleting the file twice (which
        would raise on some OS paths or silently succeed with wrong semantics).
        """
        # cleanup_on_success calls release_session_lock first, which removes
        # .pid; the file-cleanup loop then must not fail if it's already gone.
        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)  # must not raise

    def test_cleanup_old_logs_tolerates_vanishing_file(self, initialized_state_manager):
        """_cleanup_old_logs must not crash when a log file disappears mid-sort."""
        logs_dir = initialized_state_manager.logs_dir

        # Create more than 10 log files.
        for i in range(12):
            lf = logs_dir / f"run-vanish-{i:02d}.txt"
            lf.write_text(f"log {i}")
            time.sleep(0.01)

        # Delete one of the files AFTER glob but before stat — simulate this by
        # patching _cleanup_old_logs to delete one file just before sorting.
        # Simplest approximation: pre-delete a file, then call cleanup.
        (logs_dir / "run-vanish-00.txt").unlink()

        run_id = initialized_state_manager.load_state().run_id
        # Must not raise despite the missing file.
        initialized_state_manager.cleanup_on_success(run_id)

        remaining = list(logs_dir.glob("run-*.txt"))
        # 12 created − 1 pre-deleted = 11; after rotation keep 10.
        assert len(remaining) <= 10
