"""Tests for CI failures + review comments combined handling.

This module tests the bug fix where CI failures AND review comments should be
fetched and addressed together in one step, rather than requiring multiple
fix cycles.

Tests cover:
- CI failures are saved together with comments
- Combined task description is generated correctly
- Different feedback combinations are handled properly
- Edge cases (only CI, only comments, neither)
"""

from __future__ import annotations

import shutil
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.pr_context import PRContextManager
from claude_task_master.core.state import StateManager, TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

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


@pytest.fixture
def mock_agent() -> MagicMock:
    """Create a mock agent wrapper."""
    agent = MagicMock()
    agent.run_work_session = MagicMock(return_value={"output": "Fixed", "success": True})
    return agent


@pytest.fixture
def workflow_handler(
    mock_agent: MagicMock,
    state_manager: StateManager,
    mock_github_client: MagicMock,
    pr_context_manager: PRContextManager,
) -> WorkflowStageHandler:
    """Create a WorkflowStageHandler instance with mocks."""
    return WorkflowStageHandler(
        agent=mock_agent,
        state_manager=state_manager,
        github_client=mock_github_client,
        pr_context=pr_context_manager,
    )


@pytest.fixture
def sample_task_options() -> dict:
    """Sample task options for testing."""
    return {
        "auto_merge": True,
        "max_sessions": 10,
        "pause_on_pr": False,
    }


@pytest.fixture
def basic_task_state(sample_task_options: dict) -> TaskState:
    """Create a basic task state for testing."""
    now = datetime.now().isoformat()
    options = TaskOptions(**sample_task_options)
    return TaskState(
        status="working",
        workflow_stage="ci_failed",
        current_task_index=0,
        session_count=1,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=options,
        current_pr=42,
    )


# =============================================================================
# Test has_pr_comments and has_ci_failures methods
# =============================================================================


