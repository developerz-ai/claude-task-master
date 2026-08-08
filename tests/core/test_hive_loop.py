"""Tests for hive mode's effect on the work loop.

Covers the two halves of the loop that change when ``TaskOptions.parallel_tasks``
is on:

- :mod:`~claude_task_master.core.task_runner_session` — the batch that gets
  handed to one "hive lead" session, and the create-PR decision that has to be
  taken from the batch's LAST task instead of its first.
- :mod:`~claude_task_master.core.loop_working_hive` — how many tasks the
  orchestrator checks off afterwards, read from the lead's manifest.

Everything here must be a no-op when the flag is off; the disabled path is
pinned explicitly rather than assumed.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.agent_models import ModelType, TaskComplexity
from claude_task_master.core.hive import HiveBatch
from claude_task_master.core.orchestrator import WorkLoopOrchestrator
from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.task_group import parse_tasks_with_groups
from claude_task_master.core.task_runner import TaskRunner
from claude_task_master.core.task_runner_hive import (
    build_hive_task_description,
    hive_batch_complexity,
)

_LOOP = "claude_task_master.core.loop_working_stage"
_HIVE_LOOP = "claude_task_master.core.loop_working_hive"

# One group of three tasks, so a batch starting at task 1 ends on the task that
# closes the group — the case where the create-PR decision matters.
ONE_GROUP_PLAN = """## Task List

### PR 1: Core Implementation

- [ ] `[quick]` Fix a typo
- [ ] `[general]` Add tests
- [ ] `[coding]` Implement the feature
"""

TWO_GROUP_PLAN = """## Task List

### PR 1: Core Implementation

- [ ] `[coding]` Implement the feature
- [ ] `[general]` Add tests

### PR 2: Docs

