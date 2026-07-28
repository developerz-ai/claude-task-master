"""Tests for the two ways a finished PR group could fail to produce a PR.

Both were observed on the same run: 48 tasks completed, 10 commits stacked on
one local branch, zero PRs opened.

1. **Repeated headings merged into one group.** A planner that restates its
   task list (a draft, then a corrected reissue) writes ``### PR 1: …`` more
   than once. The parser folded every restatement into a single group, so the
   group's task indices were non-contiguous and "is this the last task in the
   group?" stayed False for the whole first block — the orchestrator kept
   committing locally and never entered the PR stage.

2. **A skipped task closing a group.** A task already checked off runs no
   session, and the skip path returned without ever asking whether that task
   closed its group — so a resume walked straight past the boundary and the
   group's commits stayed on the branch.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.orchestrator import WorkLoopOrchestrator
from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.task_group import parse_tasks_with_groups

_MODULE = "claude_task_master.core.loop_working_stage"


class TestRepeatedHeadingsStayContiguous:
    """A restated task list must not merge into the earlier group."""

    #: A draft plan, then the same headings reissued — the shape that stalled.
    REISSUED_PLAN = """## Task List

### PR 1: Design tokens

- [ ] Scaffold the package
- [ ] Wire the palette

### PR 2: Consume the tokens

- [ ] Swap marketing

## Verification

Reissuing the corrected plan.

### PR 1: Design tokens

- [ ] Scaffold the package
- [ ] Wire the palette

### PR 2: Consume the tokens

- [ ] Swap marketing
"""

    def test_restated_headings_open_new_group_instances(self):
        tasks, groups = parse_tasks_with_groups(self.REISSUED_PLAN)

        assert [g.id for g in groups] == ["pr_1", "pr_2", "pr_1#2", "pr_2#2"]
        assert [t.group_id for t in tasks] == [
            "pr_1",
            "pr_1",
            "pr_2",
            "pr_1#2",
            "pr_1#2",
            "pr_2#2",
        ]

    def test_every_group_holds_a_contiguous_index_run(self):
        _, groups = parse_tasks_with_groups(self.REISSUED_PLAN)

        for group in groups:
            indices = group.task_indices
            assert indices == list(range(indices[0], indices[-1] + 1)), group.id

    def test_restated_group_keeps_the_heading_name_and_number(self):
        _, groups = parse_tasks_with_groups(self.REISSUED_PLAN)

        repeat = next(g for g in groups if g.id == "pr_1#2")
        assert repeat.name == "Design tokens"
        assert repeat.pr_number == 1

    def test_the_same_heading_twice_in_a_row_is_not_a_new_instance(self):
        """Re-entering the group already current is a duplicate line, not a block."""
        plan = "### PR 1: Tokens\n\n### PR 1: Tokens\n\n- [ ] Only task\n"

        tasks, groups = parse_tasks_with_groups(plan)

        assert [g.id for g in groups] == ["pr_1"]
        assert tasks[0].group_id == "pr_1"

    def test_unrepeated_plan_is_unchanged(self):
        plan = "### PR 1: A\n\n- [ ] One\n\n### PR 2: B\n\n- [ ] Two\n"

        tasks, groups = parse_tasks_with_groups(plan)

        assert [g.id for g in groups] == ["pr_1", "pr_2"]
        assert [t.group_id for t in tasks] == ["pr_1", "pr_2"]


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.run_work_session = MagicMock(return_value={"output": "done", "success": True})
    agent.extract_session_learnings = MagicMock(return_value="")
    return agent


@pytest.fixture
def orchestrator(mock_agent, state_manager, mock_github_client):
    return WorkLoopOrchestrator(
        agent=mock_agent,
        state_manager=state_manager,
        planner=MagicMock(),
        github_client=mock_github_client,
    )


@pytest.fixture
def task_state(sample_task_options):
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


#: Two groups; the first group's last task is already checked off.
_PLAN_WITH_COMPLETE_GROUP_END = """## Task List

### PR 1: First group

- [x] Task one
- [x] Task two

### PR 2: Second group

- [ ] Task three
"""


@pytest.fixture
def skip_env(state_manager):
    """Plan on disk, console silenced, running on a feature branch."""
    state_manager.state_dir.mkdir(exist_ok=True)
    state_manager.save_plan(_PLAN_WITH_COMPLETE_GROUP_END)
    state_manager.save_goal("Test goal")
    with (
        patch(f"{_MODULE}.console"),
        patch("claude_task_master.core.task_runner_session.console"),
        patch(
            "claude_task_master.core.loop_context._LoopContextMixin._get_current_branch"
        ) as branch,
    ):
        branch.return_value = "feat/x"
        yield branch


class TestSkippedTaskClosingAGroup:
    """An already-complete task still has to hand its group to the PR stage."""

    def test_skipped_last_task_routes_to_the_pr_stage(self, orchestrator, task_state, skip_env):
        task_state.current_task_index = 1  # last task of PR 1, already [x]

        result = orchestrator._handle_working_stage(task_state)

        assert result is None
        assert task_state.workflow_stage == "pr_created"

    def test_index_is_rewound_to_the_group_s_last_task(self, orchestrator, task_state, skip_env):
        """The PR stages act on the last task; handle_merged_stage advances past it."""
        task_state.current_task_index = 1

        orchestrator._handle_working_stage(task_state)

        assert task_state.current_task_index == 1

    def test_skipped_mid_group_task_keeps_working(self, orchestrator, task_state, skip_env):
        task_state.current_task_index = 0  # first of two in PR 1

        orchestrator._handle_working_stage(task_state)

        assert task_state.workflow_stage == "working"
        assert task_state.current_task_index == 1

    def test_on_the_base_branch_nothing_is_shipped(self, orchestrator, task_state, skip_env):
        """No group work is committed on base — and the PR stage blocks there."""
        skip_env.return_value = "main"
        task_state.current_task_index = 1

        orchestrator._handle_working_stage(task_state)

        assert task_state.workflow_stage == "working"
        assert task_state.current_task_index == 2
