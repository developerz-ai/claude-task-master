"""Shared fixtures for CLI-command tests.

The ``fix-pr``/``merge-pr`` command operates on the process's current working
directory — correct in production (it is run from the project) but it means the
guards that read git see *this repository* during tests, so a developer with
uncommitted work would get different results than CI. Neutralize that ambient
state by default; tests that exercise the guards patch these explicitly.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clean_worktree_by_default() -> Generator[None, None, None]:
    """Report a clean, fully-pushed worktree unless a test says otherwise."""
    with (
        patch(
            "claude_task_master.cli_commands.fix_pr.pending_changes_summary",
            return_value="",
        ),
        patch(
            "claude_task_master.cli_commands.fix_session.fix_session_undelivered_reason",
            return_value=None,
        ),
    ):
        yield
