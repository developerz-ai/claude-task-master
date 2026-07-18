"""Durable, atomic file writes shared across the state and mailbox stores.

The task-state store, the mailbox, and the PR-context store each reimplemented
the temp-file + rename pattern, and none of them fsynced the data or the
directory entry. A crash (``kill -9``, power loss) between ``write`` and the OS
flushing its page cache could therefore leave a zero-length or truncated
``state.json`` / ``mailbox.json`` / ``addressed_threads.json`` behind.

The helpers here centralise the pattern and make it durable:

1. write the payload to a temp file in the *same* directory,
2. ``flush()`` + ``os.fsync()`` the file so its bytes reach the disk,
3. ``os.replace()`` the temp file over the target (atomic on POSIX/Windows),
4. ``fsync`` the parent directory so the rename itself is durable.

After a crash the target is therefore always either the previous complete file
or the fully-written new one -- never a partial write.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def _fsync_dir(directory: Path) -> None:
    """fsync a directory so a rename inside it survives a crash.

    Best-effort: some platforms (notably Windows) cannot open a directory for
    fsync, so any OSError is ignored rather than propagated.

    Args:
        directory: The directory whose entries should be flushed to disk.
    """
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass  # Directory fsync is best-effort.
    finally:
        os.close(dir_fd)


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically and durably write ``text`` to ``path``.

    Writes to a temp file in the same directory, fsyncs it, renames it over the
    target, then fsyncs the parent directory. A crash therefore leaves either
    the previous file or the fully-written new one -- never a partial write.

    Args:
        path: Target file path. Parent directories are created if needed.
        text: The text content to write.
        encoding: Text encoding for the file (default ``utf-8``).

    Raises:
        OSError: If the file cannot be written, synced, or renamed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".tmp")
    try:
        with open(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # Atomic rename over the target (replaces any existing file).
        os.replace(temp_path, path)
    except BaseException:
        # Clean up the temp file on any failure (including KeyboardInterrupt).
        try:
            Path(temp_path).unlink()
        except OSError:
            pass  # Temp file cleanup is best-effort.
        raise

    # Make the rename itself durable.
    _fsync_dir(path.parent)


def atomic_write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    """Atomically and durably write ``data`` to ``path`` as JSON.

    Args:
        path: Target file path. Parent directories are created if needed.
        data: A JSON-serialisable object.
        indent: Indentation passed to :func:`json.dumps` (default ``2``).

    Raises:
        TypeError: If ``data`` is not JSON-serialisable.
        OSError: If the file cannot be written, synced, or renamed.
    """
    atomic_write_text(path, json.dumps(data, indent=indent))
