"""Tests for PR Cycle Manager edge cases and integration scenarios.

This module covers:
- Edge cases for session limits and boundaries
- Full PR lifecycle integration tests
"""

from unittest.mock import MagicMock

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.github.client import PRStatus
from claude_task_master.github.pr_cycle import PRCycleManager


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_github_client():
    """Provide a mocked GitHubClient."""
    mock = MagicMock()
    mock.create_pr = MagicMock(return_value=123)
    mock.get_pr_status = MagicMock(
        return_value=PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[],
        )
    )
    mock.get_pr_comments = MagicMock(return_value="")
    mock.merge_pr = MagicMock()
    return mock


@pytest.fixture
def mock_state_manager():
    """Provide a mocked StateManager."""
    mock = MagicMock()
    mock.save_state = MagicMock()
    mock.load_context = MagicMock(return_value="Previous context")
    return mock


@pytest.fixture
def mock_agent():
    """Provide a mocked AgentWrapper."""
    mock = MagicMock()
    mock.run_work_session = MagicMock(return_value={"output": "Fixed the issues", "success": True})
    return mock


@pytest.fixture
def sample_task_state() -> TaskState:
    """Provide a sample TaskState for testing."""
    return TaskState(
        status="working",
        current_task_index=0,
        session_count=1,
        current_pr=None,
        created_at="2025-01-15T12:00:00",
        updated_at="2025-01-15T12:00:00",
        run_id="20250115-120000",
        model="sonnet",
        options=TaskOptions(
            auto_merge=True,
            max_sessions=10,
            pause_on_pr=False,
        ),
    )


@pytest.fixture
def pr_cycle_manager(
    mock_github_client,
    mock_state_manager,
    mock_agent,
) -> PRCycleManager:
    """Provide a PRCycleManager instance with mocked dependencies."""
    return PRCycleManager(
        github_client=mock_github_client,
        state_manager=mock_state_manager,
        agent=mock_agent,
    )


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestPRCycleEdgeCases:
    """Tests for edge cases in PR cycle management."""

    def test_handle_none_max_sessions(
        self, pr_cycle_manager, mock_github_client, mock_agent, sample_task_state
    ):
        """Test that None max_sessions means unlimited."""
        sample_task_state.options.max_sessions = None
        sample_task_state.session_count = 100  # High count

        mock_github_client.get_pr_status.side_effect = [
            PRStatus(
                number=123,
                ci_state="SUCCESS",
                unresolved_threads=1,
                check_details=[],
            ),
            PRStatus(
                number=123,
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            ),
        ]

        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=123,
            state=sample_task_state,
        )

        assert result is True  # Should succeed despite high session count

    def test_session_count_at_max_minus_one(
        self, pr_cycle_manager, mock_github_client, mock_agent, sample_task_state
    ):
        """Test handling when session count is at max - 1.

        After running a fix session (9 -> 10), max_sessions check kicks in,
        returning False even if the fix was successful. This is expected behavior
        to enforce session limits.
        """
        sample_task_state.session_count = 9
        sample_task_state.options.max_sessions = 10

        mock_github_client.get_pr_status.side_effect = [
            PRStatus(
                number=123,
                ci_state="SUCCESS",
                unresolved_threads=1,
                check_details=[],
            ),
            PRStatus(
                number=123,
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            ),
        ]

        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=123,
            state=sample_task_state,
        )

        # Returns False because after running fix session (9->10), max_sessions check kicks in
        assert result is False
        assert sample_task_state.session_count == 10

    def test_session_count_allows_one_more_fix_then_merge(
        self, pr_cycle_manager, mock_github_client, mock_agent, sample_task_state
    ):
        """Test that when session count + 1 is still under limit, we can fix and merge."""
        sample_task_state.session_count = 8  # Will go to 9 after fix
        sample_task_state.options.max_sessions = 10

        mock_github_client.get_pr_status.side_effect = [
            PRStatus(
                number=123,
                ci_state="SUCCESS",
                unresolved_threads=1,
                check_details=[],
            ),
            PRStatus(
                number=123,
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            ),
        ]

        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=123,
            state=sample_task_state,
        )

        # Should succeed - fix session runs (8->9), still under limit, then merges
        assert result is True
        assert sample_task_state.session_count == 9

    def test_multiple_fix_cycles(
        self, pr_cycle_manager, mock_github_client, mock_agent, sample_task_state
    ):
        """Test multiple consecutive fix cycles."""
        mock_github_client.get_pr_status.side_effect = [
            PRStatus(number=123, ci_state="SUCCESS", unresolved_threads=2, check_details=[]),
            PRStatus(number=123, ci_state="SUCCESS", unresolved_threads=1, check_details=[]),
            PRStatus(number=123, ci_state="SUCCESS", unresolved_threads=0, check_details=[]),
        ]
        mock_github_client.get_pr_comments.return_value = "Fix needed"

        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=123,
            state=sample_task_state,
        )

        assert result is True
        assert mock_agent.run_work_session.call_count == 2
        assert sample_task_state.session_count == 3  # Initial 1 + 2 fix sessions

    def test_ci_failure_then_success(
        self, pr_cycle_manager, mock_github_client, mock_agent, sample_task_state
    ):
        """Test CI failure followed by success after fix."""
        mock_github_client.get_pr_status.side_effect = [
            PRStatus(
                number=123,
                ci_state="FAILURE",
                unresolved_threads=0,
                check_details=[{"name": "tests", "conclusion": "FAILURE"}],
            ),
            PRStatus(
                number=123,
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            ),
        ]

        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=123,
            state=sample_task_state,
        )

        assert result is True
        mock_agent.run_work_session.assert_called_once()

    def test_zero_unresolved_threads(self, pr_cycle_manager, mock_github_client, sample_task_state):
        """Test handling when unresolved_threads is exactly 0."""
        mock_github_client.get_pr_status.return_value = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[],
        )

        ready, reason = pr_cycle_manager.wait_for_pr_ready(
            pr_number=123,
            state=sample_task_state,
        )

        assert ready is True
        assert reason == "success"


