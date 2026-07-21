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
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.pr_context import PRContextManager
from claude_task_master.core.state import StateManager
from claude_task_master.github.exceptions import GitHubError

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


def make_graphql_response(
    threads: list[dict[str, Any]], viewer: str | None = None
) -> dict[str, Any]:
    """Helper to create a review-threads GraphQL response.

    Each thread dict may include a ``comments`` key carrying last-comment
    author info; pass ``viewer`` to populate the authenticated-user login used
    for bot-last-comment detection in _get_thread_states.
    """
    data: dict[str, Any] = {"repository": {"pullRequest": {"reviewThreads": {"nodes": threads}}}}
    if viewer is not None:
        data["viewer"] = {"login": viewer}
    return {"data": data}


def make_thread_node(
    thread_id: str, is_resolved: bool, last_author: str | None = None
) -> dict[str, Any]:
    """Build a reviewThreads node with an optional last-comment author."""
    node: dict[str, Any] = {"id": thread_id, "isResolved": is_resolved}
    if last_author is not None:
        node["comments"] = {"nodes": [{"author": {"login": last_author}}]}
    return node


def make_rest_comment(
    comment_id: int, user: str, body: str, path: str | None, line: int | None
) -> dict[str, Any]:
    """Helper to create REST API comment format."""
    return {
        "id": comment_id,
        "user": {"login": user},
        "body": body,
        "path": path,
        "line": line,
    }


def comments_to_ndjson(comments: list[dict[str, Any]]) -> str:
    """Convert a list of REST comment dicts to NDJSON format.

    Matches the output of ``gh api --paginate --jq '.[]'`` for the
    PR comments endpoint.
    """
    return "\n".join(json.dumps(c) for c in comments)


