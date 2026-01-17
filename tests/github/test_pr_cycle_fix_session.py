"""Tests for PR Cycle Manager fix session and CI failure formatting.

This module covers:
- _run_fix_session method tests
- _format_ci_failure method tests
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
# _run_fix_session Tests
# =============================================================================


class TestRunFixSession:
    """Tests for _run_fix_session method."""

    def test_loads_context_and_runs_agent(
        self, pr_cycle_manager, mock_state_manager, mock_agent, sample_task_state
    ):
        """Test that fix session loads context and runs agent."""
        mock_state_manager.load_context.return_value = "Accumulated context"

        pr_cycle_manager._run_fix_session(
            state=sample_task_state,
            issue_description="Fix the failing tests",
        )

        mock_state_manager.load_context.assert_called_once()
        mock_agent.run_work_session.assert_called_once_with(
            task_description="Fix the failing tests",
            context="Accumulated context",
        )

    def test_increments_session_count(
        self, pr_cycle_manager, mock_state_manager, sample_task_state
    ):
        """Test that session count is incremented after fix session."""
        initial_count = sample_task_state.session_count

        pr_cycle_manager._run_fix_session(
            state=sample_task_state,
            issue_description="Fix something",
        )

        assert sample_task_state.session_count == initial_count + 1

    def test_saves_state_after_session(
        self, pr_cycle_manager, mock_state_manager, sample_task_state
    ):
        """Test that state is saved after fix session."""
        pr_cycle_manager._run_fix_session(
            state=sample_task_state,
            issue_description="Fix something",
        )

        mock_state_manager.save_state.assert_called_once_with(sample_task_state)

    def test_handles_pr_comments_issue(self, pr_cycle_manager, mock_agent, sample_task_state):
        """Test handling PR comments as issue description."""
        pr_cycle_manager._run_fix_session(
            state=sample_task_state,
            issue_description="Address PR comments:\n\n**reviewer**: Please fix indentation",
        )

        call_args = mock_agent.run_work_session.call_args
        assert "PR comments" in call_args[1]["task_description"]

    def test_handles_ci_failure_issue(self, pr_cycle_manager, mock_agent, sample_task_state):
        """Test handling CI failure as issue description."""
        pr_cycle_manager._run_fix_session(
            state=sample_task_state,
            issue_description="Fix CI failures:\n\nci_failure:\n- tests: FAILURE",
        )

        call_args = mock_agent.run_work_session.call_args
        assert "CI failures" in call_args[1]["task_description"]


# =============================================================================
# _format_ci_failure Tests
# =============================================================================


class TestFormatCIFailure:
    """Tests for _format_ci_failure method."""

    def test_format_single_failure(self, pr_cycle_manager):
        """Test formatting a single CI failure."""
        status = PRStatus(
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

        result = pr_cycle_manager._format_ci_failure(status)

        assert "ci_failure:" in result
        assert "tests" in result
        assert "FAILURE" in result
        assert "https://example.com/failure" in result

    def test_format_multiple_failures(self, pr_cycle_manager):
        """Test formatting multiple CI failures."""
        status = PRStatus(
            number=123,
            ci_state="FAILURE",
            unresolved_threads=0,
            check_details=[
                {
                    "name": "unit-tests",
                    "conclusion": "FAILURE",
                    "url": "https://example.com/unit",
                },
                {
                    "name": "lint",
                    "conclusion": "SUCCESS",
                    "url": "https://example.com/lint",
                },
                {
                    "name": "integration-tests",
                    "conclusion": "FAILURE",
                    "url": "https://example.com/integration",
                },
            ],
        )

        result = pr_cycle_manager._format_ci_failure(status)

        assert "unit-tests" in result
        assert "integration-tests" in result
        # SUCCESS check should not be included
        assert "lint" not in result

    def test_format_failure_with_error_state(self, pr_cycle_manager):
        """Test formatting CI check with ERROR state."""
        status = PRStatus(
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

        result = pr_cycle_manager._format_ci_failure(status)

        assert "build" in result
        assert "ERROR" in result

    def test_format_failure_without_url(self, pr_cycle_manager):
        """Test formatting failure without URL."""
        status = PRStatus(
            number=123,
            ci_state="FAILURE",
            unresolved_threads=0,
            check_details=[
                {
                    "name": "tests",
                    "conclusion": "FAILURE",
                }
            ],
        )

        result = pr_cycle_manager._format_ci_failure(status)

        assert "tests" in result
        assert "FAILURE" in result
        # URL should not appear
        assert "URL:" not in result

    def test_format_failure_with_empty_check_details(self, pr_cycle_manager):
        """Test formatting failure with empty check details."""
        status = PRStatus(
            number=123,
            ci_state="FAILURE",
            unresolved_threads=0,
            check_details=[],
        )

        result = pr_cycle_manager._format_ci_failure(status)

        # Should just have the header
        assert result == "ci_failure:"

    def test_format_excludes_success_and_pending(self, pr_cycle_manager):
        """Test that SUCCESS and PENDING checks are excluded."""
        status = PRStatus(
            number=123,
            ci_state="FAILURE",
            unresolved_threads=0,
            check_details=[
                {
                    "name": "passing-test",
                    "conclusion": "SUCCESS",
                    "url": "https://example.com/pass",
                },
                {
                    "name": "pending-test",
                    "conclusion": "PENDING",
                    "url": "https://example.com/pending",
                },
                {
                    "name": "failing-test",
                    "conclusion": "FAILURE",
                    "url": "https://example.com/fail",
                },
            ],
        )

        result = pr_cycle_manager._format_ci_failure(status)

        assert "passing-test" not in result
        assert "pending-test" not in result
        assert "failing-test" in result
