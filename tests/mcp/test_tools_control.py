"""Tests for MCP control tools.

Tests pause_task, stop_task, resume_task, and update_config tool implementations.
"""

import pytest

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestPauseTaskTool:
    """Test the pause_task MCP tool."""

    def test_pause_task_no_active_task(self, temp_dir):
        """Test pause_task when no task exists."""
        from claude_task_master.mcp.tools import pause_task

        result = pause_task(temp_dir)
        assert result["success"] is False
        assert "No active task found" in result["message"]

    def test_pause_task_from_planning(self, initialized_state, state_dir):
        """Test pausing a task in planning status."""
        from claude_task_master.mcp.tools import pause_task

        state_manager, state = initialized_state
        # State is initialized with status "planning"
        assert state.status == "planning"

        result = pause_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["previous_status"] == "planning"
        assert result["new_status"] == "paused"
        assert "paused successfully" in result["message"]

        # Verify state was updated
        updated_state = state_manager.load_state()
        assert updated_state.status == "paused"

    def test_pause_task_from_working(self, initialized_state, state_dir):
        """Test pausing a task in working status."""
        from claude_task_master.mcp.tools import pause_task

        state_manager, state = initialized_state
        # Change status to working
        state.status = "working"
        state_manager.save_state(state)

        result = pause_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["previous_status"] == "working"
        assert result["new_status"] == "paused"

    def test_pause_task_with_reason(self, initialized_state, state_dir):
        """Test pausing with a reason updates progress."""
        from claude_task_master.mcp.tools import pause_task

        state_manager, _ = initialized_state
        reason = "Need to review before continuing"

        result = pause_task(state_dir.parent, reason=reason, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["reason"] == reason

        # Verify reason was added to progress
        progress = state_manager.load_progress()
        assert progress is not None
        assert reason in progress
        assert "## Paused" in progress

    def test_pause_task_invalid_status(self, initialized_state, state_dir):
        """Test pause fails when task is in non-pausable status."""
        from claude_task_master.mcp.tools import pause_task

        state_manager, state = initialized_state
        # Set to a non-pausable status - transition planning -> working -> blocked
        state.status = "working"
        state_manager.save_state(state)
        state.status = "blocked"
        state_manager.save_state(state)

        result = pause_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is False
        assert result["previous_status"] == "blocked"
        assert "Cannot pause task" in result["message"]

    def test_pause_task_already_paused(self, initialized_state, state_dir):
        """Test pause fails when task is already paused."""
        from claude_task_master.mcp.tools import pause_task

        state_manager, state = initialized_state
        state.status = "paused"
        state_manager.save_state(state)

        result = pause_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is False
        assert result["previous_status"] == "paused"


class TestStopTaskTool:
    """Test the stop_task MCP tool."""

    def test_stop_task_no_active_task(self, temp_dir):
        """Test stop_task when no task exists."""
        from claude_task_master.mcp.tools import stop_task

        result = stop_task(temp_dir)
        assert result["success"] is False
        assert "No active task found" in result["message"]

    def test_stop_task_from_planning(self, initialized_state, state_dir):
        """Test stopping a task in planning status."""
        from claude_task_master.mcp.tools import stop_task

        state_manager, state = initialized_state
        assert state.status == "planning"

        result = stop_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["previous_status"] == "planning"
        assert result["new_status"] == "stopped"
        assert "stopped successfully" in result["message"]

        # Verify state was updated
        updated_state = state_manager.load_state()
        assert updated_state.status == "stopped"

    def test_stop_task_from_working(self, initialized_state, state_dir):
        """Test stopping a task in working status."""
        from claude_task_master.mcp.tools import stop_task

        state_manager, state = initialized_state
        state.status = "working"
        state_manager.save_state(state)

        result = stop_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["previous_status"] == "working"
        assert result["new_status"] == "stopped"

    def test_stop_task_from_paused(self, initialized_state, state_dir):
        """Test stopping a paused task."""
        from claude_task_master.mcp.tools import stop_task

        state_manager, state = initialized_state
        state.status = "paused"
        state_manager.save_state(state)

        result = stop_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["previous_status"] == "paused"
        assert result["new_status"] == "stopped"

    def test_stop_task_from_blocked(self, initialized_state, state_dir):
        """Test stopping a blocked task."""
        from claude_task_master.mcp.tools import stop_task

        state_manager, state = initialized_state
        # Transition planning -> working -> blocked
        state.status = "working"
        state_manager.save_state(state)
        state.status = "blocked"
        state_manager.save_state(state)

        result = stop_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["previous_status"] == "blocked"
        assert result["new_status"] == "stopped"

    def test_stop_task_with_reason(self, initialized_state, state_dir):
        """Test stopping with a reason updates progress."""
        from claude_task_master.mcp.tools import stop_task

        state_manager, _ = initialized_state
        reason = "Critical bug discovered"

        result = stop_task(state_dir.parent, reason=reason, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["reason"] == reason

        # Verify reason was added to progress
        progress = state_manager.load_progress()
        assert progress is not None
        assert reason in progress
        assert "## Stopped" in progress

    def test_stop_task_with_cleanup(self, initialized_state, state_dir):
        """Test stopping with cleanup flag."""
        from claude_task_master.mcp.tools import stop_task

        state_manager, state = initialized_state

        result = stop_task(state_dir.parent, cleanup=True, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["cleanup"] is True

    def test_stop_task_invalid_status(self, initialized_state, state_dir):
        """Test stop fails when task is in non-stoppable status."""
        from claude_task_master.mcp.tools import stop_task

        state_manager, state = initialized_state
        # Transition to a terminal status (success) - planning -> working -> success
        state.status = "working"
        state_manager.save_state(state)
        state.status = "success"
        state_manager.save_state(state)

        result = stop_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is False
        assert result["previous_status"] == "success"
        assert "Cannot stop task" in result["message"]


class TestResumeTaskTool:
    """Test the resume_task MCP tool."""

    def test_resume_task_no_active_task(self, temp_dir):
        """Test resume_task when no task exists."""
        from claude_task_master.mcp.tools import resume_task

        result = resume_task(temp_dir)
        assert result["success"] is False
        assert "No active task found" in result["message"]

    def test_resume_task_from_paused(self, initialized_state, state_dir):
        """Test resuming a paused task."""
        from claude_task_master.mcp.tools import resume_task

        state_manager, state = initialized_state
        state.status = "paused"
        state_manager.save_state(state)

        result = resume_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["previous_status"] == "paused"
        assert result["new_status"] == "working"
        assert "resumed successfully" in result["message"]

        # Verify state was updated
        updated_state = state_manager.load_state()
        assert updated_state.status == "working"

    def test_resume_task_from_blocked(self, initialized_state, state_dir):
        """Test resuming a blocked task."""
        from claude_task_master.mcp.tools import resume_task

        state_manager, state = initialized_state
        # Transition planning -> working -> blocked
        state.status = "working"
        state_manager.save_state(state)
        state.status = "blocked"
        state_manager.save_state(state)

        result = resume_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["previous_status"] == "blocked"
        assert result["new_status"] == "working"

    def test_resume_task_from_stopped(self, initialized_state, state_dir):
        """Test resuming a stopped task."""
        from claude_task_master.mcp.tools import resume_task

        state_manager, state = initialized_state
        state.status = "stopped"
        state_manager.save_state(state)

        result = resume_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["previous_status"] == "stopped"
        assert result["new_status"] == "working"

    def test_resume_task_updates_progress(self, initialized_state, state_dir):
        """Test resume updates progress file."""
        from claude_task_master.mcp.tools import resume_task

        state_manager, state = initialized_state
        state.status = "paused"
        state_manager.save_state(state)

        result = resume_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True

        # Verify progress was updated
        progress = state_manager.load_progress()
        assert progress is not None
        assert "## Resumed" in progress
        assert "paused" in progress

    def test_resume_task_invalid_status(self, initialized_state, state_dir):
        """Test resume fails when task is in non-resumable status."""
        from claude_task_master.mcp.tools import resume_task

        state_manager, state = initialized_state
        # "planning" is not resumable
        state.status = "planning"
        state_manager.save_state(state)

        result = resume_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is False
        assert result["previous_status"] == "planning"
        assert "Cannot resume task" in result["message"]

    def test_resume_task_from_working(self, initialized_state, state_dir):
        """Test resume from working status (allowed for retry scenarios)."""
        from claude_task_master.mcp.tools import resume_task

        state_manager, state = initialized_state
        # Transition to working
        state.status = "working"
        state_manager.save_state(state)

        # Resume from working is allowed (for retry scenarios)
        result = resume_task(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is True
        assert result["previous_status"] == "working"
        assert result["new_status"] == "working"


class TestUpdateConfigTool:
    """Test the update_config MCP tool."""

    def test_update_config_no_active_task(self, temp_dir):
        """Test update_config when no task exists."""
        from claude_task_master.mcp.tools import update_config

        result = update_config(temp_dir, auto_merge=False)
        assert result["success"] is False
        assert "No active task found" in result["message"]

    def test_update_config_no_options(self, initialized_state, state_dir):
        """Test update_config fails when no options provided."""
        from claude_task_master.mcp.tools import update_config

        result = update_config(state_dir.parent, state_dir=str(state_dir))
        assert result["success"] is False
        assert "No configuration options provided" in result["message"]

    def test_update_config_auto_merge(self, initialized_state, state_dir):
        """Test updating auto_merge option."""
        from claude_task_master.mcp.tools import update_config

        state_manager, state = initialized_state
        original_auto_merge = state.options.auto_merge

        result = update_config(
            state_dir.parent,
            auto_merge=not original_auto_merge,
            state_dir=str(state_dir),
        )
        assert result["success"] is True
        assert result["updated"] is not None
        assert "auto_merge" in result["updated"]
        assert result["updated"]["auto_merge"] == (not original_auto_merge)

        # Verify state was updated
        updated_state = state_manager.load_state()
        assert updated_state.options.auto_merge == (not original_auto_merge)

    def test_update_config_max_sessions(self, initialized_state, state_dir):
        """Test updating max_sessions option."""
        from claude_task_master.mcp.tools import update_config

        state_manager, _ = initialized_state

        result = update_config(
            state_dir.parent,
            max_sessions=20,
            state_dir=str(state_dir),
        )
        assert result["success"] is True
        assert result["updated"] is not None
        assert "max_sessions" in result["updated"]
        assert result["updated"]["max_sessions"] == 20

        # Verify state was updated
        updated_state = state_manager.load_state()
        assert updated_state.options.max_sessions == 20

    def test_update_config_pause_on_pr(self, initialized_state, state_dir):
        """Test updating pause_on_pr option."""
        from claude_task_master.mcp.tools import update_config

        state_manager, state = initialized_state
        original_pause_on_pr = state.options.pause_on_pr

        result = update_config(
            state_dir.parent,
            pause_on_pr=not original_pause_on_pr,
            state_dir=str(state_dir),
        )
        assert result["success"] is True
        assert result["updated"] is not None
        assert "pause_on_pr" in result["updated"]

        # Verify state was updated
        updated_state = state_manager.load_state()
        assert updated_state.options.pause_on_pr == (not original_pause_on_pr)

    def test_update_config_parallel_off(self, initialized_state, state_dir):
        """update_config turns hive fan-out off (it is on by default)."""
        from claude_task_master.mcp.tools import update_config

        state_manager, state = initialized_state
        assert state.options.parallel is True

        result = update_config(
            state_dir.parent,
            parallel=False,
            state_dir=str(state_dir),
        )
        assert result["success"] is True
        assert result["updated"] is not None
        assert result["updated"]["parallel"] is False

        assert state_manager.load_state().options.parallel is False

    def test_update_config_parallel_on(self, initialized_state, state_dir):
        """update_config turns hive fan-out back on."""
        from claude_task_master.mcp.tools import update_config

        state_manager, _ = initialized_state
        update_config(state_dir.parent, parallel=False, state_dir=str(state_dir))

        result = update_config(
            state_dir.parent,
            parallel=True,
            state_dir=str(state_dir),
        )
        assert result["success"] is True
        assert state_manager.load_state().options.parallel is True

    def test_update_config_multiple_options(self, initialized_state, state_dir):
        """Test updating multiple options at once."""
        from claude_task_master.mcp.tools import update_config

        state_manager, _ = initialized_state

        result = update_config(
            state_dir.parent,
            auto_merge=False,
            max_sessions=15,
            pause_on_pr=True,
            state_dir=str(state_dir),
        )
        assert result["success"] is True
        assert result["updated"] is not None
        assert "auto_merge" in result["updated"]
        assert "max_sessions" in result["updated"]
        assert "pause_on_pr" in result["updated"]

        # Verify all were updated
        updated_state = state_manager.load_state()
        assert updated_state.options.auto_merge is False
        assert updated_state.options.max_sessions == 15
        assert updated_state.options.pause_on_pr is True

    def test_update_config_pr_per_task(self, initialized_state, state_dir):
        """Test updating pr_per_task option."""
        from claude_task_master.mcp.tools import update_config

        state_manager, state = initialized_state
        original_pr_per_task = state.options.pr_per_task

        result = update_config(
            state_dir.parent,
            pr_per_task=not original_pr_per_task,
            state_dir=str(state_dir),
        )
        assert result["success"] is True
        assert result["updated"] is not None
        assert "pr_per_task" in result["updated"]

        # Verify state was updated
        updated_state = state_manager.load_state()
        assert updated_state.options.pr_per_task == (not original_pr_per_task)

    def test_update_config_with_none_value(self, initialized_state, state_dir):
        """Test update_config ignores None values."""
        from claude_task_master.mcp.tools import update_config

        state_manager, state = initialized_state
        original_auto_merge = state.options.auto_merge

        # Pass None value - should be ignored
        result = update_config(
            state_dir.parent,
            auto_merge=None,
            max_sessions=None,
            state_dir=str(state_dir),
        )
        # Should fail because all values are None (no options provided)
        assert result["success"] is False
        assert "No configuration options provided" in result["message"]

        # Verify nothing changed
        updated_state = state_manager.load_state()
        assert updated_state.options.auto_merge == original_auto_merge

    def test_update_config_returns_current_options(self, initialized_state, state_dir):
        """Test update_config returns current options in response."""
        from claude_task_master.mcp.tools import update_config

        result = update_config(
            state_dir.parent,
            auto_merge=True,
            state_dir=str(state_dir),
        )
        assert result["success"] is True
        assert result["current"] is not None
        assert "auto_merge" in result["current"]
        assert "max_sessions" in result["current"]
        assert "pause_on_pr" in result["current"]

    def test_update_config_no_change_needed(self, initialized_state, state_dir):
        """Test update_config when value is already set."""
        from claude_task_master.mcp.tools import update_config

        state_manager, state = initialized_state
        current_auto_merge = state.options.auto_merge

        # Try to set to the same value
        result = update_config(
            state_dir.parent,
            auto_merge=current_auto_merge,
            state_dir=str(state_dir),
        )
        assert result["success"] is True
        # Updated dict should be empty (no changes)
        assert result["updated"] == {}


class TestControlToolsIntegration:
    """Integration tests for control tools working together."""

    def test_pause_and_resume_flow(self, initialized_state, state_dir):
        """Test pause followed by resume."""
        from claude_task_master.mcp.tools import pause_task, resume_task

        state_manager, state = initialized_state
        state.status = "working"
        state_manager.save_state(state)

        # Pause
        pause_result = pause_task(state_dir.parent, state_dir=str(state_dir))
        assert pause_result["success"] is True

        # Resume
        resume_result = resume_task(state_dir.parent, state_dir=str(state_dir))
        assert resume_result["success"] is True
        assert resume_result["previous_status"] == "paused"
        assert resume_result["new_status"] == "working"

    def test_stop_and_resume_flow(self, initialized_state, state_dir):
        """Test stop followed by resume."""
        from claude_task_master.mcp.tools import resume_task, stop_task

        state_manager, state = initialized_state
        state.status = "working"
        state_manager.save_state(state)

        # Stop
        stop_result = stop_task(state_dir.parent, state_dir=str(state_dir))
        assert stop_result["success"] is True

        # Resume from stopped
        resume_result = resume_task(state_dir.parent, state_dir=str(state_dir))
        assert resume_result["success"] is True
        assert resume_result["previous_status"] == "stopped"

    def test_config_update_during_pause(self, initialized_state, state_dir):
        """Test updating config while task is paused."""
        from claude_task_master.mcp.tools import pause_task, update_config

        state_manager, state = initialized_state
        state.status = "working"
        state_manager.save_state(state)

        # Pause
        pause_result = pause_task(state_dir.parent, state_dir=str(state_dir))
        assert pause_result["success"] is True

        # Update config while paused
        update_result = update_config(
            state_dir.parent,
            max_sessions=25,
            state_dir=str(state_dir),
        )
        assert update_result["success"] is True

        # Verify config was updated
        updated_state = state_manager.load_state()
        assert updated_state.options.max_sessions == 25
        assert updated_state.status == "paused"

    def test_multiple_pauses_not_allowed(self, initialized_state, state_dir):
        """Test that pausing an already paused task fails."""
        from claude_task_master.mcp.tools import pause_task

        state_manager, state = initialized_state
        state.status = "working"
        state_manager.save_state(state)

        # First pause succeeds
        result1 = pause_task(state_dir.parent, state_dir=str(state_dir))
        assert result1["success"] is True

        # Second pause fails
        result2 = pause_task(state_dir.parent, state_dir=str(state_dir))
        assert result2["success"] is False
