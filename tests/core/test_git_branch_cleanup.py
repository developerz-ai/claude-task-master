"""The shared post-merge branch-cleanup policy (issue #153).

``delete_merged_branch`` is the single decision point behind both callers —
``claudetm merge-pr`` and the orchestrator's merged stage — so it is tested
here, in core, rather than once per caller. Every case below is a way the
deletion can be *wrong*; the policy answers all of them with a no-op.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from claude_task_master.core.git_branch import current_branch, delete_merged_branch

MODULE = "claude_task_master.core.git_branch"


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestDeleteMergedBranch:
    """Deletion is a no-op whenever it cannot be proven safe."""

    @patch(f"{MODULE}.current_branch", return_value="main")
    @patch(f"{MODULE}.run_git")
    def test_unknown_branch_deletes_nothing(self, run_git: MagicMock, _branch: MagicMock) -> None:
        delete_merged_branch(None, "main", 1)
        run_git.assert_not_called()

    @patch(f"{MODULE}.current_branch", return_value="main")
    @patch(f"{MODULE}.run_git")
    def test_base_branch_is_never_deleted(self, run_git: MagicMock, _branch: MagicMock) -> None:
        delete_merged_branch("main", "main", 1)
        run_git.assert_not_called()

    @patch(f"{MODULE}.current_branch", return_value="main")
    @patch(f"{MODULE}.run_git")
    def test_missing_local_branch_is_a_noop(self, run_git: MagicMock, _branch: MagicMock) -> None:
        run_git.return_value = _proc(returncode=1)  # rev-parse --verify fails

        delete_merged_branch("feature/x", "main", 1)
        assert all("branch" not in call.args for call in run_git.call_args_list)

    @patch(f"{MODULE}.current_branch", return_value="feature/x")
    @patch(f"{MODULE}.run_git")
    def test_checked_out_branch_is_not_deleted(
        self, run_git: MagicMock, _branch: MagicMock
    ) -> None:
        run_git.return_value = _proc()  # branch exists

        delete_merged_branch("feature/x", "main", 1)
        assert all(call.args[0] != "branch" for call in run_git.call_args_list)

    @patch(f"{MODULE}.current_branch", return_value="main")
    @patch(f"{MODULE}.run_git")
    def test_safe_delete_uses_lowercase_d(self, run_git: MagicMock, _branch: MagicMock) -> None:
        run_git.return_value = _proc()

        delete_merged_branch("feature/x", "main", 1)
        assert ("branch", "-d", "feature/x") in [call.args for call in run_git.call_args_list]
        assert ("branch", "-D", "feature/x") not in [call.args for call in run_git.call_args_list]

    @patch(f"{MODULE}.current_branch", return_value="main")
    @patch(f"{MODULE}.run_git")
    def test_squash_merge_forces_only_when_nothing_is_unpushed(
        self, run_git: MagicMock, _branch: MagicMock
    ) -> None:
        def fake(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
            if args[:2] == ("rev-parse", "--verify"):
                return _proc()  # both refs/heads and refs/remotes exist
            if args[0] == "branch" and args[1] == "-d":
                return _proc(returncode=1, stderr="error: branch 'feature/x' is not fully merged")
            if args[0] == "rev-list":
                return _proc(stdout="0\n")  # nothing local beyond origin
            return _proc()

        run_git.side_effect = fake

        delete_merged_branch("feature/x", "main", 1)
        assert ("branch", "-D", "feature/x") in [call.args for call in run_git.call_args_list]

    @patch(f"{MODULE}.current_branch", return_value="main")
    @patch(f"{MODULE}.run_git")
    def test_unpushed_commits_keep_the_branch(self, run_git: MagicMock, _branch: MagicMock) -> None:
        def fake(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
            if args[:2] == ("rev-parse", "--verify"):
                return _proc()
            if args[0] == "branch" and args[1] == "-d":
                return _proc(returncode=1, stderr="error: branch 'feature/x' is not fully merged")
            if args[0] == "rev-list":
                return _proc(stdout="3\n")  # 3 commits never pushed
            return _proc()

        run_git.side_effect = fake

        delete_merged_branch("feature/x", "main", 1)
        assert ("branch", "-D", "feature/x") not in [call.args for call in run_git.call_args_list]

    @patch(f"{MODULE}.current_branch", return_value="main")
    @patch(f"{MODULE}.run_git")
    def test_missing_remote_ref_keeps_the_branch(
        self, run_git: MagicMock, _branch: MagicMock
    ) -> None:
        """Without a remote-tracking ref we cannot prove nothing is unpushed."""

        def fake(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
            if args[:2] == ("rev-parse", "--verify"):
                ref = args[-1]
                return _proc() if ref.startswith("refs/heads/") else _proc(returncode=1)
            if args[0] == "branch" and args[1] == "-d":
                return _proc(returncode=1, stderr="not fully merged")
            return _proc()

        run_git.side_effect = fake

        delete_merged_branch("feature/x", "main", 1)
        assert ("branch", "-D", "feature/x") not in [call.args for call in run_git.call_args_list]


class TestCurrentBranch:
    """The one probe that decides "are we standing on the branch we'd delete?"."""

    @patch(f"{MODULE}.run_git", return_value=_proc(stdout="feature/x\n"))
    def test_reports_the_checked_out_branch(self, _run_git: MagicMock) -> None:
        assert current_branch() == "feature/x"

    @patch(f"{MODULE}.run_git", return_value=_proc(stdout="\n"))
    def test_detached_head_is_none(self, _run_git: MagicMock) -> None:
        assert current_branch() is None

    @patch(f"{MODULE}.run_git", return_value=None)
    def test_unrunnable_git_is_none(self, _run_git: MagicMock) -> None:
        assert current_branch() is None
