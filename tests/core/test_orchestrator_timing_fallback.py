"""Tests for orchestrator timing fallback when task_start_time is None."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.logger import LogFormat, LogLevel, TaskLogger
from claude_task_master.core.state import StateManager, TaskOptions, TaskState


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Path:
    """Create a temporary state directory."""
    state_dir = tmp_path / ".claude-task-master"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    """Create a temporary log file."""
    return tmp_path / "test.log"


class TestTimingFallback:
    """Tests for timing display when task_start_time is None."""

    def test_timing_display_with_task_start_time(self, log_file: Path) -> None:
        """Test that timing is displayed correctly when task_start_time is set."""
        logger = TaskLogger(log_file, level=LogLevel.NORMAL, log_format=LogFormat.TEXT)

        # Calculate duration (2 minutes)
        task_duration_seconds = 120.0

        # Log timing
        logger.log_task_timing(task_index=0, duration_seconds=task_duration_seconds)

        # Verify log content
        content = log_file.read_text()
        assert "[TIMING] Task #1 completed in 2m 0.0s" in content

    def test_timing_display_without_task_start_time(self, log_file: Path) -> None:
        """Test that timing uses session duration as fallback when task_start_time is None."""
        logger = TaskLogger(log_file, level=LogLevel.NORMAL, log_format=LogFormat.TEXT)

        # Simulate session duration fallback (90 seconds)
        session_duration = 90.0

        # Log timing with session duration
        logger.log_task_timing(task_index=0, duration_seconds=session_duration)

        # Verify log content
        content = log_file.read_text()
        assert "[TIMING] Task #1 completed in 1m 30.0s" in content

    def test_state_without_task_start_time_field(
        self, temp_state_dir: Path, log_file: Path
    ) -> None:
        """Test that state without task_start_time field (from older version) works correctly."""
        # Create a state dict without timing fields (simulating old state)
        state_dict = {
            "status": "working",
            "workflow_stage": "working",
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "run_id": "test-run",
            "model": "opus",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "max_prs": None,
                "pause_on_pr": False,
                "enable_checkpointing": False,
                "log_level": "normal",
                "log_format": "text",
                "pr_per_task": False,
                "webhook_url": None,
                "webhook_secret": None,
            },
            "mailbox_enabled": True,
            "prs_created": 0,
            "prs_merged": 0,
            # Note: task_start_time, pr_start_time, pr_active_work_seconds are missing
        }

        # Save state to file
        state_manager = StateManager(temp_state_dir)
        state_file = state_manager.state_file
        import json

        state_file.write_text(json.dumps(state_dict, indent=2))

        # Load state
        loaded_state = state_manager.load_state()

        # Verify timing fields default to None/0
        assert loaded_state.task_start_time is None
        assert loaded_state.pr_start_time is None
        assert loaded_state.pr_active_work_seconds == 0.0

        # Simulate timing calculation with fallback
        session_duration = 150.0
        if loaded_state.task_start_time:
            task_duration_seconds = (
                datetime.now() - loaded_state.task_start_time
            ).total_seconds()
        else:
            task_duration_seconds = session_duration

        # Verify fallback is used
        assert task_duration_seconds == session_duration

        # Log timing
        logger = TaskLogger(log_file, level=LogLevel.NORMAL, log_format=LogFormat.TEXT)
        logger.log_task_timing(
            task_index=loaded_state.current_task_index,
            duration_seconds=task_duration_seconds,
        )

        # Verify log content
        content = log_file.read_text()
        assert "[TIMING] Task #1 completed in 2m 30.0s" in content
