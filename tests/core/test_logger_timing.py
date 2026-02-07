"""Tests for logger timing functionality."""

import json
from pathlib import Path

import pytest

from claude_task_master.core.logger import LogFormat, LogLevel, TaskLogger


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    """Create a temporary log file."""
    return tmp_path / "test.log"


class TestTaskTiming:
    """Tests for task timing logs."""

    def test_log_task_timing_text_format(self, log_file: Path) -> None:
        """Test logging task timing in text format."""
        logger = TaskLogger(log_file, level=LogLevel.NORMAL, log_format=LogFormat.TEXT)

        # Log task timing
        logger.log_task_timing(task_index=0, duration_seconds=125.5)

        # Read log content
        content = log_file.read_text()

        assert "[TIMING] Task #1 completed in 2m 5.5s" in content

    def test_log_task_timing_seconds_only(self, log_file: Path) -> None:
        """Test logging task timing with seconds only."""
        logger = TaskLogger(log_file, level=LogLevel.NORMAL, log_format=LogFormat.TEXT)

        # Log task timing
        logger.log_task_timing(task_index=1, duration_seconds=45.2)

        # Read log content
        content = log_file.read_text()

        assert "[TIMING] Task #2 completed in 45.2s" in content

    def test_log_task_timing_json_format(self, log_file: Path) -> None:
        """Test logging task timing in JSON format."""
        logger = TaskLogger(log_file, level=LogLevel.NORMAL, log_format=LogFormat.JSON)

        # Start a session to set current_session
        logger.start_session(1, "working")

        # Log task timing
        logger.log_task_timing(task_index=0, duration_seconds=125.5)

        # Flush JSON entries
        logger._flush_json()

        # Read and parse JSON content
        content = json.loads(log_file.read_text())

        # Find the task_timing entry
        timing_entry = next((e for e in content if e["type"] == "task_timing"), None)
        assert timing_entry is not None
        assert timing_entry["task_index"] == 0
        assert timing_entry["duration_seconds"] == 125.5
        assert timing_entry["session"] == 1


class TestPRTiming:
    """Tests for PR timing logs."""

    def test_log_pr_timing_text_format(self, log_file: Path) -> None:
        """Test logging PR timing in text format."""
        logger = TaskLogger(log_file, level=LogLevel.NORMAL, log_format=LogFormat.TEXT)

        # Log PR timing
        logger.log_pr_timing(
            pr_number=42,
            total_seconds=600.0,  # 10 minutes
            active_work_seconds=300.0,  # 5 minutes
            ci_wait_seconds=300.0,  # 5 minutes
        )

        # Read log content
        content = log_file.read_text()

        assert "[TIMING] PR #42 merged" in content
        assert "Total: 10m 0.0s" in content
        assert "Active work: 5m 0.0s" in content
        assert "CI wait: 5m 0.0s" in content

    def test_log_pr_timing_calculates_ci_wait(self, log_file: Path) -> None:
        """Test PR timing calculation with inferred CI wait."""
        logger = TaskLogger(log_file, level=LogLevel.NORMAL, log_format=LogFormat.TEXT)

        # Log PR timing without explicit ci_wait_seconds
        logger.log_pr_timing(
            pr_number=99,
            total_seconds=900.0,  # 15 minutes
            active_work_seconds=600.0,  # 10 minutes
            # ci_wait_seconds will be calculated: 900 - 600 = 300 (5 minutes)
        )

        # Read log content
        content = log_file.read_text()

        assert "[TIMING] PR #99 merged" in content
        assert "Total: 15m 0.0s" in content
        assert "Active work: 10m 0.0s" in content
        assert "CI wait: 5m 0.0s" in content

    def test_log_pr_timing_json_format(self, log_file: Path) -> None:
        """Test logging PR timing in JSON format."""
        logger = TaskLogger(log_file, level=LogLevel.NORMAL, log_format=LogFormat.JSON)

        # Start a session to set current_session
        logger.start_session(1, "working")

        # Log PR timing
        logger.log_pr_timing(
            pr_number=42,
            total_seconds=600.0,
            active_work_seconds=300.0,
            ci_wait_seconds=300.0,
        )

        # Flush JSON entries
        logger._flush_json()

        # Read and parse JSON content
        content = json.loads(log_file.read_text())

        # Find the pr_timing entry
        timing_entry = next((e for e in content if e["type"] == "pr_timing"), None)
        assert timing_entry is not None
        assert timing_entry["pr_number"] == 42
        assert timing_entry["total_seconds"] == 600.0
        assert timing_entry["active_work_seconds"] == 300.0
        assert timing_entry["ci_wait_seconds"] == 300.0
        assert timing_entry["session"] == 1

    def test_log_pr_timing_seconds_only(self, log_file: Path) -> None:
        """Test logging PR timing with seconds only (no minutes)."""
        logger = TaskLogger(log_file, level=LogLevel.NORMAL, log_format=LogFormat.TEXT)

        # Log PR timing with small durations
        logger.log_pr_timing(
            pr_number=1,
            total_seconds=45.0,
            active_work_seconds=30.0,
            ci_wait_seconds=15.0,
        )

        # Read log content
        content = log_file.read_text()

        assert "[TIMING] PR #1 merged" in content
        assert "Total: 45.0s" in content
        assert "Active work: 30.0s" in content
        assert "CI wait: 15.0s" in content


class TestTimingLogLevels:
    """Test that timing logs are always written regardless of log level."""

    def test_task_timing_logged_at_quiet_level(self, log_file: Path) -> None:
        """Task timing should be logged even at QUIET level."""
        logger = TaskLogger(log_file, level=LogLevel.QUIET, log_format=LogFormat.TEXT)

        logger.log_task_timing(task_index=0, duration_seconds=60.0)

        content = log_file.read_text()
        assert "[TIMING] Task #1 completed in 1m 0.0s" in content

    def test_pr_timing_logged_at_quiet_level(self, log_file: Path) -> None:
        """PR timing should be logged even at QUIET level."""
        logger = TaskLogger(log_file, level=LogLevel.QUIET, log_format=LogFormat.TEXT)

        logger.log_pr_timing(
            pr_number=1,
            total_seconds=120.0,
            active_work_seconds=80.0,
        )

        content = log_file.read_text()
        assert "[TIMING] PR #1 merged" in content
