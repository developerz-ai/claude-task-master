"""Tests for the unfinished-session guard in the working stage.

Regression: a work session that stopped mid-task — the SDK cutting it off, or
the agent ending its turn on a backgrounded check — still had its task checked
off ``[x]`` and the group advanced to ``pr_created``. With no PR and a dirty
tree, the run then blocked and needed a human to commit and open the PR by hand.

A session only counts as done when it satisfies its contract: a non-error
terminal result AND a clean working tree.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from claude_task_master.core.loop_working_stage import MAX_TASK_FINISH_ATTEMPTS
from claude_task_master.core.orchestrator import WorkLoopOrchestrator
from claude_task_master.core.orchestrator_loop import OrchestratorLoop
from claude_task_master.core.state import TaskOptions, TaskState

_MODULE = "claude_task_master.core.loop_working_stage"


@pytest.fixture
def mock_agent():
    from unittest.mock import MagicMock

    agent = MagicMock()
    agent.run_work_session = MagicMock(return_value={"output": "done", "success": True})
    agent.extract_session_learnings = MagicMock(return_value="")
    return agent


@pytest.fixture
def mock_planner():
    from unittest.mock import MagicMock

    return MagicMock()


@pytest.fixture
def basic_orchestrator(mock_agent, state_manager, mock_planner, mock_github_client):
    return WorkLoopOrchestrator(
        agent=mock_agent,
        state_manager=state_manager,
        planner=mock_planner,
        github_client=mock_github_client,
    )


@pytest.fixture
def basic_task_state(sample_task_options):
    now = datetime.now().isoformat()
    return TaskState(
        status="working",
        workflow_stage="working",
        current_task_index=0,
        session_count=1,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=TaskOptions(**sample_task_options),
    )


@pytest.fixture
def basic_plan():
    return "## Task List\n\n- [ ] Task 1: Set up structure\n- [ ] Task 2: Implement core\n"


@pytest.fixture
def working_env(state_manager, basic_plan):
    """Plan + goal on disk, console silenced, git probe reporting a clean tree."""
    state_manager.state_dir.mkdir(exist_ok=True)
    state_manager.save_plan(basic_plan)
    state_manager.save_goal("Test goal")
    with (
        patch(f"{_MODULE}.console"),
        patch("claude_task_master.core.task_runner_session.console"),
        patch("claude_task_master.core.task_runner.get_current_branch", return_value="feat/x"),
        patch("claude_task_master.core.orchestrator_loop.reset_escape"),
        patch(f"{_MODULE}._LoopWorkingStageMixin._session_unfinished_reason", return_value=None),
    ):
        yield


def _mark_unfinished(reason: str = "uncommitted changes left behind"):
    return patch(
        f"{_MODULE}._LoopWorkingStageMixin._session_unfinished_reason",
        return_value=reason,
    )


class TestUnfinishedSessionRetries:
    """A session that didn't finish must not check its task off."""

    def test_unfinished_session_retries_instead_of_completing(
        self, basic_orchestrator, basic_task_state, state_manager, working_env
    ):
        with _mark_unfinished():
            result = basic_orchestrator._handle_working_stage(basic_task_state)

        assert result is None
        assert basic_task_state.task_finish_attempts == 1
        # Same task, still in working — no advance, no PR stage.
        assert basic_task_state.current_task_index == 0
        assert basic_task_state.workflow_stage == "working"
        assert "- [ ]" in (state_manager.load_plan() or "")

    def test_session_count_still_advances_on_retry(
        self, basic_orchestrator, basic_task_state, working_env
    ):
        """Retries burn sessions, so --max-sessions still bounds the loop."""
        before = basic_task_state.session_count

        with _mark_unfinished():
            basic_orchestrator._handle_working_stage(basic_task_state)

        assert basic_task_state.session_count == before + 1

    def test_gives_up_after_max_attempts_and_completes(
        self, basic_orchestrator, basic_task_state, state_manager, working_env
    ):
        """Budget spent → check off and hand over to the PR stage, never deadlock."""
        basic_task_state.task_finish_attempts = MAX_TASK_FINISH_ATTEMPTS

        with _mark_unfinished():
            result = basic_orchestrator._handle_working_stage(basic_task_state)

        assert result is None
        assert basic_task_state.task_finish_attempts == 0
        assert "- [x]" in (state_manager.load_plan() or "")

    def test_finished_session_resets_the_counter(
        self, basic_orchestrator, basic_task_state, state_manager, working_env
    ):
        basic_task_state.task_finish_attempts = 1

        basic_orchestrator._handle_working_stage(basic_task_state)

        assert basic_task_state.task_finish_attempts == 0
        assert "- [x]" in (state_manager.load_plan() or "")


