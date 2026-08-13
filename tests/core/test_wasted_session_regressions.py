"""Regressions for paths that silently re-ran or multiplied an agent session.

A wasted session is the most expensive defect this system has — each one is a
full agent run, and under hive fan-out, N of them. These pin the cases where the
orchestrator spent sessions it did not need to.
"""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.agent_exceptions import ConsecutiveFailuresError
from claude_task_master.core.agent_models import ModelType
from claude_task_master.core.agent_query import AgentQueryExecutor, _env_positive_float
from claude_task_master.core.circuit_breaker import CircuitBreaker
from claude_task_master.core.rate_limit import RateLimitConfig
from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.task_runner import TaskRunner


def _state(**options: object) -> TaskState:
    now = datetime.now().isoformat()
    return TaskState(
        status="working",
        current_task_index=0,
        session_count=0,
        created_at=now,
        updated_at=now,
        run_id="test-run",
        model="sonnet",
        options=TaskOptions(**options),  # type: ignore[arg-type]
    )


class TestFanOutIsNotOfferedWhenItCannotPay:
    """Regression: every non-fix work session got the brief, retries included."""

    @pytest.fixture
    def runner(self, state_manager) -> TaskRunner:
        agent = MagicMock()
        agent.run_work_session = MagicMock(return_value={"output": "done", "success": True})
        return TaskRunner(agent=agent, state_manager=state_manager, logger=None)

    def _run(self, runner: TaskRunner, plan: str, state: TaskState, dirty: bool) -> dict:
        runner.state_manager.save_plan(plan)
        runner.state_manager.save_goal("Ship the thing")
        with (
            patch.object(
                TaskRunner, "_leftover_changes", return_value="M src/x.py" if dirty else None
            ),
            patch("claude_task_master.core.task_runner.get_current_branch", return_value="feat/x"),
        ):
            runner.run_work_session(state)
        kwargs: dict = runner.agent.run_work_session.call_args.kwargs  # type: ignore[attr-defined]
        return kwargs

    def test_a_normal_task_may_fan_out(self, runner: TaskRunner) -> None:
        kwargs = self._run(
            runner, "- [ ] Build the whole auth subsystem [coding]", _state(parallel=True), False
        )
        assert kwargs["parallel"] is True

    def test_a_resumed_task_runs_solo(self, runner: TaskRunner) -> None:
        """A dirty tree means a previous attempt's work is half-written.

        Fanning out over it is the worst case: the lead cannot hand a worker an
        exclusive file set it can vouch for, and a fan-out that already failed
        once re-runs at N agents' cost on the retry it caused.
        """
        kwargs = self._run(
            runner, "- [ ] Build the whole auth subsystem [coding]", _state(parallel=True), True
        )
        assert kwargs["parallel"] is False
        assert kwargs["project_agents"] is None
        assert kwargs["machine"] == ""

    def test_a_quick_task_runs_solo(self, runner: TaskRunner) -> None:
        """The planner already judged it small and routed it to Haiku."""
        kwargs = self._run(
            runner, "- [ ] Bump the version string [quick]", _state(parallel=True), False
        )
        assert kwargs["parallel"] is False

    def test_no_parallel_is_honoured(self, runner: TaskRunner) -> None:
        kwargs = self._run(
            runner, "- [ ] Build the whole auth subsystem [coding]", _state(parallel=False), False
        )
        assert kwargs["parallel"] is False


class TestConsecutiveFailuresActuallyTrip:
    """Regression: a failing query could retry forever.

    The failure counter decayed on a ~60s window measured from the *first*
    failure, sized from the retry backoff rather than from how long a query
    takes. Any session that ran longer than a minute before failing reset the
    counter on every failure, so the threshold was never reached and
    ``_run_query_with_retry``'s ``while True`` was unbounded — an unattended run
    could re-run a twenty-minute Opus session forever, and with fan-out on, at N
    workers a time.
    """

    @pytest.fixture
    def executor(self) -> AgentQueryExecutor:
        return AgentQueryExecutor(
            query_func=MagicMock(),
            options_class=MagicMock(),
            working_dir=".",
            model=ModelType.SONNET,
            rate_limit_config=RateLimitConfig(max_retries=3),
            circuit_breaker=CircuitBreaker("test"),
        )

    def test_slow_failures_still_reach_the_threshold(self, executor: AgentQueryExecutor) -> None:
        error = RuntimeError("boom")
        # Failures spread far wider than any window, with no success between —
        # exactly the shape of a repeatedly-failing long work session.
        now = time.time()
        with patch("claude_task_master.core.agent_query.time.time") as clock:
            for i in range(3):
                clock.return_value = now + i * 1800
                executor._record_failure(error)
            clock.return_value = now + 3 * 1800
            with pytest.raises(ConsecutiveFailuresError):
                executor._record_failure(error)

    def test_a_success_still_clears_the_streak(self, executor: AgentQueryExecutor) -> None:
        error = RuntimeError("boom")
        for _ in range(3):
            executor._record_failure(error)
        executor._reset_failures()
        # Back to zero: the next three failures must not trip immediately.
        for _ in range(3):
            executor._record_failure(error)
        with pytest.raises(ConsecutiveFailuresError):
            executor._record_failure(error)


class TestEnvVarsNeverCrashTheCli:
    """Regression: a typo in a timeout env var raised at import time.

    ``float(os.environ.get(...))`` on a module-level constant made
    ``CLAUDETM_STREAM_IDLE_TIMEOUT_SEC=30s`` take down every claudetm command,
    ``status`` and ``doctor`` included, with a traceback.
    """

    @pytest.mark.parametrize("raw", ["30s", "", "   ", "abc", "-5", "0"])
    def test_garbage_falls_back(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        monkeypatch.setenv("CLAUDETM_TEST_TIMEOUT", raw)
        assert _env_positive_float("CLAUDETM_TEST_TIMEOUT", 1800.0) == 1800.0

    def test_a_real_value_is_honoured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDETM_TEST_TIMEOUT", "42.5")
        assert _env_positive_float("CLAUDETM_TEST_TIMEOUT", 1800.0) == 42.5


class TestRetryCounterDoesNotLeakToTheNextTask:
    """Regression: task_finish_attempts survived the no-session early returns.

    Left set, it made the *next* task's prompt open with "**Retry 1** — the
    previous session on this task stopped before committing" about a session
    that never ran, and started that task with half its retry budget spent.
    """

    def test_skipped_task_clears_the_counter(self) -> None:
        from claude_task_master.core.loop_working_stage import _LoopWorkingStageMixin

        state = _state()
        state.task_finish_attempts = 2

        mixin = _LoopWorkingStageMixin()
        orc = MagicMock()
        orc.task_runner.run_work_session.return_value = "skipped_already_complete"
        orc.agent._message_processor = None
        mixin._orc = orc
        with (
            patch.object(mixin, "_get_total_tasks", return_value=3, create=True),
            patch.object(mixin, "_get_current_branch", return_value="feat/x", create=True),
            patch.object(mixin, "_ship_group_if_skipped_task_closed_it"),
        ):
            mixin._handle_working_stage(state)

        assert state.task_finish_attempts == 0
