"""Tests for the shared durable atomic-write helpers."""

from __future__ import annotations

import errno
import json
import os
from unittest.mock import patch

import pytest

from claude_task_master.core.atomic_io import (
    _fsync_dir,
    _makedirs_durable,
    atomic_write_json,
    atomic_write_text,
)


class TestAtomicWriteText:
    """Tests for atomic_write_text."""

    def test_creates_file_with_content(self, tmp_path):
        """Writes the exact text content to the target path."""
        target = tmp_path / "out.txt"
        atomic_write_text(target, "hello world")

        assert target.read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_directories(self, tmp_path):
        """Creates missing parent directories before writing."""
        target = tmp_path / "nested" / "deep" / "out.txt"
        atomic_write_text(target, "data")

        assert target.exists()
        assert target.read_text(encoding="utf-8") == "data"

    def test_overwrites_existing_file(self, tmp_path):
        """Replaces the contents of an existing file atomically."""
        target = tmp_path / "out.txt"
        target.write_text("old")

        atomic_write_text(target, "new")

        assert target.read_text(encoding="utf-8") == "new"

    def test_no_temp_files_left(self, tmp_path):
        """Leaves no temporary files behind after a successful write."""
        atomic_write_text(tmp_path / "out.txt", "data")

        assert list(tmp_path.glob(".tmp_*")) == []

    def test_fsyncs_file_then_directory(self, tmp_path):
        """fsyncs the file fd, then syncs the parent directory for durability."""
        target = tmp_path / "out.txt"

        # Patch _fsync_dir so the file fd fsync is the only os.fsync call left,
        # and the directory-sync path can be asserted independently.
        with (
            patch("claude_task_master.core.atomic_io._fsync_dir") as mock_dir_sync,
            patch("claude_task_master.core.atomic_io.os.fsync") as mock_file_sync,
        ):
            atomic_write_text(target, "durable")

        mock_file_sync.assert_called()  # The file's bytes are flushed.
        mock_dir_sync.assert_called_once_with(target.parent)  # The rename is made durable.
        assert target.read_text(encoding="utf-8") == "durable"

    def test_cleans_up_temp_file_on_error(self, tmp_path):
        """Removes the temp file and re-raises if the rename fails."""
        target = tmp_path / "out.txt"

        with patch(
            "claude_task_master.core.atomic_io.os.replace",
            side_effect=OSError("boom"),
        ):
            with pytest.raises(OSError, match="boom"):
                atomic_write_text(target, "data")

        assert not target.exists()
        assert list(tmp_path.glob(".tmp_*")) == []

    def test_respects_encoding(self, tmp_path):
        """Honors a non-default encoding argument."""
        target = tmp_path / "out.txt"
        atomic_write_text(target, "café", encoding="utf-8")

        assert target.read_bytes() == "café".encode()


class TestAtomicWriteJson:
    """Tests for atomic_write_json."""

    def test_writes_valid_json(self, tmp_path):
        """Produces a parseable JSON file."""
        target = tmp_path / "out.json"
        atomic_write_json(target, {"a": 1, "b": [2, 3]})

        assert json.loads(target.read_text()) == {"a": 1, "b": [2, 3]}

    def test_round_trips_nested_data(self, tmp_path):
        """Round-trips nested, mixed-type data faithfully."""
        data = {"x": {"y": [1, "two", True, None]}, "n": 3.5}
        target = tmp_path / "out.json"
        atomic_write_json(target, data)

        assert json.loads(target.read_text()) == data

    def test_default_indent_is_two(self, tmp_path):
        """Uses two-space indentation by default."""
        target = tmp_path / "out.json"
        atomic_write_json(target, {"a": 1})

        assert target.read_text() == '{\n  "a": 1\n}'

    def test_overwrites_existing_file(self, tmp_path):
        """Replaces an existing JSON file's contents."""
        target = tmp_path / "out.json"
        atomic_write_json(target, {"v": 1})
        atomic_write_json(target, {"v": 2})

        assert json.loads(target.read_text()) == {"v": 2}

    def test_no_temp_files_left(self, tmp_path):
        """Leaves no temporary files behind after a successful write."""
        atomic_write_json(tmp_path / "out.json", {"a": 1})

        assert list(tmp_path.glob(".tmp_*")) == []


class TestFsyncDir:
    """Tests for _fsync_dir: tolerate only unsupported syncing, surface real errors."""

    def test_missing_directory_propagates_on_posix(self, tmp_path):
        """A genuine open failure (missing directory) surfaces instead of being hidden."""
        missing = tmp_path / "does-not-exist"
        if os.name == "nt":
            _fsync_dir(missing)  # Windows has no dir-sync primitive: tolerated.
        else:
            with pytest.raises(OSError):
                _fsync_dir(missing)

    def test_unsupported_fsync_errno_is_tolerated(self, tmp_path):
        """A filesystem that cannot fsync a directory fd (EINVAL) is tolerated."""
        err = OSError("directory fsync unsupported")
        err.errno = errno.EINVAL
        with patch("claude_task_master.core.atomic_io.os.fsync", side_effect=err):
            _fsync_dir(tmp_path)  # Should not raise.

    def test_genuine_storage_error_propagates(self, tmp_path):
        """A real storage error (EIO) is propagated, not swallowed."""
        err = OSError("I/O error")
        err.errno = errno.EIO
        with patch("claude_task_master.core.atomic_io.os.fsync", side_effect=err):
            with pytest.raises(OSError):
                _fsync_dir(tmp_path)


class TestMakedirsDurable:
    """Tests for _makedirs_durable: newly created directories are made durable."""

    def test_creates_nested_hierarchy(self, tmp_path):
        """Creates a multi-level directory hierarchy."""
        target = tmp_path / "a" / "b" / "c"
        _makedirs_durable(target)
        assert target.is_dir()

    def test_syncs_each_newly_created_directory_parent(self, tmp_path):
        """Each new directory's parent entry is fsynced so the hierarchy survives a crash."""
        target = tmp_path / "a" / "b" / "c"
        with patch("claude_task_master.core.atomic_io._fsync_dir") as mock_sync:
            _makedirs_durable(target)

        synced = {call.args[0] for call in mock_sync.call_args_list}
        assert tmp_path in synced  # parent of newly created "a"
        assert (tmp_path / "a") in synced  # parent of newly created "b"
        assert (tmp_path / "a" / "b") in synced  # parent of newly created "c"

    def test_existing_directory_does_no_sync(self, tmp_path):
        """An already-existing directory triggers no extra parent fsync."""
        with patch("claude_task_master.core.atomic_io._fsync_dir") as mock_sync:
            _makedirs_durable(tmp_path)
        mock_sync.assert_not_called()
