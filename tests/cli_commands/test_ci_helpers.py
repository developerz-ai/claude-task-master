"""Tests for CI helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.cli_commands.ci_helpers import (
    CI_TIMEOUT,
    GitHubCITimeoutError,
    is_check_pending,
    wait_for_ci_complete,
)


class TestIsCheckPending:
    """Tests for is_check_pending function."""

    def test_pending_status(self) -> None:
        assert is_check_pending({"status": "PENDING", "conclusion": None}) is True

    def test_expected_status(self) -> None:
        assert is_check_pending({"status": "EXPECTED", "conclusion": None}) is True

    def test_completed_with_success(self) -> None:
        assert is_check_pending({"status": "COMPLETED", "conclusion": "success"}) is False

    def test_completed_with_failure(self) -> None:
        assert is_check_pending({"status": "COMPLETED", "conclusion": "failure"}) is False

    def test_queued_no_conclusion(self) -> None:
        assert is_check_pending({"status": "QUEUED", "conclusion": None}) is True

    def test_in_progress_no_conclusion(self) -> None:
        assert is_check_pending({"status": "IN_PROGRESS", "conclusion": None}) is True

    def test_empty_status_no_conclusion(self) -> None:
        assert is_check_pending({"status": "", "conclusion": None}) is True

    def test_missing_status(self) -> None:
        assert is_check_pending({"conclusion": None}) is True

    def test_lowercase_pending(self) -> None:
        assert is_check_pending({"status": "pending", "conclusion": None}) is True

    def test_completed_lowercase(self) -> None:
        assert is_check_pending({"status": "completed", "conclusion": "success"}) is False


class TestWaitForCIComplete:
    """Tests for wait_for_ci_complete function."""

    def _make_status(
        self,
        ci_state: str = "SUCCESS",
        checks: list[dict] | None = None,
        mergeable: str = "MERGEABLE",
    ) -> MagicMock:
        status = MagicMock()
        status.ci_state = ci_state
        status.check_details = checks or []
        status.checks_passed = sum(1 for c in (checks or []) if c.get("conclusion") == "success")
        status.checks_failed = sum(1 for c in (checks or []) if c.get("conclusion") == "failure")
        status.mergeable = mergeable
        status.base_branch = "main"
        return status

    def test_returns_immediately_when_all_checks_complete(self) -> None:
        """Should return immediately when no checks are pending."""
        mock_github = MagicMock()
        status = self._make_status(
            checks=[{"name": "test", "status": "COMPLETED", "conclusion": "success"}]
        )
        mock_github.get_pr_status.return_value = status
        mock_github.get_required_status_checks.return_value = ["test"]

        result = wait_for_ci_complete(mock_github, 123)
        assert result == status

    def test_returns_immediately_when_no_checks(self) -> None:
        """Should return when there are no checks at all."""
        mock_github = MagicMock()
        status = self._make_status(checks=[])
        mock_github.get_pr_status.return_value = status
        mock_github.get_required_status_checks.return_value = []

        result = wait_for_ci_complete(mock_github, 123)
        assert result == status

    @patch("claude_task_master.cli_commands.ci_helpers.time.sleep")
    def test_waits_for_pending_check(self, mock_sleep: MagicMock) -> None:
        """Should poll until pending check completes."""
        mock_github = MagicMock()

        pending = self._make_status(
            checks=[{"name": "test", "status": "IN_PROGRESS", "conclusion": None}]
        )
        done = self._make_status(
            checks=[{"name": "test", "status": "COMPLETED", "conclusion": "success"}]
        )
        mock_github.get_pr_status.side_effect = [pending, pending, done]
        mock_github.get_required_status_checks.return_value = []

        result = wait_for_ci_complete(mock_github, 123)
        assert result.checks_passed == 1
        assert mock_sleep.call_count >= 1

    @patch("claude_task_master.cli_commands.ci_helpers.time.sleep")
    @patch("claude_task_master.cli_commands.ci_helpers.time.monotonic")
    def test_timeout_returns_current_status(
        self, mock_monotonic: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Should return current status when timeout is exceeded."""
        mock_github = MagicMock()

        pending = self._make_status(
            checks=[{"name": "test", "status": "PENDING", "conclusion": None}]
        )
        mock_github.get_pr_status.return_value = pending
        mock_github.get_required_status_checks.return_value = []

        # Simulate time passing: first call returns 0, second returns past timeout
        mock_monotonic.side_effect = [0, 0, 100]  # start, first loop check, second loop check

        result = wait_for_ci_complete(mock_github, 123, timeout=50)
        assert result == pending

    @patch("claude_task_master.cli_commands.ci_helpers.time.sleep")
    def test_waits_for_missing_required_check(self, mock_sleep: MagicMock) -> None:
        """Should wait for required checks that haven't reported yet."""
        mock_github = MagicMock()

        # First: only one check reported, missing "coderabbit"
        partial = self._make_status(
            checks=[{"name": "test", "status": "COMPLETED", "conclusion": "success"}]
        )
        # Second: both reported
        complete = self._make_status(
            checks=[
                {"name": "test", "status": "COMPLETED", "conclusion": "success"},
                {"name": "coderabbit", "status": "COMPLETED", "conclusion": "success"},
            ]
        )
        mock_github.get_pr_status.side_effect = [partial, partial, complete]
        mock_github.get_required_status_checks.return_value = ["test", "coderabbit"]

        result = wait_for_ci_complete(mock_github, 123)
        assert result.checks_passed == 2

    def test_returns_with_conflicts(self) -> None:
        """Should return status with conflict flag when checks pass but PR has conflicts."""
        mock_github = MagicMock()
        status = self._make_status(
            checks=[{"name": "test", "status": "COMPLETED", "conclusion": "success"}],
            mergeable="CONFLICTING",
        )
        mock_github.get_pr_status.return_value = status
        mock_github.get_required_status_checks.return_value = []

        result = wait_for_ci_complete(mock_github, 123)
        assert result.mergeable == "CONFLICTING"


