"""Tests for _PRRecovery — pr_created stage self-heal when no PR exists.

Regression: a PR group whose non-last tasks committed in commit-only mode
("do NOT push or create a PR") ended with a verification-only last task; the
agent truthfully reported "nothing to ship, no PR", and the orchestrator hit
handle_pr_created_stage → "No PR found for current branch!" → blocked, with
the group's commits stranded unpushed on the local branch. The orchestrator
must recover deterministically (push + create the PR itself, or advance when
the branch has nothing over the base) instead of blocking.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

_MODULE = "claude_task_master.core.stages.pr_recovery"


@pytest.fixture
def mock_github_client():
    client = MagicMock()
    client.get_pr_for_current_branch = MagicMock(return_value=None)
    client.create_pr = MagicMock(return_value=123)
    client.get_pr_body = MagicMock(return_value="")
    return client


@pytest.fixture
def workflow_handler(state_manager, mock_github_client):
    return WorkflowStageHandler(
        agent=MagicMock(),
        state_manager=state_manager,
        github_client=mock_github_client,
        pr_context=MagicMock(),
    )


@pytest.fixture
def task_state(sample_task_options):
    now = datetime.now().isoformat()
    return TaskState(
        status="working",
        workflow_stage="pr_created",
        current_task_index=0,
        session_count=1,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=TaskOptions(**sample_task_options),
    )


@pytest.fixture
def recovery_env(state_manager):
    """Patch console + git helpers so recovery runs hermetically.

    Yields a dict of the git-helper mocks; individual tests override returns.
    Defaults model the regression scenario: feature branch, clean tree,
    commits ahead of base, push succeeds.
    """
    state_manager.state_dir.mkdir(exist_ok=True)
    with (
        patch(f"{_MODULE}.console"),
        patch("claude_task_master.core.stages.ci_stage.console"),
        patch.object(
            WorkflowStageHandler, "_get_current_branch", return_value="feat/group-branch"
        ) as branch,
        patch.object(WorkflowStageHandler, "_has_uncommitted_changes", return_value=False) as dirty,
        patch.object(WorkflowStageHandler, "_commits_ahead_of_base", return_value=3) as ahead,
        patch.object(WorkflowStageHandler, "_push_current_branch") as push,
    ):
        yield {"branch": branch, "dirty": dirty, "ahead": ahead, "push": push}


class TestRecoverMissingPR:
    """handle_pr_created_stage with no PR on the branch."""

    def test_commits_ahead_pushes_and_creates_pr(
        self, workflow_handler, task_state, mock_github_client, recovery_env
    ):
        """Regression: stranded group commits are pushed and PR'd, not blocked."""
        result = workflow_handler.handle_pr_created_stage(task_state)

        assert result is None
        assert task_state.status == "working"  # not blocked
        recovery_env["push"].assert_called_once()
        mock_github_client.create_pr.assert_called_once()
        # Stage stays pr_created so the next cycle detects the PR normally.
        assert task_state.workflow_stage == "pr_created"

    def test_created_pr_detected_on_next_cycle(
        self, workflow_handler, task_state, mock_github_client, recovery_env
    ):
        """After recovery opens the PR, the next cycle picks it up and moves to CI."""
        workflow_handler.handle_pr_created_stage(task_state)
        mock_github_client.get_pr_for_current_branch.return_value = 123

        result = workflow_handler.handle_pr_created_stage(task_state)

        assert result is None
        assert task_state.current_pr == 123
        assert task_state.workflow_stage == "waiting_ci"

    def test_nothing_to_ship_advances_to_merged(
        self, workflow_handler, task_state, mock_github_client, recovery_env
    ):
        """A group with zero commits over base is done — no PR, no block."""
        recovery_env["ahead"].return_value = 0

        result = workflow_handler.handle_pr_created_stage(task_state)

        assert result is None
        assert task_state.workflow_stage == "merged"
        assert task_state.status == "working"
        mock_github_client.create_pr.assert_not_called()
        recovery_env["push"].assert_not_called()

    def test_on_base_branch_blocks(self, workflow_handler, task_state, recovery_env):
        """Sitting on the base branch is unrecoverable — block as before."""
        recovery_env["branch"].return_value = "main"

        result = workflow_handler.handle_pr_created_stage(task_state)

        assert result == 1
        assert task_state.status == "blocked"

    def test_dirty_tree_blocks(self, workflow_handler, task_state, recovery_env):
        """Uncommitted changes mean the session left unfinished work — block."""
        recovery_env["dirty"].return_value = True

        result = workflow_handler.handle_pr_created_stage(task_state)

        assert result == 1
        assert task_state.status == "blocked"

    def test_unknown_ahead_count_blocks(self, workflow_handler, task_state, recovery_env):
        """A failed base comparison is unknown, never treated as 0 — block."""
        recovery_env["ahead"].return_value = None

        result = workflow_handler.handle_pr_created_stage(task_state)

        assert result == 1
        assert task_state.status == "blocked"

    def test_push_failure_blocks(self, workflow_handler, task_state, recovery_env):
        """A failed push falls back to the manual-intervention block."""
        recovery_env["push"].side_effect = RuntimeError("remote rejected")

        result = workflow_handler.handle_pr_created_stage(task_state)

        assert result == 1
        assert task_state.status == "blocked"

    def test_create_pr_failure_blocks(
        self, workflow_handler, task_state, mock_github_client, recovery_env
    ):
        """A failed `gh pr create` falls back to the manual-intervention block."""
        mock_github_client.create_pr.side_effect = RuntimeError("gh exploded")

        result = workflow_handler.handle_pr_created_stage(task_state)

        assert result == 1
        assert task_state.status == "blocked"


class TestBuildGroupPRText:
    """PR title/body derivation from the plan's PR group."""

    def test_uses_group_name_and_completed_tasks(self, workflow_handler, task_state, state_manager):
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(
            "### PR 1: Auth overhaul\n"
            "- [x] Add login endpoint\n"
            "- [x] [quick] Verify session cookies\n"
        )

        title, body = workflow_handler._build_group_pr_text(task_state, "feat/auth")

        assert title == "feat: Auth overhaul"
        assert "- Add login endpoint" in body
        assert "- Verify session cookies" in body
        assert "orchestrator" in body

    def test_falls_back_to_branch_without_plan(self, workflow_handler, task_state):
        title, body = workflow_handler._build_group_pr_text(task_state, "feat/some-branch")

        assert title == "feat: feat/some-branch"
        assert "orchestrator" in body

    def test_title_is_truncated(self, workflow_handler, task_state, state_manager):
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(f"### PR 1: {'x' * 200}\n- [x] Task one\n")

        title, _ = workflow_handler._build_group_pr_text(task_state, "feat/long")

        assert len(title) <= 70
