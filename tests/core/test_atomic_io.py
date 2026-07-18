"""Tests for the shared durable atomic-write helpers."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from claude_task_master.core.atomic_io import (
    _fsync_dir,
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

    def test_fsyncs_file_and_directory(self, tmp_path):
        """fsyncs the file and the parent directory for durability."""
        target = tmp_path / "out.txt"

        with patch("claude_task_master.core.atomic_io.os.fsync") as mock_fsync:
            atomic_write_text(target, "durable")

        # File fd fsync plus the parent-directory fsync.
        assert mock_fsync.call_count >= 1
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
    """Tests for the _fsync_dir best-effort helper."""

    def test_missing_directory_does_not_raise(self, tmp_path):
        """Silently ignores a non-existent directory."""
        _fsync_dir(tmp_path / "does-not-exist")  # Should not raise.

    def test_fsync_error_does_not_raise(self, tmp_path):
        """Swallows an fsync OSError (best-effort)."""
        with patch(
            "claude_task_master.core.atomic_io.os.fsync",
            side_effect=OSError("no dir fsync"),
        ):
            _fsync_dir(tmp_path)  # Should not raise.
