"""Tests for StateRecovery - GitHub state detection and recovery.

This module contains tests for the StateRecovery class which handles:
- Detecting real workflow state from GitHub PR status
- Recovering state from GitHub when local state is stale/missing
- Applying recovered state to TaskState
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.state_recovery import RecoveredState, StateRecovery

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# RecoveredState Tests
# =============================================================================


class TestRecoveredState:
    """Tests for RecoveredState dataclass."""

    def test_create_with_all_fields(self):
        """Test creating RecoveredState with all fields."""
        state = RecoveredState(
            workflow_stage="working",
            current_pr=123,
            message="Test message",
        )
        assert state.workflow_stage == "working"
        assert state.current_pr == 123
        assert state.message == "Test message"

    def test_create_with_none_pr(self):
        """Test creating RecoveredState with None PR number."""
        state = RecoveredState(
            workflow_stage="working",
            current_pr=None,
            message="No PR found",
        )
        assert state.workflow_stage == "working"
        assert state.current_pr is None
        assert state.message == "No PR found"

    def test_workflow_stage_types(self):
        """Test all valid workflow stage types."""
        stages = ["working", "ci_failed", "waiting_ci", "addressing_reviews", "ready_to_merge"]
        for stage in stages:
            state = RecoveredState(
                workflow_stage=stage,  # type: ignore[arg-type]
                current_pr=1,
                message=f"Stage: {stage}",
            )
            assert state.workflow_stage == stage

    def test_dataclass_equality(self):
        """Test that dataclass equality works correctly."""
        state1 = RecoveredState(workflow_stage="working", current_pr=123, message="Test")
        state2 = RecoveredState(workflow_stage="working", current_pr=123, message="Test")
        assert state1 == state2

    def test_dataclass_inequality(self):
        """Test that different states are not equal."""
        state1 = RecoveredState(workflow_stage="working", current_pr=123, message="Test")
        state2 = RecoveredState(workflow_stage="ci_failed", current_pr=123, message="Test")
        assert state1 != state2


# =============================================================================
# StateRecovery Initialization Tests
# =============================================================================


class TestStateRecoveryInitialization:
    """Tests for StateRecovery initialization."""

    def test_init_without_client(self):
        """Test initialization without GitHub client."""
        recovery = StateRecovery()
        assert recovery._github_client is None

    def test_init_with_client(self):
        """Test initialization with provided GitHub client."""
        mock_client = MagicMock()
        recovery = StateRecovery(github_client=mock_client)
        assert recovery._github_client is mock_client

    def test_lazy_client_initialization(self):
        """Test that GitHub client is lazily initialized."""
        # Patch the import location inside the github module
        with patch("claude_task_master.github.GitHubClient") as mock_gh:
            mock_client = MagicMock()
            mock_gh.return_value = mock_client

            recovery = StateRecovery()
            # Client should not be created yet
            mock_gh.assert_not_called()

            # Access the property to trigger lazy init
            client = recovery.github_client

            mock_gh.assert_called_once()
            assert client is mock_client

    def test_github_client_property_returns_injected_client(self):
        """Test that github_client property returns injected client."""
        mock_client = MagicMock()
        recovery = StateRecovery(github_client=mock_client)

        # Since we injected a client, it shouldn't try to import or create a new one
        client = recovery.github_client
        assert client is mock_client


# =============================================================================
# detect_real_state - No PR Found Tests
# =============================================================================


class TestDetectRealStateNoPR:
    """Tests for detect_real_state when no PR is found."""

    def test_no_pr_returns_working_stage(self, temp_dir: Path):
        """Test that no PR returns working stage."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = None

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert result.workflow_stage == "working"
        assert result.current_pr is None
        assert "No open PR found" in result.message

    def test_no_pr_calls_github_client_with_cwd(self, temp_dir: Path):
        """Test that cwd is passed to GitHub client."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = None

        recovery = StateRecovery(github_client=mock_client)
        recovery.detect_real_state(cwd=str(temp_dir))

        mock_client.get_pr_for_current_branch.assert_called_once_with(cwd=str(temp_dir))

    def test_no_cwd_uses_current_dir(self):
        """Test that None cwd defaults to current directory."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = None

        recovery = StateRecovery(github_client=mock_client)

        with patch("os.getcwd") as mock_getcwd:
            mock_getcwd.return_value = "/some/path"
            recovery.detect_real_state(cwd=None)

            mock_client.get_pr_for_current_branch.assert_called_once_with(cwd="/some/path")


