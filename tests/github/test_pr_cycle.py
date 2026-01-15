"""Comprehensive tests for the PR Cycle Manager module."""

import pytest
import time
from unittest.mock import MagicMock, patch, call
from typing import Any

from claude_task_master.github.pr_cycle import PRCycleManager
from claude_task_master.github.client import PRStatus
from claude_task_master.core.state import TaskState, TaskOptions


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
    mock.run_work_session = MagicMock(
        return_value={"output": "Fixed the issues", "success": True}
    )
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
def sample_task_state_with_pr(sample_task_state: TaskState) -> TaskState:
    """Provide a sample TaskState with existing PR."""
    sample_task_state.current_pr = 456
    return sample_task_state


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
# PRCycleManager Initialization Tests
# =============================================================================


class TestPRCycleManagerInit:
    """Tests for PRCycleManager initialization."""

    def test_init_with_all_dependencies(
        self, mock_github_client, mock_state_manager, mock_agent
    ):
        """Test initialization with all required dependencies."""
        manager = PRCycleManager(
            github_client=mock_github_client,
            state_manager=mock_state_manager,
            agent=mock_agent,
        )
        assert manager.github is mock_github_client
        assert manager.state_manager is mock_state_manager
        assert manager.agent is mock_agent

    def test_init_stores_references(
        self, mock_github_client, mock_state_manager, mock_agent
    ):
        """Test that initialization stores references correctly."""
        manager = PRCycleManager(
            github_client=mock_github_client,
            state_manager=mock_state_manager,
            agent=mock_agent,
        )
        # Verify the dependencies are accessible
        assert hasattr(manager, "github")
        assert hasattr(manager, "state_manager")
        assert hasattr(manager, "agent")


# =============================================================================
# create_or_update_pr Tests
# =============================================================================


class TestCreateOrUpdatePR:
    """Tests for create_or_update_pr method."""

    def test_create_new_pr(
        self, pr_cycle_manager, mock_github_client, mock_state_manager, sample_task_state
    ):
        """Test creating a new PR when none exists."""
        pr_number = pr_cycle_manager.create_or_update_pr(
            title="Test PR",
            body="Test PR body",
            state=sample_task_state,
        )

        assert pr_number == 123
        mock_github_client.create_pr.assert_called_once_with(
            title="Test PR",
            body="Test PR body",
        )
        # Verify state was updated
        assert sample_task_state.current_pr == 123
        mock_state_manager.save_state.assert_called_once_with(sample_task_state)

    def test_return_existing_pr_without_creating(
        self, pr_cycle_manager, mock_github_client, sample_task_state_with_pr
    ):
        """Test returning existing PR number without creating new one."""
        pr_number = pr_cycle_manager.create_or_update_pr(
            title="Test PR",
            body="Test PR body",
            state=sample_task_state_with_pr,
        )

        assert pr_number == 456  # Existing PR number
        mock_github_client.create_pr.assert_not_called()

    def test_create_pr_with_special_characters(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
        """Test creating PR with special characters in title and body."""
        pr_cycle_manager.create_or_update_pr(
            title="Fix: Bug #123 & improve performance",
            body="## Summary\n- Added feature\n- Fixed bug",
            state=sample_task_state,
        )

        mock_github_client.create_pr.assert_called_once_with(
            title="Fix: Bug #123 & improve performance",
            body="## Summary\n- Added feature\n- Fixed bug",
        )

    def test_create_pr_with_unicode(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
        """Test creating PR with unicode content."""
        pr_cycle_manager.create_or_update_pr(
            title="Fix: 日本語 and emoji 🎉",
            body="Contains unicode: αβγ 中文",
            state=sample_task_state,
        )

        mock_github_client.create_pr.assert_called_once()

    def test_create_pr_saves_state_after_creation(
        self, pr_cycle_manager, mock_state_manager, sample_task_state
    ):
        """Test that state is saved after PR creation."""
        pr_cycle_manager.create_or_update_pr(
            title="Test",
            body="Body",
            state=sample_task_state,
        )

        # Verify save_state was called with updated state
        mock_state_manager.save_state.assert_called_once()
        saved_state = mock_state_manager.save_state.call_args[0][0]
        assert saved_state.current_pr == 123


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

    def test_not_ready_with_ci_error(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
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

    def test_waits_for_pending_ci(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
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

    def test_custom_poll_interval(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
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

    def test_multiple_pending_cycles(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
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
        assert "ci_failure" in call_args[1]["task_description"].lower() or "CI" in call_args[1]["task_description"]

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

    def test_handles_pr_comments_issue(
        self, pr_cycle_manager, mock_agent, sample_task_state
    ):
        """Test handling PR comments as issue description."""
        pr_cycle_manager._run_fix_session(
            state=sample_task_state,
            issue_description="Address PR comments:\n\n**reviewer**: Please fix indentation",
        )

        call_args = mock_agent.run_work_session.call_args
        assert "PR comments" in call_args[1]["task_description"]

    def test_handles_ci_failure_issue(
        self, pr_cycle_manager, mock_agent, sample_task_state
    ):
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


# =============================================================================
# Edge Cases and Integration Tests
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

    def test_zero_unresolved_threads(
        self, pr_cycle_manager, mock_github_client, sample_task_state
    ):
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
        assert "ci_failure" in call_kwargs["task_description"].lower() or "CI" in call_kwargs["task_description"]