class TestHasPRComments:
    """Tests for has_pr_comments method."""

    def test_returns_false_for_none_pr(self, pr_context_manager: PRContextManager) -> None:
        """Test that has_pr_comments returns False when pr_number is None."""
        result = pr_context_manager.has_pr_comments(None)
        assert result is False

    def test_returns_false_when_no_comments_dir(
        self, pr_context_manager: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that has_pr_comments returns False when comments directory doesn't exist."""
        state_manager.get_pr_dir(123)  # Create PR dir but not comments dir
        result = pr_context_manager.has_pr_comments(123)
        assert result is False

    def test_returns_false_when_comments_dir_empty(
        self, pr_context_manager: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that has_pr_comments returns False when comments directory is empty."""
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True)
        result = pr_context_manager.has_pr_comments(123)
        assert result is False

    def test_returns_true_when_comments_exist(
        self, pr_context_manager: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that has_pr_comments returns True when comment files exist."""
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True)
        (comments_dir / "comment_1.txt").write_text("Test comment")

        result = pr_context_manager.has_pr_comments(123)
        assert result is True


class TestHasCIFailures:
    """Tests for has_ci_failures method."""

    def test_returns_false_for_none_pr(self, pr_context_manager: PRContextManager) -> None:
        """Test that has_ci_failures returns False when pr_number is None."""
        result = pr_context_manager.has_ci_failures(None)
        assert result is False

    def test_returns_false_when_no_ci_dir(
        self, pr_context_manager: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that has_ci_failures returns False when ci directory doesn't exist."""
        state_manager.get_pr_dir(123)  # Create PR dir but not ci dir
        result = pr_context_manager.has_ci_failures(123)
        assert result is False

    def test_returns_false_when_ci_dir_empty(
        self, pr_context_manager: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that has_ci_failures returns False when ci directory is empty."""
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True)
        result = pr_context_manager.has_ci_failures(123)
        assert result is False

    def test_returns_true_when_ci_failures_exist(
        self, pr_context_manager: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that has_ci_failures returns True when CI failure files exist."""
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True)
        (ci_dir / "failed_tests.txt").write_text("Test failure")

        result = pr_context_manager.has_ci_failures(123)
        assert result is True


# =============================================================================
# Test get_combined_feedback method
# =============================================================================


class TestGetCombinedFeedback:
    """Tests for get_combined_feedback method."""

    def test_returns_false_false_empty_for_none_pr(
        self, pr_context_manager: PRContextManager
    ) -> None:
        """Test that get_combined_feedback returns (False, False, '') for None PR."""
        has_ci, has_comments, path = pr_context_manager.get_combined_feedback(None)
        assert has_ci is False
        assert has_comments is False
        assert path == ""

    def test_returns_correct_flags_for_ci_only(
        self, pr_context_manager: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test flags when only CI failures exist."""
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True)
        (ci_dir / "failed_tests.txt").write_text("Test failure")

        has_ci, has_comments, path = pr_context_manager.get_combined_feedback(123)
        assert has_ci is True
        assert has_comments is False
        assert str(pr_dir) == path

    def test_returns_correct_flags_for_comments_only(
        self, pr_context_manager: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test flags when only comments exist."""
        pr_dir = state_manager.get_pr_dir(123)
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True)
        (comments_dir / "comment_1.txt").write_text("Comment")

        has_ci, has_comments, path = pr_context_manager.get_combined_feedback(123)
        assert has_ci is False
        assert has_comments is True
        assert str(pr_dir) == path

    def test_returns_correct_flags_for_both(
        self, pr_context_manager: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test flags when both CI failures and comments exist."""
        pr_dir = state_manager.get_pr_dir(123)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True)
        (ci_dir / "failed_tests.txt").write_text("Test failure")
        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True)
        (comments_dir / "comment_1.txt").write_text("Comment")

        has_ci, has_comments, path = pr_context_manager.get_combined_feedback(123)
        assert has_ci is True
        assert has_comments is True
        assert str(pr_dir) == path


# =============================================================================
# Test _build_combined_ci_comments_task method
# =============================================================================


class TestBuildCombinedCICommentsTask:
    """Tests for _build_combined_ci_comments_task method."""

    def test_ci_only_task_description(self, workflow_handler: WorkflowStageHandler) -> None:
        """Test task description when only CI failures exist."""
        task = workflow_handler._build_combined_ci_comments_task(
            pr_number=42, has_ci=True, has_comments=False, pr_dir_path="/tmp/pr/42"
        )

        # Should mention CI failures
        assert "CI has failed" in task
        assert "PR #42" in task
        assert "/tmp/pr/42/ci/" in task

        # Should NOT mention comments
        assert "review comments" not in task.lower()
        assert "resolve-comments.json" not in task

    def test_comments_only_task_description(self, workflow_handler: WorkflowStageHandler) -> None:
        """Test task description when only comments exist."""
        task = workflow_handler._build_combined_ci_comments_task(
            pr_number=42, has_ci=False, has_comments=True, pr_dir_path="/tmp/pr/42"
        )

        # Should mention comments
        assert "review comments" in task.lower()
        assert "PR #42" in task
        assert "/tmp/pr/42/comments/" in task
        assert "resolve-comments.json" in task

        # Should NOT mention CI failures
        assert "CI has failed" not in task

    def test_combined_ci_and_comments_task_description(
        self, workflow_handler: WorkflowStageHandler
    ) -> None:
        """Test task description when both CI failures and comments exist."""
        task = workflow_handler._build_combined_ci_comments_task(
            pr_number=42, has_ci=True, has_comments=True, pr_dir_path="/tmp/pr/42"
        )

        # Should mention both
        assert "CI has failed" in task
        assert "review comments" in task.lower()
        assert "PR #42" in task
        assert "/tmp/pr/42/ci/" in task
        assert "/tmp/pr/42/comments/" in task
        assert "resolve-comments.json" in task

        # Should emphasize doing both in one step
        assert "BOTH" in task or "both" in task
        assert (
            "single session" in task.lower()
            or "one step" in task.lower()
            or "together" in task.lower()
        )

    def test_neither_ci_nor_comments_task_description(
        self, workflow_handler: WorkflowStageHandler
    ) -> None:
        """Test task description when neither CI failures nor comments exist."""
        task = workflow_handler._build_combined_ci_comments_task(
            pr_number=42, has_ci=False, has_comments=False, pr_dir_path="/tmp/pr/42"
        )

        # Should be a generic check message
        assert "PR #42" in task
        assert "needs attention" in task.lower() or "check" in task.lower()

    def test_task_description_mentions_priority(
        self, workflow_handler: WorkflowStageHandler
    ) -> None:
        """Test that combined task mentions CI has priority."""
        task = workflow_handler._build_combined_ci_comments_task(
            pr_number=42, has_ci=True, has_comments=True, pr_dir_path="/tmp/pr/42"
        )

        # Should mention priority for CI first
        assert "Priority 1" in task or "priority" in task.lower()


# =============================================================================
# Test handle_ci_failed_stage integration
# =============================================================================


class TestHandleCIFailedStageIntegration:
    """Integration tests for handle_ci_failed_stage with combined feedback."""

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_fetches_both_ci_and_comments(
        self,
        mock_console: MagicMock,
        mock_sleep: MagicMock,
        workflow_handler: WorkflowStageHandler,
        state_manager: StateManager,
        basic_task_state: TaskState,
        mock_github_client: MagicMock,
        mock_agent: MagicMock,
    ) -> None:
        """Test that handle_ci_failed_stage fetches both CI failures and comments."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_sleep.return_value = True

        # Setup: CI failure exists
        mock_github_client.get_pr_status.return_value = MagicMock(
            check_details=[{"name": "tests", "conclusion": "FAILURE"}]
        )

        with patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feature/fix"):
            workflow_handler.handle_ci_failed_stage(basic_task_state)

        # The save_ci_failures method internally calls save_pr_comments
        # We just verify the workflow completes successfully
        mock_agent.run_work_session.assert_called_once()

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_task_description_includes_both_when_present(
        self,
        mock_console: MagicMock,
        mock_sleep: MagicMock,
        workflow_handler: WorkflowStageHandler,
        state_manager: StateManager,
        basic_task_state: TaskState,
        mock_github_client: MagicMock,
        mock_agent: MagicMock,
        pr_context_manager: PRContextManager,
    ) -> None:
        """Test that task description includes both CI and comments when both present."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_sleep.return_value = True

        # Setup: Create both CI failures and comments files
        pr_dir = state_manager.get_pr_dir(42)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True)
        (ci_dir / "failed_tests.txt").write_text("Test failure")

        comments_dir = pr_dir / "comments"
        comments_dir.mkdir(parents=True)
        (comments_dir / "comment_1.txt").write_text("Review comment")

        # Mock save_ci_failures to not clear the directories we just created
        with (
            patch.object(pr_context_manager, "save_ci_failures"),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feature/fix"),
        ):
            workflow_handler.handle_ci_failed_stage(basic_task_state)

        # Verify the task description passed to agent includes both
        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        task_description = call_kwargs["task_description"]

        assert "CI has failed" in task_description
        assert "review comments" in task_description.lower()
        assert "BOTH" in task_description or "both" in task_description

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_task_description_ci_only_when_no_comments(
        self,
        mock_console: MagicMock,
        mock_sleep: MagicMock,
        workflow_handler: WorkflowStageHandler,
        state_manager: StateManager,
        basic_task_state: TaskState,
        mock_github_client: MagicMock,
        mock_agent: MagicMock,
        pr_context_manager: PRContextManager,
    ) -> None:
        """Test task description is CI-only when no comments present."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_sleep.return_value = True

        # Setup: Create only CI failures
        pr_dir = state_manager.get_pr_dir(42)
        ci_dir = pr_dir / "ci"
        ci_dir.mkdir(parents=True)
        (ci_dir / "failed_tests.txt").write_text("Test failure")

        # Mock save_ci_failures to not clear the directories
        with (
            patch.object(pr_context_manager, "save_ci_failures"),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feature/fix"),
        ):
            workflow_handler.handle_ci_failed_stage(basic_task_state)

        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        task_description = call_kwargs["task_description"]

        assert "CI has failed" in task_description
        # Should NOT mention addressing review comments in the same step
        assert "BOTH" not in task_description


# =============================================================================
# Test edge cases
# =============================================================================


class TestCICombinedEdgeCases:
    """Edge case tests for CI + comments combined handling."""

    def test_handles_exception_in_has_pr_comments(
        self, pr_context_manager: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that exceptions in has_pr_comments are handled gracefully."""
        with patch.object(state_manager, "get_pr_dir", side_effect=Exception("Error")):
            result = pr_context_manager.has_pr_comments(123)
            assert result is False  # Should return False, not raise

    def test_handles_exception_in_has_ci_failures(
        self, pr_context_manager: PRContextManager, state_manager: StateManager
    ) -> None:
        """Test that exceptions in has_ci_failures are handled gracefully."""
        with patch.object(state_manager, "get_pr_dir", side_effect=Exception("Error")):
            result = pr_context_manager.has_ci_failures(123)
            assert result is False  # Should return False, not raise

    def test_build_task_with_empty_pr_dir_path(
        self, workflow_handler: WorkflowStageHandler
    ) -> None:
        """Test task building with empty PR dir path uses fallback."""
        task = workflow_handler._build_combined_ci_comments_task(
            pr_number=42, has_ci=True, has_comments=False, pr_dir_path=""
        )

        # Should use fallback path
        assert ".claude-task-master/debugging/" in task

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_workflow_continues_after_combined_fix(
        self,
        mock_console: MagicMock,
        mock_sleep: MagicMock,
        workflow_handler: WorkflowStageHandler,
        state_manager: StateManager,
        basic_task_state: TaskState,
        mock_agent: MagicMock,
        pr_context_manager: PRContextManager,
    ) -> None:
        """Test that workflow moves to waiting_ci after combined fix."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_sleep.return_value = True

        with (
            patch.object(pr_context_manager, "save_ci_failures"),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="main"),
        ):
            workflow_handler.handle_ci_failed_stage(basic_task_state)

        assert basic_task_state.workflow_stage == "waiting_ci"
        assert basic_task_state.session_count == 2
