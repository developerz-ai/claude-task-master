# MCP Tools Reference

This document provides a comprehensive reference for the Claude Task Master MCP (Model Context Protocol) tools. These tools allow Claude instances (in IDEs like Cursor, VS Code, etc.) to interact with claudetm programmatically.

## Table of Contents

- [Overview](#overview)
- [Server Setup](#server-setup)
- [Authentication](#authentication)
- [Available Tools](#available-tools)
  - [Status Tools](#status-tools)
  - [Task Management Tools](#task-management-tools)
  - [Control Tools](#control-tools)
  - [Mailbox Tools](#mailbox-tools)
  - [Repo Setup Tools](#repo-setup-tools)
- [Resources](#resources)
- [Response Format](#response-format)
- [Examples](#examples)
- [IDE Integration](#ide-integration)
- [Troubleshooting](#troubleshooting)

---

## Overview

The MCP server exposes Claude Task Master functionality as tools that other Claude instances can use. This enables:

- **IDE Integration** - Control claudetm from Cursor, VS Code, or any MCP-compatible editor
- **AI Coordination** - Supervisory AI agents can monitor and guide task execution
- **Remote Orchestration** - Manage claudetm instances running on remote servers
- **Multi-Instance Workflows** - Coordinate multiple claudetm instances working together

The MCP server supports three transport types:
- **stdio** - Standard input/output (default, most secure)
- **sse** - Server-Sent Events over HTTP
- **streamable-http** - HTTP with streaming support

---

## Server Setup

### Starting the MCP Server

**Using the CLI:**

```bash
# stdio transport (default, for IDE integration)
claudetm mcp

# SSE transport with HTTP server
claudetm mcp --transport sse --port 8080

# Streamable HTTP transport
claudetm mcp --transport streamable-http --port 8080

# With password authentication (required for network transports)
claudetm mcp --transport sse --password your-secret-password

# With custom working directory
claudetm mcp --working-dir /path/to/project
```

**Environment Variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `CLAUDETM_MCP_HOST` | Host to bind to | `127.0.0.1` |
| `CLAUDETM_MCP_PORT` | Port to bind to | `8080` |
| `CLAUDETM_PASSWORD` | Password for authentication | (none) |
| `CLAUDETM_PASSWORD_HASH` | Bcrypt hash of password | (none) |

### IDE Configuration

**Cursor / VS Code:**

Add to your editor's MCP configuration:

```json
{
  "mcpServers": {
    "claude-task-master": {
      "command": "claudetm",
      "args": ["mcp"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

**For network transport:**

```json
{
  "mcpServers": {
    "claude-task-master": {
      "url": "http://localhost:8080",
      "transport": "sse",
      "headers": {
        "Authorization": "Bearer your-password"
      }
    }
  }
}
```

---

## Authentication

When using network transports (sse, streamable-http), password authentication is highly recommended.

### Setting Up Authentication

**Via command line:**
```bash
claudetm mcp --transport sse --password your-secret-password
```

**Via environment variable:**
```bash
export CLAUDETM_PASSWORD=your-secret-password
claudetm mcp --transport sse
```

**Via pre-hashed password:**
```bash
export CLAUDETM_PASSWORD_HASH='$2b$12$...'
claudetm mcp --transport sse
```

### Security Notes

- **stdio transport** does not require authentication (inherently secure)
- **Network transports** require authentication for non-localhost bindings
- Clients authenticate using Bearer token in the Authorization header
- See [Authentication Guide](./authentication.md) for detailed information

---

## Available Tools

### Status Tools

#### `get_status`

Get comprehensive status information about the current task.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `state_dir` | string | No | Custom state directory path |

**Returns:**
```json
{
  "goal": "Add dark mode support",
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
    "pause_on_pr": false
  }
}
```

**Status Values:**
- `planning` - Task is in planning phase
- `working` - Task is actively executing
- `blocked` - Task needs intervention
- `paused` - Task is paused
- `stopped` - Task has been stopped
- `success` - Task completed successfully
- `failed` - Task failed with error

---

#### `get_plan`

Get the current task plan with markdown checkboxes.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `state_dir` | string | No | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "plan": "# Task Plan\n\n- [x] Task 1: Setup authentication\n- [ ] Task 2: Add webhooks\n..."
}
```

---

#### `get_logs`

Get log content from the current run.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tail` | integer | No | 100 | Number of lines to return from end |
| `state_dir` | string | No | - | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "log_content": "[14:30:22] Starting task execution...\n...",
  "log_file": "/path/to/.claude-task-master/logs/run_20240118.txt"
}
```

---

#### `get_progress`

Get the human-readable progress summary.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `state_dir` | string | No | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "progress": "## Progress Summary\n\nCompleted:\n- Setup auth module\n..."
}
```

---

#### `get_context`

Get accumulated context and learnings.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `state_dir` | string | No | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "context": "## Key Learnings\n\n- Project uses pytest for testing\n..."
}
```

---

#### `health_check`

Health check endpoint for the MCP server.

**Parameters:** None

**Returns:**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "server_name": "claude-task-master",
  "uptime_seconds": 3600.5,
  "active_tasks": 1
}
```

---

### Task Management Tools

#### `initialize_task`

Initialize a new task with the given goal.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `goal` | string | Yes | - | The goal to achieve |
| `model` | string | No | `opus` | Model to use (opus, sonnet, haiku) |
| `auto_merge` | boolean | No | `true` | Auto-merge PRs when approved |
| `max_sessions` | integer | No | - | Max work sessions before pausing |
| `pause_on_pr` | boolean | No | `false` | Pause after creating PR |
| `state_dir` | string | No | - | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "message": "Task initialized successfully with goal: Add dark mode",
  "run_id": "run_20240118_143022",
  "status": "planning"
}
```

**Note:** This only initializes the task state - it does NOT run the task. Use `claudetm start` CLI to run the full workflow.

---

#### `list_tasks`

List tasks from the current plan with completion status.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `state_dir` | string | No | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "tasks": [
    {"task": "Setup authentication", "completed": true},
    {"task": "Add webhooks", "completed": false}
  ],
  "total": 10,
  "completed": 3,
  "current_index": 3
}
```

---

#### `clean_task`

Clean up task state directory.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `force` | boolean | No | `false` | Force cleanup even if session is active |
| `state_dir` | string | No | - | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "message": "Task state cleaned successfully",
  "files_removed": true
}
```

---

### Control Tools

#### `pause_task`

Pause a running task.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `reason` | string | No | Reason for pausing (stored in progress) |
| `state_dir` | string | No | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "message": "Task paused successfully",
  "previous_status": "working",
  "new_status": "paused",
  "reason": "Manual pause for code review"
}
```

---

#### `stop_task`

Stop a running task with optional cleanup.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `reason` | string | No | - | Reason for stopping |
| `cleanup` | boolean | No | `false` | Delete state files after stopping |
| `state_dir` | string | No | - | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "message": "Task stopped successfully",
  "previous_status": "working",
  "new_status": "stopped",
  "reason": "Manual stop",
  "cleanup": false
}
```

---

#### `resume_task`

Resume a paused or blocked task.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `state_dir` | string | No | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "message": "Task resumed successfully",
  "previous_status": "paused",
  "new_status": "working"
}
```

**Note:** This only updates the task state to "working". It does not restart the work loop - use `claudetm resume` CLI for that.

---

#### `update_config`

Update task configuration options at runtime.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `auto_merge` | boolean | No | Auto-merge PRs when approved |
| `max_sessions` | integer | No | Max work sessions before pausing |
| `pause_on_pr` | boolean | No | Pause after creating PR |
| `enable_checkpointing` | boolean | No | Enable state checkpointing |
| `log_level` | string | No | Log level: quiet, normal, verbose |
| `log_format` | string | No | Log format: text, json |
| `pr_per_task` | boolean | No | Create PR per task vs per group |
| `state_dir` | string | No | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "message": "Configuration updated successfully",
  "updated": {
    "auto_merge": false,
    "max_sessions": 20
  },
  "current": {
    "auto_merge": false,
    "max_sessions": 20,
    "pause_on_pr": false,
    "log_level": "normal"
  }
}
```

---

### Mailbox Tools

The mailbox tools enable inter-instance communication and dynamic plan updates. See [Mailbox Guide](./mailbox.md) for detailed documentation.

#### `send_message`

Send a message to the claudetm mailbox.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `content` | string | Yes | - | Message content describing the change request |
| `sender` | string | No | `anonymous` | Identifier of the sender |
| `priority` | integer | No | `1` | Priority: 0=low, 1=normal, 2=high, 3=urgent |
| `state_dir` | string | No | - | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "message_id": "msg_a1b2c3d4",
  "message": "Message sent successfully (id: msg_a1b2c3d4)"
}
```

**Example Usage:**
```
Use the send_message tool to request adding rate limiting:
- content: "Add rate limiting to the /api/users endpoint"
- sender: "security-review"
- priority: 2
```

---

#### `check_mailbox`

Check the status of the claudetm mailbox.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `state_dir` | string | No | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "count": 2,
  "previews": [
    {
      "id": "msg_a1b2c3d4",
      "sender": "security-review",
      "content_preview": "Add rate limiting to the...",
      "priority": 2,
      "timestamp": "2024-01-18T15:30:00Z"
    }
  ],
  "last_checked": "2024-01-18T15:00:00Z",
  "total_messages_received": 5
}
```

---

#### `clear_mailbox`

Clear all messages from the claudetm mailbox.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `state_dir` | string | No | Custom state directory path |

**Returns:**
```json
{
  "success": true,
  "messages_cleared": 2,
  "message": "Cleared 2 message(s) from mailbox"
}
```

---

### Repo Setup Tools

These tools enable the AI developer workflow: clone a repository, set it up for development, and plan work without executing it.

#### `clone_repo`

Clone a git repository to the workspace.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | - | Git repository URL (HTTPS, SSH, or git protocol) |
| `target_dir` | string | No | `~/workspace/claude-task-master/{repo-name}` | Custom target directory path |
| `branch` | string | No | - | Branch to checkout after cloning |

**Returns:**
```json
{
  "success": true,
  "message": "Repository cloned successfully to /home/user/workspace/claude-task-master/my-project",
  "repo_url": "https://github.com/user/my-project.git",
  "target_dir": "/home/user/workspace/claude-task-master/my-project",
  "branch": "main"
}
```

**Error Handling:**
- Returns error if URL is empty or invalid format
- Returns error if target directory already exists
- Returns error if parent directory cannot be created (permission denied)

**Use Case:**
```
Clone a repository to the workspace before setting it up:
- url: "https://github.com/myorg/my-service.git"
- target_dir: "/home/user/workspace/claude-task-master/my-service"
```

---

#### `setup_repo`

Set up a cloned repository for development.

Detects project type and performs appropriate setup:
- **Python projects**: Creates virtual environment, installs dependencies via pip or uv
- **Node projects**: Creates node_modules and installs dependencies via npm/yarn
- **All projects**: Runs setup scripts (setup-hooks.sh, setup.sh, install.sh, bootstrap.sh)

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `work_dir` | string | Yes | Path to the cloned repository directory |

**Returns:**
```json
{
  "success": true,
  "message": "Repository setup completed successfully",
  "work_dir": "/home/user/workspace/claude-task-master/my-project",
  "steps_completed": [
    "Detected Python project",
    "Created virtual environment at .venv",
    "Installed dependencies with uv",
    "Running setup script: scripts/setup-hooks.sh"
  ],
  "venv_path": "/home/user/workspace/claude-task-master/my-project/.venv",
  "dependencies_installed": true,
  "setup_scripts_run": ["scripts/setup-hooks.sh"]
}
```

**Error Handling:**
- Returns error if work directory doesn't exist
- Returns error if path is not a directory
- Returns error if setup commands fail (with details)

**Supported Project Types:**
- **Python**: Detects `pyproject.toml`, `setup.py`, `requirements.txt`, or `uv.lock`
- **Node.js**: Detects `package.json`
- **Setup Scripts**: Looks for `setup.sh`, `install.sh`, `bootstrap.sh` in `scripts/` or root

**Use Case:**
```
Set up a Python project after cloning:
- work_dir: "/home/user/workspace/claude-task-master/my-project"

This will:
1. Create .venv
2. Install dependencies with uv (or pip)
3. Run any setup scripts found in scripts/ directory
```

---

#### `plan_repo`

Create a plan for a repository without executing any work.

This plan-only mode reads the codebase using read-only tools (Read, Glob, Grep, Bash) and outputs a structured plan with tasks and success criteria. No changes are made to the repository.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `work_dir` | string | Yes | - | Path to the repository directory to plan for |
| `goal` | string | Yes | - | The goal/task description to plan for |
| `model` | string | No | `opus` | Model to use for planning (opus, sonnet, haiku) |

**Returns:**
```json
{
  "success": true,
  "message": "Plan created successfully",
  "work_dir": "/home/user/workspace/claude-task-master/my-project",
  "goal": "Add authentication to the API",
  "plan": "# Task Plan\n\n## Overview\nAdd JWT-based authentication to the existing API.\n\n## Tasks\n\n- [ ] Create auth module with JWT utilities\n- [ ] Add authentication middleware\n- [ ] Update API endpoints with auth checks\n- [ ] Add tests for authentication\n- [ ] Update API documentation\n\n## Success Criteria\n\n1. All API endpoints require valid JWT token\n2. Tests pass with 95%+ coverage\n3. Documentation updated\n4. No breaking changes to existing clients",
  "criteria": "1. All API endpoints require valid JWT token\n2. Tests pass with 95%+ coverage\n3. Documentation updated\n4. No breaking changes to existing clients",
  "run_id": "plan_20240118_143022"
}
```

**Error Handling:**
- Returns error if work directory doesn't exist
- Returns error if goal is empty
- Returns error if task is already in progress (status: planning or working)
- Returns error if credentials are not available

**Use Case:**
```
Plan work for a repository without executing it:
- work_dir: "/home/user/workspace/claude-task-master/my-project"
- goal: "Add rate limiting to the API"
- model: "opus"

This will create a task plan that you can review before executing with `start_task`.
```

**Complete Workflow:**
```
1. clone_repo
   - url: "https://github.com/myorg/my-service.git"
   - target_dir: "/home/user/workspace/claude-task-master/my-service"

2. setup_repo
   - work_dir: "/home/user/workspace/claude-task-master/my-service"

3. plan_repo
   - work_dir: "/home/user/workspace/claude-task-master/my-service"
   - goal: "Add feature X to the service"
   - model: "opus"

4. (Optional) Review plan, adjust via send_message tool

5. (In future session) start_task to execute the plan
```

---

## Resources

The MCP server also exposes task data as resources that can be accessed directly.

| Resource URI | Description |
|--------------|-------------|
| `task://goal` | Current task goal |
| `task://plan` | Current task plan (markdown) |
| `task://progress` | Progress summary |
| `task://context` | Accumulated context and learnings |

**Example (in MCP client):**
```
Access the task://plan resource to see the current task plan.
```

---

## Response Format

### Success Response

All successful responses include the requested data:

```json
{
  "success": true,
  "data": { ... }
}
```

### Error Response

Error responses follow a consistent format:

```json
{
  "success": false,
  "error": "Error message",
  "suggestion": "Suggested action (optional)"
}
```

### Common Errors

| Error | Description | Resolution |
|-------|-------------|------------|
| `No active task found` | No task initialized | Use `initialize_task` or `claudetm start` |
| `No plan found` | Planning phase not complete | Wait for planning to finish |
| `Task already exists` | Task state exists | Use `clean_task` first |
| `Another session is active` | Lock conflict | Wait or use `force=True` |
| `Operation not allowed` | Invalid state transition | Check current status |

---

## Examples

### Monitor Task Progress (in IDE)

```
1. Use get_status to check current task state
2. Use get_plan to see the task checklist
3. Use get_progress for a human-readable summary
4. Use get_logs with tail=50 for recent activity
```

### Send Feedback to Running Task

```
Use send_message with:
- content: "The login page should also have a 'forgot password' link"
- sender: "product-review"
- priority: 1

This message will be processed after the current task completes.
```

### Coordinate Multiple Instances

```
# Supervisor checking instance status
Use get_status to check task state

# If instance is stuck, send guidance
Use send_message with:
- content: "Use the existing AuthService instead of creating a new one"
- sender: "supervisor"
- priority: 2

# If instance needs to pause
Use pause_task with:
- reason: "Waiting for API changes from instance-2"
```

### Adjust Configuration Mid-Task

```
Use update_config with:
- max_sessions: 20
- log_level: "verbose"

This increases session limit and enables verbose logging.
```

### Set Up a New Project for Development

```
1. Clone the repository
   Use clone_repo with:
   - url: "https://github.com/myorg/my-service.git"
   - target_dir: "/home/user/workspace/claude-task-master/my-service"

2. Set up the development environment
   Use setup_repo with:
   - work_dir: "/home/user/workspace/claude-task-master/my-service"

   This will create venv, install dependencies, and run setup scripts.

3. Plan work for the project
   Use plan_repo with:
   - work_dir: "/home/user/workspace/claude-task-master/my-service"
   - goal: "Add user authentication to the API"
   - model: "opus"

   This creates a task plan without making any changes.

4. Review the plan and execute (in a new session)
   Use initialize_task with the goal and parameters, then execute
```

---

## IDE Integration

### Cursor Setup

1. Open Cursor Settings (Cmd/Ctrl + ,)
2. Go to Features > MCP Servers
3. Add a new server configuration:

```json
{
  "claude-task-master": {
    "command": "claudetm",
    "args": ["mcp"],
    "cwd": "${workspaceFolder}"
  }
}
```

4. Restart Cursor to activate the MCP server

### VS Code Setup

1. Install an MCP-compatible extension
2. Configure the extension with the claudetm MCP server
3. Ensure `claudetm` is in your PATH

### Using MCP Tools in Chat

Once configured, you can ask Claude in your IDE to:

- "Check the claudetm task status"
- "Show me the current task plan"
- "Send a message to add rate limiting"
- "Pause the current task"
- "Update the configuration to increase max sessions"

---

## Troubleshooting

### MCP Server Not Starting

**Check installation:**
```bash
claudetm doctor
```

**Verify MCP command:**
```bash
claudetm mcp --help
```

**Check logs:**
```bash
claudetm mcp 2>&1 | tee mcp.log
```

### Connection Refused

**For network transports:**
```bash
# Check if server is running
curl http://localhost:8080/health

# Verify port is not in use
lsof -i :8080
```

### Authentication Failed

**Verify password:**
```bash
# Test with curl
curl -H "Authorization: Bearer your-password" \
  http://localhost:8080/health
```

### Tools Not Available

**Check MCP server registration:**
- Restart your IDE
- Verify the configuration path
- Check IDE logs for MCP errors

### State Directory Issues

**Use custom state directory:**
```bash
claudetm mcp --working-dir /path/to/project
```

**Check permissions:**
```bash
ls -la .claude-task-master/
```

---

## See Also

- [REST API Reference](./api-reference.md) - HTTP REST API documentation
- [Mailbox Guide](./mailbox.md) - Inter-instance communication
- [Authentication Guide](./authentication.md) - Security configuration
- [Webhooks Guide](./webhooks.md) - Event notifications
- [Docker Guide](./docker.md) - Container deployment

---

**Questions or Issues?**

Visit the [GitHub repository](https://github.com/developerz-ai/claude-task-master) to report issues or contribute improvements.
