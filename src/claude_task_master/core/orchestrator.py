"""Work Loop Orchestrator - Main loop driving work sessions until completion."""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from . import console
from .agent import AgentWrapper, ModelType
from .agent_exceptions import AgentError, ConsecutiveFailuresError, ContentFilterError
from .circuit_breaker import CircuitBreakerError
from .config_loader import get_config
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
from .shutdown import interruptible_sleep, register_handlers, reset_shutdown, unregister_handlers
from .state import StateError, StateManager, TaskState
from .task_runner import (
    NoPlanFoundError,
    NoTasksFoundError,
    TaskRunner,
    WorkSessionError,
)
from .workflow_stages import WorkflowStageHandler

if TYPE_CHECKING:
    from ..github import GitHubClient
    from ..mailbox import MailboxStorage, MessageMerger
    from ..webhooks import WebhookClient
    from ..webhooks.events import EventType
    from .logger import TaskLogger
    from .plan_updater import PlanUpdater

logger = logging.getLogger(__name__)

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
    "WebhookEmitter",
]


# =============================================================================
# Webhook Emitter
# =============================================================================


class WebhookEmitter:
    """Helper class to emit webhook events from the orchestrator.

    Handles webhook emission with error handling and logging. Events are sent
    asynchronously in a fire-and-forget manner - failures don't block the
    orchestrator workflow.

    Attributes:
        client: The webhook client for sending events.
        run_id: The current orchestrator run ID for correlation.
    """

    def __init__(self, client: WebhookClient | None, run_id: str | None = None) -> None:
        """Initialize the webhook emitter.

        Args:
            client: Optional webhook client. If None, all emit calls are no-ops.
            run_id: Optional run ID for event correlation.
        """
        self._client = client
        self._run_id = run_id

    @property
    def enabled(self) -> bool:
        """Check if webhook emission is enabled."""
        return self._client is not None

    def emit(
        self,
        event_type: EventType | str,
        **event_data: Any,
    ) -> None:
        """Emit a webhook event.

        Creates and sends a webhook event. Failures are logged but don't
        raise exceptions to avoid blocking the orchestrator.

        Args:
            event_type: The type of event to emit.
            **event_data: Event-specific data fields.
        """
        if not self._client:
            return

        try:
            # Import here to avoid circular imports
            from ..webhooks.events import create_event

            # Add run_id to all events
            if self._run_id:
                event_data["run_id"] = self._run_id

            # Create the event
            event = create_event(event_type, **event_data)

            # Send synchronously (fire-and-forget)
            result = self._client.send_sync(
                data=event.to_dict(),
                event_type=str(event.event_type),
                delivery_id=event.event_id,
            )

            if result.success:
                logger.debug(
                    "Webhook delivered: %s (delivery_id=%s)",
                    event.event_type,
                    event.event_id,
                )
            else:
                logger.warning(
                    "Webhook delivery failed: %s - %s",
                    event.event_type,
                    result.error,
                )

        except Exception as e:
            # Log but don't raise - webhooks shouldn't block the orchestrator
            logger.warning("Failed to emit webhook event %s: %s", event_type, e)


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
        webhook_client: WebhookClient | None = None,
    ):
        """Initialize orchestrator.

        Args:
            agent: The agent wrapper for running queries.
            state_manager: The state manager for persistence.
            planner: The planner for planning phases.
            github_client: Optional GitHub client for PR operations.
            logger: Optional logger for recording session activity.
            tracker_config: Optional config for execution tracker.
            webhook_client: Optional webhook client for emitting lifecycle events.
        """
        self.agent = agent
        self.state_manager = state_manager
        self.planner = planner
        self._github_client = github_client
        self.logger = logger
        self.tracker = ExecutionTracker(config=tracker_config or TrackerConfig.default())
        self._webhook_client = webhook_client

        # Initialize component managers (lazy)
        self._task_runner: TaskRunner | None = None
        self._stage_handler: WorkflowStageHandler | None = None
        self._pr_context: PRContextManager | None = None
        self._webhook_emitter: WebhookEmitter | None = None
        self._mailbox_storage: MailboxStorage | None = None
        self._message_merger: MessageMerger | None = None
        self._plan_updater: PlanUpdater | None = None

    @property
    def github_client(self) -> GitHubClient:
        """Get or lazily initialize GitHub client."""
        if self._github_client is None:
            try:
                from ..github import GitHubClient

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
                webhook_emitter=self.webhook_emitter,
            )
        return self._stage_handler

    @property
    def webhook_emitter(self) -> WebhookEmitter:
        """Get or lazily initialize webhook emitter."""
        if self._webhook_emitter is None:
            # Initialize with run_id from state if available
            run_id = None
            try:
                if self.state_manager.exists():
                    state = self.state_manager.load_state()
                    run_id = state.run_id
            except Exception:
                pass  # Use None if state can't be loaded
            self._webhook_emitter = WebhookEmitter(self._webhook_client, run_id)
        return self._webhook_emitter

    @property
    def mailbox_storage(self) -> MailboxStorage:
        """Get or lazily initialize mailbox storage."""
        if self._mailbox_storage is None:
            from ..mailbox import MailboxStorage

            self._mailbox_storage = MailboxStorage(self.state_manager.state_dir)
            logger.debug(
                "Mailbox storage initialized: path=%s",
                self._mailbox_storage.storage_path,
            )
        return self._mailbox_storage

    @property
    def message_merger(self) -> MessageMerger:
        """Get or lazily initialize message merger."""
        if self._message_merger is None:
            from ..mailbox import MessageMerger

            self._message_merger = MessageMerger()
        return self._message_merger

    @property
    def plan_updater(self) -> PlanUpdater:
        """Get or lazily initialize plan updater."""
        if self._plan_updater is None:
            from .plan_updater import PlanUpdater

            self._plan_updater = PlanUpdater(
                agent=self.agent,
                state_manager=self.state_manager,
                logger=self.logger,
            )
        return self._plan_updater

    def _get_total_tasks(self, state: TaskState) -> int:
        """Get total number of tasks from the plan.

        Args:
            state: Current task state.

        Returns:
            Total number of tasks, or 0 if plan can't be loaded.
        """
        try:
            plan = self.state_manager.load_plan()
            if plan:
                tasks = self.state_manager._parse_plan_tasks(plan)
                return len(tasks)
        except Exception:
            pass
        return 0

    def _get_completed_tasks(self, state: TaskState) -> int:
        """Get number of completed tasks from the plan.

        Args:
            state: Current task state.

        Returns:
            Number of completed tasks.
        """
        try:
            plan = self.state_manager.load_plan()
            if plan:
                # Count tasks marked as [x]
                import re

                completed = len(re.findall(r"^- \[x\]", plan, re.MULTILINE))
                return completed
        except Exception:
            pass
        return state.current_task_index

    def _get_current_branch(self) -> str | None:
        """Get the current git branch name.

        Returns:
            Current branch name or None if not in a git repo.
        """
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() or None
        except Exception:
            return None

    def _emit_pr_created_event(self, state: TaskState) -> None:
        """Emit a pr.created webhook event.

        Args:
            state: Current task state with PR information.
        """
        if not state.current_pr:
            return

        # Get PR details from GitHub
        pr_url = ""
        pr_title = ""
        base_branch = "main"
        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)
            pr_url = pr_status.pr_url if hasattr(pr_status, "pr_url") else ""
            pr_title = pr_status.pr_title if hasattr(pr_status, "pr_title") else ""
            base_branch = pr_status.base_branch
        except Exception:
            # Use fallback values if PR details can't be fetched
            pass

        current_branch = self._get_current_branch()

        self.webhook_emitter.emit(
            "pr.created",
            pr_number=state.current_pr,
            pr_url=pr_url,
            pr_title=pr_title,
            branch=current_branch or "",
            base_branch=base_branch,
            tasks_included=1,  # Currently one task per PR or group
        )

    def _emit_pr_merged_event(self, state: TaskState) -> None:
        """Emit a pr.merged webhook event.

        Args:
            state: Current task state with PR information.
        """
        if not state.current_pr:
            return

        # Get PR details from GitHub
        pr_url = ""
        pr_title = ""
        base_branch = "main"
        merged_at = None
        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)
            pr_url = pr_status.pr_url if hasattr(pr_status, "pr_url") else ""
            pr_title = pr_status.pr_title if hasattr(pr_status, "pr_title") else ""
            base_branch = pr_status.base_branch
        except Exception:
            pass

        current_branch = self._get_current_branch()

        self.webhook_emitter.emit(
            "pr.merged",
            pr_number=state.current_pr,
            pr_url=pr_url,
            pr_title=pr_title,
            branch=current_branch or "",
            base_branch=base_branch,
            merged_at=merged_at,
            auto_merged=state.options.auto_merge,
        )

    def _check_and_process_mailbox(self, state: TaskState) -> bool:
        """Check mailbox and update plan if messages exist.

        This method is called after each task completion to check for
        messages from other instances or external systems. If messages
        are found, they are merged and used to update the plan.

        The last_mailbox_check timestamp is always updated regardless of
        whether messages were found, to track when the mailbox was last
        monitored.

        Args:
            state: Current task state.

        Returns:
            True if plan was updated, False otherwise.
        """
        logger.debug(
            "Mailbox check starting: task_index=%d, session_count=%d",
            state.current_task_index,
            state.session_count,
        )

        # Check if there are any messages in the mailbox
        message_count = self.mailbox_storage.count()
        if message_count == 0:
            check_time = datetime.now()
            logger.debug(
                "Mailbox check complete: no messages, timestamp=%s",
                check_time.isoformat(),
            )
            # Always update the timestamp to track when mailbox was checked
            state.last_mailbox_check = check_time
            self.state_manager.save_state(state)
            return False

        # Log that we're processing messages
        logger.info(
            "Mailbox check: found %d message(s) to process",
            message_count,
        )
        console.info(f"Found {message_count} message(s) in mailbox - processing...")

        # Get and clear messages atomically
        messages = self.mailbox_storage.get_and_clear()
        if not messages:
            # Race condition - messages were cleared by another process
            logger.warning(
                "Mailbox race condition: messages disappeared between count (%d) and get",
                message_count,
            )
            return False

        # Log details of each message being processed
        for msg in messages:
            logger.info(
                "Mailbox message: id=%s, sender=%s, priority=%s, timestamp=%s, content_length=%d",
                msg.id,
                msg.sender,
                msg.priority.name if hasattr(msg.priority, "name") else msg.priority,
                msg.timestamp.isoformat() if msg.timestamp else "none",
                len(msg.content),
            )

        # Merge messages into a single change request
        logger.debug(
            "Merging %d mailbox messages from senders: %s",
            len(messages),
            [msg.sender for msg in messages],
        )
        try:
            merged_content = self.message_merger.merge(messages)
            logger.info(
                "Mailbox messages merged successfully: total_length=%d, preview=%s...",
                len(merged_content),
                merged_content[:100].replace("\n", " "),
            )
        except ValueError as e:
            logger.error(
                "Failed to merge mailbox messages: error=%s, message_count=%d",
                e,
                len(messages),
            )
            console.warning(f"Failed to merge mailbox messages: {e}")
            return False

        # Update the plan with the merged content
        logger.debug("Starting plan update from mailbox messages")
        try:
            # Capture task count before update for diff calculation
            total_tasks_before = self._get_total_tasks(state)

            console.info("Updating plan based on mailbox messages...")
            result = self.plan_updater.update_plan(merged_content)

            check_time = datetime.now()
            if result.get("changes_made"):
                console.success("Plan updated based on mailbox messages")
                logger.info(
                    "Plan updated from mailbox: changes_made=True, "
                    "message_count=%d, senders=%s, timestamp=%s",
                    len(messages),
                    [msg.sender for msg in messages],
                    check_time.isoformat(),
                )

                # Update state to record the mailbox check
                state.last_mailbox_check = check_time
                self.state_manager.save_state(state)
                logger.debug(
                    "State saved with mailbox check timestamp: %s",
                    check_time.isoformat(),
                )

                # Emit plan.updated webhook event
                # Get task counts for the updated plan
                updated_total_tasks = self._get_total_tasks(state)
                updated_completed_tasks = self._get_completed_tasks(state)

                # Calculate task diff
                task_diff = updated_total_tasks - total_tasks_before
                tasks_added = max(0, task_diff)
                tasks_removed = max(0, -task_diff)

                self.webhook_emitter.emit(
                    "plan.updated",
                    update_source="mailbox",
                    message=merged_content[:500]
                    if merged_content
                    else None,  # Truncate long messages
                    total_tasks=updated_total_tasks,
                    completed_tasks=updated_completed_tasks,
                    tasks_added=tasks_added,
                    tasks_modified=None,  # TODO: Calculate from plan diff (requires content comparison)
                    tasks_removed=tasks_removed,
                )

                return True
            else:
                console.info("Mailbox messages processed - no plan changes needed")
                logger.info(
                    "Plan not modified from mailbox: message_count=%d, senders=%s, timestamp=%s",
                    len(messages),
                    [msg.sender for msg in messages],
                    check_time.isoformat(),
                )

                # Still record that we checked
                state.last_mailbox_check = check_time
                self.state_manager.save_state(state)
                logger.debug(
                    "State saved with mailbox check timestamp: %s",
                    check_time.isoformat(),
                )

                # Emit plan.updated with no changes (still useful for tracking)
                current_total_tasks = self._get_total_tasks(state)
                current_completed_tasks = self._get_completed_tasks(state)

                self.webhook_emitter.emit(
                    "plan.updated",
                    update_source="mailbox",
                    message=merged_content[:500] if merged_content else None,  # Truncate
                    total_tasks=current_total_tasks,
                    completed_tasks=current_completed_tasks,
                    tasks_added=0,
                    tasks_modified=0,
                    tasks_removed=0,
                )

                return False

        except ValueError as e:
            # No plan exists - can't update
            logger.error(
                "Cannot update plan from mailbox: no plan exists, error=%s, message_count=%d",
                e,
                len(messages),
            )
            console.warning(f"Cannot update plan: {e}")
            return False
        except Exception as e:
            # Other errors during plan update
            logger.error(
                "Error updating plan from mailbox: error=%s, type=%s, message_count=%d",
                e,
                type(e).__name__,
                len(messages),
            )
            console.warning(f"Error updating plan from mailbox: {e}")
            return False

    def _emit_status_changed(
        self,
        previous_status: str,
        new_status: str,
        state: TaskState,
        reason: str | None = None,
    ) -> None:
        """Emit a status.changed webhook event when status transitions.

        Args:
            previous_status: The status before the change.
            new_status: The status after the change.
            state: Current task state.
            reason: Optional reason for the status change.
        """
        # Only emit if status actually changed
        if previous_status == new_status:
            return

        self.webhook_emitter.emit(
            "status.changed",
            previous_status=previous_status,
            new_status=new_status,
            reason=reason,
            task_index=state.current_task_index,
            session_number=state.session_count,
        )

    def _emit_run_completed(
        self,
        state: TaskState,
        exit_code: int,
        result: str,
        run_start_time: float,
        error_message: str | None = None,
    ) -> None:
        """Emit a run.completed webhook event.

        Args:
            state: Current task state.
            exit_code: Exit code (0=success, 1=blocked, 2=interrupted).
            result: Outcome string ("success", "blocked", "failed", "interrupted").
            run_start_time: Time when the run started (time.time() value).
            error_message: Error message if run failed (optional).
        """
        # Get goal from state manager
        goal = ""
        try:
            goal = self.state_manager.load_goal()
        except Exception:
            pass

        # Get task counts
        total_tasks = self._get_total_tasks(state)
        completed_tasks = self._get_completed_tasks(state)

        # Calculate duration
        duration_seconds = time.time() - run_start_time if run_start_time > 0 else None

        self.webhook_emitter.emit(
            "run.completed",
            goal=goal,
            result=result,
            exit_code=exit_code,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            total_sessions=state.session_count,
            duration_seconds=duration_seconds,
            prs_created=0,  # TODO: Track PR counts in state
            prs_merged=0,  # TODO: Track PR counts in state
            final_status=state.status,
            error_message=error_message,
        )

    def run(self) -> int:
        """Run the main work loop until completion or blocked.

        Returns:
            0: Success - all tasks completed and verified.
            1: Blocked/Failed - max sessions reached or error.
            2: Paused - user interrupted.
        """
        # Track run start time for duration calculation
        run_start_time = time.time()

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
            self._emit_run_completed(state, 1, "blocked", run_start_time, "Max sessions reached")
            return 1

        # Emit run.started webhook event
        # Determine if this is a resumed run (session_count > 0 means we've run before)
        is_resumed = state.session_count > 0
        pr_mode = "per-task" if state.options.pr_per_task else "per-group"

        # Load goal from state manager (stored in goal.txt)
        goal = ""
        try:
            goal = self.state_manager.load_goal()
        except Exception:
            pass  # Goal is optional for webhook

        # Get working directory (parent of state_dir which is .claude-task-master/)
        working_directory = str(self.state_manager.state_dir.parent)

        self.webhook_emitter.emit(
            "run.started",
            goal=goal,
            working_directory=working_directory,
            max_sessions=state.options.max_sessions,
            auto_merge=state.options.auto_merge,
            pr_mode=pr_mode,
            resumed=is_resumed,
        )

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
            previous_status = state.status
            state.status = "paused"
            self._emit_status_changed(previous_status, "paused", state, reason)
            self.state_manager.save_state(state)
            self.state_manager.create_state_backup()
            console.newline()
            console.info(self.tracker.get_cost_report())
            console.info("Use 'claudetm resume' to continue")
            self._emit_run_completed(state, 2, "interrupted", run_start_time, reason)
            return 2

        try:
            console.detail(
                f"Checking completion: task_index={state.current_task_index}, "
                f"is_all_complete={self.task_runner.is_all_complete(state)}"
            )
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
                    previous_status = state.status
                    state.status = "blocked"
                    self._emit_status_changed(previous_status, "blocked", state, abort_reason)
                    self.state_manager.save_state(state)
                    stop_listening()
                    unregister_handlers()
                    console.info(self.tracker.get_cost_report())
                    self._emit_run_completed(state, 1, "blocked", run_start_time, abort_reason)
                    return 1

                # Run workflow cycle
                result = self._run_workflow_cycle(state)
                if result is not None:
                    stop_listening()
                    unregister_handlers()
                    console.info(self.tracker.get_cost_report())
                    # Determine result string based on exit code
                    result_str = "success" if result == 0 else "blocked"
                    self._emit_run_completed(state, result, result_str, run_start_time)
                    return result

                # Debug: check completion after each cycle
                console.detail(
                    f"After cycle: task_index={state.current_task_index}, "
                    f"stage={state.workflow_stage}, "
                    f"is_all_complete={self.task_runner.is_all_complete(state)}"
                )

                # Check session limit
                if state.options.max_sessions and state.session_count >= state.options.max_sessions:
                    console.warning(f"Max sessions ({state.options.max_sessions}) reached")
                    previous_status = state.status
                    state.status = "blocked"
                    self._emit_status_changed(
                        previous_status, "blocked", state, "Max sessions reached"
                    )
                    self.state_manager.save_state(state)
                    stop_listening()
                    unregister_handlers()
                    console.info(self.tracker.get_cost_report())
                    self._emit_run_completed(
                        state, 1, "blocked", run_start_time, "Max sessions reached"
                    )
                    return 1

            # All complete - verify with retry loop for fixes
            stop_listening()
            unregister_handlers()

            # Allow up to 3 fix attempts
            max_fix_attempts = 3
            fix_attempt = 0

            while fix_attempt <= max_fix_attempts:
                verification = self._verify_success()

                if verification["success"]:
                    # Success! Checkout to main and cleanup
                    self._checkout_to_main()
                    previous_status = state.status
                    state.status = "success"
                    self._emit_status_changed(
                        previous_status, "success", state, "All tasks completed successfully"
                    )
                    self.state_manager.save_state(state)
                    self.state_manager.cleanup_on_success(state.run_id)
                    console.success("All tasks completed successfully!")
                    console.info(self.tracker.get_cost_report())
                    self._emit_run_completed(state, 0, "success", run_start_time)
                    return 0

                # Verification failed
                console.warning("Success criteria verification failed")

                if fix_attempt >= max_fix_attempts:
                    # Max attempts reached - stay on branch for easier resume
                    console.error(f"Max fix attempts ({max_fix_attempts}) reached")
                    previous_status = state.status
                    state.status = "blocked"
                    self._emit_status_changed(
                        previous_status, "blocked", state, "Max fix attempts reached"
                    )
                    self.state_manager.save_state(state)
                    console.info(self.tracker.get_cost_report())
                    self._emit_run_completed(
                        state, 1, "blocked", run_start_time, "Max fix attempts reached"
                    )
                    return 1

                # Attempt to fix
                console.info(f"Attempting fix {fix_attempt + 1}/{max_fix_attempts}...")

                if not self._run_verification_fix(verification["details"], state):
                    # Fix failed - stay on branch for easier resume
                    console.error("Fix attempt failed")
                    previous_status = state.status
                    state.status = "blocked"
                    self._emit_status_changed(
                        previous_status, "blocked", state, "Verification fix failed"
                    )
                    self.state_manager.save_state(state)
                    console.info(self.tracker.get_cost_report())
                    self._emit_run_completed(
                        state, 1, "failed", run_start_time, "Verification fix failed"
                    )
                    return 1

                # Wait for PR to be created and merge it
                if not self._wait_for_fix_pr_merge(state):
                    # PR merge failed - stay on branch for easier resume
                    console.error("Fix PR merge failed")
                    previous_status = state.status
                    state.status = "blocked"
                    self._emit_status_changed(
                        previous_status, "blocked", state, "Fix PR merge failed"
                    )
                    self.state_manager.save_state(state)
                    console.info(self.tracker.get_cost_report())
                    self._emit_run_completed(
                        state, 1, "blocked", run_start_time, "Fix PR merge failed"
                    )
                    return 1

                # PR merged - increment and retry verification
                fix_attempt += 1
                console.info("Fix PR merged - re-verifying...")

            # Should not reach here, but handle it gracefully
            # Stay on branch for easier resume
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(
                previous_status, "blocked", state, "Unexpected exit from verification loop"
            )
            self.state_manager.save_state(state)
            console.info(self.tracker.get_cost_report())
            self._emit_run_completed(
                state, 1, "blocked", run_start_time, "Unexpected exit from verification loop"
            )
            return 1

        except KeyboardInterrupt:
            return _handle_pause("Interrupted (Ctrl+C)")
        except OrchestratorError as e:
            stop_listening()
            unregister_handlers()
            console.error(f"Orchestrator error: {e.message}")
            previous_status = state.status
            state.status = "failed"
            self._emit_status_changed(previous_status, "failed", state, e.message)
            try:
                # Don't checkout to main on error - stay on branch for easier resume
                self.state_manager.save_state(state)
            except Exception:
                pass  # Best effort - state save failed but we still return error
            self._emit_run_completed(state, 1, "failed", run_start_time, e.message)
            return 1
        except Exception as e:
            stop_listening()
            unregister_handlers()
            console.error(f"Unexpected error: {type(e).__name__}: {e}")
            previous_status = state.status
            state.status = "failed"
            error_message = f"{type(e).__name__}: {e}"
            self._emit_status_changed(previous_status, "failed", state, error_message)
            try:
                # Don't checkout to main on error - stay on branch for easier resume
                self.state_manager.save_state(state)
            except Exception:
                pass  # Best effort - state save failed but we still return error
            self._emit_run_completed(state, 1, "failed", run_start_time, error_message)
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
                # Track PR number before stage handler runs
                pr_before = state.current_pr
                result = self.stage_handler.handle_pr_created_stage(state)
                # Emit pr.created webhook if PR was detected
                if state.current_pr and state.current_pr != pr_before:
                    self._emit_pr_created_event(state)
                return result
            elif stage == "waiting_ci":
                return self.stage_handler.handle_waiting_ci_stage(state)
            elif stage == "ci_failed":
                return self.stage_handler.handle_ci_failed_stage(state)
            elif stage == "waiting_reviews":
                return self.stage_handler.handle_waiting_reviews_stage(state)
            elif stage == "addressing_reviews":
                return self.stage_handler.handle_addressing_reviews_stage(state)
            elif stage == "ready_to_merge":
                # Track stage before handler runs
                stage_before = state.workflow_stage
                result = self.stage_handler.handle_ready_to_merge_stage(state)
                # Emit pr.merged webhook if PR was merged (stage changed to "merged")
                if state.workflow_stage == "merged" and stage_before == "ready_to_merge":
                    self._emit_pr_merged_event(state)
                return result
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
            previous_status = state.status
            state.status = "failed"
            self._emit_status_changed(previous_status, "failed", state, e.message)
            self.state_manager.save_state(state)
            return 1
        except NoTasksFoundError:
            return None  # Continue to completion check
        except ContentFilterError as e:
            console.error(f"Content filter: {e.message}")
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(
                previous_status, "blocked", state, f"Content filter: {e.message}"
            )
            self.state_manager.save_state(state)
            return 1
        except CircuitBreakerError as e:
            console.warning(f"Circuit breaker: {e.message}")
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(
                previous_status, "blocked", state, f"Circuit breaker: {e.message}"
            )
            self.state_manager.save_state(state)
            return 1
        except ConsecutiveFailuresError as e:
            console.error(f"Consecutive failures: {e.message}")
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(
                previous_status, "blocked", state, f"Consecutive failures: {e.message}"
            )
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
        total_tasks = self._get_total_tasks(state)
        current_branch = self._get_current_branch()
        session_start_time = time.time()

        self.tracker.start_session(
            session_id=state.session_count + 1,
            task_index=state.current_task_index,
            task_description=task_desc,
        )

        if self.logger:
            self.logger.start_session(state.session_count + 1, "working")

        # Emit session.started webhook event
        self.webhook_emitter.emit(
            "session.started",
            session_number=state.session_count + 1,
            max_sessions=state.options.max_sessions,
            task_index=state.current_task_index,
            task_description=task_desc,
            phase="working",
        )

        # Emit task.started webhook event
        self.webhook_emitter.emit(
            "task.started",
            task_index=state.current_task_index,
            task_description=task_desc,
            total_tasks=total_tasks,
            branch=current_branch,
        )

        outcome = "completed"
        error_message = None
        error_type = None
        try:
            self.task_runner.run_work_session(state)
        except Exception as e:
            outcome = "failed"
            error_message = str(e)
            error_type = type(e).__name__
            self.tracker.record_error()
            raise
        finally:
            session_duration = time.time() - session_start_time
            self.tracker.end_session(outcome=outcome)
            if self.logger:
                self.logger.end_session(outcome)

            # Emit session.completed webhook event
            self.webhook_emitter.emit(
                "session.completed",
                session_number=state.session_count + 1,
                max_sessions=state.options.max_sessions,
                task_index=state.current_task_index,
                task_description=task_desc,
                phase="working",
                duration_seconds=session_duration,
                result=outcome,
            )

            # Emit task.failed if task failed
            if outcome == "failed":
                self.webhook_emitter.emit(
                    "task.failed",
                    task_index=state.current_task_index,
                    task_description=task_desc,
                    error_message=error_message or "Unknown error",
                    error_type=error_type,
                    duration_seconds=session_duration,
                    branch=current_branch,
                    recoverable=True,
                )

        self.tracker.record_task_progress(state.current_task_index)
        reset_escape()

        state.session_count += 1

        # Mark current task as complete in plan.md
        # This is done by the orchestrator (not the agent) for reliability
        completed_task_index = state.current_task_index
        plan = self.state_manager.load_plan()
        if plan:
            self.task_runner.mark_task_complete(plan, completed_task_index)
            console.success(f"Task #{completed_task_index + 1} marked complete in plan.md")

        # Emit task.completed webhook event
        completed_tasks = self._get_completed_tasks(state) + 1  # +1 for task we just completed
        self.webhook_emitter.emit(
            "task.completed",
            task_index=state.current_task_index,
            task_description=task_desc,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            duration_seconds=time.time() - session_start_time,
            branch=current_branch,
        )

        # Check mailbox for any messages after task completion
        # If messages exist, merge them and update the plan
        logger.debug(
            "Checking mailbox after task %d completion",
            state.current_task_index,
        )
        plan_updated = self._check_and_process_mailbox(state)
        if plan_updated:
            # Plan was updated - need to refresh total_tasks count
            # The task list may have changed
            old_total = total_tasks
            total_tasks = self._get_total_tasks(state)
            logger.info(
                "Plan updated from mailbox: old_total_tasks=%d, new_total_tasks=%d",
                old_total,
                total_tasks,
            )
            console.detail(f"Plan updated - new total tasks: {total_tasks}")

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

        # Update progress.md AFTER incrementing task index
        # So the arrow → points to the NEXT task, not the one we just completed
        self.task_runner.update_progress(state)

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

    def _verify_success(self) -> dict:
        """Verify success criteria are met.

        Returns:
            Dict with 'success' (bool) and 'details' (str) keys.
        """
        criteria = self.state_manager.load_criteria()
        if not criteria:
            return {"success": True, "details": "No criteria specified"}

        context = self.state_manager.load_context()
        result = self.agent.verify_success_criteria(criteria=criteria, context=context)
        return {
            "success": bool(result.get("success", False)),
            "details": result.get("details", ""),
        }

    def _get_target_branch(self) -> str:
        """Get the target branch from configuration."""
        config = get_config()
        return config.git.target_branch

    def _checkout_to_main(self) -> bool:
        """Checkout to the configured target branch (main/master/etc).

        Returns:
            True if checkout succeeded, False otherwise.
        """
        target_branch = self._get_target_branch()
        console.info(f"Checking out to {target_branch}...")

        try:
            # Checkout to target branch
            subprocess.run(
                ["git", "checkout", target_branch],
                check=True,
                capture_output=True,
                text=True,
            )
            # Pull latest changes
            subprocess.run(
                ["git", "pull"],
                check=True,
                capture_output=True,
                text=True,
            )
            console.success(f"Switched to {target_branch}")
            return True
        except subprocess.CalledProcessError as e:
            console.warning(f"Failed to checkout to {target_branch}: {e}")
            return False

    def _run_verification_fix(self, verification_details: str, state: TaskState) -> bool:
        """Run agent to fix verification failures and create a PR.

        Args:
            verification_details: Details of what failed during verification.
            state: Current task state.

        Returns:
            True if fix was attempted (PR created or at least committed).
        """
        console.info("Running agent to fix verification failures...")

        # Build fix prompt
        criteria = self.state_manager.load_criteria() or ""
        context = self.state_manager.load_context()

        task_description = f"""Verification of success criteria has FAILED.

**Success Criteria:**
{criteria}

**Verification Result:**
{verification_details}

**Your Task:**
1. Read the verification details carefully to understand what failed
2. Fix all issues identified in the verification
3. Run tests/lint locally to verify the fixes work
4. Commit your changes with a descriptive message
5. Push to a new branch and create a PR

IMPORTANT: You must fix ALL verification failures, not just some of them.
After fixing everything, run the tests again to confirm they pass.

After completing your fixes, end with: TASK COMPLETE"""

        try:
            self.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=ModelType.OPUS,
                create_pr=True,
            )
            state.session_count += 1
            self.state_manager.save_state(state)
            return True
        except Exception as e:
            console.error(f"Fix session failed: {e}")
            return False

    def _wait_for_fix_pr_merge(self, state: TaskState) -> bool:
        """Wait for fix PR to pass CI and merge it.

        Args:
            state: Current task state.

        Returns:
            True if PR was merged successfully.
        """
        # Detect PR from current branch
        try:
            pr_number = self.github_client.get_pr_for_current_branch()
            if not pr_number:
                console.warning("No PR found for fix branch")
                return False

            console.success(f"Fix PR #{pr_number} detected")
            state.current_pr = pr_number
            self.state_manager.save_state(state)
        except Exception as e:
            console.warning(f"Could not detect fix PR: {e}")
            return False

        # Poll CI until success or failure
        max_wait = 600  # 10 minutes max
        poll_interval = 10
        waited = 0

        while waited < max_wait:
            try:
                pr_status = self.github_client.get_pr_status(pr_number)

                if pr_status.ci_state == "SUCCESS":
                    console.success("Fix PR CI passed!")
                    break
                elif pr_status.ci_state in ("FAILURE", "ERROR"):
                    console.error("Fix PR CI failed - cannot auto-merge")
                    return False
                else:
                    console.info(f"Waiting for fix PR CI... ({pr_status.checks_pending} pending)")
                    if not interruptible_sleep(poll_interval):
                        return False
                    waited += poll_interval
            except Exception as e:
                console.warning(f"Error checking CI: {e}")
                if not interruptible_sleep(poll_interval):
                    return False
                waited += poll_interval

        if waited >= max_wait:
            console.warning("Timed out waiting for fix PR CI")
            return False

        # Merge the PR
        if state.options.auto_merge:
            try:
                console.info(f"Merging fix PR #{pr_number}...")
                self.github_client.merge_pr(pr_number)
                console.success(f"Fix PR #{pr_number} merged!")

                # Checkout back to target branch
                self._checkout_to_main()

                return True
            except Exception as e:
                console.error(f"Failed to merge fix PR: {e}")
                return False
        else:
            console.info(f"Fix PR #{pr_number} ready to merge (auto_merge disabled)")
            console.detail("Merge manually then run 'claudetm resume'")
            return False
