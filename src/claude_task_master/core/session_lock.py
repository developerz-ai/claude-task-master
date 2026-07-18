"""Single-instance session lock backed by an atomically-created PID file.

Only one ``claudetm`` process may drive a given state directory at a time. The
lock is a small JSON file (``.pid``) created with ``O_CREAT | O_EXCL`` so that
creation is *atomic*: exactly one racing process wins, with no check-then-write
window. The previous implementation checked liveness and *then* wrote the file,
so two ``claudetm start`` invocations could both believe they had acquired it.

The file records the owner's PID **and** its start time. Storing the start time
guards against PID recycling: after a crash the OS may hand the dead owner's PID
to an unrelated process, and a bare ``os.kill(pid, 0)`` liveness probe would then
report the lock as held forever. Comparing the recorded start time against the
live one detects the recycled PID so the stale lock can be reclaimed.

Process start times come from ``/proc/<pid>/stat`` (Linux). On platforms without
``/proc`` the start time is recorded as ``None`` and the recycle guard degrades
gracefully to a plain liveness probe.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from pathlib import Path

# Index of the ``starttime`` field within ``/proc/<pid>/stat`` counted from the
# first field *after* the parenthesised ``comm`` (field 2). The raw fields are
# ``pid (comm) state ppid ... starttime`` where ``starttime`` is field 22, so it
# lands at index 19 once fields 1-2 are dropped.
_STAT_STARTTIME_INDEX = 19


class LockOwner(NamedTuple):
    """Identity recorded in the PID lock file.

    Attributes:
        pid: The owning process ID.
        start_time: The owner's start time (Linux clock ticks since boot), or
            ``None`` when it could not be determined (e.g. no ``/proc``).
    """

    pid: int
    start_time: float | None


def read_process_start_time(pid: int) -> float | None:
    """Return the start time of ``pid``, or ``None`` if it cannot be determined.

    Reads field 22 (``starttime``) of ``/proc/<pid>/stat`` — a value fixed for
    the lifetime of the process, expressed in clock ticks since boot. It is used
    to distinguish a live owner from an unrelated process that later reused the
    same PID.

    Args:
        pid: The process ID to inspect.

    Returns:
        The start time as a float, or ``None`` on platforms without ``/proc`` or
        if the process or field cannot be read.
    """
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as f:
            stat_line = f.read()
    except OSError:
        return None
    # ``comm`` (field 2) is wrapped in parentheses and may itself contain spaces
    # or ')', so parse from *after* the final ')': the remaining whitespace-split
    # fields then begin at field 3 (state).
    rparen = stat_line.rfind(")")
    if rparen == -1:
        return None
    fields = stat_line[rparen + 1 :].split()
    try:
        return float(fields[_STAT_STARTTIME_INDEX])
    except (IndexError, ValueError):
        return None


def current_owner() -> LockOwner:
    """Return the :class:`LockOwner` describing the calling process."""
    pid = os.getpid()
    return LockOwner(pid=pid, start_time=read_process_start_time(pid))


def serialize_owner(owner: LockOwner) -> str:
    """Serialize a :class:`LockOwner` to the JSON stored in the lock file."""
    return json.dumps({"pid": owner.pid, "start_time": owner.start_time})


def parse_owner(text: str) -> LockOwner | None:
    """Parse lock-file contents into a :class:`LockOwner`.

    Accepts both the current JSON object and a legacy bare-integer PID file so an
    in-progress upgrade does not silently drop the single-instance guarantee.

    Args:
        text: The raw lock-file contents.

    Returns:
        The parsed :class:`LockOwner`, or ``None`` if the content is empty or
        malformed.
    """
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, bool):
        return None
    if isinstance(data, int):  # Legacy bare-PID lock file.
        return LockOwner(pid=data, start_time=None)
    if isinstance(data, dict):
        try:
            pid = int(data["pid"])
        except (KeyError, TypeError, ValueError):
            return None
        raw_start = data.get("start_time")
        if isinstance(raw_start, bool) or not isinstance(raw_start, (int, float)):
            start_time = None
        else:
            start_time = float(raw_start)
        return LockOwner(pid=pid, start_time=start_time)
    return None


def read_owner(pid_file: Path) -> LockOwner | None:
    """Read and parse the owner recorded in ``pid_file``.

    Args:
        pid_file: Path to the ``.pid`` lock file.

    Returns:
        The parsed :class:`LockOwner`, or ``None`` if the file is missing,
        unreadable, or malformed.
    """
    try:
        text = pid_file.read_text(encoding="ascii")
    except OSError:
        return None
    return parse_owner(text)


def is_owner_running(owner: LockOwner) -> bool:
    """Return whether ``owner``'s process is still alive (recycle-aware).

    Probes existence with signal 0, then — when a start time was recorded and the
    live one is readable — requires the two to match, so a PID reused by an
    unrelated process is reported as *not* running.

    Args:
        owner: The recorded lock owner to check.

    Returns:
        True if the owning process is still running, False otherwise.
    """
    try:
        os.kill(owner.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # Process exists but is not signalable by us — still alive.
    except OSError:
        return False
    if owner.start_time is not None:
        live_start = read_process_start_time(owner.pid)
        if live_start is not None and live_start != owner.start_time:
            return False  # PID was recycled by an unrelated process.
    return True
