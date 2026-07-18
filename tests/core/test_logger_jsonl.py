"""Tests for the JSON Lines (JSONL) append logger.

These lock in the durability properties of the JSON log path:
- entries are written immediately, not buffered until ``end_session``
- writes are append-only (no O(n²) whole-file rewrite)
- a corrupt or torn line never discards the surrounding history
- ``read_json_log`` tolerates blank/corrupt lines and missing files
"""

import json
from pathlib import Path

from claude_task_master.core.logger import LogFormat, LogLevel, TaskLogger, read_json_log


class TestJsonlDurability:
    """Durability guarantees of the append-based JSON logger."""

    def test_error_written_before_end_session(self, log_file: Path) -> None:
        """Errors hit disk immediately instead of buffering until end_session."""
        logger = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger.start_session(1, "work")
        logger.log_error("boom")

        # No end_session()/flush: a crash here must still preserve the error.
        entries = read_json_log(log_file)
        assert any(e["type"] == "error" and e["message"] == "boom" for e in entries)

    def test_writes_are_append_only(self, log_file: Path) -> None:
        """Later sessions append; earlier bytes are never rewritten (no O(n²) rewrite)."""
        logger = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger.start_session(1, "work")
        logger.log_prompt("first")
        logger.end_session("done")

        after_first = log_file.read_bytes()

        logger.start_session(2, "work")
        logger.log_prompt("second")
        logger.end_session("done")

        after_second = log_file.read_bytes()

        # The file only grew and the original prefix is byte-for-byte unchanged.
        assert after_second.startswith(after_first)
        assert len(after_second) > len(after_first)

    def test_corrupt_line_preserves_surrounding_history(self, log_file: Path) -> None:
        """A single corrupt line is skipped without discarding other entries."""
        logger = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger.start_session(1, "work")
        logger.log_error("first")

        # A corrupt line lands in the middle of the log.
        with open(log_file, "a") as f:
            f.write("{not valid json\n")

        logger.log_error("second")

        entries = read_json_log(log_file)
        messages = [e.get("message") for e in entries if e["type"] == "error"]
        assert messages == ["first", "second"]

    def test_survives_torn_final_line(self, log_file: Path) -> None:
        """A partially-written final line (kill -9 mid-write) never corrupts prior entries."""
        logger = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger.start_session(1, "work")
        logger.log_prompt("done cleanly")

        # Simulate kill -9 mid-write: a JSON fragment with no trailing newline.
        with open(log_file, "a") as f:
            f.write('{"type": "prompt", "content": "half-writ')

        # A fresh run appends more entries after the crash.
        logger2 = TaskLogger(log_file, log_format=LogFormat.JSON)
        logger2.start_session(2, "work")
        logger2.log_prompt("after restart")

        entries = read_json_log(log_file)
        prompts = [e.get("content") for e in entries if e["type"] == "prompt"]
        assert "done cleanly" in prompts
        assert "after restart" in prompts
        assert "half-writ" not in "".join(str(p) for p in prompts)


class TestJsonlFormat:
    """Format invariants of the JSONL output."""

    def test_each_entry_is_a_single_json_line(self, log_file: Path) -> None:
        """Every entry is exactly one line of standalone valid JSON."""
        logger = TaskLogger(log_file, log_format=LogFormat.JSON, level=LogLevel.VERBOSE)
        logger.start_session(1, "work")
        logger.log_prompt("p")
        logger.log_tool_use("Read", {"file_path": "/x"})
        logger.log_response("r")
        logger.end_session("done")

        lines = log_file.read_text().splitlines()
        # session_start, prompt, tool_use, response, session_end
        assert len(lines) == 5
        for line in lines:
            parsed = json.loads(line)  # each line parses independently
            assert "type" in parsed


class TestReadJsonLog:
    """Behavior of the read_json_log helper."""

    def test_missing_file_returns_empty(self, temp_dir: Path) -> None:
        """Reading a non-existent log returns an empty list, not an error."""
        assert read_json_log(temp_dir / "nope.jsonl") == []

    def test_blank_lines_are_skipped(self, log_file: Path) -> None:
        """Blank and whitespace-only lines are ignored by the reader."""
        log_file.write_text('{"type": "a"}\n\n   \n{"type": "b"}\n')
        entries = read_json_log(log_file)
        assert [e["type"] for e in entries] == ["a", "b"]
