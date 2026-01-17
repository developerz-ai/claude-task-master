"""Tests for MCP status, plan, and logs tools.

Tests get_status, get_plan, and get_logs MCP tool implementations.
"""

import pytest

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestGetStatusTool:
    """Test the get_status MCP tool."""

    def test_get_status_no_active_task(self, temp_dir):
        """Test get_status when no task exists."""
        from claude_task_master.mcp.tools import get_status

        result = get_status(temp_dir)
        assert result["success"] is False
        assert "No active task found" in result["error"]

    def test_get_status_with_active_task(self, initialized_state, state_dir):
        """Test get_status with an active task."""
        from claude_task_master.mcp.tools import get_status

        result = get_status(state_dir.parent, str(state_dir))

        assert result["goal"] == "Test goal for MCP"
        assert result["status"] == "planning"
        assert result["model"] == "opus"
        assert result["current_task_index"] == 0
        assert result["session_count"] == 0


class TestGetPlanTool:
    """Test the get_plan MCP tool."""

    def test_get_plan_no_active_task(self, temp_dir):
        """Test get_plan when no task exists."""
        from claude_task_master.mcp.tools import get_plan

        result = get_plan(temp_dir)
        assert result["success"] is False

    def test_get_plan_no_plan_file(self, initialized_state, state_dir):
        """Test get_plan when no plan file exists."""
        from claude_task_master.mcp.tools import get_plan

        result = get_plan(state_dir.parent, str(state_dir))
        assert result["success"] is False
        assert "No plan found" in result.get("error", "")

    def test_get_plan_with_plan(self, state_with_plan, state_dir):
        """Test get_plan with a plan saved."""
        from claude_task_master.mcp.tools import get_plan

        result = get_plan(state_dir.parent, str(state_dir))
        assert result["success"] is True
        assert "plan" in result
        assert "First task to do" in result["plan"]
        assert "Completed task" in result["plan"]


class TestGetLogsTool:
    """Test the get_logs MCP tool."""

    def test_get_logs_no_active_task(self, temp_dir):
        """Test get_logs when no task exists."""
        from claude_task_master.mcp.tools import get_logs

        result = get_logs(temp_dir)
        assert result["success"] is False

    def test_get_logs_no_log_file(self, initialized_state, state_dir):
        """Test get_logs when no log file exists."""
        from claude_task_master.mcp.tools import get_logs

        result = get_logs(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is False
        assert "No log file found" in result.get("error", "")

    def test_get_logs_with_log_file(self, initialized_state, state_dir):
        """Test get_logs with log file present."""
        from claude_task_master.mcp.tools import get_logs

        state_manager, state = initialized_state

        # Create a log file
        log_dir = state_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"run-{state.run_id}.txt"
        log_content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
        log_file.write_text(log_content)

        result = get_logs(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["log_content"] is not None
        assert "Line 1" in result["log_content"]

    def test_get_logs_with_tail_limit(self, initialized_state, state_dir):
        """Test get_logs respects tail parameter."""
        from claude_task_master.mcp.tools import get_logs

        state_manager, state = initialized_state

        # Create a log file with many lines
        log_dir = state_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"run-{state.run_id}.txt"
        log_content = "\n".join([f"Line {i}" for i in range(1, 101)])
        log_file.write_text(log_content)

        result = get_logs(state_dir.parent, tail=5, state_dir=str(state_dir))
        assert result["success"] is True
        # Should only have last 5 lines
        lines = result["log_content"].strip().split("\n")
        assert len(lines) == 5
