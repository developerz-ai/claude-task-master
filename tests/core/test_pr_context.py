"""Tests for PRContextManager - PR context handling.

This module tests:
- CI failure saving
- PR comment fetching and saving
- Comment reply posting
- Thread resolution
- Non-actionable comment filtering
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.pr_context import PRContextManager
from claude_task_master.core.state import StateManager

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def state_manager(tmp_path: Path) -> Generator[StateManager, None, None]:
    """Create a StateManager with a temporary directory."""
    state_dir = tmp_path / ".claude-task-master"
    sm = StateManager(state_dir=state_dir)
    yield sm
    if state_dir.exists():
        shutil.rmtree(state_dir)


@pytest.fixture
def mock_github_client() -> MagicMock:
    """Create a mock GitHub client."""
    client = MagicMock()
    client.get_failed_run_logs.return_value = "Error: Test failed\nLine 42"
    client.get_pr_status.return_value = MagicMock(check_details=[])
    return client


@pytest.fixture
def pr_context_manager(
    state_manager: StateManager, mock_github_client: MagicMock
) -> PRContextManager:
    """Create a PRContextManager with mocked dependencies."""
    return PRContextManager(state_manager, mock_github_client)


def make_graphql_response(threads: list[dict[str, Any]]) -> dict[str, Any]:
    """Helper to create GraphQL response structure."""
    return {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": threads}}}}}


# =============================================================================
# Constructor Tests
# =============================================================================


class TestPRContextManagerInit:
    """Tests for PRContextManager initialization."""

    def test_initialization(
        self, state_manager: StateManager, mock_github_client: MagicMock
    ) -> None:
        """Test PRContextManager can be initialized."""
        manager = PRContextManager(state_manager, mock_github_client)

        assert manager.state_manager is state_manager
        assert manager.github_client is mock_github_client


# =============================================================================
# save_ci_failures Tests
# =============================================================================


class TestSaveCIFailures:
    """Tests for save_ci_failures method."""

    def test_returns_early_for_none_pr(
        self, pr_context_manager: PRContextManager, mock_github_client: MagicMock
    ) -> None:
        """Test that save_ci_failures returns early when pr_number is None."""
        pr_context_manager.save_ci_failures(None)

        mock_github_client.get_failed_run_logs.assert_not_called()
        mock_github_client.get_pr_status.assert_not_called()

    def test_clears_old_ci_logs(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that old CI logs are cleared before saving new ones."""
        # Setup: create old CI log
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True)
        old_file = ci_dir / "old_failure.txt"
        old_file.write_text("Old failure")

        # Ensure mock returns empty check details
        mock_github_client.get_pr_status.return_value = MagicMock(check_details=[])

        pr_context_manager.save_ci_failures(123)

        # Old file should be gone (directory was cleared)
        assert not old_file.exists()

    def test_saves_failure_for_failed_checks(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that CI failures are saved for failed checks."""
        mock_github_client.get_failed_run_logs.return_value = "Test error output"
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[
                {"name": "test-job", "conclusion": "FAILURE"},
            ]
        )

        pr_context_manager.save_ci_failures(123)

        # Verify CI failure was saved
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        assert ci_dir.exists()
        ci_files = list(ci_dir.glob("failed_*.txt"))
        assert len(ci_files) == 1
        content = ci_files[0].read_text()
        assert "Test error output" in content

    def test_saves_failure_for_error_conclusion(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that CI failures are saved for ERROR conclusion."""
        mock_github_client.get_failed_run_logs.return_value = "Build error"
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[
                {"name": "build-job", "conclusion": "ERROR"},
            ]
        )

        pr_context_manager.save_ci_failures(123)

        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_files = list(ci_dir.glob("failed_*.txt"))
        assert len(ci_files) == 1

    def test_handles_log_retrieval_failure(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test fallback message when log retrieval fails."""
        mock_github_client.get_failed_run_logs.side_effect = Exception("Network error")
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[{"name": "test", "conclusion": "FAILURE"}]
        )

        pr_context_manager.save_ci_failures(123)

        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_files = list(ci_dir.glob("failed_*.txt"))
        assert len(ci_files) == 1
        content = ci_files[0].read_text()
        assert "Could not retrieve CI logs" in content

    def test_handles_pr_status_failure(
        self,
        pr_context_manager: PRContextManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test graceful handling when PR status retrieval fails."""
        mock_github_client.get_pr_status.side_effect = Exception("API error")

        # Should not raise
        with patch("claude_task_master.core.pr_context.console") as mock_console:
            pr_context_manager.save_ci_failures(123)
            mock_console.warning.assert_called()


# =============================================================================
# save_pr_comments Tests
# =============================================================================


class TestSavePRComments:
    """Tests for save_pr_comments method."""

    def test_returns_early_for_none_pr(self, pr_context_manager: PRContextManager) -> None:
        """Test that save_pr_comments returns early when pr_number is None."""
        with patch("subprocess.run") as mock_run:
            pr_context_manager.save_pr_comments(None)
            mock_run.assert_not_called()

    def test_clears_old_comments(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test that old comments are cleared before saving new ones."""
        # Setup: create old comments
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True)
        old_file = comments_dir / "old_comment.txt"
        old_file.write_text("Old comment")
        summary_file = pr_dir / "comments_summary.txt"
        summary_file.write_text("Old summary")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Stop after cleanup")
            pr_context_manager.save_pr_comments(123)

        # Old files should be gone
        assert not old_file.exists()
        assert not summary_file.exists()

    def test_fetches_and_saves_comments(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test fetching and saving PR comments via GraphQL."""
        graphql_response = make_graphql_response(
            [
                {
                    "id": "thread_1",
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {
                                "id": "comment_1",
                                "author": {"login": "reviewer"},
                                "body": "Please fix this issue in the code.",
                                "path": "src/main.py",
                                "line": 42,
                            }
                        ]
                    },
                }
            ]
        )

        with patch("subprocess.run") as mock_run:
            # First call: repo info
            mock_run.side_effect = [
                MagicMock(stdout="owner/repo\n"),
                MagicMock(stdout=json.dumps(graphql_response)),
            ]

            pr_context_manager.save_pr_comments(123)

        # Verify comments were saved
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        assert comments_dir.exists()

    def test_skips_resolved_threads(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test that resolved threads are skipped."""
        graphql_response = make_graphql_response(
            [
                {
                    "id": "thread_resolved",
                    "isResolved": True,  # Should be skipped
                    "comments": {
                        "nodes": [
                            {
                                "id": "comment_1",
                                "author": {"login": "reviewer"},
                                "body": "Already resolved comment",
                                "path": "src/main.py",
                                "line": 42,
                            }
                        ]
                    },
                },
                {
                    "id": "thread_unresolved",
                    "isResolved": False,  # Should be saved
                    "comments": {
                        "nodes": [
                            {
                                "id": "comment_2",
                                "author": {"login": "reviewer"},
                                "body": "Unresolved comment needs attention",
                                "path": "src/utils.py",
                                "line": 10,
                            }
                        ]
                    },
                },
            ]
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="owner/repo\n"),
                MagicMock(stdout=json.dumps(graphql_response)),
            ]

            pr_context_manager.save_pr_comments(123)

        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comment_files = list(comments_dir.glob("*.txt"))

        # Only unresolved thread's comment should be saved
        assert len(comment_files) == 1
        content = comment_files[0].read_text()
        assert "Unresolved comment" in content
        assert "Already resolved" not in content

    def test_skips_addressed_threads(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test that already-addressed threads are skipped."""
        # Mark a thread as addressed
        state_manager.mark_threads_addressed(123, ["thread_addressed"])

        graphql_response = make_graphql_response(
            [
                {
                    "id": "thread_addressed",  # Already addressed
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {
                                "id": "comment_1",
                                "author": {"login": "reviewer"},
                                "body": "Already addressed comment text",
                                "path": "src/main.py",
                                "line": 42,
                            }
                        ]
                    },
                },
                {
                    "id": "thread_new",  # New thread
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {
                                "id": "comment_2",
                                "author": {"login": "reviewer"},
                                "body": "New comment needs attention here",
                                "path": "src/utils.py",
                                "line": 10,
                            }
                        ]
                    },
                },
            ]
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="owner/repo\n"),
                MagicMock(stdout=json.dumps(graphql_response)),
            ]

            pr_context_manager.save_pr_comments(123)

        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comment_files = list(comments_dir.glob("*.txt"))

        # Only new thread's comment should be saved
        assert len(comment_files) == 1
        content = comment_files[0].read_text()
        assert "New comment" in content
        assert "Already addressed" not in content

    def test_handles_subprocess_error(
        self,
        pr_context_manager: PRContextManager,
    ) -> None:
        """Test graceful handling of subprocess errors."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "gh")

            with patch("claude_task_master.core.pr_context.console") as mock_console:
                pr_context_manager.save_pr_comments(123)
                mock_console.warning.assert_called()


# =============================================================================
# post_comment_replies Tests
# =============================================================================


class TestPostCommentReplies:
    """Tests for post_comment_replies method."""

    def test_returns_early_for_none_pr(self, pr_context_manager: PRContextManager) -> None:
        """Test that post_comment_replies returns early when pr_number is None."""
        with patch("subprocess.run") as mock_run:
            pr_context_manager.post_comment_replies(None)
            mock_run.assert_not_called()

    def test_handles_missing_resolve_file(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test handling when resolve-comments.json doesn't exist."""
        # Ensure PR dir exists but no resolve file
        state_manager.get_pr_dir(123)

        with patch("claude_task_master.core.pr_context.console") as mock_console:
            pr_context_manager.post_comment_replies(123)
            mock_console.detail.assert_called()

    def test_handles_empty_resolutions(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test handling when resolutions list is empty."""
        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(json.dumps({"resolutions": []}))

        pr_context_manager.post_comment_replies(123)
        # Should complete without errors

    def test_posts_replies_to_threads(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test posting replies to comment threads."""
        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "thread_123",
                            "action": "fixed",
                            "message": "Fixed the issue",
                        }
                    ]
                }
            )
        )

        with patch("subprocess.run") as mock_run:
            # First call: get resolved threads (repo info)
            # Second call: get resolved threads (graphql)
            # Third call: post reply
            # Fourth call: resolve thread
            mock_run.return_value = MagicMock(stdout=json.dumps(make_graphql_response([])))

            with patch("claude_task_master.core.pr_context.console"):
                pr_context_manager.post_comment_replies(123)

        # Verify GraphQL mutation was called (to post reply)
        assert mock_run.call_count >= 2

    def test_skips_already_resolved_threads(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test that already resolved threads are skipped."""
        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "thread_already_resolved",
                            "action": "fixed",
                            "message": "Already done",
                        }
                    ]
                }
            )
        )

        resolved_response = make_graphql_response(
            [{"id": "thread_already_resolved", "isResolved": True}]
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="owner/repo\n"),  # repo info
                MagicMock(stdout=json.dumps(resolved_response)),  # get resolved
            ]

            with patch("claude_task_master.core.pr_context.console") as mock_console:
                pr_context_manager.post_comment_replies(123)
                # Should log that thread is already resolved
                assert any("already resolved" in str(c) for c in mock_console.detail.call_args_list)

    def test_resolves_thread_on_fixed_action(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test that threads are resolved when action is 'fixed'."""
        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "thread_to_resolve",
                            "action": "fixed",
                            "message": "Fixed it",
                        }
                    ]
                }
            )
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=json.dumps(make_graphql_response([])))

            with patch("claude_task_master.core.pr_context.console"):
                pr_context_manager.post_comment_replies(123)

        # Should have made calls to resolve the thread
        # (repo info, get resolved, post reply, resolve thread)
        assert mock_run.call_count >= 3

    def test_marks_threads_addressed(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test that addressed threads are marked in state."""
        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "thread_abc",
                            "action": "explained",
                            "message": "Explained why",
                        }
                    ]
                }
            )
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=json.dumps(make_graphql_response([])))

            with patch("claude_task_master.core.pr_context.console"):
                pr_context_manager.post_comment_replies(123)

        # Verify thread was marked as addressed
        addressed = state_manager.get_addressed_threads(123)
        assert "thread_abc" in addressed

    def test_deletes_resolve_file_after_processing(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test that resolve-comments.json is deleted after processing."""
        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "thread_1",
                            "action": "fixed",
                            "message": "Done",
                        }
                    ]
                }
            )
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=json.dumps(make_graphql_response([])))

            with patch("claude_task_master.core.pr_context.console"):
                pr_context_manager.post_comment_replies(123)

        assert not resolve_file.exists()

    def test_handles_reply_posting_error(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
    ) -> None:
        """Test graceful handling when posting reply fails."""
        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "thread_1",
                            "action": "fixed",
                            "message": "Done",
                        }
                    ]
                }
            )
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # First two calls succeed (repo info, get resolved)
                return MagicMock(stdout=json.dumps(make_graphql_response([])))
            # Third call (post reply) fails
            raise subprocess.CalledProcessError(1, "gh")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = side_effect

            with patch("claude_task_master.core.pr_context.console") as mock_console:
                pr_context_manager.post_comment_replies(123)
                mock_console.warning.assert_called()


