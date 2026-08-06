"""Tests for the dirty-tree recovery in ``ready_to_merge``.

Regression: a run reached ``ready_to_merge`` on a green PR with two files an
`expo prebuild` had rewritten still sitting in the working tree. ``gh pr merge``
checks branches out, so the stage refused to merge — and then blocked outright::

    Refusing to merge PR #145: the working tree has uncommitted changes, ...
       D mobile/app/expo-env.d.ts
       M mobile/app/tsconfig.json

The condition is purely local and deterministic, so the escape hatch could not
escape it: ``claudetm resume -f --admin`` cleared the status, re-entered the same
stage, re-read the same unchanged tree and blocked again after running zero
sessions. The tree now goes to a bounded agent session instead, and a forced
resume refunds the spent attempt budgets.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

_HANDLER = "claude_task_master.core.workflow_stages.WorkflowStageHandler"


@pytest.fixture(autouse=True)
def _quiet() -> Generator[None, None, None]:
    with (
        patch("claude_task_master.core.stages.merge_cleanup.console"),
        patch("claude_task_master.core.stages.merge_stage.console"),
    ):
        yield


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.run_work_session = MagicMock(return_value={"output": "cleaned", "success": True})
    return agent


@pytest.fixture
def mock_github_client() -> MagicMock:
    client = MagicMock()
    status = MagicMock()
    status.state = "OPEN"
    status.mergeable = "MERGEABLE"
    status.base_branch = "main"
    status.head_branch = "feat/x"
    client.get_pr_status = MagicMock(return_value=status)
    client.get_pr_behind_by = MagicMock(return_value=0)
    return client


@pytest.fixture
def handler(mock_agent, state_manager, mock_github_client) -> WorkflowStageHandler:
    state_manager.state_dir.mkdir(exist_ok=True)
    return WorkflowStageHandler(
        agent=mock_agent,
        state_manager=state_manager,
        github_client=mock_github_client,
        pr_context=MagicMock(),
    )


@pytest.fixture
def state(sample_task_options) -> TaskState:
    now = datetime.now().isoformat()
    state = TaskState(
        status="working",
        workflow_stage="ready_to_merge",
        current_task_index=0,
        session_count=1,
        current_pr=145,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="opus",
        options=TaskOptions(**sample_task_options),
    )
    state.options.auto_merge = True
    return state


_PENDING = " D mobile/app/expo-env.d.ts\n M mobile/app/tsconfig.json"


class TestDirtyTreeRunsCleanupSession:
    """The regression: a dirty tree must not end the run on sight."""

    def test_dirty_tree_runs_a_session_instead_of_blocking(
        self, handler, state, mock_agent, mock_github_client
    ):
        with (
            patch.object(WorkflowStageHandler, "_uncommitted_summary", return_value=_PENDING),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/x"),
            patch.object(WorkflowStageHandler, "_head_sha", return_value="abc123"),
            patch.object(WorkflowStageHandler, "_unpushed_commit_count", return_value=0),
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result is None
        assert state.status == "working"
        # Still dirty afterwards → the stage repeats rather than merging.
        assert state.workflow_stage == "ready_to_merge"
        assert state.merge_cleanup_attempts == 1
        mock_agent.run_work_session.assert_called_once()
        mock_github_client.merge_pr.assert_not_called()

    def test_the_session_is_push_only_on_the_pr_branch(self, handler, state, mock_agent):
        with (
            patch.object(
                WorkflowStageHandler, "_uncommitted_summary", side_effect=[_PENDING, _PENDING]
            ),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/x"),
            patch.object(WorkflowStageHandler, "_head_sha", return_value="abc123"),
            patch.object(WorkflowStageHandler, "_unpushed_commit_count", return_value=0),
        ):
            handler.handle_ready_to_merge_stage(state)

        kwargs = mock_agent.run_work_session.call_args.kwargs
        assert kwargs["required_branch"] == "feat/x"
        assert kwargs["push_only"] is True
        assert kwargs["create_pr"] is False
        assert "#145" in kwargs["task_description"]
        assert "mobile/app/tsconfig.json" in kwargs["task_description"]

    def test_cleaned_tree_leaves_the_pr_ready_to_merge(
        self, handler, state, mock_github_client, mock_agent
    ):
        """Leftovers discarded, branch untouched → merge on the next cycle."""
        with (
            patch.object(WorkflowStageHandler, "_uncommitted_summary", side_effect=[_PENDING, ""]),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/x"),
            patch.object(WorkflowStageHandler, "_head_sha", return_value="abc123"),
            patch.object(WorkflowStageHandler, "_unpushed_commit_count", return_value=0),
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result is None
        assert state.status == "working"
        assert state.workflow_stage == "ready_to_merge"
        # The merge itself waits for the next cycle, which re-reads a clean tree.
        mock_github_client.merge_pr.assert_not_called()

    def test_new_commits_send_the_pr_back_through_ci(self, handler, state, mock_github_client):
        """A cleanup that committed must not merge on CI that predates it."""
        state.ci_poll_start_time = datetime.now()

        with (
            patch.object(WorkflowStageHandler, "_uncommitted_summary", side_effect=[_PENDING, ""]),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/x"),
            patch.object(WorkflowStageHandler, "_head_sha", side_effect=["abc123", "def456"]),
            patch.object(WorkflowStageHandler, "_unpushed_commit_count", return_value=0),
            patch.object(WorkflowStageHandler, "_push_current_branch"),
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result is None
        assert state.workflow_stage == "waiting_ci"
        assert state.ci_poll_start_time is None
        mock_github_client.merge_pr.assert_not_called()

    def test_an_unreadable_head_is_treated_as_moved(self, handler, state, mock_github_client):
        """Unknown must not read as "no new commits" — that merges on stale CI."""
        with (
            patch.object(WorkflowStageHandler, "_uncommitted_summary", side_effect=[_PENDING, ""]),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/x"),
            patch.object(WorkflowStageHandler, "_head_sha", return_value=None),
            patch.object(WorkflowStageHandler, "_unpushed_commit_count", return_value=None),
            patch.object(WorkflowStageHandler, "_push_current_branch") as push,
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result is None
        push.assert_called_once()
        assert state.workflow_stage == "waiting_ci"
        mock_github_client.merge_pr.assert_not_called()

    def test_committed_but_unpushed_work_is_pushed_before_merging(self, handler, state):
        """The tree reads clean, so nothing downstream would notice the gap."""
        with (
            patch.object(WorkflowStageHandler, "_uncommitted_summary", side_effect=[_PENDING, ""]),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/x"),
            patch.object(WorkflowStageHandler, "_head_sha", return_value="abc123"),
            patch.object(WorkflowStageHandler, "_unpushed_commit_count", return_value=1),
            patch.object(WorkflowStageHandler, "_push_current_branch") as push,
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result is None
        push.assert_called_once()
        assert state.workflow_stage == "waiting_ci"


class TestDirtyTreeStillBlocks:
    """Recovery only fires where it can be right; otherwise a human is needed."""

    def test_blocks_once_the_attempt_budget_is_spent(self, handler, state, mock_agent):
        state.merge_cleanup_attempts = handler.MAX_MERGE_CLEANUP_ATTEMPTS

        with (
            patch.object(WorkflowStageHandler, "_uncommitted_summary", return_value=_PENDING),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/x"),
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result == 1
        assert state.status == "blocked"
        mock_agent.run_work_session.assert_not_called()

    def test_leftovers_on_the_base_branch_block(self, handler, state, mock_agent):
        """Nothing on the base belongs to the PR, and a session must not commit there."""
        with (
            patch.object(WorkflowStageHandler, "_uncommitted_summary", return_value=_PENDING),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="main"),
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result == 1
        assert state.status == "blocked"
        mock_agent.run_work_session.assert_not_called()

    def test_a_crashed_cleanup_session_blocks(self, handler, state, mock_agent):
        mock_agent.run_work_session.side_effect = RuntimeError("session died")

        with (
            patch.object(WorkflowStageHandler, "_uncommitted_summary", return_value=_PENDING),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/x"),
            patch.object(WorkflowStageHandler, "_head_sha", return_value="abc123"),
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result == 1
        assert state.status == "blocked"

    def test_a_failed_push_blocks_rather_than_merging_without_it(self, handler, state):
        with (
            patch.object(WorkflowStageHandler, "_uncommitted_summary", side_effect=[_PENDING, ""]),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/x"),
            patch.object(WorkflowStageHandler, "_head_sha", return_value="abc123"),
            patch.object(WorkflowStageHandler, "_unpushed_commit_count", return_value=2),
            patch.object(
                WorkflowStageHandler, "_push_current_branch", side_effect=RuntimeError("rejected")
            ),
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result == 1
        assert state.status == "blocked"


class TestCounterResetOnTaskAdvance:
    """The budget is per PR, like every other attempt counter."""

    def test_advance_resets_the_cleanup_counter(self, handler, state):
        state.merge_cleanup_attempts = 2
        handler._advance_to_next_task(state)
        assert state.merge_cleanup_attempts == 0
