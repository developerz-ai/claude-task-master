"""Webhook notification system for Claude Task Master.

This module provides webhook support for notifying external systems about
task events. It includes:

- WebhookClient: HTTP client for sending webhook payloads with HMAC signatures
- WebhookManager: High-level manager for webhook configuration and delivery
- Event types: Structured event classes for different webhook events

Usage:
    from claude_task_master.webhooks import WebhookClient, WebhookManager

    # Simple client usage
    client = WebhookClient(url="https://example.com/webhook", secret="mysecret")
    response = await client.send({"event": "task.completed", "data": {...}})

    # Manager usage for configuration and queuing
    manager = WebhookManager(config=WebhookConfig(...))
    await manager.emit("task.completed", task_data)

    # Create typed events
    from claude_task_master.webhooks import EventType, create_event
    event = create_event(EventType.TASK_COMPLETED, task_index=0)
"""

from __future__ import annotations

from claude_task_master.webhooks.client import (
    WebhookClient,
    WebhookDeliveryError,
    WebhookDeliveryResult,
    WebhookTimeoutError,
)
from claude_task_master.webhooks.events import (
    EventType,
    PRCreatedEvent,
    PRMergedEvent,
    SessionCompletedEvent,
    SessionStartedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskStartedEvent,
    WebhookEvent,
    create_event,
    get_event_class,
)

__all__ = [
    # Client
    "WebhookClient",
    "WebhookDeliveryError",
    "WebhookDeliveryResult",
    "WebhookTimeoutError",
    # Events
    "EventType",
    "WebhookEvent",
    "TaskStartedEvent",
    "TaskCompletedEvent",
    "TaskFailedEvent",
    "PRCreatedEvent",
    "PRMergedEvent",
    "SessionStartedEvent",
    "SessionCompletedEvent",
    "create_event",
    "get_event_class",
]
