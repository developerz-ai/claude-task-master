"""Tests for re-running CI instead of asking an agent to fix the unfixable.

Regression (venom-astrology PR #148). Four workflow runs went red because the
runner pool was saturated: seven of the eight red jobs were killed while still
queued, and the one that got a runner lost it before writing a step. Nothing in
the branch was at fault — the same commit passed the full gate locally.

claudetm handled it like a code failure and could not get out:

1. Log download picked ``max(run_ids)``, one run of the four, and that one had
   no logs to give. The fix agent was handed an empty ``ci/`` directory.
2. With no evidence of a defect the agent correctly changed nothing, reported
   success, and pushed nothing.
3. Pushing nothing starts no new run — so ``waiting_ci`` re-read the *same* red
   run as a fresh failure, spent another of the three CI-fix attempts, and came
   back. Four cycles later the task blocked, having produced no commit and
   nothing a human could act on.

So: read every failing run's logs, recognise a run whose jobs never executed a
step, and re-run the jobs rather than spending a session on them.
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


@pytest.fixture(autouse=True)
def _quiet() -> Generator[None, None, None]:
    with (
        patch("time.sleep"),
        patch(f"{_PR_FIX}.console"),
        patch("claude_task_master.core.stages.git_ops.console"),
        patch(f"{_PR_FIX}.interruptible_sleep", return_value=True),
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
        current_pr=148,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=TaskOptions(**sample_task_options),
    )


def _infra(never_ran: bool):
    """Every failing run's jobs either never executed a step, or did."""
    detector = MagicMock()
    detector.never_ran = MagicMock(return_value=never_ran)
    return patch(_INFRA, return_value=detector)


def _rerun(accepted: bool = True):
    rerunner = MagicMock()
    rerunner.rerun_failed_jobs = MagicMock(return_value=accepted)
    return patch(_RERUN, return_value=rerunner), rerunner


def _delivered():
    return patch.object(WorkflowStageHandler, "_fix_session_unfinished_reason", return_value=None)


def _committed(yes: bool):
    return patch.object(
        WorkflowStageHandler,
        "_head_sha",
        side_effect=["before", "after"] if yes else ["same", "same"],
    )


class TestInfrastructuralFailureIsRerun:
    """A red run whose jobs never started is the platform's, not the diff's."""

    def test_reruns_without_spending_an_agent_session(self, handler, state, mock_agent):
        rerun_patch, rerunner = _rerun()

        with _infra(True), rerun_patch:
            result = handler.handle_ci_failed_stage(state)

        assert result is None
        mock_agent.run_work_session.assert_not_called()
        assert rerunner.rerun_failed_jobs.call_count == 2
        assert state.workflow_stage == "waiting_ci"
        assert state.ci_rerun_attempts == 1
        # The CI-fix budget bounds "the fix didn't work" — no fix was attempted.
        assert state.ci_fix_attempts == 0

    def test_poll_timer_restarts_with_the_rerun(self, handler, state):
        state.ci_poll_start_time = datetime.now()
        rerun_patch, _ = _rerun()

        with _infra(True), rerun_patch:
            handler.handle_ci_failed_stage(state)

        # Carrying the old timer forward would time the fresh run out on the
        # wait that already elapsed.
        assert state.ci_poll_start_time is None

    def test_a_run_that_executed_goes_to_the_fix_agent(self, handler, state, mock_agent):
        """Mixed red — one workflow genuinely broken — is still a real failure."""
        rerun_patch, rerunner = _rerun()

        with _infra(False), rerun_patch, _delivered(), _committed(True):
            result = handler.handle_ci_failed_stage(state)

        assert result is None
        mock_agent.run_work_session.assert_called_once()
        rerunner.rerun_failed_jobs.assert_not_called()
        assert state.workflow_stage == "waiting_ci"
        assert state.ci_fix_attempts == 1

    def test_blocks_once_the_rerun_budget_is_spent(self, handler, state):
        state.ci_rerun_attempts = handler.MAX_CI_RERUN_ATTEMPTS
        rerun_patch, rerunner = _rerun()

        with _infra(True), rerun_patch:
            result = handler.handle_ci_failed_stage(state)

        assert result == 1
        assert state.status == "blocked"
        rerunner.rerun_failed_jobs.assert_not_called()

    def test_blocks_when_github_refuses_every_rerun(self, handler, state):
        rerun_patch, _ = _rerun(accepted=False)

        with _infra(True), rerun_patch:
            result = handler.handle_ci_failed_stage(state)

        assert result == 1
        assert state.status == "blocked"


class TestFixSessionWithoutACommit:
    """The loop that blocked #148: no commit means no new run to wait for."""

    def test_reruns_instead_of_polling_the_same_red_run(self, handler, state):
        rerun_patch, rerunner = _rerun()

        with _infra(False), rerun_patch, _delivered(), _committed(False):
            result = handler.handle_ci_failed_stage(state)

        assert result is None
        assert rerunner.rerun_failed_jobs.call_count == 2
        assert state.workflow_stage == "waiting_ci"
        assert state.ci_rerun_attempts == 1

    def test_does_not_consume_the_ci_fix_budget(self, handler, state):
        state.ci_fix_attempts = 0
        rerun_patch, _ = _rerun()

        with _infra(False), rerun_patch, _delivered(), _committed(False):
            handler.handle_ci_failed_stage(state)

        # Incremented on entry, refunded because no fix was produced. Without
        # the refund this reaches MAX_CI_FIX_ATTEMPTS in four cycles and blocks.
        assert state.ci_fix_attempts == 0

    def test_blocks_when_no_run_can_be_identified(self, handler, state, mock_pr_context):
        mock_pr_context.failing_run_ids = MagicMock(return_value=[])

        with _infra(False), _delivered(), _committed(False):
            result = handler.handle_ci_failed_stage(state)

        assert result == 1
        assert state.status == "blocked"


class TestBudgetEndsWithTheStreak:
    """The budget bounds consecutive red CI, not the PR's whole lifetime."""

    def test_green_ci_clears_the_rerun_counter(self, handler, state, mock_github_client):
        state.workflow_stage = "waiting_ci"
        state.ci_rerun_attempts = handler.MAX_CI_RERUN_ATTEMPTS
        status = mock_github_client.get_pr_status.return_value
        status.state = "OPEN"
        status.ci_state = "SUCCESS"
        status.checks_passed = 4
        status.checks_skipped = 0
        status.checks_failed = 0
        status.checks_pending = 0
        status.check_details = []
        status.mergeable = "MERGEABLE"

        with (
            patch("claude_task_master.core.stages.ci_stage.console"),
            patch("claude_task_master.core.stages.ci_stage.interruptible_sleep", return_value=True),
        ):
            handler.handle_waiting_ci_stage(state)

        # A flake hours later gets its own retries, not a spent budget.
        assert state.ci_rerun_attempts == 0


class TestBudgetsAreRefundedOnForceResume:
    """`resume --force` means a human intervened — every budget starts over."""

    def test_recovery_clears_the_rerun_counter(self, state):
        from claude_task_master.core.state_recovery import StateRecovery

        state.ci_rerun_attempts = 9
        recovery = StateRecovery(github_client=MagicMock())
        with patch.object(StateRecovery, "detect_real_state") as detect:
            detect.return_value = MagicMock(workflow_stage="ci_failed", current_pr=148)
            recovery.apply_recovery(state)

        assert state.ci_rerun_attempts == 0
