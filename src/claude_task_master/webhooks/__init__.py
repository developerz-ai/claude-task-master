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
"""

from __future__ import annotations

from claude_task_master.webhooks.client import (
    WebhookClient,
    WebhookDeliveryError,
    WebhookDeliveryResult,
    WebhookTimeoutError,
)

__all__ = [
    "WebhookClient",
    "WebhookDeliveryError",
    "WebhookDeliveryResult",
    "WebhookTimeoutError",
]
