# REST API Reference

This document provides a comprehensive reference for the Claude Task Master REST API. The API provides programmatic access to task orchestration, status monitoring, and webhook management.

## Table of Contents

- [Overview](#overview)
- [Authentication](#authentication)
- [Base URL](#base-url)
- [Response Format](#response-format)
- [Error Handling](#error-handling)
- [Endpoints](#endpoints)
  - [Info Endpoints](#info-endpoints)
  - [Control Endpoints](#control-endpoints)
  - [Task Management Endpoints](#task-management-endpoints)
  - [Webhook Endpoints](#webhook-endpoints)

---

## Overview

The Claude Task Master REST API is built on FastAPI and provides:

- **Task Status Monitoring** - Get real-time status, progress, logs, and context
- **Task Control** - Stop, resume, and configure running tasks
- **Task Lifecycle Management** - Initialize and delete tasks
- **Webhook Management** - Configure webhook notifications for task events
- **Health Checks** - Monitor server health and uptime

All endpoints return JSON responses and follow RESTful conventions.

---

## Authentication

When authentication is enabled via the `CLAUDETM_PASSWORD` environment variable or `--password` CLI flag, all endpoints (except `/health`) require authentication using the `Authorization` header with a Bearer token:

```bash
Authorization: Bearer YOUR_PASSWORD
```

### Example Authenticated Request

```bash
curl -H "Authorization: Bearer mypassword" \
  http://localhost:8000/status
```

See [Authentication Guide](./authentication.md) for detailed information.

---

## Base URL

The default base URL when running the server locally is:

```
http://localhost:8000
```

You can change the port using the `--port` flag:

```bash
claudetm-api --port 9000
```

---

## Response Format

### Success Response

All successful responses include a `success: true` field along with the requested data:

```json
{
  "success": true,
  "data": { ... }
}
```

### Error Response

All error responses follow a consistent format:

```json
{
  "success": false,
  "error": "error_code",
  "message": "Human-readable error message",
  "detail": "Additional error details (optional)",
  "suggestion": "Suggested action to resolve (optional)"
}
```

**HTTP Status Codes:**

- `200 OK` - Request succeeded
- `201 Created` - Resource created successfully
- `400 Bad Request` - Invalid request or operation not allowed
- `404 Not Found` - Resource not found
- `409 Conflict` - Resource conflict (e.g., duplicate)
- `500 Internal Server Error` - Server error

---

## Error Handling

### Common Error Codes

| Error Code | Description | Common Cause |
|------------|-------------|--------------|
| `not_found` | Resource not found | No active task, missing file |
| `task_exists` | Task already exists | Attempting to init when task exists |
| `invalid_operation` | Operation not allowed | Task in wrong state for operation |
| `invalid_request` | Bad request data | Missing required fields, invalid values |
| `invalid_configuration` | Invalid config value | Invalid option value in update |
| `duplicate_webhook` | Webhook already exists | URL already configured |
| `internal_error` | Server error | Unexpected error during processing |
| `credentials_error` | Auth failure | Invalid or missing Claude credentials |

---

## Endpoints

### Info Endpoints

Read-only endpoints that provide information about the current task state.

#### `GET /status`

Get comprehensive status information about the current task.

**Response:** `TaskStatusResponse`

```json
{
  "success": true,
  "goal": "Add dark mode support to the application",
  "status": "working",
  "model": "opus",
  "current_task_index": 3,
  "session_count": 5,
  "run_id": "run_20240118_143022",
  "current_pr": 42,
  "workflow_stage": "pr_created",
  "options": {
    "auto_merge": true,
    "max_sessions": 10,
    "pause_on_pr": false,
    "enable_checkpointing": false,
    "log_level": "normal",
    "log_format": "text",
    "pr_per_task": false
  },
  "created_at": "2024-01-18T14:30:22Z",
  "updated_at": "2024-01-18T15:45:10Z",
  "tasks": {
    "completed": 3,
    "total": 10,
    "progress": "3/10"
  },
  "webhooks": {
    "total": 2,
    "enabled": 2,
    "disabled": 0
  }
}
```

**Status Values:**

- `planning` - Task is in planning phase
- `working` - Task is actively executing
- `blocked` - Task is blocked (needs intervention)
- `paused` - Task is paused
- `stopped` - Task has been stopped
- `success` - Task completed successfully
- `failed` - Task failed with error

**Workflow Stages:**

- `working` - Actively working on tasks
- `pr_created` - Pull request created
- `waiting_ci` - Waiting for CI checks
- `ci_failed` - CI checks failed
- `waiting_reviews` - Waiting for code reviews
- `addressing_reviews` - Addressing review feedback
- `ready_to_merge` - PR approved and ready
- `merged` - PR has been merged

**Error Responses:**

- `404 Not Found` - No active task

---

#### `GET /plan`

Get the current task plan with markdown checkboxes.

**Response:** `PlanResponse`

```json
{
  "success": true,
  "plan": "# Task Plan\n\n- [x] Task 1: Setup authentication\n- [ ] Task 2: Add webhooks\n..."
}
```

**Error Responses:**

- `404 Not Found` - No active task or plan not yet created

---

#### `GET /logs`

Get log content from the current run.

**Query Parameters:**

- `tail` (optional) - Number of lines to return from end of log (default: 100, max: 10000)

**Response:** `LogsResponse`

```json
{
  "success": true,
  "log_content": "[14:30:22] Starting task execution...\n[14:30:25] Running tests...\n...",
  "log_file": "/path/to/.claude-task-master/logs/run_20240118_143022.txt"
}
```

**Example:**

```bash
# Get last 50 lines
curl http://localhost:8000/logs?tail=50
```

**Error Responses:**

- `404 Not Found` - No active task or log file

---

#### `GET /progress`

Get human-readable progress summary.

**Response:** `ProgressResponse`

```json
{
  "success": true,
  "progress": "## Progress Summary\n\nCompleted:\n- Setup auth module\n- Added tests\n\nRemaining:\n- Add webhooks\n..."
}
```

**Error Responses:**

- `404 Not Found` - No active task

---

#### `GET /context`

Get accumulated context and learnings.

**Response:** `ContextResponse`

```json
{
  "success": true,
  "context": "## Key Learnings\n\n- Project uses pytest for testing\n- Auth module requires passlib[bcrypt]\n..."
}
```

**Error Responses:**

- `404 Not Found` - No active task

---

#### `GET /health`

Health check endpoint for monitoring and load balancers.

**Authentication:** Not required (always accessible)

**Response:** `HealthResponse`

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "server_name": "claude-task-master-api",
  "uptime_seconds": 3600.5,
  "active_tasks": 1,
  "timestamp": "2024-01-18T15:45:10Z"
}
```

**Health Status Values:**

- `healthy` - Server is operating normally
- `degraded` - Server is running but task is blocked/failed
- `unhealthy` - Server has critical issues

---

### Control Endpoints

Endpoints for runtime control of task execution.

#### `POST /control/stop`

Stop a running task with optional cleanup.

**Request Body:** `StopRequest`

```json
{
  "reason": "Manual stop for review",
  "cleanup": false
}
```

**Parameters:**

- `reason` (optional) - Reason for stopping
- `cleanup` (optional) - If true, delete state files (default: false)

**Response:** `ControlResponse`

```json
{
  "success": true,
  "message": "Task stopped successfully",
  "operation": "stop",
  "previous_status": "working",
  "new_status": "stopped",
  "details": {
    "cleanup_performed": false
  }
}
```

**Error Responses:**

- `404 Not Found` - No active task
- `400 Bad Request` - Task cannot be stopped in current state

---

#### `POST /control/resume`

Resume a paused or blocked task.

**Request Body:** `ResumeRequest`

```json
{
  "reason": "Issue resolved, continuing work"
}
```

**Parameters:**

- `reason` (optional) - Reason for resuming

**Response:** `ControlResponse`

```json
{
  "success": true,
  "message": "Task resumed successfully",
  "operation": "resume",
  "previous_status": "paused",
  "new_status": "working"
}
```

**Error Responses:**

- `404 Not Found` - No active task
- `400 Bad Request` - Task cannot be resumed in current state

---

#### `PATCH /config`

Update runtime task configuration options.

**Request Body:** `ConfigUpdateRequest`

```json
{
  "auto_merge": false,
  "max_sessions": 20,
  "log_level": "verbose"
}
```

**Supported Options:**

- `auto_merge` (boolean) - Whether to auto-merge PRs when approved
- `max_sessions` (integer, 1-1000) - Maximum work sessions before pausing
- `pause_on_pr` (boolean) - Whether to pause after creating PR
- `enable_checkpointing` (boolean) - Enable state checkpointing
- `log_level` (string) - Log level: `quiet`, `normal`, `verbose`
- `log_format` (string) - Log format: `text`, `json`
- `pr_per_task` (boolean) - Create PR per task vs per group

**Note:** Only provide the fields you want to update. At least one field is required.

**Response:** `ControlResponse`

```json
{
  "success": true,
  "message": "Configuration updated successfully",
  "operation": "update_config",
  "previous_status": "working",
  "new_status": "working",
  "details": {
    "updated_fields": ["auto_merge", "max_sessions", "log_level"],
    "auto_merge": false,
    "max_sessions": 20,
    "log_level": "verbose"
  }
}
```

**Error Responses:**

- `404 Not Found` - No active task
- `400 Bad Request` - No updates provided or invalid values

---

### Task Management Endpoints

Endpoints for managing task lifecycle.

#### `POST /task/init`

Initialize a new task with the given goal and options.

**Request Body:** `TaskInitRequest`

```json
{
  "goal": "Add dark mode support to the application",
  "model": "opus",
  "auto_merge": true,
  "max_sessions": 10,
  "pause_on_pr": false
}
```

**Parameters:**

- `goal` (required, string, 1-10000 chars) - The goal to achieve
- `model` (optional, string) - Model to use: `opus`, `sonnet`, `haiku` (default: `opus`)
- `auto_merge` (optional, boolean) - Auto-merge PRs when approved (default: `true`)
- `max_sessions` (optional, integer, 1-1000) - Max sessions before pausing
- `pause_on_pr` (optional, boolean) - Pause after creating PR (default: `false`)

**Response:** `TaskInitResponse` (201 Created)

```json
{
  "success": true,
  "message": "Task initialized successfully",
  "run_id": "run_20240118_143022",
  "status": "planning"
}
```

**Error Responses:**

- `400 Bad Request` - Task already exists or invalid parameters
- `500 Internal Server Error` - Credential or initialization error

---

#### `DELETE /task`

Delete the current task and cleanup all state files.

**Warning:** This operation cannot be undone. All task state including plan, progress, context, and logs will be removed.

**Response:** `TaskDeleteResponse`

```json
{
  "success": true,
  "message": "Task deleted successfully",
  "files_removed": true
}
```

**Error Responses:**

- `404 Not Found` - No active task

---

### Webhook Endpoints

Endpoints for managing webhook configurations.

#### `GET /webhooks`

List all configured webhook endpoints.

**Response:** `WebhooksListResponse`

```json
{
  "success": true,
  "webhooks": [
    {
      "id": "wh_a1b2c3d4_e5f6g7h8",
      "url": "https://hooks.slack.com/services/xxx/yyy/zzz",
      "has_secret": true,
      "events": ["task.completed", "pr.created"],
      "enabled": true,
      "name": "Slack Notifications",
      "description": "Send task updates to #dev-notifications",
      "timeout": 30.0,
      "max_retries": 3,
      "verify_ssl": true,
      "headers": {},
      "created_at": "2024-01-18T14:30:22Z",
      "updated_at": "2024-01-18T14:30:22Z"
    }
  ],
  "total": 1
}
```

**Webhook Fields:**

- `id` - Unique webhook identifier
- `url` - Webhook endpoint URL
- `has_secret` - Whether a secret is configured (secret value is never exposed)
- `events` - List of subscribed event types (null = all events)
- `enabled` - Whether the webhook is active
- `name` - Friendly name (optional)
- `description` - Description (optional)
- `timeout` - Request timeout in seconds (1-300)
- `max_retries` - Maximum retry attempts (0-10)
- `verify_ssl` - Whether to verify SSL certificates
- `headers` - Additional HTTP headers
- `created_at` - Creation timestamp
- `updated_at` - Last update timestamp

---

#### `POST /webhooks`

Create a new webhook configuration.

**Request Body:** `WebhookCreateRequest`

```json
{
  "url": "https://hooks.slack.com/services/xxx/yyy/zzz",
  "secret": "your-webhook-secret",
  "events": ["task.completed", "pr.created"],
  "enabled": true,
  "name": "Slack Notifications",
  "description": "Send task updates to #dev-notifications",
  "timeout": 30.0,
  "max_retries": 3,
  "verify_ssl": true,
  "headers": {
    "X-Custom-Header": "value"
  }
}
```

**Parameters:**

- `url` (required) - Webhook endpoint URL (must start with http:// or https://)
- `secret` (optional) - Shared secret for HMAC-SHA256 signature generation
- `events` (optional) - Event types to subscribe to (empty/null = all events)
- `enabled` (optional) - Whether webhook is active (default: true)
- `name` (optional) - Friendly name (max 100 chars)
- `description` (optional) - Description (max 500 chars)
- `timeout` (optional) - Request timeout in seconds (1-300, default: 30)
- `max_retries` (optional) - Max retry attempts (0-10, default: 3)
- `verify_ssl` (optional) - Verify SSL certificates (default: true)
- `headers` (optional) - Additional HTTP headers

**Valid Event Types:**

- `task.started` - Task execution began
- `task.completed` - Task completed successfully
- `task.failed` - Task failed with error
- `pr.created` - Pull request created
- `pr.merged` - Pull request merged
- `session.started` - Work session began
- `session.completed` - Work session completed

**Response:** `WebhookCreateResponse` (201 Created)

```json
{
  "success": true,
  "message": "Webhook created successfully",
  "webhook": {
    "id": "wh_a1b2c3d4_e5f6g7h8",
    "url": "https://hooks.slack.com/services/xxx/yyy/zzz",
    "has_secret": true,
    "events": ["task.completed", "pr.created"],
    "enabled": true,
    "name": "Slack Notifications",
    "description": "Send task updates to #dev-notifications",
    "timeout": 30.0,
    "max_retries": 3,
    "verify_ssl": true,
    "headers": {},
    "created_at": "2024-01-18T14:30:22Z",
    "updated_at": "2024-01-18T14:30:22Z"
  }
}
```

**Error Responses:**

- `400 Bad Request` - Invalid URL or event type
- `409 Conflict` - Webhook with this URL already exists

---

#### `GET /webhooks/{webhook_id}`

Get a specific webhook configuration by ID.

**Path Parameters:**

- `webhook_id` - The webhook ID (e.g., `wh_a1b2c3d4_e5f6g7h8`)

**Response:** `WebhookResponse`

```json
{
  "id": "wh_a1b2c3d4_e5f6g7h8",
  "url": "https://hooks.slack.com/services/xxx/yyy/zzz",
  "has_secret": true,
  "events": ["task.completed", "pr.created"],
  "enabled": true,
  "name": "Slack Notifications",
  "description": "Send task updates to #dev-notifications",
  "timeout": 30.0,
  "max_retries": 3,
  "verify_ssl": true,
  "headers": {},
  "created_at": "2024-01-18T14:30:22Z",
  "updated_at": "2024-01-18T14:30:22Z"
}
```

**Error Responses:**

- `404 Not Found` - Webhook not found

---

#### `PUT /webhooks/{webhook_id}`

Update an existing webhook configuration.

**Path Parameters:**

- `webhook_id` - The webhook ID

**Request Body:** `WebhookUpdateRequest`

All fields are optional - only provided fields are updated:

```json
{
  "enabled": false,
  "events": ["pr.created", "pr.merged"],
  "max_retries": 5
}
```

**Parameters:**

- `url` (optional) - New webhook URL
- `secret` (optional) - New secret (empty string to remove)
- `events` (optional) - New event list (empty array to clear filter)
- `enabled` (optional) - Enable/disable webhook
- `name` (optional) - New name
- `description` (optional) - New description
- `timeout` (optional) - New timeout
- `max_retries` (optional) - New max retries
- `verify_ssl` (optional) - SSL verification setting
- `headers` (optional) - New headers

**Response:** `WebhookResponse`

```json
{
  "id": "wh_a1b2c3d4_e5f6g7h8",
  "url": "https://hooks.slack.com/services/xxx/yyy/zzz",
  "has_secret": true,
  "events": ["pr.created", "pr.merged"],
  "enabled": false,
  "name": "Slack Notifications",
  "description": "Send task updates to #dev-notifications",
  "timeout": 30.0,
  "max_retries": 5,
  "verify_ssl": true,
  "headers": {},
  "created_at": "2024-01-18T14:30:22Z",
  "updated_at": "2024-01-18T16:20:15Z"
}
```

**Error Responses:**

- `404 Not Found` - Webhook not found
- `400 Bad Request` - Invalid updates
- `409 Conflict` - URL conflicts with existing webhook

---

#### `DELETE /webhooks/{webhook_id}`

Delete a webhook configuration.

**Path Parameters:**

- `webhook_id` - The webhook ID

**Response:** `WebhookDeleteResponse`

```json
{
  "success": true,
  "message": "Webhook deleted successfully",
  "id": "wh_a1b2c3d4_e5f6g7h8"
}
```

**Error Responses:**

- `404 Not Found` - Webhook not found

---

#### `POST /webhooks/test`

Send a test webhook to verify configuration.

**Request Body:** `WebhookTestRequest`

Test an existing webhook by ID:

```json
{
  "webhook_id": "wh_a1b2c3d4_e5f6g7h8"
}
```

Or test a URL directly:

```json
{
  "url": "https://hooks.example.com/webhook",
  "secret": "optional-secret"
}
```

**Parameters:**

- `webhook_id` (optional) - ID of existing webhook to test
- `url` (optional) - URL to test directly (alternative to webhook_id)
- `secret` (optional) - Secret for direct URL testing

**Note:** Either `webhook_id` or `url` must be provided.

**Response:** `WebhookTestResponse`

```json
{
  "success": true,
  "message": "Test webhook delivered successfully",
  "status_code": 200,
  "delivery_time_ms": 145.3,
  "attempt_count": 1
}
```

**Failed Delivery:**

```json
{
  "success": false,
  "message": "Test webhook delivery failed",
  "status_code": 500,
  "delivery_time_ms": 234.1,
  "attempt_count": 1,
  "error": "Connection timeout"
}
```

**Test Payload Structure:**

```json
{
  "event_type": "webhook.test",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-18T15:45:10.123456Z",
  "message": "This is a test webhook from Claude Task Master",
  "test": true
}
```

**Error Responses:**

- `404 Not Found` - Webhook ID not found
- `400 Bad Request` - Neither webhook_id nor url provided

---

## Complete Example Workflow

Here's a complete example of using the API to manage a task:

```bash
# 1. Check server health
curl http://localhost:8000/health

# 2. Initialize a new task
curl -X POST http://localhost:8000/task/init \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "goal": "Add dark mode support",
    "model": "opus",
    "auto_merge": true,
    "max_sessions": 10
  }'

# 3. Check task status
curl -H "Authorization: Bearer mypassword" \
  http://localhost:8000/status

# 4. View the plan
curl -H "Authorization: Bearer mypassword" \
  http://localhost:8000/plan

# 5. Create a webhook for notifications
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "url": "https://hooks.slack.com/services/xxx/yyy/zzz",
    "secret": "webhook-secret",
    "events": ["task.completed", "pr.created"],
    "name": "Slack Notifications"
  }'

# 6. Monitor progress
curl -H "Authorization: Bearer mypassword" \
  http://localhost:8000/progress

# 7. View recent logs
curl -H "Authorization: Bearer mypassword" \
  http://localhost:8000/logs?tail=50

# 8. Update configuration if needed
curl -X PATCH http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "log_level": "verbose"
  }'

# 9. Stop task if needed
curl -X POST http://localhost:8000/control/stop \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "reason": "Manual stop for review",
    "cleanup": false
  }'

# 10. Resume task
curl -X POST http://localhost:8000/control/resume \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mypassword" \
  -d '{
    "reason": "Continuing after review"
  }'

# 11. Delete task when done
curl -X DELETE http://localhost:8000/task \
  -H "Authorization: Bearer mypassword"
```

---

## Interactive API Documentation

When the server is running, you can access interactive API documentation at:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

These provide an interactive interface for exploring and testing the API directly in your browser.

---

## See Also

- [Authentication Guide](./authentication.md) - Detailed authentication setup and security
- [Webhooks Guide](./webhooks.md) - Webhook events, payload formats, and HMAC verification
- [Docker Guide](./docker.md) - Running the API server in Docker
- [GitHub Repository](https://github.com/developerz-ai/claude-task-master) - Source code and issues