# =============================================================================
# detect_real_state - CI Failure Tests
# =============================================================================


class TestDetectRealStateCIFailure:
    """Tests for detect_real_state with CI failures."""

    def test_ci_failure_returns_ci_failed_stage(self, temp_dir: Path):
        """Test that CI failure returns ci_failed stage."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 123
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="FAILURE",
            unresolved_threads=0,
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert result.workflow_stage == "ci_failed"
        assert result.current_pr == 123
        assert "CI failure" in result.message

    def test_ci_error_returns_ci_failed_stage(self, temp_dir: Path):
        """Test that CI error returns ci_failed stage."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 456
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="ERROR",
            unresolved_threads=0,
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert result.workflow_stage == "ci_failed"
        assert result.current_pr == 456

    def test_ci_failure_message_includes_pr_number(self, temp_dir: Path):
        """Test that CI failure message includes PR number."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 789
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="FAILURE",
            unresolved_threads=0,
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert "#789" in result.message


# =============================================================================
# detect_real_state - CI Pending Tests
# =============================================================================


class TestDetectRealStateCIPending:
    """Tests for detect_real_state with CI pending."""

    def test_ci_pending_returns_waiting_ci_stage(self, temp_dir: Path):
        """Test that CI pending returns waiting_ci stage."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 100
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="PENDING",
            unresolved_threads=0,
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert result.workflow_stage == "waiting_ci"
        assert result.current_pr == 100
        assert "pending" in result.message.lower()

    def test_ci_pending_message_includes_pr_number(self, temp_dir: Path):
        """Test that CI pending message includes PR number."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 200
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="PENDING",
            unresolved_threads=0,
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert "#200" in result.message


# =============================================================================
# detect_real_state - Unresolved Reviews Tests
# =============================================================================


class TestDetectRealStateUnresolvedReviews:
    """Tests for detect_real_state with unresolved reviews."""

    def test_unresolved_reviews_returns_addressing_reviews_stage(self, temp_dir: Path):
        """Test that unresolved reviews returns addressing_reviews stage."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 300
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="SUCCESS",
            unresolved_threads=3,
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert result.workflow_stage == "addressing_reviews"
        assert result.current_pr == 300
        assert "unresolved" in result.message.lower()

    def test_unresolved_reviews_message_includes_count(self, temp_dir: Path):
        """Test that unresolved reviews message includes count."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 400
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="SUCCESS",
            unresolved_threads=5,
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert "5" in result.message

    def test_one_unresolved_review(self, temp_dir: Path):
        """Test with exactly one unresolved review."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 500
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="SUCCESS",
            unresolved_threads=1,
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert result.workflow_stage == "addressing_reviews"
        assert "1" in result.message


# =============================================================================
# detect_real_state - Ready to Merge Tests
# =============================================================================


class TestDetectRealStateReadyToMerge:
    """Tests for detect_real_state when PR is ready to merge."""

    def test_ci_passed_no_reviews_returns_ready_to_merge(self, temp_dir: Path):
        """Test that CI passed with no unresolved reviews returns ready_to_merge."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 600
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="SUCCESS",
            unresolved_threads=0,
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert result.workflow_stage == "ready_to_merge"
        assert result.current_pr == 600
        assert "ready to merge" in result.message.lower()

    def test_ready_to_merge_message_includes_pr_number(self, temp_dir: Path):
        """Test that ready to merge message includes PR number."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 700
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="SUCCESS",
            unresolved_threads=0,
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert "#700" in result.message


# =============================================================================
# detect_real_state - Exception Handling Tests
# =============================================================================


