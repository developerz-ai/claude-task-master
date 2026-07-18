"""Tests for the single-instance session-lock helpers."""

import json
import os
import subprocess
import sys

import pytest

from claude_task_master.core import session_lock
from claude_task_master.core.session_lock import LockOwner

# Process start times are only readable via /proc (Linux). Skip the
# recycle-guard tests where they are unavailable rather than assert a fallback.
START_TIMES_AVAILABLE = session_lock.read_process_start_time(os.getpid()) is not None
requires_start_times = pytest.mark.skipif(
    not START_TIMES_AVAILABLE, reason="process start times unavailable (no /proc)"
)


def _reaped_pid() -> int:
    """Spawn a trivial child, reap it, and return its now-dead PID."""
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    return proc.pid


class TestReadProcessStartTime:
    """Tests for read_process_start_time."""

    @requires_start_times
    def test_returns_float_for_live_process(self):
        """Live process yields a numeric start time."""
        start = session_lock.read_process_start_time(os.getpid())
        assert isinstance(start, float)

    @requires_start_times
    def test_is_stable_across_calls(self):
        """Start time is fixed for the lifetime of a process."""
        first = session_lock.read_process_start_time(os.getpid())
        second = session_lock.read_process_start_time(os.getpid())
        assert first == second

    def test_returns_none_for_dead_process(self):
        """A reaped PID has no readable start time."""
        dead = _reaped_pid()
        if _is_running(dead):
            pytest.skip("PID was reused before assertion")
        assert session_lock.read_process_start_time(dead) is None


class TestCurrentOwner:
    """Tests for current_owner."""

    def test_uses_calling_pid(self):
        """current_owner reports this process's PID."""
        assert session_lock.current_owner().pid == os.getpid()

    @requires_start_times
    def test_records_start_time(self):
        """current_owner records a start time when one is available."""
        assert session_lock.current_owner().start_time is not None


class TestSerializeParseRoundTrip:
    """Tests for serialize_owner / parse_owner."""

    def test_round_trip_with_start_time(self):
        """An owner survives a serialize/parse round trip."""
        owner = LockOwner(pid=1234, start_time=987.0)
        assert session_lock.parse_owner(session_lock.serialize_owner(owner)) == owner

    def test_round_trip_without_start_time(self):
        """A None start time round-trips as None."""
        owner = LockOwner(pid=1234, start_time=None)
        assert session_lock.parse_owner(session_lock.serialize_owner(owner)) == owner

    def test_serialized_form_is_json_object(self):
        """The lock payload is a JSON object with pid and start_time."""
        data = json.loads(session_lock.serialize_owner(LockOwner(pid=42, start_time=None)))
        assert data == {"pid": 42, "start_time": None}


class TestParseOwner:
    """Tests for parse_owner edge cases."""

    def test_legacy_bare_pid(self):
        """A legacy bare-integer PID file parses with an unknown start time."""
        assert session_lock.parse_owner("12345") == LockOwner(pid=12345, start_time=None)

    def test_legacy_bare_pid_with_whitespace(self):
        """Surrounding whitespace on a legacy PID file is tolerated."""
        assert session_lock.parse_owner("  12345\n") == LockOwner(pid=12345, start_time=None)

    def test_empty_returns_none(self):
        """Empty content parses to None."""
        assert session_lock.parse_owner("") is None
        assert session_lock.parse_owner("   \n") is None

    def test_garbage_returns_none(self):
        """Non-JSON garbage parses to None."""
        assert session_lock.parse_owner("not-a-pid") is None

    def test_bool_returns_none(self):
        """A top-level JSON boolean is not a valid owner."""
        assert session_lock.parse_owner("true") is None

    def test_float_returns_none(self):
        """A top-level JSON float is not a valid owner."""
        assert session_lock.parse_owner("1.5") is None

    def test_object_missing_pid_returns_none(self):
        """An object without a pid field parses to None."""
        assert session_lock.parse_owner('{"start_time": 5.0}') is None

    def test_object_non_numeric_pid_returns_none(self):
        """A non-numeric pid parses to None."""
        assert session_lock.parse_owner('{"pid": "abc"}') is None

    def test_object_bool_start_time_ignored(self):
        """A boolean start_time is treated as unknown."""
        assert session_lock.parse_owner('{"pid": 7, "start_time": true}') == LockOwner(
            pid=7, start_time=None
        )


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class TestIsOwnerRunning:
    """Tests for is_owner_running."""

    def test_true_for_current_process(self):
        """The calling process is reported as running."""
        assert session_lock.is_owner_running(session_lock.current_owner()) is True

    def test_true_for_live_pid_without_start_time(self):
        """A live PID with no recorded start time is running."""
        assert session_lock.is_owner_running(LockOwner(pid=os.getpid(), start_time=None)) is True

    def test_false_for_dead_pid(self):
        """A reaped PID is not running."""
        dead = _reaped_pid()
        if _is_running(dead):
            pytest.skip("PID was reused before assertion")
        assert session_lock.is_owner_running(LockOwner(pid=dead, start_time=None)) is False

    @requires_start_times
    def test_true_when_start_time_matches(self):
        """A live PID with a matching start time is running."""
        ppid = os.getppid()
        start = session_lock.read_process_start_time(ppid)
        assert session_lock.is_owner_running(LockOwner(pid=ppid, start_time=start)) is True

    @requires_start_times
    def test_false_when_start_time_mismatches(self):
        """A live PID whose recorded start time differs is treated as recycled."""
        ppid = os.getppid()
        start = session_lock.read_process_start_time(ppid)
        assert start is not None
        wrong = LockOwner(pid=ppid, start_time=start + 1000.0)
        assert session_lock.is_owner_running(wrong) is False
