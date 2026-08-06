"""Tests for the undelivered-fix guard on push-only stages.

Regression: a review-fix session ended before committing (the agent ending its
turn on a backgrounded typecheck). The orchestrator posted the comment replies,
resolved the threads on GitHub, and advanced to ``waiting_ci`` — which read the
*previous* push's green CI as this fix's and walked the PR to merge. The merge
then died on a raw git error, because ``gh pr merge`` checks branches out and
the fix was still sitting in the working tree:

    Auto-merge failed: ... Your local changes to the following files would be
    overwritten by checkout: apps/internal-api/test/unit/...

A push-only session promises two things — commit, then push. Both are checked
against the repository, not the agent's report.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

_GIT_OPS = "claude_task_master.core.stages.git_ops"


@pytest.fixture(autouse=True)
def _quiet() -> Generator[None, None, None]:
    with (
        patch("time.sleep"),
        patch(f"{_GIT_OPS}.console"),
        patch("claude_task_master.core.stages.review_stage.console"),
        patch("claude_task_master.core.stages.pr_fix_stage.console"),
        patch("claude_task_master.core.stages.merge_stage.console"),
        # Imported into each stage module by name, so patch it there.
        patch(
            "claude_task_master.core.stages.review_stage.interruptible_sleep",
            return_value=True,
        ),
        patch(
            "claude_task_master.core.stages.pr_fix_stage.interruptible_sleep",
            return_value=True,
        ),
    ):
        yield


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.run_work_session = MagicMock(return_value={"output": "fixed", "success": True})
    return agent


@pytest.fixture
def mock_pr_context() -> MagicMock:
    ctx = MagicMock()
    ctx.save_pr_comments = MagicMock(return_value=2)
    ctx.post_comment_replies = MagicMock()
    ctx.save_ci_failures = MagicMock()
    ctx.get_combined_feedback = MagicMock(return_value=(True, True, "/tmp/pr"))
    return ctx


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
        workflow_stage="addressing_reviews",
        current_task_index=0,
        session_count=1,
        current_pr=42,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=TaskOptions(**sample_task_options),
    )


def _delivered(clean: bool = True):
    """Patch the two repo probes a push-only session is judged by."""
    return patch.object(
        WorkflowStageHandler,
        "_fix_session_unfinished_reason",
        return_value=None if clean else "uncommitted changes left behind",
    )


class TestReviewFixNotDelivered:
    """The regression: threads must not be resolved for an uncommitted fix."""

    def test_threads_are_not_resolved(self, handler, state, mock_pr_context):
        with _delivered(clean=False):
            result = handler.handle_addressing_reviews_stage(state)

        assert result is None
        mock_pr_context.post_comment_replies.assert_not_called()
        # Stays put so the session re-runs — never advances onto stale CI.
        assert state.workflow_stage == "addressing_reviews"
        assert state.fix_finish_attempts == 1

    def test_delivered_fix_resolves_and_advances(self, handler, state, mock_pr_context):
        state.fix_finish_attempts = 1

        with _delivered(clean=True):
            result = handler.handle_addressing_reviews_stage(state)

        assert result is None
        mock_pr_context.post_comment_replies.assert_called_once()
        assert state.workflow_stage == "waiting_ci"
        assert state.fix_finish_attempts == 0

    def test_blocks_after_attempt_budget(self, handler, state, mock_pr_context):
        state.fix_finish_attempts = handler.MAX_FIX_FINISH_ATTEMPTS

        with _delivered(clean=False):
            result = handler.handle_addressing_reviews_stage(state)

        assert result == 1
        assert state.status == "blocked"
        mock_pr_context.post_comment_replies.assert_not_called()


class TestCIFixNotDelivered:
    """A CI fix that never landed must not consume the CI-fix budget."""

    def test_stays_in_ci_failed_without_burning_budget(self, handler, state):
        state.workflow_stage = "ci_failed"
        state.ci_fix_attempts = 0

        with _delivered(clean=False):
            result = handler.handle_ci_failed_stage(state)

        assert result is None
        assert state.workflow_stage == "ci_failed"
        assert state.fix_finish_attempts == 1
        # Incremented on entry, refunded because no fix was produced.
        assert state.ci_fix_attempts == 0

    def test_delivered_fix_advances_to_waiting_ci(self, handler, state):
        state.workflow_stage = "ci_failed"

        with _delivered(clean=True):
            result = handler.handle_ci_failed_stage(state)

        assert result is None
        assert state.workflow_stage == "waiting_ci"
        assert state.fix_finish_attempts == 0


class TestMergeRefusesDirtyTree:
    """`gh pr merge` checks branches out — never call it on a dirty tree."""

    def test_dirty_tree_never_reaches_gh_pr_merge(self, handler, state, mock_github_client):
        """A dirty tree diverts to the cleanup session (see
        test_merge_dirty_tree_recovery), but `gh pr merge` is never called on it."""
        state.workflow_stage = "ready_to_merge"
        state.options.auto_merge = True

        with (
            patch.object(
                WorkflowStageHandler, "_uncommitted_summary", return_value=" M src/thing.py"
            ),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/x"),
            patch.object(WorkflowStageHandler, "_head_sha", return_value="abc123"),
            patch.object(WorkflowStageHandler, "_unpushed_commit_count", return_value=0),
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result is None
        assert state.workflow_stage == "ready_to_merge"
        assert state.merge_cleanup_attempts == 1
        mock_github_client.merge_pr.assert_not_called()

    def test_clean_tree_merges(self, handler, state, mock_github_client):
        state.workflow_stage = "ready_to_merge"
        state.options.auto_merge = True

        with (
            patch.object(WorkflowStageHandler, "_uncommitted_summary", return_value=""),
            patch.object(WorkflowStageHandler, "_confirm_pr_merged", return_value=True),
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result is None
        mock_github_client.merge_pr.assert_called_once()

    def test_unreadable_repo_does_not_stall_the_merge(self, handler, state, mock_github_client):
        """An unreadable repo is left to `gh`, not turned into a block."""
        state.workflow_stage = "ready_to_merge"
        state.options.auto_merge = True

        with (
            patch.object(WorkflowStageHandler, "_porcelain_status", return_value=None),
            patch.object(WorkflowStageHandler, "_confirm_pr_merged", return_value=True),
        ):
            result = handler.handle_ready_to_merge_stage(state)

        assert result is None
        mock_github_client.merge_pr.assert_called_once()


class TestFixSessionUnfinishedReason:
    """The probe: dirty tree, unpushed commits, and the unknown cases."""

    def test_dirty_tree(self, handler):
        with patch.object(WorkflowStageHandler, "_porcelain_status", return_value=" M a.py"):
            assert handler._fix_session_unfinished_reason("feat/x") is not None

    def test_unpushed_commits(self, handler):
        with (
            patch.object(WorkflowStageHandler, "_porcelain_status", return_value=""),
            patch.object(WorkflowStageHandler, "_unpushed_commit_count", return_value=2),
        ):
            reason = handler._fix_session_unfinished_reason("feat/x")
        assert reason is not None and "push" in reason

    def test_clean_and_pushed(self, handler):
        with (
            patch.object(WorkflowStageHandler, "_porcelain_status", return_value=""),
            patch.object(WorkflowStageHandler, "_unpushed_commit_count", return_value=0),
        ):
            assert handler._fix_session_unfinished_reason("feat/x") is None

    def test_unreadable_repo_is_not_a_violation(self, handler):
        """Fail open — never loop re-running a session over a repo we can't read."""
        with patch.object(WorkflowStageHandler, "_porcelain_status", return_value=None):
            assert handler._fix_session_unfinished_reason("feat/x") is None

    def test_probes_read_the_project_tree_not_the_process_cwd(self, handler, state_manager):
        """Regression: measured against whatever repo the process happened to sit in.

        `_unpushed_commit_count` ran without a cwd, so in a checkout of the
        project's own repo (CI) it counted the PR's commits as unpushed and
        every fix stage refused to advance — while passing locally, where the
        process cwd happened to have nothing committed yet.
        """
        project = str(state_manager.state_dir.parent)

        with patch(f"{_GIT_OPS}.subprocess.run") as run:
            run.return_value = MagicMock(stdout="0\n", returncode=0)
            handler._unpushed_commit_count("feat/x")
            handler._porcelain_status()

        assert run.call_args_list, "expected git to be invoked"
        for call in run.call_args_list:
            assert call.kwargs.get("cwd") == project

    def test_unknown_push_state_is_not_a_violation(self, handler):
        with (
            patch.object(WorkflowStageHandler, "_porcelain_status", return_value=""),
            patch.object(WorkflowStageHandler, "_unpushed_commit_count", return_value=None),
        ):
            assert handler._fix_session_unfinished_reason("feat/x") is None
