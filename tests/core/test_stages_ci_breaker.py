"""Tests for the circuit breaker on CI that no diff can ever turn green.

Regression (issue #116), found dogfooding a 24/7 loop against a repo whose
GitHub account was locked for a billing issue. Every job concluded ``failure``
about two seconds after starting, recorded ``steps: []``, and carried the check
annotation *"The job was not started because your account is locked due to a
billing issue."*

What the loop did with that: each red poll spawned a fresh Opus session, which
correctly concluded the PR was fine and changed nothing; changing nothing meant
no push, so the next poll re-read the identical red run and spawned another.
The run ended at ``--max-sessions`` having burned subscription quota and left
nothing on the PR to say why.

Two things are asserted here:

* a failure GitHub has declared **permanent** costs zero agent sessions and
  zero re-runs — the budget would only be spent on the way to the same block;
* whenever claudetm stops on CI it cannot fix, it says so on the PR **once** —
  blocking silently is what made the original burn expensive to diagnose, and
  a comment per cycle would be the same defect wearing a hat.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

_PR_FIX = "claude_task_master.core.stages.pr_fix_stage"
_INFRA = "claude_task_master.github.ci_infra.CIInfraDetector"
_RERUN = "claude_task_master.github.ci_rerun.CIRerunner"
_NOTICE = "claude_task_master.github.ci_infra.post_external_block_notice"

BILLING_LOCK = "The job was not started because your account is locked due to a billing issue."


@pytest.fixture(autouse=True)
def _quiet() -> Generator[None, None, None]:
    with (
        patch("time.sleep"),
        patch(f"{_PR_FIX}.console"),
        patch("claude_task_master.core.stages.git_ops.console"),
        patch(f"{_PR_FIX}.interruptible_sleep", return_value=True),
        patch("claude_task_master.core.stages.git_ops.interruptible_sleep", return_value=True),
    ):
        yield


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.run_work_session = MagicMock(return_value={"output": "done", "success": True})
    return agent


@pytest.fixture
def mock_pr_context() -> MagicMock:
    ctx = MagicMock()
    ctx.save_ci_failures = MagicMock()
    ctx.get_combined_feedback = MagicMock(return_value=(True, False, "/tmp/pr"))
    ctx.failing_run_ids = MagicMock(return_value=[101, 202])
    return ctx


@pytest.fixture
def mock_github_client() -> MagicMock:
    client = MagicMock()
    client._get_repo_info = MagicMock(return_value="owner/repo")
    status = MagicMock()
    status.head_branch = "feat/x"
    client.get_pr_status = MagicMock(return_value=status)
    return client


@pytest.fixture
def handler(mock_agent, state_manager, mock_github_client, mock_pr_context):
    state_manager.state_dir.mkdir(exist_ok=True)
    return WorkflowStageHandler(
        agent=mock_agent,
        state_manager=state_manager,
        github_client=mock_github_client,
        pr_context=mock_pr_context,
    )


@pytest.fixture
def state(sample_task_options):
    now = datetime.now().isoformat()
    return TaskState(
        status="working",
        workflow_stage="ci_failed",
        current_task_index=0,
        session_count=1,
        current_pr=116,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=TaskOptions(**sample_task_options),
    )


def _infra(never_ran: bool, block_reason: str | None = None):
    """The detector's verdict on the PR's failing runs."""
    detector = MagicMock()
    detector.never_ran = MagicMock(return_value=never_ran)
    detector.external_block_reason = MagicMock(return_value=block_reason)
    return patch(_INFRA, return_value=detector)


def _rerun(accepted: bool = True):
    rerunner = MagicMock()
    rerunner.rerun_failed_jobs = MagicMock(return_value=accepted)
    return patch(_RERUN, return_value=rerunner), rerunner


def _notice(posted: bool = True):
    return patch(_NOTICE, return_value=posted)


class TestPermanentBlockCostsNothing:
    """The billing-lock repro: red in 2s, no steps, GitHub says why."""

    def test_no_agent_session_and_no_rerun(self, handler, state, mock_agent):
        rerun_patch, rerunner = _rerun()

        with _infra(True, BILLING_LOCK), rerun_patch, _notice() as notice:
            result = handler.handle_ci_failed_stage(state)

        assert result == 1
        assert state.status == "blocked"
        # Not one Opus session, and not one wasted re-run: GitHub already said
        # the jobs are refused, so both would only reach this same block.
        mock_agent.run_work_session.assert_not_called()
        rerunner.rerun_failed_jobs.assert_not_called()
        assert state.ci_rerun_attempts == 0
        assert state.ci_fix_attempts == 0
        notice.assert_called_once()

    def test_the_pr_is_told_why(self, handler, state):
        rerun_patch, _ = _rerun()

        with _infra(True, BILLING_LOCK), rerun_patch, _notice() as notice:
            handler.handle_ci_failed_stage(state)

        repo, pr_number, run_ids, summary = notice.call_args.args[:4]
        assert (repo, pr_number) == ("owner/repo", 116)
        assert run_ids == [101, 202]
        assert summary
        # GitHub's own sentence is the only thing that tells a human what to fix.
        assert notice.call_args.args[4] == BILLING_LOCK

    def test_the_loop_does_not_re_enter(self, handler, state, mock_agent):
        """Ten more cycles cost ten more blocks, never a session.

        The original defect was that "nothing to change" was not a terminal
        state, so the orchestrator came back for more. It is terminal now.
        """
        rerun_patch, rerunner = _rerun()

        with _infra(True, BILLING_LOCK), rerun_patch, _notice(posted=False):
            for _ in range(10):
                assert handler.handle_ci_failed_stage(state) == 1

        mock_agent.run_work_session.assert_not_called()
        rerunner.rerun_failed_jobs.assert_not_called()

    def test_a_failed_comment_does_not_derail_the_block(self, handler, state):
        """Blocking is the point; the comment is a courtesy."""
        rerun_patch, _ = _rerun()

        with _infra(True, BILLING_LOCK), rerun_patch, patch(_NOTICE, side_effect=Exception("500")):
            result = handler.handle_ci_failed_stage(state)

        assert result == 1
        assert state.status == "blocked"

    def test_a_pr_less_block_posts_nothing(self, handler, state):
        state.current_pr = None
        rerun_patch, _ = _rerun()

        with _infra(True, BILLING_LOCK), rerun_patch, _notice() as notice:
            handler.handle_ci_failed_stage(state)

        notice.assert_not_called()


class TestUnexplainedFailuresKeepTheirBudget:
    """Only a *declared* permanent refusal skips the re-run budget."""

    def test_a_queue_kill_is_still_re_run(self, handler, state):
        """No annotation means "nobody said this is permanent" — retry it."""
        rerun_patch, rerunner = _rerun()

        with _infra(True, None), rerun_patch, _notice() as notice:
            result = handler.handle_ci_failed_stage(state)

        assert result is None
        assert state.status != "blocked"
        assert rerunner.rerun_failed_jobs.call_count == 2
        assert state.ci_rerun_attempts == 1
        notice.assert_not_called()

    def test_a_run_that_executed_is_left_to_the_fix_agent(self, handler, state, mock_agent):
        with (
            _infra(False, BILLING_LOCK),
            _notice() as notice,
            patch.object(WorkflowStageHandler, "_fix_session_unfinished_reason", return_value=None),
            patch.object(WorkflowStageHandler, "_head_sha", side_effect=["before", "after"]),
        ):
            result = handler.handle_ci_failed_stage(state)

        # A job that recorded steps ran and failed on its merits; an annotation
        # elsewhere in the run must not talk claudetm out of reading the logs.
        assert result is None
        mock_agent.run_work_session.assert_called_once()
        notice.assert_not_called()


class TestTheRepeatCaseTripsTheBreaker:
    """Same red signature, same "nothing in the diff", budget after budget."""

    def test_spent_rerun_budget_explains_itself_on_the_pr(self, handler, state):
        state.ci_rerun_attempts = handler.MAX_CI_RERUN_ATTEMPTS
        rerun_patch, _ = _rerun()

        with _infra(True, None), rerun_patch, _notice() as notice:
            result = handler.handle_ci_failed_stage(state)

        assert result == 1
        assert state.status == "blocked"
        notice.assert_called_once()
        assert str(handler.MAX_CI_RERUN_ATTEMPTS) in notice.call_args.args[3]

    def test_a_refusal_to_re_run_explains_itself_too(self, handler, state):
        rerun_patch, _ = _rerun(accepted=False)

        with _infra(True, None), rerun_patch, _notice() as notice:
            result = handler.handle_ci_failed_stage(state)

        assert result == 1
        assert state.status == "blocked"
        notice.assert_called_once()

    def test_a_fix_session_that_changes_nothing_ends_at_one_comment(self, handler, state):
        """The full #116 shape when the jobs *did* run but nothing is fixable.

        Cycle 1 and 2 re-run the jobs (a session found nothing to commit, so
        without a re-run there would be no new run to wait for at all); cycle 3
        has no budget left and trips the breaker. Three sessions, one comment,
        one terminal block — not an open-ended burn.
        """
        rerun_patch, _ = _rerun()

        with (
            _infra(False, None),
            rerun_patch,
            _notice() as notice,
            patch.object(WorkflowStageHandler, "_fix_session_unfinished_reason", return_value=None),
            patch.object(WorkflowStageHandler, "_head_sha", return_value="unchanged"),
        ):
            assert handler.handle_ci_failed_stage(state) is None
            assert handler.handle_ci_failed_stage(state) is None
            assert handler.handle_ci_failed_stage(state) == 1

        assert state.status == "blocked"
        assert state.ci_rerun_attempts == handler.MAX_CI_RERUN_ATTEMPTS
        notice.assert_called_once()
