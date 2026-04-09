"""Tests for CI helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from claude_task_master.cli_commands.ci_helpers import (
    CI_TIMEOUT,
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
        status.checks_passed = sum(
            1 for c in (checks or []) if c.get("conclusion") == "success"
        )
        status.checks_failed = sum(
            1 for c in (checks or []) if c.get("conclusion") == "failure"
        )
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

    def test_timeout_constant_is_90_minutes(self) -> None:
        """CI_TIMEOUT should be 90 minutes."""
        assert CI_TIMEOUT == 90 * 60

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