class TestDetectRealStateExceptionHandling:
    """Tests for detect_real_state exception handling."""

    def test_exception_returns_working_stage(self, temp_dir: Path):
        """Test that exceptions return working stage."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.side_effect = Exception("API error")

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert result.workflow_stage == "working"
        assert result.current_pr is None
        assert "Could not detect" in result.message

    def test_exception_message_includes_error(self, temp_dir: Path):
        """Test that exception message includes error details."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.side_effect = ValueError("Invalid branch")

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert "Invalid branch" in result.message

    def test_pr_status_exception_returns_working(self, temp_dir: Path):
        """Test that get_pr_status exception returns working stage."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 800
        mock_client.get_pr_status.side_effect = RuntimeError("Status check failed")

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        assert result.workflow_stage == "working"
        assert result.current_pr is None
        assert "Status check failed" in result.message


# =============================================================================
# apply_recovery Tests
# =============================================================================


class TestApplyRecovery:
    """Tests for apply_recovery method."""

    def _create_task_state(self) -> TaskState:
        """Create a TaskState for testing."""
        timestamp = datetime.now().isoformat()
        return TaskState(
            status="planning",
            current_task_index=0,
            session_count=0,
            current_pr=None,
            created_at=timestamp,
            updated_at=timestamp,
            run_id="test-run",
            model="sonnet",
            options=TaskOptions(),
        )

    def test_apply_recovery_updates_workflow_stage(self, temp_dir: Path):
        """Test that apply_recovery updates workflow_stage."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 123
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="FAILURE",
            unresolved_threads=0,
        )

        state = self._create_task_state()
        recovery = StateRecovery(github_client=mock_client)

        result = recovery.apply_recovery(state, cwd=str(temp_dir))

        assert state.workflow_stage == "ci_failed"
        assert result.workflow_stage == "ci_failed"

    def test_apply_recovery_updates_current_pr(self, temp_dir: Path):
        """Test that apply_recovery updates current_pr."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 456
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="SUCCESS",
            unresolved_threads=0,
        )

        state = self._create_task_state()
        recovery = StateRecovery(github_client=mock_client)

        result = recovery.apply_recovery(state, cwd=str(temp_dir))

        assert state.current_pr == 456
        assert result.current_pr == 456

    def test_apply_recovery_sets_status_to_working(self, temp_dir: Path):
        """Test that apply_recovery sets status to working."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 789
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="PENDING",
            unresolved_threads=0,
        )

        state = self._create_task_state()
        state.status = "blocked"
        recovery = StateRecovery(github_client=mock_client)

        recovery.apply_recovery(state, cwd=str(temp_dir))

        assert state.status == "working"

    def test_apply_recovery_returns_recovered_state(self, temp_dir: Path):
        """Test that apply_recovery returns RecoveredState."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 100
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="SUCCESS",
            unresolved_threads=2,
        )

        state = self._create_task_state()
        recovery = StateRecovery(github_client=mock_client)

        result = recovery.apply_recovery(state, cwd=str(temp_dir))

        assert isinstance(result, RecoveredState)
        assert result.workflow_stage == "addressing_reviews"
        assert result.current_pr == 100

    def test_apply_recovery_no_pr_found(self, temp_dir: Path):
        """Test apply_recovery when no PR is found."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = None

        state = self._create_task_state()
        state.current_pr = 999  # Existing PR in state
        recovery = StateRecovery(github_client=mock_client)

        result = recovery.apply_recovery(state, cwd=str(temp_dir))

        assert state.current_pr is None
        assert state.workflow_stage == "working"
        assert result.current_pr is None

    def test_apply_recovery_handles_exception(self, temp_dir: Path):
        """Test apply_recovery handles exceptions gracefully."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.side_effect = Exception("Network error")

        state = self._create_task_state()
        recovery = StateRecovery(github_client=mock_client)

        result = recovery.apply_recovery(state, cwd=str(temp_dir))

        # Should still update state to working
        assert state.status == "working"
        assert state.workflow_stage == "working"
        assert state.current_pr is None
        assert "Network error" in result.message

    def test_apply_recovery_uses_default_cwd(self):
        """Test that apply_recovery uses current directory when cwd is None."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = None

        state = self._create_task_state()
        recovery = StateRecovery(github_client=mock_client)

        with patch("os.getcwd") as mock_getcwd:
            mock_getcwd.return_value = "/test/path"
            recovery.apply_recovery(state, cwd=None)

            # Should have called detect_real_state which uses os.getcwd()
            mock_client.get_pr_for_current_branch.assert_called_once_with(cwd="/test/path")


