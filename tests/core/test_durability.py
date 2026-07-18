"""Durability integration tests for the state-persistence stack.

Each test exercises one of the four headline crash-safety guarantees:

1. **Crash-sim truncate mid-write → stale backup refused** — a corrupt/truncated
   ``state.json`` left by an interrupted atomic write is not silently rolled back
   to a materially older backup; recovery refuses loudly instead.

2. **Two concurrent ``start`` — exactly one wins** — the ``O_CREAT|O_EXCL``
   session lock ensures that at most one process (or the same process on its
   first acquire) holds the lock at a time. A second foreign process is blocked.

3. **JSONL logger survives kill -9** — a torn final line (no trailing newline,
   simulating a crash mid-write) never corrupts prior entries; a fresh instance
   that appends after the crash produces a readable log.

4. **Schema round-trip** — state persisted without a ``schema_version`` field
   (legacy format) is loaded, stamped with the current version, and remains
   valid after a subsequent save/load cycle.

Fixtures from ``tests/conftest.py``: ``temp_dir``, ``state_dir``,
``sample_state_file``.

Note: the session lock is *process-level* (keyed on PID). Tests that simulate
a second caller use a live foreign PID (the parent process) to create a
realistic foreign lock without spawning extra sub-processes.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from claude_task_master.core import session_lock
from claude_task_master.core.logger import LogFormat, TaskLogger, read_json_log
from claude_task_master.core.state import (
    CURRENT_SCHEMA_VERSION,
    StateCorruptedError,
    StateError,
    StateManager,
    StateValidationError,
    TaskOptions,
    TaskState,
)

# =============================================================================
# 1. Crash-sim truncate mid-write → stale backup refused
# =============================================================================


class TestCrashSimTruncateMidWrite:
    """Truncated state.json from a crash must not silently roll back to a stale backup."""

    @staticmethod
    def _replace_backups_with_stale(manager: StateManager, *, age_hours: float = 6.0) -> None:
        """Replace all existing backups with a single stale one."""
        manager.backup_dir.mkdir(parents=True, exist_ok=True)
        for existing in manager.backup_dir.glob("state.*.json"):
            existing.unlink(missing_ok=True)

        stale_ts = (datetime.now() - timedelta(hours=age_hours)).isoformat()
        stale_state = TaskState(
            status="working",
            current_task_index=3,
            session_count=7,
            created_at=stale_ts,
            updated_at=stale_ts,
            run_id="stale-run-xyz",
            model="sonnet",
            options=TaskOptions(),
        )
        backup_path = manager.backup_dir / "state.stale.json"
        backup_path.write_text(json.dumps(stale_state.model_dump(mode="json")))

    def test_truncated_write_refuses_stale_backup(self, temp_dir: Path) -> None:
        """A crash mid-write leaves state.json truncated; a stale backup must not be restored.

        Scenario: ``claudetm`` saves state; the kernel crashes mid-write so
        ``state.json`` is left with a partial JSON object. The only backup on
        disk is several hours old — restoring it would silently roll back merged
        tasks and created PRs. Recovery must refuse with
        ``StateCorruptedError(recoverable=False)``.
        """
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)
        manager.initialize(goal="crash test", model="sonnet", options=TaskOptions())

        # Replace any fresh backups with a single stale one.
        self._replace_backups_with_stale(manager, age_hours=6.0)

        # Simulate a mid-write crash: state.json is left truncated — valid JSON
        # prefix but the object is never closed (no trailing `}`).
        manager.state_file.write_bytes(b'{"status": "working", "schema_versi')

        with pytest.raises(StateCorruptedError) as exc_info:
            manager.load_state()

        assert exc_info.value.recoverable is False, (
            "Recovery with a stale backup must set recoverable=False so the caller "
            "surfaces the error rather than silently rolling back completed work."
        )

    def test_zero_byte_state_file_refuses_stale_backup(self, temp_dir: Path) -> None:
        """An O_TRUNC crash (empty state.json) does not restore a stale backup."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)
        manager.initialize(goal="trunc test", model="sonnet", options=TaskOptions())

        self._replace_backups_with_stale(manager, age_hours=4.0)

        # Simulate an O_TRUNC crash: the file descriptor is opened for writing
        # and the old content is discarded, but nothing new is written.
        manager.state_file.write_bytes(b"")

        with pytest.raises((StateCorruptedError, StateValidationError)):
            # The key invariant: the stale backup is NOT silently restored.
            # Either a StateCorruptedError(recoverable=False) or a
            # StateValidationError because empty JSON is invalid.
            manager.load_state()

    def test_fresh_backup_is_recovered_after_corrupt_write(self, temp_dir: Path) -> None:
        """A backup close in time to the corrupt file IS restored; fresh recovery works.

        The staleness guard only blocks backups that are materially older than
        the corrupt file. A backup written in the same second as the state file
        (as ``save_state`` does) must still be trusted.
        """
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)
        original = manager.initialize(goal="fresh test", model="sonnet", options=TaskOptions())
        # initialize() calls save_state() which creates a backup with a fresh
        # updated_at — well within the staleness threshold.

        # Corrupt state.json to force a recovery attempt.
        manager.state_file.write_text("{ truncated")

        recovered = manager.load_state()
        assert recovered.run_id == original.run_id, (
            "A fresh backup (within the staleness threshold) must be restored "
            "to avoid data loss from a crash mid-write."
        )

    def test_no_backup_at_all_raises_unrecoverable(self, temp_dir: Path) -> None:
        """Corrupt state.json with no backups at all → StateCorruptedError(recoverable=False)."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text("{ corrupt")

        manager = StateManager(state_dir)
        with pytest.raises(StateCorruptedError) as exc_info:
            manager.load_state()

        assert exc_info.value.recoverable is False


# =============================================================================
# 2. Two concurrent ``start`` — exactly one wins
# =============================================================================


def _race_initialize_worker(
    state_dir_str: str, start_barrier: object, done_barrier: object, results: object
) -> None:
    """Subprocess entry point for the concurrent-``initialize`` race.

    Both workers block on ``start_barrier`` so their ``O_CREAT | O_EXCL`` lock
    creations land as simultaneously as possible, then each reports whether it
    acquired the session lock. Each worker waits on ``done_barrier`` *after*
    reporting so the winner stays alive — and thus observable as a live lock
    owner — throughout the loser's acquisition attempt; a prematurely-exited
    winner would otherwise look like a reclaimable dead PID and both could win.
    """
    from pathlib import Path as _Path

    from claude_task_master.core.state import StateError, StateManager, TaskOptions

    manager = StateManager(_Path(state_dir_str))
    outcome = "error"
    try:
        start_barrier.wait(timeout=30)  # type: ignore[attr-defined]
        try:
            manager.initialize(goal="race", model="sonnet", options=TaskOptions())
            outcome = "acquired"
        except StateError:
            outcome = "blocked"
    except Exception:  # pragma: no cover - defensive against a broken barrier
        outcome = "error"
    finally:
        results.put(outcome)  # type: ignore[attr-defined]
    try:
        done_barrier.wait(timeout=30)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - sibling already exited
        pass


class TestConcurrentStartRace:
    """A genuine two-process race on the O_CREAT | O_EXCL session lock."""

    def test_two_processes_race_exactly_one_acquires(self, temp_dir: Path) -> None:
        """Two subprocesses initialize() the same dir behind a barrier — one wins.

        Unlike the sequential foreign-PID simulations below, this exercises the
        real cross-process ``O_CREAT | O_EXCL`` race window: both processes reach
        the lock creation at (near) the same instant, and exactly one must
        acquire while the other is cleanly blocked.
        """
        if not hasattr(os, "fork"):
            pytest.skip("cross-process fork race requires a POSIX fork")

        ctx = mp.get_context("fork")
        state_dir = temp_dir / ".claude-task-master"
        start_barrier = ctx.Barrier(2)
        done_barrier = ctx.Barrier(2)
        results: mp.Queue = ctx.Queue()

        procs = [
            ctx.Process(
                target=_race_initialize_worker,
                args=(str(state_dir), start_barrier, done_barrier, results),
            )
            for _ in range(2)
        ]
        for proc in procs:
            proc.start()

        try:
            outcomes = sorted(results.get(timeout=60) for _ in procs)
        finally:
            for proc in procs:
                proc.join(timeout=30)
                if proc.is_alive():  # pragma: no cover - safety net for a hung child
                    proc.terminate()

        # Exactly one process acquires the lock; the other is cleanly blocked.
        assert outcomes == ["acquired", "blocked"], outcomes


class TestConcurrentStart:
    """Session lock: a live foreign process must block a second initialize()."""

    def test_foreign_live_process_blocks_initialize(self, state_manager: StateManager) -> None:
        """A live foreign PID in the lock file blocks initialize().

        The session lock is process-level (keyed on PID). Planting the parent
        process's PID (which is alive) as the recorded owner simulates a second
        ``claudetm start`` already running in another process.
        """
        state_manager.state_dir.mkdir(parents=True, exist_ok=True)

        # Plant a lock owned by the parent process (a live, foreign PID).
        parent_pid = os.getppid()
        parent_start = session_lock.read_process_start_time(parent_pid)
        foreign_owner = session_lock.LockOwner(pid=parent_pid, start_time=parent_start)
        state_manager._pid_file.write_text(session_lock.serialize_owner(foreign_owner))

        with pytest.raises(StateError, match="[Aa]nother"):
            state_manager.initialize(goal="blocked", model="sonnet", options=TaskOptions())

    def test_stale_dead_pid_is_reclaimed_and_new_start_succeeds(
        self, state_manager: StateManager
    ) -> None:
        """A stale PID file (dead process) is reclaimed and the new start proceeds."""
        import subprocess
        import sys

        state_manager.state_dir.mkdir(parents=True, exist_ok=True)

        # Spawn a process and wait for it to die.
        proc = subprocess.Popen([sys.executable, "-c", ""])
        proc.wait()
        dead_pid = proc.pid

        # A dead PID can never compare equal to a live one's start time.
        stale_owner = session_lock.LockOwner(pid=dead_pid, start_time=None)
        state_manager._pid_file.write_text(session_lock.serialize_owner(stale_owner))

        # Should succeed: stale lock is reclaimed during acquire.
        state = state_manager.initialize(goal="reclaimed", model="sonnet", options=TaskOptions())
        assert state.status == "planning"

    def test_second_start_on_same_state_dir_blocked(self, temp_dir: Path) -> None:
        """When one session holds the lock, a second StateManager cannot initialize()."""
        state_dir = temp_dir / ".claude-task-master"

        manager1 = StateManager(state_dir)
        manager1.initialize(goal="first", model="sonnet", options=TaskOptions())
        # Lock is held by this process.

        # Simulate a SECOND process by planting that process's PID.  Because
        # manager1 owns the lock with os.getpid(), a second manager in the same
        # process would be granted re-entry (idempotent).  To simulate a true
        # second-process block, plant a live foreign PID.
        parent_pid = os.getppid()
        parent_start = session_lock.read_process_start_time(parent_pid)
        foreign_owner = session_lock.LockOwner(pid=parent_pid, start_time=parent_start)

        # Overwrite the lock with the foreign PID to simulate the second process
        # having grabbed it (as if this process died and the parent took over).
        state_manager2 = StateManager(state_dir)
        state_manager2._pid_file.write_text(session_lock.serialize_owner(foreign_owner))

        with pytest.raises(StateError, match="[Aa]nother"):
            state_manager2.initialize(goal="second", model="sonnet", options=TaskOptions())

    def test_release_allows_new_session(self, temp_dir: Path) -> None:
        """After releasing the lock, a new session can initialize successfully."""
        state_dir = temp_dir / ".claude-task-master"

        manager1 = StateManager(state_dir)
        manager1.initialize(goal="first", model="sonnet", options=TaskOptions())
        manager1.release_session_lock()  # Simulates graceful shutdown / cleanup.

        manager2 = StateManager(state_dir)
        state2 = manager2.initialize(goal="second", model="sonnet", options=TaskOptions())
        assert state2.status == "planning"


# =============================================================================
# 3. JSONL logger survives kill -9
# =============================================================================


class TestJsonlKill9Survival:
    """JSONL append logger: a torn write (kill -9 mid-write) must not corrupt prior entries."""

    def test_torn_final_line_does_not_corrupt_prior_entries(self, log_file: Path) -> None:
        """Entries written before a kill -9 are still readable after the crash.

        Simulates kill -9 mid-write: a JSON fragment without a trailing newline
        is appended. A fresh logger instance opened after the crash appends new
        entries. Prior entries must survive intact.
        """
        logger = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger.start_session(1, "work")
        logger.log_error("written before crash")

        # Simulate kill -9: partial JSON, no trailing newline.
        with open(log_file, "a") as f:
            f.write('{"type": "error", "message": "half-writ')

        # A *new* logger instance (fresh process after restart) appends more entries.
        logger2 = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger2.start_session(2, "work")
        logger2.log_error("written after restart")

        entries = read_json_log(log_file)
        messages = [e.get("message") for e in entries if e.get("type") == "error"]

        assert "written before crash" in messages, (
            "The pre-crash entry must survive the torn write."
        )
        assert "written after restart" in messages, (
            "The post-restart entry must appear in the parsed log."
        )
        assert not any("half-writ" in str(m) for m in messages), (
            "The torn (half-written) entry must NOT appear in the parsed output."
        )

    def test_prior_sessions_survive_torn_mid_session_write(self, log_file: Path) -> None:
        """Entries from a completed session survive a torn write in a later session."""
        # Session 1 completes cleanly.
        logger = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger.start_session(1, "work")
        logger.log_prompt("session-1-prompt")
        logger.end_session("done")

        # Session 2 starts but crashes mid-entry (no trailing newline).
        logger2 = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger2.start_session(2, "work")
        with open(log_file, "a") as f:
            f.write('{"type": "prompt", "content": "killed-mid-wri')

        # Session 3 opens after restart.
        logger3 = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger3.start_session(3, "work")
        logger3.log_prompt("session-3-prompt")
        logger3.end_session("recovered")

        entries = read_json_log(log_file)
        prompts = [e.get("content") for e in entries if e.get("type") == "prompt"]

        assert "session-1-prompt" in prompts, (
            "Completed session-1 prompt must be readable after the kill -9."
        )
        assert "session-3-prompt" in prompts, (
            "Session-3 entries appended after restart must be readable."
        )
        assert not any("killed-mid-wri" in str(p) for p in prompts), (
            "Partial session-2 prompt must be discarded."
        )

    def test_append_only_writes_do_not_rewrite_earlier_bytes(self, log_file: Path) -> None:
        """Writing a second session appends bytes; the first session's bytes are unchanged.

        An O(n²) in-place rewrite would fail this: the snapshot taken after the
        first session would not be a prefix of the final file.
        """
        logger = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger.start_session(1, "work")
        logger.log_prompt("session-1-prompt")
        logger.end_session("done")

        snapshot = log_file.read_bytes()

        logger2 = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger2.start_session(2, "work")
        logger2.log_prompt("session-2-prompt")
        logger2.end_session("done")

        final = log_file.read_bytes()

        assert final.startswith(snapshot), (
            "Session-2 writes must only append; earlier bytes must not change."
        )
        assert len(final) > len(snapshot)


# =============================================================================
# 4. Schema round-trip
# =============================================================================


class TestSchemaRoundTrip:
    """State persisted in a legacy (no schema_version) format survives a full round-trip."""

    def test_legacy_state_gains_schema_version_on_load(
        self, state_dir: Path, sample_state_file: Path
    ) -> None:
        """State without ``schema_version`` (legacy format) is stamped on load.

        The ``sample_state_file`` fixture writes a state dict WITHOUT
        ``schema_version`` to simulate on-disk state from before versioning was
        introduced. Loading it must stamp the current schema version.
        """
        raw = json.loads(sample_state_file.read_text())
        assert "schema_version" not in raw, (
            "The sample_state_file fixture must not contain schema_version "
            "(it represents legacy on-disk state)."
        )

        manager = StateManager(state_dir)
        state = manager.load_state()

        assert state.schema_version == CURRENT_SCHEMA_VERSION

    def test_round_trip_preserves_all_fields(
        self, state_dir: Path, sample_state_file: Path
    ) -> None:
        """A full save → load cycle preserves every meaningful state field."""
        manager = StateManager(state_dir)
        loaded = manager.load_state()

        loaded.session_count = 42
        loaded.current_task_index = 7
        manager.save_state(loaded, validate_transition=False)

        reloaded = manager.load_state()

        assert reloaded.schema_version == CURRENT_SCHEMA_VERSION
        assert reloaded.run_id == loaded.run_id
        assert reloaded.model == loaded.model
        assert reloaded.session_count == 42
        assert reloaded.current_task_index == 7

    def test_schema_version_written_to_disk_on_save(
        self, state_dir: Path, sample_state_file: Path
    ) -> None:
        """After the first save of a legacy state, ``schema_version`` appears on disk."""
        manager = StateManager(state_dir)
        state = manager.load_state()
        manager.save_state(state, validate_transition=False)

        on_disk = json.loads((state_dir / "state.json").read_text())
        assert on_disk["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_newer_schema_version_rejected_loudly(self, state_dir: Path) -> None:
        """State written by a newer version of the tool is rejected, not silently truncated.

        Pydantic would silently drop unknown fields from a newer schema and then
        destroy them on the next save. Explicit version rejection prevents this
        so the operator knows to upgrade rather than silently losing data.
        """
        future_version = CURRENT_SCHEMA_VERSION + 1
        state_file = state_dir / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "schema_version": future_version,
                    "status": "working",
                    "run_id": "future-run",
                    "model": "opus",
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "options": {},
                    "new_future_field": "would be silently dropped by pydantic",
                }
            )
        )

        manager = StateManager(state_dir)
        with pytest.raises(StateValidationError) as exc_info:
            manager.load_state()

        error_text = str(exc_info.value).lower()
        assert "newer" in error_text or str(future_version) in str(exc_info.value), (
            "The error must mention the schema version so the operator understands "
            "they need to upgrade, not that the file is 'corrupt'."
        )

    def test_schema_version_stamped_idempotently_on_repeated_loads(
        self, state_dir: Path, sample_state_file: Path
    ) -> None:
        """Multiple successive loads of a legacy state all yield the current schema version."""
        manager = StateManager(state_dir)

        state1 = manager.load_state()
        state2 = manager.load_state()

        assert state1.schema_version == CURRENT_SCHEMA_VERSION
        assert state2.schema_version == CURRENT_SCHEMA_VERSION
        assert state1.run_id == state2.run_id
