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

from contextlib import ExitStack
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler
from claude_task_master.github.exceptions import GitHubError

# Stage sub-modules that own their own ``console`` / ``interruptible_sleep``
# bindings after the workflow_stages.py split. Single-stage tests patch the one
# sub-module they exercise; integration-style tests that drive several stages in
# one flow use the ``silence_all_stages`` fixture below to neutralise IO in all
# of them at once (there is no single interception point post-split).
_STAGE_SLEEP_MODULES = (
    "ci_stage",
    "pr_fix_stage",
    "review_stage",
    "merge_stage",
    "release_stage",
)
_STAGE_CONSOLE_MODULES = (*_STAGE_SLEEP_MODULES, "git_ops")


@pytest.fixture
def silence_all_stages():
    """Patch ``console`` + ``interruptible_sleep`` across every stage sub-module.

    Sleep returns ``True`` (not interrupted) so poll loops advance without real
    waits. Used by tests that drive multiple stages in a single flow.
    """
    with ExitStack() as stack:
        for mod in _STAGE_CONSOLE_MODULES:
            stack.enter_context(patch(f"claude_task_master.core.stages.{mod}.console"))
        for mod in _STAGE_SLEEP_MODULES:
            stack.enter_context(
                patch(
                    f"claude_task_master.core.stages.{mod}.interruptible_sleep",
                    return_value=True,
                )
            )
        yield


@pytest.fixture(autouse=True)
def no_real_sleep():
    """Prevent real sleeping (module-level time.sleep runs outside patched boundaries)."""
    with patch("time.sleep"):
        yield


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_agent():
    """Create a mock agent wrapper."""
    agent = MagicMock()
    agent.run_work_session = MagicMock(return_value={"output": "Fixed", "success": True})
    # Release verification runs through run_release_check (verify-only, no PR
    # contract), separate from run_work_session used by work/fix sessions.
    agent.run_release_check = MagicMock(
        return_value={"output": "RELEASE_CHECK: PASS", "success": True}
    )
    return agent


@pytest.fixture
def mock_github_client():
    """Create a mock GitHub client."""
    client = MagicMock()
    client.get_pr_for_current_branch = MagicMock(return_value=None)
    client.get_pr_status = MagicMock()
    client.merge_pr = MagicMock()
    client.get_pr_body = MagicMock(return_value="")
    client.update_pr_body = MagicMock()
    return client


