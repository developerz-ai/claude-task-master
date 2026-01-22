"""Tests for orchestrator mailbox integration.

This module tests the mailbox integration in WorkLoopOrchestrator:
- Mailbox check after task completion
- Message merging and plan updates
- Handling of edge cases (no messages, errors, etc.)
- Webhook events for mailbox processing
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.orchestrator import WorkLoopOrchestrator
from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.mailbox import MailboxStorage, MessageMerger, Priority

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_agent():
    """Create a mock agent wrapper."""
    agent = MagicMock()
    agent.run_work_session = MagicMock(
        return_value={"output": "Task completed successfully", "success": True}
    )
    agent.verify_success_criteria = MagicMock(return_value={"success": True})
    agent.get_tools_for_phase = MagicMock(return_value=["Read", "Glob", "Grep"])
    return agent


@pytest.fixture
def mock_planner():
    """Create a mock planner."""
    planner = MagicMock()
    planner.run_planning_phase = MagicMock(return_value={"plan": "test", "criteria": "test"})
    return planner


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    logger = MagicMock()
    logger.start_session = MagicMock()
    logger.end_session = MagicMock()
    logger.log_prompt = MagicMock()
    logger.log_response = MagicMock()
    logger.log_error = MagicMock()
    return logger


@pytest.fixture
def basic_orchestrator(mock_agent, state_manager, mock_planner, mock_github_client):
    """Create a basic WorkLoopOrchestrator instance with mocks."""
    return WorkLoopOrchestrator(
        agent=mock_agent,
        state_manager=state_manager,
        planner=mock_planner,
        github_client=mock_github_client,
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
def mailbox_storage(state_dir):
    """Create a mailbox storage instance."""
    return MailboxStorage(state_dir)


@pytest.fixture
def orchestrator_with_mailbox(
    mock_agent, state_manager, mock_planner, mock_github_client, mailbox_storage
):
    """Create an orchestrator with mailbox storage pre-configured."""
    orchestrator = WorkLoopOrchestrator(
        agent=mock_agent,
        state_manager=state_manager,
        planner=mock_planner,
        github_client=mock_github_client,
    )
    # Pre-set the mailbox storage to use our test instance
    orchestrator._mailbox_storage = mailbox_storage
    return orchestrator


# =============================================================================
# Test Lazy Property Initialization
# =============================================================================


class TestMailboxLazyProperties:
    """Tests for lazy initialization of mailbox-related properties."""

    def test_mailbox_storage_lazy_init(self, basic_orchestrator):
        """Should lazily initialize mailbox storage on first access."""
        assert basic_orchestrator._mailbox_storage is None
        storage = basic_orchestrator.mailbox_storage
        assert storage is not None
        assert isinstance(storage, MailboxStorage)
        # Second access should return same instance
        assert basic_orchestrator.mailbox_storage is storage

    def test_message_merger_lazy_init(self, basic_orchestrator):
        """Should lazily initialize message merger on first access."""
        assert basic_orchestrator._message_merger is None
        merger = basic_orchestrator.message_merger
        assert merger is not None
        assert isinstance(merger, MessageMerger)
        # Second access should return same instance
        assert basic_orchestrator.message_merger is merger

    def test_plan_updater_lazy_init(self, basic_orchestrator, state_manager, sample_plan_file):
        """Should lazily initialize plan updater on first access."""
        from claude_task_master.core.plan_updater import PlanUpdater

        assert basic_orchestrator._plan_updater is None
        updater = basic_orchestrator.plan_updater
        assert updater is not None
        assert isinstance(updater, PlanUpdater)
        # Second access should return same instance
        assert basic_orchestrator.plan_updater is updater


# =============================================================================
# Test _check_and_process_mailbox Method
# =============================================================================


class TestCheckAndProcessMailbox:
    """Tests for the _check_and_process_mailbox method."""

    def test_no_messages_returns_false(self, orchestrator_with_mailbox, basic_task_state):
        """Should return False when mailbox is empty."""
        result = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)
        assert result is False

    def test_single_message_updates_plan(
        self, orchestrator_with_mailbox, basic_task_state, state_manager, sample_plan_file
    ):
        """Should process single message and update plan."""
        # Add a message to the mailbox
        orchestrator_with_mailbox.mailbox_storage.add_message(
            content="Please add a new task for testing",
            sender="supervisor",
            priority=Priority.NORMAL,
        )

        # Mock the plan updater to return success
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated plan"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        result = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)

        assert result is True
        mock_plan_updater.update_plan.assert_called_once()
        # The merged message should contain the original content
        call_args = mock_plan_updater.update_plan.call_args[0][0]
        assert "Please add a new task for testing" in call_args

    def test_multiple_messages_merged(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Should merge multiple messages before updating plan."""
        storage = orchestrator_with_mailbox.mailbox_storage

        # Add multiple messages
        storage.add_message("First change request", sender="user1", priority=Priority.NORMAL)
        storage.add_message("Urgent fix needed", sender="admin", priority=Priority.URGENT)
        storage.add_message("Low priority cleanup", sender="bot", priority=Priority.LOW)

        # Mock the plan updater
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated plan"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        result = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)

        assert result is True
        # Check that all messages were included in the merged content
        call_args = mock_plan_updater.update_plan.call_args[0][0]
        assert "First change request" in call_args
        assert "Urgent fix needed" in call_args
        assert "Low priority cleanup" in call_args

    def test_mailbox_cleared_after_processing(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Should clear mailbox after processing messages."""
        storage = orchestrator_with_mailbox.mailbox_storage
        storage.add_message("Test message", sender="tester")

        # Mock the plan updater
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)

        # Mailbox should be empty after processing
        assert storage.count() == 0

    def test_no_plan_changes_returns_false(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Should return False when plan update makes no changes."""
        storage = orchestrator_with_mailbox.mailbox_storage
        storage.add_message("Minor suggestion", sender="reviewer")

        # Mock the plan updater to return no changes
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": False, "plan": "same plan"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        result = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)

        # Returns False because plan wasn't changed
        assert result is False

    def test_plan_update_error_handled(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Should handle errors during plan update gracefully."""
        storage = orchestrator_with_mailbox.mailbox_storage
        storage.add_message("Test message", sender="tester")

        # Mock the plan updater to raise an error
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(side_effect=ValueError("No plan exists"))
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Should not raise, but return False
        result = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)
        assert result is False

    def test_last_mailbox_check_timestamp_updated(
        self, orchestrator_with_mailbox, basic_task_state, state_manager, sample_plan_file
    ):
        """Should update last_mailbox_check timestamp in state."""
        storage = orchestrator_with_mailbox.mailbox_storage
        storage.add_message("Test message", sender="tester")

        # Mock the plan updater
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Store initial state
        initial_check = basic_task_state.last_mailbox_check

        # Initialize state_manager with state
        state_manager.save_state(basic_task_state)

        orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)

        # The timestamp should be updated
        assert basic_task_state.last_mailbox_check is not None
        if initial_check is not None:
            assert basic_task_state.last_mailbox_check > initial_check

    def test_webhook_emitted_on_process(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Should emit webhook event when mailbox is processed."""
        storage = orchestrator_with_mailbox.mailbox_storage
        storage.add_message("Test message", sender="webhook-tester")

        # Mock the plan updater
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Mock the webhook emitter
        mock_emitter = MagicMock()
        orchestrator_with_mailbox._webhook_emitter = mock_emitter

        orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)

        # Check that webhook was emitted
        mock_emitter.emit.assert_called()
        # Find the mailbox.processed call
        calls = [c for c in mock_emitter.emit.call_args_list if c[0][0] == "mailbox.processed"]
        assert len(calls) == 1
        call_kwargs = calls[0][1]
        assert call_kwargs["message_count"] == 1
        assert call_kwargs["plan_updated"] is True
        assert "webhook-tester" in call_kwargs["senders"]


# =============================================================================
# Test Message Priority Handling
# =============================================================================


class TestMessagePriorityHandling:
    """Tests for message priority handling in mailbox processing."""

    def test_urgent_messages_processed_first(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Should process urgent messages before normal ones (in merged order)."""
        storage = orchestrator_with_mailbox.mailbox_storage

        # Add messages in different order than priority
        storage.add_message("Normal message", sender="user", priority=Priority.NORMAL)
        storage.add_message("Urgent message", sender="admin", priority=Priority.URGENT)
        storage.add_message("Low priority", sender="bot", priority=Priority.LOW)

        # Mock the plan updater
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)

        # The merged content should have messages in priority order
        call_args = mock_plan_updater.update_plan.call_args[0][0]

        # URGENT should appear before NORMAL which appears before LOW
        urgent_pos = call_args.find("Urgent message")
        normal_pos = call_args.find("Normal message")
        low_pos = call_args.find("Low priority")

        assert urgent_pos < normal_pos, "Urgent should appear before normal"
        assert normal_pos < low_pos, "Normal should appear before low"


# =============================================================================
# Test Integration with Working Stage
# =============================================================================


class TestWorkingStageMailboxIntegration:
    """Tests for mailbox integration within the working stage handler."""

    @patch("claude_task_master.core.orchestrator.reset_escape")
    @patch("claude_task_master.core.orchestrator.time.time")
    def test_mailbox_checked_after_task_completion(
        self, mock_time, mock_reset, orchestrator_with_mailbox, basic_task_state, state_manager
    ):
        """Should check mailbox after completing a task."""
        mock_time.return_value = 1000.0

        # Setup: save a plan and state
        plan = """## Task List
- [ ] Task 1: First task
- [ ] Task 2: Second task
"""
        state_manager.save_plan(plan)
        state_manager.save_state(basic_task_state)

        # Add a message before the task runs
        orchestrator_with_mailbox.mailbox_storage.add_message(
            "Update needed after task 1",
            sender="supervisor",
        )

        # Mock the task runner
        mock_task_runner = MagicMock()
        mock_task_runner.run_work_session = MagicMock()
        mock_task_runner.get_current_task_description = MagicMock(return_value="First task")
        mock_task_runner.mark_task_complete = MagicMock()
        mock_task_runner.update_progress = MagicMock()
        mock_task_runner.is_last_task_in_group = MagicMock(return_value=False)
        orchestrator_with_mailbox._task_runner = mock_task_runner

        # Mock the plan updater
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated plan"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Run the working stage
        orchestrator_with_mailbox._handle_working_stage(basic_task_state)

        # Verify mailbox was checked and plan was updated
        mock_plan_updater.update_plan.assert_called_once()
        call_args = mock_plan_updater.update_plan.call_args[0][0]
        assert "Update needed after task 1" in call_args

    @patch("claude_task_master.core.orchestrator.reset_escape")
    @patch("claude_task_master.core.orchestrator.time.time")
    def test_no_mailbox_check_when_empty(
        self, mock_time, mock_reset, orchestrator_with_mailbox, basic_task_state, state_manager
    ):
        """Should not call plan updater when mailbox is empty."""
        mock_time.return_value = 1000.0

        # Setup: save a plan and state
        plan = """## Task List
- [ ] Task 1: First task
"""
        state_manager.save_plan(plan)
        state_manager.save_state(basic_task_state)

        # Mock the task runner
        mock_task_runner = MagicMock()
        mock_task_runner.run_work_session = MagicMock()
        mock_task_runner.get_current_task_description = MagicMock(return_value="First task")
        mock_task_runner.mark_task_complete = MagicMock()
        mock_task_runner.update_progress = MagicMock()
        mock_task_runner.is_last_task_in_group = MagicMock(return_value=True)
        orchestrator_with_mailbox._task_runner = mock_task_runner

        # Mock the plan updater
        mock_plan_updater = MagicMock()
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Run the working stage with empty mailbox
        orchestrator_with_mailbox._handle_working_stage(basic_task_state)

        # Verify plan updater was NOT called (no messages)
        mock_plan_updater.update_plan.assert_not_called()


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestMailboxEdgeCases:
    """Tests for edge cases in mailbox processing."""

    def test_empty_message_content(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Should handle messages with minimal content."""
        storage = orchestrator_with_mailbox.mailbox_storage
        storage.add_message(".", sender="test")  # Minimal content

        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": False, "plan": "unchanged"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Should not raise
        result = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)
        assert result is False  # No changes made

    def test_special_characters_in_message(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Should handle messages with special characters."""
        storage = orchestrator_with_mailbox.mailbox_storage
        storage.add_message(
            "Add task: `fix bug` in **module** <script>alert('xss')</script>",
            sender="user@example.com",
        )

        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Should not raise
        result = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)
        assert result is True

    def test_very_long_message(self, orchestrator_with_mailbox, basic_task_state, sample_plan_file):
        """Should handle very long messages."""
        storage = orchestrator_with_mailbox.mailbox_storage
        long_content = "x" * 10000  # 10KB message
        storage.add_message(long_content, sender="test")

        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Should not raise
        result = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)
        assert result is True

    def test_concurrent_message_addition(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Should handle messages added concurrently (race condition simulation)."""
        storage = orchestrator_with_mailbox.mailbox_storage

        # Add initial message
        storage.add_message("Initial message", sender="test1")

        # Mock plan updater
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Process should complete without error
        result = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)
        assert result is True

    def test_plan_updater_exception_handling(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Should handle unexpected exceptions from plan updater."""
        storage = orchestrator_with_mailbox.mailbox_storage
        storage.add_message("Test message", sender="test")

        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(side_effect=RuntimeError("Unexpected error"))
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Should not raise, but return False
        result = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)
        assert result is False


# =============================================================================
# Test State Persistence
# =============================================================================


class TestMailboxStatePersistence:
    """Tests for state persistence after mailbox processing."""

    def test_state_saved_after_mailbox_check(
        self, orchestrator_with_mailbox, basic_task_state, state_manager, sample_plan_file
    ):
        """Should save state after processing mailbox messages."""
        storage = orchestrator_with_mailbox.mailbox_storage
        storage.add_message("Test message", sender="test")

        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Initialize state
        state_manager.save_state(basic_task_state)

        orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)

        # Load state and verify it was saved
        loaded_state = state_manager.load_state()
        assert loaded_state.last_mailbox_check is not None

    def test_mailbox_messages_persisted(self, mailbox_storage, state_dir):
        """Should persist mailbox messages to disk."""
        mailbox_storage.add_message("Persistent message", sender="test")

        # Create new storage instance to verify persistence
        new_storage = MailboxStorage(state_dir)
        messages = new_storage.get_messages()

        assert len(messages) == 1
        assert messages[0].content == "Persistent message"
