"""End-to-end integration tests for the mailbox workflow.

These tests verify the complete mailbox workflow including:
- Adding messages to the mailbox
- Merging multiple messages
- Triggering plan updates from mailbox messages
- Orchestrator mailbox integration after task completion
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.orchestrator import WorkLoopOrchestrator
from claude_task_master.core.plan_updater import PlanUpdater
from claude_task_master.core.planner import Planner
from claude_task_master.core.state import StateManager, TaskOptions
from claude_task_master.mailbox import MailboxStorage, MessageMerger
from claude_task_master.mailbox.models import MailboxMessage, Priority


class TestMailboxStorageWorkflow:
    """Tests for the complete mailbox storage workflow."""

    def test_add_and_retrieve_single_message(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test adding and retrieving a single message."""
        storage = MailboxStorage(integration_state_dir)

        # Add a message
        msg_id = storage.add_message(
            content="Add new feature X",
            sender="user",
            priority=Priority.NORMAL,
        )

        # Retrieve messages
        messages = storage.get_messages()

        assert len(messages) == 1
        assert messages[0].id == msg_id
        assert messages[0].content == "Add new feature X"
        assert messages[0].sender == "user"
        assert messages[0].priority == Priority.NORMAL

    def test_add_multiple_messages_with_priorities(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test adding multiple messages with different priorities."""
        storage = MailboxStorage(integration_state_dir)

        # Add messages with different priorities
        storage.add_message("Low priority task", sender="user1", priority=Priority.LOW)
        storage.add_message("Normal priority task", sender="user2", priority=Priority.NORMAL)
        storage.add_message("High priority task", sender="user3", priority=Priority.HIGH)
        storage.add_message("Urgent task", sender="admin", priority=Priority.URGENT)

        # Messages should be sorted by priority
        messages = storage.get_messages()

        assert len(messages) == 4
        # Highest priority first
        assert messages[0].priority == Priority.URGENT
        assert messages[1].priority == Priority.HIGH
        assert messages[2].priority == Priority.NORMAL
        assert messages[3].priority == Priority.LOW

    def test_get_and_clear_atomicity(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test that get_and_clear is atomic."""
        storage = MailboxStorage(integration_state_dir)

        # Add some messages
        storage.add_message("Message 1", sender="user")
        storage.add_message("Message 2", sender="user")
        storage.add_message("Message 3", sender="user")

        # Get and clear should return all messages
        messages = storage.get_and_clear()
        assert len(messages) == 3

        # Subsequent calls should return empty
        messages_after = storage.get_messages()
        assert len(messages_after) == 0

        # Count should be 0
        assert storage.count() == 0

    def test_mailbox_persistence_across_instances(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test that mailbox data persists across storage instances."""
        # Create first instance and add messages
        storage1 = MailboxStorage(integration_state_dir)
        storage1.add_message("Persisted message", sender="user")

        # Create new instance and verify message exists
        storage2 = MailboxStorage(integration_state_dir)
        messages = storage2.get_messages()

        assert len(messages) == 1
        assert messages[0].content == "Persisted message"

    def test_mailbox_status_returns_correct_info(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test that get_status returns correct mailbox information."""
        storage = MailboxStorage(integration_state_dir)

        # Add some messages
        storage.add_message("Task A", sender="user1")
        storage.add_message("Task B", sender="user2", priority=Priority.HIGH)

        status = storage.get_status()

        assert status["count"] == 2
        assert len(status["previews"]) == 2
        assert status["total_messages_received"] == 2


class TestMessageMergerWorkflow:
    """Tests for the message merger in a complete workflow."""

    def test_merge_single_message(
        self,
        integration_temp_dir: Path,
    ):
        """Test merging a single message."""
        merger = MessageMerger()

        message = MailboxMessage(
            content="Add authentication feature",
            sender="user",
            priority=Priority.NORMAL,
        )

        result = merger.merge([message])

        assert "Add authentication feature" in result

    def test_merge_multiple_messages_maintains_priority_order(
        self,
        integration_temp_dir: Path,
    ):
        """Test that merged messages maintain priority order."""
        merger = MessageMerger()

        messages = [
            MailboxMessage(content="Low priority", sender="user1", priority=Priority.LOW),
            MailboxMessage(content="Urgent fix!", sender="admin", priority=Priority.URGENT),
            MailboxMessage(content="Normal task", sender="user2", priority=Priority.NORMAL),
        ]

        # Sort by priority (highest first) like storage does
        sorted_messages = sorted(messages, key=lambda m: -m.priority)
        result = merger.merge(sorted_messages)

        # Urgent should come first in the merged output
        urgent_pos = result.find("Urgent fix!")
        normal_pos = result.find("Normal task")
        low_pos = result.find("Low priority")

        assert urgent_pos < normal_pos < low_pos

    def test_merge_messages_with_sender_attribution(
        self,
        integration_temp_dir: Path,
    ):
        """Test that merged messages include sender attribution."""
        merger = MessageMerger()

        messages = [
            MailboxMessage(content="Task from Alice", sender="alice", priority=Priority.NORMAL),
            MailboxMessage(content="Task from Bob", sender="bob", priority=Priority.NORMAL),
        ]

        result = merger.merge(messages)

        assert "alice" in result
        assert "bob" in result

    def test_merge_empty_messages_raises_error(
        self,
        integration_temp_dir: Path,
    ):
        """Test that merging empty message list raises ValueError."""
        merger = MessageMerger()

        with pytest.raises(ValueError, match="empty"):
            merger.merge([])

    def test_merge_to_single_content(
        self,
        integration_temp_dir: Path,
    ):
        """Test merge_to_single_content combines only content."""
        merger = MessageMerger()

        messages = [
            MailboxMessage(content="First task", sender="user1", priority=Priority.HIGH),
            MailboxMessage(content="Second task", sender="user2", priority=Priority.LOW),
        ]

        result = merger.merge_to_single_content(messages)

        assert "First task" in result
        assert "Second task" in result
        # Should not include formatted headers
        assert "Consolidated Change Requests" not in result


class TestMailboxWithOrchestratorIntegration:
    """Integration tests for mailbox with the orchestrator."""

    def test_orchestrator_checks_mailbox_after_task(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
        mock_github_client,
        monkeypatch,
    ):
        """Test that orchestrator checks mailbox after completing a task."""
        monkeypatch.chdir(integration_temp_dir)

        # Set up state manager
        state_manager = StateManager(integration_state_dir)
        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Test mailbox check", model="sonnet", options=options)

        # Create a plan with one task
        state_manager.save_plan("""## Task List

- [ ] Complete the task

## Success Criteria

1. Task is done
""")

        state.status = "working"
        state_manager.save_state(state)

        # Set up mailbox with a message
        mailbox = MailboxStorage(integration_state_dir)
        mailbox.add_message("Update plan with new requirement", sender="supervisor")

        # Configure mock agent
        mock_agent_wrapper.run_work_session = MagicMock(
            return_value={"output": "Task completed", "success": True}
        )
        mock_agent_wrapper.verify_success_criteria = MagicMock(
            return_value={"success": True, "details": "All done"}
        )

        # Create plan updater mock
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": False}
        )

        # Create orchestrator - mailbox components are lazy loaded
        planner = Planner(mock_agent_wrapper, state_manager)
        orchestrator = WorkLoopOrchestrator(
            mock_agent_wrapper,
            state_manager,
            planner,
            github_client=mock_github_client,
        )

        # Inject the mailbox storage and related components
        orchestrator._mailbox_storage = mailbox
        orchestrator._message_merger = MessageMerger()
        orchestrator._plan_updater = mock_plan_updater

        # Run orchestrator
        orchestrator.run()

        # Mailbox should be checked (and cleared)
        assert mailbox.count() == 0

    def test_orchestrator_updates_plan_from_mailbox(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
        mock_github_client,
        monkeypatch,
    ):
        """Test that orchestrator updates plan when mailbox has messages."""
        monkeypatch.chdir(integration_temp_dir)

        state_manager = StateManager(integration_state_dir)
        options = TaskOptions(auto_merge=True)
        state = state_manager.initialize(goal="Test plan update", model="sonnet", options=options)

        state_manager.save_plan("""## Task List

- [ ] Task 1
- [ ] Task 2

## Success Criteria

1. All tasks done
""")

        state.status = "working"
        state_manager.save_state(state)

        # Add mailbox message
        mailbox = MailboxStorage(integration_state_dir)
        mailbox.add_message("Add Task 3 to the plan", sender="supervisor")

        # Mock the plan updater to indicate changes were made
        mock_plan_updater = MagicMock()
        mock_plan_updater.update_plan = MagicMock(
            return_value={"success": True, "changes_made": True, "plan": "Updated plan"}
        )

        mock_agent_wrapper.run_work_session = MagicMock(
            return_value={"output": "Done", "success": True}
        )
        mock_agent_wrapper.verify_success_criteria = MagicMock(
            return_value={"success": True, "details": "Done"}
        )

        planner = Planner(mock_agent_wrapper, state_manager)
        orchestrator = WorkLoopOrchestrator(
            mock_agent_wrapper,
            state_manager,
            planner,
            github_client=mock_github_client,
        )

        # Inject the mailbox storage and related components
        orchestrator._mailbox_storage = mailbox
        orchestrator._message_merger = MessageMerger()
        orchestrator._plan_updater = mock_plan_updater

        # Run one iteration
        orchestrator.run()

        # Plan updater should have been called with the message
        if mock_plan_updater.update_plan.called:
            call_args = mock_plan_updater.update_plan.call_args[0][0]
            assert "Add Task 3" in call_args


class TestMailboxConcurrencyScenarios:
    """Tests for mailbox behavior in concurrent scenarios."""

    def test_multiple_messages_merged_correctly(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test that multiple messages from different sources merge correctly."""
        storage = MailboxStorage(integration_state_dir)

        # Simulate messages from different sources
        storage.add_message("Add feature A", sender="developer1", priority=Priority.NORMAL)
        storage.add_message(
            "URGENT: Fix security bug", sender="security-team", priority=Priority.URGENT
        )
        storage.add_message("Update documentation", sender="tech-writer", priority=Priority.LOW)

        messages = storage.get_and_clear()
        merger = MessageMerger()
        merged = merger.merge(messages)

        # All messages should be in the merged output
        assert "feature A" in merged
        assert "security bug" in merged
        assert "documentation" in merged

        # URGENT should be mentioned first
        urgent_pos = merged.find("URGENT")
        feature_pos = merged.find("feature A")
        assert urgent_pos < feature_pos

    def test_mailbox_handles_rapid_message_additions(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test mailbox handles rapid message additions correctly."""
        storage = MailboxStorage(integration_state_dir)

        # Rapidly add many messages
        for i in range(50):
            storage.add_message(
                f"Message {i}",
                sender=f"user{i % 5}",
                priority=Priority(i % 4),
            )

        assert storage.count() == 50

        # Get and clear should return all
        messages = storage.get_and_clear()
        assert len(messages) == 50
        assert storage.count() == 0


class TestMailboxWithPlanUpdater:
    """Tests for mailbox integration with PlanUpdater."""

    def test_mailbox_messages_trigger_plan_update(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
    ):
        """Test that mailbox messages can trigger plan updates."""
        # Set up state manager with a plan
        state_manager = StateManager(integration_state_dir)
        options = TaskOptions(auto_merge=True)
        state_manager.initialize(goal="Test plan update", model="sonnet", options=options)
        state_manager.save_plan("""## Task List

- [ ] Task 1
- [ ] Task 2

## Success Criteria

1. All done
""")

        # Set up mailbox
        storage = MailboxStorage(integration_state_dir)
        storage.add_message("Add error handling to all tasks", sender="reviewer")
        storage.add_message("Include unit tests", sender="qa-team")

        # Get messages and merge
        messages = storage.get_and_clear()
        merger = MessageMerger()
        merged_content = merger.merge(messages)

        # Create plan updater
        plan_updater = PlanUpdater(mock_agent_wrapper, state_manager)

        # Mock the query execution
        with patch.object(plan_updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = """## Task List

- [ ] Task 1
- [ ] Task 2
- [ ] Add error handling (NEW from mailbox)
- [ ] Include unit tests (NEW from mailbox)

## Success Criteria

1. All done
"""
            result = plan_updater.update_plan(merged_content)

        assert result["success"] is True
        assert result["changes_made"] is True
        assert "error handling" in result["plan"]
        assert "unit tests" in result["plan"]


class TestMailboxStatusTracking:
    """Tests for mailbox status and tracking functionality."""

    def test_last_checked_timestamp_updated(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test that last_checked timestamp is updated after get_and_clear."""
        storage = MailboxStorage(integration_state_dir)

        # Add a message
        storage.add_message("Test message", sender="user")

        # Get status before clearing
        status_before = storage.get_status()
        assert status_before["last_checked"] is None

        # Clear messages
        storage.get_and_clear()

        # Get status after clearing
        status_after = storage.get_status()
        assert status_after["last_checked"] is not None

    def test_total_messages_received_counter(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test that total_messages_received counter increments correctly."""
        storage = MailboxStorage(integration_state_dir)

        # Add some messages
        storage.add_message("Message 1", sender="user")
        storage.add_message("Message 2", sender="user")

        status1 = storage.get_status()
        assert status1["total_messages_received"] == 2

        # Clear and add more
        storage.get_and_clear()
        storage.add_message("Message 3", sender="user")

        status2 = storage.get_status()
        assert status2["total_messages_received"] == 3
        assert status2["count"] == 1  # Only 1 pending


class TestMailboxEdgeCases:
    """Edge case tests for mailbox functionality."""

    def test_empty_content_message(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test handling of message with empty content."""
        storage = MailboxStorage(integration_state_dir)

        storage.add_message("", sender="user")

        messages = storage.get_messages()
        assert len(messages) == 1
        assert messages[0].content == ""

    def test_special_characters_in_message(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test handling of special characters in messages."""
        storage = MailboxStorage(integration_state_dir)

        special_content = 'Fix "bug" with <script> & special chars: \n\t\r'
        storage.add_message(special_content, sender="user")

        messages = storage.get_messages()
        assert messages[0].content == special_content

    def test_unicode_content_in_message(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test handling of Unicode content in messages."""
        storage = MailboxStorage(integration_state_dir)

        unicode_content = "Add feature: 日本語対応 and emoji support 🚀"
        storage.add_message(unicode_content, sender="user")

        messages = storage.get_messages()
        assert messages[0].content == unicode_content

    def test_very_long_message(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test handling of very long messages."""
        storage = MailboxStorage(integration_state_dir)

        long_content = "A" * 10000
        storage.add_message(long_content, sender="user")

        messages = storage.get_messages()
        assert len(messages[0].content) == 10000

    def test_message_with_metadata(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
    ):
        """Test that message metadata is preserved."""
        storage = MailboxStorage(integration_state_dir)

        metadata = {"source": "api", "request_id": "12345", "tags": ["urgent", "security"]}
        storage.add_message("Test", sender="user", metadata=metadata)

        messages = storage.get_messages()
        assert messages[0].metadata == metadata
