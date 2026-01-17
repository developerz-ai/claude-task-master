"""Tests for MCP tool error handling.

Tests exception handling and error recovery in MCP tools.
"""

from unittest.mock import patch

import pytest

from claude_task_master.core.state import StateManager

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestMCPToolErrorHandling:
    """Test error handling in MCP tools."""

    def test_get_status_exception_handling(self, temp_dir):
        """Test get_status handles exceptions gracefully."""
        from claude_task_master.mcp.tools import get_status

        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("invalid json")

        result = get_status(temp_dir)
        assert result["success"] is False
        assert "error" in result

    def test_get_plan_exception_handling(self, temp_dir):
        """Test get_plan handles exceptions gracefully."""
        from claude_task_master.mcp.tools import get_plan

        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("invalid json")

        result = get_plan(temp_dir)
        assert result["success"] is False
        assert "error" in result

    def test_get_progress_exception_handling(self, temp_dir, monkeypatch):
        """Test get_progress handles exceptions gracefully."""
        from claude_task_master.mcp.tools import get_progress

        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("{}")

        # Mock load_progress to raise an exception
        def mock_load_progress(*args, **kwargs):
            raise RuntimeError("Test error")

        monkeypatch.setattr(StateManager, "load_progress", mock_load_progress)

        result = get_progress(temp_dir)
        assert result["success"] is False
        assert "error" in result

    def test_get_context_exception_handling(self, temp_dir, monkeypatch):
        """Test get_context handles exceptions gracefully."""
        from claude_task_master.mcp.tools import get_context

        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("{}")

        # Mock load_context to raise an exception
        def mock_load_context(*args, **kwargs):
            raise RuntimeError("Test error")

        monkeypatch.setattr(StateManager, "load_context", mock_load_context)

        result = get_context(temp_dir)
        assert result["success"] is False
        assert "error" in result

    def test_get_logs_exception_handling(self, temp_dir):
        """Test get_logs handles exceptions gracefully."""
        from claude_task_master.mcp.tools import get_logs

        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("invalid json")

        result = get_logs(temp_dir)
        assert result["success"] is False
        assert "error" in result

    def test_list_tasks_exception_handling(self, temp_dir):
        """Test list_tasks handles exceptions gracefully."""
        from claude_task_master.mcp.tools import list_tasks

        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("invalid json")

        result = list_tasks(temp_dir)
        assert result["success"] is False
        assert "error" in result

    def test_clean_task_exception_handling(self, initialized_state, state_dir):
        """Test clean_task handles exceptions gracefully."""
        from claude_task_master.mcp import tools as mcp_tools

        # Use context manager patch to ensure proper cleanup
        with patch.object(mcp_tools.shutil, "rmtree") as mock_rmtree:
            mock_rmtree.side_effect = PermissionError("Access denied")

            result = mcp_tools.clean_task(state_dir.parent, force=True, state_dir=str(state_dir))
            assert result["success"] is False
            assert "Failed to clean" in result["message"]
            mock_rmtree.assert_called_once()

    def test_initialize_task_exception_handling(self, temp_dir, monkeypatch):
        """Test initialize_task handles exceptions gracefully."""
        from claude_task_master.mcp.tools import initialize_task

        # Mock StateManager.initialize to raise an exception
        def mock_init(*args, **kwargs):
            raise RuntimeError("Initialization failed")

        monkeypatch.setattr(StateManager, "initialize", mock_init)

        result = initialize_task(temp_dir, goal="Test goal")
        assert result["success"] is False
        assert "Failed to initialize" in result["message"]
