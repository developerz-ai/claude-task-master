"""Post-merge behaviour of ``claudetm merge-pr``: verify, then clean up.

Regression tests for two compounding defects:

* #153 — cleanup deleted the *checked-out* local branch instead of the merged
  PR's head branch, destroying an unrelated open PR's branch.
* #152 — a merge that never happened was reported as success and exited 0,
  and the destructive cleanup ran anyway.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from claude_task_master.cli import app

runner = CliRunner()
COMMAND = "merge-pr"

FIX_PR = "claude_task_master.cli_commands.fix_pr"
GITHUB = "claude_task_master.github.GitHubClient"
MERGE_FINALIZE = "claude_task_master.cli_commands.merge_finalize"

# Seams the command uses for the destructive half of the flow.
CHECKOUT = f"{FIX_PR}.checkout_and_pull"
DELETE_BRANCH = f"{FIX_PR}.delete_merged_branch"


def strip_ansi(text: str) -> str:
    return re.compile(r"\x1b\[[0-9;]*m").sub("", text)


@pytest.fixture(autouse=True)
def _fast_sleep():
    """Neutralize the CI/review/merge-confirmation sleeps."""
    with (
        patch(f"{FIX_PR}.time.sleep"),
        patch(f"{MERGE_FINALIZE}.time.sleep"),
    ):
        yield


def _pr_status(
    state: str = "OPEN",
    merged_at: str | None = None,
    head_branch: str = "feature/pr-branch",
    base_branch: str = "main",
    ci_state: str = "SUCCESS",
    mergeable: str = "MERGEABLE",
) -> MagicMock:
    status = MagicMock()
    status.state = state
    status.merged_at = merged_at
    status.head_branch = head_branch
    status.base_branch = base_branch
    status.ci_state = ci_state
    status.mergeable = mergeable
    status.merge_state_status = "CLEAN"
    status.unresolved_threads = 0
    status.checks_passed = 1
    status.checks_failed = 0
    status.check_details = []
    return status


def _setup(
    mock_github_class: MagicMock,
    mock_cred_class: MagicMock,
    mock_state_class: MagicMock,
) -> tuple[MagicMock, MagicMock]:
    mock_github = MagicMock()
    mock_github_class.return_value = mock_github
    mock_cred_class.return_value.get_valid_token.return_value = "test-token"

    mock_state = MagicMock()
    mock_state.is_session_active.return_value = False
    mock_state.acquire_session_lock.return_value = True
    mock_state_class.return_value = mock_state
    return mock_github, mock_state


class TestDeletesTheMergedPRsBranch:
    """#153: the branch that gets deleted is the merged PR's head branch."""

    @patch(DELETE_BRANCH)
    @patch(CHECKOUT, return_value=True)
    @patch(f"{MERGE_FINALIZE}.get_current_branch", return_value="other/open-pr-branch")
    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_deletes_pr_head_branch_not_checked_out_branch(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
        mock_branch: MagicMock,
        mock_checkout: MagicMock,
        mock_delete: MagicMock,
    ) -> None:
        """Run from an unrelated branch: only PR #342's own branch may be deleted."""
        mock_github, _ = _setup(mock_github_class, mock_cred_class, mock_state_class)
        mock_wait_ci.return_value = _pr_status(head_branch="dependabot/github_actions/minor-85123b")
        mock_github.get_pr_status.return_value = _pr_status(
            state="MERGED",
            merged_at="2026-08-08T00:00:00Z",
            head_branch="dependabot/github_actions/minor-85123b",
        )

        result = runner.invoke(app, [COMMAND, "342"])
        assert result.exit_code == 0
        mock_delete.assert_called_once()
        assert mock_delete.call_args.args[0] == "dependabot/github_actions/minor-85123b"
        # The unrelated branch the operator happened to be on must survive.
        assert "other/open-pr-branch" not in str(mock_delete.call_args)


class TestFailedMergeIsNotSuccess:
    """#152: the repository, not the command's own report, decides."""

    @patch(DELETE_BRANCH)
    @patch(CHECKOUT, return_value=True)
    @patch(f"{MERGE_FINALIZE}.get_current_branch", return_value="feature/pr-branch")
    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_unmerged_pr_exits_nonzero_without_claiming_success(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
        mock_branch: MagicMock,
        mock_checkout: MagicMock,
        mock_delete: MagicMock,
    ) -> None:
        """gh returned 0 but the PR is still OPEN — that is a failed merge."""
        mock_github, mock_state = _setup(mock_github_class, mock_cred_class, mock_state_class)
        mock_wait_ci.return_value = _pr_status()
        mock_github.get_pr_status.return_value = _pr_status(state="OPEN")

        result = runner.invoke(app, [COMMAND, "123"])
        output = strip_ansi(result.stdout)
        assert result.exit_code != 0
        assert "merged successfully" not in output
        assert "not merged" in output.lower()
        mock_state.release_session_lock.assert_called()

    @patch(DELETE_BRANCH)
    @patch(CHECKOUT, return_value=True)
    @patch(f"{MERGE_FINALIZE}.get_current_branch", return_value="feature/pr-branch")
    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_no_cleanup_after_unmerged_pr(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
        mock_branch: MagicMock,
        mock_checkout: MagicMock,
        mock_delete: MagicMock,
    ) -> None:
        """No checkout, no branch delete, when the merge did not land."""
        mock_github, _ = _setup(mock_github_class, mock_cred_class, mock_state_class)
        mock_wait_ci.return_value = _pr_status()
        mock_github.get_pr_status.return_value = _pr_status(state="OPEN")

        result = runner.invoke(app, [COMMAND, "123"])
        assert result.exit_code != 0
        mock_delete.assert_not_called()
        mock_checkout.assert_not_called()

    @patch(DELETE_BRANCH)
    @patch(CHECKOUT, return_value=True)
    @patch(f"{MERGE_FINALIZE}.get_current_branch", return_value="feature/pr-branch")
    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_no_cleanup_when_merge_command_fails(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
        mock_branch: MagicMock,
        mock_checkout: MagicMock,
        mock_delete: MagicMock,
    ) -> None:
        """A non-zero ``gh pr merge`` must exit non-zero and delete nothing."""
        mock_github, _ = _setup(mock_github_class, mock_cred_class, mock_state_class)
        mock_wait_ci.return_value = _pr_status()
        mock_github.merge_pr.side_effect = Exception(
            "Failed to merge PR #123: Pull request is not mergeable: "
            "the base branch policy prohibits the merge"
        )

        result = runner.invoke(app, [COMMAND, "123"])
        output = strip_ansi(result.stdout)
        assert result.exit_code != 0
        assert "merged successfully" not in output
        # The policy refusal has a documented remedy; say so.
        assert "--admin" in output
        mock_delete.assert_not_called()
        mock_checkout.assert_not_called()

    @patch(DELETE_BRANCH)
    @patch(CHECKOUT, return_value=True)
    @patch(f"{MERGE_FINALIZE}.get_current_branch", return_value="feature/pr-branch")
    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_unverifiable_merge_does_not_delete(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
        mock_branch: MagicMock,
        mock_checkout: MagicMock,
        mock_delete: MagicMock,
    ) -> None:
        """If the merge state cannot be read, nothing local is destroyed."""
        mock_github, _ = _setup(mock_github_class, mock_cred_class, mock_state_class)
        mock_wait_ci.return_value = _pr_status()
        mock_github.get_pr_status.side_effect = Exception("502 Bad Gateway")

        result = runner.invoke(app, [COMMAND, "123"])
        assert result.exit_code != 0
        mock_delete.assert_not_called()
        mock_checkout.assert_not_called()
