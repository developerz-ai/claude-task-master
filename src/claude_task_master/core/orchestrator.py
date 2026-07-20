"""Work Loop Orchestrator - Main loop driving work sessions until completion."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .agent import AgentWrapper, ModelType  # noqa: F401 — re-exported
from .context_accumulator import ContextAccumulator
from .control_channel import ControlChannel
from .mailbox_processor import MailboxProcessor
from .orchestrator_errors import (
    MaxSessionsReachedError,
    OrchestratorError,
    StateRecoveryError,
)
from .orchestrator_loop import OrchestratorLoop
from .plan_parsing import count_completed_tasks, parse_task_descriptions
from .planner import Planner
from .pr_context import PRContextManager
from .progress_tracker import ExecutionTracker, TrackerConfig
from .state import StateManager, TaskState
from .task_runner import (
    NoPlanFoundError,
    NoTasksFoundError,
    TaskRunner,
    WorkSessionError,
)
from .webhook_emitter import WebhookEmitter
from .workflow_stages import WorkflowStageHandler

if TYPE_CHECKING:
    from ..github import GitHubClient
    from ..mailbox import MailboxStorage, MessageMerger
    from ..webhooks import WebhookClient
    from .logger import TaskLogger
    from .plan_updater import PlanUpdater

logger = logging.getLogger(__name__)

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

        # Lazily initialised component managers
        self._control_channel: ControlChannel | None = None
        self._task_runner: TaskRunner | None = None
        self._stage_handler: WorkflowStageHandler | None = None
        self._pr_context: PRContextManager | None = None
        self._webhook_emitter: WebhookEmitter | None = None
        self._mailbox_storage: MailboxStorage | None = None
        self._message_merger: MessageMerger | None = None
        self._plan_updater: PlanUpdater | None = None
        self._context_accumulator: ContextAccumulator | None = None

    # ------------------------------------------------------------------
    # Lazy properties — component managers
    # ------------------------------------------------------------------

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
    def control_channel(self) -> ControlChannel:
        """Get or lazily initialize the durable cross-process control channel."""
        if self._control_channel is None:
            self._control_channel = ControlChannel(self.state_manager.state_dir)
        return self._control_channel

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
            from ..webhooks import WebhookRegistry

            run_id = None
            try:
                if self.state_manager.exists():
                    state = self.state_manager.load_state()
                    run_id = state.run_id
            except Exception:
                pass
            registry = WebhookRegistry(self.state_manager.state_dir)
            self._webhook_emitter = WebhookEmitter(self._webhook_client, run_id, registry=registry)
        return self._webhook_emitter

    def _drain_webhooks(self) -> None:
        """Flush and stop the background webhook worker before ``run`` returns.

        Accesses the cached emitter directly (not the lazy property) so a run
        that never configured webhooks does not create one just to close it.
        """
        emitter = self._webhook_emitter
        if emitter is not None:
            emitter.close()
            self._webhook_emitter = None

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

    @property
    def context_accumulator(self) -> ContextAccumulator:
        """Get or lazily initialize the context accumulator."""
        if self._context_accumulator is None:
            self._context_accumulator = ContextAccumulator(self.state_manager)
        return self._context_accumulator

    # ------------------------------------------------------------------
    # Task-count helpers (used by the loop and mailbox processor)
    # ------------------------------------------------------------------

    def _get_total_tasks(self, state: TaskState) -> int:
        """Return total task count from the plan.

        Args:
            state: Current task state.

        Returns:
            Total number of tasks, or 0 if the plan cannot be loaded.
        """
        try:
            plan = self.state_manager.load_plan()
            if plan:
                tasks = parse_task_descriptions(plan)
                return len(tasks)
        except Exception:
            pass
        return 0

    def _get_completed_tasks(self, state: TaskState) -> int:
        """Return completed task count from the plan.

        Args:
            state: Current task state.

        Returns:
            Completed tasks, or ``state.current_task_index`` on error.
        """
        try:
            plan = self.state_manager.load_plan()
            if plan:
                return count_completed_tasks(plan)
        except Exception:
            pass
        return state.current_task_index

    # ------------------------------------------------------------------
    # Mailbox delegation
    # ------------------------------------------------------------------

    def _check_and_process_mailbox(self, state: TaskState) -> bool:
        """Check the mailbox and update the plan when messages are present.

        Delegates to :class:`~claude_task_master.core.mailbox_processor.MailboxProcessor`.

        Args:
            state: Current task state.

        Returns:
            True if the plan was updated, False otherwise.
        """
        processor = MailboxProcessor(
            mailbox_storage=self.mailbox_storage,
            message_merger=self.message_merger,
            plan_updater=self.plan_updater,
            webhook_emitter=self.webhook_emitter,
            state_manager=self.state_manager,
        )
        return processor.check_and_process(state)

    # ------------------------------------------------------------------
    # Main entry point — delegates to OrchestratorLoop
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Run the main work loop until completion or blocked.

        Returns:
            0: Success — all tasks completed and verified.
            1: Blocked/Failed — max sessions reached or error.
            2: Paused — user interrupted.
        """
        return OrchestratorLoop(self).run()

    # ------------------------------------------------------------------
    # Delegation stubs — private methods forwarded to OrchestratorLoop.
    # Kept here so existing call-sites (tests, internal callers) that
    # reference ``orchestrator._run_workflow_cycle`` etc. continue to work
    # without changes.
    # ------------------------------------------------------------------

    def _run_workflow_cycle(self, state: TaskState) -> int | None:
        return OrchestratorLoop(self)._run_workflow_cycle(state)

    def _handle_working_stage(self, state: TaskState) -> int | None:
        return OrchestratorLoop(self)._handle_working_stage(state)

    def _attempt_state_recovery(self) -> TaskState | None:
        return OrchestratorLoop(self)._attempt_state_recovery()

    def _verify_success(self, state: TaskState) -> dict[str, object]:
        return OrchestratorLoop(self)._verify_success(state)

    def _accumulate_context(self, state: TaskState) -> None:
        OrchestratorLoop(self)._accumulate_context(state)

    def _build_completed_tasks_summary(self, state: TaskState) -> str:
        return OrchestratorLoop(self)._build_completed_tasks_summary(state)

    def _get_target_branch(self) -> str:
        return OrchestratorLoop(self)._get_target_branch()

    def _checkout_to_main(self) -> bool:
        return OrchestratorLoop(self)._checkout_to_main()

    def _run_verification_fix(self, verification_details: str, state: TaskState) -> bool:
        return OrchestratorLoop(self)._run_verification_fix(verification_details, state)

    def _wait_for_fix_pr_merge(self, state: TaskState) -> bool:
        return OrchestratorLoop(self)._wait_for_fix_pr_merge(state)

    def _fix_pr_ci_failure(self, pr_number: int, state: TaskState) -> bool:
        return OrchestratorLoop(self)._fix_pr_ci_failure(pr_number, state)

    def _poll_fix_pr_ci(self, pr_number: int, state: TaskState) -> str:
        return OrchestratorLoop(self)._poll_fix_pr_ci(pr_number, state)

    def _get_current_branch(self) -> str | None:
        return OrchestratorLoop._get_current_branch()

    def _emit_status_changed(
        self,
        previous_status: str,
        new_status: str,
        state: TaskState,
        reason: str | None = None,
    ) -> None:
        OrchestratorLoop(self)._emit_status_changed(previous_status, new_status, state, reason)

    def _emit_run_completed(
        self,
        state: TaskState,
        exit_code: int,
        result: str,
        run_start_time: float,
        error_message: str | None = None,
    ) -> None:
        OrchestratorLoop(self)._emit_run_completed(
            state, exit_code, result, run_start_time, error_message
        )

    def _emit_pr_created_event(self, state: TaskState) -> None:
        OrchestratorLoop(self)._emit_pr_created_event(state)

    def _emit_pr_merged_event(self, state: TaskState) -> None:
        OrchestratorLoop(self)._emit_pr_merged_event(state)
