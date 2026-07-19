"""Work Loop Orchestrator - Main loop driving work sessions until completion."""

from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from . import console
from .agent import AgentWrapper, ModelType
from .agent_exceptions import AgentError, ConsecutiveFailuresError, ContentFilterError
from .circuit_breaker import CircuitBreakerError
from .config_loader import get_config
from .context_accumulator import ContextAccumulator
from .control_channel import ControlChannel
from .key_listener import (
    get_cancellation_reason,
    is_cancellation_requested,
    reset_escape,
    start_listening,
    stop_listening,
)
from .plan_parsing import count_completed_tasks, is_task_complete, parse_task_descriptions
from .planner import Planner
from .pr_context import PRContextManager
from .progress_tracker import ExecutionTracker, TrackerConfig
from .shutdown import (
    interruptible_sleep,
    register_handlers,
    reset_shutdown,
    set_durable_stop_check,
    unregister_handlers,
)
from .state import StateError, StateManager, StateValidationError, TaskState
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
    from ..webhooks import WebhookClient, WebhookRegistry
    from ..webhooks.config import WebhookConfig
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


@dataclass(frozen=True)
class _DeliveryJob:
    """A single prepared webhook delivery handed to the background worker.

    Attributes:
        client: The webhook client to deliver through.
        payload: The event payload, already serialised to a dict.
        event_name: The event type string for the delivery header.
        delivery_id: The unique delivery id for correlation.
        webhook_id: Optional registry id, included in logs for traceability.
    """

    client: WebhookClient
    payload: dict[str, Any]
    event_name: str
    delivery_id: str
    webhook_id: str | None = None


@dataclass(frozen=True)
class _FlushMarker:
    """A barrier enqueued by :meth:`WebhookEmitter.flush`.

    The worker sets ``event`` once it reaches this marker, meaning every
    delivery enqueued before it has been processed.
    """

    event: threading.Event


