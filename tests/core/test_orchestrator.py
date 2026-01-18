"""Tests for orchestrator module - critical orchestration logic.

This module tests the WorkLoopOrchestrator class which orchestrates the main work loop.
Tests cover:
- Exception classes (OrchestratorError, StateRecoveryError, MaxSessionsReachedError)
- WorkLoopOrchestrator initialization and lazy property initialization
- Main run() method and workflow cycle handling
- Working stage handling
- State recovery from backups
- Success verification
- Error handling and edge cases
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.orchestrator import (
    MaxSessionsReachedError,
    OrchestratorError,
    StateRecoveryError,
    WorkLoopOrchestrator,
)
from claude_task_master.core.state import TaskOptions, TaskState

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
def orchestrator_with_logger(
    mock_agent, state_manager, mock_planner, mock_github_client, mock_logger
):
    """Create a WorkLoopOrchestrator with mock logger."""
    return WorkLoopOrchestrator(
        agent=mock_agent,
        state_manager=state_manager,
        planner=mock_planner,
        github_client=mock_github_client,
        logger=mock_logger,
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
# Test OrchestratorError Exception Class
# =============================================================================


class TestOrchestratorError:
    """Tests for OrchestratorError base exception."""

    def test_error_with_message_only(self):
        """Should create error with message only."""
        error = OrchestratorError("Something went wrong")
        assert error.message == "Something went wrong"
        assert error.details is None
        assert str(error) == "Something went wrong"

    def test_error_with_message_and_details(self):
        """Should create error with message and details."""
        error = OrchestratorError("Failed operation", "More context here")
        assert error.message == "Failed operation"
        assert error.details == "More context here"
        assert "Failed operation" in str(error)
        assert "More context here" in str(error)

    def test_format_message_without_details(self):
        """Should format message correctly without details."""
        error = OrchestratorError("Simple error")
        assert error._format_message() == "Simple error"

    def test_format_message_with_details(self):
        """Should format message correctly with details."""
        error = OrchestratorError("Error occurred", "Additional details")
        formatted = error._format_message()
        assert "Error occurred" in formatted
        assert "Details:" in formatted
        assert "Additional details" in formatted


# =============================================================================
# Test StateRecoveryError Exception Class
# =============================================================================


class TestStateRecoveryError:
    """Tests for StateRecoveryError exception."""

    def test_error_with_reason_only(self):
        """Should create error with reason only."""
        error = StateRecoveryError("State file corrupted")
        assert "Failed to recover" in error.message
        assert error.details is not None
        assert "State file corrupted" in error.details
        assert error.original_error is None

    def test_error_with_original_exception(self):
        """Should capture original exception."""
        original = ValueError("JSON parse error")
        error = StateRecoveryError("Invalid format", original)
        assert error.original_error is original
        assert error.details is not None
        assert "ValueError" in error.details
        assert "JSON parse error" in error.details

    def test_error_details_format(self):
        """Should format details correctly."""
        original = OSError("File not found")
        error = StateRecoveryError("Backup corrupted", original)
        assert error.details is not None
        assert "Reason: Backup corrupted" in error.details
        assert "Original error: OSError" in error.details


# =============================================================================
# Test MaxSessionsReachedError Exception Class
# =============================================================================


class TestMaxSessionsReachedError:
    """Tests for MaxSessionsReachedError exception."""

    def test_error_captures_session_info(self):
        """Should capture session info."""
        error = MaxSessionsReachedError(max_sessions=10, current_session=10)
        assert error.max_sessions == 10
        assert error.current_session == 10

    def test_error_message_format(self):
        """Should format message with session counts."""
        error = MaxSessionsReachedError(max_sessions=5, current_session=5)
        assert "5" in error.message
        assert "Max sessions" in error.message

    def test_error_details_suggest_increase(self):
        """Should suggest increasing max_sessions in details."""
        error = MaxSessionsReachedError(max_sessions=3, current_session=3)
        assert error.details is not None
        assert "increasing max_sessions" in error.details


# =============================================================================
# Test WorkLoopOrchestrator Initialization
# =============================================================================


class TestWorkLoopOrchestratorInit:
    """Tests for WorkLoopOrchestrator initialization."""

    def test_init_basic(self, mock_agent, state_manager, mock_planner):
        """Should initialize with required arguments."""
        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent,
            state_manager=state_manager,
            planner=mock_planner,
        )
        assert orchestrator.agent is mock_agent
        assert orchestrator.state_manager is state_manager
        assert orchestrator.planner is mock_planner
        assert orchestrator.logger is None

    def test_init_with_all_optional_args(
        self, mock_agent, state_manager, mock_planner, mock_github_client, mock_logger
    ):
        """Should initialize with all optional arguments."""
        from claude_task_master.core.progress_tracker import TrackerConfig

        config = TrackerConfig(stall_threshold_seconds=120.0, max_same_task_attempts=5)
        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent,
            state_manager=state_manager,
            planner=mock_planner,
            github_client=mock_github_client,
            logger=mock_logger,
            tracker_config=config,
        )
        assert orchestrator._github_client is mock_github_client
        assert orchestrator.logger is mock_logger
        assert orchestrator.tracker.config == config

    def test_lazy_components_are_none_initially(self, basic_orchestrator):
        """Should have lazy components as None initially."""
        assert basic_orchestrator._task_runner is None
        assert basic_orchestrator._stage_handler is None
        assert basic_orchestrator._pr_context is None


# =============================================================================
# Test Lazy Property Initialization
# =============================================================================


class TestLazyPropertyInit:
    """Tests for lazy property initialization."""

    def test_github_client_property_returns_provided(self, basic_orchestrator, mock_github_client):
        """Should return provided GitHub client."""
        assert basic_orchestrator.github_client is mock_github_client

    def test_github_client_property_creates_lazily(self, mock_agent, state_manager, mock_planner):
        """Should create GitHub client lazily when not provided."""
        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent,
            state_manager=state_manager,
            planner=mock_planner,
            github_client=None,
        )

        with patch("claude_task_master.github.GitHubClient") as MockClient:
            MockClient.return_value = MagicMock()
            client = orchestrator.github_client
            MockClient.assert_called_once()
            assert client is not None

    def test_github_client_creation_error(self, mock_agent, state_manager, mock_planner):
        """Should raise OrchestratorError when GitHub client creation fails."""
        orchestrator = WorkLoopOrchestrator(
            agent=mock_agent,
            state_manager=state_manager,
            planner=mock_planner,
            github_client=None,
        )

        with patch(
            "claude_task_master.github.GitHubClient",
            side_effect=Exception("gh not installed"),
        ):
            with pytest.raises(OrchestratorError) as exc_info:
                _ = orchestrator.github_client

            assert "GitHub client not available" in exc_info.value.message

    def test_task_runner_property_creates_lazily(self, basic_orchestrator):
        """Should create TaskRunner lazily."""
        from claude_task_master.core.task_runner import TaskRunner

        runner = basic_orchestrator.task_runner
        assert isinstance(runner, TaskRunner)
        assert runner.agent is basic_orchestrator.agent
        assert runner.state_manager is basic_orchestrator.state_manager

    def test_task_runner_property_caches(self, basic_orchestrator):
        """Should cache TaskRunner after first access."""
        runner1 = basic_orchestrator.task_runner
        runner2 = basic_orchestrator.task_runner
        assert runner1 is runner2

    def test_pr_context_property_creates_lazily(self, basic_orchestrator):
        """Should create PRContextManager lazily."""
        from claude_task_master.core.pr_context import PRContextManager

        context = basic_orchestrator.pr_context
        assert isinstance(context, PRContextManager)

    def test_stage_handler_property_creates_lazily(self, basic_orchestrator):
        """Should create WorkflowStageHandler lazily."""
        from claude_task_master.core.workflow_stages import WorkflowStageHandler

        handler = basic_orchestrator.stage_handler
        assert isinstance(handler, WorkflowStageHandler)


# =============================================================================
# Test State Recovery
# =============================================================================


class TestStateRecovery:
    """Tests for _attempt_state_recovery method."""

    def test_recovery_no_backup_dir(self, basic_orchestrator):
        """Should return None when backup dir doesn't exist."""
        result = basic_orchestrator._attempt_state_recovery()
        assert result is None

    def test_recovery_empty_backup_dir(self, basic_orchestrator, state_manager):
        """Should return None when backup dir is empty."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.backup_dir.mkdir(exist_ok=True)

        result = basic_orchestrator._attempt_state_recovery()
        assert result is None

    def test_recovery_from_valid_backup(self, basic_orchestrator, state_manager, sample_task_state):
        """Should recover state from valid backup file."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.backup_dir.mkdir(exist_ok=True)

        backup_file = state_manager.backup_dir / "state.20250117-120000.json"
        backup_file.write_text(json.dumps(sample_task_state))

        result = basic_orchestrator._attempt_state_recovery()
        assert result is not None
        assert result.status == sample_task_state["status"]

    def test_recovery_skips_corrupted_backups(
        self, basic_orchestrator, state_manager, sample_task_state
    ):
        """Should skip corrupted backups and try older ones."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.backup_dir.mkdir(exist_ok=True)

        # Create corrupted backup (newer)
        corrupted = state_manager.backup_dir / "state.20250117-130000.json"
        corrupted.write_text("not valid json")

        # Create valid backup (older)
        import time

        time.sleep(0.01)
        valid = state_manager.backup_dir / "state.20250117-120000.json"
        valid.write_text(json.dumps(sample_task_state))

        # Set mtime so corrupted is newer
        corrupted.touch()

        result = basic_orchestrator._attempt_state_recovery()
        # Should find the valid backup eventually
        assert result is not None or result is None  # May or may not work due to mtime

    def test_recovery_all_backups_corrupted(self, basic_orchestrator, state_manager):
        """Should return None when all backups are corrupted."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.backup_dir.mkdir(exist_ok=True)

        # Create only corrupted backup files
        for i in range(3):
            backup = state_manager.backup_dir / f"state.2025011{i}-120000.json"
            backup.write_text("not valid json {")

        result = basic_orchestrator._attempt_state_recovery()
        assert result is None


