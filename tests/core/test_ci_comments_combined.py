"""Tests for combined CI failures and PR comments handling.

This module tests that CI failures and PR comments are fetched and handled
together in a single step, avoiding the need for multiple fix cycles.

The key behavior being tested:
1. When CI fails, BOTH CI logs AND PR comments are saved
2. The agent receives a combined task description covering both
3. Single commits can address both CI failures and review comments
"""

import json
import shutil
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.pr_context import PRContextManager
from claude_task_master.core.state import StateManager


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
    mock = MagicMock()
    mock.get_failed_run_logs.return_value = "Test failure: AssertionError in test_main.py"
    mock.get_pr_status.return_value = MagicMock(
        base_branch="main",
        check_details=[
            {"name": "tests", "conclusion": "FAILURE", "status": "COMPLETED"},
        ],
    )
    return mock


@pytest.fixture
def pr_context(state_manager: StateManager, mock_github_client: MagicMock) -> PRContextManager:
    """Create a PRContextManager instance."""
    return PRContextManager(state_manager=state_manager, github_client=mock_github_client)


class TestSaveCIFailuresAlsoSavesComments:
    """Tests that save_ci_failures also saves PR comments."""

    def test_save_ci_failures_calls_save_pr_comments(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that save_ci_failures triggers save_pr_comments by default."""
        # Mock PR status with detailsUrl
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[
                {
                    "name": "test",
                    "conclusion": "FAILURE",
                    "url": "https://github.com/owner/repo/actions/runs/12345/job/789",
                }
            ]
        )

        # Repo info goes through github_client; CILogDownloader still uses subprocess directly.
        # save_pr_comments REST + GraphQL calls go through _run_gh_command.
        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = ""  # no review comments (empty NDJSON)
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(
            {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
        )
        mock_github_client._run_gh_command.side_effect = [rest_result, graphql_result]

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                # CILogDownloader -> gh api --paginate --jq .jobs[] .../jobs (NDJSON)
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "id": 1,
                            "name": "test",
                            "status": "completed",
                            "conclusion": "failure",
                        }
                    ),
                    stderr="",
                ),
                # CILogDownloader -> gh api .../jobs/1/logs
                MagicMock(returncode=0, stdout=b"Test logs", stderr=b""),
            ]

            pr_context.save_ci_failures(123)

            # CILogDownloader used subprocess; comments went through _run_gh_command
            assert mock_run.call_count >= 2
            assert mock_github_client._run_gh_command.call_count >= 2

    def test_save_ci_failures_creates_ci_directory(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that save_ci_failures creates CI failure files."""
        # Mock PR status with detailsUrl
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[
                {
                    "name": "test",
                    "conclusion": "FAILURE",
                    "url": "https://github.com/owner/repo/actions/runs/12345/job/789",
                }
            ]
        )

        # Repo info + comments go through github_client; CILogDownloader uses subprocess directly.
        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = ""  # no review comments (empty NDJSON)
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(
            {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
        )
        mock_github_client._run_gh_command.side_effect = [rest_result, graphql_result]

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                # CILogDownloader -> gh api --paginate --jq .jobs[] .../jobs (NDJSON)
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "id": 1,
                            "name": "test",
                            "status": "completed",
                            "conclusion": "failure",
                        }
                    ),
                    stderr="",
                ),
                # CILogDownloader -> gh api .../jobs/1/logs
                MagicMock(returncode=0, stdout=b"Test logs", stderr=b""),
            ]

            pr_context.save_ci_failures(123)

            pr_dir = state_manager.get_pr_dir(123)
            ci_dir = pr_dir / "ci"
            assert ci_dir.exists()

    def test_save_ci_failures_no_recursion(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that _also_save_comments=False prevents recursive calls."""
        with patch("subprocess.run") as mock_run:
            # When _also_save_comments=False, save_pr_comments should NOT be called
            pr_context.save_ci_failures(123, _also_save_comments=False)

            # Should not have called subprocess (no comment fetching)
            # The only calls should be for CI logs
            for call in mock_run.call_args_list:
                args = call[0][0] if call[0] else []
                # Should not have GraphQL calls for comments
                if "graphql" in args:
                    pytest.fail("Should not call GraphQL when _also_save_comments=False")


class TestSavePRCommentsAlsoSavesCI:
    """Tests that save_pr_comments also saves CI failures."""

    def test_save_pr_comments_calls_save_ci_failures(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that save_pr_comments triggers save_ci_failures by default."""
        # Setup mock to have CI failures with detailsUrl
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[
                {
                    "name": "test",
                    "conclusion": "FAILURE",
                    "url": "https://github.com/owner/repo/actions/runs/12345/job/789",
                }
            ]
        )

        # Repo info + comments go through github_client; CILogDownloader uses subprocess directly.
        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = ""  # no review comments (empty NDJSON)
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(
            {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
        )
        mock_github_client._run_gh_command.side_effect = [rest_result, graphql_result]

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                # CILogDownloader -> gh api --paginate --jq .jobs[] .../jobs (NDJSON)
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "id": 1,
                            "name": "test",
                            "status": "completed",
                            "conclusion": "failure",
                        }
                    ),
                    stderr="",
                ),
                # CILogDownloader -> gh api .../jobs/1/logs
                MagicMock(returncode=0, stdout=b"Test logs", stderr=b""),
            ]

            pr_context.save_pr_comments(123)

            # Verify get_pr_status was called (CI save was triggered)
            mock_github_client.get_pr_status.assert_called()

    def test_save_pr_comments_no_recursion(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that _also_save_ci=False prevents recursive calls."""
        # All gh calls go through github_client (no subprocess for comments path)
        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = ""  # no review comments (empty NDJSON)
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(
            {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
        )
        mock_github_client._run_gh_command.side_effect = [rest_result, graphql_result]

        # Reset mock to track only this call
        mock_github_client.get_pr_status.reset_mock()

        pr_context.save_pr_comments(123, _also_save_ci=False)

        # Should not have called get_pr_status (CI save was skipped)
        mock_github_client.get_pr_status.assert_not_called()


class TestGetCombinedFeedback:
    """Tests for the get_combined_feedback method."""

    def test_get_combined_feedback_with_both(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test get_combined_feedback when both CI and comments exist."""
        # Create CI failure file in new chunked structure
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci" / "Tests"
        ci_dir.mkdir(parents=True, exist_ok=True)
        (ci_dir / "1.log").write_text("Test failure")

        # Create comments file
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True, exist_ok=True)
        (comments_dir / "comment_1.txt").write_text("Please fix this")

        has_ci, has_comments, pr_dir_path = pr_context.get_combined_feedback(123)

        assert has_ci is True
        assert has_comments is True
        assert "123" in pr_dir_path

    def test_get_combined_feedback_with_ci_only(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test get_combined_feedback when only CI failures exist."""
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci" / "Tests"
        ci_dir.mkdir(parents=True, exist_ok=True)
        (ci_dir / "1.log").write_text("Test failure")

        has_ci, has_comments, pr_dir_path = pr_context.get_combined_feedback(123)

        assert has_ci is True
        assert has_comments is False

    def test_get_combined_feedback_with_comments_only(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test get_combined_feedback when only comments exist."""
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True, exist_ok=True)
        (comments_dir / "comment_1.txt").write_text("Please fix this")

        has_ci, has_comments, pr_dir_path = pr_context.get_combined_feedback(123)

        assert has_ci is False
        assert has_comments is True

    def test_get_combined_feedback_with_neither(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test get_combined_feedback when neither CI nor comments exist."""
        has_ci, has_comments, pr_dir_path = pr_context.get_combined_feedback(123)

        assert has_ci is False
        assert has_comments is False

    def test_get_combined_feedback_with_none_pr(self, pr_context: PRContextManager) -> None:
        """Test get_combined_feedback with None PR number."""
        has_ci, has_comments, pr_dir_path = pr_context.get_combined_feedback(None)

        assert has_ci is False
        assert has_comments is False
        assert pr_dir_path == ""


class TestHasCIFailures:
    """Tests for the has_ci_failures method."""

    def test_has_ci_failures_true(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test has_ci_failures returns True when CI files exist."""
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci" / "Tests"
        ci_dir.mkdir(parents=True, exist_ok=True)
        (ci_dir / "1.log").write_text("Test failure")

        assert pr_context.has_ci_failures(123) is True

    def test_has_ci_failures_false(self, pr_context: PRContextManager) -> None:
        """Test has_ci_failures returns False when no CI files exist."""
        assert pr_context.has_ci_failures(123) is False

    def test_has_ci_failures_with_none(self, pr_context: PRContextManager) -> None:
        """Test has_ci_failures returns False for None PR number."""
        assert pr_context.has_ci_failures(None) is False

    def test_has_ci_failures_empty_directory(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test has_ci_failures returns False when CI directory is empty."""
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True, exist_ok=True)
        # Directory exists but no files

        assert pr_context.has_ci_failures(123) is False


class TestHasPRComments:
    """Tests for the has_pr_comments method."""

    def test_has_pr_comments_true(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test has_pr_comments returns True when comment files exist."""
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True, exist_ok=True)
        (comments_dir / "comment_1.txt").write_text("Review comment")

        assert pr_context.has_pr_comments(123) is True

    def test_has_pr_comments_false(self, pr_context: PRContextManager) -> None:
        """Test has_pr_comments returns False when no comment files exist."""
        assert pr_context.has_pr_comments(123) is False

    def test_has_pr_comments_with_none(self, pr_context: PRContextManager) -> None:
        """Test has_pr_comments returns False for None PR number."""
        assert pr_context.has_pr_comments(None) is False

    def test_has_pr_comments_empty_directory(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test has_pr_comments returns False when comments directory is empty."""
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True, exist_ok=True)
        # Directory exists but no files

        assert pr_context.has_pr_comments(123) is False


class TestWorkflowStagesCombinedHandling:
    """Tests for WorkflowStageHandler combined CI + comments handling."""

    @pytest.fixture
    def mock_agent(self) -> MagicMock:
        """Create a mock agent wrapper."""
        mock = MagicMock()
        mock.run_work_session = MagicMock()
        return mock

    @pytest.fixture
    def mock_workflow_state(self) -> MagicMock:
        """Create a mock task state."""
        mock = MagicMock()
        mock.current_pr = 123
        mock.session_count = 1
        return mock

    def test_build_combined_task_description_both(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that task description includes both CI and comments when present."""
        from claude_task_master.core.workflow_stages import WorkflowStageHandler

        # Set up both CI and comments
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True, exist_ok=True)
        (ci_dir / "failed_tests.txt").write_text("Test failure")

        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True, exist_ok=True)
        (comments_dir / "comment_1.txt").write_text("Please fix this")

        # Create handler (agent and github_client can be mocks for this test)
        handler = WorkflowStageHandler(
            agent=MagicMock(),
            state_manager=state_manager,
            github_client=MagicMock(),
            pr_context=pr_context,
        )

        # Build task description
        task = handler._build_combined_ci_comments_task(
            pr_number=123,
            has_ci=True,
            has_comments=True,
            pr_dir_path=str(pr_dir),
        )

        # Verify both are included
        assert "CI has failed" in task
        assert "review comments" in task.lower()
        assert "Fix BOTH" in task
        assert "ci/" in task
        assert "comments/" in task

    def test_build_combined_task_description_ci_only(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that task description handles CI only case."""
        from claude_task_master.core.workflow_stages import WorkflowStageHandler

        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True, exist_ok=True)
        (ci_dir / "failed_tests.txt").write_text("Test failure")

        handler = WorkflowStageHandler(
            agent=MagicMock(),
            state_manager=state_manager,
            github_client=MagicMock(),
            pr_context=pr_context,
        )

        task = handler._build_combined_ci_comments_task(
            pr_number=123,
            has_ci=True,
            has_comments=False,
            pr_dir_path=str(pr_dir),
        )

        assert "CI has failed" in task
        assert "Fix BOTH" not in task
        assert "ci/" in task

    def test_build_combined_task_description_comments_only(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that task description handles comments only case."""
        from claude_task_master.core.workflow_stages import WorkflowStageHandler

        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True, exist_ok=True)
        (comments_dir / "comment_1.txt").write_text("Please fix this")

        handler = WorkflowStageHandler(
            agent=MagicMock(),
            state_manager=state_manager,
            github_client=MagicMock(),
            pr_context=pr_context,
        )

        task = handler._build_combined_ci_comments_task(
            pr_number=123,
            has_ci=False,
            has_comments=True,
            pr_dir_path=str(pr_dir),
        )

        assert "review comments" in task.lower()
        assert "CI has failed" not in task
        assert "comments/" in task

    def test_build_combined_task_description_neither(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that task description handles neither case."""
        from claude_task_master.core.workflow_stages import WorkflowStageHandler

        handler = WorkflowStageHandler(
            agent=MagicMock(),
            state_manager=state_manager,
            github_client=MagicMock(),
            pr_context=pr_context,
        )

        task = handler._build_combined_ci_comments_task(
            pr_number=123,
            has_ci=False,
            has_comments=False,
            pr_dir_path="",
        )

        # Should still produce a valid task
        assert "PR #123" in task


class TestClearingOldData:
    """Tests that old CI and comment data is cleared when saving new data."""

    def test_save_ci_failures_clears_old_ci_after_successful_fetch(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that save_ci_failures clears stale CI logs after a successful fetch.

        Clearing happens AFTER the fetch succeeds so existing data is
        preserved if the GitHub API call fails (new "clear-after" semantics).
        """
        # Create stale CI file
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True, exist_ok=True)
        old_file = ci_dir / "old_failure.txt"
        old_file.write_text("Old failure")

        # PR status has a failing check WITH a URL containing a valid run ID
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[
                {
                    "name": "test",
                    "conclusion": "FAILURE",
                    "url": "https://github.com/owner/repo/actions/runs/99999/job/1",
                }
            ]
        )
        mock_github_client._get_repo_info.return_value = "owner/repo"

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                # CILogDownloader -> gh api --paginate --jq .jobs[] (NDJSON)
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(
                        {"id": 1, "name": "test", "status": "completed", "conclusion": "failure"}
                    ),
                    stderr="",
                ),
                # CILogDownloader -> gh api .../jobs/1/logs
                MagicMock(returncode=0, stdout=b"##[error]Build failed", stderr=b""),
            ]

            pr_context.save_ci_failures(123, _also_save_comments=False)

            # Old file should be gone — cleared before writing new logs
            assert not old_file.exists()

    def test_save_ci_failures_preserves_old_ci_when_no_run_id(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that stale CI logs are preserved when no run ID can be extracted.

        If the failing check has no URL (or an unrecognised URL format), we
        return early without clearing so the operator can still see the last
        known failure logs.
        """
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True, exist_ok=True)
        old_file = ci_dir / "old_failure.txt"
        old_file.write_text("Old failure")

        # Failing check but NO URL → can't extract run ID
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[{"name": "tests", "conclusion": "FAILURE", "status": "COMPLETED"}]
        )

        pr_context.save_ci_failures(123, _also_save_comments=False)

        # Old data must be preserved — we never got a valid run ID to fetch with
        assert old_file.exists()

    def test_save_pr_comments_clears_old_comments_after_successful_fetch(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that save_pr_comments clears stale comment files after a successful fetch.

        Clearing happens AFTER the fetch succeeds so existing data is
        preserved if the GitHub API call fails (new "clear-after" semantics).
        """
        # Create old stale data
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True, exist_ok=True)
        old_file = comments_dir / "old_comment.txt"
        old_file.write_text("Old comment")
        summary_file = pr_dir / "comments_summary.txt"
        summary_file.write_text("OLD_UNIQUE_CONTENT_MARKER")

        # Properly mock _get_repo_info and _run_gh_command for a successful empty fetch
        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        rest_result.stdout = ""  # empty NDJSON → no comments
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {"pageInfo": {"hasNextPage": False}, "nodes": []}
                        }
                    }
                }
            }
        )
        mock_github_client._run_gh_command.side_effect = [rest_result, graphql_result]

        pr_context.save_pr_comments(123, _also_save_ci=False)

        # Old individual comment files should be gone
        assert not old_file.exists()
        # Old summary marker should be gone (replaced by new empty summary)
        if summary_file.exists():
            assert "OLD_UNIQUE_CONTENT_MARKER" not in summary_file.read_text()

    def test_save_pr_comments_preserves_old_comments_on_fetch_failure(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that stale comments are preserved when the fetch fails."""
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True, exist_ok=True)
        old_file = comments_dir / "old_comment.txt"
        old_file.write_text("Old comment")

        mock_github_client._get_repo_info.side_effect = Exception("API unavailable")

        pr_context.save_pr_comments(123, _also_save_ci=False)

        # Old data must be preserved — fetch failed
        assert old_file.exists()


class TestErrorHandling:
    """Tests for error handling in combined CI + comments scenarios."""

    def test_save_ci_failures_handles_comment_errors(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that CI failures are saved even if comment saving fails."""
        with patch("subprocess.run") as mock_run:
            # Make comment fetching fail
            mock_run.side_effect = Exception("Network error")

            # Should not raise - should handle error gracefully
            pr_context.save_ci_failures(123)

    def test_save_pr_comments_handles_ci_errors(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that comments are saved even if CI saving fails."""
        # Make CI fetching fail
        mock_github_client.get_failed_run_logs.side_effect = Exception("API error")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="owner/repo\n"),
                MagicMock(
                    returncode=0,
                    stdout='{"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}',
                ),
            ]

            # Should not raise - should handle error gracefully
            count = pr_context.save_pr_comments(123)

            # Should return 0 comments (no threads in mock response)
            assert count == 0

    def test_get_combined_feedback_handles_missing_pr_dir(
        self, pr_context: PRContextManager
    ) -> None:
        """Test get_combined_feedback handles missing PR directory gracefully."""
        # PR 999 has never had any data saved
        has_ci, has_comments, pr_dir_path = pr_context.get_combined_feedback(999)

        # Should return False for both without raising
        assert has_ci is False
        assert has_comments is False


class TestIntegrationScenarios:
    """Integration tests for realistic CI + comments scenarios."""

    def test_full_ci_failure_with_coderabbit_comments(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test realistic scenario: CI fails, CodeRabbit has left comments."""
        # Simulate a PR where:
        # 1. Tests are failing
        # 2. CodeRabbit has left actionable comments

        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[
                {
                    "name": "test",
                    "conclusion": "FAILURE",
                    "url": "https://github.com/owner/repo/actions/runs/12345/job/789",
                }
            ]
        )

        # Repo info + comments go through github_client; CILogDownloader uses subprocess directly.
        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        # NDJSON: one comment object per line (matches --paginate --jq '.[]')
        rest_result.stdout = json.dumps(
            {
                "id": 123456,
                "user": {"login": "coderabbitai"},
                "body": "Consider using a constant for this magic number",
                "path": "src/main.py",
                "line": 42,
            }
        )
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False},
                                "nodes": [
                                    {
                                        "id": "thread_123",
                                        "isResolved": False,
                                        "comments": {"nodes": [{"databaseId": 123456}]},
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        )
        mock_github_client._run_gh_command.side_effect = [rest_result, graphql_result]

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                # CILogDownloader -> gh api --paginate --jq '.jobs[]' (NDJSON: one job per line)
                MagicMock(
                    returncode=0,
                    stdout=json.dumps(
                        {"id": 1, "name": "test", "status": "completed", "conclusion": "failure"}
                    ),
                    stderr="",
                ),
                # CILogDownloader -> gh api .../jobs/1/logs
                MagicMock(
                    returncode=0,
                    stdout=b"FAILED tests/test_main.py::test_addition\nE       AssertionError: 1 + 1 != 3\n",
                    stderr=b"",
                ),
            ]

            # Save CI failures (should also save comments)
            pr_context.save_ci_failures(123)

            # Verify both exist
            assert pr_context.has_ci_failures(123) is True
            assert pr_context.has_pr_comments(123) is True

            # Verify get_combined_feedback returns both
            has_ci, has_comments, pr_dir_path = pr_context.get_combined_feedback(123)
            assert has_ci is True
            assert has_comments is True

    def test_ci_passes_but_comments_exist(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test scenario: CI passes but review comments need addressing."""
        # In this case, we'd normally be in waiting_reviews stage
        # but this tests that comments can be fetched independently

        # All gh calls go through github_client (no subprocess for comments path)
        mock_github_client._get_repo_info.return_value = "owner/repo"
        rest_result = MagicMock()
        # NDJSON: one comment object per line (matches --paginate --jq '.[]')
        rest_result.stdout = json.dumps(
            {
                "id": 789012,
                "user": {"login": "reviewer"},
                "body": "Please add error handling here",
                "path": "src/handler.py",
                "line": 100,
            }
        )
        graphql_result = MagicMock()
        graphql_result.stdout = json.dumps(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False},
                                "nodes": [
                                    {
                                        "id": "thread_456",
                                        "isResolved": False,
                                        "comments": {"nodes": [{"databaseId": 789012}]},
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        )
        mock_github_client._run_gh_command.side_effect = [rest_result, graphql_result]

        # Save only comments (no CI failures)
        count = pr_context.save_pr_comments(123, _also_save_ci=False)

        assert count == 1
        assert pr_context.has_pr_comments(123) is True
        assert pr_context.has_ci_failures(123) is False
