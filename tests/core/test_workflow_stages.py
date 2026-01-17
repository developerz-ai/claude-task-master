"""Tests for workflow_stages module - critical workflow logic.

This module tests the WorkflowStageHandler class which manages the PR lifecycle.
Tests cover:
- Static helper methods (check name extraction, branch operations)
- PR created stage handling
- CI waiting and failure stages
- Review stages (waiting and addressing)
- Ready to merge and merged stages
- Error handling and edge cases
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_agent():
    """Create a mock agent wrapper."""
    agent = MagicMock()
    agent.run_work_session = MagicMock(return_value={"output": "Fixed", "success": True})
    return agent


@pytest.fixture
def mock_github_client():
    """Create a mock GitHub client."""
    client = MagicMock()
    client.get_pr_for_current_branch = MagicMock(return_value=None)
    client.get_pr_status = MagicMock()
    client.merge_pr = MagicMock()
    return client


@pytest.fixture
def mock_pr_context():
    """Create a mock PR context manager."""
    context = MagicMock()
    context.save_ci_failures = MagicMock()
    context.save_pr_comments = MagicMock()
    context.post_comment_replies = MagicMock()
    return context


@pytest.fixture
def workflow_handler(mock_agent, state_manager, mock_github_client, mock_pr_context):
    """Create a WorkflowStageHandler instance with mocks."""
    return WorkflowStageHandler(
        agent=mock_agent,
        state_manager=state_manager,
        github_client=mock_github_client,
        pr_context=mock_pr_context,
    )


@pytest.fixture
def basic_task_state(sample_task_options):
    """Create a basic task state for testing."""
    now = datetime.now().isoformat()
    options = TaskOptions(**sample_task_options)
    return TaskState(
        status="working",
        workflow_stage="working",
        current_task_index=0,
        session_count=1,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=options,
    )


@pytest.fixture
def mock_pr_status():
    """Create a mock PR status object."""
    status = MagicMock()
    status.ci_state = "SUCCESS"
    status.checks_passed = 5
    status.checks_failed = 0
    status.checks_pending = 0
    status.checks_skipped = 1
    status.check_details = []
    status.unresolved_threads = 0
    status.resolved_threads = 0
    status.total_threads = 0
    status.mergeable = "MERGEABLE"
    status.base_branch = "main"
    return status


# =============================================================================
# Test Static Helper Methods
# =============================================================================


class TestGetCheckName:
    """Tests for _get_check_name static method."""

    def test_get_check_name_from_name_field(self):
        """Should extract name from CheckRun (name field)."""
        check = {"name": "CI Build", "status": "COMPLETED"}
        name = WorkflowStageHandler._get_check_name(check)
        assert name == "CI Build"

    def test_get_check_name_from_context_field(self):
        """Should extract name from StatusContext (context field)."""
        check = {"context": "continuous-integration/travis", "state": "success"}
        name = WorkflowStageHandler._get_check_name(check)
        assert name == "continuous-integration/travis"

    def test_get_check_name_prefers_name_over_context(self):
        """Should prefer name field over context field."""
        check = {"name": "Preferred", "context": "Fallback"}
        name = WorkflowStageHandler._get_check_name(check)
        assert name == "Preferred"

    def test_get_check_name_empty_dict(self):
        """Should return 'unknown' for empty dict."""
        name = WorkflowStageHandler._get_check_name({})
        assert name == "unknown"

    def test_get_check_name_none_values(self):
        """Should fallback when name is None."""
        check = {"name": None, "context": "Fallback"}
        name = WorkflowStageHandler._get_check_name(check)
        assert name == "Fallback"


class TestGetCurrentBranch:
    """Tests for _get_current_branch static method."""

    def test_get_current_branch_success(self):
        """Should return branch name on success."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="feature/my-branch\n")
            branch = WorkflowStageHandler._get_current_branch()
            assert branch == "feature/my-branch"

    def test_get_current_branch_empty(self):
        """Should return None for empty output (detached HEAD)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            branch = WorkflowStageHandler._get_current_branch()
            assert branch is None

    def test_get_current_branch_error(self):
        """Should return None on error."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Git not available")
            branch = WorkflowStageHandler._get_current_branch()
            assert branch is None


