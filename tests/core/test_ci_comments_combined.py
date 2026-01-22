"""Tests for combined CI failures and PR comments handling.

This module tests that CI failures and PR comments are fetched and handled
together in a single step, avoiding the need for multiple fix cycles.

The key behavior being tested:
1. When CI fails, BOTH CI logs AND PR comments are saved
2. The agent receives a combined task description covering both
3. Single commits can address both CI failures and review comments
"""

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
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that save_ci_failures triggers save_pr_comments by default."""
        # Mock the subprocess calls for comments
        with patch("subprocess.run") as mock_run:
            # First call: get repo info
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="owner/repo",
            )
            # Use side_effect to handle multiple calls
            mock_run.side_effect = [
                # For save_pr_comments -> get repo info
                MagicMock(returncode=0, stdout="owner/repo\n"),
                # For save_pr_comments -> GraphQL query (empty threads)
                MagicMock(
                    returncode=0,
                    stdout='{"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}',
                ),
                # For save_ci_failures -> get_pr_status (handled by mock_github_client)
            ]

            pr_context.save_ci_failures(123)

            # Verify subprocess was called (for comments)
            assert mock_run.call_count >= 2

    def test_save_ci_failures_creates_ci_directory(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that save_ci_failures creates CI failure files."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="owner/repo\n"),
                MagicMock(
                    returncode=0,
                    stdout='{"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}',
                ),
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
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                # For save_ci_failures -> (no subprocess needed, uses mock_github_client)
                MagicMock(returncode=0, stdout="owner/repo\n"),
                MagicMock(
                    returncode=0,
                    stdout='{"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}',
                ),
            ]

            pr_context.save_pr_comments(123)

            # CI failures should have been saved via github_client
            mock_github_client.get_failed_run_logs.assert_called()

    def test_save_pr_comments_no_recursion(
        self,
        pr_context: PRContextManager,
        state_manager: StateManager,
        mock_github_client: MagicMock,
    ) -> None:
        """Test that _also_save_ci=False prevents recursive calls."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="owner/repo\n"),
                MagicMock(
                    returncode=0,
                    stdout='{"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}',
                ),
            ]

            # Reset mock to track only this call
            mock_github_client.get_failed_run_logs.reset_mock()

            pr_context.save_pr_comments(123, _also_save_ci=False)

            # Should not have called get_failed_run_logs
            mock_github_client.get_failed_run_logs.assert_not_called()


class TestGetCombinedFeedback:
    """Tests for the get_combined_feedback method."""

    def test_get_combined_feedback_with_both(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test get_combined_feedback when both CI and comments exist."""
        # Create CI failure file
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True, exist_ok=True)
        (ci_dir / "failed_tests.txt").write_text("Test failure")

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
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True, exist_ok=True)
        (ci_dir / "failed_tests.txt").write_text("Test failure")

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
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True, exist_ok=True)
        (ci_dir / "failed_tests.txt").write_text("Test failure")

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

    def test_save_ci_failures_clears_old_ci(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that save_ci_failures clears old CI logs."""
        # Create old CI file
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True, exist_ok=True)
        old_file = ci_dir / "old_failure.txt"
        old_file.write_text("Old failure")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="owner/repo\n"),
                MagicMock(
                    returncode=0,
                    stdout='{"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}',
                ),
            ]

            pr_context.save_ci_failures(123)

            # Old file should be gone (directory recreated)
            assert not old_file.exists()

    def test_save_pr_comments_clears_old_comments(
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that save_pr_comments clears old comments."""
        # Create old comment file
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True, exist_ok=True)
        old_file = comments_dir / "old_comment.txt"
        old_file.write_text("Old comment")

        # Also create old summary with distinct content
        summary_file = pr_dir / "comments_summary.txt"
        summary_file.write_text("OLD_UNIQUE_CONTENT_MARKER")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="owner/repo\n"),
                MagicMock(
                    returncode=0,
                    stdout='{"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}',
                ),
            ]

            pr_context.save_pr_comments(123, _also_save_ci=False)

            # Old comment file should be gone (comments dir cleared)
            assert not old_file.exists()
            # Summary file should exist but with new content (not the old marker)
            if summary_file.exists():
                content = summary_file.read_text()
                assert "OLD_UNIQUE_CONTENT_MARKER" not in content


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

        mock_github_client.get_failed_run_logs.return_value = """
        FAILED tests/test_main.py::test_addition
        E       AssertionError: 1 + 1 != 3
        """

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="owner/repo\n"),
                MagicMock(
                    returncode=0,
                    stdout="""{
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "reviewThreads": {
                                        "nodes": [
                                            {
                                                "id": "thread_123",
                                                "isResolved": false,
                                                "comments": {
                                                    "nodes": [
                                                        {
                                                            "id": "comment_1",
                                                            "author": {"login": "coderabbitai"},
                                                            "body": "Consider using a constant for this magic number",
                                                            "path": "src/main.py",
                                                            "line": 42
                                                        }
                                                    ]
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    }""",
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
        self, pr_context: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test scenario: CI passes but review comments need addressing."""
        # In this case, we'd normally be in waiting_reviews stage
        # but this tests that comments can be fetched independently

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="owner/repo\n"),
                MagicMock(
                    returncode=0,
                    stdout="""{
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "reviewThreads": {
                                        "nodes": [
                                            {
                                                "id": "thread_456",
                                                "isResolved": false,
                                                "comments": {
                                                    "nodes": [
                                                        {
                                                            "id": "comment_2",
                                                            "author": {"login": "reviewer"},
                                                            "body": "Please add error handling here",
                                                            "path": "src/handler.py",
                                                            "line": 100
                                                        }
                                                    ]
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    }""",
                ),
            ]

            # Save only comments (no CI failures)
            count = pr_context.save_pr_comments(123, _also_save_ci=False)

            assert count == 1
            assert pr_context.has_pr_comments(123) is True
            assert pr_context.has_ci_failures(123) is False
