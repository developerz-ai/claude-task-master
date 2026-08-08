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


# =============================================================================
# Permanently blocked CI (issue #116)
# =============================================================================

_LOCK = "The job was not started because your account is locked due to a billing issue."


def _locked_job(job_id: int = 1) -> dict:
    """The billing-lock repro: red in ~2s, zero steps, refused by GitHub."""
    return {
        "id": job_id,
        "name": "Lint",
        "conclusion": "failure",
        "steps": [],
        "started_at": "2026-08-08T10:00:00Z",
        "completed_at": "2026-08-08T10:00:02Z",
        "check_run_url": f"https://api.github.com/repos/owner/repo/check-runs/{job_id}",
    }


def _calls(*results):
    """Patch subprocess.run with a sequence of results/exceptions."""
    return patch("subprocess.run", side_effect=list(results))


def _stdout(text: str) -> MagicMock:
    result = MagicMock()
    result.stdout = text
    return result


class TestExternalBlockReason:
    """Some never-ran failures clear on a re-run; some never will.

    A saturated pool is worth two re-runs. An account locked for billing is
    worth none — GitHub says so in the job's check annotation, and repeating
    the request only burns the budget on the way to the same block.
    """

    def test_billing_lock_is_recognised(self, detector):
        with _calls(_stdout(json.dumps(_locked_job())), _stdout(_LOCK)):
            assert detector.external_block_reason(1) == _LOCK

    def test_a_queue_kill_has_no_annotation(self, detector):
        """No annotation → not permanent → the ordinary re-run path."""
        with _calls(_stdout(json.dumps(_locked_job())), _stdout("")):
            assert detector.external_block_reason(1) is None

    def test_an_ordinary_annotation_is_not_a_block(self, detector):
        """Only phrases that mean "you may not run jobs" count."""
        with _calls(
            _stdout(json.dumps(_locked_job())),
            _stdout("tests/test_x.py:3:1: F401 imported but unused"),
        ):
            assert detector.external_block_reason(1) is None

    def test_a_job_that_ran_is_never_asked_about(self, detector):
        """A job with steps failed on its merits — no annotation lookup."""
        job = _locked_job()
        job["steps"] = [{"name": "pytest", "conclusion": "failure"}]
        with _calls(_stdout(json.dumps(job))) as run:
            assert detector.external_block_reason(1) is None
        assert run.call_count == 1

    def test_annotation_lookups_are_capped(self, detector):
        """A saturated pool strands dozens of jobs; they all say the same."""
        from claude_task_master.github.ci_infra import MAX_ANNOTATION_JOBS

        jobs = _stdout("\n".join(json.dumps(_locked_job(i)) for i in range(10)))
        with _calls(jobs, *[_stdout("")] * 10) as run:
            assert detector.external_block_reason(1) is None
        assert run.call_count == 1 + MAX_ANNOTATION_JOBS

    def test_unreadable_run_is_not_a_block(self, detector):
        """ "Could not tell" must never be reported as "give up"."""
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "gh")):
            assert detector.external_block_reason(1) is None

    def test_unreadable_annotations_are_not_a_block(self, detector):
        with _calls(
            _stdout(json.dumps(_locked_job())),
            subprocess.CalledProcessError(1, "gh"),
        ):
            assert detector.external_block_reason(1) is None


class TestBlockNotice:
    """The explanation is posted once, or not at all — never once per cycle."""

    def test_comment_explains_and_carries_its_marker(self):
        from claude_task_master.github.ci_infra import NOTICE_MARKER, format_external_block_comment

        body = format_external_block_comment([101, 202], "CI is still red after 2 re-runs.", _LOCK)

        assert body.startswith(NOTICE_MARKER)
        assert "`101`" in body and "`202`" in body
        assert _LOCK in body
        assert "resume -f" in body

    def test_posts_when_no_notice_exists(self):
        from claude_task_master.github.ci_infra import (
            NOTICE_MARKER,
            post_external_block_notice,
        )

        with _calls(_stdout("some unrelated review comment"), _stdout("")) as run:
            assert post_external_block_notice("owner/repo", 7, [101], "summary", _LOCK) is True

        posted = run.call_args_list[-1].args[0]
        assert posted[:3] == ["gh", "pr", "comment"]
        assert NOTICE_MARKER in posted[-1]

    def test_does_not_post_a_second_time(self):
        """The block is re-entered by every forced resume."""
        from claude_task_master.github.ci_infra import NOTICE_MARKER, post_external_block_notice

        with _calls(_stdout(f"{NOTICE_MARKER}\nCI is red for reasons...")) as run:
            assert post_external_block_notice("owner/repo", 7, [101], "summary") is False
        assert run.call_count == 1

    def test_unreadable_comment_list_does_not_post(self):
        """Silence beats a column of duplicates on a PR we cannot read."""
        with _calls(subprocess.CalledProcessError(1, "gh")) as run:
            from claude_task_master.github.ci_infra import post_external_block_notice

            assert post_external_block_notice("owner/repo", 7, [101], "summary") is False
        assert run.call_count == 1

    def test_a_failed_post_is_reported_not_raised(self):
        from claude_task_master.github.ci_infra import post_external_block_notice

        with _calls(_stdout(""), subprocess.CalledProcessError(1, "gh")):
            assert post_external_block_notice("owner/repo", 7, [101], "summary") is False