class TestCheckoutBranch:
    """Tests for _checkout_branch static method."""

    @patch("claude_task_master.core.workflow_stages.console")
    def test_checkout_branch_success(self, mock_console):
        """Should return True on successful checkout."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = WorkflowStageHandler._checkout_branch("main")
            assert result is True
            assert mock_run.call_count == 2  # checkout + pull

    @patch("claude_task_master.core.workflow_stages.console")
    def test_checkout_branch_failure(self, mock_console):
        """Should return False on checkout failure."""
        with patch("subprocess.run") as mock_run:
            from subprocess import CalledProcessError

            mock_run.side_effect = CalledProcessError(1, "git checkout")
            result = WorkflowStageHandler._checkout_branch("nonexistent")
            assert result is False
            mock_console.warning.assert_called()


# =============================================================================
# Test WorkflowStageHandler Initialization
# =============================================================================


class TestWorkflowStageHandlerInit:
    """Tests for WorkflowStageHandler initialization."""

    def test_init_basic(self, mock_agent, state_manager, mock_github_client, mock_pr_context):
        """Should initialize with all required arguments."""
        handler = WorkflowStageHandler(
            agent=mock_agent,
            state_manager=state_manager,
            github_client=mock_github_client,
            pr_context=mock_pr_context,
        )
        assert handler.agent is mock_agent
        assert handler.state_manager is state_manager
        assert handler.github_client is mock_github_client
        assert handler.pr_context is mock_pr_context

    def test_ci_poll_interval_constant(self):
        """Should have CI poll interval defined."""
        assert WorkflowStageHandler.CI_POLL_INTERVAL == 10


# =============================================================================
# Test Handle PR Created Stage
# =============================================================================


class TestHandlePRCreatedStage:
    """Tests for handle_pr_created_stage method."""

    @patch("claude_task_master.core.workflow_stages.console")
    def test_detects_pr_from_branch(
        self, mock_console, workflow_handler, state_manager, basic_task_state, mock_github_client
    ):
        """Should detect PR number from current branch."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_github_client.get_pr_for_current_branch.return_value = 42

        result = workflow_handler.handle_pr_created_stage(basic_task_state)

        assert result is None
        assert basic_task_state.current_pr == 42
        assert basic_task_state.workflow_stage == "waiting_ci"
        mock_console.success.assert_called()

    @patch("claude_task_master.core.workflow_stages.console")
    def test_no_pr_found_skips_to_merged(
        self, mock_console, workflow_handler, state_manager, basic_task_state, mock_github_client
    ):
        """Should skip to merged stage when no PR found."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_github_client.get_pr_for_current_branch.return_value = None

        result = workflow_handler.handle_pr_created_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "merged"
        mock_console.detail.assert_called()

    @patch("claude_task_master.core.workflow_stages.console")
    def test_pr_detection_error_skips_to_merged(
        self, mock_console, workflow_handler, state_manager, basic_task_state, mock_github_client
    ):
        """Should skip to merged stage when PR detection fails."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_github_client.get_pr_for_current_branch.side_effect = Exception("API error")

        result = workflow_handler.handle_pr_created_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "merged"
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.workflow_stages.console")
    def test_existing_pr_moves_to_ci(
        self, mock_console, workflow_handler, state_manager, basic_task_state
    ):
        """Should move to waiting_ci when PR already set."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 99

        result = workflow_handler.handle_pr_created_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "waiting_ci"
        mock_console.detail.assert_called()


# =============================================================================
# Test Handle Waiting CI Stage
# =============================================================================


class TestHandleWaitingCIStage:
    """Tests for handle_waiting_ci_stage method."""

    @patch("claude_task_master.core.workflow_stages.console")
    def test_no_pr_moves_to_reviews(
        self, mock_console, workflow_handler, state_manager, basic_task_state
    ):
        """Should move to waiting_reviews when no PR."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = None

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "waiting_reviews"

    @patch("claude_task_master.core.workflow_stages.console")
    def test_ci_success_moves_to_reviews(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should move to waiting_reviews on CI success."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.ci_state = "SUCCESS"
        mock_github_client.get_pr_status.return_value = mock_pr_status

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "waiting_reviews"
        mock_console.success.assert_called()

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_ci_failure_all_complete_moves_to_ci_failed(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should move to ci_failed when CI fails and all checks complete."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.ci_state = "FAILURE"
        mock_pr_status.checks_pending = 0
        mock_pr_status.checks_failed = 2
        mock_pr_status.check_details = [
            {"name": "Build", "conclusion": "FAILURE"},
            {"name": "Lint", "conclusion": "FAILURE"},
        ]
        mock_github_client.get_pr_status.return_value = mock_pr_status

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "ci_failed"
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_ci_failure_with_pending_waits(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should wait when CI has failures but checks still pending."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.ci_state = "FAILURE"
        mock_pr_status.checks_pending = 2  # Still pending
        mock_pr_status.checks_failed = 1
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result is None
        # Should stay in waiting_ci, not move to ci_failed
        assert basic_task_state.workflow_stage == "working"  # Original state unchanged
        mock_sleep.assert_called_once()

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_ci_pending_shows_status(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should show status and wait when CI pending."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.ci_state = "PENDING"
        mock_pr_status.checks_pending = 3
        mock_pr_status.check_details = [
            {"name": "Build", "status": "IN_PROGRESS"},
            {"name": "Tests", "status": "QUEUED"},
        ]
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result is None
        mock_console.info.assert_called()
        mock_sleep.assert_called_once()

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_ci_check_error_retries(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
    ):
        """Should retry on CI check error."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.side_effect = Exception("API error")
        mock_sleep.return_value = True

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result is None
        mock_console.warning.assert_called()
        mock_sleep.assert_called_once()


# =============================================================================
# Test Handle CI Failed Stage
# =============================================================================


class TestHandleCIFailedStage:
    """Tests for handle_ci_failed_stage method."""

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_runs_agent_to_fix(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_pr_context,
    ):
        """Should run agent to fix CI failures."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_sleep.return_value = True

        with patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feature/fix"):
            result = workflow_handler.handle_ci_failed_stage(basic_task_state)

        assert result is None
        mock_pr_context.save_ci_failures.assert_called_once_with(42)
        mock_agent.run_work_session.assert_called_once()
        assert basic_task_state.workflow_stage == "waiting_ci"
        assert basic_task_state.session_count == 2  # Incremented

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_uses_opus_model(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
    ):
        """Should use Opus model for CI fixes."""
        from claude_task_master.core.agent import ModelType

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_sleep.return_value = True

        with patch.object(WorkflowStageHandler, "_get_current_branch", return_value="main"):
            workflow_handler.handle_ci_failed_stage(basic_task_state)

        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        assert call_kwargs["model_override"] == ModelType.OPUS

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_context_load_error_continues(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
    ):
        """Should continue even if context load fails."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_sleep.return_value = True

        with (
            patch.object(state_manager, "load_context", side_effect=Exception("Error")),
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="main"),
        ):
            result = workflow_handler.handle_ci_failed_stage(basic_task_state)

        assert result is None
        mock_agent.run_work_session.assert_called_once()


# =============================================================================
# Test Handle Waiting Reviews Stage
# =============================================================================


class TestHandleWaitingReviewsStage:
    """Tests for handle_waiting_reviews_stage method."""

    @patch("claude_task_master.core.workflow_stages.console")
    def test_no_pr_moves_to_merged(
        self, mock_console, workflow_handler, state_manager, basic_task_state
    ):
        """Should move to merged when no PR."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = None

        result = workflow_handler.handle_waiting_reviews_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "merged"

    @patch("claude_task_master.core.workflow_stages.console")
    def test_no_comments_moves_to_ready(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should move to ready_to_merge when no comments."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.unresolved_threads = 0
        mock_pr_status.total_threads = 0
        mock_pr_status.check_details = []
        mock_github_client.get_pr_status.return_value = mock_pr_status

        result = workflow_handler.handle_waiting_reviews_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "ready_to_merge"
        mock_console.success.assert_called()

    @patch("claude_task_master.core.workflow_stages.console")
    def test_unresolved_comments_moves_to_addressing(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should move to addressing_reviews when unresolved comments."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.unresolved_threads = 2
        mock_pr_status.total_threads = 5
        mock_pr_status.check_details = []
        mock_github_client.get_pr_status.return_value = mock_pr_status

        result = workflow_handler.handle_waiting_reviews_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "addressing_reviews"
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_pending_checks_waits(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should wait when checks still pending."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.unresolved_threads = 0
        mock_pr_status.check_details = [
            {"name": "Review Bot", "status": "PENDING", "conclusion": None}
        ]
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        result = workflow_handler.handle_waiting_reviews_stage(basic_task_state)

        assert result is None
        mock_sleep.assert_called_once()

    @patch("claude_task_master.core.workflow_stages.console")
    def test_all_comments_resolved_moves_to_ready(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should move to ready when all comments resolved."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.unresolved_threads = 0
        mock_pr_status.resolved_threads = 3
        mock_pr_status.total_threads = 3
        mock_pr_status.check_details = []
        mock_github_client.get_pr_status.return_value = mock_pr_status

        result = workflow_handler.handle_waiting_reviews_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "ready_to_merge"
        mock_console.success.assert_called()

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_review_check_error_retries(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
    ):
        """Should retry on review check error."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.side_effect = Exception("API error")
        mock_sleep.return_value = True

        result = workflow_handler.handle_waiting_reviews_stage(basic_task_state)

        assert result is None
        mock_console.warning.assert_called()
        mock_sleep.assert_called_once()


# =============================================================================
# Test Handle Addressing Reviews Stage
# =============================================================================


class TestHandleAddressingReviewsStage:
    """Tests for handle_addressing_reviews_stage method."""

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_runs_agent_to_address(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_pr_context,
    ):
        """Should run agent to address review comments."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_sleep.return_value = True

        with patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feature/fix"):
            result = workflow_handler.handle_addressing_reviews_stage(basic_task_state)

        assert result is None
        mock_pr_context.save_pr_comments.assert_called_once_with(42)
        mock_agent.run_work_session.assert_called_once()
        mock_pr_context.post_comment_replies.assert_called_once_with(42)
        assert basic_task_state.workflow_stage == "waiting_ci"
        assert basic_task_state.session_count == 2

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_uses_opus_model(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
    ):
        """Should use Opus model for addressing reviews."""
        from claude_task_master.core.agent import ModelType

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_sleep.return_value = True

        with patch.object(WorkflowStageHandler, "_get_current_branch", return_value="main"):
            workflow_handler.handle_addressing_reviews_stage(basic_task_state)

        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        assert call_kwargs["model_override"] == ModelType.OPUS


# =============================================================================
# Test Handle Ready to Merge Stage
# =============================================================================


class TestHandleReadyToMergeStage:
    """Tests for handle_ready_to_merge_stage method."""

    @patch("claude_task_master.core.workflow_stages.console")
    def test_no_pr_moves_to_merged(
        self, mock_console, workflow_handler, state_manager, basic_task_state
    ):
        """Should move to merged when no PR."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = None

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "merged"

    @patch("claude_task_master.core.workflow_stages.console")
    def test_auto_merge_enabled_merges(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should merge PR when auto_merge enabled."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True
        mock_github_client.get_pr_status.return_value = mock_pr_status

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result is None
        mock_github_client.merge_pr.assert_called_once_with(42)
        assert basic_task_state.workflow_stage == "merged"
        mock_console.success.assert_called()

    @patch("claude_task_master.core.workflow_stages.console")
    def test_auto_merge_disabled_pauses(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should pause when auto_merge disabled."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = False
        mock_github_client.get_pr_status.return_value = mock_pr_status

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result == 2  # Interrupted/paused exit code
        assert basic_task_state.status == "paused"
        mock_console.info.assert_called()

    @patch("claude_task_master.core.workflow_stages.console")
    def test_merge_conflict_blocks(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should block when PR has conflicts."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True
        mock_pr_status.mergeable = "CONFLICTING"
        mock_github_client.get_pr_status.return_value = mock_pr_status

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result == 1  # Blocked exit code
        assert basic_task_state.status == "blocked"
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_mergeable_unknown_waits(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should wait when mergeable status unknown."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True
        mock_pr_status.mergeable = "UNKNOWN"
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result is None
        mock_console.info.assert_called()
        mock_sleep.assert_called_once()

    @patch("claude_task_master.core.workflow_stages.console")
    def test_merge_error_blocks(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should block when merge fails."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.merge_pr.side_effect = Exception("Merge failed")

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "blocked"
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.workflow_stages.console")
    def test_mergeable_check_error_continues(
        self, mock_console, workflow_handler, state_manager, basic_task_state, mock_github_client
    ):
        """Should continue to merge even if mergeable check fails."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True
        mock_github_client.get_pr_status.side_effect = Exception("API error")

        workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        # Should attempt merge anyway
        mock_github_client.merge_pr.assert_called_once_with(42)


# =============================================================================
# Test Handle Merged Stage
# =============================================================================


class TestHandleMergedStage:
    """Tests for handle_merged_stage method."""

    @patch("claude_task_master.core.workflow_stages.console")
    def test_marks_task_complete(
        self, mock_console, workflow_handler, state_manager, basic_task_state
    ):
        """Should mark task complete and increment index."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1\n- [ ] Task 2")

        mark_fn = MagicMock()
        result = workflow_handler.handle_merged_stage(basic_task_state, mark_fn)

        assert result is None
        mark_fn.assert_called_once()
        assert basic_task_state.current_task_index == 1
        assert basic_task_state.current_pr is None
        assert basic_task_state.workflow_stage == "working"
        mock_console.success.assert_called()

    @patch("claude_task_master.core.workflow_stages.console")
    def test_clears_pr_context_when_pr_exists(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should clear PR context when PR was merged."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.return_value = mock_pr_status

        mark_fn = MagicMock()

        with patch.object(
            WorkflowStageHandler, "_checkout_branch", return_value=True
        ) as mock_checkout:
            result = workflow_handler.handle_merged_stage(basic_task_state, mark_fn)

        assert result is None
        mock_checkout.assert_called_once_with("main")

    @patch("claude_task_master.core.workflow_stages.console")
    def test_checkout_to_base_branch(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should checkout to base branch after merge."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        basic_task_state.current_pr = 42
        mock_pr_status.base_branch = "develop"
        mock_github_client.get_pr_status.return_value = mock_pr_status

        mark_fn = MagicMock()

        with patch.object(
            WorkflowStageHandler, "_checkout_branch", return_value=True
        ) as mock_checkout:
            workflow_handler.handle_merged_stage(basic_task_state, mark_fn)

        mock_checkout.assert_called_once_with("develop")

    @patch("claude_task_master.core.workflow_stages.console")
    def test_checkout_failure_continues(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should continue even if checkout fails."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.return_value = mock_pr_status

        mark_fn = MagicMock()

        with patch.object(WorkflowStageHandler, "_checkout_branch", return_value=False):
            result = workflow_handler.handle_merged_stage(basic_task_state, mark_fn)

        assert result is None
        assert basic_task_state.workflow_stage == "working"
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.workflow_stages.console")
    def test_no_plan_continues(
        self, mock_console, workflow_handler, state_manager, basic_task_state
    ):
        """Should continue even if no plan loaded."""
        state_manager.state_dir.mkdir(exist_ok=True)
        # No plan saved

        mark_fn = MagicMock()
        result = workflow_handler.handle_merged_stage(basic_task_state, mark_fn)

        assert result is None
        # mark_fn should not be called when plan is empty/None
        mark_fn.assert_not_called()
        assert basic_task_state.workflow_stage == "working"

    @patch("claude_task_master.core.workflow_stages.console")
    def test_pr_status_error_uses_default_branch(
        self, mock_console, workflow_handler, state_manager, basic_task_state, mock_github_client
    ):
        """Should use main as default when PR status fails."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.side_effect = Exception("API error")

        mark_fn = MagicMock()

        with patch.object(
            WorkflowStageHandler, "_checkout_branch", return_value=True
        ) as mock_checkout:
            workflow_handler.handle_merged_stage(basic_task_state, mark_fn)

        mock_checkout.assert_called_once_with("main")  # Default fallback


# =============================================================================
# Test Integration Scenarios
# =============================================================================


class TestWorkflowIntegration:
    """Integration tests for workflow stage transitions."""

    @patch("claude_task_master.core.workflow_stages.console")
    def test_full_successful_pr_flow(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should handle full successful PR workflow."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        basic_task_state.options.auto_merge = True

        # Stage 1: PR Created
        mock_github_client.get_pr_for_current_branch.return_value = 42
        workflow_handler.handle_pr_created_stage(basic_task_state)
        assert basic_task_state.workflow_stage == "waiting_ci"
        assert basic_task_state.current_pr == 42

        # Stage 2: CI passes
        mock_pr_status.ci_state = "SUCCESS"
        mock_github_client.get_pr_status.return_value = mock_pr_status
        workflow_handler.handle_waiting_ci_stage(basic_task_state)
        assert basic_task_state.workflow_stage == "waiting_reviews"

        # Stage 3: No review comments
        mock_pr_status.unresolved_threads = 0
        mock_pr_status.total_threads = 0
        mock_pr_status.check_details = []
        workflow_handler.handle_waiting_reviews_stage(basic_task_state)
        assert basic_task_state.workflow_stage == "ready_to_merge"

        # Stage 4: Merge
        mock_pr_status.mergeable = "MERGEABLE"
        workflow_handler.handle_ready_to_merge_stage(basic_task_state)
        assert basic_task_state.workflow_stage == "merged"

        # Stage 5: Move to next task
        mark_fn = MagicMock()
        with patch.object(WorkflowStageHandler, "_checkout_branch", return_value=True):
            workflow_handler.handle_merged_stage(basic_task_state, mark_fn)

        assert basic_task_state.workflow_stage == "working"
        assert basic_task_state.current_task_index == 1
        assert basic_task_state.current_pr is None

    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    @patch("claude_task_master.core.workflow_stages.console")
    def test_pr_with_ci_failure_and_fix(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_github_client,
        mock_pr_status,
        mock_pr_context,
    ):
        """Should handle CI failure and fix flow."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"
        mock_sleep.return_value = True

        # CI fails
        mock_pr_status.ci_state = "FAILURE"
        mock_pr_status.checks_pending = 0
        mock_pr_status.checks_failed = 1
        mock_pr_status.check_details = [{"name": "Test", "conclusion": "FAILURE"}]
        mock_github_client.get_pr_status.return_value = mock_pr_status

        workflow_handler.handle_waiting_ci_stage(basic_task_state)
        assert basic_task_state.workflow_stage == "ci_failed"

        # Fix CI
        with patch.object(WorkflowStageHandler, "_get_current_branch", return_value="main"):
            workflow_handler.handle_ci_failed_stage(basic_task_state)

        assert basic_task_state.workflow_stage == "waiting_ci"
        assert basic_task_state.session_count == 2
        mock_agent.run_work_session.assert_called_once()
