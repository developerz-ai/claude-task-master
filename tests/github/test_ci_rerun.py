"""Tests for CIRerunner."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.github.ci_rerun import CIRerunner
from claude_task_master.github.exceptions import GitHubTimeoutError


@pytest.fixture
def rerunner():
    return CIRerunner(repo="owner/repo", timeout=60)


class TestRerunFailedJobs:
    def test_reruns_only_the_failed_jobs(self, rerunner):
        """Re-running the passing jobs wastes the very runners that ran out."""
        with patch("subprocess.run", return_value=MagicMock()) as run:
            assert rerunner.rerun_failed_jobs(123) is True

        assert run.call_args[0][0] == [
            "gh",
            "run",
            "rerun",
            "123",
            "--failed",
            "--repo",
            "owner/repo",
        ]

    def test_refusal_is_reported_not_raised(self, rerunner):
        """A run past its retention window cannot re-run — the caller decides."""
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "gh")):
            assert rerunner.rerun_failed_jobs(123) is False

    def test_timeout_is_distinct_from_refusal(self, rerunner):
        """A timeout may already have restarted the run; a refusal never did.

        Collapsing the two would block a task whose CI is in fact re-running.
        """
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 60)):
            with pytest.raises(GitHubTimeoutError):
                rerunner.rerun_failed_jobs(123)
