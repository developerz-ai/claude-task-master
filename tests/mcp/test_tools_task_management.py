"""Tests for MCP task management tools.

Tests clean_task, initialize_task, and list_tasks MCP tool implementations.
"""

import pytest

from claude_task_master.core.state import StateManager

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestCleanTaskTool:
    """Test the clean_task MCP tool."""

    def test_clean_task_no_state(self, temp_dir):
        """Test clean_task when no state exists."""
        from claude_task_master.mcp.tools import clean_task

        result = clean_task(temp_dir)
        assert result["success"] is True
        assert result["files_removed"] is False

    def test_clean_task_with_state(self, initialized_state, state_dir):
        """Test clean_task removes state directory."""
        from claude_task_master.mcp.tools import clean_task

        # Verify state exists
        assert state_dir.exists()

        result = clean_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["files_removed"] is True

        # Verify state is removed
        assert not state_dir.exists()


class TestCleanTaskActiveSession:
    """Test clean_task when session is active."""

    def test_clean_task_active_session_no_force(self, initialized_state, state_dir, monkeypatch):
        """Test clean_task fails if session is active and force=False."""
        from claude_task_master.mcp.tools import clean_task

        # Mock is_session_active to return True
        monkeypatch.setattr(StateManager, "is_session_active", lambda self: True)

        result = clean_task(state_dir.parent, force=False, state_dir=str(state_dir))
        assert result["success"] is False
        assert "session is active" in result["message"]

    def test_clean_task_active_session_with_force(self, initialized_state, state_dir, monkeypatch):
        """Test clean_task succeeds with force=True even if session is active."""
        from claude_task_master.mcp.tools import clean_task

        # Mock is_session_active to return True
        monkeypatch.setattr(StateManager, "is_session_active", lambda self: True)

        result = clean_task(state_dir.parent, force=True, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["files_removed"] is True


class TestInitializeTaskTool:
    """Test the initialize_task MCP tool."""

    def test_initialize_task_success(self, temp_dir):
        """Test initialize_task creates new task."""
        from claude_task_master.mcp.tools import initialize_task

        state_dir = temp_dir / ".claude-task-master"
        result = initialize_task(
            temp_dir,
            goal="Create new feature",
            model="sonnet",
            state_dir=str(state_dir),
        )

        assert result["success"] is True
        assert result["run_id"] is not None
        assert result["status"] == "planning"

        # Verify state was created
        assert state_dir.exists()
        state_manager = StateManager(state_dir=state_dir)
        goal = state_manager.load_goal()
        assert goal == "Create new feature"

    def test_initialize_task_already_exists(self, initialized_state, state_dir):
        """Test initialize_task fails if task already exists."""
        from claude_task_master.mcp.tools import initialize_task

        result = initialize_task(
            state_dir.parent,
            goal="Another goal",
            state_dir=str(state_dir),
        )

        assert result["success"] is False
        assert "already exists" in result["message"]

    def test_initialize_task_with_options(self, temp_dir):
        """Test initialize_task respects options."""
        from claude_task_master.mcp.tools import initialize_task

        state_dir = temp_dir / ".claude-task-master"
        result = initialize_task(
            temp_dir,
            goal="Test with options",
            model="haiku",
            auto_merge=False,
            max_sessions=5,
            pause_on_pr=True,
            state_dir=str(state_dir),
        )

        assert result["success"] is True

        # Verify options were saved
        state_manager = StateManager(state_dir=state_dir)
        state = state_manager.load_state()
        assert state.model == "haiku"
        assert state.options.auto_merge is False
        assert state.options.max_sessions == 5
        assert state.options.pause_on_pr is True


class TestListTasksTool:
    """Test the list_tasks MCP tool."""

    def test_list_tasks_no_active_task(self, temp_dir):
        """Test list_tasks when no task exists."""
        from claude_task_master.mcp.tools import list_tasks

        result = list_tasks(temp_dir)
        assert result["success"] is False

    def test_list_tasks_no_plan(self, initialized_state, state_dir):
        """Test list_tasks when no plan exists."""
        from claude_task_master.mcp.tools import list_tasks

        result = list_tasks(state_dir.parent, str(state_dir))
        assert result["success"] is False
        assert "No plan found" in result.get("error", "")

    def test_list_tasks_with_plan(self, state_with_plan, state_dir):
        """Test list_tasks returns parsed tasks."""
        from claude_task_master.mcp.tools import list_tasks

        result = list_tasks(state_dir.parent, str(state_dir))
        assert result["success"] is True
        assert result["total"] == 4
        assert result["completed"] == 1
        assert len(result["tasks"]) == 4

        # Check task structure
        incomplete_tasks = [t for t in result["tasks"] if not t["completed"]]
        completed_tasks = [t for t in result["tasks"] if t["completed"]]
        assert len(incomplete_tasks) == 3
        assert len(completed_tasks) == 1
