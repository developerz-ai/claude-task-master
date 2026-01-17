"""Tests for PR Cycle Manager wait_for_pr_ready functionality.

This module covers:
- wait_for_pr_ready method tests
- CI state handling (SUCCESS, FAILURE, PENDING, ERROR)
- Poll interval and multiple waiting cycles
"""

from unittest.mock import MagicMock, patch

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
# wait_for_pr_ready Tests
# =============================================================================


class TestWaitForPRReady:
    """Tests for wait_for_pr_ready method."""

    def test_ready_on_first_check_success(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
        """Test PR is ready immediately with SUCCESS CI state."""
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
        mock_github_client.get_pr_status.assert_called_once_with(123)

    def test_not_ready_with_unresolved_threads(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
        """Test PR not ready when there are unresolved threads."""
        mock_github_client.get_pr_status.return_value = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=3,
            check_details=[],
        )

        ready, reason = pr_cycle_manager.wait_for_pr_ready(
            pr_number=123,
            state=sample_task_state,
        )

        assert ready is False
        assert reason == "unresolved_comments"

    def test_not_ready_with_ci_failure(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
        """Test PR not ready when CI fails."""
        mock_github_client.get_pr_status.return_value = PRStatus(
            number=123,
            ci_state="FAILURE",
            unresolved_threads=0,
            check_details=[
                {
                    "name": "tests",
                    "conclusion": "FAILURE",
                    "url": "https://example.com/failure",
                }
            ],
        )

        ready, reason = pr_cycle_manager.wait_for_pr_ready(
            pr_number=123,
            state=sample_task_state,
        )

        assert ready is False
        assert reason.startswith("ci_failure:")
        assert "tests" in reason

    def test_not_ready_with_ci_error(self, pr_cycle_manager, mock_github_client, sample_task_state):
        """Test PR not ready when CI has error state."""
        mock_github_client.get_pr_status.return_value = PRStatus(
            number=123,
            ci_state="ERROR",
            unresolved_threads=0,
            check_details=[
                {
                    "name": "build",
                    "conclusion": "ERROR",
                    "url": "https://example.com/error",
                }
            ],
        )

        ready, reason = pr_cycle_manager.wait_for_pr_ready(
            pr_number=123,
            state=sample_task_state,
        )

        assert ready is False
        assert reason.startswith("ci_failure:")

    def test_waits_for_pending_ci(self, pr_cycle_manager, mock_github_client, sample_task_state):
        """Test that method waits when CI is pending then succeeds."""
        # First call returns PENDING, second returns SUCCESS
        mock_github_client.get_pr_status.side_effect = [
            PRStatus(
                number=123,
                ci_state="PENDING",
                unresolved_threads=0,
                check_details=[],
            ),
            PRStatus(
                number=123,
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            ),
        ]

        with patch("time.sleep") as mock_sleep:
            ready, reason = pr_cycle_manager.wait_for_pr_ready(
                pr_number=123,
                state=sample_task_state,
                poll_interval=5,  # Short interval for test
            )

        assert ready is True
        assert reason == "success"
        mock_sleep.assert_called_once_with(5)
        assert mock_github_client.get_pr_status.call_count == 2

    def test_custom_poll_interval(self, pr_cycle_manager, mock_github_client, sample_task_state):
        """Test that custom poll interval is used."""
        mock_github_client.get_pr_status.side_effect = [
            PRStatus(
                number=123,
                ci_state="PENDING",
                unresolved_threads=0,
                check_details=[],
            ),
            PRStatus(
                number=123,
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            ),
        ]

        with patch("time.sleep") as mock_sleep:
            pr_cycle_manager.wait_for_pr_ready(
                pr_number=123,
                state=sample_task_state,
                poll_interval=60,
            )

        mock_sleep.assert_called_once_with(60)

    def test_multiple_pending_cycles(self, pr_cycle_manager, mock_github_client, sample_task_state):
        """Test waiting through multiple pending cycles."""
        mock_github_client.get_pr_status.side_effect = [
            PRStatus(number=123, ci_state="PENDING", unresolved_threads=0, check_details=[]),
            PRStatus(number=123, ci_state="PENDING", unresolved_threads=0, check_details=[]),
            PRStatus(number=123, ci_state="PENDING", unresolved_threads=0, check_details=[]),
            PRStatus(number=123, ci_state="SUCCESS", unresolved_threads=0, check_details=[]),
        ]

        with patch("time.sleep") as mock_sleep:
            ready, reason = pr_cycle_manager.wait_for_pr_ready(
                pr_number=123,
                state=sample_task_state,
            )

        assert ready is True
        assert mock_sleep.call_count == 3
        assert mock_github_client.get_pr_status.call_count == 4
