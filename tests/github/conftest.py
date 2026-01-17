"""Pytest configuration and fixtures for GitHub client tests."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def github_client():
    """Provide a GitHubClient with mocked auth check."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        from claude_task_master.github.client import GitHubClient

        client = GitHubClient()
    return client
