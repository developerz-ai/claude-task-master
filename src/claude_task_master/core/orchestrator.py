"""Work Loop Orchestrator - Main loop driving work sessions until completion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import console
from .agent import AgentWrapper
from .agent_exceptions import AgentError, ContentFilterError
from .circuit_breaker import CircuitBreakerError
from .key_listener import (
    get_cancellation_reason,
    is_cancellation_requested,
    reset_escape,
    start_listening,
    stop_listening,
)
from .planner import Planner
from .pr_context import PRContextManager
from .progress_tracker import ExecutionTracker, TrackerConfig
from .shutdown import register_handlers, reset_shutdown, unregister_handlers
from .state import StateError, StateManager, TaskState
from .task_runner import (
    NoPlanFoundError,
    NoTasksFoundError,
    TaskRunner,
    WorkSessionError,
)
from .workflow_stages import WorkflowStageHandler

if TYPE_CHECKING:
    from ..github.client import GitHubClient
    from .logger import TaskLogger

# =============================================================================
# Custom Exception Classes
# =============================================================================


class OrchestratorError(Exception):
    """Base exception for all orchestrator-related errors."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class StateRecoveryError(OrchestratorError):
    """Raised when state recovery fails."""

    def __init__(self, reason: str, original_error: Exception | None = None):
        self.original_error = original_error
        details = f"Reason: {reason}"
        if original_error:
            details += f" | Original error: {type(original_error).__name__}: {original_error}"
        super().__init__("Failed to recover orchestrator state", details)


class MaxSessionsReachedError(OrchestratorError):
    """Raised when max sessions limit is reached."""

    def __init__(self, max_sessions: int, current_session: int):
        self.max_sessions = max_sessions
        self.current_session = current_session
        super().__init__(
            f"Max sessions ({max_sessions}) reached",
            f"Currently at session {current_session}. Consider increasing max_sessions.",
        )


# Re-export for backwards compatibility
__all__ = [
    "WorkLoopOrchestrator",
    "OrchestratorError",
    "StateRecoveryError",
    "MaxSessionsReachedError",
    "NoPlanFoundError",
    "NoTasksFoundError",
    "WorkSessionError",
]


