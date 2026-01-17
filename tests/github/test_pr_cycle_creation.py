"""Tests for PR Cycle Manager initialization and PR creation.

This module covers:
- PRCycleManager initialization tests
- create_or_update_pr method tests
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

    def test_init_with_all_dependencies(self, mock_github_client, mock_state_manager, mock_agent):
        """Test initialization with all required dependencies."""
        manager = PRCycleManager(
            github_client=mock_github_client,
            state_manager=mock_state_manager,
            agent=mock_agent,
        )
        assert manager.github is mock_github_client
        assert manager.state_manager is mock_state_manager
        assert manager.agent is mock_agent

    def test_init_stores_references(self, mock_github_client, mock_state_manager, mock_agent):
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

    def test_create_pr_with_unicode(self, pr_cycle_manager, mock_github_client, sample_task_state):
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
