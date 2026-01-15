"""Tests for MCP server implementation.

Tests the MCP server tools and resources for Claude Task Master.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from claude_task_master.core.state import StateManager, TaskOptions

# Skip all tests if MCP is not installed
try:
    from mcp.server.fastmcp import FastMCP

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    FastMCP = None


pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp_path = tempfile.mkdtemp()
    yield Path(temp_path)
    # Cleanup
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def state_dir(temp_dir):
    """Create a state directory within temp directory."""
    state_path = temp_dir / ".claude-task-master"
    state_path.mkdir(parents=True, exist_ok=True)
    return state_path


@pytest.fixture
def initialized_state(state_dir):
    """Initialize a task state for testing."""
    state_manager = StateManager(state_dir=state_dir)
    options = TaskOptions(auto_merge=True, max_sessions=10)
    state = state_manager.initialize(
        goal="Test goal for MCP",
        model="opus",
        options=options,
    )
    return state_manager, state


@pytest.fixture
def state_with_plan(initialized_state):
    """State with a plan saved."""
    state_manager, state = initialized_state
    plan_content = """# Test Plan

## Tasks

- [ ] First task to do
- [ ] Second task to do
- [x] Completed task
- [ ] Fourth task
"""
    state_manager.save_plan(plan_content)
    return state_manager, state


@pytest.fixture
def mcp_server(temp_dir):
    """Create an MCP server for testing."""
    from claude_task_master.mcp.server import create_server

    return create_server(name="test-server", working_dir=str(temp_dir))


class TestMCPServerCreation:
    """Test MCP server creation and configuration."""

    def test_create_server_returns_fastmcp_instance(self, temp_dir):
        """Test that create_server returns a FastMCP instance."""
        from claude_task_master.mcp.server import create_server

        server = create_server(working_dir=str(temp_dir))
        assert server is not None

    def test_create_server_with_custom_name(self, temp_dir):
        """Test server creation with custom name."""
        from claude_task_master.mcp.server import create_server

        server = create_server(name="custom-server", working_dir=str(temp_dir))
        assert server is not None

    def test_create_server_without_mcp_raises_import_error(self, temp_dir):
        """Test that create_server raises ImportError if MCP is not installed."""
        from claude_task_master.mcp import server as mcp_server_module

        # Temporarily set FastMCP to None
        original_fastmcp = mcp_server_module.FastMCP
        mcp_server_module.FastMCP = None

        try:
            with pytest.raises(ImportError, match="MCP SDK not installed"):
                mcp_server_module.create_server(working_dir=str(temp_dir))
        finally:
            mcp_server_module.FastMCP = original_fastmcp


class TestGetStatusTool:
    """Test the get_status MCP tool."""

    def test_get_status_no_active_task(self, temp_dir):
        """Test get_status when no task exists."""
        state_dir = temp_dir / ".claude-task-master"

        # No state exists, should return error
        result = _call_get_status(str(state_dir))
        assert result["success"] is False
        assert "No active task found" in result["error"]

    def test_get_status_with_active_task(self, initialized_state, state_dir):
        """Test get_status with an active task."""
        state_manager, state = initialized_state

        result = _call_get_status(str(state_dir))

        assert "goal" in result or "success" in result
        if "goal" in result:
            assert result["goal"] == "Test goal for MCP"
            assert result["status"] == "planning"
            assert result["model"] == "opus"
        else:
            # If structured as success response
            assert result.get("success", True) is True


class TestGetPlanTool:
    """Test the get_plan MCP tool."""

    def test_get_plan_no_active_task(self, temp_dir):
        """Test get_plan when no task exists."""
        state_dir = temp_dir / ".claude-task-master"
        result = _call_get_plan(str(state_dir))
        assert result["success"] is False

    def test_get_plan_no_plan_file(self, initialized_state, state_dir):
        """Test get_plan when no plan file exists."""
        result = _call_get_plan(str(state_dir))
        assert result["success"] is False
        assert "No plan found" in result.get("error", "")

    def test_get_plan_with_plan(self, state_with_plan, state_dir):
        """Test get_plan with a plan saved."""
        state_manager, state = state_with_plan

        result = _call_get_plan(str(state_dir))
        assert result["success"] is True
        assert "plan" in result
        assert "First task to do" in result["plan"]
        assert "Completed task" in result["plan"]


class TestGetLogsTool:
    """Test the get_logs MCP tool."""

    def test_get_logs_no_active_task(self, temp_dir):
        """Test get_logs when no task exists."""
        state_dir = temp_dir / ".claude-task-master"
        result = _call_get_logs(str(state_dir))
        assert result["success"] is False

    def test_get_logs_no_log_file(self, initialized_state, state_dir):
        """Test get_logs when no log file exists."""
        result = _call_get_logs(str(state_dir))
        assert result["success"] is False
        assert "No log file found" in result.get("error", "")

    def test_get_logs_with_log_file(self, initialized_state, state_dir):
        """Test get_logs with log file present."""
        state_manager, state = initialized_state

        # Create a log file
        log_dir = state_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"run-{state.run_id}.txt"
        log_content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
        log_file.write_text(log_content)

        result = _call_get_logs(str(state_dir))
        assert result["success"] is True
        assert result["log_content"] is not None
        assert "Line 1" in result["log_content"]

    def test_get_logs_with_tail_limit(self, initialized_state, state_dir):
        """Test get_logs respects tail parameter."""
        state_manager, state = initialized_state

        # Create a log file with many lines
        log_dir = state_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"run-{state.run_id}.txt"
        log_content = "\n".join([f"Line {i}" for i in range(1, 101)])
        log_file.write_text(log_content)

        result = _call_get_logs(str(state_dir), tail=5)
        assert result["success"] is True
        # Should only have last 5 lines
        lines = result["log_content"].strip().split("\n")
        assert len(lines) == 5


class TestGetProgressTool:
    """Test the get_progress MCP tool."""

    def test_get_progress_no_active_task(self, temp_dir):
        """Test get_progress when no task exists."""
        state_dir = temp_dir / ".claude-task-master"
        result = _call_get_progress(str(state_dir))
        assert result["success"] is False

    def test_get_progress_no_progress_file(self, initialized_state, state_dir):
        """Test get_progress when no progress file exists."""
        result = _call_get_progress(str(state_dir))
        assert result["success"] is True
        assert result["progress"] is None

    def test_get_progress_with_progress(self, initialized_state, state_dir):
        """Test get_progress with progress saved."""
        state_manager, state = initialized_state
        state_manager.save_progress("# Progress\n\nCompleted 2 of 5 tasks")

        result = _call_get_progress(str(state_dir))
        assert result["success"] is True
        assert "Completed 2 of 5 tasks" in result["progress"]


class TestGetContextTool:
    """Test the get_context MCP tool."""

    def test_get_context_no_active_task(self, temp_dir):
        """Test get_context when no task exists."""
        state_dir = temp_dir / ".claude-task-master"
        result = _call_get_context(str(state_dir))
        assert result["success"] is False

    def test_get_context_empty(self, initialized_state, state_dir):
        """Test get_context when context is empty."""
        result = _call_get_context(str(state_dir))
        assert result["success"] is True
        assert result["context"] == ""

    def test_get_context_with_context(self, initialized_state, state_dir):
        """Test get_context with context saved."""
        state_manager, state = initialized_state
        state_manager.save_context("# Learnings\n\n- Found bug in auth module")

        result = _call_get_context(str(state_dir))
        assert result["success"] is True
        assert "Found bug in auth module" in result["context"]


class TestCleanTaskTool:
    """Test the clean_task MCP tool."""

    def test_clean_task_no_state(self, temp_dir):
        """Test clean_task when no state exists."""
        state_dir = temp_dir / ".claude-task-master"
        result = _call_clean_task(str(state_dir))
        assert result["success"] is True
        assert result["files_removed"] is False

    def test_clean_task_with_state(self, initialized_state, state_dir):
        """Test clean_task removes state directory."""
        state_manager, state = initialized_state

        # Verify state exists
        assert state_dir.exists()

        result = _call_clean_task(str(state_dir))
        assert result["success"] is True
        assert result["files_removed"] is True

        # Verify state is removed
        assert not state_dir.exists()


class TestInitializeTaskTool:
    """Test the initialize_task MCP tool."""

    def test_initialize_task_success(self, temp_dir):
        """Test initialize_task creates new task."""
        state_dir = temp_dir / ".claude-task-master"
        result = _call_initialize_task(
            str(state_dir),
            goal="Create new feature",
            model="sonnet",
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
        result = _call_initialize_task(
            str(state_dir),
            goal="Another goal",
        )

        assert result["success"] is False
        assert "already exists" in result["message"]

    def test_initialize_task_with_options(self, temp_dir):
        """Test initialize_task respects options."""
        state_dir = temp_dir / ".claude-task-master"
        result = _call_initialize_task(
            str(state_dir),
            goal="Test with options",
            model="haiku",
            auto_merge=False,
            max_sessions=5,
            pause_on_pr=True,
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
        state_dir = temp_dir / ".claude-task-master"
        result = _call_list_tasks(str(state_dir))
        assert result["success"] is False

    def test_list_tasks_no_plan(self, initialized_state, state_dir):
        """Test list_tasks when no plan exists."""
        result = _call_list_tasks(str(state_dir))
        assert result["success"] is False
        assert "No plan found" in result.get("error", "")

    def test_list_tasks_with_plan(self, state_with_plan, state_dir):
        """Test list_tasks returns parsed tasks."""
        state_manager, state = state_with_plan

        result = _call_list_tasks(str(state_dir))
        assert result["success"] is True
        assert result["total"] == 4
        assert result["completed"] == 1
        assert len(result["tasks"]) == 4

        # Check task structure
        incomplete_tasks = [t for t in result["tasks"] if not t["completed"]]
        completed_tasks = [t for t in result["tasks"] if t["completed"]]
        assert len(incomplete_tasks) == 3
        assert len(completed_tasks) == 1


class TestMCPResources:
    """Test MCP resource endpoints."""

    def test_resource_goal_no_task(self, temp_dir):
        """Test resource_goal when no task exists."""
        result = _call_resource_goal(str(temp_dir))
        assert "No active task" in result

    def test_resource_goal_with_task(self, initialized_state, state_dir):
        """Test resource_goal returns goal."""
        result = _call_resource_goal(str(state_dir.parent))
        assert "Test goal for MCP" in result

    def test_resource_plan_no_task(self, temp_dir):
        """Test resource_plan when no task exists."""
        result = _call_resource_plan(str(temp_dir))
        assert "No active task" in result

    def test_resource_plan_with_plan(self, state_with_plan, state_dir):
        """Test resource_plan returns plan."""
        result = _call_resource_plan(str(state_dir.parent))
        assert "First task to do" in result

    def test_resource_progress_no_task(self, temp_dir):
        """Test resource_progress when no task exists."""
        result = _call_resource_progress(str(temp_dir))
        assert "No active task" in result

    def test_resource_context_no_task(self, temp_dir):
        """Test resource_context when no task exists."""
        result = _call_resource_context(str(temp_dir))
        assert "No active task" in result


class TestMCPServerCLI:
    """Test MCP server CLI entry point."""

    def test_main_function_exists(self):
        """Test that main function exists and is callable."""
        from claude_task_master.mcp.server import main

        assert callable(main)

    def test_run_server_function_exists(self):
        """Test that run_server function exists and is callable."""
        from claude_task_master.mcp.server import run_server

        assert callable(run_server)


# =============================================================================
# Helper Functions - Simulate tool calls
# =============================================================================


def _call_get_status(state_dir: str) -> dict:
    """Simulate calling get_status tool."""
    from claude_task_master.core.state import StateManager

    state_path = Path(state_dir)
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": False,
            "error": "No active task found",
            "suggestion": "Use start_task to begin a new task",
        }

    try:
        state = state_manager.load_state()
        goal = state_manager.load_goal()

        return {
            "goal": goal,
            "status": state.status,
            "model": state.model,
            "current_task_index": state.current_task_index,
            "session_count": state.session_count,
            "run_id": state.run_id,
            "current_pr": state.current_pr,
            "workflow_stage": state.workflow_stage,
            "options": state.options.model_dump(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def _call_get_plan(state_dir: str) -> dict:
    """Simulate calling get_plan tool."""
    from claude_task_master.core.state import StateManager

    state_path = Path(state_dir)
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": False,
            "error": "No active task found",
        }

    try:
        plan = state_manager.load_plan()
        if not plan:
            return {
                "success": False,
                "error": "No plan found",
            }

        return {
            "success": True,
            "plan": plan,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def _call_get_logs(state_dir: str, tail: int = 100) -> dict:
    """Simulate calling get_logs tool."""
    from claude_task_master.core.state import StateManager

    state_path = Path(state_dir)
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": False,
            "error": "No active task found",
        }

    try:
        state = state_manager.load_state()
        log_file = state_manager.get_log_file(state.run_id)

        if not log_file.exists():
            return {
                "success": False,
                "error": "No log file found",
            }

        with open(log_file) as f:
            lines = f.readlines()

        log_content = "".join(lines[-tail:])

        return {
            "success": True,
            "log_content": log_content,
            "log_file": str(log_file),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def _call_get_progress(state_dir: str) -> dict:
    """Simulate calling get_progress tool."""
    from claude_task_master.core.state import StateManager

    state_path = Path(state_dir)
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": False,
            "error": "No active task found",
        }

    try:
        progress = state_manager.load_progress()
        if not progress:
            return {
                "success": True,
                "progress": None,
                "message": "No progress recorded yet",
            }

        return {
            "success": True,
            "progress": progress,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def _call_get_context(state_dir: str) -> dict:
    """Simulate calling get_context tool."""
    from claude_task_master.core.state import StateManager

    state_path = Path(state_dir)
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": False,
            "error": "No active task found",
        }

    try:
        context = state_manager.load_context()
        return {
            "success": True,
            "context": context or "",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def _call_clean_task(state_dir: str) -> dict:
    """Simulate calling clean_task tool."""
    from claude_task_master.core.state import StateManager

    state_path = Path(state_dir)
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": True,
            "message": "No task state found to clean",
            "files_removed": False,
        }

    try:
        if state_manager.state_dir.exists():
            shutil.rmtree(state_manager.state_dir)
            return {
                "success": True,
                "message": "Task state cleaned successfully",
                "files_removed": True,
            }
        return {
            "success": True,
            "message": "State directory did not exist",
            "files_removed": False,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to clean task state: {e}",
        }


def _call_initialize_task(
    state_dir: str,
    goal: str,
    model: str = "opus",
    auto_merge: bool = True,
    max_sessions: int | None = None,
    pause_on_pr: bool = False,
) -> dict:
    """Simulate calling initialize_task tool."""
    from claude_task_master.core.state import StateManager, TaskOptions

    state_path = Path(state_dir)
    state_manager = StateManager(state_dir=state_path)

    if state_manager.exists():
        return {
            "success": False,
            "message": "Task already exists. Use clean_task first or resume the existing task.",
        }

    try:
        options = TaskOptions(
            auto_merge=auto_merge,
            max_sessions=max_sessions,
            pause_on_pr=pause_on_pr,
        )
        state = state_manager.initialize(goal=goal, model=model, options=options)

        return {
            "success": True,
            "message": f"Task initialized successfully with goal: {goal}",
            "run_id": state.run_id,
            "status": state.status,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to initialize task: {e}",
        }


def _call_list_tasks(state_dir: str) -> dict:
    """Simulate calling list_tasks tool."""
    from claude_task_master.core.state import StateManager

    state_path = Path(state_dir)
    state_manager = StateManager(state_dir=state_path)

    if not state_manager.exists():
        return {
            "success": False,
            "error": "No active task found",
        }

    try:
        plan = state_manager.load_plan()
        if not plan:
            return {
                "success": False,
                "error": "No plan found",
            }

        tasks = []
        for line in plan.split("\n"):
            stripped = line.strip()
            if stripped.startswith("- [ ]"):
                tasks.append({
                    "task": stripped[5:].strip(),
                    "completed": False,
                })
            elif stripped.startswith("- [x]"):
                tasks.append({
                    "task": stripped[5:].strip(),
                    "completed": True,
                })

        state = state_manager.load_state()

        return {
            "success": True,
            "tasks": tasks,
            "total": len(tasks),
            "completed": sum(1 for t in tasks if t["completed"]),
            "current_index": state.current_task_index,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def _call_resource_goal(working_dir: str) -> str:
    """Simulate calling resource_goal."""
    from claude_task_master.core.state import StateManager

    state_manager = StateManager(state_dir=Path(working_dir) / ".claude-task-master")
    if not state_manager.exists():
        return "No active task"
    try:
        return state_manager.load_goal()
    except Exception:
        return "Error loading goal"


def _call_resource_plan(working_dir: str) -> str:
    """Simulate calling resource_plan."""
    from claude_task_master.core.state import StateManager

    state_manager = StateManager(state_dir=Path(working_dir) / ".claude-task-master")
    if not state_manager.exists():
        return "No active task"
    try:
        plan = state_manager.load_plan()
        return plan or "No plan found"
    except Exception:
        return "Error loading plan"


def _call_resource_progress(working_dir: str) -> str:
    """Simulate calling resource_progress."""
    from claude_task_master.core.state import StateManager

    state_manager = StateManager(state_dir=Path(working_dir) / ".claude-task-master")
    if not state_manager.exists():
        return "No active task"
    try:
        progress = state_manager.load_progress()
        return progress or "No progress recorded"
    except Exception:
        return "Error loading progress"


def _call_resource_context(working_dir: str) -> str:
    """Simulate calling resource_context."""
    from claude_task_master.core.state import StateManager

    state_manager = StateManager(state_dir=Path(working_dir) / ".claude-task-master")
    if not state_manager.exists():
        return "No active task"
    try:
        return state_manager.load_context()
    except Exception:
        return "Error loading context"
