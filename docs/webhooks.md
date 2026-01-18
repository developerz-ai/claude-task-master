# Webhooks Guide

This guide covers webhook event notifications in Claude Task Master, including event types, payload formats, HMAC signature verification, and integration examples.

## Table of Contents

- [Overview](#overview)
- [Event Types](#event-types)
- [Webhook Configuration](#webhook-configuration)
- [Payload Format](#payload-format)
- [HMAC Signature Verification](#hmac-signature-verification)
- [HTTP Headers](#http-headers)
- [Event Payloads](#event-payloads)
  - [Task Events](#task-events)
  - [Pull Request Events](#pull-request-events)
  - [Session Events](#session-events)
- [Delivery and Retry Behavior](#delivery-and-retry-behavior)
- [Configuration Examples](#configuration-examples)
- [Integration Examples](#integration-examples)
- [Testing Webhooks](#testing-webhooks)
- [Security Best Practices](#security-best-practices)
- [Troubleshooting](#troubleshooting)

---

## Overview

Webhooks enable Claude Task Master to send real-time HTTP notifications to external services when specific events occur during task orchestration. This allows you to:

- **Monitor task progress** in real-time via external dashboards or notification services
- **Trigger automated workflows** based on task lifecycle events
- **Integrate with CI/CD pipelines** to coordinate deployments
- **Send notifications** to Slack, Discord, email, or custom systems
- **Log events** to external monitoring and analytics platforms

All webhook payloads are sent as JSON via HTTP POST requests and can be secured with HMAC-SHA256 signatures.

---

## Event Types

Claude Task Master emits the following webhook event types:

| Event Type | Description | When Emitted |
|------------|-------------|--------------|
| `task.started` | Task execution begins | When the orchestrator starts working on a task |
| `task.completed` | Task completes successfully | When a task finishes with all requirements met |
| `task.failed` | Task fails with error | When a task encounters an unrecoverable error |
| `pr.created` | Pull request created | When a PR is created for completed tasks |
| `pr.merged` | Pull request merged | When a PR is successfully merged |
| `session.started` | Work session begins | When a Claude Agent SDK query starts |
| `session.completed` | Work session completes | When a Claude Agent SDK query finishes |

### Event Filtering

When configuring a webhook, you can subscribe to:
- **All events** - Leave the `events` field empty or null
- **Specific events** - Provide an array of event types (e.g., `["task.completed", "pr.created"]`)

---

## Webhook Configuration

Webhooks are configured via the REST API. Each webhook configuration includes:

```json
{
  "url": "https://hooks.example.com/webhook",
  "secret": "your-shared-secret",
  "events": ["task.completed", "pr.created"],
  "enabled": true,
  "name": "Production Notifications",
  "description": "Send task updates to monitoring system",
  "timeout": 30.0,
  "max_retries": 3,
  "verify_ssl": true,
  "headers": {
    "X-Custom-Header": "value"
  }
}
```

### Configuration Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | string | Yes | - | Webhook endpoint URL (must be http:// or https://) |
| `secret` | string | No | null | Shared secret for HMAC-SHA256 signature generation |
| `events` | array | No | null | Event types to subscribe to (null = all events) |
| `enabled` | boolean | No | true | Whether the webhook is active |
| `name` | string | No | null | Friendly name (max 100 chars) |
| `description` | string | No | null | Description (max 500 chars) |
| `timeout` | float | No | 30.0 | Request timeout in seconds (1-300) |
| `max_retries` | integer | No | 3 | Maximum retry attempts (0-10) |
| `verify_ssl` | boolean | No | true | Whether to verify SSL certificates |
| `headers` | object | No | {} | Additional HTTP headers to include |

See the [REST API Reference](./api-reference.md#webhook-endpoints) for details on creating and managing webhooks.

---

## Payload Format

All webhook payloads follow a consistent JSON structure with common metadata fields:

```json
{
  "event_type": "task.completed",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-18T15:45:10.123456Z",
  "run_id": "run_20240118_143022",

  // Event-specific fields below
  "task_index": 3,
  "task_description": "Add dark mode support",
  "total_tasks": 10,
  "completed_tasks": 4,
  "duration_seconds": 125.5,
  "commit_hash": "abc123def456",
  "branch": "feat/dark-mode",
  "pr_group": "UI Enhancements"
}
```

### Common Fields

All events include these base fields:

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | string | The event type (e.g., "task.completed") |
| `event_id` | string | Unique UUID for this event instance |
| `timestamp` | string | ISO 8601 timestamp with timezone (UTC) |
| `run_id` | string | Orchestrator run ID for correlation (optional) |

---

## HMAC Signature Verification

When a webhook is configured with a `secret`, Claude Task Master signs all payloads using HMAC-SHA256. This allows you to verify that webhooks are genuinely from your Claude Task Master instance.

### Signature Format

Two signature headers are provided:

1. **`X-Webhook-Signature`** - Signs the payload only (for backward compatibility)
2. **`X-Webhook-Signature-256`** - Signs `timestamp.payload` (recommended, provides replay protection)

Both signatures use the format: `sha256=<hex_digest>`

### Verification Algorithm

To verify a webhook signature (recommended method using `X-Webhook-Signature-256`):

1. Extract the timestamp from the `X-Webhook-Timestamp` header
2. Construct the signed payload: `timestamp + "." + raw_json_body`
3. Compute HMAC-SHA256 of the signed payload using your shared secret
4. Compare the computed signature with the `X-Webhook-Signature-256` header using constant-time comparison
5. Optionally, reject requests with timestamps older than 5 minutes to prevent replay attacks

### Python Example

```python
import hmac
import hashlib
import time

def verify_webhook_signature(
    payload: bytes,
    timestamp: str,
    signature_header: str,
    secret: str,
    max_age_seconds: int = 300
) -> bool:
    """Verify webhook signature and timestamp.

    Args:
        payload: Raw request body bytes
        timestamp: Value from X-Webhook-Timestamp header
        signature_header: Value from X-Webhook-Signature-256 header
        secret: Your shared secret
        max_age_seconds: Maximum age for timestamp (default 5 minutes)

    Returns:
        True if signature is valid and timestamp is recent
    """
    # Check timestamp freshness (prevent replay attacks)
    try:
        event_time = int(timestamp)
        current_time = int(time.time())
        if abs(current_time - event_time) > max_age_seconds:
            return False
    except ValueError:
        return False

    # Construct signed payload
    signed_payload = f"{timestamp}.".encode() + payload

    # Compute expected signature
    expected_signature = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256
    ).hexdigest()

    # Extract provided signature (remove "sha256=" prefix)
    if signature_header.startswith("sha256="):
        provided_signature = signature_header[7:]
    else:
        provided_signature = signature_header

    # Constant-time comparison (prevent timing attacks)
    return hmac.compare_digest(expected_signature, provided_signature)
```

### Node.js Example

```javascript
const crypto = require('crypto');

function verifyWebhookSignature(payload, timestamp, signatureHeader, secret, maxAgeSeconds = 300) {
    // Check timestamp freshness
    const eventTime = parseInt(timestamp);
    const currentTime = Math.floor(Date.now() / 1000);
    if (Math.abs(currentTime - eventTime) > maxAgeSeconds) {
        return false;
    }

    // Construct signed payload
    const signedPayload = `${timestamp}.${payload}`;

    // Compute expected signature
    const expectedSignature = crypto
        .createHmac('sha256', secret)
        .update(signedPayload)
        .digest('hex');

    // Extract provided signature (remove "sha256=" prefix)
    const providedSignature = signatureHeader.startsWith('sha256=')
        ? signatureHeader.slice(7)
        : signatureHeader;

    // Constant-time comparison
    return crypto.timingSafeEqual(
        Buffer.from(expectedSignature, 'hex'),
        Buffer.from(providedSignature, 'hex')
    );
}
```

### Go Example

```go
package main

import (
    "crypto/hmac"
    "crypto/sha256"
    "crypto/subtle"
    "encoding/hex"
    "fmt"
    "strconv"
    "strings"
    "time"
)

func verifyWebhookSignature(payload []byte, timestamp, signatureHeader, secret string, maxAgeSeconds int) bool {
    // Check timestamp freshness
    eventTime, err := strconv.ParseInt(timestamp, 10, 64)
    if err != nil {
        return false
    }
    currentTime := time.Now().Unix()
    if abs(currentTime - eventTime) > int64(maxAgeSeconds) {
        return false
    }

    // Construct signed payload
    signedPayload := fmt.Sprintf("%s.%s", timestamp, payload)

    // Compute expected signature
    mac := hmac.New(sha256.New, []byte(secret))
    mac.Write([]byte(signedPayload))
    expectedSignature := hex.EncodeToString(mac.Sum(nil))

    // Extract provided signature (remove "sha256=" prefix)
    providedSignature := strings.TrimPrefix(signatureHeader, "sha256=")

    // Constant-time comparison
    return subtle.ConstantTimeCompare(
        []byte(expectedSignature),
        []byte(providedSignature),
    ) == 1
}

func abs(n int64) int64 {
    if n < 0 {
        return -n
    }
    return n
}
```

---

## HTTP Headers

All webhook requests include the following headers:

| Header | Description | Example |
|--------|-------------|---------|
| `Content-Type` | Always `application/json` | `application/json` |
| `X-Webhook-Timestamp` | Unix timestamp when event was generated | `1705594510` |
| `X-Webhook-Event` | Event type | `task.completed` |
| `X-Webhook-Delivery-Id` | Unique identifier for this delivery attempt | `550e8400-e29b-41d4-a716-446655440000` |
| `X-Webhook-Signature` | HMAC-SHA256 of payload (if secret configured) | `sha256=abc123...` |
| `X-Webhook-Signature-256` | HMAC-SHA256 of timestamp+payload (if secret configured) | `sha256=def456...` |
| Custom headers | Any headers configured in webhook settings | - |

---

## Event Payloads

### Task Events

#### task.started

Emitted when the orchestrator begins working on a task.

```json
{
  "event_type": "task.started",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-18T15:45:10.123456Z",
  "run_id": "run_20240118_143022",

  "task_index": 3,
  "task_description": "Add dark mode toggle to settings",
  "total_tasks": 10,
  "branch": "feat/dark-mode",
  "pr_group": "UI Enhancements"
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `task_index` | integer | Zero-based index of the task in the plan |
| `task_description` | string | Human-readable description of the task |
| `total_tasks` | integer | Total number of tasks in the plan |
| `branch` | string | Git branch name being used (optional) |
| `pr_group` | string | PR group name if task is part of a group (optional) |

#### task.completed

Emitted when a task completes successfully.

```json
{
  "event_type": "task.completed",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-18T15:47:15.123456Z",
  "run_id": "run_20240118_143022",

  "task_index": 3,
  "task_description": "Add dark mode toggle to settings",
  "total_tasks": 10,
  "completed_tasks": 4,
  "duration_seconds": 125.5,
  "commit_hash": "abc123def456789",
  "branch": "feat/dark-mode",
  "pr_group": "UI Enhancements"
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `task_index` | integer | Zero-based index of the completed task |
| `task_description` | string | Human-readable description of the task |
| `total_tasks` | integer | Total number of tasks in the plan |
| `completed_tasks` | integer | Number of tasks completed so far (including this one) |
| `duration_seconds` | float | Time taken to complete the task in seconds (optional) |
| `commit_hash` | string | Git commit hash if changes were committed (optional) |
| `branch` | string | Git branch name (optional) |
| `pr_group` | string | PR group name if task is part of a group (optional) |

#### task.failed

Emitted when a task fails with an error.

```json
{
  "event_type": "task.failed",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-18T15:46:30.123456Z",
  "run_id": "run_20240118_143022",

  "task_index": 3,
  "task_description": "Add dark mode toggle to settings",
  "error_message": "Tests failed: 2 failures in test_settings.py",
  "error_type": "test_failure",
  "duration_seconds": 45.2,
  "branch": "feat/dark-mode",
  "pr_group": "UI Enhancements",
  "recoverable": true
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `task_index` | integer | Zero-based index of the failed task |
| `task_description` | string | Human-readable description of the task |
| `error_message` | string | Description of the failure |
| `error_type` | string | Type/classification of the error (optional) |
| `duration_seconds` | float | Time elapsed before failure in seconds (optional) |
| `branch` | string | Git branch name (optional) |
| `pr_group` | string | PR group name if task is part of a group (optional) |
| `recoverable` | boolean | Whether the error is potentially recoverable (default: true) |

### Pull Request Events

#### pr.created

Emitted when a pull request is created.

```json
{
  "event_type": "pr.created",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-18T15:50:00.123456Z",
  "run_id": "run_20240118_143022",

  "pr_number": 42,
  "pr_url": "https://github.com/owner/repo/pull/42",
  "pr_title": "Add dark mode support",
  "branch": "feat/dark-mode",
  "base_branch": "main",
  "tasks_included": 5,
  "pr_group": "UI Enhancements",
  "repository": "owner/repo"
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pr_number` | integer | The pull request number |
| `pr_url` | string | URL to the pull request |
| `pr_title` | string | Title of the pull request |
| `branch` | string | Source branch name |
| `base_branch` | string | Target branch name (usually "main" or "master") |
| `tasks_included` | integer | Number of tasks included in this PR |
| `pr_group` | string | PR group name (optional) |
| `repository` | string | Repository name in owner/repo format (optional) |

#### pr.merged

Emitted when a pull request is merged.

```json
{
  "event_type": "pr.merged",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-18T16:00:00.123456Z",
  "run_id": "run_20240118_143022",

  "pr_number": 42,
  "pr_url": "https://github.com/owner/repo/pull/42",
  "pr_title": "Add dark mode support",
  "branch": "feat/dark-mode",
  "base_branch": "main",
  "merge_commit_hash": "def789abc456123",
  "merged_at": "2024-01-18T16:00:00.123456Z",
  "pr_group": "UI Enhancements",
  "repository": "owner/repo",
  "auto_merged": true
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pr_number` | integer | The pull request number |
| `pr_url` | string | URL to the pull request |
| `pr_title` | string | Title of the pull request |
| `branch` | string | Source branch that was merged |
| `base_branch` | string | Target branch that received the merge |
| `merge_commit_hash` | string | The merge commit hash (optional) |
| `merged_at` | string | ISO 8601 timestamp when the PR was merged (optional) |
| `pr_group` | string | PR group name (optional) |
| `repository` | string | Repository name in owner/repo format (optional) |
| `auto_merged` | boolean | Whether this was an auto-merge (default: false) |

### Session Events

#### session.started

Emitted when a work session (Claude Agent SDK query) begins.

```json
{
  "event_type": "session.started",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-18T15:45:15.123456Z",
  "run_id": "run_20240118_143022",

  "session_number": 5,
  "max_sessions": 10,
  "task_index": 3,
  "task_description": "Add dark mode toggle to settings",
  "phase": "working"
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_number` | integer | Current session number (1-indexed) |
| `max_sessions` | integer | Maximum allowed sessions (optional, null if unlimited) |
| `task_index` | integer | Index of the task being worked on |
| `task_description` | string | Description of the current task |
| `phase` | string | Current phase: "planning", "working", or "verification" |

#### session.completed

Emitted when a work session completes.

```json
{
  "event_type": "session.completed",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-18T15:46:45.123456Z",
  "run_id": "run_20240118_143022",

  "session_number": 5,
  "max_sessions": 10,
  "task_index": 3,
  "task_description": "Add dark mode toggle to settings",
  "phase": "working",
  "duration_seconds": 90.5,
  "result": "success",
  "tools_used": 12,
  "tokens_used": 8500
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_number` | integer | Session number that completed |
| `max_sessions` | integer | Maximum allowed sessions (optional) |
| `task_index` | integer | Index of the task being worked on |
| `task_description` | string | Description of the task |
| `phase` | string | Phase that was completed |
| `duration_seconds` | float | Duration of the session in seconds (optional) |
| `result` | string | Outcome: "success", "blocked", "failed", etc. |
| `tools_used` | integer | Number of tool invocations in this session |
| `tokens_used` | integer | Total tokens consumed (optional) |

---

## Delivery and Retry Behavior

### Retry Logic

Claude Task Master automatically retries failed webhook deliveries using exponential backoff:

- **Retryable status codes:** 429 (Too Many Requests), 500, 502, 503, 504
- **Non-retryable status codes:** All other 4xx errors (except 429)
- **Success status codes:** All 2xx status codes
- **Timeout errors:** Retried based on `max_retries` configuration
- **Connection errors:** Retried based on `max_retries` configuration

### Backoff Strategy

Retry delays use exponential backoff with a cap:

- **1st retry:** 1 second delay
- **2nd retry:** 2 seconds delay
- **3rd retry:** 4 seconds delay
- **Maximum delay:** 30 seconds

### Timeout Configuration

Each webhook request has a configurable timeout (default: 30 seconds). Your endpoint should:
- Respond within the configured timeout
- Return a 2xx status code quickly (process asynchronously if needed)
- Avoid long-running operations in the webhook handler

### Expected Response

Your webhook endpoint should:
- Return a 2xx status code (200, 201, 202, 204) for successful receipt
- Return quickly (< 5 seconds recommended)
- Process the webhook asynchronously if needed
- Return 429 if rate-limited (will be retried)
- Return 5xx for server errors (will be retried)

Example successful response:

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "received": true,
  "event_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

## Configuration Examples

This section provides ready-to-use webhook configurations for popular services.

### Slack Incoming Webhooks

Slack's Incoming Webhooks allow you to post messages directly to Slack channels. However, Slack webhooks expect a specific JSON format, so you'll need an intermediate transformation service (see [Integration Examples](#integration-examples) below).

**Step 1: Create Slack Incoming Webhook**

1. Go to your Slack workspace settings
2. Navigate to "Apps" → "Incoming Webhooks"
3. Click "Add to Slack" and select a channel
4. Copy the webhook URL (example format: `https://hooks.slack.com/services/YOUR_TEAM_ID/YOUR_CHANNEL_ID/YOUR_TOKEN`)

**Step 2: Set up transformation service**

Since Claude Task Master sends a different payload format than Slack expects, deploy a transformation service (see example in [Integration Examples](#integration-examples)) or use a service like Zapier/n8n.

**Step 3: Configure Claude Task Master webhook**

Point to your transformation service:

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://your-transform-service.com/slack-webhook",
    "name": "Slack Notifications",
    "description": "Send task updates to #dev-notifications channel",
    "events": ["task.completed", "task.failed", "pr.created"],
    "timeout": 10.0,
    "max_retries": 3,
    "verify_ssl": true
  }'
```

**Alternative: Direct Slack webhook with custom formatting**

If you use a transformation service that accepts Claude Task Master payloads and forwards to Slack, configure it like this:

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://your-transformer.com/webhook/slack",
    "secret": "shared-secret-with-transformer",
    "name": "Slack via Transformer",
    "events": ["task.completed", "task.failed", "pr.created", "pr.merged"],
    "headers": {
      "X-Slack-Channel": "#dev-notifications",
      "X-Slack-Webhook-URL": "https://hooks.slack.com/services/YOUR_TEAM_ID/YOUR_CHANNEL_ID/YOUR_TOKEN"
    }
  }'
```

### Discord Webhooks

Discord webhooks natively accept JSON payloads, but like Slack, require a specific format. You'll need a transformation service.

**Step 1: Create Discord Webhook**

1. Open your Discord server settings
2. Go to "Integrations" → "Webhooks"
3. Click "New Webhook"
4. Set the name and channel
5. Copy the webhook URL (example format: `https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN`)

**Step 2: Configure transformation service**

Deploy a service that transforms Claude Task Master events to Discord's embed format (see [Integration Examples](#integration-examples)).

**Step 3: Configure Claude Task Master webhook**

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://your-transform-service.com/discord-webhook",
    "name": "Discord Notifications",
    "description": "Send updates to #task-updates channel",
    "events": ["task.completed", "task.failed", "pr.created", "pr.merged"],
    "timeout": 10.0,
    "max_retries": 3,
    "verify_ssl": true,
    "headers": {
      "X-Discord-Webhook-URL": "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"
    }
  }'
```

### Microsoft Teams

Microsoft Teams uses Incoming Webhooks with a card-based format.

**Step 1: Create Teams Incoming Webhook**

1. In your Teams channel, click "..." → "Connectors"
2. Search for "Incoming Webhook" and click "Configure"
3. Name your webhook and optionally add an image
4. Copy the webhook URL

**Step 2: Configure Claude Task Master webhook**

Point to your transformation service:

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://your-transform-service.com/teams-webhook",
    "name": "Microsoft Teams Notifications",
    "description": "Send task updates to Teams channel",
    "events": ["task.completed", "task.failed", "pr.created"],
    "timeout": 15.0,
    "headers": {
      "X-Teams-Webhook-URL": "https://outlook.office.com/webhook/..."
    }
  }'
```

### Custom HTTP Endpoint

For custom applications that can directly consume Claude Task Master webhook payloads.

**Basic Configuration:**

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://api.myapp.com/webhooks/claude-task-master",
    "secret": "generate-strong-random-secret-here",
    "name": "Custom Application",
    "description": "Send all events to internal monitoring system",
    "events": null,
    "enabled": true,
    "timeout": 30.0,
    "max_retries": 3,
    "verify_ssl": true
  }'
```

**With Custom Headers:**

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://api.myapp.com/webhooks/events",
    "secret": "your-webhook-secret",
    "name": "Production API",
    "description": "Send events to production monitoring API",
    "events": ["task.completed", "task.failed", "pr.merged"],
    "timeout": 20.0,
    "max_retries": 5,
    "verify_ssl": true,
    "headers": {
      "X-API-Key": "your-api-key",
      "X-Environment": "production",
      "X-Source": "claude-task-master"
    }
  }'
```

**Development/Testing Configuration:**

For local development, you might want to disable SSL verification and use ngrok:

```bash
# Start ngrok
ngrok http 3000

# Configure webhook with ngrok URL
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://abc123.ngrok.io/webhook",
    "secret": "test-secret-123",
    "name": "Local Development",
    "description": "Testing webhooks locally",
    "events": null,
    "timeout": 30.0,
    "verify_ssl": true
  }'
```

### PagerDuty Integration

PagerDuty can receive webhook events to trigger incidents.

**Configuration:**

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://your-transform-service.com/pagerduty-webhook",
    "secret": "pagerduty-webhook-secret",
    "name": "PagerDuty Alerts",
    "description": "Trigger incidents for failed tasks",
    "events": ["task.failed"],
    "timeout": 10.0,
    "max_retries": 3,
    "headers": {
      "X-PagerDuty-Integration-Key": "your-integration-key"
    }
  }'
```

### Datadog Event Tracking

Send events to Datadog for monitoring and analytics.

**Configuration:**

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://your-transform-service.com/datadog-webhook",
    "secret": "datadog-webhook-secret",
    "name": "Datadog Events",
    "description": "Track task execution metrics in Datadog",
    "events": ["task.completed", "task.failed", "session.completed"],
    "timeout": 15.0,
    "headers": {
      "X-Datadog-API-Key": "your-datadog-api-key",
      "X-Datadog-App-Key": "your-datadog-app-key"
    }
  }'
```

### Webhook.site (Testing)

For quick testing without setting up a server:

**Step 1: Get a unique URL**

1. Go to [https://webhook.site](https://webhook.site)
2. Copy the unique URL displayed

**Step 2: Configure webhook**

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://webhook.site/your-unique-id",
    "name": "Webhook.site Testing",
    "description": "Testing webhook payloads",
    "events": null,
    "timeout": 30.0
  }'
```

**Step 3: Trigger events and view on webhook.site**

You'll see all webhook payloads with full headers and body in real-time.

### Multiple Webhooks Example

You can configure multiple webhooks for different purposes:

```bash
# Webhook 1: Slack for all task events
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://transform.example.com/slack",
    "name": "Slack - Task Updates",
    "events": ["task.started", "task.completed", "task.failed"]
  }'

# Webhook 2: PagerDuty for failures only
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://transform.example.com/pagerduty",
    "name": "PagerDuty - Failures",
    "events": ["task.failed"]
  }'

# Webhook 3: Database logger for everything
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://api.internal.com/webhook-logger",
    "secret": "internal-secret",
    "name": "Event Logger",
    "events": null
  }'

# Webhook 4: GitHub integration for PR events
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://api.internal.com/github-sync",
    "secret": "github-sync-secret",
    "name": "GitHub PR Sync",
    "events": ["pr.created", "pr.merged"]
  }'
```

### Environment-Based Configuration

**Production:**

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${CLAUDETM_PASSWORD}" \
  -d '{
    "url": "https://api.production.com/webhooks/claudetm",
    "secret": "'"${WEBHOOK_SECRET}"'",
    "name": "Production Monitor",
    "events": ["task.completed", "task.failed", "pr.created", "pr.merged"],
    "timeout": 30.0,
    "max_retries": 5,
    "verify_ssl": true,
    "headers": {
      "X-Environment": "production",
      "X-API-Key": "'"${PROD_API_KEY}"'"
    }
  }'
```

**Staging:**

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${CLAUDETM_PASSWORD}" \
  -d '{
    "url": "https://api.staging.com/webhooks/claudetm",
    "secret": "'"${WEBHOOK_SECRET}"'",
    "name": "Staging Monitor",
    "events": null,
    "timeout": 20.0,
    "max_retries": 3,
    "verify_ssl": true,
    "headers": {
      "X-Environment": "staging"
    }
  }'
```

---

## Integration Examples

### Slack Notification

Using Slack's Incoming Webhooks:

```python
# Configure webhook in Claude Task Master
POST /webhooks
{
  "url": "https://hooks.slack.com/services/YOUR_TEAM_ID/YOUR_CHANNEL_ID/YOUR_TOKEN",
  "events": ["task.completed", "task.failed", "pr.created"],
  "name": "Slack Notifications"
}
```

Transform webhook payload to Slack format (intermediate service):

```python
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook_handler():
    event = request.json

    # Transform to Slack message format
    if event['event_type'] == 'task.completed':
        message = {
            "text": f"✅ Task completed: {event['task_description']}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Task Completed*\n{event['task_description']}\n\n"
                                f"• Progress: {event['completed_tasks']}/{event['total_tasks']}\n"
                                f"• Duration: {event['duration_seconds']:.1f}s\n"
                                f"• Commit: `{event['commit_hash'][:7]}`"
                    }
                }
            ]
        }
    elif event['event_type'] == 'task.failed':
        message = {
            "text": f"❌ Task failed: {event['task_description']}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Task Failed*\n{event['task_description']}\n\n"
                                f"• Error: {event['error_message']}"
                    }
                }
            ]
        }

    # Forward to Slack
    requests.post(SLACK_WEBHOOK_URL, json=message)

    return jsonify({"received": True}), 200
```

### Discord Notification

Using Discord Webhooks:

```python
import requests
from datetime import datetime

@app.route('/webhook', methods=['POST'])
def discord_webhook():
    event = request.json

    # Color based on event type
    colors = {
        'task.completed': 0x00ff00,  # Green
        'task.failed': 0xff0000,      # Red
        'pr.created': 0x0099ff,       # Blue
    }

    embed = {
        "embeds": [{
            "title": event['task_description'],
            "description": f"Event: `{event['event_type']}`",
            "color": colors.get(event['event_type'], 0x888888),
            "timestamp": event['timestamp'],
            "fields": [
                {
                    "name": "Progress",
                    "value": f"{event.get('completed_tasks', 0)}/{event.get('total_tasks', 0)}",
                    "inline": True
                },
                {
                    "name": "Branch",
                    "value": event.get('branch', 'N/A'),
                    "inline": True
                }
            ]
        }]
    }

    requests.post(DISCORD_WEBHOOK_URL, json=embed)
    return jsonify({"received": True}), 200
```

### Custom Database Logger

Log all events to a database:

```python
from flask import Flask, request, jsonify
from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import hmac
import hashlib

app = Flask(__name__)
Base = declarative_base()
engine = create_engine('postgresql://user:pass@localhost/events')
Session = sessionmaker(bind=engine)

class WebhookEvent(Base):
    __tablename__ = 'webhook_events'

    id = Column(Integer, primary_key=True)
    event_id = Column(String, unique=True, nullable=False)
    event_type = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    run_id = Column(String)
    payload = Column(JSON, nullable=False)

@app.route('/webhook', methods=['POST'])
def log_webhook():
    # Verify signature
    signature = request.headers.get('X-Webhook-Signature-256')
    timestamp = request.headers.get('X-Webhook-Timestamp')

    if not verify_webhook_signature(
        request.data, timestamp, signature, SECRET
    ):
        return jsonify({"error": "Invalid signature"}), 401

    # Parse and store event
    event = request.json

    db_session = Session()
    try:
        webhook_event = WebhookEvent(
            event_id=event['event_id'],
            event_type=event['event_type'],
            timestamp=event['timestamp'],
            run_id=event.get('run_id'),
            payload=event
        )
        db_session.add(webhook_event)
        db_session.commit()
    finally:
        db_session.close()

    return jsonify({"received": True}), 200
```

---

## Testing Webhooks

### Using the Test Endpoint

Test a configured webhook:

```bash
curl -X POST http://localhost:8000/webhooks/test \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "webhook_id": "wh_a1b2c3d4_e5f6g7h8"
  }'
```

Test a URL directly without creating a webhook:

```bash
curl -X POST http://localhost:8000/webhooks/test \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://example.com/webhook",
    "secret": "test-secret"
  }'
```

The test sends a payload with `event_type: "webhook.test"`:

```json
{
  "event_type": "webhook.test",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-18T15:45:10.123456Z",
  "message": "This is a test webhook from Claude Task Master",
  "test": true
}
```

### Local Testing with webhook.site

For quick testing without setting up a server:

1. Go to [webhook.site](https://webhook.site)
2. Copy the unique URL provided
3. Create a webhook with that URL
4. Send a test webhook
5. View the received payload on webhook.site

### Local Testing with ngrok

For testing against your local development server:

```bash
# Start ngrok tunnel
ngrok http 3000

# Use the ngrok URL in your webhook configuration
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://abc123.ngrok.io/webhook",
    "secret": "test-secret"
  }'
```

---

## Security Best Practices

### 1. Always Use HTTPS

Configure webhooks with HTTPS URLs to ensure payloads are encrypted in transit:

```json
{
  "url": "https://example.com/webhook",  // ✅ Good
  "verify_ssl": true
}
```

Avoid HTTP for production:

```json
{
  "url": "http://example.com/webhook",  // ❌ Insecure
}
```

### 2. Verify HMAC Signatures

Always verify webhook signatures to ensure authenticity:

```python
def handle_webhook(request):
    # Verify signature before processing
    if not verify_webhook_signature(
        request.data,
        request.headers.get('X-Webhook-Timestamp'),
        request.headers.get('X-Webhook-Signature-256'),
        SECRET
    ):
        return {"error": "Invalid signature"}, 401

    # Process webhook...
```

### 3. Implement Timestamp Validation

Reject webhooks with old timestamps to prevent replay attacks:

```python
MAX_AGE_SECONDS = 300  # 5 minutes

def is_timestamp_valid(timestamp: str) -> bool:
    try:
        event_time = int(timestamp)
        current_time = int(time.time())
        return abs(current_time - event_time) <= MAX_AGE_SECONDS
    except ValueError:
        return False
```

### 4. Use Strong Secrets

Generate cryptographically secure random secrets:

```python
import secrets

# Generate a secure 32-byte secret
webhook_secret = secrets.token_urlsafe(32)
print(webhook_secret)  # Use this as your webhook secret
```

### 5. Rate Limiting

Implement rate limiting on your webhook endpoint:

```python
from flask_limiter import Limiter

limiter = Limiter(app, key_func=lambda: request.remote_addr)

@app.route('/webhook', methods=['POST'])
@limiter.limit("60 per minute")
def webhook_handler():
    # Process webhook...
```

### 6. Idempotency

Handle duplicate deliveries gracefully using the `event_id`:

```python
def handle_webhook(request):
    event = request.json
    event_id = event['event_id']

    # Check if already processed
    if event_already_processed(event_id):
        return {"received": True, "duplicate": True}, 200

    # Process and mark as processed
    process_event(event)
    mark_as_processed(event_id)

    return {"received": True}, 200
```

### 7. Asynchronous Processing

Process webhooks asynchronously to respond quickly:

```python
from celery import Celery

celery = Celery('tasks', broker='redis://localhost:6379')

@celery.task
def process_webhook_async(event_data):
    # Long-running processing here
    pass

@app.route('/webhook', methods=['POST'])
def webhook_handler():
    # Verify signature first
    if not verify_signature(...):
        return {"error": "Invalid signature"}, 401

    # Queue for async processing
    process_webhook_async.delay(request.json)

    # Return immediately
    return {"received": True}, 202
```

---

## Troubleshooting

### Webhooks Not Being Delivered

**Check webhook is enabled:**

```bash
curl http://localhost:8000/webhooks \
  -H "Authorization: Bearer mypassword"
```

Ensure `"enabled": true` in the response.

**Check event filter:**

If the webhook has specific `events` configured, verify the event type is included:

```json
{
  "events": ["task.completed", "pr.created"]  // Will only receive these events
}
```

Use `"events": null` or `[]` to receive all events.

**Check logs:**

View the Claude Task Master logs for webhook delivery errors:

```bash
curl http://localhost:8000/logs?tail=100 \
  -H "Authorization: Bearer mypassword"
```

### Signature Verification Failing

**Ensure you're using the raw request body:**

```python
# ✅ Correct - use raw bytes
signature_valid = verify_signature(request.data, ...)

# ❌ Wrong - don't use parsed JSON
signature_valid = verify_signature(request.json, ...)
```

**Check secret matches:**

Ensure the secret used in verification matches the one configured in the webhook.

**Verify using X-Webhook-Signature-256:**

Use the timestamp-based signature for better security:

```python
# ✅ Recommended
signature = request.headers.get('X-Webhook-Signature-256')
timestamp = request.headers.get('X-Webhook-Timestamp')
verify_webhook_signature(payload, timestamp, signature, secret)

# ⚠️ Less secure (no replay protection)
signature = request.headers.get('X-Webhook-Signature')
verify_simple_signature(payload, signature, secret)
```

### Delivery Timeouts

**Increase timeout:**

```bash
curl -X PUT http://localhost:8000/webhooks/{webhook_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{"timeout": 60.0}'
```

**Process asynchronously:**

Ensure your webhook endpoint returns quickly (< 5 seconds) and processes payloads asynchronously.

### SSL Certificate Errors

For development/testing with self-signed certificates:

```bash
curl -X PUT http://localhost:8000/webhooks/{webhook_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{"verify_ssl": false}'
```

**⚠️ Never disable SSL verification in production.**

### Testing Event Delivery

Monitor your endpoint to see what's being received:

```python
@app.route('/webhook', methods=['POST'])
def debug_webhook():
    print("Headers:", dict(request.headers))
    print("Body:", request.data.decode())
    return {"received": True}, 200
```

---

## See Also

- [REST API Reference](./api-reference.md) - Complete API documentation including webhook endpoints
- [Authentication Guide](./authentication.md) - Securing your Claude Task Master instance
- [Docker Guide](./docker.md) - Running Claude Task Master in containers

---

**Questions or Issues?**

Visit the [GitHub repository](https://github.com/developerz-ai/claude-task-master) to report issues or contribute improvements.
