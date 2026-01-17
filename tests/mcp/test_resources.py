"""Tests for MCP resource endpoints.

Tests resource functions and their error handling.
"""

import pytest

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestMCPResources:
    """Test MCP resource endpoints."""

    def test_resource_goal_no_task(self, temp_dir):
        """Test resource_goal when no task exists."""
        from claude_task_master.mcp.tools import resource_goal

        result = resource_goal(temp_dir)
        assert "No active task" in result

    def test_resource_goal_with_task(self, initialized_state, state_dir):
        """Test resource_goal returns goal."""
        from claude_task_master.mcp.tools import resource_goal

        result = resource_goal(state_dir.parent)
        assert "Test goal for MCP" in result

    def test_resource_plan_no_task(self, temp_dir):
        """Test resource_plan when no task exists."""
        from claude_task_master.mcp.tools import resource_plan

        result = resource_plan(temp_dir)
        assert "No active task" in result

    def test_resource_plan_with_plan(self, state_with_plan, state_dir):
        """Test resource_plan returns plan."""
        from claude_task_master.mcp.tools import resource_plan

        result = resource_plan(state_dir.parent)
        assert "First task to do" in result

    def test_resource_progress_no_task(self, temp_dir):
        """Test resource_progress when no task exists."""
        from claude_task_master.mcp.tools import resource_progress

        result = resource_progress(temp_dir)
        assert "No active task" in result

    def test_resource_context_no_task(self, temp_dir):
        """Test resource_context when no task exists."""
        from claude_task_master.mcp.tools import resource_context

        result = resource_context(temp_dir)
        assert "No active task" in result


class TestMCPResourceErrorHandling:
    """Test error handling in MCP resources."""

    def test_resource_goal_error(self, temp_dir):
        """Test resource_goal handles errors."""
        from claude_task_master.mcp.tools import resource_goal

        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("{}")
        # No goal.txt file

        result = resource_goal(temp_dir)
        assert "Error loading goal" in result

    def test_resource_plan_error(self, temp_dir):
        """Test resource_plan handles errors."""
        from claude_task_master.mcp.tools import resource_plan

        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("{}")

        result = resource_plan(temp_dir)
        # No plan exists yet
        assert result == "No plan found"

    def test_resource_progress_error(self, temp_dir):
        """Test resource_progress handles errors."""
        from claude_task_master.mcp.tools import resource_progress

        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("{}")

        result = resource_progress(temp_dir)
        # No progress exists yet
        assert result == "No progress recorded"

    def test_resource_context_error(self, temp_dir):
        """Test resource_context handles errors."""
        from claude_task_master.mcp.tools import resource_context

        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("{}")

        result = resource_context(temp_dir)
        # No context or error
        assert result is not None
