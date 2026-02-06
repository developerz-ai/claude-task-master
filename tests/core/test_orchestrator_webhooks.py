"""Tests for orchestrator webhook emission during task lifecycle.

This module tests webhook events emitted by the WorkLoopOrchestrator during
task execution, PR creation, and session management. Tests verify that:

- Correct webhook events are emitted at appropriate lifecycle points
- Event data includes accurate task/session/PR information
- Webhook emission failures don't block orchestrator operation
- Events are properly correlated with run_id
- WebhookEmitter class handles edge cases gracefully
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from claude_task_master.core.orchestrator import WebhookEmitter, WorkLoopOrchestrator
from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.webhooks.events import EventType

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_webhook_client():
    """Create a mock webhook client."""
    client = MagicMock()
    # Default to successful sends
    client.send_sync = MagicMock(return_value=MagicMock(success=True, status_code=200, error=None))
    return client


@pytest.fixture
def webhook_emitter(mock_webhook_client):
    """Create a WebhookEmitter with mock client."""
    return WebhookEmitter(mock_webhook_client, run_id="test-run-123")


@pytest.fixture
def webhook_emitter_no_client():
    """Create a WebhookEmitter without a client (disabled)."""
    return WebhookEmitter(None, run_id="test-run-123")


@pytest.fixture
def mock_agent():
    """Create a mock agent wrapper."""
    agent = MagicMock()
    agent.run_work_session = MagicMock(
        return_value={"output": "Task completed successfully", "success": True}
    )
    agent.verify_success_criteria = MagicMock(return_value={"success": True})
    return agent


@pytest.fixture
def mock_planner():
    """Create a mock planner."""
    planner = MagicMock()
    planner.run_planning_phase = MagicMock(return_value={"plan": "test", "criteria": "test"})
    return planner


@pytest.fixture
def orchestrator_with_webhooks(
    mock_agent, state_manager, mock_planner, mock_github_client, mock_webhook_client
):
    """Create a WorkLoopOrchestrator with webhook client."""
    return WorkLoopOrchestrator(
        agent=mock_agent,
        state_manager=state_manager,
        planner=mock_planner,
        github_client=mock_github_client,
        webhook_client=mock_webhook_client,
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
def basic_plan():
    """Basic plan with unchecked tasks."""
    return """## Task List

- [ ] Task 1: Set up project structure
- [ ] Task 2: Implement core functionality
- [ ] Task 3: Add unit tests
"""


# =============================================================================
# Test WebhookEmitter Class
# =============================================================================


class TestWebhookEmitter:
    """Tests for WebhookEmitter helper class."""

    def test_emitter_enabled_with_client(self, webhook_emitter):
        """Should be enabled when client is provided."""
        assert webhook_emitter.enabled is True

    def test_emitter_disabled_without_client(self, webhook_emitter_no_client):
        """Should be disabled when client is None."""
        assert webhook_emitter_no_client.enabled is False

    def test_emit_with_client_sends_event(self, webhook_emitter, mock_webhook_client):
        """Should send event when client is available."""
        webhook_emitter.emit(
            "task.started",
            task_index=0,
            task_description="Test task",
            total_tasks=3,
        )

        # Verify send_sync was called
        mock_webhook_client.send_sync.assert_called_once()
        call_args = mock_webhook_client.send_sync.call_args

        # Verify event data
        event_data = call_args.kwargs["data"]
        assert event_data["event_type"] == "task.started"
        assert event_data["task_index"] == 0
        assert event_data["task_description"] == "Test task"
        assert event_data["total_tasks"] == 3
        assert event_data["run_id"] == "test-run-123"

    def test_emit_without_client_is_noop(self, webhook_emitter_no_client):
        """Should do nothing when client is None."""
        # Should not raise
        webhook_emitter_no_client.emit(
            "task.started",
            task_index=0,
            task_description="Test task",
        )

    def test_emit_adds_run_id_to_events(self, webhook_emitter, mock_webhook_client):
        """Should automatically add run_id to all events."""
        webhook_emitter.emit(
            "task.completed",
            task_index=0,
            task_description="Done",
        )

        call_args = mock_webhook_client.send_sync.call_args
        event_data = call_args.kwargs["data"]
        assert event_data["run_id"] == "test-run-123"

    def test_emit_handles_send_failure_gracefully(self, webhook_emitter, mock_webhook_client):
        """Should log error but not raise when send fails."""
        mock_webhook_client.send_sync.return_value = MagicMock(
            success=False, error="Network timeout"
        )

        # Should not raise
        webhook_emitter.emit(
            "task.started",
            task_index=0,
            task_description="Test",
        )

    def test_emit_handles_exception_gracefully(self, webhook_emitter, mock_webhook_client):
        """Should catch and log exceptions during emission."""
        mock_webhook_client.send_sync.side_effect = Exception("Connection error")

        # Should not raise
        webhook_emitter.emit(
            "task.started",
            task_index=0,
            task_description="Test",
        )

    def test_emit_with_event_type_enum(self, webhook_emitter, mock_webhook_client):
        """Should accept EventType enum values."""
        webhook_emitter.emit(
            EventType.TASK_STARTED,
            task_index=0,
            task_description="Test",
        )

        call_args = mock_webhook_client.send_sync.call_args
        event_data = call_args.kwargs["data"]
        assert event_data["event_type"] == "task.started"

    def test_emit_sets_delivery_id(self, webhook_emitter, mock_webhook_client):
        """Should pass event_id as delivery_id."""
        webhook_emitter.emit(
            "task.started",
            task_index=0,
            task_description="Test",
        )

        call_args = mock_webhook_client.send_sync.call_args
        delivery_id = call_args.kwargs["delivery_id"]
        event_data = call_args.kwargs["data"]

        # delivery_id should match event_id
        assert delivery_id == event_data["event_id"]

    def test_emit_sets_event_type_parameter(self, webhook_emitter, mock_webhook_client):
        """Should pass event_type string to send_sync."""
        webhook_emitter.emit(
            "task.completed",
            task_index=0,
            task_description="Done",
        )

        call_args = mock_webhook_client.send_sync.call_args
        event_type = call_args.kwargs["event_type"]
        assert event_type == "task.completed"


# =============================================================================
# Test Orchestrator Webhook Property
# =============================================================================


class TestOrchestratorWebhookProperty:
    """Tests for orchestrator webhook_emitter property."""

    def test_webhook_emitter_lazy_initialization(self, orchestrator_with_webhooks):
        """Should create webhook emitter lazily."""
        assert orchestrator_with_webhooks._webhook_emitter is None
        emitter = orchestrator_with_webhooks.webhook_emitter
        assert emitter is not None
        assert isinstance(emitter, WebhookEmitter)

    def test_webhook_emitter_caches_instance(self, orchestrator_with_webhooks):
        """Should cache webhook emitter after first access."""
        emitter1 = orchestrator_with_webhooks.webhook_emitter
        emitter2 = orchestrator_with_webhooks.webhook_emitter
        assert emitter1 is emitter2

    def test_webhook_emitter_extracts_run_id_from_state(
        self, orchestrator_with_webhooks, state_manager, sample_task_options
    ):
        """Should extract run_id from state when available."""
        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test", model="sonnet", options=options)
        state = state_manager.load_state()
        state.run_id = "extracted-run-id"
        state_manager.save_state(state)

        emitter = orchestrator_with_webhooks.webhook_emitter
        assert emitter._run_id == "extracted-run-id"

    def test_webhook_emitter_handles_missing_state(
        self, mock_agent, state_manager, mock_planner, mock_webhook_client
    ):
        """Should use None run_id when state can't be loaded."""
        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent,
            state_manager=state_manager,
            planner=mock_planner,
            webhook_client=mock_webhook_client,
        )
        # State doesn't exist
        emitter = orchestrator.webhook_emitter
        assert emitter._run_id is None


