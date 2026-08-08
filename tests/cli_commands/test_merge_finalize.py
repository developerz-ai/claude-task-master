"""Unit tests for merge verification, plus the CLI's link to the cleanup policy.

The cleanup policy itself now lives in ``core.git_branch`` and is tested in
``tests/core/test_git_branch_cleanup.py`` — this module only has to show that
``merge-pr`` still reaches *that* implementation rather than a second copy.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from claude_task_master.cli_commands import merge_finalize
from claude_task_master.cli_commands.merge_finalize import merge_failure_hint, verify_merged
from claude_task_master.core import git_branch


def _status(
    state: str = "OPEN",
    merged_at: str | None = None,
    head_branch: str = "feature/x",
    base_branch: str = "main",
    merge_state_status: str = "BLOCKED",
) -> MagicMock:
    status = MagicMock()
    status.state = state
    status.merged_at = merged_at
    status.head_branch = head_branch
    status.base_branch = base_branch
    status.merge_state_status = merge_state_status
    return status


class TestVerifyMerged:
    """GitHub decides whether the merge happened."""

    def test_merged_state_is_confirmed(self) -> None:
        client = MagicMock()
        client.get_pr_status.return_value = _status(state="MERGED", head_branch="feature/x")

        result = verify_merged(client, 7, polls=3, interval=0)
        assert result.merged is True
        assert result.head_branch == "feature/x"
        assert result.base_branch == "main"

    def test_merged_at_alone_confirms(self) -> None:
        client = MagicMock()
        client.get_pr_status.return_value = _status(merged_at="2026-08-08T10:00:00Z")

        assert verify_merged(client, 7, polls=2, interval=0).merged is True

    def test_still_open_is_not_merged(self) -> None:
        client = MagicMock()
        client.get_pr_status.return_value = _status(state="OPEN")

        result = verify_merged(client, 7, polls=2, interval=0)
        assert result.merged is False
        assert result.state == "OPEN"
        assert "still OPEN" in result.detail
        assert "BLOCKED" in result.detail

    def test_closed_without_merge_reported_immediately(self) -> None:
        client = MagicMock()
        client.get_pr_status.return_value = _status(state="CLOSED")

        result = verify_merged(client, 7, polls=5, interval=0)
        assert result.merged is False
        assert "CLOSED" in result.detail
        assert client.get_pr_status.call_count == 1

    def test_transient_read_error_is_retried_not_fatal(self) -> None:
        client = MagicMock()
        client.get_pr_status.side_effect = [
            Exception("502 Bad Gateway"),
            _status(state="MERGED"),
        ]

        assert verify_merged(client, 7, polls=3, interval=0).merged is True

    def test_unreadable_state_is_never_success(self) -> None:
        client = MagicMock()
        client.get_pr_status.side_effect = Exception("502 Bad Gateway")

        result = verify_merged(client, 7, polls=2, interval=0)
        assert result.merged is False
        assert result.state is None
        assert "could not read" in result.detail
        assert "502" in result.detail

    def test_non_string_fields_are_not_trusted(self) -> None:
        """A bare MagicMock status must not read as merged."""
        client = MagicMock()
        client.get_pr_status.return_value = MagicMock()

        assert verify_merged(client, 7, polls=2, interval=0).merged is False


class TestMergeFailureHint:
    """Policy refusals have a documented remedy."""

    def test_policy_refusal_points_at_admin(self) -> None:
        hint = merge_failure_hint("the base branch policy prohibits the merge", False, 42)
        assert hint is not None
        assert "--admin" in hint
        assert "42" in hint

    def test_no_hint_when_admin_already_used(self) -> None:
        assert merge_failure_hint("the base branch policy prohibits the merge", True, 42) is None

    def test_no_hint_for_unrelated_failure(self) -> None:
        assert merge_failure_hint("connection reset by peer", False, 42) is None


class TestDelegatesToTheSharedPolicy:
    """One implementation of the branch-cleanup policy, in core, for both callers."""

    def test_cleanup_is_the_core_policy(self) -> None:
        assert merge_finalize.delete_merged_branch is git_branch.delete_merged_branch

    def test_git_helpers_are_the_core_ones(self) -> None:
        assert merge_finalize.run_git is git_branch.run_git
        assert merge_finalize.git_failure is git_branch.git_failure
        assert merge_finalize.local_branch_exists is git_branch.local_branch_exists
