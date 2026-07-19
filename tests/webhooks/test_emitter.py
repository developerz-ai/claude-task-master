"""Tests for WebhookEmitter fan-out delivery.

Covers the delivery contract the emitter + registry integration must satisfy:

- A webhook registered via the REST API and subscribed to ``run.started``
  actually receives the event (end-to-end fan-out through the registry).
- emit() returns immediately on the calling thread; a slow or dead delivery
  endpoint cannot stall the orchestrator loop (background-worker assertion).
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from unittest.mock import patch

from claude_task_master.core.orchestrator import WebhookEmitter
from claude_task_master.webhooks.registry import WebhookRegistry

# =============================================================================
# Helpers
# =============================================================================


def _register(
    registry: WebhookRegistry,
    url: str,
    *,
    events: list[str] | None = None,
) -> str:
    """Insert a minimal webhook record into the registry.

    Args:
        registry: The registry to write into.
        url: Endpoint URL for the new webhook.
        events: Event filter list, or None for all events.

    Returns:
        The generated webhook id.
    """
    wid = f"wh_{uuid.uuid4().hex[:8]}_{uuid.uuid4().hex[:8]}"
    with registry.transaction() as webhooks:
        webhooks[wid] = {
            "url": url,
            "secret": None,
            "events": events,
            "enabled": True,
            "name": None,
            "description": None,
            "timeout": 1.0,
            "max_retries": 0,
            "verify_ssl": False,
            "headers": {},
            "created_at": "2026-07-19T00:00:00",
            "updated_at": "2026-07-19T00:00:00",
        }
    return wid


# =============================================================================
# Fan-out: registered webhook receives run.started
# =============================================================================


class TestRegisteredWebhookFanout:
    """A registered webhook subscribed to run.started actually receives it."""

    def test_run_started_delivered_to_registered_webhook(self, state_dir: Path) -> None:
        """Fan-out delivers run.started payload to a subscribed registered webhook."""
        registry = WebhookRegistry(state_dir)
        _register(registry, "https://example.com/hook", events=["run.started"])

        # synchronous=True: delivery completes inline before emit() returns.
        emitter = WebhookEmitter(client=None, registry=registry, synchronous=True)

        delivered: list[dict] = []

        def _capture(client, payload, event_name, delivery_id, *, webhook_id=None):
            delivered.append({"payload": payload, "event_name": event_name})

        with patch.object(emitter, "_deliver", side_effect=_capture):
            emitter.emit("run.started", goal="test goal", working_directory="/tmp")

        assert len(delivered) == 1
        assert delivered[0]["event_name"] == "run.started"
        assert delivered[0]["payload"]["event_type"] == "run.started"
        assert delivered[0]["payload"]["goal"] == "test goal"

    def test_run_started_payload_contains_event_metadata(self, state_dir: Path) -> None:
        """The delivered payload carries event_id and timestamp alongside domain data."""
        registry = WebhookRegistry(state_dir)
        _register(registry, "https://example.com/hook", events=["run.started"])
        emitter = WebhookEmitter(client=None, registry=registry, synchronous=True)

        delivered: list[dict] = []

        def _capture(client, payload, event_name, delivery_id, *, webhook_id=None):
            delivered.append(payload)

        with patch.object(emitter, "_deliver", side_effect=_capture):
            emitter.emit("run.started", goal="my goal", working_directory="/workspace")

        p = delivered[0]
        assert p["event_type"] == "run.started"
        assert "event_id" in p and p["event_id"]
        assert "timestamp" in p and p["timestamp"]
        assert p["goal"] == "my goal"

    def test_unsubscribed_webhook_does_not_receive_run_started(self, state_dir: Path) -> None:
        """A webhook subscribed only to task.completed is not called for run.started."""
        registry = WebhookRegistry(state_dir)
        _register(registry, "https://example.com/hook", events=["task.completed"])
        emitter = WebhookEmitter(client=None, registry=registry, synchronous=True)

        with patch.object(emitter, "_deliver") as mock_deliver:
            emitter.emit("run.started", goal="test", working_directory="/tmp")

        mock_deliver.assert_not_called()

    def test_all_events_webhook_receives_run_started(self, state_dir: Path) -> None:
        """A webhook with events=None (all events) receives run.started."""
        registry = WebhookRegistry(state_dir)
        _register(registry, "https://example.com/hook", events=None)  # subscribe to all
        emitter = WebhookEmitter(client=None, registry=registry, synchronous=True)

        delivered: list[dict] = []

        def _capture(client, payload, event_name, delivery_id, *, webhook_id=None):
            delivered.append(payload)

        with patch.object(emitter, "_deliver", side_effect=_capture):
            emitter.emit("run.started", goal="test", working_directory="/tmp")

        assert len(delivered) == 1
        assert delivered[0]["event_type"] == "run.started"


# =============================================================================
# Non-blocking delivery: emit() returns before the endpoint responds
# =============================================================================


class TestEmitNonBlocking:
    """emit() returns immediately; slow or dead endpoints never stall the caller."""

    #: Maximum wall-clock seconds emit() may consume (well under any retry period).
    _BUDGET_S = 0.5

    def test_emit_returns_immediately_with_slow_endpoint(self, state_dir: Path) -> None:
        """emit() returns in < 0.5 s even when send_sync blocks indefinitely."""
        registry = WebhookRegistry(state_dir)
        _register(registry, "https://dead.example.com/hook")

        hold = threading.Event()  # released after timing check

        def _block(client, payload, event_name, delivery_id, *, webhook_id=None):
            hold.wait(timeout=10.0)

        # Background-worker mode (synchronous=False is the default).
        emitter = WebhookEmitter(client=None, registry=registry, synchronous=False)

        with patch.object(emitter, "_deliver", side_effect=_block):
            t0 = time.monotonic()
            emitter.emit("run.started", goal="test", working_directory="/tmp")
            elapsed = time.monotonic() - t0

            # Timing must be checked *before* we unblock the delivery thread.
            assert elapsed < self._BUDGET_S, (
                f"emit() blocked for {elapsed:.3f}s — background delivery must not stall caller"
            )
            hold.set()
            emitter.close(timeout=3.0)