- [ ] `[quick]` Update the README
"""


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.run_work_session = MagicMock(return_value={"output": "done", "success": True})
    agent.extract_session_learnings = MagicMock(return_value="")
    return agent


@pytest.fixture
def task_runner(mock_agent, state_manager):
    return TaskRunner(agent=mock_agent, state_manager=state_manager, logger=None)


def _state(sample_task_options, **overrides) -> TaskState:
    now = datetime.now().isoformat()
    options = TaskOptions(**sample_task_options)
    for key, value in overrides.pop("options", {}).items():
        setattr(options, key, value)
    return TaskState(
        status="working",
        workflow_stage="working",
        current_task_index=0,
        session_count=1,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=options,
        **overrides,
    )


@pytest.fixture
def hive_state(sample_task_options):
    return _state(sample_task_options, options={"parallel_tasks": True})


@pytest.fixture
def plain_state(sample_task_options):
    return _state(sample_task_options)


@pytest.fixture
def session_env(state_manager):
    """Console silenced and the branch probe pinned to a feature branch."""
    with (
        patch("claude_task_master.core.task_runner_session.console"),
        patch("claude_task_master.core.task_runner.get_current_branch", return_value="feat/x"),
    ):
        yield


def _write_plan(state_manager, plan: str, goal: str = "Ship the thing") -> None:
    state_manager.state_dir.mkdir(exist_ok=True)
    state_manager.save_plan(plan)
    state_manager.save_goal(goal)


# =============================================================================
# run_work_session — batching
# =============================================================================


class TestHiveBatchSession:
    """The lead session: what it is told, and which model runs it."""

    def test_batch_closing_the_group_still_creates_the_pr(
        self, task_runner, state_manager, mock_agent, hive_state, session_env
    ):
        """THE regression: create_pr must come from the batch's LAST task.

        ``is_last_in_group`` is computed for ``current_task_index`` — the FIRST
        task of the batch — so it is False for any batch of two or more. Leaving
        it there gives the lead a commit-only prompt, and the group's PR is never
        opened: tasks complete, commits stack on an unpushed local branch, and
        the run silently ships nothing.
        """
        _write_plan(state_manager, ONE_GROUP_PLAN)

        task_runner.run_work_session(hive_state)

        kwargs = mock_agent.run_work_session.call_args.kwargs
        assert kwargs["create_pr"] is True
        assert kwargs["hive_task_numbers"] == [1, 2, 3]

    def test_batch_not_closing_the_group_does_not_create_a_pr(
        self, task_runner, state_manager, mock_agent, hive_state, session_env
    ):
        """A batch that stops short of the group's end stays commit-only.

        Guards the obvious over-correction: "always create the PR for a batch".
        The batch takes every OPEN task of the group, so the only way it ends
        before the group does is a task after it that is already checked off.
        """
        plan = ONE_GROUP_PLAN.replace(
            "- [ ] `[coding]` Implement the feature",
            "- [x] `[coding]` Implement the feature",
        )
        _write_plan(state_manager, plan)

        task_runner.run_work_session(hive_state)

        kwargs = mock_agent.run_work_session.call_args.kwargs
        assert kwargs["hive_task_numbers"] == [1, 2]
        # Task 3 is complete but still the last task OF THE GROUP, so the batch
        # ending at task 2 must not open the PR.
        assert kwargs["create_pr"] is False

    def test_batch_stops_at_the_group_boundary(
        self, task_runner, state_manager, mock_agent, hive_state, session_env
    ):
        """A batch never reaches into the next PR group."""
        _write_plan(state_manager, TWO_GROUP_PLAN)

        task_runner.run_work_session(hive_state)

        kwargs = mock_agent.run_work_session.call_args.kwargs
        assert kwargs["hive_task_numbers"] == [1, 2]
        assert kwargs["create_pr"] is True

    def test_lead_routes_on_the_hardest_task_in_the_batch(
        self, task_runner, state_manager, mock_agent, hive_state, session_env
    ):
        """First task is `[quick]`, batch contains `[coding]` → Opus, not Haiku."""
        _write_plan(state_manager, ONE_GROUP_PLAN)

        task_runner.run_work_session(hive_state)

        kwargs = mock_agent.run_work_session.call_args.kwargs
        assert kwargs["model_override"] == ModelType.OPUS

    def test_batch_is_exposed_to_the_caller(
        self, task_runner, state_manager, hive_state, session_env
    ):
        _write_plan(state_manager, ONE_GROUP_PLAN)

        task_runner.run_work_session(hive_state)

        assert task_runner.last_hive_batch is not None
        assert task_runner.last_hive_batch.numbers == (1, 2, 3)

    def test_a_stale_batch_never_leaks_into_the_next_session(
        self, task_runner, state_manager, plain_state, session_env
    ):
        """Set on every call, including the ones that return early."""
        _write_plan(state_manager, ONE_GROUP_PLAN)
        task_runner.last_hive_batch = HiveBatch(
            indices=(0, 1), descriptions=("a", "b"), group_name="stale"
        )

        task_runner.run_work_session(plain_state)

        assert task_runner.last_hive_batch is None

    def test_retry_recomputes_the_batch_from_the_current_plan(
        self, task_runner, state_manager, mock_agent, hive_state, session_env
    ):
        """A task the cut-off session did check off drops out of the retry."""
        plan = ONE_GROUP_PLAN.replace("- [ ] `[quick]` Fix a typo", "- [x] `[quick]` Fix a typo")
        _write_plan(state_manager, plan)
        hive_state.current_task_index = 1
        hive_state.task_finish_attempts = 1

        task_runner.run_work_session(hive_state)

        kwargs = mock_agent.run_work_session.call_args.kwargs
        assert kwargs["hive_task_numbers"] == [2, 3]
        assert "Retry 1" in kwargs["task_description"]


class TestHiveDisabled:
    """The flag is off (the default): nothing about the session changes."""

    def test_single_task_path_is_unchanged(
        self, task_runner, state_manager, mock_agent, plain_state, session_env
    ):
        _write_plan(state_manager, ONE_GROUP_PLAN)

        task_runner.run_work_session(plain_state)

        kwargs = mock_agent.run_work_session.call_args.kwargs
        assert kwargs["hive_tasks"] is None
        assert kwargs["hive_task_numbers"] is None
        assert kwargs["create_pr"] is False  # task 1 of 3 — commit only
        assert kwargs["model_override"] == ModelType.HAIKU  # first task's own `[quick]`
        assert task_runner.last_hive_batch is None
        assert "Current Task (#1)" in kwargs["task_description"]

    def test_pr_per_task_is_untouched_by_hive_mode(
        self, task_runner, state_manager, mock_agent, hive_state, session_env
    ):
        """pr_per_task wins: one task, one PR, no batching."""
        _write_plan(state_manager, ONE_GROUP_PLAN)
        hive_state.options.pr_per_task = True

        task_runner.run_work_session(hive_state)

        kwargs = mock_agent.run_work_session.call_args.kwargs
        assert kwargs["hive_tasks"] is None
        assert kwargs["create_pr"] is True
        assert task_runner.last_hive_batch is None

    def test_single_remaining_task_falls_back_to_the_normal_path(
        self, task_runner, state_manager, mock_agent, hive_state, session_env
    ):
        """Below HIVE_MIN_BATCH_TASKS a hive session costs more than it saves."""
        _write_plan(state_manager, TWO_GROUP_PLAN)
        hive_state.current_task_index = 2  # lone task of PR 2

        task_runner.run_work_session(hive_state)

        kwargs = mock_agent.run_work_session.call_args.kwargs
        assert kwargs["hive_tasks"] is None
        assert kwargs["create_pr"] is True
        assert task_runner.last_hive_batch is None


# =============================================================================
# task_runner_hive — pure helpers
# =============================================================================


class TestHiveHelpers:
    def test_complexity_is_the_maximum_over_the_batch(self):
        parsed, _ = parse_tasks_with_groups(ONE_GROUP_PLAN)
        batch = HiveBatch(indices=(0, 1, 2), descriptions=("a", "b", "c"), group_name="PR 1")

        assert hive_batch_complexity(parsed, batch) is TaskComplexity.CODING

    def test_complexity_defaults_to_coding_when_indices_are_unresolvable(self):
        batch = HiveBatch(indices=(99,), descriptions=("x",), group_name="PR 1")

        assert hive_batch_complexity([], batch) is TaskComplexity.CODING

    def test_description_uses_plan_numbers_and_carries_the_retry_note(self):
        parsed, _ = parse_tasks_with_groups(ONE_GROUP_PLAN)
        batch = HiveBatch(
            indices=(1, 2),
            descriptions=("Add tests", "Implement the feature"),
            group_name="Core Implementation",
        )

        text = build_hive_task_description("Ship it", batch, parsed, "\n**Retry 1** — finish it\n")

        assert "Goal: Ship it" in text
        assert "Task #2: Add tests" in text
        assert "Task #3: Implement the feature" in text
        assert "Retry 1" in text


class TestMarkTasksComplete:
    """Marking a batch must not lose marks the way a loop of single marks does."""

    def test_all_indices_survive_one_write(self, task_runner, state_manager):
        _write_plan(state_manager, ONE_GROUP_PLAN)

        task_runner.mark_tasks_complete(ONE_GROUP_PLAN, [0, 2])

        plan = state_manager.load_plan() or ""
        assert task_runner.is_task_complete(plan, 0)
        assert not task_runner.is_task_complete(plan, 1)
        assert task_runner.is_task_complete(plan, 2)

    def test_looping_single_marks_would_lose_all_but_the_last(self, task_runner, state_manager):
        """Pins WHY mark_tasks_complete exists (documents the bug it replaces)."""
        _write_plan(state_manager, ONE_GROUP_PLAN)

        task_runner.mark_task_complete(ONE_GROUP_PLAN, 0)
        task_runner.mark_task_complete(ONE_GROUP_PLAN, 2)

        plan = state_manager.load_plan() or ""
        assert not task_runner.is_task_complete(plan, 0)  # silently overwritten
        assert task_runner.is_task_complete(plan, 2)


# =============================================================================
# The orchestrator's check-off
# =============================================================================


@pytest.fixture
def orchestrator(mock_agent, state_manager, mock_github_client):
    return WorkLoopOrchestrator(
        agent=mock_agent,
        state_manager=state_manager,
        planner=MagicMock(),
        github_client=mock_github_client,
    )


@pytest.fixture
def loop_env(state_manager):
    """Plan on disk, console silenced, clean tree, feature branch."""
    _write_plan(state_manager, ONE_GROUP_PLAN)
    with (
        patch(f"{_LOOP}.console"),
        patch(f"{_HIVE_LOOP}.console"),
        patch("claude_task_master.core.task_runner_session.console"),
        patch("claude_task_master.core.task_runner.get_current_branch", return_value="feat/x"),
        patch("claude_task_master.core.orchestrator_loop.reset_escape"),
        patch(f"{_LOOP}._LoopWorkingStageMixin._session_unfinished_reason", return_value=None),
    ):
        yield


def _run_hive_stage(orchestrator, state, output: str) -> None:
    """Run the working stage with a lead session that produced ``output``."""
    orchestrator.agent.run_work_session.return_value = {"output": output, "success": True}
    orchestrator._handle_working_stage(state)


class TestHiveCheckOff:
    def test_full_manifest_checks_off_the_whole_batch_and_ships(
        self, orchestrator, hive_state, state_manager, loop_env
    ):
        _run_hive_stage(orchestrator, hive_state, "all done\n\nTASKS COMPLETE: 1, 2, 3")

        plan = state_manager.load_plan() or ""
        assert plan.count("- [x]") == 3
        # Highest completed task closes the group → PR stage.
        assert hive_state.current_task_index == 2
        assert hive_state.workflow_stage == "pr_created"

    def test_partial_manifest_makes_progress_without_shipping(
        self, orchestrator, hive_state, state_manager, loop_env
    ):
        """Some tasks done → those are checked off, the rest re-enter working."""
        _run_hive_stage(orchestrator, hive_state, "TASKS COMPLETE: 1, 2")

        plan = state_manager.load_plan() or ""
        assert plan.count("- [x]") == 2
        assert hive_state.current_task_index == 2  # the one still open
        assert hive_state.workflow_stage == "working"

    def test_a_skipped_task_is_not_stranded_by_the_highest_completed_one(
        self, orchestrator, hive_state, state_manager, loop_env
    ):
        """The lead did 1 and 3 but skipped 2.

        Resuming at ``max(done) + 1`` would step over task 2 and leave it
        unfinished forever while the group shipped.
        """
        _run_hive_stage(orchestrator, hive_state, "TASKS COMPLETE: 1, 3")

        assert hive_state.current_task_index == 1  # task #2, still open
        assert hive_state.workflow_stage == "working"

    def test_missing_manifest_falls_back_to_single_task_behaviour(
        self, orchestrator, hive_state, state_manager, loop_env
    ):
        """A lead that forgot the line must neither mass-check-off nor stall."""
        _run_hive_stage(orchestrator, hive_state, "I finished everything, trust me.")

        plan = state_manager.load_plan() or ""
        assert plan.count("- [x]") == 1
        assert hive_state.current_task_index == 1
        assert hive_state.workflow_stage == "working"

    def test_empty_manifest_checks_off_nothing_and_holds_position(
        self, orchestrator, hive_state, state_manager, loop_env
    ):
        """A lead saying it finished none of them must not check off the first."""
        _run_hive_stage(orchestrator, hive_state, "blocked everywhere\n\nTASKS COMPLETE: none")

        plan = state_manager.load_plan() or ""
        assert "- [x]" not in plan
        assert hive_state.current_task_index == 0
        assert hive_state.workflow_stage == "working"

    def test_unsubstituted_placeholder_reads_as_an_empty_manifest(
        self, orchestrator, hive_state, state_manager, loop_env
    ):
        _run_hive_stage(
            orchestrator,
            hive_state,
            "TASKS COMPLETE: <comma-separated plan task numbers>",
        )

        assert "- [x]" not in (state_manager.load_plan() or "")
        assert hive_state.current_task_index == 0

    def test_numbers_outside_the_batch_are_ignored(
        self, orchestrator, hive_state, state_manager, loop_env
    ):
        """A hallucinated number must never check off a task the batch never covered."""
        _run_hive_stage(orchestrator, hive_state, "TASKS COMPLETE: 1, 9")

        plan = state_manager.load_plan() or ""
        assert plan.count("- [x]") == 1
        assert hive_state.current_task_index == 1

    def test_cut_off_session_ignores_the_manifest_entirely(
        self, orchestrator, hive_state, state_manager
    ):
        """Retry budget spent + dirty tree → the repository probe wins, not the report."""
        _write_plan(state_manager, ONE_GROUP_PLAN)
        hive_state.task_finish_attempts = 2  # MAX_TASK_FINISH_ATTEMPTS
        with (
            patch(f"{_LOOP}.console"),
            patch(f"{_HIVE_LOOP}.console"),
            patch("claude_task_master.core.task_runner_session.console"),
            patch("claude_task_master.core.task_runner.get_current_branch", return_value="feat/x"),
            patch("claude_task_master.core.orchestrator_loop.reset_escape"),
            patch(
                f"{_LOOP}._LoopWorkingStageMixin._session_unfinished_reason",
                return_value="uncommitted changes left behind",
            ),
        ):
            _run_hive_stage(orchestrator, hive_state, "TASKS COMPLETE: 1, 2, 3")

        plan = state_manager.load_plan() or ""
        assert plan.count("- [x]") == 1
        assert hive_state.current_task_index == 1
        assert hive_state.workflow_stage == "working"

    def test_disabled_hive_checks_off_exactly_one_task(
        self, orchestrator, plain_state, state_manager, loop_env
    ):
        """A `TASKS COMPLETE:` line in a plain session changes nothing."""
        _run_hive_stage(orchestrator, plain_state, "TASKS COMPLETE: 1, 2, 3")

        plan = state_manager.load_plan() or ""
        assert plan.count("- [x]") == 1
        assert plain_state.current_task_index == 1
        assert plain_state.workflow_stage == "working"


class TestHiveTrackerInteraction:
    """Loop detection and regression detection must survive a multi-task jump."""

    def test_batch_jump_is_not_a_regression(self, orchestrator, hive_state, loop_env):
        _run_hive_stage(orchestrator, hive_state, "TASKS COMPLETE: 1, 2, 3")

        should_abort, reason = orchestrator.tracker.should_abort()
        assert should_abort is False, reason

    def test_resuming_below_the_highest_completed_task_is_not_a_regression(
        self, orchestrator, hive_state, loop_env
    ):
        """Task 3 checked off, run resumes at task 2 — the tracker must not abort."""
        _run_hive_stage(orchestrator, hive_state, "TASKS COMPLETE: 1, 3")

        orchestrator.tracker.start_session(
            session_id=2, task_index=hive_state.current_task_index, task_description="task 2"
        )
        should_abort, reason = orchestrator.tracker.should_abort()
        assert should_abort is False, reason

    def test_a_lead_reporting_no_progress_eventually_trips_loop_detection(
        self, orchestrator, hive_state, loop_env
    ):
        """Case 2 cannot spin forever: the same index re-attempted trips the tracker."""
        for _ in range(4):
            _run_hive_stage(orchestrator, hive_state, "TASKS COMPLETE: none")

        should_abort, reason = orchestrator.tracker.should_abort()
        assert should_abort is True
        assert "Loop detected" in reason


class TestHiveWebhooks:
    def test_batch_completion_reports_every_task_it_closed(
        self, orchestrator, hive_state, loop_env
    ):
        with patch.object(orchestrator.webhook_emitter, "emit") as emit:
            _run_hive_stage(orchestrator, hive_state, "TASKS COMPLETE: 1, 2, 3")

        completed = [c for c in emit.call_args_list if c.args and c.args[0] == "task.completed"]
        assert len(completed) == 1
        assert completed[0].kwargs["task_index"] == 2
        assert "#1, #2, #3" in completed[0].kwargs["task_description"]

    def test_a_session_that_closed_nothing_emits_no_completion(
        self, orchestrator, hive_state, loop_env
    ):
        with patch.object(orchestrator.webhook_emitter, "emit") as emit:
            _run_hive_stage(orchestrator, hive_state, "TASKS COMPLETE: none")

        assert not [c for c in emit.call_args_list if c.args and c.args[0] == "task.completed"]