# =============================================================================
# _post_thread_reply Tests
# =============================================================================


class TestPostThreadReply:
    """Tests for _post_thread_reply method."""

    def test_posts_reply_via_graphql(self, pr_context_manager: PRContextManager) -> None:
        """Test that reply is posted via GraphQL mutation."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()

            pr_context_manager._post_thread_reply("thread_id_123", "Reply body")

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        args = call_args[0][0]

        assert "gh" in args
        assert "graphql" in args
        # Should contain mutation and thread ID
        assert any("mutation" in str(a) for a in args)
        assert any("thread_id_123" in str(a) for a in args)

    def test_raises_on_subprocess_error(self, pr_context_manager: PRContextManager) -> None:
        """Test that subprocess errors are raised."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "gh")

            with pytest.raises(subprocess.CalledProcessError):
                pr_context_manager._post_thread_reply("thread_id", "body")


# =============================================================================
# resolve_thread Tests
# =============================================================================


class TestResolveThread:
    """Tests for resolve_thread method."""

    def test_resolves_thread_via_graphql(self, pr_context_manager: PRContextManager) -> None:
        """Test that thread is resolved via GraphQL mutation."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()

            pr_context_manager.resolve_thread("thread_to_resolve")

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        args = call_args[0][0]

        assert "gh" in args
        assert "graphql" in args
        # Should contain resolve mutation
        assert any("resolveReviewThread" in str(a) for a in args)
        assert any("thread_to_resolve" in str(a) for a in args)

    def test_raises_on_subprocess_error(self, pr_context_manager: PRContextManager) -> None:
        """Test that subprocess errors are raised."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "gh")

            with pytest.raises(subprocess.CalledProcessError):
                pr_context_manager.resolve_thread("thread_id")


