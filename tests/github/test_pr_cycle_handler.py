"""Tests for PR Cycle Manager handle_pr_cycle functionality.

This module covers:
- handle_pr_cycle method tests
- Auto-merge behavior
- CI failure and comment handling
- Max sessions limit
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
# handle_pr_cycle Tests
# =============================================================================


class TestHandlePRCycle:
    """Tests for handle_pr_cycle method."""

    def test_merge_when_ready_and_auto_merge_enabled(
        self, pr_cycle_manager, mock_github_client, mock_state_manager, sample_task_state
    ):
        """Test PR is merged when ready and auto_merge is enabled."""
        mock_github_client.get_pr_status.return_value = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[],
        )

        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=123,
            state=sample_task_state,
        )

        assert result is True
        mock_github_client.merge_pr.assert_called_once_with(123)
        # Verify PR was cleared from state
        assert sample_task_state.current_pr is None
        mock_state_manager.save_state.assert_called_once_with(sample_task_state)

    def test_no_merge_when_auto_merge_disabled(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
        """Test PR is not merged when auto_merge is disabled."""
        sample_task_state.options.auto_merge = False
        mock_github_client.get_pr_status.return_value = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[],
        )

        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=123,
            state=sample_task_state,
        )

        assert result is False
        mock_github_client.merge_pr.assert_not_called()

    def test_handles_unresolved_comments(
        self, pr_cycle_manager, mock_github_client, mock_agent, sample_task_state
    ):
        """Test handling unresolved comments triggers fix session."""
        # First call has unresolved comments, second call is success
        mock_github_client.get_pr_status.side_effect = [
            PRStatus(
                number=123,
                ci_state="SUCCESS",
                unresolved_threads=2,
                check_details=[],
            ),
            PRStatus(
                number=123,
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            ),
        ]
        mock_github_client.get_pr_comments.return_value = "Please fix the indentation"

        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=123,
            state=sample_task_state,
        )

        assert result is True
        mock_github_client.get_pr_comments.assert_called_once_with(123)
        mock_agent.run_work_session.assert_called_once()
        # Verify session count was incremented
        assert sample_task_state.session_count == 2

    def test_handles_ci_failure(
        self, pr_cycle_manager, mock_github_client, mock_agent, sample_task_state
    ):
        """Test handling CI failure triggers fix session."""
        # First call has CI failure, second call is success
        mock_github_client.get_pr_status.side_effect = [
            PRStatus(
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
        # Verify CI failure info was passed to agent
        call_args = mock_agent.run_work_session.call_args
        assert (
            "ci_failure" in call_args[1]["task_description"].lower()
            or "CI" in call_args[1]["task_description"]
        )

    def test_respects_max_sessions_limit(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
        """Test that max_sessions limit is respected."""
        sample_task_state.session_count = 10  # Already at max
        sample_task_state.options.max_sessions = 10
        mock_github_client.get_pr_status.return_value = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=2,  # Has issues
            check_details=[],
        )

        result = pr_cycle_manager.handle_pr_cycle(
            pr_number=123,
            state=sample_task_state,
        )

        assert result is False

    def test_returns_false_on_unknown_issue(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
        """Test that unknown issues return False."""
        # Create a custom wait_for_pr_ready return
        with patch.object(
            pr_cycle_manager, "wait_for_pr_ready", return_value=(False, "unknown_issue")
        ):
            result = pr_cycle_manager.handle_pr_cycle(
                pr_number=123,
                state=sample_task_state,
            )

        assert result is False
