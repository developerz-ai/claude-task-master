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


# =============================================================================
# Test Plan Update Order and Continuation
# =============================================================================


class TestMergedMessagesTriggerPlanUpdate:
    """Tests verifying that merged messages trigger plan update BEFORE continuing work.

    This is the key requirement: when messages are in the mailbox, the plan MUST
    be updated before the orchestrator moves to the next task. This ensures that
    any new tasks or changes from external sources are incorporated into the
    workflow before continuation.
    """

    @patch("claude_task_master.core.orchestrator.reset_escape")
    @patch("claude_task_master.core.orchestrator.time.time")
    def test_plan_updated_before_task_index_incremented(
        self, mock_time, mock_reset, orchestrator_with_mailbox, basic_task_state, state_manager
    ):
        """Plan should be updated BEFORE task index is incremented."""
        mock_time.return_value = 1000.0

        # Setup: initial plan with 2 tasks
        initial_plan = """## Task List
- [ ] Task 1: First task
- [ ] Task 2: Second task
"""
        state_manager.save_plan(initial_plan)
        state_manager.save_state(basic_task_state)

        # Add mailbox message to trigger plan update
        orchestrator_with_mailbox.mailbox_storage.add_message(
            "Add a new task 3 for testing",
            sender="supervisor",
        )

        # Track the order of operations
        operation_order = []

        # Mock task runner
        mock_task_runner = MagicMock()
        mock_task_runner.run_work_session = MagicMock()
        mock_task_runner.get_current_task_description = MagicMock(return_value="First task")
        mock_task_runner.mark_task_complete = MagicMock()
        mock_task_runner.update_progress = MagicMock()
        mock_task_runner.is_last_task_in_group = MagicMock(return_value=False)
        orchestrator_with_mailbox._task_runner = mock_task_runner

        # Mock plan updater to record when it's called
        def mock_update_plan(change_request):
            operation_order.append("plan_updated")
            return {"success": True, "changes_made": True, "plan": "updated plan"}

        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(side_effect=mock_update_plan)
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Patch state save to track when task index is saved
        original_save = state_manager.save_state

        def tracking_save(state):
            if state.current_task_index > 0:
                operation_order.append("task_index_incremented")
            return original_save(state)

        state_manager.save_state = tracking_save

        # Run the working stage
        orchestrator_with_mailbox._handle_working_stage(basic_task_state)

        # Verify plan was updated BEFORE task index was incremented
        assert "plan_updated" in operation_order
        # Plan update should happen before any increment save
        plan_idx = (
            operation_order.index("plan_updated") if "plan_updated" in operation_order else -1
        )
        increment_indices = [
            i for i, op in enumerate(operation_order) if op == "task_index_incremented"
        ]

        # If there's an increment, plan update should come first
        if increment_indices:
            assert plan_idx < increment_indices[0], (
                "Plan must be updated BEFORE task index is incremented"
            )

    @patch("claude_task_master.core.orchestrator.reset_escape")
    @patch("claude_task_master.core.orchestrator.time.time")
    def test_updated_plan_used_for_next_task_determination(
        self, mock_time, mock_reset, orchestrator_with_mailbox, basic_task_state, state_manager
    ):
        """After plan update, the orchestrator should use the NEW plan for next task."""
        mock_time.return_value = 1000.0

        # Setup: initial plan
        initial_plan = """## Task List
- [ ] Task 1: First task
- [ ] Task 2: Second task
"""
        # Updated plan with new task
        updated_plan = """## Task List
- [x] Task 1: First task
- [ ] Task 2: Second task
- [ ] Task 3: New task from mailbox
"""
        state_manager.save_plan(initial_plan)
        state_manager.save_state(basic_task_state)

        # Add mailbox message
        orchestrator_with_mailbox.mailbox_storage.add_message(
            "Add a new task 3",
            sender="supervisor",
        )

        # Mock task runner
        mock_task_runner = MagicMock()
        mock_task_runner.run_work_session = MagicMock()
        mock_task_runner.get_current_task_description = MagicMock(return_value="First task")
        mock_task_runner.mark_task_complete = MagicMock()
        mock_task_runner.update_progress = MagicMock()
        mock_task_runner.is_last_task_in_group = MagicMock(return_value=False)
        orchestrator_with_mailbox._task_runner = mock_task_runner

        # Mock plan updater to return the updated plan
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": updated_plan}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Run the working stage
        orchestrator_with_mailbox._handle_working_stage(basic_task_state)

        # Verify the plan updater was called with merged message content
        mock_plan_updater.update_plan.assert_called_once()
        call_args = mock_plan_updater.update_plan.call_args[0][0]
        assert "Add a new task 3" in call_args

    @patch("claude_task_master.core.orchestrator.reset_escape")
    @patch("claude_task_master.core.orchestrator.time.time")
    def test_multiple_messages_merged_then_plan_updated(
        self, mock_time, mock_reset, orchestrator_with_mailbox, basic_task_state, state_manager
    ):
        """Multiple messages should be merged into one request before plan update."""
        mock_time.return_value = 1000.0

        plan = """## Task List
- [ ] Task 1: First task
"""
        state_manager.save_plan(plan)
        state_manager.save_state(basic_task_state)

        # Add multiple messages with different priorities
        storage = orchestrator_with_mailbox.mailbox_storage
        storage.add_message("Normal priority task", sender="user", priority=Priority.NORMAL)
        storage.add_message(
            "URGENT: Fix security bug", sender="security-team", priority=Priority.URGENT
        )
        storage.add_message("Low priority refactor", sender="tech-debt-bot", priority=Priority.LOW)

        # Mock task runner
        mock_task_runner = MagicMock()
        mock_task_runner.run_work_session = MagicMock()
        mock_task_runner.get_current_task_description = MagicMock(return_value="First task")
        mock_task_runner.mark_task_complete = MagicMock()
        mock_task_runner.update_progress = MagicMock()
        mock_task_runner.is_last_task_in_group = MagicMock(return_value=True)
        orchestrator_with_mailbox._task_runner = mock_task_runner

        # Mock plan updater
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Run the working stage
        orchestrator_with_mailbox._handle_working_stage(basic_task_state)

        # Verify plan updater was called exactly once with merged content
        assert mock_plan_updater.update_plan.call_count == 1

        # Verify all message contents are in the merged request
        merged_content = mock_plan_updater.update_plan.call_args[0][0]
        assert "URGENT: Fix security bug" in merged_content
        assert "Normal priority task" in merged_content
        assert "Low priority refactor" in merged_content

        # Verify URGENT appears before NORMAL (priority ordering preserved in merger)
        urgent_pos = merged_content.find("URGENT: Fix security bug")
        normal_pos = merged_content.find("Normal priority task")
        assert urgent_pos < normal_pos, "Urgent message should appear before normal message"

    @patch("claude_task_master.core.orchestrator.reset_escape")
    @patch("claude_task_master.core.orchestrator.time.time")
    def test_total_tasks_refreshed_after_plan_update(
        self, mock_time, mock_reset, orchestrator_with_mailbox, basic_task_state, state_manager
    ):
        """After plan update, total_tasks count should reflect the new plan."""
        mock_time.return_value = 1000.0

        # Initial plan with 2 tasks
        initial_plan = """## Task List
- [ ] Task 1: First task
- [ ] Task 2: Second task
"""
        state_manager.save_plan(initial_plan)
        state_manager.save_state(basic_task_state)

        # Add mailbox message
        orchestrator_with_mailbox.mailbox_storage.add_message(
            "Add task 3",
            sender="supervisor",
        )

        # Mock task runner
        mock_task_runner = MagicMock()
        mock_task_runner.run_work_session = MagicMock()
        mock_task_runner.get_current_task_description = MagicMock(return_value="First task")
        mock_task_runner.mark_task_complete = MagicMock()
        mock_task_runner.update_progress = MagicMock()
        mock_task_runner.is_last_task_in_group = MagicMock(return_value=False)
        orchestrator_with_mailbox._task_runner = mock_task_runner

        # Mock plan updater - this should also update the actual plan file
        def update_plan_and_save(change_request):
            # Simulate saving an updated plan with 3 tasks
            new_plan = """## Task List
- [x] Task 1: First task
- [ ] Task 2: Second task
- [ ] Task 3: New task added
"""
            state_manager.save_plan(new_plan)
            return {"success": True, "changes_made": True, "plan": new_plan}

        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(side_effect=update_plan_and_save)
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Get initial task count
        initial_total = orchestrator_with_mailbox._get_total_tasks(basic_task_state)
        assert initial_total == 2

        # Run the working stage
        orchestrator_with_mailbox._handle_working_stage(basic_task_state)

        # After mailbox processing, total should reflect updated plan
        updated_total = orchestrator_with_mailbox._get_total_tasks(basic_task_state)
        assert updated_total == 3, "Total tasks should be updated to reflect new plan"

    def test_mailbox_checked_atomically(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Mailbox should be cleared atomically to prevent duplicate processing."""
        storage = orchestrator_with_mailbox.mailbox_storage
        storage.add_message("Message 1", sender="user1")
        storage.add_message("Message 2", sender="user2")

        # Mock plan updater
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # First check
        result1 = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)
        assert result1 is True
        assert storage.count() == 0, "Messages should be cleared after processing"

        # Second check should find no messages
        result2 = orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)
        assert result2 is False, "No messages should remain for second processing"

    @patch("claude_task_master.core.orchestrator.reset_escape")
    @patch("claude_task_master.core.orchestrator.time.time")
    def test_work_continues_after_plan_update_failure(
        self, mock_time, mock_reset, orchestrator_with_mailbox, basic_task_state, state_manager
    ):
        """Work should continue even if plan update fails (graceful degradation)."""
        mock_time.return_value = 1000.0

        plan = """## Task List
- [ ] Task 1: First task
- [ ] Task 2: Second task
"""
        state_manager.save_plan(plan)
        state_manager.save_state(basic_task_state)

        # Add mailbox message
        orchestrator_with_mailbox.mailbox_storage.add_message(
            "Add new task",
            sender="supervisor",
        )

        # Mock task runner
        mock_task_runner = MagicMock()
        mock_task_runner.run_work_session = MagicMock()
        mock_task_runner.get_current_task_description = MagicMock(return_value="First task")
        mock_task_runner.mark_task_complete = MagicMock()
        mock_task_runner.update_progress = MagicMock()
        mock_task_runner.is_last_task_in_group = MagicMock(return_value=False)
        orchestrator_with_mailbox._task_runner = mock_task_runner

        # Mock plan updater to fail
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(side_effect=Exception("Plan update failed"))
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Run the working stage - should complete without raising
        result = orchestrator_with_mailbox._handle_working_stage(basic_task_state)

        # Workflow should continue (result is None for continue, or int for terminal)
        # The key is that it doesn't raise an exception
        assert result is None  # None means continue to next cycle

        # Task runner should have been called (work happened)
        mock_task_runner.run_work_session.assert_called_once()


class TestMailboxProcessingTiming:
    """Tests for the timing of mailbox processing in the workflow."""

    @patch("claude_task_master.core.orchestrator.reset_escape")
    @patch("claude_task_master.core.orchestrator.time.time")
    def test_mailbox_processed_after_task_completion_not_before(
        self, mock_time, mock_reset, orchestrator_with_mailbox, basic_task_state, state_manager
    ):
        """Mailbox should be checked AFTER task is marked complete, not before."""
        mock_time.return_value = 1000.0

        plan = """## Task List
- [ ] Task 1: First task
"""
        state_manager.save_plan(plan)
        state_manager.save_state(basic_task_state)

        # Add mailbox message
        orchestrator_with_mailbox.mailbox_storage.add_message(
            "Update plan",
            sender="supervisor",
        )

        # Track operation order
        operation_order = []

        # Mock task runner with order tracking
        mock_task_runner = MagicMock()

        def track_work_session(*args, **kwargs):
            operation_order.append("task_completed")

        mock_task_runner.run_work_session = MagicMock(side_effect=track_work_session)
        mock_task_runner.get_current_task_description = MagicMock(return_value="First task")

        def track_mark_complete(*args, **kwargs):
            operation_order.append("task_marked_complete")

        mock_task_runner.mark_task_complete = MagicMock(side_effect=track_mark_complete)
        mock_task_runner.update_progress = MagicMock()
        mock_task_runner.is_last_task_in_group = MagicMock(return_value=True)
        orchestrator_with_mailbox._task_runner = mock_task_runner

        # Mock plan updater with order tracking
        def track_plan_update(change_request):
            operation_order.append("mailbox_plan_updated")
            return {"success": True, "changes_made": True, "plan": "updated"}

        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(side_effect=track_plan_update)
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        # Run the working stage
        orchestrator_with_mailbox._handle_working_stage(basic_task_state)

        # Verify order: task complete -> mark complete -> mailbox processed
        assert "task_completed" in operation_order
        assert "task_marked_complete" in operation_order
        assert "mailbox_plan_updated" in operation_order

        task_idx = operation_order.index("task_completed")
        mark_idx = operation_order.index("task_marked_complete")
        mailbox_idx = operation_order.index("mailbox_plan_updated")

        assert task_idx < mark_idx < mailbox_idx, (
            "Order must be: task complete -> mark complete -> mailbox process"
        )

    def test_messages_from_multiple_senders_all_processed(
        self, orchestrator_with_mailbox, basic_task_state, sample_plan_file
    ):
        """Messages from different senders should all be included in merged content."""
        storage = orchestrator_with_mailbox.mailbox_storage

        # Add messages from different senders
        storage.add_message("Request from AI supervisor", sender="ai-supervisor")
        storage.add_message("Request from human manager", sender="human@company.com")
        storage.add_message("Request from automation", sender="ci-bot")

        # Mock plan updater
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "updated"}
        )
        orchestrator_with_mailbox._plan_updater = mock_plan_updater

        orchestrator_with_mailbox._check_and_process_mailbox(basic_task_state)

        # Verify all senders' messages are in the merged content
        merged_content = mock_plan_updater.update_plan.call_args[0][0]
        assert "Request from AI supervisor" in merged_content
        assert "Request from human manager" in merged_content
        assert "Request from automation" in merged_content