class TestGitHubCITimeoutError:
    """Tests for the GitHubCITimeoutError exception."""

    def test_stores_pr_number_and_elapsed(self) -> None:
        """Should expose pr_number and elapsed as attributes."""
        err = GitHubCITimeoutError(pr_number=42, elapsed=75.5, timeout=50, waiting=["test"])
        assert err.pr_number == 42
        assert err.elapsed == 75.5

    def test_message_includes_timeout_pr_and_waiting_checks(self) -> None:
        """Message should mention the timeout, PR number, and pending check names."""
        err = GitHubCITimeoutError(
            pr_number=42, elapsed=75.0, timeout=50, waiting=["build", "lint"]
        )
        message = str(err)
        assert "50s" in message
        assert "#42" in message
        assert "build" in message
        assert "lint" in message

    def test_message_truncates_waiting_list_to_five(self) -> None:
        """Message should list at most the first five pending check names."""
        waiting = [f"check-{i}" for i in range(8)]
        err = GitHubCITimeoutError(pr_number=1, elapsed=10.0, timeout=5, waiting=waiting)
        message = str(err)
        for name in waiting[:5]:
            assert name in message
        for name in waiting[5:]:
            assert name not in message


class TestWaitForCITimeout:
    """Tests for wait_for_ci_complete timeout behavior."""

    def _make_pending_status(self) -> MagicMock:
        status = MagicMock()
        status.ci_state = "PENDING"
        status.check_details = [{"name": "test", "status": "PENDING", "conclusion": None}]
        status.checks_passed = 0
        status.checks_failed = 0
        status.mergeable = "MERGEABLE"
        status.base_branch = "main"
        return status

    def _make_github(self, status: MagicMock) -> MagicMock:
        mock_github = MagicMock()
        mock_github.get_pr_status.return_value = status
        mock_github.get_required_status_checks.return_value = []
        return mock_github

    @patch("claude_task_master.cli_commands.ci_helpers.time.sleep")
    @patch("claude_task_master.cli_commands.ci_helpers.time.monotonic")
    def test_timeout_without_raise_returns_last_status(
        self, mock_monotonic: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Should warn and return the last PRStatus on timeout by default."""
        pending = self._make_pending_status()
        mock_github = self._make_github(pending)

        # Simulate time passing: start, first loop check, second loop check past timeout
        mock_monotonic.side_effect = [0, 0, 100]

        result = wait_for_ci_complete(mock_github, 123, timeout=50, raise_on_timeout=False)
        assert result == pending

    @patch("claude_task_master.cli_commands.ci_helpers.time.sleep")
    @patch("claude_task_master.cli_commands.ci_helpers.time.monotonic")
    def test_timeout_with_raise_raises_github_ci_timeout_error(
        self, mock_monotonic: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Should raise GitHubCITimeoutError on timeout when raise_on_timeout=True."""
        pending = self._make_pending_status()
        mock_github = self._make_github(pending)

        mock_monotonic.side_effect = [0, 0, 100, 100, 100]

        with pytest.raises(GitHubCITimeoutError) as exc_info:
            wait_for_ci_complete(mock_github, 123, timeout=50, raise_on_timeout=True)

        assert exc_info.value.pr_number == 123
        assert exc_info.value.elapsed >= 50
        assert "50" in str(exc_info.value)

    @patch("claude_task_master.cli_commands.ci_helpers.time.sleep")
    @patch("claude_task_master.cli_commands.ci_helpers.time.monotonic")
    def test_timeout_default_raise_on_timeout_returns_last_status(
        self, mock_monotonic: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """raise_on_timeout should default to False, returning the last status on timeout."""
        pending = self._make_pending_status()
        mock_github = self._make_github(pending)

        mock_monotonic.side_effect = [0, 0, 100]

        result = wait_for_ci_complete(mock_github, 123, timeout=50)
        assert result == pending

    @patch("claude_task_master.cli_commands.ci_helpers.time.sleep")
    @patch("claude_task_master.cli_commands.ci_helpers.time.monotonic")
    def test_raised_error_message_includes_pending_check_names(
        self, mock_monotonic: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Raised GitHubCITimeoutError should name the checks still pending at timeout."""
        pending = self._make_pending_status()
        mock_github = self._make_github(pending)

        mock_monotonic.side_effect = [0, 0, 100, 100, 100]

        with pytest.raises(GitHubCITimeoutError, match="test"):
            wait_for_ci_complete(mock_github, 123, timeout=50, raise_on_timeout=True)

    @patch("claude_task_master.cli_commands.ci_helpers.time.sleep")
    @patch("claude_task_master.cli_commands.ci_helpers.time.monotonic")
    def test_raised_error_includes_missing_required_checks(
        self, mock_monotonic: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """Raised error should name required checks that never reported before timeout."""
        pending = self._make_pending_status()
        mock_github = self._make_github(pending)
        mock_github.get_required_status_checks.return_value = ["coderabbit"]

        mock_monotonic.side_effect = [0, 0, 100, 100, 100]

        with pytest.raises(GitHubCITimeoutError, match="coderabbit"):
            wait_for_ci_complete(mock_github, 123, timeout=50, raise_on_timeout=True)

    def test_raise_on_timeout_true_does_not_raise_when_checks_complete(self) -> None:
        """Should return the final status without raising when checks finish in time."""
        status = MagicMock()
        status.ci_state = "SUCCESS"
        status.check_details = [{"name": "test", "status": "COMPLETED", "conclusion": "success"}]
        status.checks_passed = 1
        status.checks_failed = 0
        status.mergeable = "MERGEABLE"
        status.base_branch = "main"
        mock_github = self._make_github(status)

        result = wait_for_ci_complete(mock_github, 123, timeout=50, raise_on_timeout=True)
        assert result == status

    def test_github_ci_timeout_error_is_exception_subclass(self) -> None:
        """GitHubCITimeoutError should be a subclass of Exception."""
        assert issubclass(GitHubCITimeoutError, Exception)

    def test_timeout_constant_is_120_minutes(self) -> None:
        """CI_TIMEOUT should be 120 minutes."""
        assert CI_TIMEOUT == 120 * 60
