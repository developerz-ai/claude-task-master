"""Tests for the review-stage poll timeout (issue #147).

``waiting_ci`` and ``waiting_reviews`` share one timer (``CI_POLL_TIMEOUT`` via
``state.ci_poll_start_time``) and used to take *opposite* actions when it
expired: the CI stage blocked (with ``--admin`` as the documented override),
while the review stage warned and fell through — in the same cycle — to the
unresolved-thread check, which sets ``ready_to_merge``.

The checks still pending at that point are precisely the late reporters (review
bots, anything that starts after CI), so the run proceeded toward merge as
though they had passed, with no ``--admin`` required and no distinction between
"the bot is slow" and "the bot is about to report a failure". Both stages now
route through one policy: block by default, ``--admin`` proceeds.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

_REVIEW = "claude_task_master.core.stages.review_stage"
_CI = "claude_task_master.core.stages.ci_stage"
_BASE = "claude_task_master.core.stages.base"


@pytest.fixture(autouse=True)
def _quiet() -> Generator[None, None, None]:
    with (
        patch("time.sleep"),
        patch(f"{_REVIEW}.console"),
        patch(f"{_CI}.console"),
        patch(f"{_BASE}.console"),
        patch(f"{_REVIEW}.interruptible_sleep", return_value=True),
        patch(f"{_CI}.interruptible_sleep", return_value=True),
    ):
        yield


@pytest.fixture
def mock_github_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def handler(state_manager, mock_github_client) -> WorkflowStageHandler:
    state_manager.state_dir.mkdir(exist_ok=True)
    return WorkflowStageHandler(
        agent=MagicMock(),
        state_manager=state_manager,
        github_client=mock_github_client,
        pr_context=MagicMock(),
    )


@pytest.fixture
def state(sample_task_options) -> TaskState:
    now = datetime.now().isoformat()
    options = TaskOptions(**sample_task_options)
    options.auto_merge = True
    return TaskState(
        status="working",
        workflow_stage="waiting_reviews",
        current_task_index=0,
        session_count=1,
        current_pr=42,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        # Timer started well beyond CI_POLL_TIMEOUT (7200s) ago.
        ci_poll_start_time=datetime.now() - timedelta(seconds=7300),
        options=options,
    )


#: A review bot that has not reported yet.
_PENDING_BOT = {"name": "coderabbit", "status": "IN_PROGRESS", "conclusion": None}
#: The same bot reporting its quota response — tolerated everywhere else.
_RATE_LIMITED_BOT = {
    "name": "CodeRabbit",
    "context": "CodeRabbit",
    "status": "PENDING",
    "conclusion": "PENDING",
    "description": "Review rate limited",
}


def _pr_status(check_details: list[dict]) -> MagicMock:
    status = MagicMock()
    status.number = 42
    status.state = "OPEN"
    status.ci_state = "SUCCESS"
    status.check_details = check_details
    status.unresolved_threads = 0
    status.resolved_threads = 0
    status.total_threads = 0
    status.review_decision = None
    return status


class TestTimedOutReviewChecksBlock:
    """A pending late reporter is not a passing one."""

    def test_blocks_instead_of_proceeding_to_merge(self, handler, state, mock_github_client):
        mock_github_client.get_pr_status.return_value = _pr_status([_PENDING_BOT])

        result = handler.handle_waiting_reviews_stage(state)

        assert result == 1
        assert state.status == "blocked"
        assert state.workflow_stage == "waiting_reviews"

    def test_timer_is_cleared_so_a_forced_resume_gets_a_fresh_window(
        self, handler, state, mock_github_client
    ):
        """An expired timer left in state re-blocks the instant the stage re-enters."""
        mock_github_client.get_pr_status.return_value = _pr_status([_PENDING_BOT])

        handler.handle_waiting_reviews_stage(state)

        assert state.ci_poll_start_time is None

    def test_admin_proceeds_as_the_ci_stage_does(self, handler, state, mock_github_client):
        state.options.admin_merge = True
        mock_github_client.get_pr_status.return_value = _pr_status([_PENDING_BOT])

        result = handler.handle_waiting_reviews_stage(state)

        assert result is None
        assert state.status != "blocked"
        assert state.workflow_stage == "ready_to_merge"
        assert state.ci_poll_start_time is None

    def test_not_yet_timed_out_still_waits(self, handler, state, mock_github_client):
        state.ci_poll_start_time = datetime.now()
        mock_github_client.get_pr_status.return_value = _pr_status([_PENDING_BOT])

        result = handler.handle_waiting_reviews_stage(state)

        assert result is None
        assert state.status != "blocked"
        assert state.workflow_stage == "waiting_reviews"


class TestToleratedChecksAreNotWaitedOn:
    """A failure we would discount must never be what blocks the run."""

    def test_rate_limited_review_bot_does_not_block(self, handler, state, mock_github_client):
        mock_github_client.get_pr_status.return_value = _pr_status([_RATE_LIMITED_BOT])

        result = handler.handle_waiting_reviews_stage(state)

        assert result is None
        assert state.status != "blocked"
        assert state.workflow_stage == "ready_to_merge"

    def test_a_real_pending_check_alongside_it_still_blocks(
        self, handler, state, mock_github_client
    ):
        mock_github_client.get_pr_status.return_value = _pr_status(
            [_RATE_LIMITED_BOT, _PENDING_BOT]
        )

        result = handler.handle_waiting_reviews_stage(state)

        assert result == 1
        assert state.status == "blocked"


class TestBothWaitsShareOnePolicy:
    """The two stages must not disagree by accident again."""

    def test_same_decision_for_both_stages(self, handler, state):
        for admin in (False, True):
            state.options.admin_merge = admin

            state.status = "working"
            state.ci_poll_start_time = datetime.now() - timedelta(seconds=7300)
            ci_result = handler._ci_timeout_action(state, "CI polling timed out")
            ci_blocked = (ci_result, state.status == "blocked")

            state.status = "working"
            state.ci_poll_start_time = datetime.now() - timedelta(seconds=7300)
            review_result = handler._review_checks_timeout_action(state, ["coderabbit"])
            review_blocked = (review_result, state.status == "blocked")

            assert ci_blocked == review_blocked == ((1, True) if not admin else (None, False))

    def test_review_timeout_reason_names_the_pending_checks(self, handler, state):
        # The block itself is emitted by the shared policy helper on the stage
        # base class — that sharing is the point of the fix.
        with patch(f"{_BASE}.console") as mock_console:
            handler._review_checks_timeout_action(state, ["coderabbit", "sonar"])

        message = mock_console.error.call_args[0][0]
        assert "coderabbit" in message
        assert "sonar" in message
        assert "blocking" in message
