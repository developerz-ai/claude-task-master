"""Tests for merge-pr main loop logic (CI fix loop, merge, exit conditions)."""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from claude_task_master.cli import app

runner = CliRunner()
COMMAND = "merge-pr"

# Common patch paths
FIX_PR = "claude_task_master.cli_commands.fix_pr"
GITHUB = "claude_task_master.github.GitHubClient"


def strip_ansi(text: str) -> str:
    return re.compile(r"\x1b\[[0-9;]*m").sub("", text)


def _make_pr_status(
    ci_state: str = "SUCCESS",
    unresolved_threads: int = 0,
    mergeable: str = "MERGEABLE",
    checks_passed: int = 1,
    checks_failed: int = 0,
) -> MagicMock:
    """Create a mock PRStatus."""
    status = MagicMock()
    status.ci_state = ci_state
    status.unresolved_threads = unresolved_threads
    status.mergeable = mergeable
    status.checks_passed = checks_passed
    status.checks_failed = checks_failed
    status.check_details = []
    status.base_branch = "main"
    return status


def _setup_mocks(
    mock_github_class: MagicMock,
    mock_cred_class: MagicMock,
    mock_state_class: MagicMock,
) -> tuple[MagicMock, MagicMock]:
    """Common mock setup. Returns (mock_github, mock_state)."""
    mock_github = MagicMock()
    mock_github_class.return_value = mock_github

    mock_cred_class.return_value.get_valid_token.return_value = "test-token"

    mock_state = MagicMock()
    mock_state.is_session_active.return_value = False
    mock_state.acquire_session_lock.return_value = True
    mock_state_class.return_value = mock_state

    return mock_github, mock_state