# =============================================================================
# Integration Tests
# =============================================================================


class TestPRCycleIntegration:
    """Integration tests for full PR cycle workflows."""

    def test_full_pr_lifecycle_happy_path(
        self, pr_cycle_manager, mock_github_client, mock_state_manager, sample_task_state
    ):
        """Test complete PR lifecycle from creation to merge."""
        # Create PR
        pr_number = pr_cycle_manager.create_or_update_pr(
            title="New Feature",
            body="Adds awesome feature",
            state=sample_task_state,
        )
        assert pr_number == 123
        assert sample_task_state.current_pr == 123

        # Handle cycle (immediate success)
        mock_github_client.get_pr_status.return_value = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[],
        )

        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=pr_number,
            state=sample_task_state,
        )

        assert result is True
        mock_github_client.merge_pr.assert_called_once_with(123)
        assert sample_task_state.current_pr is None

    def test_full_pr_lifecycle_with_review(
        self,
        pr_cycle_manager,
        mock_github_client,
        mock_state_manager,
        mock_agent,
        sample_task_state,
    ):
        """Test complete PR lifecycle with review comments."""
        # Create PR
        pr_number = pr_cycle_manager.create_or_update_pr(
            title="New Feature",
            body="Adds feature",
            state=sample_task_state,
        )

        # Configure mock for review cycle
        mock_github_client.get_pr_status.side_effect = [
            PRStatus(number=123, ci_state="SUCCESS", unresolved_threads=1, check_details=[]),
            PRStatus(number=123, ci_state="SUCCESS", unresolved_threads=0, check_details=[]),
        ]
        mock_github_client.get_pr_comments.return_value = "Please add tests"

        # Handle cycle
        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=pr_number,
            state=sample_task_state,
        )

        assert result is True
        mock_github_client.get_pr_comments.assert_called_once()
        mock_agent.run_work_session.assert_called_once()
        mock_github_client.merge_pr.assert_called_once()

    def test_full_pr_lifecycle_with_ci_fix(
        self,
        pr_cycle_manager,
        mock_github_client,
        mock_state_manager,
        mock_agent,
        sample_task_state,
    ):
        """Test complete PR lifecycle with CI failure fix."""
        # Create PR
        pr_number = pr_cycle_manager.create_or_update_pr(
            title="New Feature",
            body="Adds feature",
            state=sample_task_state,
        )

        # Configure mock for CI failure then success
        mock_github_client.get_pr_status.side_effect = [
            PRStatus(
                number=123,
                ci_state="FAILURE",
                unresolved_threads=0,
                check_details=[{"name": "tests", "conclusion": "FAILURE", "url": "https://ci.com"}],
            ),
            PRStatus(number=123, ci_state="SUCCESS", unresolved_threads=0, check_details=[]),
        ]

        # Handle cycle
        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=pr_number,
            state=sample_task_state,
        )

        assert result is True
        mock_agent.run_work_session.assert_called_once()
        # Verify CI failure info was passed
        call_kwargs = mock_agent.run_work_session.call_args[1]
        assert (
            "ci_failure" in call_kwargs["task_description"].lower()
            or "CI" in call_kwargs["task_description"]
        )
