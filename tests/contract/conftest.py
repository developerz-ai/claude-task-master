"""Shared fixtures for REST/MCP contract tests.

Both transports are wired to the same temporary state directory so every
contract test exercises an identical scenario against both surfaces.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import StateManager, TaskOptions

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

try:
    from fastapi.testclient import TestClient  # noqa: F401

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

try:
    import mcp.server.fastmcp as _mcp_fastmcp  # noqa: F401

    _MCP_AVAILABLE = _mcp_fastmcp is not None
except ImportError:
    _MCP_AVAILABLE = False

# Skip entire module when either transport is missing.
pytestmark = pytest.mark.skipif(
    not (_FASTAPI_AVAILABLE and _MCP_AVAILABLE),
    reason="FastAPI or MCP SDK not installed",
)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _make_state_manager(state_dir: Path) -> StateManager:
    return StateManager(state_dir=state_dir)


def _init_task(state_dir: Path, goal: str = "contract test goal") -> StateManager:
    """Initialize a task in *state_dir* and return the bound StateManager."""
    sm = _make_state_manager(state_dir)
    sm.initialize(goal=goal, model="sonnet", options=TaskOptions(auto_merge=True, max_sessions=5))
    return sm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def work_dir(tmp_path: Path) -> Path:
    """Root working directory shared between REST and MCP surfaces."""
    return tmp_path


@pytest.fixture()
def state_dir(work_dir: Path) -> Path:
    """State directory path (not yet created — caller controls initialization)."""
    return work_dir / ".claude-task-master"


@pytest.fixture()
def rest_client(work_dir: Path):
    """FastAPI TestClient pointed at *work_dir*.

    Credentials are mocked so tests don't need real OAuth tokens.
    """
    if not _FASTAPI_AVAILABLE:
        pytest.skip("FastAPI not installed")

    from fastapi.testclient import TestClient

    from claude_task_master.api.server import create_app

    app = create_app(working_dir=work_dir, cors_origins=["*"], include_docs=False)

    with patch("claude_task_master.api.routes.CredentialManager") as mock_cred_cls:
        mock_instance = MagicMock()
        mock_instance.get_valid_token.return_value = "mock-token"
        mock_cred_cls.return_value = mock_instance
        with TestClient(app) as client:
            yield client


# ---------------------------------------------------------------------------
# Convenient scenario helpers (used across test classes)
# ---------------------------------------------------------------------------


@pytest.fixture()
def initialized_work_dir(work_dir: Path) -> tuple[Path, StateManager]:
    """work_dir with a task already initialized; returns (work_dir, state_manager)."""
    sm = _init_task(work_dir / ".claude-task-master", goal="contract test goal")
    return work_dir, sm


@pytest.fixture()
def paused_work_dir(initialized_work_dir: tuple[Path, StateManager]) -> tuple[Path, StateManager]:
    """work_dir with a task paused; returns (work_dir, state_manager)."""
    work_dir, sm = initialized_work_dir
    state = sm.load_state()
    # planning → paused is valid
    sm.save_state(state, validate_transition=False)
    from claude_task_master.core.control import ControlManager

    ControlManager(state_manager=sm).pause()
    return work_dir, sm