class TestSessionUnfinishedReason:
    """The detector itself: two independent signals, no false positives."""

    def test_sdk_error_result_is_unfinished(self, basic_orchestrator):
        assert (
            OrchestratorLoop(basic_orchestrator)._session_unfinished_reason("ran_incomplete")
            is not None
        )

    def test_dirty_tree_is_unfinished(self, basic_orchestrator):
        with patch(f"{_MODULE}.subprocess.run") as run:
            run.return_value.stdout = " M src/thing.py\n"
            assert (
                OrchestratorLoop(basic_orchestrator)._session_unfinished_reason("ran") is not None
            )

    def test_clean_tree_is_finished(self, basic_orchestrator):
        with patch(f"{_MODULE}.subprocess.run") as run:
            run.return_value.stdout = "\n"
            assert OrchestratorLoop(basic_orchestrator)._session_unfinished_reason("ran") is None

    def test_failed_git_probe_never_invents_unfinished_work(self, basic_orchestrator):
        """Not a repo / no git / timeout must not stall a healthy run."""
        with patch(f"{_MODULE}.subprocess.run", side_effect=OSError("no git")):
            assert OrchestratorLoop(basic_orchestrator)._session_unfinished_reason("ran") is None


_LIMIT_LINE = "You've hit your session limit · resets 1pm (America/Bogota)"


class TestUsageLimitRefusedSession:
    """An account-wide usage limit is never charged to the task.

    Regression: a limited account answered every session in seconds with only
    the limit notice; the loop burned both retry attempts per task in under a
    minute and then checked untouched tasks off ``[x]`` — silent work loss on
    resume. A refused session must consume no attempt and mark nothing.
    """

    def _refuse_with_limit(self, mock_agent):
        mock_agent.run_work_session.return_value = {
            "output": _LIMIT_LINE,
            "success": False,
            "subtype": "success",
        }

    def test_refused_session_consumes_no_attempt_and_stays_on_task(
        self, mock_agent, basic_orchestrator, basic_task_state, state_manager, working_env
    ):
        self._refuse_with_limit(mock_agent)

        result = basic_orchestrator._handle_working_stage(basic_task_state)

        assert result is None
        assert basic_task_state.task_finish_attempts == 0
        assert basic_task_state.current_task_index == 0
        assert basic_task_state.workflow_stage == "working"
        assert "- [x]" not in (state_manager.load_plan() or "")

    def test_refused_session_never_checked_off_even_with_budget_spent(
        self, mock_agent, basic_orchestrator, basic_task_state, state_manager, working_env
    ):
        """The exhausted-budget fallback ("check it off anyway, the PR stage
        ships what's on the branch") must not fire for a session that ran
        nothing — that is exactly how four tasks were lost in the live run."""
        basic_task_state.task_finish_attempts = MAX_TASK_FINISH_ATTEMPTS
        self._refuse_with_limit(mock_agent)

        result = basic_orchestrator._handle_working_stage(basic_task_state)

        assert result is None
        assert basic_task_state.task_finish_attempts == MAX_TASK_FINISH_ATTEMPTS
        assert basic_task_state.workflow_stage == "working"
        assert "- [x]" not in (state_manager.load_plan() or "")

    def test_ordinary_cutoff_still_burns_an_attempt(
        self, mock_agent, basic_orchestrator, basic_task_state, working_env
    ):
        """A genuine mid-task cutoff (no limit notice) keeps the old path."""
        mock_agent.run_work_session.return_value = {
            "output": "got halfway through the refactor",
            "success": False,
            "subtype": "error_max_turns",
        }

        with _mark_unfinished("session was cut off"):
            result = basic_orchestrator._handle_working_stage(basic_task_state)

        assert result is None
        assert basic_task_state.task_finish_attempts == 1


class TestContextAccumulationSkipsLimitNotice:
    def test_limit_notice_is_not_distilled_into_context(
        self, mock_agent, basic_orchestrator, basic_task_state
    ):
        basic_orchestrator.task_runner.last_session_output = _LIMIT_LINE

        with patch("claude_task_master.core.loop_context.console"):
            basic_orchestrator._accumulate_context(basic_task_state)

        mock_agent.extract_session_learnings.assert_not_called()
