"""Tests for local branch cleanup after a merge (issue #153, orchestrator half).

``handle_merged_stage`` used to capture ``self._get_current_branch()`` and hand
it to ``git branch -D``: "delete whatever we happen to be on", unconditionally
forced. That is the same defect #153 reported against ``claudetm merge-pr``,
where it destroyed an unrelated *open* PR's branch. The orchestrator is normally
sitting on the PR's own branch — but "normally" is not a safety property, and
``-D`` discards unmerged commits with nothing but the reflog behind it.

The branch to delete is now the PR's **head** branch, read from GitHub together
with the base and the merged state, and the deletion itself goes through the one
shared policy (``core.git_branch.delete_merged_branch``, which ``claudetm
merge-pr`` calls too) rather than a second copy of it here.
"""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

_MERGE = "claude_task_master.core.stages.merge_stage"
_POLICY = "claude_task_master.core.git_branch"


@pytest.fixture(autouse=True)
def _quiet() -> Generator[None, None, None]:
    with (
        patch("time.sleep"),
        patch(f"{_MERGE}.console"),
        patch("claude_task_master.core.stages.git_ops.console"),
        patch(f"{_POLICY}.console"),
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
    return TaskState(
        status="working",
        workflow_stage="merged",
        current_task_index=0,
        session_count=1,
        current_pr=42,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=TaskOptions(**sample_task_options),
    )


def _pr_status(*, state: str = "MERGED", head: str = "feat/x", base: str = "main") -> MagicMock:
    status = MagicMock()
    status.number = 42
    status.state = state
    status.head_branch = head
    status.base_branch = base
    return status


def _merged_stage(handler: WorkflowStageHandler, task_state: TaskState) -> None:
    """Run handle_merged_stage with the checkout stubbed out (it is not under test).

    Stubbing it True *without* actually switching branches is deliberate: it
    leaves the process sitting on an unrelated branch, which is exactly the
    situation the old code deleted.
    """
    with patch.object(WorkflowStageHandler, "_checkout_branch", return_value=True):
        handler.handle_merged_stage(task_state, MagicMock())


# --------------------------------------------------------------------------- #
# End-to-end, against a real repository
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t.invalid",
            "-c",
            "user.name=t",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _branches(repo: Path) -> set[str]:
    out = _git(repo, "branch", "--format=%(refname:short)").stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """main ← feat/x (merged), plus an unrelated other/pr which stays checked out."""
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "commit", "--allow-empty", "-m", "a")
    _git(path, "checkout", "-b", "feat/x")
    _git(path, "commit", "--allow-empty", "-m", "b")
    _git(path, "checkout", "main")
    _git(path, "merge", "--ff-only", "feat/x")
    _git(path, "checkout", "-b", "other/pr")
    _git(path, "commit", "--allow-empty", "-m", "c")
    return path


@pytest.mark.timeout(30)
class TestOnlyThePRsOwnBranchIsDeleted:
    """The checked-out branch is not evidence of anything."""

    def test_unrelated_checked_out_branch_survives(
        self, handler, state, mock_github_client, repo, monkeypatch
    ):
        monkeypatch.chdir(repo)
        mock_github_client.get_pr_status.return_value = _pr_status()

        _merged_stage(handler, state)

        remaining = _branches(repo)
        assert "other/pr" in remaining  # the branch we happened to be on
        assert "main" in remaining
        assert "feat/x" not in remaining  # the merged PR's own branch

    def test_nothing_is_deleted_when_the_merge_is_not_confirmed(
        self, handler, state, mock_github_client, repo, monkeypatch
    ):
        monkeypatch.chdir(repo)
        mock_github_client.get_pr_status.return_value = _pr_status(state="OPEN")

        _merged_stage(handler, state)

        assert _branches(repo) == {"main", "feat/x", "other/pr"}

    def test_base_branch_is_never_deleted(
        self, handler, state, mock_github_client, repo, monkeypatch
    ):
        """A PR whose head is reported as the base must not take main with it."""
        monkeypatch.chdir(repo)
        mock_github_client.get_pr_status.return_value = _pr_status(head="main")

        _merged_stage(handler, state)

        assert "main" in _branches(repo)


# --------------------------------------------------------------------------- #
# What the stage hands to the shared policy
# --------------------------------------------------------------------------- #


class TestDelegatesToTheSharedPolicy:
    """One decision point for merge-pr and the orchestrator, not two."""

    def test_passes_the_pr_head_branch(self, handler, state, mock_github_client):
        mock_github_client.get_pr_status.return_value = _pr_status()

        with patch(f"{_MERGE}.delete_merged_branch") as delete:
            _merged_stage(handler, state)

        delete.assert_called_once_with("feat/x", "main", 42)

    def test_unidentifiable_head_branch_deletes_nothing(self, handler, state, mock_github_client):
        """An empty head ref must reach the policy as None, which no-ops."""
        mock_github_client.get_pr_status.return_value = _pr_status(head="")

        with patch(f"{_MERGE}.delete_merged_branch") as delete:
            _merged_stage(handler, state)

        delete.assert_called_once_with(None, "main", 42)

    def test_failed_status_lookup_deletes_nothing(self, handler, state, mock_github_client):
        """Unknown head, unknown base, unknown merge state — touch nothing."""
        mock_github_client.get_pr_status.side_effect = Exception("GitHub is down")

        with patch(f"{_MERGE}.delete_merged_branch") as delete:
            _merged_stage(handler, state)

        delete.assert_not_called()

    def test_unconfirmed_merge_never_reaches_the_policy(self, handler, state, mock_github_client):
        mock_github_client.get_pr_status.return_value = _pr_status(state="OPEN")

        with patch(f"{_MERGE}.delete_merged_branch") as delete:
            _merged_stage(handler, state)

        delete.assert_not_called()