@pytest.fixture
def mock_pr_context():
    """Create a mock PR context manager."""
    context = MagicMock()
    context.save_ci_failures = MagicMock()
    context.save_pr_comments = MagicMock(return_value=3)
    context.post_comment_replies = MagicMock()
    context.resolve_addressed_threads = MagicMock(return_value=0)
    # New methods for combined CI + comments handling
    context.has_ci_failures = MagicMock(return_value=True)
    context.has_pr_comments = MagicMock(return_value=False)
    # Returns (has_ci, has_comments, pr_dir_path)
    context.get_combined_feedback = MagicMock(
        return_value=(True, False, "/tmp/.claude-task-master/debugging/pr/42")
    )
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

    @patch("claude_task_master.core.stages.git_ops.console")
    def test_checkout_branch_success(self, mock_console):
        """Should return True on successful checkout."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = WorkflowStageHandler._checkout_branch("main")
            assert result is True
            assert mock_run.call_count == 2  # checkout + pull

    @patch("claude_task_master.core.stages.git_ops.console")
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

    @patch("claude_task_master.core.stages.ci_stage.console")
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

    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_no_pr_found_blocks(
        self, mock_console, workflow_handler, state_manager, basic_task_state, mock_github_client
    ):
        """Should block when no PR found - agent failed to create one."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_github_client.get_pr_for_current_branch.return_value = None

        result = workflow_handler.handle_pr_created_stage(basic_task_state)

        assert result == 1  # Blocked
        assert basic_task_state.status == "blocked"
        mock_console.error.assert_called()

    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_pr_detection_error_blocks(
        self, mock_console, workflow_handler, state_manager, basic_task_state, mock_github_client
    ):
        """Should block when PR detection fails with exception."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_github_client.get_pr_for_current_branch.side_effect = Exception("API error")

        result = workflow_handler.handle_pr_created_stage(basic_task_state)

        assert result == 1  # Blocked
        assert basic_task_state.status == "blocked"
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_sanitizes_pr_body_on_detection(
        self, mock_console, workflow_handler, state_manager, basic_task_state, mock_github_client
    ):
        """A newly detected PR whose body has decorative glyphs is rewritten clean."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_github_client.get_pr_for_current_branch.return_value = 42
        mock_github_client.get_pr_body.return_value = "## Verification\n- ✓ tests pass"

        workflow_handler.handle_pr_created_stage(basic_task_state)

        mock_github_client.update_pr_body.assert_called_once()
        _, cleaned = mock_github_client.update_pr_body.call_args[0]
        assert "✓" not in cleaned
        assert "tests pass" in cleaned

    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_clean_pr_body_not_rewritten(
        self, mock_console, workflow_handler, state_manager, basic_task_state, mock_github_client
    ):
        """A glyph-free PR body is left untouched (no needless edit call)."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_github_client.get_pr_for_current_branch.return_value = 42
        mock_github_client.get_pr_body.return_value = "## Summary\nplain body"

        workflow_handler.handle_pr_created_stage(basic_task_state)

        mock_github_client.update_pr_body.assert_not_called()

    @patch("claude_task_master.core.stages.ci_stage.console")
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

    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_no_pr_moves_to_reviews(
        self, mock_console, workflow_handler, state_manager, basic_task_state
    ):
        """Should move to waiting_reviews when no PR."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = None

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "waiting_reviews"

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_ci_success_moves_to_reviews(
        self,
        mock_console,
        mock_sleep,
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
        mock_sleep.return_value = True  # Sleep not interrupted

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "waiting_reviews"
        mock_console.success.assert_called()
        # Verify the review delay was applied
        mock_sleep.assert_called_with(workflow_handler.REVIEW_DELAY)

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
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

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
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

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
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

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
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

    @patch("claude_task_master.core.stages.pr_fix_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.pr_fix_stage.console")
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

    @patch("claude_task_master.core.stages.pr_fix_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.pr_fix_stage.console")
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

    @patch("claude_task_master.core.stages.pr_fix_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.pr_fix_stage.console")
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

    @patch("claude_task_master.core.stages.review_stage.console")
    def test_no_pr_moves_to_merged(
        self, mock_console, workflow_handler, state_manager, basic_task_state
    ):
        """Should move to merged when no PR."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = None

        result = workflow_handler.handle_waiting_reviews_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "merged"

    @patch("claude_task_master.core.stages.review_stage.console")
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

    @patch("claude_task_master.core.stages.review_stage.console")
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

    @patch("claude_task_master.core.stages.review_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.review_stage.console")
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

    @patch("claude_task_master.core.stages.review_stage.console")
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

    @patch("claude_task_master.core.stages.review_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.review_stage.console")
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

    @patch("claude_task_master.core.stages.review_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.review_stage.console")
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

    @patch("claude_task_master.core.stages.review_stage.console")
    def test_skips_agent_when_no_actionable_comments(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_pr_context,
    ):
        """Should skip agent and resolve threads directly when 0 actionable comments."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_context.save_pr_comments.return_value = 0
        mock_pr_context.resolve_addressed_threads.return_value = 1

        result = workflow_handler.handle_addressing_reviews_stage(basic_task_state)

        assert result is None
        mock_pr_context.save_pr_comments.assert_called_once_with(42)
        mock_agent.run_work_session.assert_not_called()
        mock_pr_context.post_comment_replies.assert_not_called()
        mock_pr_context.resolve_addressed_threads.assert_called_once_with(42)
        assert basic_task_state.workflow_stage == "waiting_reviews"

    @patch("claude_task_master.core.stages.review_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.review_stage.console")
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

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_no_pr_moves_to_merged(
        self, mock_console, workflow_handler, state_manager, basic_task_state
    ):
        """Should move to merged when no PR."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = None

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "merged"

    @patch("claude_task_master.core.stages.merge_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_auto_merge_enabled_merges(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should merge PR when auto_merge enabled and the merge is confirmed."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True
        merged_status = MagicMock()
        merged_status.state = "MERGED"  # merge confirmation poll sees MERGED
        mock_github_client.get_pr_status.side_effect = [mock_pr_status, merged_status]
        mock_sleep.return_value = True

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result is None
        mock_github_client.merge_pr.assert_called_once_with(42, admin=False)
        assert basic_task_state.workflow_stage == "merged"
        mock_console.success.assert_called()

    @patch("claude_task_master.core.stages.merge_stage.console")
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

    @patch("claude_task_master.core.stages.merge_stage.console")
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

    @patch("claude_task_master.core.stages.merge_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.merge_stage.console")
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
        assert workflow_handler._merge_unknown_attempts[42] == 1
        mock_sleep.assert_called_once()

    @patch("claude_task_master.core.stages.merge_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_merge_error_blocks(
        self,
        mock_console,
        mock_sleep,
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
        mock_sleep.return_value = True

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "blocked"
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.stages.merge_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_mergeable_check_error_retries_without_merging(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
    ):
        """Should retry with backoff and NEVER fall through to merge on status errors."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True
        mock_github_client.get_pr_status.side_effect = Exception("API error")
        mock_sleep.return_value = True

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result is None
        assert basic_task_state.status != "blocked"
        mock_github_client.merge_pr.assert_not_called()
        mock_sleep.assert_called_once()

    @patch("claude_task_master.core.stages.merge_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_mergeable_check_error_blocks_after_max_attempts(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
    ):
        """Should block after 6 consecutive status errors without ever calling merge_pr."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True
        mock_github_client.get_pr_status.side_effect = Exception("API error")
        mock_sleep.return_value = True

        result = None
        for _ in range(WorkflowStageHandler.MAX_MERGE_UNKNOWN_ATTEMPTS):
            result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "blocked"
        mock_github_client.merge_pr.assert_not_called()

    @patch("claude_task_master.core.stages.merge_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_mergeable_unknown_blocks_after_max_attempts(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """UNKNOWN mergeable polling is bounded: after 6 cycles it blocks."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True
        mock_pr_status.mergeable = "UNKNOWN"
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        result = None
        for _ in range(WorkflowStageHandler.MAX_MERGE_UNKNOWN_ATTEMPTS):
            result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "blocked"
        mock_github_client.merge_pr.assert_not_called()

    @patch("claude_task_master.core.stages.merge_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_merge_confirmed_advances_to_merged(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Merge confirmed via post-merge poll advances to merged."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True
        merged_status = MagicMock()
        merged_status.state = "MERGED"
        mock_github_client.get_pr_status.side_effect = [mock_pr_status, merged_status]
        mock_sleep.return_value = True

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "merged"
        mock_github_client.merge_pr.assert_called_once_with(42, admin=False)

    @patch("claude_task_master.core.stages.merge_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_merge_not_confirmed_stays_ready_to_merge(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Auto-merge scheduled (merge not confirmed) stays in ready_to_merge."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "ready_to_merge"
        basic_task_state.options.auto_merge = True
        mock_pr_status.state = "OPEN"  # never MERGED - auto-merge was scheduled
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        result = workflow_handler.handle_ready_to_merge_stage(basic_task_state)

        assert result is None
        mock_github_client.merge_pr.assert_called_once_with(42, admin=False)
        assert basic_task_state.workflow_stage == "ready_to_merge"
        assert basic_task_state.status != "blocked"
        # Confirmation polling is bounded at MERGE_CONFIRM_POLLS cycles
        assert mock_github_client.get_pr_status.call_count == (
            1 + WorkflowStageHandler.MERGE_CONFIRM_POLLS
        )


# =============================================================================
# Test Handle Merged Stage
# =============================================================================


class TestHandleMergedStage:
    """Tests for handle_merged_stage method."""

    @patch("claude_task_master.core.stages.merge_stage.console")
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

    @patch("claude_task_master.core.stages.merge_stage.console")
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

    @patch("claude_task_master.core.stages.merge_stage.console")
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

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_checkout_failure_blocks(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Should block workflow if checkout fails after PR merge."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.return_value = mock_pr_status

        mark_fn = MagicMock()

        with patch.object(WorkflowStageHandler, "_checkout_branch", return_value=False):
            result = workflow_handler.handle_merged_stage(basic_task_state, mark_fn)

        # Should block instead of continuing
        assert result == 1
        assert basic_task_state.status == "blocked"
        mock_console.error.assert_called()

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_release_fix_pr_merge_preserves_attempt_counter(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """A merged release-fix PR must NOT reset release_fix_attempts (cap stays reachable)."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        state_manager.save_release_guide("# Release\n\n1. Check /health returns 200")
        basic_task_state.options.enable_release = True
        basic_task_state.current_pr = 42
        basic_task_state.in_release_fix = True
        basic_task_state.release_fix_attempts = 4
        mock_github_client.get_pr_status.return_value = mock_pr_status

        with patch.object(WorkflowStageHandler, "_checkout_branch", return_value=True):
            result = workflow_handler.handle_merged_stage(basic_task_state, MagicMock())

        assert result is None
        assert basic_task_state.workflow_stage == "releasing"
        assert basic_task_state.release_fix_attempts == 4

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_normal_pr_merge_resets_release_fix_attempts(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """A normal (non-release-fix) PR merge DOES reset release_fix_attempts."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        state_manager.save_release_guide("# Release\n\n1. Check /health returns 200")
        basic_task_state.options.enable_release = True
        basic_task_state.current_pr = 42
        basic_task_state.in_release_fix = False
        basic_task_state.release_fix_attempts = 2
        mock_github_client.get_pr_status.return_value = mock_pr_status

        with patch.object(WorkflowStageHandler, "_checkout_branch", return_value=True):
            result = workflow_handler.handle_merged_stage(basic_task_state, MagicMock())

        assert result is None
        assert basic_task_state.workflow_stage == "releasing"
        assert basic_task_state.release_fix_attempts == 0

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_pr_merged_event_fn_invoked_for_externally_merged_pr(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Merged stage reached via external merge invokes pr_merged_event_fn exactly once."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        # Stage reached without a ready_to_merge transition (PR merged externally)
        basic_task_state.workflow_stage = "merged"
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.return_value = mock_pr_status

        mark_fn = MagicMock()
        event_fn = MagicMock()

        with patch.object(WorkflowStageHandler, "_checkout_branch", return_value=True):
            result = workflow_handler.handle_merged_stage(basic_task_state, mark_fn, event_fn)

        assert result is None
        event_fn.assert_called_once_with(basic_task_state)

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_pr_merged_event_fn_not_double_called_across_stages(
        self,
        mock_console,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
    ):
        """Second merged-stage call for the same PR invokes the callback again (once per call).

        Idempotency lives in the orchestrator callback, not in the stage handler.
        """
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.return_value = mock_pr_status

        event_fn = MagicMock()

        with patch.object(WorkflowStageHandler, "_checkout_branch", return_value=True):
            workflow_handler.handle_merged_stage(basic_task_state, MagicMock(), event_fn)
            # Simulate the stage being re-entered for the same PR (e.g. after resume)
            basic_task_state.current_pr = 42
            workflow_handler.handle_merged_stage(basic_task_state, MagicMock(), event_fn)

        # Each stage entry fires the callback once; the callback itself dedupes
        assert event_fn.call_count == 2

    @patch("claude_task_master.core.stages.merge_stage.console")
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

    @patch("claude_task_master.core.stages.merge_stage.console")
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

    def test_full_successful_pr_flow(
        self,
        silence_all_stages,
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

        # Stage 4: Merge (post-merge confirmation poll sees MERGED)
        mock_pr_status.mergeable = "MERGEABLE"
        mock_pr_status.state = "MERGED"
        workflow_handler.handle_ready_to_merge_stage(basic_task_state)
        assert basic_task_state.workflow_stage == "merged"

        # Stage 5: Move to next task
        mark_fn = MagicMock()
        with patch.object(WorkflowStageHandler, "_checkout_branch", return_value=True):
            workflow_handler.handle_merged_stage(basic_task_state, mark_fn)

        assert basic_task_state.workflow_stage == "working"
        assert basic_task_state.current_task_index == 1
        assert basic_task_state.current_pr is None

    def test_pr_with_ci_failure_and_fix(
        self,
        silence_all_stages,
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


# =============================================================================
# Test CI Polling Timeout
# =============================================================================


class TestCIPollingTimeout:
    """Tests for CI polling timeout to prevent infinite hangs."""

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_ci_poll_timeout_blocks_when_checks_pending(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
        state_manager,
    ):
        """Should block (not merge) when CI polling times out with pending checks."""
        from datetime import datetime, timedelta

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"
        # Set poll start time in the past (beyond the 7200s timeout)
        basic_task_state.ci_poll_start_time = datetime.now() - timedelta(seconds=7300)

        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = "PENDING"
        mock_pr_status.checks_pending = 2
        mock_pr_status.check_details = [
            {"name": "test", "status": "IN_PROGRESS", "conclusion": None}
        ]
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.return_value = []

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        # Non-admin: error out rather than merge a PR whose CI never finished
        assert result == 1
        assert basic_task_state.status == "blocked"
        assert basic_task_state.ci_poll_start_time is None

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_ci_poll_timeout_advances_when_admin(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
        state_manager,
    ):
        """--admin should force-advance to waiting_reviews on CI timeout."""
        from datetime import datetime, timedelta

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"
        basic_task_state.options.admin_merge = True
        basic_task_state.ci_poll_start_time = datetime.now() - timedelta(seconds=7300)

        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = "PENDING"
        mock_pr_status.checks_pending = 2
        mock_pr_status.check_details = [
            {"name": "test", "status": "IN_PROGRESS", "conclusion": None}
        ]
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.return_value = []

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "waiting_reviews"
        assert basic_task_state.ci_poll_start_time is None
        assert basic_task_state.status != "blocked"

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_ci_poll_timeout_advances_when_required_checks_missing(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
        state_manager,
    ):
        """Should block when required checks never report and timeout is reached."""
        from datetime import datetime, timedelta

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"
        basic_task_state.ci_poll_start_time = datetime.now() - timedelta(seconds=7300)

        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = "PENDING"
        mock_pr_status.checks_pending = 0
        mock_pr_status.check_details = []
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.return_value = ["required-ci"]

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "blocked"
        assert basic_task_state.ci_poll_start_time is None

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_ci_poll_keeps_waiting_before_timeout(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
        state_manager,
    ):
        """Should keep polling when timeout has not been reached."""
        from datetime import datetime, timedelta

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"
        # Only 30 seconds in - well before the 7200s timeout
        basic_task_state.ci_poll_start_time = datetime.now() - timedelta(seconds=30)

        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = "PENDING"
        mock_pr_status.checks_pending = 1
        mock_pr_status.check_details = [
            {"name": "test", "status": "IN_PROGRESS", "conclusion": None}
        ]
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.return_value = []
        mock_sleep.return_value = True

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        # Should return None (keep polling) and NOT change stage
        assert result is None
        assert basic_task_state.workflow_stage == "waiting_ci"

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_no_ci_first_poll_starts_timer_and_keeps_polling(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
        state_manager,
    ):
        """First poll with empty CI only starts the confirmation timer - no fast path."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"
        basic_task_state.ci_poll_start_time = None

        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = None
        mock_pr_status.checks_pending = 0
        mock_pr_status.check_details = []
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.return_value = []
        mock_sleep.return_value = True

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "waiting_ci"
        assert basic_task_state.ci_poll_start_time is not None
        mock_sleep.assert_called_once()

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_no_ci_configured_skips_to_reviews_after_confirmation_window(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
        state_manager,
    ):
        """Should skip CI wait only after the no-CI confirmation window has passed."""
        from datetime import datetime, timedelta

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"
        # Timer started 31s ago - past the ~30s confirmation window
        basic_task_state.ci_poll_start_time = datetime.now() - timedelta(seconds=31)

        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = None  # No CI state computed
        mock_pr_status.checks_pending = 0
        mock_pr_status.check_details = []  # No checks at all
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.return_value = []  # No required checks

        workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert basic_task_state.workflow_stage == "waiting_reviews"
        assert basic_task_state.ci_poll_start_time is None

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_required_checks_fetch_error_keeps_polling(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
        state_manager,
    ):
        """get_required_status_checks failure is 'unknown - keep polling', not zero checks."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"

        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = None
        mock_pr_status.checks_pending = 0
        mock_pr_status.check_details = []
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.side_effect = GitHubError("API error")
        mock_sleep.return_value = True

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "waiting_ci"
        mock_sleep.assert_called_once()

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_required_checks_fetch_error_blocks_on_timeout(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
        state_manager,
    ):
        """get_required_status_checks failure honors the CI timeout via _ci_timeout_action."""
        from datetime import datetime, timedelta

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"
        basic_task_state.ci_poll_start_time = datetime.now() - timedelta(seconds=7300)

        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = None
        mock_pr_status.checks_pending = 0
        mock_pr_status.check_details = []
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.side_effect = GitHubError("API timeout")

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "blocked"
        assert basic_task_state.ci_poll_start_time is None

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_ci_success_with_empty_details_still_passes(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
        state_manager,
    ):
        """CI state SUCCESS with empty check_details should still advance (not skip as no-CI)."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"

        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = "SUCCESS"
        mock_pr_status.checks_passed = 3
        mock_pr_status.checks_pending = 0
        mock_pr_status.checks_skipped = 1
        mock_pr_status.check_details = []
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.return_value = []
        mock_sleep.return_value = True

        with patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat"):
            workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert basic_task_state.workflow_stage == "waiting_reviews"

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_ci_poll_timeout_on_error(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        state_manager,
    ):
        """Should block on timeout even when CI check raises exceptions."""
        from datetime import datetime, timedelta

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"
        basic_task_state.ci_poll_start_time = datetime.now() - timedelta(seconds=7300)

        mock_github_client.get_pr_status.side_effect = Exception("API error")

        result = workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "blocked"
        assert basic_task_state.ci_poll_start_time is None

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_ci_failure_timeout_treats_as_failure(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
        state_manager,
    ):
        """CI failure with pending checks should treat as failure after timeout."""
        from datetime import datetime, timedelta

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_ci"
        basic_task_state.ci_poll_start_time = datetime.now() - timedelta(seconds=7300)

        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = "FAILURE"
        mock_pr_status.checks_pending = 1  # Still pending but timed out
        mock_pr_status.checks_failed = 1
        mock_pr_status.checks_passed = 2
        mock_pr_status.check_details = [{"name": "test", "conclusion": "FAILURE"}]
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.return_value = []

        with patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat"):
            workflow_handler.handle_waiting_ci_stage(basic_task_state)

        assert basic_task_state.workflow_stage == "ci_failed"
        assert basic_task_state.ci_poll_start_time is None

    @patch("claude_task_master.core.stages.ci_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_pr_created_stage_initializes_ci_poll_timer(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        state_manager,
    ):
        """PR created stage should initialize ci_poll_start_time."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "pr_created"
        basic_task_state.ci_poll_start_time = None

        workflow_handler.handle_pr_created_stage(basic_task_state)

        assert basic_task_state.workflow_stage == "waiting_ci"
        assert basic_task_state.ci_poll_start_time is not None


class TestWaitingReviewsTimeout:
    """Tests for waiting_reviews stage pending checks timeout."""

    def test_no_review_poll_timeout_constant(self):
        """REVIEW_POLL_TIMEOUT no longer exists (reviews share the CI poll timeout)."""
        assert not hasattr(WorkflowStageHandler, "REVIEW_POLL_TIMEOUT")

    def test_is_check_pending_used_for_pending_detection(self):
        """review_stage uses the shared is_check_pending helper from ci_helpers."""
        import inspect

        from claude_task_master.core.stages import review_stage

        # Imported lazily inside the polling method, so assert on the source
        source = inspect.getsource(review_stage)
        assert "from ...cli_commands.ci_helpers import is_check_pending" in source

    @patch("claude_task_master.core.stages.review_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.review_stage.console")
    def test_review_checks_timeout_advances(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        basic_task_state,
        mock_github_client,
        mock_pr_status,
        state_manager,
    ):
        """Should proceed past pending checks in reviews after timeout."""
        from datetime import datetime, timedelta

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "waiting_reviews"
        basic_task_state.ci_poll_start_time = datetime.now() - timedelta(seconds=7300)

        mock_pr_status.state = "OPEN"
        mock_pr_status.check_details = [
            {"name": "coderabbit", "status": "IN_PROGRESS", "conclusion": None}
        ]
        mock_pr_status.unresolved_threads = 0
        mock_pr_status.resolved_threads = 0
        mock_pr_status.total_threads = 0
        mock_github_client.get_pr_status.return_value = mock_pr_status

        workflow_handler.handle_waiting_reviews_stage(basic_task_state)

        assert basic_task_state.workflow_stage == "ready_to_merge"
        assert basic_task_state.ci_poll_start_time is None


# =============================================================================
# Test CI Fix Attempt Cap
# =============================================================================


class TestHandleCIFailedStageCap:
    """Tests for the MAX_CI_FIX_ATTEMPTS cap in handle_ci_failed_stage."""

    @patch("claude_task_master.core.stages.pr_fix_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.pr_fix_stage.console")
    def test_ci_fix_at_cap_blocks_without_agent(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
    ):
        """At the cap (3 attempts), should block and return 1 WITHOUT running the agent."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.ci_fix_attempts = WorkflowStageHandler.MAX_CI_FIX_ATTEMPTS

        result = workflow_handler.handle_ci_failed_stage(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "blocked"
        mock_agent.run_work_session.assert_not_called()
        mock_console.error.assert_called()
        mock_sleep.assert_not_called()

    @patch("claude_task_master.core.stages.pr_fix_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.pr_fix_stage.console")
    def test_ci_fix_below_cap_increments_and_runs_agent(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
    ):
        """Below the cap, should increment ci_fix_attempts, run agent, and wait for CI."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.ci_fix_attempts = 1
        mock_sleep.return_value = True

        with patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat"):
            result = workflow_handler.handle_ci_failed_stage(basic_task_state)

        assert result is None
        assert basic_task_state.ci_fix_attempts == 2
        mock_agent.run_work_session.assert_called_once()
        assert basic_task_state.workflow_stage == "waiting_ci"


# =============================================================================
# Test Advance To Next Task Resets
# =============================================================================


class TestAdvanceToNextTask:
    """Tests for _advance_to_next_task field resets."""

    def test_advance_resets_fix_attempt_fields(
        self, workflow_handler, state_manager, basic_task_state
    ):
        """Should reset in_release_fix, release_fix_attempts, and ci_fix_attempts."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.in_release_fix = True
        basic_task_state.release_fix_attempts = 3
        basic_task_state.ci_fix_attempts = 2

        workflow_handler._advance_to_next_task(basic_task_state)

        assert basic_task_state.current_task_index == 1
        assert basic_task_state.current_pr is None
        assert basic_task_state.workflow_stage == "working"
        assert basic_task_state.in_release_fix is False
        assert basic_task_state.release_fix_attempts == 0
        assert basic_task_state.ci_fix_attempts == 0


# =============================================================================
# Test PR Head Branch Sessions
# =============================================================================


class TestPRHeadBranchSessions:
    """Fix sessions must target the PR head ref, not whatever branch is checked out."""

    @patch("claude_task_master.core.stages.pr_fix_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.pr_fix_stage.console")
    def test_ci_failed_stage_passes_head_branch_as_required_branch(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_github_client,
        mock_pr_status,
    ):
        """handle_ci_failed_stage passes get_pr_status(...).head_branch as required_branch."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.head_branch = "feat/pr-branch"
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        with (
            patch.object(
                WorkflowStageHandler, "_get_current_branch", return_value="feat/pr-branch"
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = workflow_handler.handle_ci_failed_stage(basic_task_state)

        assert result is None
        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        assert call_kwargs["required_branch"] == "feat/pr-branch"

    @patch("claude_task_master.core.stages.pr_fix_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.pr_fix_stage.console")
    def test_ci_failed_stage_checks_out_head_branch_when_different(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_github_client,
        mock_pr_status,
    ):
        """When current branch differs, the PR head branch is checked out before the session."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.head_branch = "feat/pr-branch"
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        with (
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="main"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = workflow_handler.handle_ci_failed_stage(basic_task_state)

        assert result is None
        checkout_calls = [
            c for c in mock_run.call_args_list if c.args[0][:2] == ["git", "checkout"]
        ]
        assert len(checkout_calls) == 1
        assert checkout_calls[0].args[0] == ["git", "checkout", "feat/pr-branch"]
        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        assert call_kwargs["required_branch"] == "feat/pr-branch"

    @patch("claude_task_master.core.stages.review_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.review_stage.console")
    def test_addressing_reviews_stage_passes_head_branch_as_required_branch(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_github_client,
        mock_pr_status,
    ):
        """handle_addressing_reviews_stage also targets the PR head branch."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.head_branch = "feat/review-branch"
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        with (
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="main"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = workflow_handler.handle_addressing_reviews_stage(basic_task_state)

        assert result is None
        checkout_calls = [
            c for c in mock_run.call_args_list if c.args[0][:2] == ["git", "checkout"]
        ]
        assert len(checkout_calls) == 1
        assert checkout_calls[0].args[0] == ["git", "checkout", "feat/review-branch"]
        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        assert call_kwargs["required_branch"] == "feat/review-branch"


# =============================================================================
# Test Fix Session Push-Only Mode + Rebase Policy
# =============================================================================


class TestFixSessionPushOnlyMode:
    """Fix sessions operate on an EXISTING PR: they must push (create_pr=False,
    push_only=True) so the agent updates that PR instead of opening a duplicate,
    and their prompts must not mandate rebase/force-push — that rewrites
    already-reviewed commits and breaks the PR's review threads."""

    @patch("claude_task_master.core.stages.pr_fix_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.pr_fix_stage.console")
    def test_ci_failed_stage_runs_push_only(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_github_client,
        mock_pr_status,
    ):
        """handle_ci_failed_stage pushes to the existing PR (no new PR, no rebase)."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.head_branch = "feat/pr-branch"
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        with (
            patch.object(
                WorkflowStageHandler, "_get_current_branch", return_value="feat/pr-branch"
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            workflow_handler.handle_ci_failed_stage(basic_task_state)

        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        assert call_kwargs["push_only"] is True
        assert call_kwargs["create_pr"] is False

    @patch("claude_task_master.core.stages.review_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.review_stage.console")
    def test_addressing_reviews_stage_runs_push_only(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_github_client,
        mock_pr_status,
    ):
        """handle_addressing_reviews_stage pushes to the existing PR (no new PR)."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.head_branch = "feat/pr-branch"
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        with (
            patch.object(
                WorkflowStageHandler, "_get_current_branch", return_value="feat/pr-branch"
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            workflow_handler.handle_addressing_reviews_stage(basic_task_state)

        call_kwargs = mock_agent.run_work_session.call_args.kwargs
        assert call_kwargs["push_only"] is True
        assert call_kwargs["create_pr"] is False

    @pytest.mark.parametrize(
        "has_ci,has_comments",
        [(True, True), (True, False), (False, True)],
    )
    def test_ci_comments_task_body_has_no_rebase_mandate(
        self, workflow_handler, has_ci, has_comments
    ):
        """CI/comment fix bodies must not mandate rebase or force-push — the single
        push_only policy owns the git mechanics (`git push origin HEAD`)."""
        task = workflow_handler._build_combined_ci_comments_task(
            42, has_ci, has_comments, "/tmp/pr-42"
        )
        lowered = task.lower()
        assert "rebase onto" not in lowered
        assert "force-with-lease" not in lowered
        assert "git rebase origin" not in lowered
        assert "git push origin head" in lowered

    @patch("claude_task_master.core.stages.review_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.review_stage.console")
    def test_addressing_reviews_body_has_no_rebase_mandate(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_github_client,
        mock_pr_status,
    ):
        """The review-fix prompt must not mandate rebase-onto-target or force-push."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        mock_pr_status.head_branch = "feat/pr-branch"
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        with (
            patch.object(
                WorkflowStageHandler, "_get_current_branch", return_value="feat/pr-branch"
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            workflow_handler.handle_addressing_reviews_stage(basic_task_state)

        task = mock_agent.run_work_session.call_args.kwargs["task_description"].lower()
        assert "rebase onto" not in task
        assert "force-with-lease" not in task
        assert "git push origin head" in task


# =============================================================================
# Test CI Poll Timer Helpers
# =============================================================================


class TestCIPollTimerHelpers:
    """Tests for _is_ci_poll_timed_out (resume must not insta-timeout)."""

    def test_is_ci_poll_timed_out_false_when_timer_cleared(
        self, workflow_handler, basic_task_state
    ):
        """A cleared timer (None) is never timed out, regardless of prior elapsed time."""
        basic_task_state.ci_poll_start_time = None
        assert workflow_handler._is_ci_poll_timed_out(basic_task_state) is False

    def test_is_ci_poll_timed_out_true_when_elapsed_exceeds_timeout(
        self, workflow_handler, basic_task_state
    ):
        """An uncleared timer far in the past IS timed out."""
        from datetime import timedelta

        basic_task_state.ci_poll_start_time = datetime.now() - timedelta(
            seconds=WorkflowStageHandler.CI_POLL_TIMEOUT + 100
        )
        assert workflow_handler._is_ci_poll_timed_out(basic_task_state) is True

    def test_clear_ci_poll_timer_prevents_insta_timeout_on_resume(
        self, workflow_handler, basic_task_state
    ):
        """After the timer is cleared, a resume does not instantly time out."""
        from datetime import timedelta

        basic_task_state.ci_poll_start_time = datetime.now() - timedelta(seconds=7300)
        workflow_handler._clear_ci_poll_timer(basic_task_state)
        assert basic_task_state.ci_poll_start_time is None
        assert workflow_handler._is_ci_poll_timed_out(basic_task_state) is False


# =============================================================================
# Test Checkout Branch Stash Recovery
# =============================================================================


class TestCheckoutBranchStashRecovery:
    """Tests for _checkout_branch dirty-tree stash recovery."""

    @patch("claude_task_master.core.stages.git_ops.console")
    def test_stash_recovery_logs_stash_ref_loudly(self, mock_console):
        """Dirty-tree recovery must warn loudly with the stash ref."""
        from subprocess import CalledProcessError

        responses = [
            CalledProcessError(1, "git checkout"),  # initial checkout fails
            MagicMock(returncode=0, stdout=" M dirty.py\n"),  # status: dirty tree
            MagicMock(returncode=0, stdout=""),  # stash push succeeds
            MagicMock(returncode=0, stdout="stash@{0}: claudetm: auto-stash\n"),  # stash list
            MagicMock(returncode=0, stdout=""),  # retry checkout succeeds
            MagicMock(returncode=0, stdout=""),  # pull succeeds
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = responses
            result = WorkflowStageHandler._checkout_branch("main")

        assert result is True
        warning_texts = [str(c.args[0]) for c in mock_console.warning.call_args_list]
        assert any("stash" in text.lower() for text in warning_texts)

    @patch("claude_task_master.core.stages.git_ops.console")
    def test_stash_failure_aborts_checkout(self, mock_console):
        """A failed stash aborts the checkout instead of losing track of local work."""
        from subprocess import CalledProcessError

        responses = [
            CalledProcessError(1, "git checkout"),  # initial checkout fails
            MagicMock(returncode=0, stdout=" M dirty.py\n"),  # status: dirty tree
            CalledProcessError(1, "git stash"),  # stash push FAILS
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = responses
            result = WorkflowStageHandler._checkout_branch("main")

        assert result is False
        # Retry checkout must never run - the abort protects uncommitted work
        retry_checkouts = [
            c
            for c in mock_run.call_args_list[2:]
            if c.args and c.args[0][:2] == ["git", "checkout"]
        ]
        assert retry_checkouts == []
        warning_texts = [str(c.args[0]) for c in mock_console.warning.call_args_list]
        assert any("Aborting checkout" in text for text in warning_texts)

    @patch("claude_task_master.core.stages.git_ops.console")
    def test_stash_failure_returns_false_without_recovery_attempt(self, mock_console):
        """Stash failure returns False immediately - no stash list, no pull attempted."""
        from subprocess import CalledProcessError

        responses = [
            CalledProcessError(1, "git checkout"),  # initial checkout fails
            MagicMock(returncode=0, stdout="?? untracked.py\n"),  # status: dirty tree
            CalledProcessError(1, "git stash"),  # stash push FAILS
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = responses
            result = WorkflowStageHandler._checkout_branch("develop")

        assert result is False
        # Exactly 3 git calls: checkout, status, stash push - nothing after the abort
        assert mock_run.call_count == 3


# =============================================================================
# Test CI Fix Cycle Cap (Full Cycle)
# =============================================================================


class TestCIFixCycleCap:
    """Repeated ci_failed cycles must block exactly at MAX_CI_FIX_ATTEMPTS + 1 entries."""

    @patch("claude_task_master.core.stages.pr_fix_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.pr_fix_stage.console")
    def test_repeated_cycles_run_agent_until_cap_then_block(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_github_client,
        mock_pr_status,
    ):
        """Each cycle below the cap runs the agent; the cycle past the cap blocks."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "ci_failed"
        mock_pr_status.head_branch = "feat/ci-fix"
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_sleep.return_value = True

        cap = WorkflowStageHandler.MAX_CI_FIX_ATTEMPTS
        with (
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/ci-fix"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            for cycle in range(1, cap + 2):
                # Each ci_failed entry re-enters from waiting_ci
                basic_task_state.workflow_stage = "ci_failed"
                result = workflow_handler.handle_ci_failed_stage(basic_task_state)
                if cycle <= cap:
                    assert result is None, f"cycle {cycle} should keep fixing"
                    assert basic_task_state.ci_fix_attempts == cycle
                    assert basic_task_state.workflow_stage == "waiting_ci"
                    assert basic_task_state.status != "blocked"
                else:
                    assert result == 1, f"cycle {cycle} should block"
                    assert basic_task_state.status == "blocked"

        # Agent ran exactly cap times - the blocked cycle never reaches it
        assert mock_agent.run_work_session.call_count == cap
        # Attempt counter is persisted and not reset by blocking
        assert basic_task_state.ci_fix_attempts == cap + 1

    @patch("claude_task_master.core.stages.pr_fix_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.pr_fix_stage.console")
    def test_blocked_at_cap_saves_state_without_running_agent(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
    ):
        """The over-cap entry persists the blocked status and skips the agent entirely."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.current_pr = 42
        basic_task_state.workflow_stage = "ci_failed"
        basic_task_state.ci_fix_attempts = WorkflowStageHandler.MAX_CI_FIX_ATTEMPTS

        result = workflow_handler.handle_ci_failed_stage(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "blocked"
        assert basic_task_state.workflow_stage == "ci_failed"  # stage unchanged
        mock_agent.run_work_session.assert_not_called()
        mock_sleep.assert_not_called()
        mock_console.error.assert_called()


# =============================================================================
# Test PR Head Branch Resolution Failures
# =============================================================================


class TestPRHeadBranchResolution:
    """_get_pr_head_branch must fall back to the current branch on any failure."""

    def test_resolves_head_branch_and_returns_it(
        self, workflow_handler, basic_task_state, mock_github_client, mock_pr_status
    ):
        """Head branch matching the current branch is returned without a checkout."""
        basic_task_state.current_pr = 42
        mock_pr_status.head_branch = "feat/head"
        mock_github_client.get_pr_status.return_value = mock_pr_status

        with (
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="feat/head"),
            patch("subprocess.run") as mock_run,
        ):
            result = workflow_handler._get_pr_head_branch(basic_task_state)

        assert result == "feat/head"
        mock_run.assert_not_called()  # No checkout needed - already on the branch

    def test_pr_status_error_falls_back_to_current_branch(
        self, workflow_handler, basic_task_state, mock_github_client
    ):
        """A get_pr_status failure falls back to the current local branch."""
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.side_effect = GitHubError("API error")

        with patch.object(WorkflowStageHandler, "_get_current_branch", return_value="local-branch"):
            result = workflow_handler._get_pr_head_branch(basic_task_state)

        assert result == "local-branch"

    def test_empty_head_branch_falls_back_to_current_branch(
        self, workflow_handler, basic_task_state, mock_github_client, mock_pr_status
    ):
        """An empty head_branch (e.g. fork deleted) falls back to the current branch."""
        basic_task_state.current_pr = 42
        mock_pr_status.head_branch = ""
        mock_github_client.get_pr_status.return_value = mock_pr_status

        with patch.object(WorkflowStageHandler, "_get_current_branch", return_value="local-branch"):
            result = workflow_handler._get_pr_head_branch(basic_task_state)

        assert result == "local-branch"

    @patch("claude_task_master.core.stages.git_ops.console")
    def test_checkout_failure_falls_back_to_current_branch(
        self, mock_console, workflow_handler, basic_task_state, mock_github_client, mock_pr_status
    ):
        """A failed head-branch checkout warns and returns the ACTUAL current branch.

        The worktree stays on the previous branch when checkout fails, so
        required_branch must reflect reality (not the intended head): otherwise a
        push-only fix session would be told it is on the PR head while sitting on
        main, and could push commits to the wrong local branch.
        """
        from subprocess import CalledProcessError

        basic_task_state.current_pr = 42
        mock_pr_status.head_branch = "feat/head"
        mock_github_client.get_pr_status.return_value = mock_pr_status

        with (
            patch.object(WorkflowStageHandler, "_get_current_branch", return_value="main"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.side_effect = CalledProcessError(1, "git checkout", stderr="boom")
            result = workflow_handler._get_pr_head_branch(basic_task_state)

        assert result == "main"
        mock_console.warning.assert_called()

    def test_no_pr_uses_current_branch(self, workflow_handler, basic_task_state):
        """Without a PR, resolution is just the current branch (no API call)."""
        basic_task_state.current_pr = None

        with patch.object(
            WorkflowStageHandler, "_get_current_branch", return_value="main"
        ) as mock_branch:
            result = workflow_handler._get_pr_head_branch(basic_task_state)

        assert result == "main"
        mock_branch.assert_called_once()


# =============================================================================
# Test Release-Fix Counter Persistence
# =============================================================================


class TestReleasingStageVerifyOnlyContract:
    """Release verification must run verify-only — NOT wrapped in the create-PR
    contract — so the RELEASE_CHECK marker survives and the check can FAIL."""

    @pytest.fixture
    def _release_state(self, state_manager, basic_task_state, mock_github_client, mock_pr_status):
        """Persist a release guide + plan and wire a merged PR ready for release."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        state_manager.save_release_guide("# Release\n\n1. Check /health returns 200")
        basic_task_state.options.auto_merge = True
        basic_task_state.options.enable_release = True
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.return_value = mock_pr_status
        return basic_task_state

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_releasing_uses_release_check_not_work_session(
        self, mock_console, mock_sleep, workflow_handler, mock_agent, _release_state
    ):
        """handle_releasing_stage routes through run_release_check (verify-only),
        never run_work_session (which carries the create-PR contract)."""
        from claude_task_master.core.agent import ModelType

        mock_sleep.return_value = True

        workflow_handler.handle_releasing_stage(_release_state)

        mock_agent.run_release_check.assert_called_once()
        mock_agent.run_work_session.assert_not_called()
        # Sonnet for speed, and the built release-verification prompt is passed.
        call = mock_agent.run_release_check.call_args
        assert call.kwargs["model_override"] == ModelType.SONNET
        prompt = call.args[0]
        assert "RELEASE VERIFICATION" in prompt

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_release_check_can_fail(
        self, mock_console, mock_sleep, workflow_handler, mock_agent, _release_state
    ):
        """A FAIL marker transitions to release_fix — proving the check is not
        silently swallowed into SKIP the way the work-session wrapper caused."""
        mock_sleep.return_value = True
        mock_agent.run_release_check.return_value = {
            "output": "RELEASE_CHECK: FAIL — /health returned 500",
            "success": True,
        }

        result = workflow_handler.handle_releasing_stage(_release_state)

        assert result is None
        assert _release_state.workflow_stage == "release_fix"

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_release_check_pass_advances(
        self, mock_console, mock_sleep, workflow_handler, mock_agent, _release_state
    ):
        """A PASS marker advances to the next task."""
        mock_sleep.return_value = True
        mock_agent.run_release_check.return_value = {
            "output": "RELEASE_CHECK: PASS",
            "success": True,
        }

        result = workflow_handler.handle_releasing_stage(_release_state)

        assert result is None
        assert _release_state.workflow_stage == "working"
        assert _release_state.current_task_index == 1


class TestReleaseFixDetails:
    """A failed release check must hand its failure details to the fix session
    (persisted through the release_fix stage transition) instead of running blind."""

    @pytest.fixture
    def _release_state(self, state_manager, basic_task_state, mock_github_client, mock_pr_status):
        """Persist a release guide + plan and wire a merged PR ready for release."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        state_manager.save_release_guide("# Release\n\n1. Check /health returns 200")
        basic_task_state.options.auto_merge = True
        basic_task_state.options.enable_release = True
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.return_value = mock_pr_status
        return basic_task_state

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_releasing_fail_persists_details(
        self, mock_console, mock_sleep, workflow_handler, mock_agent, _release_state
    ):
        """A FAILED release check persists its output into state for the fix session."""
        mock_sleep.return_value = True
        mock_agent.run_release_check.return_value = {
            "output": "RELEASE_CHECK: FAIL — /health returned 500 on api.example.com",
            "success": True,
        }

        workflow_handler.handle_releasing_stage(_release_state)

        assert _release_state.workflow_stage == "release_fix"
        assert _release_state.release_fix_details is not None
        assert "/health returned 500" in _release_state.release_fix_details

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_releasing_fail_caps_details_to_tail(
        self, mock_console, mock_sleep, workflow_handler, mock_agent, _release_state
    ):
        """Persisted details are tail-capped so state.json stays small."""
        mock_sleep.return_value = True
        big_output = "x" * 10000 + "RELEASE_CHECK: FAIL"
        mock_agent.run_release_check.return_value = {"output": big_output, "success": True}

        workflow_handler.handle_releasing_stage(_release_state)

        cap = WorkflowStageHandler.RELEASE_FAIL_DETAILS_MAX_CHARS
        assert _release_state.release_fix_details is not None
        assert len(_release_state.release_fix_details) == cap
        # Tail is kept, so the FAIL marker at the end survives the cap.
        assert _release_state.release_fix_details.endswith("RELEASE_CHECK: FAIL")

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_release_fix_injects_failed_checks_section(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
    ):
        """handle_release_fix_stage injects persisted details under ## Failed Checks."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_release_guide("# Release guide")
        basic_task_state.current_pr = 42
        basic_task_state.release_fix_details = "Health check failed: 503 at /healthz"
        mock_sleep.return_value = True

        workflow_handler.handle_release_fix_stage(basic_task_state)

        task = mock_agent.run_work_session.call_args.kwargs["task_description"]
        assert "## Failed Checks" in task
        assert "Health check failed: 503 at /healthz" in task

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_release_fix_handles_missing_details(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
    ):
        """With no persisted details the prompt still carries a ## Failed Checks section."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_release_guide("# Release guide")
        basic_task_state.current_pr = 42
        basic_task_state.release_fix_details = None
        mock_sleep.return_value = True

        workflow_handler.handle_release_fix_stage(basic_task_state)

        task = mock_agent.run_work_session.call_args.kwargs["task_description"]
        assert "## Failed Checks" in task
        assert "No failure details captured." in task

    def test_advance_clears_release_fix_details(
        self, workflow_handler, state_manager, basic_task_state
    ):
        """_advance_to_next_task clears details so they never leak to the next task."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.release_fix_details = "stale failure text"

        workflow_handler._advance_to_next_task(basic_task_state)

        assert basic_task_state.release_fix_details is None


class TestReleaseFixCounterPersistence:
    """release_fix_attempts must survive the fix-PR merge so the 5-attempt cap stays reachable."""

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_release_fix_stage_increments_and_persists_counter(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
    ):
        """handle_release_fix_stage increments the counter and flags in_release_fix."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.release_fix_attempts = 2
        basic_task_state.in_release_fix = False
        mock_sleep.return_value = True

        result = workflow_handler.handle_release_fix_stage(basic_task_state)

        assert result is None
        assert basic_task_state.release_fix_attempts == 3
        assert basic_task_state.in_release_fix is True
        assert basic_task_state.current_pr is None  # cleared for re-discovery
        assert basic_task_state.workflow_stage == "pr_created"
        mock_agent.run_work_session.assert_called_once()

    def test_repeated_failure_cycles_stop_at_max_attempts(
        self,
        silence_all_stages,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_github_client,
        mock_pr_status,
    ):
        """releasing → release_fix cycles advance past the cap only because the
        merged-stage preserves the counter for release-fix PRs."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        state_manager.save_release_guide("# Release\n\n1. Check /health returns 200")
        basic_task_state.options.auto_merge = True
        basic_task_state.options.enable_release = True
        basic_task_state.current_pr = 42
        mock_github_client.get_pr_status.return_value = mock_pr_status
        # Release verification (run_release_check) fails; the fix session
        # (run_work_session) keeps its default success return.
        mock_agent.run_release_check.return_value = {
            "output": "RELEASE_CHECK: FAIL — health endpoint 500",
            "success": True,
        }

        # Counter accumulated over previous fix cycles; in_release_fix is set by
        # handle_release_fix_stage, so simulate the state right after attempt 4's
        # fix PR merged (merged stage must have preserved the counter at 4).
        basic_task_state.in_release_fix = True
        basic_task_state.release_fix_attempts = 4

        # 5th release verification fails again
        result = workflow_handler.handle_releasing_stage(basic_task_state)

        assert result is None
        assert basic_task_state.workflow_stage == "release_fix"

        # 5th fix attempt runs - counter reaches the cap
        result = workflow_handler.handle_release_fix_stage(basic_task_state)
        assert result is None
        assert basic_task_state.release_fix_attempts == 5

        # Fix PR #5 merges - in_release_fix is still True, so the counter survives
        basic_task_state.current_pr = 43
        basic_task_state.workflow_stage = "merged"
        with patch.object(WorkflowStageHandler, "_checkout_branch", return_value=True):
            result = workflow_handler.handle_merged_stage(basic_task_state, MagicMock())
        assert result is None
        assert basic_task_state.release_fix_attempts == 5
        assert basic_task_state.workflow_stage == "releasing"

        # 6th verification failure hits the cap: advance WITHOUT another fix cycle
        release_checks_before = mock_agent.run_release_check.call_count
        result = workflow_handler.handle_releasing_stage(basic_task_state)
        assert result is None
        assert basic_task_state.workflow_stage == "working"
        assert basic_task_state.release_fix_attempts == 0  # reset by _advance_to_next_task
        assert basic_task_state.current_task_index == 1
        # One final verification runs, then the cap blocks any further fix cycle
        assert mock_agent.run_release_check.call_count == release_checks_before + 1

    def test_release_fix_counter_reset_only_by_task_advance(
        self,
        silence_all_stages,
        workflow_handler,
        state_manager,
        basic_task_state,
        mock_agent,
        mock_github_client,
        mock_pr_status,
    ):
        """A release-fix PR merge reaching 'releasing' keeps the counter; a normal
        advance (release passes) resets it to zero."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        state_manager.save_release_guide("# Release\n\n1. Check /health returns 200")
        basic_task_state.options.auto_merge = True
        basic_task_state.options.enable_release = True
        mock_github_client.get_pr_status.return_value = mock_pr_status

        # Release-fix PR merged: counter preserved while entering releasing
        basic_task_state.current_pr = 42
        basic_task_state.in_release_fix = True
        basic_task_state.release_fix_attempts = 2
        basic_task_state.workflow_stage = "merged"
        with patch.object(WorkflowStageHandler, "_checkout_branch", return_value=True):
            workflow_handler.handle_merged_stage(basic_task_state, MagicMock())
        assert basic_task_state.workflow_stage == "releasing"
        assert basic_task_state.release_fix_attempts == 2

        # Release verification now passes: advance resets the counter
        mock_agent.run_release_check.return_value = {
            "output": "RELEASE_CHECK: PASS",
            "success": True,
        }
        workflow_handler.handle_releasing_stage(basic_task_state)
        assert basic_task_state.workflow_stage == "working"
        assert basic_task_state.release_fix_attempts == 0
        assert basic_task_state.in_release_fix is False