class WorkLoopOrchestrator:
    """Orchestrates the main work loop with full PR workflow support.

    Workflow: plan → work → PR → CI → reviews → fix → merge → next → success

    Supports conversation mode where tasks in the same PR share a conversation,
    allowing Claude to remember context from previous tasks in the same PR.
    """

    def __init__(
        self,
        agent: AgentWrapper,
        state_manager: StateManager,
        planner: Planner,
        github_client: GitHubClient | None = None,
        logger: TaskLogger | None = None,
        tracker_config: TrackerConfig | None = None,
    ):
        """Initialize orchestrator.

        Args:
            agent: The agent wrapper for running queries.
            state_manager: The state manager for persistence.
            planner: The planner for planning phases.
            github_client: Optional GitHub client for PR operations.
            logger: Optional logger for recording session activity.
            tracker_config: Optional config for execution tracker.
        """
        self.agent = agent
        self.state_manager = state_manager
        self.planner = planner
        self._github_client = github_client
        self.logger = logger
        self.tracker = ExecutionTracker(config=tracker_config or TrackerConfig.default())

        # Initialize component managers (lazy)
        self._task_runner: TaskRunner | None = None
        self._stage_handler: WorkflowStageHandler | None = None
        self._pr_context: PRContextManager | None = None

    @property
    def github_client(self) -> GitHubClient:
        """Get or lazily initialize GitHub client."""
        if self._github_client is None:
            try:
                from ..github.client import GitHubClient

                self._github_client = GitHubClient()
            except Exception as e:
                raise OrchestratorError(
                    "GitHub client not available",
                    f"Install gh CLI and run 'gh auth login': {e}",
                ) from e
        return self._github_client

    @property
    def task_runner(self) -> TaskRunner:
        """Get or lazily initialize task runner."""
        if self._task_runner is None:
            self._task_runner = TaskRunner(
                agent=self.agent,
                state_manager=self.state_manager,
                logger=self.logger,
            )
        return self._task_runner

    @property
    def pr_context(self) -> PRContextManager:
        """Get or lazily initialize PR context manager."""
        if self._pr_context is None:
            self._pr_context = PRContextManager(
                state_manager=self.state_manager,
                github_client=self.github_client,
            )
        return self._pr_context

    @property
    def stage_handler(self) -> WorkflowStageHandler:
        """Get or lazily initialize stage handler."""
        if self._stage_handler is None:
            self._stage_handler = WorkflowStageHandler(
                agent=self.agent,
                state_manager=self.state_manager,
                github_client=self.github_client,
                pr_context=self.pr_context,
            )
        return self._stage_handler

    def run(self) -> int:
        """Run the main work loop until completion or blocked.

        Returns:
            0: Success - all tasks completed and verified.
            1: Blocked/Failed - max sessions reached or error.
            2: Paused - user interrupted.
        """
        # Load state with recovery
        try:
            state = self.state_manager.load_state()
        except StateError as e:
            console.warning(f"State loading error: {e.message}")
            recovered = self._attempt_state_recovery()
            if recovered:
                console.success("State recovered from backup")
                state = recovered
            else:
                raise StateRecoveryError("State file corrupted", e) from e

        # Check max sessions
        if state.options.max_sessions and state.session_count >= state.options.max_sessions:
            console.warning(
                MaxSessionsReachedError(state.options.max_sessions, state.session_count).message
            )
            return 1

        # Setup signal handlers and key listener
        register_handlers()
        reset_shutdown()
        start_listening()
        console.detail("Press [Escape] to pause, [Ctrl+C] to interrupt")

        def _handle_pause(reason: str) -> int:
            stop_listening()
            unregister_handlers()
            console.newline()
            console.warning(f"{reason} - pausing...")
            self.tracker.end_session(outcome="cancelled")
            state.status = "paused"
            self.state_manager.save_state(state)
            self.state_manager.create_state_backup()
            console.newline()
            console.info(self.tracker.get_cost_report())
            console.info("Use 'claudetm resume' to continue")
            return 2

        try:
            while not self.task_runner.is_all_complete(state):
                # Check cancellation
                if is_cancellation_requested():
                    reason = get_cancellation_reason() or "Cancellation requested"
                    if reason == "escape":
                        reason = "Escape pressed"
                    return _handle_pause(reason)

                # Check for stalls
                should_abort, abort_reason = self.tracker.should_abort()
                if should_abort:
                    console.warning(f"Execution issue: {abort_reason}")
                    state.status = "blocked"
                    self.state_manager.save_state(state)
                    stop_listening()
                    unregister_handlers()
                    console.info(self.tracker.get_cost_report())
                    return 1

                # Run workflow cycle
                result = self._run_workflow_cycle(state)
                if result is not None:
                    stop_listening()
                    unregister_handlers()
                    console.info(self.tracker.get_cost_report())
                    return result

                # Check session limit
                if state.options.max_sessions and state.session_count >= state.options.max_sessions:
                    console.warning(f"Max sessions ({state.options.max_sessions}) reached")
                    state.status = "blocked"
                    self.state_manager.save_state(state)
                    stop_listening()
                    unregister_handlers()
                    console.info(self.tracker.get_cost_report())
                    return 1

            # All complete - verify
            stop_listening()
            unregister_handlers()

            if self._verify_success():
                state.status = "success"
                self.state_manager.save_state(state)
                self.state_manager.cleanup_on_success(state.run_id)
                console.success("All tasks completed successfully!")
                console.info(self.tracker.get_cost_report())
                return 0
            else:
                console.warning("Success criteria verification failed")
                state.status = "blocked"
                self.state_manager.save_state(state)
                console.info(self.tracker.get_cost_report())
                return 1

        except KeyboardInterrupt:
            return _handle_pause("Interrupted (Ctrl+C)")
        except OrchestratorError as e:
            stop_listening()
            unregister_handlers()
            console.error(f"Orchestrator error: {e.message}")
            state.status = "failed"
            try:
                self.state_manager.save_state(state)
            except Exception:
                pass  # Best effort - state save failed but we still return error
            return 1
        except Exception as e:
            stop_listening()
            unregister_handlers()
            console.error(f"Unexpected error: {type(e).__name__}: {e}")
            state.status = "failed"
            try:
                self.state_manager.save_state(state)
            except Exception:
                pass  # Best effort - state save failed but we still return error
            return 1

    def _run_workflow_cycle(self, state: TaskState) -> int | None:
        """Run one cycle of the PR workflow."""
        if state.workflow_stage is None:
            state.workflow_stage = "working"
            self.state_manager.save_state(state)

        stage = state.workflow_stage

        try:
            if stage == "working":
                return self._handle_working_stage(state)
            elif stage == "pr_created":
                return self.stage_handler.handle_pr_created_stage(state)
            elif stage == "waiting_ci":
                return self.stage_handler.handle_waiting_ci_stage(state)
            elif stage == "ci_failed":
                return self.stage_handler.handle_ci_failed_stage(state)
            elif stage == "waiting_reviews":
                return self.stage_handler.handle_waiting_reviews_stage(state)
            elif stage == "addressing_reviews":
                return self.stage_handler.handle_addressing_reviews_stage(state)
            elif stage == "ready_to_merge":
                return self.stage_handler.handle_ready_to_merge_stage(state)
            elif stage == "merged":
                return self.stage_handler.handle_merged_stage(
                    state, self.task_runner.mark_task_complete
                )
            else:
                console.warning(f"Unknown stage: {stage}, resetting")
                state.workflow_stage = "working"
                self.state_manager.save_state(state)
                return None

        except NoPlanFoundError as e:
            console.error(e.message)
            state.status = "failed"
            self.state_manager.save_state(state)
            return 1
        except NoTasksFoundError:
            return None  # Continue to completion check
        except ContentFilterError as e:
            console.error(f"Content filter: {e.message}")
            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1
        except CircuitBreakerError as e:
            console.warning(f"Circuit breaker: {e.message}")
            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1
        except AgentError as e:
            console.error(f"Agent error: {e.message}")
            raise WorkSessionError(
                state.current_task_index,
                self.task_runner.get_current_task_description(state),
                e,
            ) from e

    def _handle_working_stage(self, state: TaskState) -> int | None:
        """Handle the working stage - implement the current task."""
        task_desc = self.task_runner.get_current_task_description(state)

        self.tracker.start_session(
            session_id=state.session_count + 1,
            task_index=state.current_task_index,
            task_description=task_desc,
        )

        if self.logger:
            self.logger.start_session(state.session_count + 1, "working")

        outcome = "completed"
        try:
            self.task_runner.run_work_session(state)
        except Exception:
            outcome = "failed"
            self.tracker.record_error()
            raise
        finally:
            self.tracker.end_session(outcome=outcome)
            if self.logger:
                self.logger.end_session(outcome)

        self.tracker.record_task_progress(state.current_task_index)
        reset_escape()

        state.session_count += 1

        # Determine if we should trigger PR workflow or continue to next task
        # Two modes: pr_per_task=True (one PR per task) or grouped mode (one PR per group)
        if state.options.pr_per_task:
            # Task mode: always create PR after each task
            state.workflow_stage = "pr_created"
        else:
            # Grouped mode (default): only create PR after last task in group
            if self.task_runner.is_last_task_in_group(state):
                state.workflow_stage = "pr_created"
            else:
                # More tasks in this PR group - skip PR workflow, move to next task
                console.info("More tasks in PR group - continuing without creating PR")
                state.current_task_index += 1
                state.workflow_stage = "working"

        self.state_manager.save_state(state)
        return None

    def _attempt_state_recovery(self) -> TaskState | None:
        """Attempt to recover state from backup."""
        try:
            backup_dir = self.state_manager.backup_dir
            if not backup_dir.exists():
                return None

            import json

            backups = sorted(
                backup_dir.glob("state.*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            for backup_file in backups:
                try:
                    with open(backup_file) as f:
                        data = json.load(f)
                    return TaskState(**data)
                except Exception:
                    continue

            return None
        except Exception:
            return None

    def _verify_success(self) -> bool:
        """Verify success criteria are met."""
        criteria = self.state_manager.load_criteria()
        if not criteria:
            return True

        context = self.state_manager.load_context()
        result = self.agent.verify_success_criteria(criteria=criteria, context=context)
        return bool(result.get("success", False))
