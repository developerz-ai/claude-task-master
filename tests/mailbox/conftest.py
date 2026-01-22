"""Shared fixtures for mailbox tests."""

import shutil
import tempfile
from pathlib import Path

import pytest


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
