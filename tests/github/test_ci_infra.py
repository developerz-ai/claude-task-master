"""Tests for CIInfraDetector — telling a platform failure from a code one.

GitHub fills a job's ``steps`` as it runs, so a red job with an empty step list
never executed anything: it was killed in the queue or lost its runner. That is
the only signal used here, because it is the only one that cannot be produced
by a broken branch.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.github.ci_infra import CIInfraDetector


@pytest.fixture
def detector():
    return CIInfraDetector(repo="owner/repo", timeout=60)


def _jobs(*jobs: dict):
    """Patch the gh call with an NDJSON job list."""
    result = MagicMock()
    result.stdout = "\n".join(json.dumps(job) for job in jobs)
    return patch("subprocess.run", return_value=result)


def _job(conclusion: str, steps: list | None = None) -> dict:
    return {"id": 1, "name": "test", "conclusion": conclusion, "steps": steps or []}


class TestNeverRan:
    def test_queued_job_killed_before_starting(self, detector):
        """The #148 shape: cancelled while queued, zero steps recorded."""
        with _jobs(_job("cancelled"), _job("cancelled")):
            assert detector.never_ran(1) is True

    def test_runner_lost_before_the_first_step(self, detector):
        with _jobs(_job("failure")):
            assert detector.never_ran(1) is True

    def test_a_job_that_actually_failed(self, detector):
        with _jobs(_job("failure", steps=[{"name": "test", "conclusion": "failure"}])):
            assert detector.never_ran(1) is False

    def test_one_executed_job_is_enough(self, detector):
        """Mixed red stays the fix agent's business."""
        with _jobs(_job("cancelled"), _job("failure", steps=[{"name": "build"}])):
            assert detector.never_ran(1) is False

    def test_matrix_fail_fast_is_a_real_failure(self, detector):
        """fail-fast cancels the siblings of a job that genuinely broke.

        The cancelled siblings record no steps, but the sibling that *caused*
        the cancellation did — and that one is a defect the agent must see, so
        the run as a whole is not infrastructural.
        """
        with _jobs(
            _job("failure", steps=[{"name": "pytest", "conclusion": "failure"}]),
            _job("cancelled"),
            _job("cancelled"),
        ):
            assert detector.never_ran(1) is False

    def test_green_run_is_not_infrastructural(self, detector):
        with _jobs({"id": 1, "name": "test", "conclusion": "success", "steps": []}):
            assert detector.never_ran(1) is False

    def test_skipped_jobs_are_not_failures(self, detector):
        """A skipped job records no steps but is not red — it must not count."""
        with _jobs({"id": 1, "name": "gate", "conclusion": "skipped", "steps": []}):
            assert detector.never_ran(1) is False

    def test_running_job_without_a_conclusion(self, detector):
        with _jobs({"id": 1, "name": "test", "conclusion": None, "steps": []}):
            assert detector.never_ran(1) is False


class TestUnreadableRun:
    """An unreadable run must not be waved through as 'not the diff's fault'."""

    def test_api_failure(self, detector):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "gh")):
            assert detector.never_ran(1) is False

    def test_timeout(self, detector):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 60)):
            assert detector.never_ran(1) is False

    def test_malformed_json(self, detector):
        result = MagicMock()
        result.stdout = "not json"
        with patch("subprocess.run", return_value=result):
            assert detector.never_ran(1) is False
