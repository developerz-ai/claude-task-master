"""Tests for TaskLogger core functionality.

This module covers:
- TaskLogger initialization
- Session logging (start/end)
- Internal helper methods
- File handling behavior
"""

import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest


class TestTaskLoggerInit:
    """Tests for TaskLogger initialization."""

    def test_init_with_path(self, log_file: Path):
        """Test TaskLogger initialization with a log file path."""
        from claude_task_master.core.logger import TaskLogger

        logger = TaskLogger(log_file)

        assert logger.log_file == log_file
        assert logger.current_session is None
        assert logger.session_start is None

    def test_init_with_custom_max_line_length(self, log_file: Path):
        """Test TaskLogger initialization with custom max line length."""
        from claude_task_master.core.logger import TaskLogger

        logger = TaskLogger(log_file, max_line_length=100)

        assert logger.max_line_length == 100

    def test_init_creates_logger_without_file(self, temp_dir: Path):
        """Test that TaskLogger can be created even if file doesn't exist yet."""
        from claude_task_master.core.logger import TaskLogger

        non_existent_file = temp_dir / "non_existent" / "log.txt"
        logger = TaskLogger(non_existent_file)

        assert logger.log_file == non_existent_file


class TestSessionLogging:
    """Tests for session logging functionality."""

    def test_start_session(self, task_logger, log_file: Path):
        """Test starting a new logging session."""
        task_logger.start_session(session_number=1, phase="planning")

        assert task_logger.current_session == 1
        assert task_logger.session_start is not None
        assert isinstance(task_logger.session_start, datetime)

        # Verify log file contents (compact format)
        content = log_file.read_text()
        assert "SESSION 1" in content
        assert "PLANNING" in content
        assert "===" in content

    def test_start_session_work_phase(self, task_logger, log_file: Path):
        """Test starting a session with work phase."""
        task_logger.start_session(session_number=5, phase="work")

        content = log_file.read_text()
        assert "SESSION 5" in content
        assert "WORK" in content

    def test_start_session_verification_phase(self, task_logger, log_file: Path):
        """Test starting a session with verification phase."""
        task_logger.start_session(session_number=10, phase="verification")

        content = log_file.read_text()
        assert "SESSION 10" in content
        assert "VERIFICATION" in content

    def test_start_multiple_sessions(self, task_logger, log_file: Path):
        """Test starting multiple sessions updates state correctly."""
        task_logger.start_session(session_number=1, phase="planning")
        first_start = task_logger.session_start

        # Small delay to ensure different timestamp
        time.sleep(0.01)

        task_logger.start_session(session_number=2, phase="work")

        assert task_logger.current_session == 2
        assert task_logger.session_start != first_start

        content = log_file.read_text()
        assert "SESSION 1" in content
        assert "PLANNING" in content
        assert "SESSION 2" in content
        assert "WORK" in content

    def test_end_session(self, task_logger, log_file: Path):
        """Test ending a session."""
        task_logger.start_session(session_number=1, phase="planning")

        # Small delay to have measurable duration
        time.sleep(0.05)

        task_logger.end_session(outcome="success")

        assert task_logger.current_session is None
        assert task_logger.session_start is None

        content = log_file.read_text()
        assert "END" in content
        assert "success" in content
        assert "s" in content  # seconds indicator

    def test_end_session_with_failure_outcome(self, task_logger, log_file: Path):
        """Test ending a session with failure outcome."""
        task_logger.start_session(session_number=1, phase="work")
        task_logger.end_session(outcome="failed - max retries exceeded")

        content = log_file.read_text()
        assert "failed - max retries exceeded" in content

    def test_end_session_without_start(self, task_logger, log_file: Path):
        """Test ending a session without starting one first."""
        # Should not crash, just not write duration
        task_logger.end_session(outcome="orphan_end")

        assert task_logger.current_session is None
        assert task_logger.session_start is None


class TestInternalMethods:
    """Tests for internal helper methods."""

    def test_write_creates_file(self, temp_dir: Path):
        """Test that _write creates the file if it doesn't exist."""
        from claude_task_master.core.logger import TaskLogger

        log_file = temp_dir / "new_log.txt"
        logger = TaskLogger(log_file)

        logger._write("test message")

        assert log_file.exists()
        assert log_file.read_text() == "test message\n"

    def test_write_appends_to_file(self, task_logger, log_file: Path):
        """Test that _write appends to existing file."""
        task_logger._write("line 1")
        task_logger._write("line 2")
        task_logger._write("line 3")

        content = log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 3
        assert lines[0] == "line 1"
        assert lines[1] == "line 2"
        assert lines[2] == "line 3"

    def test_write_empty_string(self, task_logger, log_file: Path):
        """Test _write with empty string."""
        task_logger._write("")

        content = log_file.read_text()
        assert content == "\n"

    def test_format_params_json(self, task_logger):
        """Test that parameters are formatted as compact JSON."""
        params = {"key": "value", "num": 42}
        result = task_logger._format_params(params)

        assert '"key":"value"' in result
        assert '"num":42' in result


class TestFileHandling:
    """Tests for file handling behavior."""

    def test_creates_parent_directory(self, temp_dir: Path):
        """Test that writing creates parent directories if needed."""
        from claude_task_master.core.logger import TaskLogger

        nested_path = temp_dir / "deep" / "nested" / "path" / "log.txt"
        nested_path.parent.mkdir(parents=True, exist_ok=True)

        logger = TaskLogger(nested_path)
        logger._write("test")

        assert nested_path.exists()

    def test_append_mode(self, task_logger, log_file: Path):
        """Test that logger always appends and never overwrites."""
        # Write some initial content
        task_logger._write("initial content")

        # Create a new logger instance pointing to the same file
        from claude_task_master.core.logger import TaskLogger

        new_logger = TaskLogger(log_file)
        new_logger._write("new content")

        content = log_file.read_text()
        assert "initial content" in content
        assert "new content" in content

    def test_handles_file_permission_error(self, temp_dir: Path, monkeypatch):
        """Test handling of permission errors gracefully."""
        from claude_task_master.core.logger import TaskLogger

        log_file = temp_dir / "readonly.txt"
        logger = TaskLogger(log_file)

        # Mock open to raise PermissionError
        def raise_permission_error(*args, **kwargs):
            raise PermissionError("Cannot write to file")

        with pytest.raises(PermissionError):
            with patch("builtins.open", side_effect=raise_permission_error):
                logger._write("test")
