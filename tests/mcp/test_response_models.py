"""Tests for MCP response model classes.

Tests the Pydantic models used for MCP tool responses.
"""

import pytest

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestResponseModels:
    """Test response model classes."""

    def test_task_status_model(self):
        """Test TaskStatus model."""
        from claude_task_master.mcp.tools import TaskStatus

        status = TaskStatus(
            goal="Test goal",
            status="working",
            model="opus",
            current_task_index=1,
            session_count=2,
            run_id="test-123",
            options={"auto_merge": True},
        )
        assert status.goal == "Test goal"
        assert status.status == "working"

    def test_start_task_result_model(self):
        """Test StartTaskResult model."""
        from claude_task_master.mcp.tools import StartTaskResult

        result = StartTaskResult(
            success=True,
            message="Task started",
            run_id="test-123",
            status="planning",
        )
        assert result.success is True
        assert result.run_id == "test-123"

    def test_clean_result_model(self):
        """Test CleanResult model."""
        from claude_task_master.mcp.tools import CleanResult

        result = CleanResult(
            success=True,
            message="Cleaned",
            files_removed=True,
        )
        assert result.success is True
        assert result.files_removed is True

    def test_logs_result_model(self):
        """Test LogsResult model."""
        from claude_task_master.mcp.tools import LogsResult

        result = LogsResult(
            success=True,
            log_content="Some logs",
            log_file="/path/to/log.txt",
        )
        assert result.success is True
        assert result.log_content == "Some logs"

    def test_health_check_result_model(self):
        """Test HealthCheckResult model."""
        from claude_task_master.mcp.tools import HealthCheckResult

        result = HealthCheckResult(
            status="healthy",
            version="1.0.0",
            server_name="test-server",
            uptime_seconds=123.45,
            active_tasks=2,
        )
        assert result.status == "healthy"
        assert result.version == "1.0.0"
        assert result.server_name == "test-server"
        assert result.uptime_seconds == 123.45
        assert result.active_tasks == 2
