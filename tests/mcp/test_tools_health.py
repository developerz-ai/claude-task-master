"""Tests for MCP health check tool.

Tests the health_check MCP tool implementation.
"""

import time

import pytest

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestHealthCheckTool:
    """Test the health_check MCP tool."""

    def test_health_check_basic(self, temp_dir):
        """Test basic health check returns expected structure."""
        from claude_task_master.mcp.tools import health_check

        result = health_check(temp_dir, "test-server")

        assert result["status"] == "healthy"
        assert result["server_name"] == "test-server"
        assert "version" in result
        assert result["active_tasks"] == 0

    def test_health_check_with_uptime(self, temp_dir):
        """Test health check includes uptime when start_time provided."""
        from claude_task_master.mcp.tools import health_check

        start_time = time.time()
        time.sleep(0.1)  # Small delay to ensure uptime > 0

        result = health_check(temp_dir, "test-server", start_time)

        assert result["status"] == "healthy"
        assert result["uptime_seconds"] is not None
        assert result["uptime_seconds"] > 0

    def test_health_check_with_active_task(self, initialized_state, state_dir):
        """Test health check detects active task."""
        from claude_task_master.mcp.tools import health_check

        result = health_check(state_dir.parent, "test-server")

        assert result["status"] == "healthy"
        assert result["active_tasks"] == 1

    def test_health_check_no_uptime(self, temp_dir):
        """Test health check without start_time doesn't include uptime."""
        from claude_task_master.mcp.tools import health_check

        result = health_check(temp_dir, "test-server", None)

        assert result["status"] == "healthy"
        assert result["uptime_seconds"] is None

    def test_health_check_corrupted_state(self, temp_dir):
        """Test health check handles corrupted state gracefully."""
        from claude_task_master.mcp.tools import health_check

        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("invalid json")

        result = health_check(temp_dir, "test-server")

        # Should still return healthy even if state is corrupted
        assert result["status"] == "healthy"
        assert result["active_tasks"] == 0