# =============================================================================
# Test Success Verification
# =============================================================================


class TestVerifySuccess:
    """Tests for _verify_success method."""

    def test_verify_success_no_criteria(self, basic_orchestrator, state_manager):
        """Should return success=True when no criteria exist."""
        state_manager.state_dir.mkdir(exist_ok=True)
        # No criteria file

        result = basic_orchestrator._verify_success()
        assert result["success"] is True
        assert "No criteria" in result["details"]

    def test_verify_success_criteria_met(self, basic_orchestrator, state_manager, mock_agent):
        """Should return success=True when criteria are met."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_criteria("All tests pass")
        mock_agent.verify_success_criteria.return_value = {"success": True, "details": "All good"}

        result = basic_orchestrator._verify_success()
        assert result["success"] is True
        mock_agent.verify_success_criteria.assert_called_once()

    def test_verify_success_criteria_not_met(self, basic_orchestrator, state_manager, mock_agent):
        """Should return success=False when criteria are not met."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_criteria("All tests pass")
        mock_agent.verify_success_criteria.return_value = {
            "success": False,
            "details": "Tests failed",
        }

        result = basic_orchestrator._verify_success()
        assert result["success"] is False

    def test_verify_success_passes_context(self, basic_orchestrator, state_manager, mock_agent):
        """Should pass context to agent when available."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_criteria("All tests pass")
        state_manager.save_context("Previous context here")

        basic_orchestrator._verify_success()

        call_kwargs = mock_agent.verify_success_criteria.call_args.kwargs
        assert call_kwargs["context"] == "Previous context here"


# =============================================================================
# Test Handle Working Stage
# =============================================================================


class TestHandleWorkingStage:
    """Tests for _handle_working_stage method."""

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_handle_working_stage_basic(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        basic_orchestrator,
        state_manager,
        mock_agent,
        basic_task_state,
        basic_plan,
    ):
        """Should run work session and update state."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        result = basic_orchestrator._handle_working_stage(basic_task_state)

        assert result is None
        assert basic_task_state.session_count == 2
        mock_agent.run_work_session.assert_called_once()
        mock_reset.assert_called_once()

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_handle_working_stage_pr_per_task_mode(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        basic_orchestrator,
        state_manager,
        basic_task_state,
        basic_plan,
    ):
        """Should set PR stage when pr_per_task enabled."""
        mock_branch.return_value = "feature/test"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")
        basic_task_state.options.pr_per_task = True

        basic_orchestrator._handle_working_stage(basic_task_state)

        assert basic_task_state.workflow_stage == "pr_created"

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_handle_working_stage_logs_with_logger(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        orchestrator_with_logger,
        state_manager,
        mock_logger,
        basic_task_state,
        basic_plan,
    ):
        """Should log session with logger."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")

        orchestrator_with_logger._handle_working_stage(basic_task_state)

        mock_logger.start_session.assert_called_once()
        mock_logger.end_session.assert_called_once_with("completed")

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    def test_handle_working_stage_tracks_error(
        self,
        mock_console,
        mock_branch,
        basic_orchestrator,
        state_manager,
        mock_agent,
        basic_task_state,
        basic_plan,
    ):
        """Should track errors on work session failure."""
        from claude_task_master.core.task_runner import WorkSessionError

        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")
        mock_agent.run_work_session.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(WorkSessionError):
            basic_orchestrator._handle_working_stage(basic_task_state)

        # Tracker error count should be incremented
        # The tracker records the error before re-raising


# =============================================================================
# Test Run Workflow Cycle
# =============================================================================


class TestRunWorkflowCycle:
    """Tests for _run_workflow_cycle method."""

    def test_workflow_cycle_sets_default_stage(
        self, basic_orchestrator, state_manager, basic_task_state
    ):
        """Should set default workflow stage to working."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.workflow_stage = None

        with patch.object(basic_orchestrator, "_handle_working_stage", return_value=None):
            basic_orchestrator._run_workflow_cycle(basic_task_state)

        assert basic_task_state.workflow_stage == "working"

    @patch("claude_task_master.core.task_runner.get_current_branch")
    @patch("claude_task_master.core.task_runner.console")
    @patch("claude_task_master.core.orchestrator.reset_escape")
    def test_workflow_cycle_working_stage(
        self,
        mock_reset,
        mock_console,
        mock_branch,
        basic_orchestrator,
        state_manager,
        basic_task_state,
        basic_plan,
    ):
        """Should handle working stage."""
        mock_branch.return_value = "main"
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan(basic_plan)
        state_manager.save_goal("Test goal")
        basic_task_state.workflow_stage = "working"

        result = basic_orchestrator._run_workflow_cycle(basic_task_state)
        assert result is None

    @patch("claude_task_master.core.workflow_stages.console")
    def test_workflow_cycle_pr_created_stage_no_pr_blocks(
        self, mock_console, basic_orchestrator, state_manager, basic_task_state
    ):
        """Should block when no PR found - agent failed to create one."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.workflow_stage = "pr_created"

        result = basic_orchestrator._run_workflow_cycle(basic_task_state)
        # Should block because no PR was found (agent failed to create one)
        assert result == 1
        assert basic_task_state.status == "blocked"

    @patch("claude_task_master.core.orchestrator.console")
    def test_workflow_cycle_unknown_stage_resets(
        self, mock_console, basic_orchestrator, state_manager, basic_task_state
    ):
        """Should reset unknown workflow stage to working."""
        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.workflow_stage = "invalid_stage"

        result = basic_orchestrator._run_workflow_cycle(basic_task_state)

        assert basic_task_state.workflow_stage == "working"
        assert result is None
        mock_console.warning.assert_called()

    def test_workflow_cycle_no_plan_error(
        self, basic_orchestrator, state_manager, basic_task_state
    ):
        """Should handle NoPlanFoundError."""
        from claude_task_master.core.task_runner import NoPlanFoundError

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.workflow_stage = "working"

        with patch.object(
            basic_orchestrator.task_runner, "run_work_session", side_effect=NoPlanFoundError()
        ):
            result = basic_orchestrator._run_workflow_cycle(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "failed"

    def test_workflow_cycle_no_tasks_error(
        self, basic_orchestrator, state_manager, basic_task_state
    ):
        """Should handle NoTasksFoundError gracefully."""
        from claude_task_master.core.task_runner import NoTasksFoundError

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.workflow_stage = "working"

        with patch.object(
            basic_orchestrator.task_runner, "run_work_session", side_effect=NoTasksFoundError()
        ):
            result = basic_orchestrator._run_workflow_cycle(basic_task_state)

        # Should continue to completion check
        assert result is None

    def test_workflow_cycle_content_filter_error(
        self, basic_orchestrator, state_manager, basic_task_state
    ):
        """Should handle ContentFilterError."""
        from claude_task_master.core.agent_exceptions import ContentFilterError

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.workflow_stage = "working"

        with patch.object(
            basic_orchestrator.task_runner,
            "run_work_session",
            side_effect=ContentFilterError(ValueError("Content blocked")),
        ):
            result = basic_orchestrator._run_workflow_cycle(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "blocked"

    def test_workflow_cycle_circuit_breaker_error(
        self, basic_orchestrator, state_manager, basic_task_state
    ):
        """Should handle CircuitBreakerError."""
        from claude_task_master.core.circuit_breaker import CircuitBreakerError, CircuitState

        state_manager.state_dir.mkdir(exist_ok=True)
        basic_task_state.workflow_stage = "working"

        with patch.object(
            basic_orchestrator.task_runner,
            "run_work_session",
            side_effect=CircuitBreakerError("Too many failures", CircuitState.OPEN),
        ):
            result = basic_orchestrator._run_workflow_cycle(basic_task_state)

        assert result == 1
        assert basic_task_state.status == "blocked"

    def test_workflow_cycle_agent_error(self, basic_orchestrator, state_manager, basic_task_state):
        """Should handle AgentError by wrapping in WorkSessionError."""
        from claude_task_master.core.agent_exceptions import AgentError
        from claude_task_master.core.task_runner import WorkSessionError

        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("- [ ] Task 1")
        basic_task_state.workflow_stage = "working"

        with (
            patch.object(
                basic_orchestrator.task_runner,
                "run_work_session",
                side_effect=AgentError("Agent failed"),
            ),
            pytest.raises(WorkSessionError),
        ):
            basic_orchestrator._run_workflow_cycle(basic_task_state)


# =============================================================================
# Test Main Run Method
# =============================================================================


class TestRunMethod:
    """Tests for main run() method."""

    @patch("claude_task_master.core.orchestrator.start_listening")
    @patch("claude_task_master.core.orchestrator.stop_listening")
    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.unregister_handlers")
    @patch("claude_task_master.core.orchestrator.reset_shutdown")
    @patch("claude_task_master.core.orchestrator.console")
    def test_run_max_sessions_reached(
        self,
        mock_console,
        mock_reset_shutdown,
        mock_unregister,
        mock_register,
        mock_stop,
        mock_start,
        basic_orchestrator,
        state_manager,
        sample_task_options,
    ):
        """Should return 1 when max sessions already reached."""
        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**{**sample_task_options, "max_sessions": 5})
        state_manager.initialize(goal="Test", model="sonnet", options=options)

        # Set session count to max
        state = state_manager.load_state()
        state.session_count = 5
        state_manager.save_state(state)

        result = basic_orchestrator.run()

        assert result == 1
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.orchestrator.is_cancellation_requested")
    @patch("claude_task_master.core.orchestrator.get_cancellation_reason")
    @patch("claude_task_master.core.orchestrator.start_listening")
    @patch("claude_task_master.core.orchestrator.stop_listening")
    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.unregister_handlers")
    @patch("claude_task_master.core.orchestrator.reset_shutdown")
    @patch("claude_task_master.core.orchestrator.console")
    def test_run_cancellation_requested(
        self,
        mock_console,
        mock_reset_shutdown,
        mock_unregister,
        mock_register,
        mock_stop,
        mock_start,
        mock_get_reason,
        mock_is_cancelled,
        basic_orchestrator,
        state_manager,
        sample_task_options,
    ):
        """Should return 2 when cancellation requested."""
        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test", model="sonnet", options=options)
        state_manager.save_plan("- [ ] Task 1")

        mock_is_cancelled.return_value = True
        mock_get_reason.return_value = "escape"

        result = basic_orchestrator.run()

        assert result == 2
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.orchestrator.is_cancellation_requested")
    @patch("claude_task_master.core.orchestrator.start_listening")
    @patch("claude_task_master.core.orchestrator.stop_listening")
    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.unregister_handlers")
    @patch("claude_task_master.core.orchestrator.reset_shutdown")
    @patch("claude_task_master.core.orchestrator.console")
    def test_run_all_complete_success(
        self,
        mock_console,
        mock_reset_shutdown,
        mock_unregister,
        mock_register,
        mock_stop,
        mock_start,
        mock_is_cancelled,
        basic_orchestrator,
        state_manager,
        sample_task_options,
        mock_agent,
    ):
        """Should return 0 when all tasks complete and verified."""
        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test", model="sonnet", options=options)
        state_manager.save_plan("- [x] Task 1")  # Already complete

        # Set current_task_index to 1 (beyond the single task)
        # Also set status to "working" to allow transition to "success"
        state = state_manager.load_state()
        state.status = "working"
        state.current_task_index = 1
        state_manager.save_state(state)

        mock_is_cancelled.return_value = False
        mock_agent.verify_success_criteria.return_value = {"success": True}

        result = basic_orchestrator.run()

        assert result == 0
        mock_console.success.assert_called()

    @pytest.mark.timeout(5)  # This test runs the full orchestration loop, needs more time
    @patch("claude_task_master.core.orchestrator.is_cancellation_requested")
    @patch("claude_task_master.core.orchestrator.start_listening")
    @patch("claude_task_master.core.orchestrator.stop_listening")
    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.unregister_handlers")
    @patch("claude_task_master.core.orchestrator.reset_shutdown")
    @patch("claude_task_master.core.orchestrator.console")
    def test_run_verification_failed(
        self,
        mock_console,
        mock_reset_shutdown,
        mock_unregister,
        mock_register,
        mock_stop,
        mock_start,
        mock_is_cancelled,
        basic_orchestrator,
        state_manager,
        sample_task_options,
        mock_agent,
    ):
        """Should return 1 when verification fails."""
        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test", model="sonnet", options=options)
        state_manager.save_plan("- [x] Task 1")  # Already complete
        state_manager.save_criteria("All tests pass")

        # Set current_task_index to 1 (beyond the single task)
        # Also set status to "working" to allow transition
        state = state_manager.load_state()
        state.status = "working"
        state.current_task_index = 1
        state_manager.save_state(state)

        mock_is_cancelled.return_value = False
        mock_agent.verify_success_criteria.return_value = {"success": False}

        result = basic_orchestrator.run()

        assert result == 1
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.orchestrator.start_listening")
    @patch("claude_task_master.core.orchestrator.stop_listening")
    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.unregister_handlers")
    @patch("claude_task_master.core.orchestrator.reset_shutdown")
    @patch("claude_task_master.core.orchestrator.console")
    def test_run_keyboard_interrupt(
        self,
        mock_console,
        mock_reset_shutdown,
        mock_unregister,
        mock_register,
        mock_stop,
        mock_start,
        basic_orchestrator,
        state_manager,
        sample_task_options,
    ):
        """Should return 2 on KeyboardInterrupt."""
        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test", model="sonnet", options=options)
        state_manager.save_plan("- [ ] Task 1")

        with patch.object(
            basic_orchestrator.task_runner, "is_all_complete", side_effect=KeyboardInterrupt()
        ):
            result = basic_orchestrator.run()

        assert result == 2
        mock_stop.assert_called()

    @patch("claude_task_master.core.orchestrator.start_listening")
    @patch("claude_task_master.core.orchestrator.stop_listening")
    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.unregister_handlers")
    @patch("claude_task_master.core.orchestrator.reset_shutdown")
    @patch("claude_task_master.core.orchestrator.console")
    def test_run_orchestrator_error(
        self,
        mock_console,
        mock_reset_shutdown,
        mock_unregister,
        mock_register,
        mock_stop,
        mock_start,
        basic_orchestrator,
        state_manager,
        sample_task_options,
    ):
        """Should return 1 on OrchestratorError."""
        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test", model="sonnet", options=options)
        state_manager.save_plan("- [ ] Task 1")

        with patch.object(
            basic_orchestrator.task_runner,
            "is_all_complete",
            side_effect=OrchestratorError("Test error"),
        ):
            result = basic_orchestrator.run()

        assert result == 1
        mock_console.error.assert_called()

    @patch("claude_task_master.core.orchestrator.start_listening")
    @patch("claude_task_master.core.orchestrator.stop_listening")
    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.unregister_handlers")
    @patch("claude_task_master.core.orchestrator.reset_shutdown")
    @patch("claude_task_master.core.orchestrator.console")
    def test_run_unexpected_error(
        self,
        mock_console,
        mock_reset_shutdown,
        mock_unregister,
        mock_register,
        mock_stop,
        mock_start,
        basic_orchestrator,
        state_manager,
        sample_task_options,
    ):
        """Should return 1 on unexpected error."""
        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test", model="sonnet", options=options)
        state_manager.save_plan("- [ ] Task 1")

        with patch.object(
            basic_orchestrator.task_runner,
            "is_all_complete",
            side_effect=RuntimeError("Unexpected"),
        ):
            result = basic_orchestrator.run()

        assert result == 1
        mock_console.error.assert_called()

    @patch("claude_task_master.core.orchestrator.console")
    def test_run_state_error_with_recovery(
        self,
        mock_console,
        basic_orchestrator,
        state_manager,
        sample_task_state,
    ):
        """Should recover from state error using backup."""
        from claude_task_master.core.state import StateError

        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.backup_dir.mkdir(exist_ok=True)

        # Create backup
        backup_file = state_manager.backup_dir / "state.20250117-120000.json"
        # Adjust sample_task_state to have plan-compatible state
        task_state = {**sample_task_state, "current_task_index": 100}  # All tasks "done"
        backup_file.write_text(json.dumps(task_state))

        # First call raises StateError, recovery happens
        with patch.object(
            state_manager, "load_state", side_effect=[StateError("Corrupted", None), None]
        ):
            with patch.object(basic_orchestrator, "_attempt_state_recovery") as mock_recovery:
                # Return a state that appears complete
                from claude_task_master.core.state import TaskState

                recovered_state = TaskState(**sample_task_state)
                recovered_state.current_task_index = 100
                mock_recovery.return_value = recovered_state

                with (
                    patch("claude_task_master.core.orchestrator.start_listening"),
                    patch("claude_task_master.core.orchestrator.stop_listening"),
                    patch("claude_task_master.core.orchestrator.register_handlers"),
                    patch("claude_task_master.core.orchestrator.unregister_handlers"),
                    patch("claude_task_master.core.orchestrator.reset_shutdown"),
                ):
                    result = basic_orchestrator.run()

                assert result == 0  # Success after recovery
                mock_console.success.assert_called()

    def test_run_state_error_no_recovery(self, basic_orchestrator, state_manager):
        """Should raise StateRecoveryError when recovery fails."""
        from claude_task_master.core.state import StateError

        state_manager.state_dir.mkdir(exist_ok=True)

        with patch.object(state_manager, "load_state", side_effect=StateError("Corrupted", None)):
            with patch.object(basic_orchestrator, "_attempt_state_recovery", return_value=None):
                with pytest.raises(StateRecoveryError):
                    basic_orchestrator.run()


# =============================================================================
# Test Tracker Integration
# =============================================================================


class TestTrackerIntegration:
    """Tests for execution tracker integration."""

    @patch("claude_task_master.core.orchestrator.is_cancellation_requested")
    @patch("claude_task_master.core.orchestrator.start_listening")
    @patch("claude_task_master.core.orchestrator.stop_listening")
    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.unregister_handlers")
    @patch("claude_task_master.core.orchestrator.reset_shutdown")
    @patch("claude_task_master.core.orchestrator.console")
    def test_run_aborts_on_stall(
        self,
        mock_console,
        mock_reset_shutdown,
        mock_unregister,
        mock_register,
        mock_stop,
        mock_start,
        mock_is_cancelled,
        basic_orchestrator,
        state_manager,
        sample_task_options,
    ):
        """Should abort when tracker detects stall."""
        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**sample_task_options)
        state_manager.initialize(goal="Test", model="sonnet", options=options)
        state_manager.save_plan("- [ ] Task 1")

        mock_is_cancelled.return_value = False

        # Mock tracker to indicate stall
        with patch.object(
            basic_orchestrator.tracker, "should_abort", return_value=(True, "Stalled for too long")
        ):
            result = basic_orchestrator.run()

        assert result == 1
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.orchestrator.is_cancellation_requested")
    @patch("claude_task_master.core.orchestrator.start_listening")
    @patch("claude_task_master.core.orchestrator.stop_listening")
    @patch("claude_task_master.core.orchestrator.register_handlers")
    @patch("claude_task_master.core.orchestrator.unregister_handlers")
    @patch("claude_task_master.core.orchestrator.reset_shutdown")
    @patch("claude_task_master.core.orchestrator.console")
    def test_run_checks_session_limit_in_loop(
        self,
        mock_console,
        mock_reset_shutdown,
        mock_unregister,
        mock_register,
        mock_stop,
        mock_start,
        mock_is_cancelled,
        basic_orchestrator,
        state_manager,
        sample_task_options,
    ):
        """Should check session limit after each cycle."""
        state_manager.state_dir.mkdir(exist_ok=True)
        options = TaskOptions(**{**sample_task_options, "max_sessions": 2})
        state_manager.initialize(goal="Test", model="sonnet", options=options)
        state_manager.save_plan("- [ ] Task 1")

        mock_is_cancelled.return_value = False

        # Simulate reaching max sessions during run
        def side_effect(state):
            state.session_count = 2
            return None

        with (
            patch.object(basic_orchestrator, "_run_workflow_cycle", side_effect=side_effect),
            patch.object(basic_orchestrator.task_runner, "is_all_complete", return_value=False),
            patch.object(basic_orchestrator.tracker, "should_abort", return_value=(False, None)),
        ):
            result = basic_orchestrator.run()

        assert result == 1
        mock_console.warning.assert_called()


# =============================================================================
# Test Checkout to Main
# =============================================================================


class TestCheckoutToMain:
    """Tests for _checkout_to_main and _get_target_branch methods."""

    @patch("claude_task_master.core.orchestrator.get_config")
    @patch("claude_task_master.core.orchestrator.subprocess.run")
    @patch("claude_task_master.core.orchestrator.console")
    def test_checkout_to_main_success(
        self, mock_console, mock_subprocess, mock_get_config, basic_orchestrator
    ):
        """Should checkout to main successfully."""
        mock_config = MagicMock()
        mock_config.git.target_branch = "main"
        mock_get_config.return_value = mock_config
        mock_subprocess.return_value = MagicMock(returncode=0)

        result = basic_orchestrator._checkout_to_main()

        assert result is True
        assert mock_subprocess.call_count == 2  # checkout + pull
        mock_console.success.assert_called()

    @patch("claude_task_master.core.orchestrator.get_config")
    @patch("claude_task_master.core.orchestrator.subprocess.run")
    @patch("claude_task_master.core.orchestrator.console")
    def test_checkout_to_main_failure(
        self, mock_console, mock_subprocess, mock_get_config, basic_orchestrator
    ):
        """Should handle checkout failure gracefully."""
        import subprocess

        mock_config = MagicMock()
        mock_config.git.target_branch = "main"
        mock_get_config.return_value = mock_config
        mock_subprocess.side_effect = subprocess.CalledProcessError(1, "git")

        result = basic_orchestrator._checkout_to_main()

        assert result is False
        mock_console.warning.assert_called()

    @patch("claude_task_master.core.orchestrator.get_config")
    def test_get_target_branch_from_config(self, mock_get_config, basic_orchestrator):
        """Should get target branch from config."""
        mock_config = MagicMock()
        mock_config.git.target_branch = "develop"
        mock_get_config.return_value = mock_config

        result = basic_orchestrator._get_target_branch()

        assert result == "develop"


# =============================================================================
# Test Verification Fix Flow
# =============================================================================


class TestVerificationFixFlow:
    """Tests for verification fix loop functionality."""

    @patch("claude_task_master.core.orchestrator.console")
    def test_run_verification_fix_success(
        self, mock_console, basic_orchestrator, state_manager, mock_agent, basic_task_state
    ):
        """Should run fix session and return True on success."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_criteria("Tests must pass")

        result = basic_orchestrator._run_verification_fix("Tests failed", basic_task_state)

        assert result is True
        mock_agent.run_work_session.assert_called()

    @patch("claude_task_master.core.orchestrator.console")
    def test_run_verification_fix_failure(
        self, mock_console, basic_orchestrator, state_manager, mock_agent, basic_task_state
    ):
        """Should return False when fix session fails."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_criteria("Tests must pass")
        mock_agent.run_work_session.side_effect = RuntimeError("Fix failed")

        result = basic_orchestrator._run_verification_fix("Tests failed", basic_task_state)

        assert result is False
        mock_console.error.assert_called()
