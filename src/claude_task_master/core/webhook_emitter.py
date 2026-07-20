"""WebhookEmitter — background-threaded fan-out delivery to all configured webhooks.

Extracted from orchestrator.py so the class can be imported by both the
orchestrator and test fixtures without pulling in the full work-loop.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..webhooks import WebhookClient, WebhookRegistry
    from ..webhooks.config import WebhookConfig
    from ..webhooks.events import EventType

logger = logging.getLogger(__name__)


# =============================================================================
# Internal helpers
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


# =============================================================================
# WebhookEmitter
# =============================================================================


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
        # close() may have flipped _closed after the check above; if the worker
        # can no longer start, deliver inline so nothing is silently dropped.
        with self._worker_lock:
            if self._closed or self._worker is None:
                for job in jobs:
                    self._deliver_job(job)
                return
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