# =============================================================================
# Test Task Lifecycle Webhook Events
# =============================================================================


class TestTaskLifecycleWebhooks:
    """Tests for webhook events during task lifecycle."""

    @patch("claude_task_master.core.orchestrator.subprocess.run")
    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_task_started_event_emitted(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        mock_subprocess,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should emit task.started event when task begins."""
        mock_branch.return_value = "feature/test"
        # Mock subprocess for getting branch
        mock_subprocess.return_value = MagicMock(stdout="feature/test\n", returncode=0)

        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        orchestrator_with_webhooks._handle_working_stage(basic_task_state)

        # Find the task.started event call
        calls = mock_webhook_client.send_sync.call_args_list
        task_started_calls = [c for c in calls if c.kwargs.get("event_type") == "task.started"]

        assert len(task_started_calls) == 1
        event_data = task_started_calls[0].kwargs["data"]
        assert event_data["event_type"] == "task.started"
        assert event_data["task_index"] == 0
        assert "Task 1" in event_data["task_description"]
        assert event_data["total_tasks"] == 3
        # Branch may be real or mocked
        assert event_data["branch"] is not None

    @patch("claude_task_master.core.orchestrator.subprocess.run")
    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_task_completed_event_emitted(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        mock_subprocess,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should emit task.completed event when task completes."""
        mock_branch.return_value = "feature/test"
        mock_subprocess.return_value = MagicMock(stdout="feature/test\n", returncode=0)

        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        orchestrator_with_webhooks._handle_working_stage(basic_task_state)

        # Find the task.completed event call
        calls = mock_webhook_client.send_sync.call_args_list
        task_completed_calls = [c for c in calls if c.kwargs.get("event_type") == "task.completed"]

        assert len(task_completed_calls) == 1
        event_data = task_completed_calls[0].kwargs["data"]
        assert event_data["event_type"] == "task.completed"
        assert event_data["task_index"] == 0
        assert "Task 1" in event_data["task_description"]
        assert event_data["total_tasks"] == 3
        # Completed tasks count varies depending on state, just check it exists
        assert event_data["completed_tasks"] >= 1
        assert "duration_seconds" in event_data
        assert event_data["branch"] is not None

    @patch("claude_task_master.core.orchestrator.subprocess.run")
    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    def test_task_failed_event_emitted_on_error(
        self,
        mock_console,
        mock_branch,
        mock_subprocess,
        orchestrator_with_webhooks,
        state_manager,
        mock_agent,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should emit task.failed event when task fails."""
        from claude_task_master.core.task_runner import WorkSessionError

        mock_branch.return_value = "feature/test"
        mock_subprocess.return_value = MagicMock(stdout="feature/test\n", returncode=0)

        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        # Make agent fail
        mock_agent.run_work_session.side_effect = RuntimeError("Task failed")

        with pytest.raises(WorkSessionError):
            orchestrator_with_webhooks._handle_working_stage(basic_task_state)

        # Find the task.failed event call
        calls = mock_webhook_client.send_sync.call_args_list
        task_failed_calls = [c for c in calls if c.kwargs.get("event_type") == "task.failed"]

        assert len(task_failed_calls) == 1
        event_data = task_failed_calls[0].kwargs["data"]
        assert event_data["event_type"] == "task.failed"
        assert event_data["task_index"] == 0
        # Error message may be wrapped by WorkSessionError
        assert "Task failed" in event_data["error_message"]
        # Error type is the wrapper exception type (WorkSessionError or RuntimeError)
        assert event_data["error_type"] in ("RuntimeError", "WorkSessionError")
        assert event_data["recoverable"] is True


# =============================================================================
# Test Session Lifecycle Webhook Events
# =============================================================================


class TestSessionLifecycleWebhooks:
    """Tests for webhook events during session lifecycle."""

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_session_started_event_emitted(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should emit session.started event when session begins."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        orchestrator_with_webhooks._handle_working_stage(basic_task_state)

        # Find the session.started event call
        calls = mock_webhook_client.send_sync.call_args_list
        session_started_calls = [
            c for c in calls if c.kwargs.get("event_type") == "session.started"
        ]

        assert len(session_started_calls) == 1
        event_data = session_started_calls[0].kwargs["data"]
        assert event_data["event_type"] == "session.started"
        assert event_data["session_number"] == 2  # session_count + 1
        assert event_data["task_index"] == 0
        assert event_data["phase"] == "working"

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_session_completed_event_emitted(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should emit session.completed event when session ends."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        orchestrator_with_webhooks._handle_working_stage(basic_task_state)

        # Find the session.completed event call
        calls = mock_webhook_client.send_sync.call_args_list
        session_completed_calls = [
            c for c in calls if c.kwargs.get("event_type") == "session.completed"
        ]

        assert len(session_completed_calls) == 1
        event_data = session_completed_calls[0].kwargs["data"]
        assert event_data["event_type"] == "session.completed"
        assert event_data["session_number"] == 2
        assert event_data["task_index"] == 0
        assert event_data["phase"] == "working"
        assert event_data["result"] == "completed"
        assert "duration_seconds" in event_data

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    def test_session_completed_with_failure_result(
        self,
        mock_console,
        mock_branch,
        orchestrator_with_webhooks,
        state_manager,
        mock_agent,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should emit session.completed with failed result on error."""
        from claude_task_master.core.task_runner import WorkSessionError

        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        # Make agent fail
        mock_agent.run_work_session.side_effect = RuntimeError("Session error")

        with pytest.raises(WorkSessionError):
            orchestrator_with_webhooks._handle_working_stage(basic_task_state)

        # Find the session.completed event call
        calls = mock_webhook_client.send_sync.call_args_list
        session_completed_calls = [
            c for c in calls if c.kwargs.get("event_type") == "session.completed"
        ]

        assert len(session_completed_calls) == 1
        event_data = session_completed_calls[0].kwargs["data"]
        assert event_data["result"] == "failed"


# =============================================================================
# Test PR Lifecycle Webhook Events
# =============================================================================


class TestPRLifecycleWebhooks:
    """Tests for webhook events during PR lifecycle."""

    @patch("claude_task_master.core.workflow_stages.console")
    def test_pr_created_event_emitted(
        self,
        mock_console,
        orchestrator_with_webhooks,
        state_manager,
        mock_github_client,
        mock_webhook_client,
        basic_task_state,
    ):
        """Should emit pr.created event when PR is detected."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.workflow_stage = "pr_created"

        # Mock GitHub to return a PR
        mock_github_client.get_pr_for_current_branch.return_value = 42
        mock_pr_status = Mock()
        mock_pr_status.pr_url = "https://github.com/owner/repo/pull/42"
        mock_pr_status.pr_title = "Test PR"
        mock_pr_status.base_branch = "main"
        mock_pr_status.ci_state = "SUCCESS"
        mock_pr_status.checks_pending = 0
        mock_github_client.get_pr_status.return_value = mock_pr_status

        orchestrator_with_webhooks._run_workflow_cycle(basic_task_state)

        # Find the pr.created event call
        calls = mock_webhook_client.send_sync.call_args_list
        pr_created_calls = [c for c in calls if c.kwargs.get("event_type") == "pr.created"]

        assert len(pr_created_calls) == 1
        event_data = pr_created_calls[0].kwargs["data"]
        assert event_data["event_type"] == "pr.created"
        assert event_data["pr_number"] == 42
        assert event_data["pr_url"] == "https://github.com/owner/repo/pull/42"
        assert event_data["pr_title"] == "Test PR"
        assert event_data["base_branch"] == "main"

    @patch("claude_task_master.core.workflow_stages.console")
    @patch("claude_task_master.core.orchestrator.interruptible_sleep")
    def test_pr_merged_event_emitted(
        self,
        mock_sleep,
        mock_console,
        orchestrator_with_webhooks,
        state_manager,
        mock_github_client,
        mock_webhook_client,
        basic_task_state,
    ):
        """Should emit pr.merged event when PR is merged."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.workflow_stage = "ready_to_merge"
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True

        # Mock GitHub PR status
        mock_pr_status = Mock()
        mock_pr_status.pr_url = "https://github.com/owner/repo/pull/42"
        mock_pr_status.pr_title = "Test PR"
        mock_pr_status.base_branch = "main"
        mock_pr_status.ci_state = "SUCCESS"
        mock_pr_status.checks_pending = 0
        mock_pr_status.reviews_approved = 1
        mock_pr_status.reviews_requested = 0
        mock_github_client.get_pr_status.return_value = mock_pr_status

        # Mock successful merge
        mock_github_client.merge_pr.return_value = True

        orchestrator_with_webhooks._run_workflow_cycle(basic_task_state)

        # Find the pr.merged event call
        calls = mock_webhook_client.send_sync.call_args_list
        pr_merged_calls = [c for c in calls if c.kwargs.get("event_type") == "pr.merged"]

        assert len(pr_merged_calls) == 1
        event_data = pr_merged_calls[0].kwargs["data"]
        assert event_data["event_type"] == "pr.merged"
        assert event_data["pr_number"] == 42
        assert event_data["auto_merged"] is True


# =============================================================================
# Test Event Ordering and Correlation
# =============================================================================


class TestEventOrderingAndCorrelation:
    """Tests for event ordering and correlation."""

    @patch("claude_task_master.core.orchestrator.subprocess.run")
    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_events_emitted_in_correct_order(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        mock_subprocess,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should emit events in correct order during task execution."""
        mock_branch.return_value = "main"
        mock_subprocess.return_value = MagicMock(stdout="main\n", returncode=0)

        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        orchestrator_with_webhooks._handle_working_stage(basic_task_state)

        # Extract event types in order
        calls = mock_webhook_client.send_sync.call_args_list
        event_types = [c.kwargs["event_type"] for c in calls]

        # Verify order: session.started -> task.started -> session.completed -> task.completed
        # Note: session.completed is emitted in finally block, so comes before task.completed
        assert event_types == [
            "session.started",
            "task.started",
            "session.completed",
            "task.completed",
        ]

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_all_events_have_same_run_id(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should include same run_id in all events."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")
        basic_task_state.run_id = "correlation-test-123"

        # Initialize webhook emitter with run_id
        orchestrator_with_webhooks._webhook_emitter = WebhookEmitter(
            mock_webhook_client, run_id="correlation-test-123"
        )

        orchestrator_with_webhooks._handle_working_stage(basic_task_state)

        # Verify all events have the same run_id
        calls = mock_webhook_client.send_sync.call_args_list
        for call_obj in calls:
            event_data = call_obj.kwargs["data"]
            assert event_data["run_id"] == "correlation-test-123"


# =============================================================================
# Test Error Handling and Edge Cases
# =============================================================================


class TestWebhookErrorHandling:
    """Tests for webhook error handling and edge cases."""

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_webhook_failure_does_not_block_execution(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should continue execution even when webhook delivery fails."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        # Make webhook client fail
        mock_webhook_client.send_sync.return_value = MagicMock(success=False, error="Network error")

        # Should complete without raising
        result = orchestrator_with_webhooks._handle_working_stage(basic_task_state)
        assert result is None

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_webhook_exception_does_not_block_execution(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should continue execution even when webhook raises exception."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        # Make webhook client raise exception
        mock_webhook_client.send_sync.side_effect = Exception("Connection timeout")

        # Should complete without raising
        result = orchestrator_with_webhooks._handle_working_stage(basic_task_state)
        assert result is None

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_orchestrator_without_webhook_client_works(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        mock_agent,
        state_manager,
        mock_planner,
        mock_github_client,
        basic_task_state,
        basic_plan,
    ):
        """Should work normally when no webhook client is provided."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        # Create orchestrator without webhook client
        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent,
            state_manager=state_manager,
            planner=mock_planner,
            github_client=mock_github_client,
            webhook_client=None,  # No webhook client
        )

        # Should complete without issues
        result = orchestrator._handle_working_stage(basic_task_state)
        assert result is None


# =============================================================================
# Test New Webhook Events (run.started, run.completed, status.changed, CI, plan.updated)
# =============================================================================


class TestRunLifecycleWebhooks:
    """Tests for run.started and run.completed webhook events."""

    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.start_listening")
    def test_run_started_event_emitted_on_orchestrator_start(
        self,
        mock_start_listening,
        mock_register,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        sample_task_options,
        basic_plan,
    ):
        """Should emit run.started event when orchestrator starts."""
        from claude_task_master.core.state import TaskOptions

        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        options.max_sessions = 5
        options.auto_merge = True
        state_manager.initialize(goal="Test goal", model="sonnet", options=options)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        # Mock the work loop to exit immediately
        with patch.object(orchestrator_with_webhooks, "_run_workflow_cycle", return_value=0):
            orchestrator_with_webhooks.run()

        # Find the run.started event call
        calls = mock_webhook_client.send_sync.call_args_list
        run_started_calls = [c for c in calls if c.kwargs.get("event_type") == "run.started"]

        assert len(run_started_calls) == 1
        event_data = run_started_calls[0].kwargs["data"]
        assert event_data["event_type"] == "run.started"
        assert event_data["goal"] == "Test goal"
        assert event_data["max_sessions"] == 5
        assert event_data["auto_merge"] is True
        assert event_data["pr_mode"] in ("per-task", "per-group")
        assert event_data["resumed"] is False
        assert "working_directory" in event_data

    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.start_listening")
    def test_run_started_event_indicates_resumed_run(
        self,
        mock_start_listening,
        mock_register,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        sample_task_options,
        basic_plan,
    ):
        """Should indicate resumed=True when run is resumed (session_count > 0)."""
        from claude_task_master.core.state import TaskOptions

        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test goal", model="sonnet", options=options)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        # Increment session count to simulate resumed run
        state = state_manager.load_state()
        state.session_count = 3
        state_manager.save_state(state)

        # Mock the work loop to exit immediately
        with patch.object(orchestrator_with_webhooks, "_run_workflow_cycle", return_value=0):
            orchestrator_with_webhooks.run()

        # Find the run.started event call
        calls = mock_webhook_client.send_sync.call_args_list
        run_started_calls = [c for c in calls if c.kwargs.get("event_type") == "run.started"]

        assert len(run_started_calls) == 1
        event_data = run_started_calls[0].kwargs["data"]
        assert event_data["resumed"] is True

    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.start_listening")
    def test_run_completed_event_emitted_on_success(
        self,
        mock_start_listening,
        mock_register,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        sample_task_options,
        basic_plan,
    ):
        """Should emit run.completed event with success result when run completes."""
        from claude_task_master.core.state import TaskOptions

        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Complete the project", model="sonnet", options=options)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Complete the project")

        # Mock the work loop to exit with success
        with patch.object(orchestrator_with_webhooks, "_run_workflow_cycle", return_value=0):
            exit_code = orchestrator_with_webhooks.run()

        assert exit_code == 0

        # Find the run.completed event call
        calls = mock_webhook_client.send_sync.call_args_list
        run_completed_calls = [c for c in calls if c.kwargs.get("event_type") == "run.completed"]

        assert len(run_completed_calls) == 1
        event_data = run_completed_calls[0].kwargs["data"]
        assert event_data["event_type"] == "run.completed"
        assert event_data["result"] == "success"
        assert event_data["exit_code"] == 0
        assert event_data["goal"] == "Complete the project"
        assert "total_tasks" in event_data
        assert "completed_tasks" in event_data
        assert "total_sessions" in event_data
        assert "duration_seconds" in event_data
        # Status could be "planning" or "working" depending on mock setup
        assert event_data["final_status"] in ("planning", "working", "success")
        assert event_data["error_message"] is None

    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.start_listening")
    def test_run_completed_event_emitted_on_blocked(
        self,
        mock_start_listening,
        mock_register,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        sample_task_options,
        basic_plan,
    ):
        """Should emit run.completed event with blocked result when max sessions reached."""
        from claude_task_master.core.state import TaskOptions

        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        options.max_sessions = 5
        state_manager.initialize(goal="Test goal", model="sonnet", options=options)
        state_manager.save_plan(basic_plan)

        # Set session count to max sessions
        state = state_manager.load_state()
        state.session_count = 5
        state_manager.save_state(state)

        exit_code = orchestrator_with_webhooks.run()
        assert exit_code == 1

        # Find the run.completed event call
        calls = mock_webhook_client.send_sync.call_args_list
        run_completed_calls = [c for c in calls if c.kwargs.get("event_type") == "run.completed"]

        assert len(run_completed_calls) == 1
        event_data = run_completed_calls[0].kwargs["data"]
        assert event_data["result"] == "blocked"
        assert event_data["exit_code"] == 1
        assert "Max sessions reached" in event_data["error_message"]

    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.start_listening")
    @patch("claude_task_master.core.orchestrator.unregister_handlers")
    @patch("claude_task_master.core.orchestrator.stop_listening")
    @patch("claude_task_master.core.orchestrator.reset_shutdown")
    @patch("claude_task_master.core.orchestrator.is_cancellation_requested")
    def test_run_completed_event_emitted_on_interruption(
        self,
        mock_cancel_requested,
        mock_reset_shutdown,
        mock_stop_listening,
        mock_unregister,
        mock_start_listening,
        mock_register,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        sample_task_options,
        basic_plan,
    ):
        """Should emit run.completed event with interrupted result when cancelled."""
        from claude_task_master.core.state import TaskOptions

        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test goal", model="sonnet", options=options)
        state_manager.save_plan(basic_plan)

        # Mock cancellation request
        mock_cancel_requested.return_value = True

        # Mock the work loop to check cancellation - always return an int exit code
        def mock_workflow_cycle(state):
            # Simulate cancellation during run
            if mock_cancel_requested():
                return 2
            return 0  # Default to success if not cancelled

        with patch.object(
            orchestrator_with_webhooks, "_run_workflow_cycle", side_effect=mock_workflow_cycle
        ):
            exit_code = orchestrator_with_webhooks.run()

        assert exit_code == 2

        # Find the run.completed event call
        calls = mock_webhook_client.send_sync.call_args_list
        run_completed_calls = [c for c in calls if c.kwargs.get("event_type") == "run.completed"]

        assert len(run_completed_calls) == 1
        event_data = run_completed_calls[0].kwargs["data"]
        assert event_data["result"] == "interrupted"
        assert event_data["exit_code"] == 2


class TestStatusChangedWebhooks:
    """Tests for status.changed webhook events."""

    def test_status_changed_event_emitted_on_transition(
        self,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
    ):
        """Should emit status.changed event when status transitions."""
        state_manager.state_dir.mkdir(exist_ok=True)

        orchestrator_with_webhooks._emit_status_changed(
            previous_status="working",
            new_status="completed",
            state=basic_task_state,
            reason="All tasks completed successfully",
        )

        # Find the status.changed event call
        calls = mock_webhook_client.send_sync.call_args_list
        status_changed_calls = [c for c in calls if c.kwargs.get("event_type") == "status.changed"]

        assert len(status_changed_calls) == 1
        event_data = status_changed_calls[0].kwargs["data"]
        assert event_data["event_type"] == "status.changed"
        assert event_data["previous_status"] == "working"
        assert event_data["new_status"] == "completed"
        assert event_data["reason"] == "All tasks completed successfully"
        assert event_data["task_index"] == 0
        assert event_data["session_number"] == 1

    def test_status_changed_event_not_emitted_if_status_unchanged(
        self,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
    ):
        """Should not emit status.changed event if status didn't change."""
        state_manager.state_dir.mkdir(exist_ok=True)

        orchestrator_with_webhooks._emit_status_changed(
            previous_status="working",
            new_status="working",  # Same status
            state=basic_task_state,
            reason="No change",
        )

        # Should not have emitted any event
        calls = mock_webhook_client.send_sync.call_args_list
        status_changed_calls = [c for c in calls if c.kwargs.get("event_type") == "status.changed"]

        assert len(status_changed_calls) == 0


class TestCIWebhooks:
    """Tests for ci.passed and ci.failed webhook events."""

    @patch("claude_task_master.core.workflow_stages.console")
    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    def test_ci_passed_event_emitted_when_checks_succeed(
        self,
        mock_sleep,
        mock_console,
        orchestrator_with_webhooks,
        state_manager,
        mock_github_client,
        mock_webhook_client,
        basic_task_state,
    ):
        """Should emit ci.passed event when CI checks pass."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.workflow_stage = "waiting_ci"
        basic_task_state.current_pr = 42

        # Mock successful CI
        mock_pr_status = Mock()
        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = "SUCCESS"
        mock_pr_status.checks_passed = 3
        mock_pr_status.checks_failed = 0
        mock_pr_status.checks_pending = 0
        mock_pr_status.checks_skipped = 1
        mock_pr_status.base_branch = "main"
        mock_pr_status.check_details = []
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.return_value = []

        # Handle waiting_ci stage
        orchestrator_with_webhooks._run_workflow_cycle(basic_task_state)

        # Find the ci.passed event call
        calls = mock_webhook_client.send_sync.call_args_list
        ci_passed_calls = [c for c in calls if c.kwargs.get("event_type") == "ci.passed"]

        assert len(ci_passed_calls) == 1
        event_data = ci_passed_calls[0].kwargs["data"]
        assert event_data["event_type"] == "ci.passed"
        assert event_data["pr_number"] == 42
        assert "branch" in event_data

    @patch("claude_task_master.core.workflow_stages.console")
    @patch("claude_task_master.core.workflow_stages.interruptible_sleep")
    def test_ci_failed_event_emitted_when_checks_fail(
        self,
        mock_sleep,
        mock_console,
        orchestrator_with_webhooks,
        state_manager,
        mock_github_client,
        mock_webhook_client,
        basic_task_state,
    ):
        """Should emit ci.failed event when CI checks fail."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.workflow_stage = "waiting_ci"
        basic_task_state.current_pr = 42

        # Mock failed CI
        mock_pr_status = Mock()
        mock_pr_status.state = "OPEN"
        mock_pr_status.ci_state = "FAILURE"
        mock_pr_status.checks_passed = 2
        mock_pr_status.checks_failed = 1
        mock_pr_status.checks_pending = 0
        mock_pr_status.checks_skipped = 0
        mock_pr_status.base_branch = "main"
        mock_pr_status.check_details = [
            {"name": "test-suite", "conclusion": "FAILURE"},
            {"name": "lint", "conclusion": "SUCCESS"},
        ]
        mock_github_client.get_pr_status.return_value = mock_pr_status
        mock_github_client.get_required_status_checks.return_value = []

        # Handle waiting_ci stage
        orchestrator_with_webhooks._run_workflow_cycle(basic_task_state)

        # Find the ci.failed event call
        calls = mock_webhook_client.send_sync.call_args_list
        ci_failed_calls = [c for c in calls if c.kwargs.get("event_type") == "ci.failed"]

        assert len(ci_failed_calls) == 1
        event_data = ci_failed_calls[0].kwargs["data"]
        assert event_data["event_type"] == "ci.failed"
        assert event_data["pr_number"] == 42
        assert "branch" in event_data
        assert "failure_reason" in event_data
        assert "test-suite" in event_data["failure_reason"]


class TestPlanUpdatedWebhooks:
    """Tests for plan.updated webhook events."""

    @patch("claude_task_master.core.orchestrator.console")
    def test_plan_updated_event_emitted_on_mailbox_update(
        self,
        mock_console,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should emit plan.updated event when plan is updated via mailbox."""
        from claude_task_master.mailbox.models import Priority

        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        # Add message to mailbox
        orchestrator_with_webhooks.mailbox_storage.add_message(
            content="Add feature X to the plan",
            sender="user",
            priority=Priority.NORMAL,
        )

        # Mock plan updater to succeed with changes
        mock_updater_result = {
            "success": True,
            "changes_made": True,
            "updated_plan": basic_plan + "\n- [ ] Task 4: Feature X",
        }
        with patch.object(
            orchestrator_with_webhooks.plan_updater,
            "update_plan",
            return_value=mock_updater_result,
        ):
            plan_updated = orchestrator_with_webhooks._check_and_process_mailbox(basic_task_state)

        assert plan_updated is True

        # Find the plan.updated event call
        calls = mock_webhook_client.send_sync.call_args_list
        plan_updated_calls = [c for c in calls if c.kwargs.get("event_type") == "plan.updated"]

        assert len(plan_updated_calls) == 1
        event_data = plan_updated_calls[0].kwargs["data"]
        assert event_data["event_type"] == "plan.updated"
        assert event_data["update_source"] == "mailbox"
        assert "message" in event_data
        assert "total_tasks" in event_data
        assert "completed_tasks" in event_data
        assert event_data["tasks_added"] >= 0

    @patch("claude_task_master.core.orchestrator.console")
    def test_plan_updated_event_with_no_changes(
        self,
        mock_console,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        basic_task_state,
        basic_plan,
    ):
        """Should emit plan.updated event even when plan doesn't change."""
        from claude_task_master.mailbox.models import Priority

        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        # Add message to mailbox
        orchestrator_with_webhooks.mailbox_storage.add_message(
            content="No actual changes needed",
            sender="user",
            priority=Priority.LOW,
        )

        # Mock plan updater to return same plan (no changes)
        mock_updater_result = {
            "success": True,
            "changes_made": False,
            "updated_plan": basic_plan,  # Same plan
        }
        with patch.object(
            orchestrator_with_webhooks.plan_updater,
            "update_plan",
            return_value=mock_updater_result,
        ):
            plan_updated = orchestrator_with_webhooks._check_and_process_mailbox(basic_task_state)

        assert plan_updated is False

        # Find the plan.updated event call
        calls = mock_webhook_client.send_sync.call_args_list
        plan_updated_calls = [c for c in calls if c.kwargs.get("event_type") == "plan.updated"]

        # Should still emit event even though plan didn't change
        assert len(plan_updated_calls) == 1
        event_data = plan_updated_calls[0].kwargs["data"]
        assert event_data["event_type"] == "plan.updated"
        assert event_data["update_source"] == "mailbox"
        assert event_data["tasks_added"] == 0
        assert event_data["tasks_removed"] == 0


# =============================================================================
# Test PR Count Tracking in Webhook Events
# =============================================================================


class TestPRCountTrackingWebhooks:
    """Tests for PR count tracking in webhook events."""

    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.start_listening")
    def test_run_completed_includes_pr_counts(
        self,
        mock_start_listening,
        mock_register,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        sample_task_options,
        basic_plan,
    ):
        """Should include PR counts in run.completed webhook event."""
        from claude_task_master.core.state import TaskOptions

        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test PR tracking", model="sonnet", options=options)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test PR tracking")

        # Set up initial PR counts
        state = state_manager.load_state()
        state.prs_created = 3
        state.prs_merged = 2
        state_manager.save_state(state)

        # Mock the work loop to exit with success
        with patch.object(orchestrator_with_webhooks, "_run_workflow_cycle", return_value=0):
            exit_code = orchestrator_with_webhooks.run()

        assert exit_code == 0

        # Find the run.completed event call
        calls = mock_webhook_client.send_sync.call_args_list
        run_completed_calls = [c for c in calls if c.kwargs.get("event_type") == "run.completed"]

        assert len(run_completed_calls) == 1
        event_data = run_completed_calls[0].kwargs["data"]
        assert event_data["event_type"] == "run.completed"
        assert event_data["prs_created"] == 3
        assert event_data["prs_merged"] == 2
        assert event_data["result"] == "success"

    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.start_listening")
    def test_run_completed_with_zero_pr_counts(
        self,
        mock_start_listening,
        mock_register,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        sample_task_options,
        basic_plan,
    ):
        """Should include zero PR counts when no PRs have been created."""
        from claude_task_master.core.state import TaskOptions

        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="No PRs", model="sonnet", options=options)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("No PRs")

        # Verify initial state has zero PR counts
        state = state_manager.load_state()
        assert state.prs_created == 0
        assert state.prs_merged == 0

        # Mock the work loop to exit with success
        with patch.object(orchestrator_with_webhooks, "_run_workflow_cycle", return_value=0):
            exit_code = orchestrator_with_webhooks.run()

        assert exit_code == 0

        # Find the run.completed event call
        calls = mock_webhook_client.send_sync.call_args_list
        run_completed_calls = [c for c in calls if c.kwargs.get("event_type") == "run.completed"]

        assert len(run_completed_calls) == 1
        event_data = run_completed_calls[0].kwargs["data"]
        assert event_data["prs_created"] == 0
        assert event_data["prs_merged"] == 0

    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.start_listening")
    def test_run_completed_blocked_includes_pr_counts(
        self,
        mock_start_listening,
        mock_register,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        sample_task_options,
        basic_plan,
    ):
        """Should include PR counts in run.completed event even when blocked."""
        from claude_task_master.core.state import TaskOptions

        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        options.max_sessions = 3
        state_manager.initialize(goal="Test PR counts on blocked", model="sonnet", options=options)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test PR counts on blocked")

        # Set up PR counts
        state = state_manager.load_state()
        state.session_count = 3
        state.prs_created = 5
        state.prs_merged = 3
        state_manager.save_state(state)

        # Run orchestrator (should exit due to max sessions)
        exit_code = orchestrator_with_webhooks.run()
        assert exit_code == 1

        # Find the run.completed event call
        calls = mock_webhook_client.send_sync.call_args_list
        run_completed_calls = [c for c in calls if c.kwargs.get("event_type") == "run.completed"]

        assert len(run_completed_calls) == 1
        event_data = run_completed_calls[0].kwargs["data"]
        assert event_data["result"] == "blocked"
        assert event_data["prs_created"] == 5
        assert event_data["prs_merged"] == 3

    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.start_listening")
    @patch("claude_task_master.core.orchestrator.unregister_handlers")
    @patch("claude_task_master.core.orchestrator.stop_listening")
    @patch("claude_task_master.core.orchestrator.reset_shutdown")
    @patch("claude_task_master.core.orchestrator.is_cancellation_requested")
    def test_run_completed_interrupted_includes_pr_counts(
        self,
        mock_cancel_requested,
        mock_reset_shutdown,
        mock_stop_listening,
        mock_unregister,
        mock_start_listening,
        mock_register,
        orchestrator_with_webhooks,
        state_manager,
        mock_webhook_client,
        sample_task_options,
        basic_plan,
    ):
        """Should include PR counts in run.completed event when interrupted."""
        from claude_task_master.core.state import TaskOptions

        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(
            goal="Test PR counts on interrupt", model="sonnet", options=options
        )
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test PR counts on interrupt")

        # Set up PR counts
        state = state_manager.load_state()
        state.prs_created = 2
        state.prs_merged = 1
        state_manager.save_state(state)

        # Mock cancellation request
        mock_cancel_requested.return_value = True

        # Mock the work loop to check cancellation - always return an int exit code
        def mock_workflow_cycle(state):
            # Simulate cancellation during run
            if mock_cancel_requested():
                return 2
            return 0  # Default to success if not cancelled

        with patch.object(
            orchestrator_with_webhooks,
            "_run_workflow_cycle",
            side_effect=mock_workflow_cycle,
        ):
            exit_code = orchestrator_with_webhooks.run()

        assert exit_code == 2

        # Find the run.completed event call
        calls = mock_webhook_client.send_sync.call_args_list
        run_completed_calls = [c for c in calls if c.kwargs.get("event_type") == "run.completed"]

        assert len(run_completed_calls) == 1
        event_data = run_completed_calls[0].kwargs["data"]
        assert event_data["result"] == "interrupted"
        assert event_data["prs_created"] == 2
        assert event_data["prs_merged"] == 1

    @patch("claude_task_master.core.workflow_stages.console")
    def test_pr_created_event_increments_count(
        self,
        mock_console,
        orchestrator_with_webhooks,
        state_manager,
        mock_github_client,
        mock_webhook_client,
        basic_task_state,
        sample_task_options,
    ):
        """Should increment prs_created count when PR is created."""
        from claude_task_master.core.state import TaskOptions

        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test PR created", model="sonnet", options=options)
        basic_task_state.workflow_stage = "pr_created"

        # Mock GitHub to return a PR
        mock_github_client.get_pr_for_current_branch.return_value = 42
        mock_pr_status = Mock()
        mock_pr_status.pr_url = "https://github.com/owner/repo/pull/42"
        mock_pr_status.pr_title = "Test PR"
        mock_pr_status.base_branch = "main"
        mock_pr_status.ci_state = "SUCCESS"
        mock_pr_status.checks_pending = 0
        mock_github_client.get_pr_status.return_value = mock_pr_status

        # Handle PR creation stage
        orchestrator_with_webhooks._run_workflow_cycle(basic_task_state)

        # Verify counter was incremented
        updated_state = state_manager.load_state()
        assert updated_state.prs_created == 1

        # Find the pr.created event call
        calls = mock_webhook_client.send_sync.call_args_list
        pr_created_calls = [c for c in calls if c.kwargs.get("event_type") == "pr.created"]

        assert len(pr_created_calls) == 1
        event_data = pr_created_calls[0].kwargs["data"]
        assert event_data["event_type"] == "pr.created"
        assert event_data["pr_number"] == 42

    @patch("claude_task_master.core.workflow_stages.console")
    @patch("claude_task_master.core.orchestrator.interruptible_sleep")
    def test_pr_merged_event_increments_count(
        self,
        mock_sleep,
        mock_console,
        orchestrator_with_webhooks,
        state_manager,
        mock_github_client,
        mock_webhook_client,
        basic_task_state,
        sample_task_options,
    ):
        """Should increment prs_merged count when PR is merged."""
        from claude_task_master.core.state import TaskOptions

        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test PR merged", model="sonnet", options=options)
        basic_task_state.workflow_stage = "ready_to_merge"
        basic_task_state.current_pr = 42
        basic_task_state.options.auto_merge = True

        # Mock GitHub PR status
        mock_pr_status = Mock()
        mock_pr_status.pr_url = "https://github.com/owner/repo/pull/42"
        mock_pr_status.pr_title = "Test PR"
        mock_pr_status.base_branch = "main"
        mock_pr_status.ci_state = "SUCCESS"
        mock_pr_status.checks_pending = 0
        mock_pr_status.reviews_approved = 1
        mock_pr_status.reviews_requested = 0
        mock_github_client.get_pr_status.return_value = mock_pr_status

        # Mock successful merge
        mock_github_client.merge_pr.return_value = True

        # Handle PR merge stage
        orchestrator_with_webhooks._run_workflow_cycle(basic_task_state)

        # Verify counter was incremented
        updated_state = state_manager.load_state()
        assert updated_state.prs_merged == 1

        # Find the pr.merged event call
        calls = mock_webhook_client.send_sync.call_args_list
        pr_merged_calls = [c for c in calls if c.kwargs.get("event_type") == "pr.merged"]

        assert len(pr_merged_calls) == 1
        event_data = pr_merged_calls[0].kwargs["data"]
        assert event_data["event_type"] == "pr.merged"
        assert event_data["pr_number"] == 42
        assert event_data["auto_merged"] is True
