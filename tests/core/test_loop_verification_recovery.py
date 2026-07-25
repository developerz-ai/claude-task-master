"""Tests for _open_missing_fix_pr — recovery on the verification-fix path.

The PR stages learned to open a PR themselves when a session committed but
stopped before `gh pr create`; the verification path had no such recovery, so
the same half-finished session left the run dead with the fix sitting on a
local branch and a human needed to open the PR by hand.

Only the unambiguous case is recovered: a real feature branch, a clean tree,
commits over the base. Everything else reports the failure as before rather
than pushing something it cannot vouch for.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.orchestrator import WorkLoopOrchestrator
from claude_task_master.core.orchestrator_loop import OrchestratorLoop
from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

_MODULE = "claude_task_master.core.loop_verification"


@pytest.fixture
def orchestrator(state_manager, mock_github_client):
    state_manager.state_dir.mkdir(exist_ok=True)
    mock_github_client.create_pr = MagicMock(return_value=77)
    return WorkLoopOrchestrator(
        agent=MagicMock(),
        state_manager=state_manager,
        planner=MagicMock(),
        github_client=mock_github_client,
    )


@pytest.fixture
def loop(orchestrator):
    return OrchestratorLoop(orchestrator)


@pytest.fixture
def state(sample_task_options):
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


@contextmanager
def repo(branch="fix/verification", dirty=False, ahead=2, push_error=None):
    """Pin the git view the recovery decides from. Yields the push mock."""
    with ExitStack() as stack:
        stack.enter_context(patch(f"{_MODULE}.console"))
        for name, value in (
            ("_get_current_branch", branch),
            ("_has_uncommitted_changes", dirty),
            ("_commits_ahead_of_base", ahead),
        ):
            stack.enter_context(patch.object(WorkflowStageHandler, name, return_value=value))
        yield stack.enter_context(
            patch.object(WorkflowStageHandler, "_push_current_branch", side_effect=push_error)
        )


class TestOpenMissingFixPR:
    def test_opens_the_pr_when_the_branch_has_commits(self, loop, state, orchestrator):
        with repo() as push:
            pr = loop._open_missing_fix_pr(state)

        assert pr == 77
        push.assert_called_once()
        orchestrator.github_client.create_pr.assert_called_once()

    def test_refuses_on_the_base_branch(self, loop, state, orchestrator):
        with repo(branch="main"):
            assert loop._open_missing_fix_pr(state) is None
        orchestrator.github_client.create_pr.assert_not_called()

    def test_refuses_on_a_dirty_tree(self, loop, state, orchestrator):
        with repo(dirty=True):
            assert loop._open_missing_fix_pr(state) is None
        orchestrator.github_client.create_pr.assert_not_called()

    def test_refuses_when_nothing_is_ahead_of_base(self, loop, state, orchestrator):
        with repo(ahead=0):
            assert loop._open_missing_fix_pr(state) is None
        orchestrator.github_client.create_pr.assert_not_called()

    def test_refuses_when_the_base_comparison_is_unknown(self, loop, state, orchestrator):
        """None means unmeasurable — never read as "nothing to ship", nor as proof."""
        with repo(ahead=None):
            assert loop._open_missing_fix_pr(state) is None
        orchestrator.github_client.create_pr.assert_not_called()

    def test_push_failure_reports_rather_than_raising(self, loop, state):
        with repo(push_error=RuntimeError("rejected")):
            assert loop._open_missing_fix_pr(state) is None