def make_resolved_status_response(resolved_map: dict[int, tuple[bool, str]]) -> dict[str, Any]:
    """Helper to create GraphQL resolved status response.

    Args:
        resolved_map: Maps comment_id -> (is_resolved, thread_id)
    """
    # Group by thread_id
    thread_data: dict[str, tuple[bool, list[int]]] = {}
    for comment_id, (is_resolved, thread_id) in resolved_map.items():
        if thread_id not in thread_data:
            thread_data[thread_id] = (is_resolved, [])
        thread_data[thread_id][1].append(comment_id)

    nodes = []
    for thread_id, (is_resolved, comment_ids) in thread_data.items():
        nodes.append(
            {
                "id": thread_id,
                "isResolved": is_resolved,
                "comments": {"nodes": [{"databaseId": cid} for cid in comment_ids]},
            }
        )

    return {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}}}


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
        # Mock PR status with url containing run ID
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[
                {
                    "name": "test-job",
                    "conclusion": "FAILURE",
                    "url": "https://github.com/owner/repo/actions/runs/12345/job/789",
                },
            ]
        )

        # Repo info goes through github_client; CILogDownloader still uses subprocess
        mock_github_client._get_repo_info.return_value = "owner/repo"
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                # gh api .../jobs via --paginate --jq '.jobs[]' → NDJSON
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "id": 1,
                            "name": "test-job",
                            "status": "completed",
                            "conclusion": "failure",
                        }
                    ),
                    stderr="",
                ),
                # gh api .../jobs/1/logs (download logs) — via CILogDownloader
                MagicMock(
                    returncode=0,
                    stdout=b"Test error output\n##[error]Test failed",
                    stderr=b"",
                ),
            ]

            pr_context_manager.save_ci_failures(123, _also_save_comments=False)

        # Verify CI failure was saved in chunked format
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        assert ci_dir.exists()

        # Check for job directory and log file
        job_dir = ci_dir / "test-job"
        assert job_dir.exists()
        log_file = job_dir / "1.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "Test error output" in content

    def test_none_url_check_does_not_abort_run_id_extraction(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """A failing check with "url": None must not abort run-ID extraction.

        Regression: a StatusContext's targetUrl is often null, so the "url"
        key is present-but-None; `"/runs/" in None` raised TypeError and no
        CI logs were downloaded even when another failing check had a valid
        run URL.
        """
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[
                {"name": "external-status", "conclusion": "FAILURE", "url": None},
                {
                    "name": "test-job",
                    "conclusion": "FAILURE",
                    "url": "https://github.com/owner/repo/actions/runs/12345/job/789",
                },
            ]
        )

        mock_github_client._get_repo_info.return_value = "owner/repo"
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "id": 1,
                            "name": "test-job",
                            "status": "completed",
                            "conclusion": "failure",
                        }
                    ),
                    stderr="",
                ),
                MagicMock(returncode=0, stdout=b"Test error\n##[error]failed", stderr=b""),
            ]

            pr_context_manager.save_ci_failures(123, _also_save_comments=False)

        log_file = state_manager.get_pr_dir(123) / "ci" / "test-job" / "1.log"
        assert log_file.exists()
        assert "Test error" in log_file.read_text()

    def test_saves_failure_for_error_conclusion(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that CI failures are saved for ERROR conclusion."""
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[
                {
                    "name": "build-job",
                    "conclusion": "ERROR",
                    "url": "https://github.com/owner/repo/actions/runs/12345/job/789",
                },
            ]
        )

        # Repo info goes through github_client; CILogDownloader still uses subprocess
        mock_github_client._get_repo_info.return_value = "owner/repo"
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                # NDJSON: one job object per line
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "id": 1,
                            "name": "build-job",
                            "status": "completed",
                            "conclusion": "failure",
                        }
                    ),
                    stderr="",
                ),
                MagicMock(returncode=0, stdout=b"Build error\n##[error]Build failed", stderr=b""),
            ]

            pr_context_manager.save_ci_failures(123, _also_save_comments=False)

        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        job_dir = ci_dir / "build-job"
        assert job_dir.exists()
        log_file = job_dir / "1.log"
        assert log_file.exists()

    def test_handles_log_retrieval_failure(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test graceful handling when check details have no run URL (no run_id extracted)."""
        # check_details has no URL → run_id is None → save_ci_failures returns early
        # CILogDownloader is never invoked, so no subprocess calls are made.
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[{"name": "test", "conclusion": "FAILURE"}]
        )

        pr_context_manager.save_ci_failures(123, _also_save_comments=False)

        # Should handle gracefully - CI dir may not have files due to error
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        # Directory might exist but be empty due to the error
        if ci_dir.exists():
            files = list(ci_dir.rglob("*.log"))
            # No files should be saved due to download failure
            assert len(files) == 0

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

    def test_ghost_user_and_none_path_do_not_abort_save(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """A ghost-user comment ("user": null) must not abort the whole save.

        Regression: GitHub sends "user": null for deleted accounts — the key
        is present, so .get("user", {}) returned None and the chained
        .get("login") raised AttributeError, aborting save_pr_comments
        entirely (0 comments saved, review loop spins).
        """
        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = comments_to_ndjson(
            [
                {
                    "id": 1,
                    "user": None,  # ghost/deleted account
                    "body": "This comment still needs to be addressed properly.",
                    "path": None,  # outdated-diff comment
                    "line": None,
                }
            ]
        )
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(make_resolved_status_response({}))
        conv_result = MagicMock()
        conv_result.stdout = comments_to_ndjson(
            [
                {
                    "id": 2,
                    "user": None,  # ghost user on a conversation comment
                    "body": "Please also update the documentation for this.",
                }
            ]
        )
        mock_github_client._run_gh_command.side_effect = [
            rest_result,
            graphql_result,
            conv_result,
        ]

        saved = pr_context_manager.save_pr_comments(123, _also_save_ci=False)

        assert saved == 2
        comments_dir = state_manager.get_pr_dir(123) / "comments"
        contents = [f.read_text() for f in sorted(comments_dir.glob("*.txt"))]
        assert all("Author: unknown" in c for c in contents)

    def test_returns_early_for_none_pr(
        self, pr_context_manager: PRContextManager, mock_github_client: MagicMock
    ) -> None:
        """Test that save_pr_comments returns early when pr_number is None."""
        pr_context_manager.save_pr_comments(None)
        mock_github_client._get_repo_info.assert_not_called()
        mock_github_client._run_gh_command.assert_not_called()

    def test_clears_old_comments_on_successful_fetch(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that old comment files are cleared after a successful fetch.

        Individual comment files in comments/ are deleted.  The summary file
        is also deleted and then recreated fresh by state_manager, so we verify
        old content is gone (the stale file is replaced, not preserved).
        """
        # Setup: create old stale comment data
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True)
        old_file = comments_dir / "old_comment.txt"
        old_file.write_text("Old stale comment")
        summary_file = pr_dir / "comments_summary.txt"
        summary_file.write_text("Stale summary from previous run")

        # Mock a successful empty fetch (REST returns nothing, GraphQL returns no threads)
        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = ""  # empty NDJSON → no comments
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(
            {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
        )
        # 3rd call = conversation (issue-level) comments; empty here.
        mock_github_client._run_gh_command.side_effect = [
            rest_result,
            graphql_result,
            MagicMock(stdout=""),
        ]

        pr_context_manager.save_pr_comments(123, _also_save_ci=False)

        # Old individual comment files must be gone
        assert not old_file.exists()
        # The summary is regenerated by state_manager (old content replaced)
        if summary_file.exists():
            assert "Stale summary from previous run" not in summary_file.read_text()

    def test_preserves_old_comments_on_fetch_failure(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that old comments are preserved when the fetch fails."""
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True)
        old_file = comments_dir / "old_comment.txt"
        old_file.write_text("Old comment")

        mock_github_client._get_repo_info.return_value = "owner/repo"
        mock_github_client._run_gh_command.side_effect = GitHubError("network error")

        pr_context_manager.save_pr_comments(123, _also_save_ci=False)

        # Old file must still exist — fetch failed so we keep the previous data
        assert old_file.exists()

    def test_fetches_and_saves_comments(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test fetching and saving PR comments via REST API + GraphQL."""
        # REST API returns all comments (as NDJSON — one object per line)
        rest_comments = [
            make_rest_comment(
                1, "reviewer", "Please fix this issue in the code.", "src/main.py", 42
            ),
        ]
        # GraphQL returns resolved status
        resolved_response = make_resolved_status_response({1: (False, "thread_1")})

        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = comments_to_ndjson(rest_comments)
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        # 3rd call = conversation (issue-level) comments; empty here.
        mock_github_client._run_gh_command.side_effect = [
            rest_result,
            graphql_result,
            MagicMock(stdout=""),
        ]

        pr_context_manager.save_pr_comments(123, _also_save_ci=False)

        # Verify comments were saved
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        assert comments_dir.exists()

    def test_skips_resolved_threads(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that resolved comments are skipped."""
        # REST API returns all comments (NDJSON)
        rest_comments = [
            make_rest_comment(1, "reviewer", "Already resolved comment", "src/main.py", 42),
            make_rest_comment(
                2, "reviewer", "Unresolved comment needs attention", "src/utils.py", 10
            ),
        ]
        # GraphQL returns resolved status: comment 1 resolved, comment 2 unresolved
        resolved_response = make_resolved_status_response(
            {
                1: (True, "thread_resolved"),
                2: (False, "thread_unresolved"),
            }
        )

        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = comments_to_ndjson(rest_comments)
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        # 3rd call = conversation (issue-level) comments; empty here.
        mock_github_client._run_gh_command.side_effect = [
            rest_result,
            graphql_result,
            MagicMock(stdout=""),
        ]

        pr_context_manager.save_pr_comments(123, _also_save_ci=False)

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
        mock_github_client: MagicMock,
    ) -> None:
        """Test that already-addressed threads are skipped."""
        # Mark a thread as addressed
        state_manager.mark_threads_addressed(123, ["thread_addressed"])

        # REST API returns all comments (NDJSON)
        rest_comments = [
            make_rest_comment(1, "reviewer", "Already addressed comment text", "src/main.py", 42),
            make_rest_comment(
                2, "reviewer", "New comment needs attention here", "src/utils.py", 10
            ),
        ]
        # GraphQL returns resolved status (both unresolved, but one is addressed)
        resolved_response = make_resolved_status_response(
            {
                1: (False, "thread_addressed"),  # This thread was already addressed
                2: (False, "thread_new"),
            }
        )

        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = comments_to_ndjson(rest_comments)
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        # 3rd call = conversation (issue-level) comments; empty here.
        mock_github_client._run_gh_command.side_effect = [
            rest_result,
            graphql_result,
            MagicMock(stdout=""),
        ]

        pr_context_manager.save_pr_comments(123, _also_save_ci=False)

        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comment_files = list(comments_dir.glob("*.txt"))

        # Only new thread's comment should be saved
        assert len(comment_files) == 1
        content = comment_files[0].read_text()
        assert "New comment" in content
        assert "Already addressed" not in content

    def test_handles_gh_command_error(
        self,
        pr_context_manager: PRContextManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test graceful handling of gh command errors."""
        mock_github_client._run_gh_command.side_effect = GitHubError("mock error")

        with patch("claude_task_master.core.pr_context.console") as mock_console:
            pr_context_manager.save_pr_comments(123)
            mock_console.warning.assert_called()


# =============================================================================
# Conversation (issue-level) comment Tests
# =============================================================================


class TestConversationComments:
    """Tests for surfacing PR conversation (issue-level) comments."""

    def _setup(
        self,
        mock_github_client: MagicMock,
        conversation: list[dict[str, Any]],
    ) -> None:
        """Wire the 3 gh calls: empty review comments, empty threads, conversation."""
        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = ""  # no inline review comments
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(make_resolved_status_response({}))
        conv_result = MagicMock()
        conv_result.stdout = comments_to_ndjson(conversation)
        mock_github_client._run_gh_command.side_effect = [
            rest_result,
            graphql_result,
            conv_result,
        ]

    def test_surfaces_actionable_conversation_comment(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that an issue-level 'please also change X' comment is saved."""
        conversation = [
            {
                "id": 999,
                "user": {"login": "human"},
                "body": "Please also add tests for the edge cases.",
            }
        ]
        self._setup(mock_github_client, conversation)

        pr_context_manager.save_pr_comments(123, _also_save_ci=False)

        comments_dir = state_manager.get_pr_dir(123) / "comments"
        files = list(comments_dir.glob("*.txt"))
        assert len(files) == 1
        assert "Please also add tests" in files[0].read_text()

    def test_skips_addressed_conversation_comment(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that a conversation comment already addressed is not re-surfaced."""
        state_manager.mark_threads_addressed(123, ["issue_comment_999"])
        conversation = [
            {
                "id": 999,
                "user": {"login": "human"},
                "body": "Please also add tests for the edge cases.",
            }
        ]
        self._setup(mock_github_client, conversation)

        pr_context_manager.save_pr_comments(123, _also_save_ci=False)

        comments_dir = state_manager.get_pr_dir(123) / "comments"
        assert list(comments_dir.glob("*.txt")) == []

    def test_filters_non_actionable_conversation_comment(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that short/bot conversation comments are filtered out."""
        conversation = [
            {"id": 1, "user": {"login": "human"}, "body": "LGTM"},  # too short
        ]
        self._setup(mock_github_client, conversation)

        pr_context_manager.save_pr_comments(123, _also_save_ci=False)

        comments_dir = state_manager.get_pr_dir(123) / "comments"
        assert list(comments_dir.glob("*.txt")) == []

    def test_conversation_fetch_failure_is_non_fatal(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that a conversation-fetch error doesn't lose review comments."""
        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = comments_to_ndjson(
            [make_rest_comment(1, "reviewer", "Please fix this real issue here.", "a.py", 3)]
        )
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(make_resolved_status_response({1: (False, "thread_1")}))
        # 3rd call (conversation fetch) fails — must be swallowed.
        mock_github_client._run_gh_command.side_effect = [
            rest_result,
            graphql_result,
            GitHubError("conversation fetch failed"),
        ]

        with patch("claude_task_master.core.pr_context.console"):
            pr_context_manager.save_pr_comments(123, _also_save_ci=False)

        comments_dir = state_manager.get_pr_dir(123) / "comments"
        files = list(comments_dir.glob("*.txt"))
        assert len(files) == 1
        assert "Please fix this real issue" in files[0].read_text()


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

    def test_conversation_comment_marked_addressed_without_thread_mutation(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Conversation ids are acknowledged without a review-thread GraphQL call."""
        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "issue_comment_555",
                            "action": "fixed",
                            "message": "Added the requested tests",
                        }
                    ]
                }
            )
        )

        mock_github_client._get_repo_info.return_value = "owner/repo"
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(make_graphql_response([]))
        mock_github_client._run_gh_command.return_value = graphql_result

        with patch("claude_task_master.core.pr_context.console"):
            pr_context_manager.post_comment_replies(123)

        # No reply/resolve mutation issued for a synthetic conversation id.
        all_cmds = [
            call.args[0] for call in mock_github_client._run_gh_command.call_args_list if call.args
        ]
        assert not any("addPullRequestReviewThreadReply" in str(cmd) for cmd in all_cmds)
        assert not any("resolveReviewThread" in str(cmd) for cmd in all_cmds)
        # Marked addressed so it isn't re-surfaced next cycle.
        assert "issue_comment_555" in state_manager.get_addressed_threads(123)

    def test_posts_replies_to_threads(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
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

        # _get_resolved_thread_ids: 1 graphql call
        # _post_thread_reply: 1 mutation call
        # resolve_thread: 1 mutation call
        mock_github_client._get_repo_info.return_value = "owner/repo"
        gh_result = MagicMock()
        gh_result.stdout = json.dumps(make_graphql_response([]))
        mock_github_client._run_gh_command.return_value = gh_result

        with patch("claude_task_master.core.pr_context.console"):
            pr_context_manager.post_comment_replies(123)

        # Verify mutations were called (graphql query + post reply + resolve)
        assert mock_github_client._run_gh_command.call_count >= 2

    def test_posts_reply_but_skips_resolve_for_already_resolved_threads(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that already resolved threads still get a reply but skip resolve."""
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

        mock_github_client._get_repo_info.return_value = "owner/repo"
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        reply_result = MagicMock()
        reply_result.stdout = "{}"
        # 1: get_resolved graphql, 2: post reply (thread already resolved → no 3rd resolve call)
        mock_github_client._run_gh_command.side_effect = [graphql_result, reply_result]

        with patch("claude_task_master.core.pr_context.console"):
            pr_context_manager.post_comment_replies(123)

        # Should have 2 calls: get resolved, post reply
        # No resolve call since thread is already resolved on GitHub
        assert mock_github_client._run_gh_command.call_count == 2

    def test_resolves_thread_on_fixed_action(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
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

        mock_github_client._get_repo_info.return_value = "owner/repo"
        gh_result = MagicMock()
        gh_result.stdout = json.dumps(make_graphql_response([]))
        mock_github_client._run_gh_command.return_value = gh_result

        with patch("claude_task_master.core.pr_context.console"):
            pr_context_manager.post_comment_replies(123)

        # Should have 3 calls: get resolved (graphql query), post reply, resolve thread
        assert mock_github_client._run_gh_command.call_count >= 3

    def test_marks_threads_addressed(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
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

        mock_github_client._get_repo_info.return_value = "owner/repo"
        gh_result = MagicMock()
        gh_result.stdout = json.dumps(make_graphql_response([]))
        mock_github_client._run_gh_command.return_value = gh_result

        with patch("claude_task_master.core.pr_context.console"):
            pr_context_manager.post_comment_replies(123)

        # Verify thread was marked as addressed
        addressed = state_manager.get_addressed_threads(123)
        assert "thread_abc" in addressed

    def test_resolves_thread_on_explained_action(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that threads are resolved when action is 'explained'."""
        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "thread_to_resolve",
                            "action": "explained",
                            "message": "Explained why this is correct",
                        }
                    ]
                }
            )
        )

        mock_github_client._get_repo_info.return_value = "owner/repo"
        gh_result = MagicMock()
        gh_result.stdout = json.dumps(make_graphql_response([]))
        mock_github_client._run_gh_command.return_value = gh_result

        with patch("claude_task_master.core.pr_context.console"):
            pr_context_manager.post_comment_replies(123)

        # Should have at least 3 calls: get resolved (graphql query), post reply, resolve thread
        assert mock_github_client._run_gh_command.call_count >= 3
        # Verify resolveReviewThread was called via _run_gh_command
        all_cmd_args = [
            call.args[0] for call in mock_github_client._run_gh_command.call_args_list if call.args
        ]
        assert any("resolveReviewThread" in str(cmd) for cmd in all_cmd_args)

    def test_deletes_resolve_file_after_processing(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
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

        mock_github_client._get_repo_info.return_value = "owner/repo"
        gh_result = MagicMock()
        gh_result.stdout = json.dumps(make_graphql_response([]))
        mock_github_client._run_gh_command.return_value = gh_result

        with patch("claude_task_master.core.pr_context.console"):
            pr_context_manager.post_comment_replies(123)

        assert not resolve_file.exists()

    def test_handles_reply_posting_error(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
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

        mock_github_client._get_repo_info.return_value = "owner/repo"
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(make_graphql_response([]))
        # First call (_get_resolved_thread_ids) succeeds; second call (_post_thread_reply) fails
        mock_github_client._run_gh_command.side_effect = [
            graphql_result,
            GitHubError("post reply failed"),
        ]

        with patch("claude_task_master.core.pr_context.console") as mock_console:
            pr_context_manager.post_comment_replies(123)
            mock_console.warning.assert_called()


# =============================================================================
# _post_thread_reply Tests
# =============================================================================


class TestPostThreadReply:
    """Tests for _post_thread_reply method."""

    def test_posts_reply_via_graphql(
        self, pr_context_manager: PRContextManager, mock_github_client: MagicMock
    ) -> None:
        """Test that reply is posted via GraphQL mutation through github_client."""
        pr_context_manager._post_thread_reply("thread_id_123", "Reply body")

        mock_github_client._run_gh_command.assert_called_once()
        call_args = mock_github_client._run_gh_command.call_args
        args = call_args[0][0]  # First positional arg is the cmd list

        assert "gh" in args
        assert "graphql" in args
        # Should contain mutation and thread ID
        assert any("mutation" in str(a) for a in args)
        assert any("thread_id_123" in str(a) for a in args)

    def test_raises_on_gh_command_error(
        self, pr_context_manager: PRContextManager, mock_github_client: MagicMock
    ) -> None:
        """Test that gh command errors are raised."""
        mock_github_client._run_gh_command.side_effect = GitHubError("mock error")

        with pytest.raises(GitHubError):
            pr_context_manager._post_thread_reply("thread_id", "body")


# =============================================================================
# resolve_addressed_threads Tests
# =============================================================================


class TestResolveAddressedThreads:
    """Tests for resolve_addressed_threads method."""

    def test_returns_zero_for_none_pr(self, pr_context_manager: PRContextManager) -> None:
        """Test returns 0 when pr_number is None."""
        assert pr_context_manager.resolve_addressed_threads(None) == 0

    def test_resolves_unresolved_addressed_threads(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that addressed threads whose last comment is ours get resolved."""
        # Mark threads as addressed
        state_manager.mark_threads_addressed(123, ["thread_1", "thread_2"])

        # thread_2 is unresolved and our reply ("bot-user") is the last comment.
        resolved_response = make_graphql_response(
            [
                make_thread_node("thread_1", True),  # already resolved
                make_thread_node("thread_2", False, last_author="bot-user"),
            ],
            viewer="bot-user",
        )

        mock_github_client._get_repo_info.return_value = "owner/repo"
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        resolve_result = MagicMock()
        resolve_result.stdout = "{}"
        # 1st call: get thread states graphql; 2nd call: batched resolve of thread_2
        mock_github_client._run_gh_command.side_effect = [graphql_result, resolve_result]

        with patch("claude_task_master.core.pr_context.console"):
            result = pr_context_manager.resolve_addressed_threads(123)

        assert result == 1
        # Should have batch-resolved thread_2 only (2nd _run_gh_command call)
        resolve_call = mock_github_client._run_gh_command.call_args_list[1]
        cmd = resolve_call[0][0]
        assert any("resolveReviewThread" in str(a) for a in cmd)
        assert any("thread_2" in str(a) for a in cmd)

    def test_returns_zero_when_all_already_resolved(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test returns 0 when all addressed threads are already resolved."""
        state_manager.mark_threads_addressed(123, ["thread_1"])

        resolved_response = make_graphql_response([{"id": "thread_1", "isResolved": True}])

        mock_github_client._get_repo_info.return_value = "owner/repo"
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        mock_github_client._run_gh_command.return_value = graphql_result

        with patch("claude_task_master.core.pr_context.console"):
            result = pr_context_manager.resolve_addressed_threads(123)

        assert result == 0

    def test_handles_resolve_failure_gracefully(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that resolve failures are handled gracefully."""
        state_manager.mark_threads_addressed(123, ["thread_1"])

        # thread_1 is bot-last so a resolve is attempted (then fails).
        resolved_response = make_graphql_response(
            [make_thread_node("thread_1", False, last_author="bot-user")],
            viewer="bot-user",
        )

        mock_github_client._get_repo_info.return_value = "owner/repo"
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        # Batched resolve fails, then the per-thread fallback also fails — both
        # must be caught gracefully, resolving nothing.
        mock_github_client._run_gh_command.side_effect = [
            graphql_result,
            GitHubError("batch resolve failed"),
            GitHubError("fallback resolve failed"),
        ]

        with patch("claude_task_master.core.pr_context.console"):
            result = pr_context_manager.resolve_addressed_threads(123)

        assert result == 0

    def test_prunes_thread_when_human_replied_last(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Human re-opened threads are left open and pruned, never force-resolved."""
        state_manager.mark_threads_addressed(123, ["thread_reopened"])

        # Unresolved, but the last comment is a human's (not our bot login).
        resolved_response = make_graphql_response(
            [make_thread_node("thread_reopened", False, last_author="human-reviewer")],
            viewer="bot-user",
        )

        mock_github_client._get_repo_info.return_value = "owner/repo"
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        # Only the states query runs — no resolve mutation for a re-opened thread.
        mock_github_client._run_gh_command.return_value = graphql_result

        with patch("claude_task_master.core.pr_context.console"):
            result = pr_context_manager.resolve_addressed_threads(123)

        assert result == 0
        assert mock_github_client._run_gh_command.call_count == 1
        # Pruned from the addressed set so its new feedback re-surfaces.
        assert "thread_reopened" not in state_manager.get_addressed_threads(123)


class TestPostCommentRepliesResolvesAlreadyAddressed:
    """Tests for how post_comment_replies treats already-addressed threads."""

    def test_skips_already_addressed_thread_deferring_resolution(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Already-addressed threads are skipped, not re-replied or resolved.

        Resolving addressed-but-unresolved threads is handled separately by
        resolve_addressed_threads (which only resolves threads whose last
        comment is ours), so post_comment_replies must not touch them.
        """
        # Mark thread as addressed
        state_manager.mark_threads_addressed(123, ["thread_unresolved"])

        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "thread_unresolved",
                            "action": "fixed",
                            "message": "Already fixed",
                        }
                    ]
                }
            )
        )

        # thread_unresolved is NOT in resolved set
        resolved_response = make_graphql_response([])

        mock_github_client._get_repo_info.return_value = "owner/repo"
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        mock_github_client._run_gh_command.return_value = graphql_result

        with patch("claude_task_master.core.pr_context.console"):
            pr_context_manager.post_comment_replies(123)

        # Only 1 call: get thread states. No reply, no resolve — deferred.
        assert mock_github_client._run_gh_command.call_count == 1
        all_cmds = [
            call.args[0] for call in mock_github_client._run_gh_command.call_args_list if call.args
        ]
        assert not any("resolveReviewThread" in str(cmd) for cmd in all_cmds)

    def test_skips_already_addressed_and_resolved_thread(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that threads already replied to AND resolved are fully skipped."""
        state_manager.mark_threads_addressed(123, ["thread_done"])

        pr_dir = state_manager.get_pr_dir(123)
        resolve_file = pr_dir / "resolve-comments.json"
        resolve_file.write_text(
            json.dumps(
                {
                    "resolutions": [
                        {
                            "thread_id": "thread_done",
                            "action": "fixed",
                            "message": "Done",
                        }
                    ]
                }
            )
        )

        resolved_response = make_graphql_response([{"id": "thread_done", "isResolved": True}])

        mock_github_client._get_repo_info.return_value = "owner/repo"
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        # Only 1 call: get resolved. Thread is already addressed AND resolved → nothing more.
        mock_github_client._run_gh_command.return_value = graphql_result

        with patch("claude_task_master.core.pr_context.console"):
            pr_context_manager.post_comment_replies(123)

        # Only 1 call: get resolved. No reply, no resolve.
        assert mock_github_client._run_gh_command.call_count == 1


# =============================================================================
# resolve_thread Tests
# =============================================================================


class TestResolveThread:
    """Tests for resolve_thread method."""

    def test_resolves_thread_via_graphql(
        self, pr_context_manager: PRContextManager, mock_github_client: MagicMock
    ) -> None:
        """Test that thread is resolved via GraphQL mutation through github_client."""
        pr_context_manager.resolve_thread("thread_to_resolve")

        mock_github_client._run_gh_command.assert_called_once()
        call_args = mock_github_client._run_gh_command.call_args
        args = call_args[0][0]  # First positional arg is the cmd list

        assert "gh" in args
        assert "graphql" in args
        # Should contain resolve mutation
        assert any("resolveReviewThread" in str(a) for a in args)
        assert any("thread_to_resolve" in str(a) for a in args)

    def test_raises_on_gh_command_error(
        self, pr_context_manager: PRContextManager, mock_github_client: MagicMock
    ) -> None:
        """Test that gh command errors are raised."""
        mock_github_client._run_gh_command.side_effect = GitHubError("mock error")

        with pytest.raises(GitHubError):
            pr_context_manager.resolve_thread("thread_id")


# =============================================================================
# _get_resolved_thread_ids Tests
# =============================================================================


class TestGetResolvedThreadIds:
    """Tests for _get_resolved_thread_ids method."""

    def test_returns_resolved_thread_ids(
        self, pr_context_manager: PRContextManager, mock_github_client: MagicMock
    ) -> None:
        """Test that resolved thread IDs are returned."""
        graphql_response = make_graphql_response(
            [
                {"id": "thread_1", "isResolved": True},
                {"id": "thread_2", "isResolved": False},
                {"id": "thread_3", "isResolved": True},
            ]
        )

        mock_github_client._get_repo_info.return_value = "owner/repo"
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(graphql_response)
        mock_github_client._run_gh_command.return_value = graphql_result

        result = pr_context_manager._get_resolved_thread_ids(123)

        assert result == {"thread_1", "thread_3"}
        assert "thread_2" not in result

    def test_returns_empty_on_error(
        self, pr_context_manager: PRContextManager, mock_github_client: MagicMock
    ) -> None:
        """Test that empty set is returned on error."""
        mock_github_client._get_repo_info.side_effect = GitHubError("mock error")

        with patch("claude_task_master.core.pr_context.console"):
            result = pr_context_manager._get_resolved_thread_ids(123)

        assert result == set()

    def test_returns_empty_for_no_threads(
        self, pr_context_manager: PRContextManager, mock_github_client: MagicMock
    ) -> None:
        """Test that empty set is returned when no threads exist."""
        graphql_response = make_graphql_response([])

        mock_github_client._get_repo_info.return_value = "owner/repo"
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(graphql_response)
        mock_github_client._run_gh_command.return_value = graphql_result

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
        "action,expected_prefix",
        [
            ("fixed", "Fixed:"),
            ("explained", "Note:"),
            ("skipped", "Skipped:"),
        ],
    )
    def test_action_emoji_mapping(
        self,
        pr_context_manager: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
        action: str,
        expected_prefix: str,
    ) -> None:
        """Test that different actions get correct prefixes."""
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

        # Capture body from _run_gh_command call for _post_thread_reply
        posted_body = None

        def capture_run_gh(cmd, **kwargs):
            nonlocal posted_body
            # Look for body= in the command args (mutation call for post reply)
            for i, arg in enumerate(cmd):
                if isinstance(arg, str) and "body=" in arg:
                    posted_body = arg.split("body=", 1)[1]
                    break
                elif arg == "-F" and i + 1 < len(cmd) and "body=" in cmd[i + 1]:
                    posted_body = cmd[i + 1].split("body=", 1)[1]
                    break
            result = MagicMock()
            result.stdout = json.dumps(make_graphql_response([]))
            return result

        mock_github_client._get_repo_info.return_value = "owner/repo"
        mock_github_client._run_gh_command.side_effect = capture_run_gh

        with patch("claude_task_master.core.pr_context.console"):
            pr_context_manager.post_comment_replies(123)

        # Verify the action prefix was included in the posted reply body
        assert expected_prefix in (posted_body or "")


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
        # Step 1: Save PR comments using REST API + GraphQL
        rest_comments = [
            make_rest_comment(
                1, "reviewer", "Please add error handling for null values", "src/utils.py", 50
            ),
        ]
        resolved_response = make_resolved_status_response({1: (False, "thread_review")})

        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = comments_to_ndjson(rest_comments)
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        # 3rd call = conversation (issue-level) comments; empty here.
        mock_github_client._run_gh_command.side_effect = [
            rest_result,
            graphql_result,
            MagicMock(stdout=""),
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

        # Step 3: Post replies — reset the mock for the post_comment_replies calls
        mock_github_client._run_gh_command.reset_mock(side_effect=True)
        gh_result = MagicMock()
        gh_result.stdout = json.dumps(make_graphql_response([]))
        mock_github_client._run_gh_command.return_value = gh_result

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
        # Setup CI failure mocks with url
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[
                {
                    "name": "tests",
                    "conclusion": "FAILURE",
                    "url": "https://github.com/owner/repo/actions/runs/12345/job/789",
                }
            ]
        )

        # Save CI failures — repo info goes through github_client, CILogDownloader uses subprocess
        mock_github_client._get_repo_info.return_value = "owner/repo"
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                # gh api .../jobs --paginate --jq '.jobs[]' → NDJSON (one job per line)
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(
                        {"id": 1, "name": "tests", "status": "completed", "conclusion": "failure"}
                    ),
                    stderr="",
                ),
                # gh api .../jobs/1/logs — via CILogDownloader
                MagicMock(returncode=0, stdout=b"pytest failed\n##[error]Test error", stderr=b""),
            ]
            pr_context_manager.save_ci_failures(123, _also_save_comments=False)

        # Setup and save comments using REST API + GraphQL
        rest_comments = [
            make_rest_comment(1, "user", "Review comment text here", "test.py", 1),
        ]
        resolved_response = make_resolved_status_response({1: (False, "thread_1")})

        rest_result = MagicMock()
        rest_result.stdout = comments_to_ndjson(rest_comments)
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(resolved_response)
        # 3rd call = conversation (issue-level) comments; empty here.
        mock_github_client._run_gh_command.side_effect = [
            rest_result,
            graphql_result,
            MagicMock(stdout=""),
        ]
        pr_context_manager.save_pr_comments(123, _also_save_ci=False)

        # Verify both are in context
        context = state_manager.load_pr_context(123)
        assert "CI Failures" in context
        assert "pytest failed" in context or "Test error" in context
        assert "Review Comments" in context
