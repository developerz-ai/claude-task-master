"""Shared fixtures for MCP server tests.

Provides common fixtures for testing MCP server tools and resources.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from claude_task_master.core.state import StateManager, TaskOptions

# Skip all MCP tests if MCP is not installed
try:
    from mcp.server.fastmcp import FastMCP

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    FastMCP = None  # type: ignore[assignment,misc]

# Apply skip marker to all tests in this package
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