# =============================================================================
# State Recovery Priority Tests (CI status takes precedence)
# =============================================================================


class TestStateRecoveryPriority:
    """Tests for state detection priority order."""

    def test_ci_failure_takes_precedence_over_unresolved_reviews(self, temp_dir: Path):
        """Test that CI failure is detected even with unresolved reviews."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 123
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="FAILURE",
            unresolved_threads=5,  # Has unresolved reviews too
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        # Should return ci_failed, not addressing_reviews
        assert result.workflow_stage == "ci_failed"

    def test_ci_pending_takes_precedence_over_unresolved_reviews(self, temp_dir: Path):
        """Test that CI pending is detected even with unresolved reviews."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 123
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="PENDING",
            unresolved_threads=3,  # Has unresolved reviews too
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        # Should return waiting_ci, not addressing_reviews
        assert result.workflow_stage == "waiting_ci"

    def test_unresolved_reviews_takes_precedence_over_ready_to_merge(self, temp_dir: Path):
        """Test that unresolved reviews prevent ready_to_merge detection."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 123
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="SUCCESS",
            unresolved_threads=1,  # One unresolved review
        )

        recovery = StateRecovery(github_client=mock_client)
        result = recovery.detect_real_state(cwd=str(temp_dir))

        # Should return addressing_reviews, not ready_to_merge
        assert result.workflow_stage == "addressing_reviews"


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestStateRecoveryIntegration:
    """Integration-style tests for StateRecovery."""

    def test_full_recovery_workflow(self, temp_dir: Path):
        """Test full recovery workflow from detection to application."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 999
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="SUCCESS",
            unresolved_threads=0,
        )

        timestamp = datetime.now().isoformat()
        state = TaskState(
            status="blocked",
            current_task_index=5,
            session_count=10,
            current_pr=100,  # Different PR
            created_at=timestamp,
            updated_at=timestamp,
            run_id="test-run",
            model="sonnet",
            options=TaskOptions(),
            workflow_stage="ci_failed",  # Was stuck on CI failure
        )

        recovery = StateRecovery(github_client=mock_client)

        # First detect
        detected = recovery.detect_real_state(cwd=str(temp_dir))
        assert detected.workflow_stage == "ready_to_merge"
        assert detected.current_pr == 999

        # Then apply
        applied = recovery.apply_recovery(state, cwd=str(temp_dir))

        # State should be updated
        assert state.workflow_stage == "ready_to_merge"
        assert state.current_pr == 999
        assert state.status == "working"

        # Returned state should match detected
        assert applied.workflow_stage == "ready_to_merge"

    def test_recovery_preserves_other_state_fields(self, temp_dir: Path):
        """Test that recovery only updates relevant fields."""
        mock_client = MagicMock()
        mock_client.get_pr_for_current_branch.return_value = 123
        mock_client.get_pr_status.return_value = MagicMock(
            ci_state="SUCCESS",
            unresolved_threads=0,
        )

        timestamp = datetime.now().isoformat()
        state = TaskState(
            status="blocked",
            current_task_index=5,
            session_count=10,
            current_pr=100,
            created_at=timestamp,
            updated_at=timestamp,
            run_id="original-run-id",
            model="opus",
            options=TaskOptions(auto_merge=False, max_sessions=50),
        )

        recovery = StateRecovery(github_client=mock_client)
        recovery.apply_recovery(state, cwd=str(temp_dir))

        # These fields should be updated
        assert state.status == "working"
        assert state.current_pr == 123
        assert state.workflow_stage == "ready_to_merge"

        # These fields should NOT be changed
        assert state.current_task_index == 5
        assert state.session_count == 10
        assert state.run_id == "original-run-id"
        assert state.model == "opus"
        assert state.options.auto_merge is False
        assert state.options.max_sessions == 50