class WebhookEmitter:
    """Helper class to emit webhook events from the orchestrator.

    Fans each lifecycle event out to two destinations:

    * the optional single ``--webhook-url`` client (unfiltered — it receives
      every event), and
    * every webhook registered through the REST API via the shared
      :class:`~claude_task_master.webhooks.registry.WebhookRegistry`, filtered by
      each webhook's event subscription (:meth:`WebhookConfig.should_send_event`).

    Before the registry was wired in, registered webhooks never received any
    events — the orchestrator only knew about the CLI ``--webhook-url``. Delivery
    failures are logged, never raised, so a dead endpoint cannot break the loop.

    Attributes:
        client: The optional CLI webhook client for sending events.
        registry: The optional shared registry of REST-registered webhooks.
        run_id: The current orchestrator run ID for correlation.
    """

    # Default bound on how long close()/flush() wait for in-flight deliveries.
    _DEFAULT_DRAIN_TIMEOUT = 10.0

    def __init__(
        self,
        client: WebhookClient | None,
        run_id: str | None = None,
        registry: WebhookRegistry | None = None,
        *,
        synchronous: bool = False,
    ) -> None:
        """Initialize the webhook emitter.

        Args:
            client: Optional single webhook client (from ``--webhook-url``). It
                receives every event, unfiltered.
            run_id: Optional run ID for event correlation.
            registry: Optional shared webhook registry. Registered webhooks are
                delivered to on each emit, filtered by their subscriptions.
            synchronous: When True, deliver inline on the calling thread instead
                of the background worker. Used by tests (and simple embedders)
                that need delivery to complete before ``emit`` returns.
        """
        self._client = client
        self._run_id = run_id
        self._registry = registry
        self._synchronous = synchronous
        # Background single-worker delivery queue (started lazily on first emit).
        self._queue: queue.Queue[Any] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()
        self._closed = False

    @property
    def enabled(self) -> bool:
        """Check if any webhook destination is configured."""
        return self._client is not None or self._registry is not None

    def emit(
        self,
        event_type: EventType | str,
        **event_data: Any,
    ) -> None:
        """Emit a webhook event to every configured destination.

        Builds the event once (on the calling thread), then hands delivery to a
        background single-worker queue so a slow or dead endpoint can never block
        the orchestrator loop — even across the CLI ``--webhook-url`` client and
        every registered webhook subscribed to this event type. Delivery failures
        are logged, never raised. Pending deliveries are drained by
        :meth:`flush`/:meth:`close`. In ``synchronous`` mode delivery happens
        inline before ``emit`` returns.

        Args:
            event_type: The type of event to emit.
            **event_data: Event-specific data fields.
        """
        # Registered webhooks subscribed to this event (subscription-filtered).
        registry_targets = self._registry_targets(event_type)
        if self._client is None and not registry_targets:
            return

        try:
            # Import here to avoid circular imports
            from ..webhooks.events import create_event

            # Add run_id to all events
            if self._run_id:
                event_data["run_id"] = self._run_id

            event = create_event(event_type, **event_data)
        except Exception as e:
            logger.warning("Failed to build webhook event %s: %s", event_type, e)
            return

        payload = event.to_dict()
        event_name = str(event.event_type)
        delivery_id = event.event_id

        # Resolve every destination into a delivery job (cheap, no network I/O).
        jobs: list[_DeliveryJob] = []
        # The CLI --webhook-url client receives every event (unfiltered).
        if self._client is not None:
            jobs.append(_DeliveryJob(self._client, payload, event_name, delivery_id))
        # Registered webhooks are already filtered to this event's subscribers.
        for webhook_id, config in registry_targets:
            client = self._client_for_config(config)
            if client is not None:
                jobs.append(
                    _DeliveryJob(client, payload, event_name, delivery_id, webhook_id=webhook_id)
                )

        # Hand the actual HTTP delivery (slow, retried) off the calling thread.
        self._dispatch(jobs)

    def _dispatch(self, jobs: list[_DeliveryJob]) -> None:
        """Deliver jobs, either inline (synchronous) or via the background worker.

        Args:
            jobs: The prepared deliveries for a single event.
        """
        if not jobs:
            return
        # Synchronous mode (tests/embedders) and the post-close fallback deliver
        # inline so nothing is silently dropped.
        if self._synchronous or self._closed:
            for job in jobs:
                self._deliver_job(job)
            return
        self._ensure_worker()
        for job in jobs:
            self._queue.put(job)

    def _ensure_worker(self) -> None:
        """Start the single background delivery worker if it isn't running."""
        with self._worker_lock:
            if self._worker is None and not self._closed:
                self._worker = threading.Thread(
                    target=self._run_worker,
                    name="webhook-delivery",
                    daemon=True,
                )
                self._worker.start()

    def _run_worker(self) -> None:
        """Process queued deliveries (and flush markers) until stopped.

        A ``None`` sentinel stops the worker after draining preceding items;
        a :class:`_FlushMarker` signals its waiter that the queue is drained.
        """
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                if isinstance(item, _FlushMarker):
                    item.event.set()
                    continue
                self._deliver_job(item)
            except Exception as e:  # defensive: a bad job must not kill the worker
                logger.warning("Webhook delivery worker error: %s", e)
            finally:
                self._queue.task_done()

    def _deliver_job(self, job: _DeliveryJob) -> None:
        """Deliver a single prepared job through its client."""
        self._deliver(
            job.client,
            job.payload,
            job.event_name,
            job.delivery_id,
            webhook_id=job.webhook_id,
        )

    def flush(self, timeout: float | None = None) -> bool:
        """Block until all queued deliveries have been processed.

        Args:
            timeout: Maximum seconds to wait; ``None`` waits indefinitely.

        Returns:
            True if the queue drained within the timeout (always True in
            synchronous mode or when no worker has started), False on timeout.
        """
        with self._worker_lock:
            worker = self._worker
        if self._synchronous or worker is None:
            return True
        marker = _FlushMarker(threading.Event())
        self._queue.put(marker)
        return marker.event.wait(timeout)

    def close(self, timeout: float | None = None) -> None:
        """Drain pending deliveries and stop the background worker.

        Safe to call repeatedly and when no worker was ever started. After
        close, further :meth:`emit` calls fall back to inline delivery.

        Args:
            timeout: Maximum seconds to wait for the worker to drain and exit.
                Defaults to :data:`_DEFAULT_DRAIN_TIMEOUT`.
        """
        with self._worker_lock:
            worker = self._worker
            self._closed = True
            self._worker = None
        if worker is None:
            return
        # FIFO: the stop sentinel is processed only after all queued deliveries.
        self._queue.put(None)
        worker.join(timeout if timeout is not None else self._DEFAULT_DRAIN_TIMEOUT)

    def _registry_targets(self, event_type: EventType | str) -> list[tuple[str, WebhookConfig]]:
        """Return registered webhooks subscribed to ``event_type``.

        Args:
            event_type: The event being emitted.

        Returns:
            List of ``(webhook_id, config)`` pairs; empty when no registry is
            configured or it cannot be read.
        """
        if self._registry is None:
            return []
        try:
            return self._registry.configs_for_event(event_type)
        except Exception as e:
            logger.warning("Failed to read webhook registry for %s: %s", event_type, e)
            return []

    @staticmethod
    def _client_for_config(config: WebhookConfig) -> WebhookClient | None:
        """Build a delivery client for a registered webhook config.

        Args:
            config: The registered webhook's configuration.

        Returns:
            A configured ``WebhookClient``, or ``None`` if it cannot be built.
        """
        from ..webhooks import WebhookClient

        try:
            return WebhookClient(
                url=config.url,
                secret=config.secret,
                timeout=config.timeout,
                max_retries=config.max_retries,
                retry_delay=config.retry_delay,
                verify_ssl=config.verify_ssl,
                headers=dict(config.headers),
            )
        except Exception as e:
            logger.warning("Skipping webhook with invalid config (%s): %s", config.url, e)
            return None

    def _deliver(
        self,
        client: WebhookClient,
        payload: dict[str, Any],
        event_name: str,
        delivery_id: str,
        webhook_id: str | None = None,
    ) -> None:
        """Deliver a prepared payload to a single webhook client.

        Args:
            client: The webhook client to deliver through.
            payload: The event payload, already serialised to a dict.
            event_name: The event type string for the delivery header.
            delivery_id: The unique delivery id for correlation.
            webhook_id: Optional registry id, included in logs for traceability.
        """
        label = f" (webhook_id={webhook_id})" if webhook_id else ""
        try:
            result = client.send_sync(
                data=payload,
                event_type=event_name,
                delivery_id=delivery_id,
            )
        except Exception as e:
            # Log but don't raise - webhooks shouldn't block the orchestrator.
            logger.warning("Failed to emit webhook event %s%s: %s", event_name, label, e)
            return

        if result.success:
            logger.debug("Webhook delivered: %s%s (delivery_id=%s)", event_name, label, delivery_id)
        else:
            logger.warning("Webhook delivery failed: %s%s - %s", event_name, label, result.error)


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
        self._control_channel: ControlChannel | None = None
        self._task_runner: TaskRunner | None = None
        self._stage_handler: WorkflowStageHandler | None = None
        self._pr_context: PRContextManager | None = None
        self._webhook_emitter: WebhookEmitter | None = None
        self._mailbox_storage: MailboxStorage | None = None
        self._message_merger: MessageMerger | None = None
        self._plan_updater: PlanUpdater | None = None
        self._context_accumulator: ContextAccumulator | None = None

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

            # Initialize with run_id from state if available
            run_id = None
            try:
                if self.state_manager.exists():
                    state = self.state_manager.load_state()
                    run_id = state.run_id
            except Exception:
                pass  # Use None if state can't be loaded
            # Fan out to REST-registered webhooks via the shared registry as well
            # as the optional single --webhook-url client.
            registry = WebhookRegistry(self.state_manager.state_dir)
            self._webhook_emitter = WebhookEmitter(self._webhook_client, run_id, registry=registry)
        return self._webhook_emitter

    def _drain_webhooks(self) -> None:
        """Flush and stop the background webhook worker before ``run`` returns.

        The emitter delivers events on a background daemon thread so a slow or
        dead endpoint can never block the work loop. Without an explicit drain,
        deliveries still queued when :meth:`run` returns — most importantly the
        terminal ``run.completed`` event emitted moments earlier — would be lost
        when the process exits under the daemon thread. Closing blocks (bounded
        by the emitter's own drain timeout) until the queue is flushed and the
        worker exits, then clears the cached emitter so a subsequent :meth:`run`
        on a reused orchestrator starts a fresh worker instead of the closed one.

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
        """Get or lazily initialize the context accumulator.

        Owns the context.md accumulation: after each successful work session the
        orchestrator distils learnings and persists them here so later planning,
        work, and verification prompts build on prior sessions.
        """
        if self._context_accumulator is None:
            self._context_accumulator = ContextAccumulator(self.state_manager)
        return self._context_accumulator

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
                tasks = parse_task_descriptions(plan)
                return len(tasks)
        except Exception:
            pass
        return 0

    def _get_completed_tasks(self, state: TaskState) -> int:
        """Get number of completed tasks from the plan.

        Counts ``- [x]``/``- [X]`` completions via core.plan_parsing.

        Args:
            state: Current task state.

        Returns:
            Number of completed tasks, falling back to
            ``state.current_task_index`` on error or missing plan.
        """
        try:
            plan = self.state_manager.load_plan()
            if plan:
                return count_completed_tasks(plan)
        except Exception:
            pass
        return state.current_task_index

    def _accumulate_context(self, state: TaskState) -> None:
        """Distil the just-finished work session into context.md.

        Runs the extraction prompt over the session output and appends the
        resulting learnings under a ``## Session N`` header, so accumulated
        context grows across sessions and is injected into later
        planning/work/verification prompts.

        Best-effort: any failure is logged and swallowed so a summarizer hiccup
        never fails an otherwise-complete task. ``KeyboardInterrupt`` still
        propagates so Ctrl+C interrupts the run.

        Args:
            state: Current task state (``session_count`` already incremented for
                the session being summarized).
        """
        session_output = getattr(self.task_runner, "last_session_output", "") or ""
        if not session_output.strip():
            return

        try:
            # Feed back the (capped) accumulated context so the model avoids
            # repeating learnings it already captured. get_context_for_prompt
            # bounds the size, keeping extraction cost from growing per session.
            existing_context = self.context_accumulator.get_context_for_prompt()
            learnings = self.agent.extract_session_learnings(
                session_output=session_output,
                existing_context=existing_context,
            )
            if learnings.strip():
                self.context_accumulator.add_session_summary(state.session_count, learnings.strip())
                console.detail(f"context.md updated from session {state.session_count}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            # Context accumulation is advisory; never let it fail the task.
            logger.warning("Context accumulation failed (non-fatal): %s", e)
            console.detail(f"Context accumulation skipped (non-fatal): {e}")

    def _build_completed_tasks_summary(self, state: TaskState) -> str:
        """Summarize completed tasks + merged PRs for the verification prompt.

        Distinct from accumulated context.md: this lists what was actually done
        (checked-off ``- [x]`` plan tasks plus PR counts) so the verifier sees
        the concrete deliverables, while context.md is injected separately under
        its own header.

        Args:
            state: Current task state.

        Returns:
            Markdown bullet list, or ``""`` when nothing is available.
        """
        lines: list[str] = []
        try:
            plan = self.state_manager.load_plan()
            if plan:
                lines.extend(
                    f"- {desc}"
                    for index, desc in enumerate(parse_task_descriptions(plan))
                    if is_task_complete(plan, index)
                )
        except Exception:
            pass

        if state.prs_created or state.prs_merged:
            pr_line = f"- PRs: {state.prs_created} created, {state.prs_merged} merged"
            if state.last_counted_pr_merged is not None:
                pr_line += f" (last merged: #{state.last_counted_pr_merged})"
            lines.append(pr_line)

        return "\n".join(lines)

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
        """Emit a pr.created webhook event and increment prs_created counter.

        Args:
            state: Current task state with PR information.
        """
        if not state.current_pr:
            return

        # Check for idempotency - skip if this PR was already counted
        if state.last_counted_pr_created == state.current_pr:
            return

        # Increment PR created counter and mark this PR as counted
        state.prs_created += 1
        state.last_counted_pr_created = state.current_pr
        self.state_manager.save_state_merged(state)

        # Get PR details from GitHub
        pr_url = ""
        pr_title = ""
        base_branch = "main"
        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)
            pr_url = pr_status.url
            pr_title = pr_status.title
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
        """Emit a pr.merged webhook event and increment prs_merged counter.

        Args:
            state: Current task state with PR information.
        """
        if not state.current_pr:
            return

        # Check for idempotency - skip if this PR was already counted
        if state.last_counted_pr_merged == state.current_pr:
            return

        # Increment PR merged counter and mark this PR as counted
        state.prs_merged += 1
        state.last_counted_pr_merged = state.current_pr
        self.state_manager.save_state_merged(state)

        # Get PR details from GitHub
        pr_url = ""
        pr_title = ""
        base_branch = "main"
        merged_at = None
        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)
            pr_url = pr_status.url
            pr_title = pr_status.title
            base_branch = pr_status.base_branch
            merged_at = getattr(pr_status, "merged_at", None)
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
            self.state_manager.save_state_merged(state)
            return False

        # Log that we're processing messages
        logger.info(
            "Mailbox check: found %d message(s) to process",
            message_count,
        )
        console.info(f"Found {message_count} message(s) in mailbox - processing...")

        # Peek at messages WITHOUT removing them. They are removed only after
        # being fully processed (see remove_messages below), so a transient
        # failure in merge or plan update leaves the user's change requests in
        # the mailbox to be retried on the next check instead of losing them.
        messages = self.mailbox_storage.get_messages()
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
            # Messages were only peeked, never removed, so they stay in the
            # mailbox and are retried on the next check.
            return False

        # Update the plan with the merged content
        logger.debug("Starting plan update from mailbox messages")
        try:
            # Capture task count before update for diff calculation
            total_tasks_before = self._get_total_tasks(state)

            console.info("Updating plan based on mailbox messages...")
            result = self.plan_updater.update_plan(
                merged_content, current_task_index=state.current_task_index
            )

            # Adopt any positional-index reconciliation before the state save
            # below. current_task_index is orchestrator-owned (not merged from
            # disk by save_state_merged), so the stale in-memory value would
            # otherwise clobber the plan updater's on-disk fix.
            reconciled_index = result.get("current_task_index")
            if reconciled_index is not None:
                state.current_task_index = reconciled_index

            # update_plan returned without raising: the plan (if changed) is
            # already persisted, so these messages are fully processed. Remove
            # exactly the peeked IDs — not a blanket clear — so any message that
            # arrived during the update is preserved for the next check.
            logger.info(
                "Dropping %d processed mailbox message(s)",
                len(messages),
            )
            removed = self.mailbox_storage.remove_messages([msg.id for msg in messages])
            logger.debug(
                "Removed %d processed message(s) from mailbox after plan update",
                removed,
            )

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
                self.state_manager.save_state_merged(state)
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
                self.state_manager.save_state_merged(state)
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
            # Not removed — messages remain in the mailbox so they are not lost.
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
            # Not removed — a transient error (e.g. API failure) must not
            # permanently lose the user's change requests; retried next check.
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
            prs_created=state.prs_created,
            prs_merged=state.prs_merged,
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

        # Load state with recovery. Backup fallback is scoped to genuine
        # corruption: a StateValidationError signals a *deliberate* schema or
        # structural incompatibility (state written by a newer version, an
        # invalid schema marker, missing required fields). Silently restoring an
        # older backup there would downgrade the state and destroy
        # forward-schema fields, so that error is surfaced instead.
        try:
            state = self.state_manager.load_state()
        except StateValidationError:
            raise
        except StateError as e:
            console.warning(f"State loading error: {e.message}")
            recovered = self._attempt_state_recovery()
            if recovered:
                console.success("State recovered from backup")
                state = recovered
            else:
                raise StateRecoveryError("State file corrupted", e) from e

        # Reset CI poll timer when resuming a paused run mid-CI-wait so the
        # timeout doesn't fire immediately (timer restarts on next stage entry)
        if state.workflow_stage in ("waiting_ci", "waiting_reviews") and (
            state.ci_poll_start_time is not None
        ):
            state.ci_poll_start_time = None
            self.state_manager.save_state_merged(state)

        # Check max sessions
        if state.options.max_sessions and state.session_count >= state.options.max_sessions:
            console.warning(
                MaxSessionsReachedError(state.options.max_sessions, state.session_count).message
            )
            self._emit_run_completed(state, 1, "blocked", run_start_time, "Max sessions reached")
            # Early return bypasses the finally below; drain here so the
            # run.completed delivery isn't dropped on process exit.
            self._drain_webhooks()
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

        # Bind the durable control channel so a cross-process stop (from
        # claudetm-server / MCP / CLI in another process) is observed by
        # is_shutdown_requested()/interruptible_sleep — reaching even a long
        # in-cycle CI wait. Unbound in the finally below.
        set_durable_stop_check(self.control_channel.stop_requested)

        def _handle_pause(reason: str) -> int:
            stop_listening()
            unregister_handlers()
            console.newline()
            console.warning(f"{reason} - pausing...")
            self.tracker.end_session(outcome="cancelled")
            previous_status = state.status
            state.status = "paused"
            self._emit_status_changed(previous_status, "paused", state, reason)
            # Merged save (backs up on every write) so a config patch from
            # another process is not reverted; in the pause flow disk is
            # "working" or already "paused", so "paused" is persisted.
            self.state_manager.save_state_merged(state)
            console.newline()
            console.info(self.tracker.get_cost_report())
            console.info("Use 'claudetm resume' to continue")
            self._emit_run_completed(state, 2, "interrupted", run_start_time, reason)
            return 2

        def _handle_stop(reason: str) -> int:
            stop_listening()
            unregister_handlers()
            console.newline()
            console.warning(f"{reason} - stopping...")
            self.tracker.end_session(outcome="cancelled")
            previous_status = state.status
            state.status = "stopped"
            self._emit_status_changed(previous_status, "stopped", state, reason)
            # Re-assert the authoritative stopped status. Routine saves in this
            # cycle already go through save_state_merged, which keeps a
            # cross-process "stopped" instead of clobbering it with the stale
            # in-memory "working"; this final merged save persists it plainly.
            self.state_manager.save_state_merged(state)
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
                # Durable cross-process control: a stop/pause written to
                # control.json by ControlManager (server / MCP / CLI in another
                # process) is polled here each cycle, beside the in-process
                # cancellation check below.
                control_request = self.control_channel.read()
                if control_request is not None:
                    self.control_channel.clear()
                    if control_request.action == "stop":
                        return _handle_stop(control_request.reason or "Stop requested")
                    return _handle_pause(control_request.reason or "Pause requested")

                # Check cancellation (Escape / SIGINT / durable stop bridged via
                # the shutdown manager during an in-cycle wait).
                if is_cancellation_requested():
                    # A durable stop that raced in after the poll above (or broke
                    # an in-cycle wait) surfaces here — honour it as a stop, not
                    # a pause, so the terminal status matches the request.
                    if self.control_channel.stop_requested():
                        self.control_channel.clear()
                        return _handle_stop(get_cancellation_reason() or "Stop requested")
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
                    self.state_manager.save_state_merged(state)
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
                    result_str = {0: "success", 2: "interrupted"}.get(result, "blocked")
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
                    self.state_manager.save_state_merged(state)
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

            # Final verification is opt-in (off by default). Each task already
            # verifies itself (tests + lint) and PRs go through CI + reviews,
            # so the post-all-tasks success-criteria verification + fix loop is
            # often redundant and can hang in long sessions (re-verify cycles).
            # Enable with --verify or TaskOptions.enable_verification=True.
            if not state.options.enable_verification:
                self._checkout_to_main()
                previous_status = state.status
                state.status = "success"
                self._emit_status_changed(
                    previous_status,
                    "success",
                    state,
                    "All tasks completed (final verification disabled)",
                )
                self.state_manager.save_state_merged(state)
                console.success(
                    "All tasks completed! (Final verification skipped — pass --verify to enable.)"
                )
                console.info(self.tracker.get_cost_report())
                # Emit run.completed BEFORE cleanup deletes plan/goal (payload needs them)
                self._emit_run_completed(state, 0, "success", run_start_time)
                self.state_manager.cleanup_on_success(state.run_id)
                return 0

            # Allow up to 3 fix attempts
            max_fix_attempts = 3
            fix_attempt = 0

            while fix_attempt <= max_fix_attempts:
                verification = self._verify_success(state)

                if verification["success"]:
                    # Success! Checkout to main and cleanup
                    self._checkout_to_main()
                    previous_status = state.status
                    state.status = "success"
                    self._emit_status_changed(
                        previous_status, "success", state, "All tasks completed successfully"
                    )
                    self.state_manager.save_state_merged(state)
                    console.success("All tasks completed successfully!")
                    console.info(self.tracker.get_cost_report())
                    # Emit run.completed BEFORE cleanup deletes plan/goal (payload needs them)
                    self._emit_run_completed(state, 0, "success", run_start_time)
                    self.state_manager.cleanup_on_success(state.run_id)
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
                    self.state_manager.save_state_merged(state)
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
                    self.state_manager.save_state_merged(state)
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
                    self.state_manager.save_state_merged(state)
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
            self.state_manager.save_state_merged(state)
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
                self.state_manager.save_state_merged(state)
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
                self.state_manager.save_state_merged(state)
            except Exception:
                pass  # Best effort - state save failed but we still return error
            self._emit_run_completed(state, 1, "failed", run_start_time, error_message)
            return 1
        finally:
            # Unbind the durable stop check so a later run/instance sharing the
            # global shutdown manager is not affected by this run's channel.
            set_durable_stop_check(None)
            # Flush background webhook deliveries (notably the terminal
            # run.completed event queued moments ago) before returning so they
            # are not lost when the process exits under the daemon worker.
            self._drain_webhooks()

    def _run_workflow_cycle(self, state: TaskState) -> int | None:
        """Run one cycle of the PR workflow."""
        if state.workflow_stage is None:
            state.workflow_stage = "working"
            self.state_manager.save_state_merged(state)

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
                # Emit pr.merged webhook if PR was merged (stage changed to "merged").
                # Idempotent (gated by last_counted_pr_merged); handle_merged_stage
                # also emits via callback to cover externally-merged PRs.
                if state.workflow_stage == "merged" and stage_before == "ready_to_merge":
                    self._emit_pr_merged_event(state)
                return result
            elif stage == "merged":
                return self.stage_handler.handle_merged_stage(
                    state,
                    self.task_runner.mark_task_complete,
                    self._emit_pr_merged_event,
                )
            elif stage == "releasing":
                return self.stage_handler.handle_releasing_stage(state)
            elif stage == "release_fix":
                return self.stage_handler.handle_release_fix_stage(state)
            else:
                console.warning(f"Unknown stage: {stage}, resetting")
                state.workflow_stage = "working"
                self.state_manager.save_state_merged(state)
                return None

        except NoPlanFoundError as e:
            console.error(e.message)
            previous_status = state.status
            state.status = "failed"
            self._emit_status_changed(previous_status, "failed", state, e.message)
            self.state_manager.save_state_merged(state)
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
            self.state_manager.save_state_merged(state)
            return 1
        except CircuitBreakerError as e:
            console.warning(f"Circuit breaker: {e.message}")
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(
                previous_status, "blocked", state, f"Circuit breaker: {e.message}"
            )
            self.state_manager.save_state_merged(state)
            return 1
        except ConsecutiveFailuresError as e:
            console.error(f"Consecutive failures: {e.message}")
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(
                previous_status, "blocked", state, f"Consecutive failures: {e.message}"
            )
            self.state_manager.save_state_merged(state)
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

        # Set task start time if not already set (first work session for this task)
        if state.task_start_time is None:
            state.task_start_time = datetime.now()
            self.state_manager.save_state_merged(state)

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
        # Capture the task index BEFORE the work session: on a normal run the
        # runner may advance state.current_task_index, and on an
        # already-complete task it advances the index without doing any work.
        completed_task_index = state.current_task_index
        session_result: str | None = None
        try:
            session_result = self.task_runner.run_work_session(state)
        except Exception as e:
            outcome = "failed"
            error_message = str(e)
            error_type = type(e).__name__
            self.tracker.record_error()
            raise
        finally:
            session_duration = time.time() - session_start_time
            if session_result == "skipped_already_complete":
                outcome = "skipped"
            # Feed actual cost/token data from the most recent ResultMessage
            # before ending the session so the cost report shows real charges.
            mp = getattr(self.agent, "_message_processor", None)
            if mp is not None:
                cost_usd = getattr(mp, "last_total_cost_usd", None)
                if isinstance(cost_usd, float):
                    self.tracker.record_cost(
                        cost_usd=cost_usd,
                        tokens_in=int(getattr(mp, "last_input_tokens", 0) or 0),
                        tokens_out=int(getattr(mp, "last_output_tokens", 0) or 0),
                    )
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

        # Task was already complete - the runner advanced state.current_task_index.
        # Skip session counting, mark_task_complete, and task.completed; return so
        # the next loop iteration picks up the new index.
        if session_result == "skipped_already_complete":
            console.info(f"Task #{completed_task_index + 1} already complete - skipping")
            self.state_manager.save_state_merged(state)
            return None

        self.tracker.record_task_progress(state.current_task_index)
        reset_escape()

        state.session_count += 1

        # Accumulate active work time for PR timing
        state.pr_active_work_seconds += session_duration

        # Mark current task as complete in plan.md
        # This is done by the orchestrator (not the agent) for reliability
        plan = self.state_manager.load_plan()
        if plan:
            self.task_runner.mark_task_complete(plan, completed_task_index)
            console.success(f"Task #{completed_task_index + 1} marked complete in plan.md")

        # Calculate and log task duration
        if state.task_start_time:
            task_duration_seconds = (datetime.now() - state.task_start_time).total_seconds()
        else:
            # Fallback to session duration if task_start_time not set
            # (e.g., state created before timing feature added)
            task_duration_seconds = session_duration

        # Always log timing (to file and console)
        if self.logger:
            self.logger.log_task_timing(state.current_task_index, task_duration_seconds)
        console.info(
            f"Task #{completed_task_index + 1} took {task_duration_seconds / 60:.1f} minutes"
        )

        # Distil this session's output into accumulated context.md (best-effort)
        # so later sessions build on prior learnings.
        self._accumulate_context(state)

        # Emit task.completed webhook event
        # (count already includes the task just marked complete in plan.md)
        completed_tasks = self._get_completed_tasks(state)
        self.webhook_emitter.emit(
            "task.completed",
            task_index=state.current_task_index,
            task_description=task_desc,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            duration_seconds=task_duration_seconds if state.task_start_time else session_duration,
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
                # Reset task timing for next task, but keep PR timing (same PR group)
                state.task_start_time = None

        # Update progress.md AFTER incrementing task index
        # So the arrow → points to the NEXT task, not the one we just completed
        self.task_runner.update_progress(state)

        self.state_manager.save_state_merged(state)

        # Stall check after the session ended (works without an active session)
        should_abort, abort_reason = self.tracker.should_abort()
        if should_abort:
            console.warning(f"Execution issue: {abort_reason}")
            previous_status = state.status
            state.status = "blocked"
            self._emit_status_changed(previous_status, "blocked", state, abort_reason)
            self.state_manager.save_state_merged(state)
            return 1

        return None

    def _attempt_state_recovery(self) -> TaskState | None:
        """Attempt to recover state from the newest non-stale backup.

        Delegates to the state manager's staleness-guarded backup selection so a
        materially old backup is never silently restored (which would roll back
        merged tasks or duplicate PRs). Performs no write; the caller resumes
        from the returned in-memory state.

        Returns:
            The recovered TaskState, or None if no fresh-enough backup exists.
        """
        try:
            reference_time: datetime | None = None
            state_file = self.state_manager.state_file
            if state_file.exists():
                try:
                    reference_time = datetime.fromtimestamp(state_file.stat().st_mtime)
                except OSError:
                    reference_time = None
            return self.state_manager.find_recoverable_state(reference_time)
        except Exception:
            return None

    def _verify_success(self, state: TaskState) -> dict:
        """Verify success criteria are met.

        Args:
            state: Current task state (used to summarize completed tasks/PRs).

        Returns:
            Dict with 'success' (bool) and 'details' (str) keys.
        """
        criteria = self.state_manager.load_criteria()
        if not criteria:
            return {"success": True, "details": "No criteria specified"}

        # Pass accumulated context and the real completed-tasks summary
        # separately so context is injected under its own header rather than
        # being mislabelled as the list of completed tasks.
        context = self.state_manager.load_context()
        tasks_summary = self._build_completed_tasks_summary(state)
        result = self.agent.verify_success_criteria(
            criteria=criteria, context=context, tasks_summary=tasks_summary
        )
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
            # Load coding style for consistent style in fix session
            coding_style = self.state_manager.load_coding_style()

            # Verification fix creates a NEW PR (there is no existing PR to push
            # to): _wait_for_fix_pr_merge then detects it via
            # get_pr_for_current_branch(). Do NOT switch this to push_only — that
            # would skip PR creation and leave the detection step with nothing.
            self.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=ModelType.OPUS,
                create_pr=True,
                coding_style=coding_style,
            )
            state.session_count += 1
            self.state_manager.save_state_merged(state)
            return True
        except Exception as e:
            console.error(f"Fix session failed: {e}")
            return False

    def _wait_for_fix_pr_merge(self, state: TaskState) -> bool:
        """Wait for fix PR to pass CI and merge it.

        If CI fails, attempts to fix the issues (up to 2 retries) before giving up.
        This mirrors the regular PR workflow where CI failures trigger fix sessions.

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
            # Only set pr_start_time if not already set (avoid overwriting on resume)
            if state.pr_start_time is None:
                state.pr_start_time = datetime.now()
            self.state_manager.save_state_merged(state)
        except Exception as e:
            console.warning(f"Could not detect fix PR: {e}")
            return False

        # Allow up to 2 CI fix attempts before giving up
        max_ci_fix_attempts = 2
        ci_fix_attempt = 0

        while ci_fix_attempt <= max_ci_fix_attempts:
            # Poll CI until success or failure
            ci_result = self._poll_fix_pr_ci(pr_number, state)

            if ci_result == "success":
                # CI passed, proceed to merge
                break
            elif ci_result == "failure":
                ci_fix_attempt += 1
                if ci_fix_attempt > max_ci_fix_attempts:
                    console.error(f"Fix PR CI failed after {ci_fix_attempt - 1} fix attempts")
                    return False

                # Attempt to fix the CI failure
                console.info(
                    f"Attempting to fix CI failure ({ci_fix_attempt}/{max_ci_fix_attempts})..."
                )
                if not self._fix_pr_ci_failure(pr_number, state):
                    console.error("Failed to fix CI issues")
                    return False

                # Wait for CI to restart after push
                console.info("Waiting 60s for CI to restart...")
                if not interruptible_sleep(60):
                    return False
            else:
                # Interrupted or timed out
                return False

        # Merge the PR
        if state.options.auto_merge:
            try:
                console.info(f"Merging fix PR #{pr_number}...")
                self.github_client.merge_pr(pr_number, admin=state.options.admin_merge)
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

    def _poll_fix_pr_ci(self, pr_number: int, state: TaskState) -> str:
        """Poll CI status for a fix PR.

        Args:
            pr_number: The PR number to check.
            state: Current task state.

        Returns:
            "success" if CI passed, "failure" if CI failed, "interrupted" if cancelled.
        """
        max_wait = 7200  # 120 minutes max (big CIs can run long)
        poll_interval = 10
        waited = 0

        while waited < max_wait:
            try:
                pr_status = self.github_client.get_pr_status(pr_number)

                if pr_status.ci_state == "SUCCESS":
                    console.success("Fix PR CI passed!")
                    return "success"
                elif pr_status.ci_state in ("FAILURE", "ERROR"):
                    console.warning("Fix PR CI failed")
                    return "failure"
                else:
                    console.info(f"Waiting for fix PR CI... ({pr_status.checks_pending} pending)")
                    if not interruptible_sleep(poll_interval):
                        return "interrupted"
                    waited += poll_interval
            except Exception as e:
                console.warning(f"Error checking CI: {e}")
                if not interruptible_sleep(poll_interval):
                    return "interrupted"
                waited += poll_interval

        console.warning("Timed out waiting for fix PR CI")
        return "interrupted"

    def _fix_pr_ci_failure(self, pr_number: int, state: TaskState) -> bool:
        """Fix CI failures on a fix PR.

        Saves CI failure logs and runs an agent to fix the issues.

        Args:
            pr_number: The PR number with failing CI.
            state: Current task state.

        Returns:
            True if fix session completed successfully.
        """
        try:
            # Save CI failure logs
            self.pr_context.save_ci_failures(pr_number)

            # Get feedback (CI failures)
            has_ci, has_comments, pr_dir_path = self.pr_context.get_combined_feedback(pr_number)

            if not has_ci and not has_comments:
                console.warning("No CI failures or comments found to fix")
                return False

            # Build task description
            ci_path = f"{pr_dir_path}/ci/" if pr_dir_path else ".claude-task-master/debugging/"

            task_description = f"""
Fix PR CI Failure

The CI checks have failed for this fix PR. Your task is to:

1. Read the CI failure logs in `{ci_path}`
2. Understand what tests/lints are failing
3. Fix the issues in the codebase
4. Run tests locally to verify fixes (check package.json, Makefile, or pyproject.toml for test commands)
5. Commit and push the fixes

Important:
- Only fix issues identified in the CI logs
- Run tests locally before committing
- Push changes to trigger a new CI run
"""

            # Run agent to fix issues
            context = self.state_manager.load_context()
            coding_style = self.state_manager.load_coding_style()

            current_branch = self._get_current_branch()

            # Determine the fix PR's head branch - after a resume we may be on
            # main, so fetch the PR head ref instead of trusting the checkout
            head_branch = None
            try:
                head_branch = self.github_client.get_pr_status(pr_number).head_branch
            except Exception as e:
                console.warning(f"Could not fetch PR head branch: {e}")

            # Best effort: checkout the PR branch if we're not already on it
            if head_branch and head_branch != current_branch:
                try:
                    subprocess.run(
                        ["git", "checkout", head_branch],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    console.info(f"Checked out PR branch {head_branch}")
                except Exception as e:
                    console.warning(f"Failed to checkout {head_branch}: {e}")

            # Fix an EXISTING fix PR: push to re-trigger CI, never open a new PR
            # or rebase (push_only routes through _build_push_only_execution,
            # which forbids rebasing already-reviewed commits).
            self.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=ModelType.OPUS,
                required_branch=head_branch or current_branch,
                coding_style=coding_style,
                create_pr=False,
                push_only=True,
            )

            state.session_count += 1
            self.state_manager.save_state_merged(state)
            return True

        except Exception as e:
            console.error(f"Failed to fix CI issues: {e}")
            return False