class TestMergePRLoopSuccess:
    """Tests for successful merge-pr flows."""

    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_exits_0_on_clean_merge(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
    ) -> None:
        """Should exit 0 when CI passes and PR merges successfully."""
        mock_github, mock_state = _setup_mocks(
            mock_github_class, mock_cred_class, mock_state_class
        )
        mock_wait_ci.return_value = _make_pr_status()

        result = runner.invoke(app, [COMMAND, "123"])
        assert result.exit_code == 0
        mock_github.merge_pr.assert_called_once_with(123)
        mock_state.release_session_lock.assert_called()

    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_exits_0_no_merge_flag(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
    ) -> None:
        """Should exit 0 with --no-merge when CI is clean."""
        mock_github, mock_state = _setup_mocks(
            mock_github_class, mock_cred_class, mock_state_class
        )
        mock_wait_ci.return_value = _make_pr_status()

        result = runner.invoke(app, [COMMAND, "123", "--no-merge"])
        assert result.exit_code == 0
        mock_github.merge_pr.assert_not_called()
        output = strip_ansi(result.stdout)
        assert "ready to merge" in output

    @patch(f"{FIX_PR}.time.sleep")
    @patch(f"{FIX_PR}.run_fix_session", return_value=True)
    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_fixes_then_merges(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
        mock_fix: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Should fix CI failure, then merge on next iteration."""
        mock_github, _ = _setup_mocks(
            mock_github_class, mock_cred_class, mock_state_class
        )

        # First: CI fails. Second: CI passes.
        mock_wait_ci.side_effect = [
            _make_pr_status(ci_state="FAILURE", checks_failed=1),
            _make_pr_status(),
        ]

        result = runner.invoke(app, [COMMAND, "123"])
        assert result.exit_code == 0
        mock_fix.assert_called_once()
        mock_github.merge_pr.assert_called_once()


class TestMergePRLoopFailures:
    """Tests for failure conditions in merge-pr."""

    @patch(f"{FIX_PR}.run_fix_session", return_value=False)
    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_exits_1_unresolvable_comments(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
        mock_fix: MagicMock,
    ) -> None:
        """Should exit 1 when comments can't be resolved and CI passes."""
        _setup_mocks(mock_github_class, mock_cred_class, mock_state_class)
        mock_wait_ci.return_value = _make_pr_status(unresolved_threads=2)

        result = runner.invoke(app, [COMMAND, "123"])
        assert result.exit_code == 1
        output = strip_ansi(result.stdout)
        assert "manual review" in output

    @patch(f"{FIX_PR}.time.sleep")
    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_exits_1_merge_conflicts_at_merge_time(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Should exit 1 when PR has merge conflicts discovered at merge time."""
        mock_github, _ = _setup_mocks(
            mock_github_class, mock_cred_class, mock_state_class
        )
        # CI passes with MERGEABLE initially, but get_pr_status returns CONFLICTING
        # during the mergeable wait polling
        mock_wait_ci.return_value = _make_pr_status(mergeable="UNKNOWN")
        mock_github.get_pr_status.return_value = _make_pr_status(mergeable="CONFLICTING")

        result = runner.invoke(app, [COMMAND, "123"])
        assert result.exit_code == 1
        output = strip_ansi(result.stdout)
        assert "merge conflicts" in output

    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_exits_1_merge_exception(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
    ) -> None:
        """Should exit 1 when merge raises an exception."""
        mock_github, _ = _setup_mocks(
            mock_github_class, mock_cred_class, mock_state_class
        )
        mock_wait_ci.return_value = _make_pr_status()
        mock_github.merge_pr.side_effect = Exception("branch protection")

        result = runner.invoke(app, [COMMAND, "123"])
        assert result.exit_code == 1
        output = strip_ansi(result.stdout)
        assert "Merge failed" in output


class TestMergePRMaxIterations:
    """Tests for max iteration handling."""

    @patch(f"{FIX_PR}.time.sleep")
    @patch(f"{FIX_PR}.run_fix_session", return_value=True)
    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_final_ci_check_after_max_iterations(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
        mock_fix: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """After exhausting iterations, should do a final CI check and merge if clean."""
        mock_github, _ = _setup_mocks(
            mock_github_class, mock_cred_class, mock_state_class
        )

        # 2 iterations of failure, then final check passes
        mock_wait_ci.side_effect = [
            _make_pr_status(ci_state="FAILURE", checks_failed=1),
            _make_pr_status(ci_state="FAILURE", checks_failed=1),
            # This is the final CI check after for-else
            _make_pr_status(),
        ]

        result = runner.invoke(app, [COMMAND, "123", "-m", "2"])
        assert result.exit_code == 0
        mock_github.merge_pr.assert_called_once()

    @patch(f"{FIX_PR}.time.sleep")
    @patch(f"{FIX_PR}.run_fix_session", return_value=True)
    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_exits_1_when_still_broken_after_max(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
        mock_fix: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Should exit 1 when CI still fails after all iterations + final check."""
        _setup_mocks(mock_github_class, mock_cred_class, mock_state_class)

        failing = _make_pr_status(ci_state="FAILURE", checks_failed=1)
        # 2 iterations + 1 final check, all failing
        mock_wait_ci.side_effect = [failing, failing, failing]

        result = runner.invoke(app, [COMMAND, "123", "-m", "2"])
        assert result.exit_code == 1
        output = strip_ansi(result.stdout)
        assert "Max iterations" in output


class TestMergePRLockRelease:
    """Tests that session lock is always released."""

    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_lock_released_on_success(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
    ) -> None:
        _, mock_state = _setup_mocks(
            mock_github_class, mock_cred_class, mock_state_class
        )
        mock_wait_ci.return_value = _make_pr_status()

        runner.invoke(app, [COMMAND, "123"])
        mock_state.release_session_lock.assert_called()

    @patch(f"{FIX_PR}.run_fix_session", return_value=False)
    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_lock_released_on_failure(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
        mock_fix: MagicMock,
    ) -> None:
        _, mock_state = _setup_mocks(
            mock_github_class, mock_cred_class, mock_state_class
        )
        mock_wait_ci.return_value = _make_pr_status(unresolved_threads=3)

        runner.invoke(app, [COMMAND, "123"])
        mock_state.release_session_lock.assert_called()

    @patch(f"{FIX_PR}.wait_for_ci_complete")
    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_lock_released_on_exception(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_wait_ci: MagicMock,
    ) -> None:
        _, mock_state = _setup_mocks(
            mock_github_class, mock_cred_class, mock_state_class
        )
        mock_wait_ci.side_effect = Exception("network error")

        runner.invoke(app, [COMMAND, "123"])
        mock_state.release_session_lock.assert_called()

    @patch(f"{FIX_PR}.StateManager")
    @patch(f"{FIX_PR}.CredentialManager")
    @patch(GITHUB)
    def test_no_lock_on_active_session(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
    ) -> None:
        """Should not acquire lock if another session is active."""
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github
        mock_cred_class.return_value.get_valid_token.return_value = "test-token"

        mock_state = MagicMock()
        mock_state.is_session_active.return_value = True
        mock_state_class.return_value = mock_state

        result = runner.invoke(app, [COMMAND, "123"])
        assert result.exit_code == 1
        output = strip_ansi(result.stdout)
        assert "Another claudetm session" in output
