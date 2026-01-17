"""Tests for MCP progress and context tools.

Tests get_progress and get_context MCP tool implementations.
"""

import pytest

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestGetProgressTool:
    """Test the get_progress MCP tool."""

    def test_get_progress_no_active_task(self, temp_dir):
        """Test get_progress when no task exists."""
        from claude_task_master.mcp.tools import get_progress

        result = get_progress(temp_dir)
        assert result["success"] is False

    def test_get_progress_no_progress_file(self, initialized_state, state_dir):
        """Test get_progress when no progress file exists."""
        from claude_task_master.mcp.tools import get_progress

        result = get_progress(state_dir.parent, str(state_dir))
        assert result["success"] is True
        assert result["progress"] is None

    def test_get_progress_with_progress(self, initialized_state, state_dir):
        """Test get_progress with progress saved."""
        from claude_task_master.mcp.tools import get_progress

        state_manager, state = initialized_state
        state_manager.save_progress("# Progress\n\nCompleted 2 of 5 tasks")

        result = get_progress(state_dir.parent, str(state_dir))
        assert result["success"] is True
        assert "Completed 2 of 5 tasks" in result["progress"]


class TestGetContextTool:
    """Test the get_context MCP tool."""

    def test_get_context_no_active_task(self, temp_dir):
        """Test get_context when no task exists."""
        from claude_task_master.mcp.tools import get_context

        result = get_context(temp_dir)
        assert result["success"] is False

    def test_get_context_empty(self, initialized_state, state_dir):
        """Test get_context when context is empty."""
        from claude_task_master.mcp.tools import get_context

        result = get_context(state_dir.parent, str(state_dir))
        assert result["success"] is True
        assert result["context"] == ""

    def test_get_context_with_context(self, initialized_state, state_dir):
        """Test get_context with context saved."""
        from claude_task_master.mcp.tools import get_context

        state_manager, state = initialized_state
        state_manager.save_context("# Learnings\n\n- Found bug in auth module")

        result = get_context(state_dir.parent, str(state_dir))
        assert result["success"] is True
        assert "Found bug in auth module" in result["context"]
