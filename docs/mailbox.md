# Mailbox System Guide

This guide covers the mailbox system in Claude Task Master, which enables inter-instance communication and dynamic plan updates during task execution.

## Table of Contents

- [Overview](#overview)
- [Use Cases](#use-cases)
- [How It Works](#how-it-works)
- [CLI Usage](#cli-usage)
- [REST API](#rest-api)
- [MCP Tools](#mcp-tools)
- [Message Priority](#message-priority)
- [Message Merging](#message-merging)
- [Multi-Instance Coordination](#multi-instance-coordination)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Overview

The mailbox system allows external systems (other Claude Task Master instances, CI/CD pipelines, supervisory AI agents, or humans) to send messages that modify the current task's plan while it's running. This enables:

- **Dynamic Plan Updates** - Change requirements mid-task without restarting
- **Multi-Instance Coordination** - Multiple claudetm instances can communicate
- **Supervisory Control** - AI supervisors can guide task execution
- **Human Intervention** - Operators can adjust plans without stopping work

When a message is sent to the mailbox, it's stored and processed after the current task completes. Multiple messages are merged into a single change request that updates the plan before continuing with the next task.

---

## Use Cases

### 1. Requirement Changes Mid-Task

A stakeholder realizes they need an additional feature:

```bash
# While claudetm is working on "Add user authentication"
curl -X POST http://localhost:8000/mailbox/send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer password" \
  -d '{
    "content": "Also add password reset functionality",
    "sender": "product-manager",
    "priority": 2
  }'
```

### 2. Bug Discovery During Development

CI finds a bug that should be prioritized:

```bash
curl -X POST http://localhost:8000/mailbox/send \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Critical: Fix SQL injection vulnerability in login endpoint before continuing",
    "sender": "security-scan",
    "priority": 3
  }'
```

### 3. AI Supervisor Coordination

An orchestrating AI observes the work and provides guidance:

```bash
# Supervisor notices a better approach
curl -X POST http://localhost:8000/mailbox/send \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Use the existing AuthProvider instead of creating a new one. See src/auth/provider.py for the interface.",
    "sender": "ai-supervisor",
    "priority": 2
  }'
```

### 4. Multi-Instance Workflows

Instance A discovers a dependency that Instance B should know about:

```bash
# Instance A sends to Instance B
curl -X POST http://instance-b:8000/mailbox/send \
  -H "Content-Type: application/json" \
  -d '{
    "content": "I have updated the UserModel schema. Please update your API endpoints to match the new field names.",
    "sender": "instance-a",
    "priority": 2
  }'
```

---

## How It Works

### Message Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        MAILBOX FLOW                              │
│                                                                  │
│  External Source ──► POST /mailbox/send ──► Mailbox Storage     │
│  (API, MCP, CLI)                              (mailbox.json)     │
│                                                                  │
│                         ┌─────────────────────┐                  │
│                         │  Task Completes     │                  │
│                         └─────────┬───────────┘                  │
│                                   ▼                              │
│                      ┌────────────────────────┐                  │
│                      │  Check Mailbox         │                  │
│                      │  (get_and_clear)       │                  │
│                      └─────────┬──────────────┘                  │
│                                │                                 │
│              ┌─────────────────┴─────────────────┐               │
│              ▼                                   ▼               │
│   ┌──────────────────┐               ┌──────────────────┐        │
│   │  No Messages     │               │  Messages Found  │        │
│   │  Continue Work   │               │  Merge & Update  │        │
│   └──────────────────┘               │  Plan            │        │
│                                      └─────────┬────────┘        │
│                                                ▼                 │
│                                      ┌──────────────────┐        │
│                                      │  Continue Work   │        │
│                                      │  (Updated Plan)  │        │
│                                      └──────────────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

### Processing Timeline

1. **Message Received** - Stored in `.claude-task-master/mailbox.json`
2. **Task Completes** - Orchestrator finishes current task
3. **Mailbox Check** - Orchestrator retrieves and clears all messages
4. **Message Merge** - Multiple messages combined into one change request
5. **Plan Update** - Planning agent updates plan with change request
6. **Work Continues** - Next task from (potentially updated) plan

---

## CLI Usage

### Resume with Message

The simplest way to update a plan is using `claudetm resume` with a message:

```bash
# Resume without changes (existing behavior)
claudetm resume

# Resume with a change request
claudetm resume "Add rate limiting to the API endpoints"

# More detailed change request
claudetm resume "Instead of using JWT tokens, switch to session-based auth for better security"
```

When a message is provided, claudetm will:
1. Update the plan using the message as context
2. Resume work with the updated plan

### Examples

```bash
# Add a new requirement
claudetm resume "Also add email verification to the signup flow"

# Change approach
claudetm resume "Use PostgreSQL instead of SQLite for the database"

# Fix discovered issue
claudetm resume "The tests are failing because of a missing mock. Fix that first."

# Prioritize different task
claudetm resume "Actually, let's focus on the API endpoints first, then UI"
```

---

## REST API

### Send Message to Mailbox

**Endpoint:** `POST /mailbox/send`

Send a message to the mailbox for processing after the current task.

**Request Body:**

```json
{
  "content": "Add dark mode support to the settings page",
  "sender": "product-team",
  "priority": 1,
  "metadata": {
    "ticket": "JIRA-123",
    "source": "planning-meeting"
  }
}
```

**Parameters:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `content` | string | Yes | - | The message content describing the change request |
| `sender` | string | No | "anonymous" | Identifier for the message sender |
| `priority` | integer | No | 1 | Priority level (0=low, 1=normal, 2=high, 3=urgent) |
| `metadata` | object | No | {} | Additional metadata for tracking |

**Response (201 Created):**

```json
{
  "success": true,
  "message_id": "msg_a1b2c3d4",
  "message": "Message sent successfully (id: msg_a1b2c3d4)"
}
```

**Example:**

```bash
curl -X POST http://localhost:8000/mailbox/send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer password" \
  -d '{
    "content": "Add input validation to all form fields",
    "sender": "security-review",
    "priority": 2
  }'
```

### Check Mailbox Status

**Endpoint:** `GET /mailbox`

Check the current mailbox status including message count and previews.

**Response:**

```json
{
  "success": true,
  "count": 2,
  "messages": [
    {
      "id": "msg_a1b2c3d4",
      "sender": "security-review",
      "content_preview": "Add input validation to all form...",
      "priority": 2,
      "timestamp": "2024-01-18T15:30:00Z"
    },
    {
      "id": "msg_e5f6g7h8",
      "sender": "product-team",
      "content_preview": "Also add export functionality for...",
      "priority": 1,
      "timestamp": "2024-01-18T15:35:00Z"
    }
  ],
  "last_checked": "2024-01-18T15:00:00Z",
  "total_messages_received": 5
}
```

**Example:**

```bash
curl http://localhost:8000/mailbox \
  -H "Authorization: Bearer password"
```

### Clear Mailbox

**Endpoint:** `DELETE /mailbox`

Clear all pending messages from the mailbox.

**Response:**

```json
{
  "success": true,
  "messages_cleared": 2,
  "message": "Cleared 2 message(s) from mailbox"
}
```

**Example:**

```bash
curl -X DELETE http://localhost:8000/mailbox \
  -H "Authorization: Bearer password"
```

---

## MCP Tools

The mailbox system is also accessible via MCP tools for IDE integration.

### send_message

Send a message to the mailbox.

**Parameters:**
- `content` (required): Message content
- `sender` (optional): Sender identifier (default: "anonymous")
- `priority` (optional): 0-3 (default: 1)

**Example (Claude Editor):**
```
Use the send_message tool with:
- content: "Add caching to the database queries"
- sender: "code-review"
- priority: 2
```

### check_mailbox

Check mailbox status and view pending messages.

**Returns:**
- Message count
- List of message previews (id, sender, content preview, priority, timestamp)
- Last checked time
- Total messages received

### clear_mailbox

Clear all pending messages.

**Returns:**
- Number of messages cleared

---

## Message Priority

Messages have four priority levels that affect their processing order:

| Priority | Value | Name | Use Case |
|----------|-------|------|----------|
| 0 | Low | `low` | Nice-to-have suggestions, minor improvements |
| 1 | Normal | `normal` | Standard change requests (default) |
| 2 | High | `high` | Important changes that should be addressed soon |
| 3 | Urgent | `urgent` | Critical issues that must be addressed immediately |

### Priority Processing

When messages are merged, higher priority messages appear first in the merged change request. This ensures the planning agent considers urgent items before lower-priority ones.

```bash
# Urgent security fix
curl -X POST http://localhost:8000/mailbox/send \
  -d '{"content": "Fix SQL injection NOW", "priority": 3}'

# Normal feature request
curl -X POST http://localhost:8000/mailbox/send \
  -d '{"content": "Add dark mode support", "priority": 1}'
```

When merged, the security fix will be listed first.

---

## Message Merging

When multiple messages are pending, they are merged into a single coherent change request.

### Merge Format

```
# Combined Change Request

## Message from security-review (Priority: URGENT)
Received: 2024-01-18 15:30:00

Fix the SQL injection vulnerability in the login endpoint.

---

## Message from product-team (Priority: NORMAL)
Received: 2024-01-18 15:35:00

Add export functionality for user data.

---

## Summary
- 2 message(s) merged
- Highest priority: URGENT
```

### Merge Behavior

1. **Priority Ordering**: Higher priority messages first
2. **Sender Attribution**: Each message includes its sender
3. **Timestamps**: When each message was received
4. **Full Content**: Complete message content preserved
5. **Summary**: Overview of merged messages

---

## Multi-Instance Coordination

The mailbox system enables sophisticated multi-instance workflows.

### Architecture Example

```
┌─────────────────────────────────────────────────────────────────┐
│                    AI SUPERVISOR                                 │
│                                                                  │
│  Monitors: claudetm-1, claudetm-2, claudetm-3                   │
│  Coordinates via mailbox messages                                │
└───────────────────────────┬─────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
            ▼               ▼               ▼
     ┌──────────┐    ┌──────────┐    ┌──────────┐
     │claudetm-1│    │claudetm-2│    │claudetm-3│
     │          │    │          │    │          │
     │Backend   │    │Frontend  │    │Testing   │
     │API work  │    │UI work   │    │QA work   │
     └──────────┘    └──────────┘    └──────────┘
```

### Coordination Patterns

**1. Dependency Notification:**
```bash
# Instance 1 notifies Instance 2 of schema change
curl -X POST http://instance-2:8000/mailbox/send \
  -d '{"content": "UserModel schema updated: added email_verified field", "sender": "instance-1"}'
```

**2. Supervisor Guidance:**
```bash
# Supervisor adjusts Instance 3's priorities
curl -X POST http://instance-3:8000/mailbox/send \
  -d '{"content": "Pause integration tests. Focus on unit tests first.", "sender": "supervisor", "priority": 2}'
```

**3. Cross-Instance Information Sharing:**
```bash
# Instance 2 shares discovery with Instance 1
curl -X POST http://instance-1:8000/mailbox/send \
  -d '{"content": "Found bug in auth: tokens expire 1 hour early. Related to your API work.", "sender": "instance-2"}'
```

---

## Best Practices

### 1. Be Specific in Messages

**Good:**
```json
{
  "content": "Add rate limiting of 100 requests/minute to /api/users endpoint using Redis",
  "sender": "security-team"
}
```

**Avoid:**
```json
{
  "content": "Add rate limiting",
  "sender": "anonymous"
}
```

### 2. Use Appropriate Priority

- **Urgent (3)**: Security vulnerabilities, production issues
- **High (2)**: Important business requirements, blocking issues
- **Normal (1)**: Standard feature requests, improvements
- **Low (0)**: Nice-to-haves, minor optimizations

### 3. Include Sender Information

Always identify the sender for traceability:

```json
{
  "sender": "ci-pipeline",
  "content": "Tests failed: 3 failures in auth module"
}
```

### 4. Use Metadata for Tracking

```json
{
  "content": "Implement JIRA-456 feature",
  "metadata": {
    "ticket": "JIRA-456",
    "sprint": "2024-Q1-S3",
    "requester": "jane@example.com"
  }
}
```

### 5. Don't Overload the Mailbox

Send consolidated messages rather than many small ones:

**Good:**
```json
{
  "content": "Please address these review comments:\n1. Add error handling to login\n2. Validate email format\n3. Add rate limiting"
}
```

**Avoid:**
```json
// Three separate messages for related items
{"content": "Add error handling to login"}
{"content": "Validate email format"}
{"content": "Add rate limiting"}
```

---

## Troubleshooting

### Messages Not Being Processed

**Check mailbox status:**
```bash
curl http://localhost:8000/mailbox
```

**Verify messages are stored:**
```bash
cat .claude-task-master/mailbox.json
```

**Check orchestrator logs:**
```bash
claudetm logs -n 100 | grep -i mailbox
```

### Plan Not Updating

**Verify task is running:**
```bash
claudetm status
```

Messages are only processed when:
1. A task completes
2. The orchestrator checks the mailbox
3. There are pending messages

**Force plan update:**
```bash
# Stop and resume with message
claudetm resume "Update the plan with: <your changes>"
```

### Message Priority Issues

Messages are merged in priority order. If urgent messages aren't being addressed first, verify the priority value:

```bash
# Check message priorities in mailbox
curl http://localhost:8000/mailbox | jq '.messages[].priority'
```

### Connection Refused

**Ensure server is running:**
```bash
claudetm-server --port 8000
```

**Check Docker container:**
```bash
docker logs claudetm
```

---

## See Also

- [REST API Reference](./api-reference.md) - Complete API documentation
- [Authentication Guide](./authentication.md) - Securing your instance
- [Docker Guide](./docker.md) - Container deployment
- [Webhooks Guide](./webhooks.md) - Event notifications

---

**Questions or Issues?**

Visit the [GitHub repository](https://github.com/developerz-ai/claude-task-master) to report issues or contribute improvements.