# =============================================================================
# _get_resolved_thread_ids Tests
# =============================================================================


class TestGetResolvedThreadIds:
    """Tests for _get_resolved_thread_ids method."""

    def test_returns_resolved_thread_ids(self, pr_context_manager: PRContextManager) -> None:
        """Test that resolved thread IDs are returned."""
        graphql_response = make_graphql_response(
            [
                {"id": "thread_1", "isResolved": True},
                {"id": "thread_2", "isResolved": False},
                {"id": "thread_3", "isResolved": True},
            ]
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="owner/repo\n"),  # repo info
                MagicMock(stdout=json.dumps(graphql_response)),  # graphql query
            ]

            result = pr_context_manager._get_resolved_thread_ids(123)

        assert result == {"thread_1", "thread_3"}
        assert "thread_2" not in result

    def test_returns_empty_on_error(self, pr_context_manager: PRContextManager) -> None:
        """Test that empty set is returned on error."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "gh")

            with patch("claude_task_master.core.pr_context.console"):
                result = pr_context_manager._get_resolved_thread_ids(123)

        assert result == set()

    def test_returns_empty_for_no_threads(self, pr_context_manager: PRContextManager) -> None:
        """Test that empty set is returned when no threads exist."""
        graphql_response = make_graphql_response([])

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="owner/repo\n"),
                MagicMock(stdout=json.dumps(graphql_response)),
            ]

            result = pr_context_manager._get_resolved_thread_ids(123)

        assert result == set()


# =============================================================================
# _is_non_actionable_comment Tests
# =============================================================================


class TestIsNonActionableComment:
    """Tests for _is_non_actionable_comment method."""

    def test_short_comments_are_non_actionable(self, pr_context_manager: PRContextManager) -> None:
        """Test that very short comments are non-actionable."""
        assert pr_context_manager._is_non_actionable_comment("user", "LGTM")
        assert pr_context_manager._is_non_actionable_comment("user", "Thanks!")
        assert pr_context_manager._is_non_actionable_comment("user", "   ")

    def test_regular_comments_are_actionable(self, pr_context_manager: PRContextManager) -> None:
        """Test that regular review comments are actionable."""
        body = "Please fix the error handling in this function"
        assert not pr_context_manager._is_non_actionable_comment("reviewer", body)

    def test_coderabbit_status_comments_non_actionable(
        self, pr_context_manager: PRContextManager
    ) -> None:
        """Test that CodeRabbit status comments are non-actionable."""
        body = "Currently processing your PR..."
        assert pr_context_manager._is_non_actionable_comment("coderabbitai", body)

        body = "Review in progress, please wait."
        assert pr_context_manager._is_non_actionable_comment("coderabbitai", body)

        body = "CodeRabbit is analyzing this pull request"
        assert pr_context_manager._is_non_actionable_comment("coderabbitai", body)

    def test_coderabbit_review_comments_actionable(
        self, pr_context_manager: PRContextManager
    ) -> None:
        """Test that CodeRabbit review comments are actionable."""
        body = "This function has a potential bug. Consider adding null checks."
        assert not pr_context_manager._is_non_actionable_comment("coderabbitai", body)

    def test_coderabbit_walkthrough_comments_non_actionable(
        self, pr_context_manager: PRContextManager
    ) -> None:
        """Test that CodeRabbit walkthrough comments are non-actionable."""
        body = "## Walkthrough\nThis PR adds new features and tests..."
        assert pr_context_manager._is_non_actionable_comment("coderabbitai", body)

    def test_coderabbit_walkthrough_with_fix_actionable(
        self, pr_context_manager: PRContextManager
    ) -> None:
        """Test that walkthrough with proposed fix is actionable."""
        body = "## Walkthrough\nThis has issues.\n\n## Proposed Fix\nChange X to Y"
        assert not pr_context_manager._is_non_actionable_comment("coderabbitai", body)

    def test_github_actions_status_non_actionable(
        self, pr_context_manager: PRContextManager
    ) -> None:
        """Test that GitHub Actions status comments are non-actionable."""
        body = "Currently processing your workflow"
        assert pr_context_manager._is_non_actionable_comment("github-actions", body)

    def test_dependabot_status_non_actionable(self, pr_context_manager: PRContextManager) -> None:
        """Test that Dependabot status comments are non-actionable."""
        body = "Review in progress for this update"
        assert pr_context_manager._is_non_actionable_comment("dependabot", body)

    def test_case_insensitive_bot_matching(self, pr_context_manager: PRContextManager) -> None:
        """Test that bot matching is case insensitive."""
        body = "Currently processing..."
        assert pr_context_manager._is_non_actionable_comment("CodeRabbitAI", body)
        assert pr_context_manager._is_non_actionable_comment("CODERABBITAI", body)

    def test_long_status_messages_from_bots_actionable(
        self, pr_context_manager: PRContextManager
    ) -> None:
        """Test that long status messages from bots are still actionable."""
        # Long messages (>200 chars) with status indicators are still actionable
        body = "Currently processing " + "x" * 200
        assert not pr_context_manager._is_non_actionable_comment("coderabbitai", body)


# =============================================================================
# Action Emoji Mapping Tests
# =============================================================================


class TestActionEmojiMapping:
    """Tests for action emoji mapping in post_comment_replies."""

    @pytest.mark.parametrize(
        "action,expected_emoji",
        [
            ("fixed", "\\u2705"),  # checkmark
            ("explained", "\\ud83d\\udcac"),  # speech bubble
            ("skipped", "\\u23ed\\ufe0f"),  # skip forward
        ],
    )
    def test_action_emoji_mapping(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        action: str,
        expected_emoji: str,
    ) -> None:
        """Test that different actions get correct emojis."""
        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "thread_1",
                            "action": action,
                            "message": "Test message",
                        }
                    ]
                }
            )
        )

        posted_body = None

        def capture_post(*args, **kwargs):
            nonlocal posted_body
            cmd = args[0]
            # Look for body parameter
            for i, arg in enumerate(cmd):
                if arg == "body=" or (isinstance(arg, str) and "body=" in arg):
                    # Extract body from next arg or same arg
                    if "body=" in arg:
                        posted_body = arg.split("body=", 1)[1]
                    elif i + 1 < len(cmd):
                        posted_body = cmd[i + 1]
            return MagicMock(stdout=json.dumps(make_graphql_response([])))

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = capture_post

            with patch("claude_task_master.core.pr_context.console"):
                pr_context_manager.post_comment_replies(123)

        # Verify the action was included in reply
        assert action.capitalize() in (posted_body or "")


# =============================================================================
# Integration Tests
# =============================================================================


class TestPRContextIntegration:
    """Integration tests for PRContextManager."""

    def test_full_comment_workflow(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test full workflow: save comments -> create resolutions -> post replies."""
        # Step 1: Save PR comments
        graphql_response = make_graphql_response(
            [
                {
                    "id": "thread_review",
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {
                                "id": "comment_1",
                                "author": {"login": "reviewer"},
                                "body": "Please add error handling for null values",
                                "path": "src/utils.py",
                                "line": 50,
                            }
                        ]
                    },
                }
            ]
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="owner/repo\n"),
                MagicMock(stdout=json.dumps(graphql_response)),
            ]
            pr_context_manager.save_pr_comments(123)

        # Verify comments were saved
        context = state_manager.load_pr_context(123)
        assert "error handling" in context

        # Step 2: Create resolution file (simulating Claude's response)
        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "thread_review",
                            "action": "fixed",
                            "message": "Added null checks",
                        }
                    ]
                }
            )
        )

        # Step 3: Post replies
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=json.dumps(make_graphql_response([])))

            with patch("claude_task_master.core.pr_context.console"):
                pr_context_manager.post_comment_replies(123)

        # Verify thread was marked as addressed
        addressed = state_manager.get_addressed_threads(123)
        assert "thread_review" in addressed

        # Verify resolve file was deleted
        assert not resolve_file.exists()

    def test_ci_failure_and_comment_workflow(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test saving both CI failures and comments."""
        # Setup CI failure
        mock_github_client.get_failed_run_logs.return_value = "pytest failed"
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[{"name": "tests", "conclusion": "FAILURE"}]
        )

        # Save CI failures
        pr_context_manager.save_ci_failures(123)

        # Setup and save comments
        graphql_response = make_graphql_response(
            [
                {
                    "id": "thread_1",
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {
                                "id": "c1",
                                "author": {"login": "user"},
                                "body": "Review comment text here",
                                "path": "test.py",
                                "line": 1,
                            }
                        ]
                    },
                }
            ]
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="owner/repo\n"),
                MagicMock(stdout=json.dumps(graphql_response)),
            ]
            pr_context_manager.save_pr_comments(123)

        # Verify both are in context
        context = state_manager.load_pr_context(123)
        assert "CI Failures" in context
        assert "pytest failed" in context
        assert "Review Comments" in context
