# Authentication Guide

This guide explains how password-based authentication works in Claude Task Master for securing REST API, MCP server, and webhook endpoints.

## Table of Contents

- [Overview](#overview)
- [Password Configuration](#password-configuration)
- [Authentication Flow](#authentication-flow)
- [REST API Authentication](#rest-api-authentication)
- [MCP Server Authentication](#mcp-server-authentication)
- [Webhook Authentication](#webhook-authentication)
- [Security Best Practices](#security-best-practices)
- [Troubleshooting](#troubleshooting)

## Overview

Claude Task Master uses password-based authentication with Bearer token authorization to secure network-accessible services:

- **REST API** - Protects task management endpoints
- **MCP Server** - Secures network transports (SSE, streamable-http)
- **Webhooks** - Signs outgoing webhook payloads with HMAC-SHA256

**Authentication Method:**
- REST API and MCP: `Authorization: Bearer <password>` header
- Webhooks: HMAC-SHA256 signature verification

**When Authentication is Required:**
- REST API: Always when `CLAUDETM_PASSWORD` or `CLAUDETM_PASSWORD_HASH` is set
- MCP Server: Only for network transports (SSE, streamable-http), not stdio
- Webhooks: Signatures always included when `webhook_secret` is configured

## Password Configuration

### Development Mode (Plaintext Password)

For development and testing, use a plaintext password:

```bash
# Set the password
export CLAUDETM_PASSWORD="your-secure-password"

# Start the server
claudetm-server --rest-port 8000 --mcp-port 8080
```

**⚠️ Warning:** Never use plaintext passwords in production!

### Production Mode (Hashed Password)

For production deployments, pre-hash your password with bcrypt:

```bash
# Generate a bcrypt hash (requires passlib[bcrypt])
python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('your-secure-password'))"
# Output: $2b$12$...hash...

# Set the hash as an environment variable
export CLAUDETM_PASSWORD_HASH='$2b$12$...hash...'

# Start the server
claudetm-server --rest-port 8000 --mcp-port 8080
```

**Benefits of pre-hashed passwords:**
- Password never exists in plaintext in environment
- Safer for production deployments
- Can be stored in secrets management systems

### Environment Variables

| Variable | Description | Example | Recommended For |
|----------|-------------|---------|-----------------|
| `CLAUDETM_PASSWORD` | Plaintext password | `my-secret-123` | Development |
| `CLAUDETM_PASSWORD_HASH` | Bcrypt hash | `$2b$12$...` | Production |

**Priority:** `CLAUDETM_PASSWORD_HASH` takes precedence over `CLAUDETM_PASSWORD` if both are set.

### Docker Configuration

When using Docker, pass the password via environment variable:

```bash
# With plaintext password (development)
docker run -d \
  -e CLAUDETM_PASSWORD=your-password \
  -p 8000:8000 -p 8080:8080 \
  ghcr.io/developerz-ai/claude-task-master:latest

# With hashed password (production)
docker run -d \
  -e CLAUDETM_PASSWORD_HASH='$2b$12$...' \
  -p 8000:8000 -p 8080:8080 \
  ghcr.io/developerz-ai/claude-task-master:latest
```

For docker-compose, use environment files:

```yaml
# docker-compose.yml
services:
  claudetm:
    image: ghcr.io/developerz-ai/claude-task-master:latest
    env_file:
      - .env
    ports:
      - "8000:8000"
      - "8080:8080"
```

```bash
# .env
CLAUDETM_PASSWORD_HASH=$2b$12$...your-hash...
```

## Authentication Flow

### Request Flow

```
1. Client sends request with Authorization header
   ↓
2. Middleware extracts Bearer token from header
   ↓
3. Token is verified against configured password
   - If CLAUDETM_PASSWORD_HASH: bcrypt verification
   - If CLAUDETM_PASSWORD: constant-time plaintext comparison
   ↓
4. If valid: Request proceeds to handler
   If invalid: Return 401 or 403 error
```

### Password Verification

**Bcrypt Hash Verification:**
```python
# Automatic constant-time comparison via bcrypt
provided_password = "user-input"
stored_hash = "$2b$12$..."

# Uses passlib's verify() - constant-time by design
verify_password(provided_password, stored_hash)  # True/False
```

**Plaintext Verification:**
```python
# Constant-time comparison to prevent timing attacks
import secrets

provided = "user-input"
expected = os.getenv("CLAUDETM_PASSWORD")

secrets.compare_digest(provided, expected)  # True/False
```

### Bcrypt Details

- **Algorithm**: bcrypt with 12 rounds (cost factor)
- **Hash Format**: `$2b$12$...` (60 character string)
- **Password Limit**: 72 bytes (UTF-8 encoded) - automatically truncated
- **Security**: Designed to be slow (prevents brute force attacks)

## REST API Authentication

### Making Authenticated Requests

All REST API endpoints (except health checks) require authentication when password is configured.

#### Using curl

Set your password as an environment variable for easy reuse:

```bash
export PASSWORD="your-secure-password"
```

**Info Endpoints (Read-only):**

```bash
# Get task status
curl -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/status

# Get task plan with checkboxes
curl -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/plan

# Get last 100 lines of logs (default)
curl -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/logs

# Get last 500 lines of logs
curl -H "Authorization: Bearer $PASSWORD" \
  "http://localhost:8000/logs?tail=500"

# Get progress summary
curl -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/progress

# Get accumulated context/learnings
curl -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/context

# Health check (no auth required)
curl http://localhost:8000/health
```

**Task Management Endpoints:**

```bash
# Initialize a new task
curl -X POST \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Add user authentication to the API",
    "model": "sonnet",
    "auto_merge": false,
    "max_sessions": 10,
    "pause_on_pr": true
  }' \
  http://localhost:8000/task/init

# Delete current task
curl -X DELETE \
  -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/task
```

**Control Endpoints:**

```bash
# Stop a running task (keep state files)
curl -X POST \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Need to review changes",
    "cleanup": false
  }' \
  http://localhost:8000/control/stop

# Stop task and clean up state files
curl -X POST \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Cancelling task",
    "cleanup": true
  }' \
  http://localhost:8000/control/stop

# Resume a paused or stopped task
curl -X POST \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{}' \
  http://localhost:8000/control/resume

# Update configuration
curl -X PATCH \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "auto_merge": true,
    "max_sessions": 20
  }' \
  http://localhost:8000/config
```

**Webhook Endpoints:**

```bash
# List all webhooks
curl -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/webhooks

# Create a new webhook
curl -X POST \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/webhook",
    "secret": "webhook-secret-key",
    "events": ["task.completed", "pr.created"],
    "enabled": true
  }' \
  http://localhost:8000/webhooks

# Get specific webhook by ID
curl -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/webhooks/webhook-123

# Update a webhook
curl -X PUT \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/webhook/updated",
    "secret": "new-secret",
    "events": ["task.completed", "task.failed"],
    "enabled": true
  }' \
  http://localhost:8000/webhooks/webhook-123

# Delete a webhook
curl -X DELETE \
  -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/webhooks/webhook-123

# Test webhook delivery
curl -X POST \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook_id": "webhook-123",
    "event_type": "task.completed"
  }' \
  http://localhost:8000/webhooks/test
```

**Pretty-Print JSON Responses:**

Add `| jq` to format JSON output (requires [jq](https://jqlr.dev/)):

```bash
# Pretty-print status response
curl -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/status | jq

# Extract specific fields
curl -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/status | jq '.goal, .status, .session_count'

# Get just task progress
curl -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/status | jq '.tasks'
```

**Error Handling:**

```bash
# Capture HTTP status code
HTTP_CODE=$(curl -o /dev/null -s -w "%{http_code}" \
  -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/status)

if [ "$HTTP_CODE" -eq 200 ]; then
  echo "Success"
elif [ "$HTTP_CODE" -eq 401 ]; then
  echo "Authentication required"
elif [ "$HTTP_CODE" -eq 403 ]; then
  echo "Invalid password"
else
  echo "Error: $HTTP_CODE"
fi

# Show full response with headers
curl -i \
  -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/status

# Verbose output for debugging
curl -v \
  -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/status
```

#### Using Python requests

```python
import requests

password = "your-secure-password"
headers = {"Authorization": f"Bearer {password}"}

# Get status
response = requests.get(
    "http://localhost:8000/status",
    headers=headers
)

if response.status_code == 200:
    print(response.json())
elif response.status_code == 401:
    print("Not authenticated - missing or invalid header")
elif response.status_code == 403:
    print("Invalid password")
```

#### Using JavaScript fetch

```javascript
const password = "your-secure-password";

const response = await fetch("http://localhost:8000/status", {
  headers: {
    "Authorization": `Bearer ${password}`
  }
});

if (response.ok) {
  const data = await response.json();
  console.log(data);
} else if (response.status === 401) {
  console.error("Not authenticated");
} else if (response.status === 403) {
  console.error("Invalid password");
}
```

### Public Endpoints

The following endpoints do **not** require authentication:

- `/` - API information
- `/health` - Health check
- `/healthz` - Kubernetes health check
- `/ready` - Readiness probe
- `/livez` - Liveness probe
- `/docs` - OpenAPI documentation
- `/redoc` - ReDoc documentation
- `/openapi.json` - OpenAPI schema

All other endpoints require valid authentication.

### Error Responses

**401 Unauthorized** - Missing or malformed Authorization header:
```json
{
  "detail": "Not authenticated",
  "error": "missing_authorization",
  "message": "Authorization header required. Use: Authorization: Bearer <password>"
}
```

**403 Forbidden** - Invalid password:
```json
{
  "detail": "Invalid credentials",
  "error": "invalid_password",
  "message": "The provided password is incorrect"
}
```

**500 Internal Server Error** - Authentication not configured:
```json
{
  "detail": "Authentication configuration error",
  "error": "config_error",
  "message": "Authentication required but not configured. Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH environment variable."
}
```

## MCP Server Authentication

### Transport Types

MCP Server authentication depends on the transport type:

| Transport | Authentication Required | Use Case |
|-----------|------------------------|----------|
| `stdio` | ❌ No (local process) | Local Claude Desktop |
| `sse` | ✅ Yes (network) | Remote MCP connections |
| `streamable-http` | ✅ Yes (network) | HTTP-based MCP |

**stdio transport** is inherently secure (local process communication) and does not support authentication.

**Network transports** (SSE, streamable-http) require authentication when `CLAUDETM_PASSWORD` or `CLAUDETM_PASSWORD_HASH` is set.

### MCP Client Configuration

MCP clients can connect to Claude Task Master using different transports. The configuration varies based on whether authentication is required.

#### Claude Desktop Configuration

**Location**:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

**stdio transport (local, no authentication):**

```json
{
  "mcpServers": {
    "claude-task-master": {
      "command": "claudetm-mcp",
      "args": ["--transport", "stdio"],
      "env": {}
    }
  }
}
```

This is the recommended configuration for Claude Desktop as it:
- Uses local process communication (most secure)
- No network exposure
- No authentication needed
- Lowest latency

**SSE transport (network, with authentication):**

```json
{
  "mcpServers": {
    "claude-task-master-remote": {
      "command": "claudetm-mcp",
      "args": [
        "--transport", "sse",
        "--host", "localhost",
        "--port", "8080"
      ],
      "env": {
        "CLAUDETM_PASSWORD": "your-secure-password"
      }
    }
  }
}
```

**Remote SSE server (different machine):**

```json
{
  "mcpServers": {
    "claude-task-master-remote": {
      "command": "claudetm-mcp",
      "args": [
        "--transport", "sse",
        "--host", "remote.example.com",
        "--port", "8080"
      ],
      "env": {
        "CLAUDETM_PASSWORD": "your-secure-password",
        "CLAUDETM_TLS": "true"
      }
    }
  }
}
```

**Using password hash (more secure):**

```json
{
  "mcpServers": {
    "claude-task-master": {
      "command": "claudetm-mcp",
      "args": [
        "--transport", "sse",
        "--host", "localhost",
        "--port", "8080"
      ],
      "env": {
        "CLAUDETM_PASSWORD_HASH": "$2b$12$..."
      }
    }
  }
}
```

#### Python MCP Client

**stdio transport (local, no authentication):**

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    # Configure server parameters
    server_params = StdioServerParameters(
        command="claudetm-mcp",
        args=["--transport", "stdio"],
        env={}
    )

    # Connect and use the server
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()

            # List available tools
            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}")

            # Call a tool (e.g., get status)
            result = await session.call_tool("get_status", {})
            print(f"Task status: {result}")

if __name__ == "__main__":
    asyncio.run(main())
```

**SSE transport (network, with authentication):**

```python
import asyncio
import os
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    password = os.getenv("CLAUDETM_PASSWORD", "your-secure-password")

    # Configure headers with authentication
    headers = {
        "Authorization": f"Bearer {password}"
    }

    # Connect to SSE endpoint
    url = "http://localhost:8080/sse"

    async with sse_client(url, headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()

            # Call tools with authentication
            result = await session.call_tool("get_status", {})
            print(f"Task status: {result}")

if __name__ == "__main__":
    asyncio.run(main())
```

**Full example with error handling:**

```python
import asyncio
import logging
import os
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def call_claudetm_tool(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    password: str | None = None,
    host: str = "localhost",
    port: int = 8080,
) -> Any:
    """Call a Claude Task Master MCP tool with authentication.

    Args:
        tool_name: Name of the tool to call (e.g., "get_status", "start_task")
        arguments: Tool arguments as a dictionary
        password: Authentication password (or uses CLAUDETM_PASSWORD env var)
        host: MCP server host
        port: MCP server port

    Returns:
        Tool result

    Raises:
        ConnectionError: If connection fails
        ValueError: If authentication fails
    """
    # Get password from env if not provided
    pwd = password or os.getenv("CLAUDETM_PASSWORD")
    if not pwd:
        raise ValueError("Password required. Set CLAUDETM_PASSWORD or pass password argument")

    # Configure headers
    headers = {"Authorization": f"Bearer {pwd}"}
    url = f"http://{host}:{port}/sse"

    try:
        async with sse_client(url, headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize
                init_result = await session.initialize()
                logger.info(f"Connected to {init_result.serverInfo.name} v{init_result.serverInfo.version}")

                # Call tool
                result = await session.call_tool(tool_name, arguments or {})
                logger.info(f"Tool {tool_name} completed successfully")

                return result

    except Exception as e:
        if "401" in str(e) or "403" in str(e):
            raise ValueError(f"Authentication failed: {e}") from e
        raise ConnectionError(f"Failed to connect to MCP server: {e}") from e


async def main():
    try:
        # Get current task status
        status = await call_claudetm_tool("get_status")
        print(f"Goal: {status['goal']}")
        print(f"Status: {status['status']}")
        print(f"Sessions: {status['session_count']}/{status['max_sessions']}")

        # Start a new task
        result = await call_claudetm_tool(
            "start_task",
            {
                "goal": "Add feature X to the codebase",
                "model": "sonnet",
                "max_sessions": 10,
                "auto_merge": False
            }
        )
        print(f"Task started: {result}")

    except ValueError as e:
        logger.error(f"Authentication error: {e}")
    except ConnectionError as e:
        logger.error(f"Connection error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
```

#### TypeScript/JavaScript MCP Client

**Using @modelcontextprotocol/sdk:**

```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";

async function main() {
  const password = process.env.CLAUDETM_PASSWORD || "your-secure-password";

  // Create SSE transport with authentication
  const transport = new SSEClientTransport(
    new URL("http://localhost:8080/sse"),
    {
      headers: {
        "Authorization": `Bearer ${password}`
      }
    }
  );

  // Create client and connect
  const client = new Client(
    {
      name: "my-client",
      version: "1.0.0"
    },
    {
      capabilities: {}
    }
  );

  await client.connect(transport);

  try {
    // List available tools
    const tools = await client.listTools();
    console.log("Available tools:", tools.tools.map(t => t.name));

    // Call get_status tool
    const status = await client.callTool({
      name: "get_status",
      arguments: {}
    });
    console.log("Task status:", status);

    // Start a new task
    const result = await client.callTool({
      name: "start_task",
      arguments: {
        goal: "Implement feature X",
        model: "sonnet",
        max_sessions: 10,
        auto_merge: false
      }
    });
    console.log("Task started:", result);

  } finally {
    await client.close();
  }
}

main().catch(console.error);
```

**Using fetch API (manual HTTP):**

```typescript
interface MCPRequest {
  jsonrpc: "2.0";
  id: string | number;
  method: string;
  params?: any;
}

interface MCPResponse {
  jsonrpc: "2.0";
  id: string | number;
  result?: any;
  error?: {
    code: number;
    message: string;
    data?: any;
  };
}

async function callMCPTool(
  toolName: string,
  args: Record<string, any> = {},
  password: string = process.env.CLAUDETM_PASSWORD || ""
): Promise<any> {
  const request: MCPRequest = {
    jsonrpc: "2.0",
    id: Date.now(),
    method: "tools/call",
    params: {
      name: toolName,
      arguments: args
    }
  };

  const response = await fetch("http://localhost:8080/sse", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${password}`
    },
    body: JSON.stringify(request)
  });

  if (response.status === 401) {
    throw new Error("Authentication required - missing or invalid password");
  }
  if (response.status === 403) {
    throw new Error("Invalid password");
  }
  if (!response.ok) {
    throw new Error(`HTTP error ${response.status}: ${response.statusText}`);
  }

  const data: MCPResponse = await response.json();

  if (data.error) {
    throw new Error(`MCP error: ${data.error.message}`);
  }

  return data.result;
}

// Usage
async function example() {
  try {
    const status = await callMCPTool("get_status");
    console.log("Task status:", status);
  } catch (error) {
    console.error("Error:", error.message);
  }
}
```

#### Manual HTTP Requests (curl)

For debugging or testing, you can manually call MCP SSE endpoints:

```bash
# Set password
export PASSWORD="your-secure-password"

# Initialize MCP session (SSE endpoint)
curl -N \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Accept: text/event-stream" \
  http://localhost:8080/sse

# Call tool via JSON-RPC
curl -X POST \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_status",
      "arguments": {}
    }
  }' \
  http://localhost:8080/sse

# List available tools
curl -X POST \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
  }' \
  http://localhost:8080/sse
```

#### Configuration Best Practices

**1. Local Development (stdio):**
```json
{
  "mcpServers": {
    "claudetm": {
      "command": "claudetm-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```
- ✅ Most secure (no network exposure)
- ✅ No authentication needed
- ✅ Lowest latency
- ❌ Only works on same machine

**2. Local Network (SSE with auth):**
```json
{
  "mcpServers": {
    "claudetm": {
      "command": "claudetm-mcp",
      "args": ["--transport", "sse", "--host", "localhost", "--port", "8080"],
      "env": {"CLAUDETM_PASSWORD": "dev-password"}
    }
  }
}
```
- ✅ Works across containers/VMs on same host
- ✅ Simple password authentication
- ❌ Password in config file (use for dev only)

**3. Remote Server (SSE with hash):**
```json
{
  "mcpServers": {
    "claudetm": {
      "command": "claudetm-mcp",
      "args": ["--transport", "sse", "--host", "remote.internal", "--port", "8080"],
      "env": {"CLAUDETM_PASSWORD_HASH": "$2b$12$..."}
    }
  }
}
```
- ✅ Secure for production
- ✅ Password hash (not plaintext)
- ✅ Works across network
- ⚠️ Requires TLS/VPN for security

**4. Production (SSE with TLS):**
```bash
# Server side: Use reverse proxy (nginx/caddy) for TLS
# Client side config:
{
  "mcpServers": {
    "claudetm": {
      "command": "claudetm-mcp",
      "args": ["--transport", "sse", "--host", "claudetm.example.com", "--port", "443"],
      "env": {
        "CLAUDETM_PASSWORD_HASH": "$2b$12$...",
        "CLAUDETM_TLS": "true"
      }
    }
  }
}
```
- ✅ Production-ready
- ✅ TLS encryption
- ✅ Password authentication
- ✅ Can cross internet securely

### MCP Authentication Flow

```
1. Client connects to MCP SSE/HTTP endpoint
   ↓
2. Starlette middleware intercepts request
   ↓
3. Authorization header checked (if auth enabled)
   ↓
4. Password verified against configured value
   ↓
5. If valid: MCP protocol handler processes request
   If invalid: 401/403 response
```

### Security Warnings

When starting MCP server, authentication status is logged:

```bash
# Without authentication on localhost
⚠️  MCP server running without authentication. This is acceptable for localhost
   but consider enabling authentication for security.

# Without authentication on non-localhost
⚠️  MCP server binding to non-localhost address (0.0.0.0) without authentication.
   This is a security risk. Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH.

# With authentication
✅ MCP server authentication enabled
```

## Webhook Authentication

Webhooks use **HMAC-SHA256 signatures** to authenticate outgoing notifications, allowing recipients to verify payload integrity and authenticity.

### Webhook Signature Generation

When a webhook is configured with a secret, Claude Task Master automatically signs each payload:

```python
# Configure webhook with secret
claudetm start "my task" \
  --webhook-url https://example.com/webhook \
  --webhook-secret "shared-secret-key"
```

Each webhook request includes these headers:

```
X-Webhook-Signature: sha256=<hmac-hex>
X-Webhook-Signature-256: sha256=<timestamp-hmac-hex>
X-Webhook-Timestamp: <unix-timestamp>
X-Webhook-Event: <event-type>
X-Webhook-Delivery-Id: <unique-id>
```

### Signature Calculation

**Simple Signature** (`X-Webhook-Signature`):
```
HMAC-SHA256(secret, json_payload)
```

**Timestamped Signature** (`X-Webhook-Signature-256`) - Prevents replay attacks:
```
HMAC-SHA256(secret, timestamp + "." + json_payload)
```

### Verifying Webhook Signatures

All webhook payloads include HMAC-SHA256 signatures that you should verify to ensure authenticity. Below are complete, production-ready examples for common languages and frameworks.

#### Overview of Signature Headers

Every webhook request includes:

```
X-Webhook-Signature: sha256=<hmac-hex>                    # Simple signature (backward compat)
X-Webhook-Signature-256: sha256=<timestamp-hmac-hex>      # Timestamped signature (recommended)
X-Webhook-Timestamp: <unix-timestamp>                      # Request timestamp
X-Webhook-Event: <event-type>                              # Event type
X-Webhook-Delivery-Id: <unique-id>                         # Unique delivery ID
```

**Always use `X-Webhook-Signature-256`** (timestamped) to prevent replay attacks.

---

#### Python Examples

##### Standalone Verification Function

```python
import hmac
import hashlib
import time
from typing import Optional


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
    timestamp: Optional[str] = None,
    max_age: int = 300  # 5 minutes
) -> bool:
    """Verify webhook HMAC-SHA256 signature.

    Args:
        payload: Raw request body (bytes) - use request.get_data() in Flask
        signature: X-Webhook-Signature-256 header value
        secret: Shared webhook secret (configured when creating webhook)
        timestamp: X-Webhook-Timestamp header value
        max_age: Maximum age of webhook in seconds (default 300 = 5 min)

    Returns:
        True if signature is valid and fresh, False otherwise

    Example:
        >>> payload = b'{"type": "task.completed", "data": {...}}'
        >>> signature = "sha256=abc123..."
        >>> secret = "my-webhook-secret"
        >>> timestamp = "1704117600"
        >>> verify_webhook_signature(payload, signature, secret, timestamp)
        True
    """
    # 1. Check timestamp freshness (prevent replay attacks)
    if timestamp:
        webhook_time = int(timestamp)
        current_time = int(time.time())
        age = abs(current_time - webhook_time)
        if age > max_age:
            print(f"Webhook too old: {age}s > {max_age}s")
            return False

    # 2. Remove "sha256=" prefix if present
    if signature.startswith("sha256="):
        signature = signature[7:]

    # 3. Calculate expected signature
    if timestamp:
        # Timestamped signature (recommended - includes timestamp in HMAC)
        signed_payload = f"{timestamp}.".encode() + payload
    else:
        # Simple signature (for backward compatibility)
        signed_payload = payload

    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256
    ).hexdigest()

    # 4. Constant-time comparison (prevents timing attacks)
    return hmac.compare_digest(signature, expected)
```

##### Flask Example

```python
from flask import Flask, request, jsonify
import logging

app = Flask(__name__)
WEBHOOK_SECRET = "your-shared-secret"  # Match secret from webhook config

logger = logging.getLogger(__name__)


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    """Handle incoming Claude Task Master webhooks."""
    # Get headers
    signature = request.headers.get("X-Webhook-Signature-256")
    timestamp = request.headers.get("X-Webhook-Timestamp")
    event_type = request.headers.get("X-Webhook-Event")
    delivery_id = request.headers.get("X-Webhook-Delivery-Id")

    # Validate signature presence
    if not signature:
        logger.warning("Webhook received without signature")
        return jsonify({"error": "Missing signature"}), 401

    # Verify signature (use raw bytes, NOT parsed JSON!)
    if not verify_webhook_signature(
        request.get_data(),  # Raw bytes - important!
        signature,
        WEBHOOK_SECRET,
        timestamp
    ):
        logger.warning(f"Invalid webhook signature for delivery {delivery_id}")
        return jsonify({"error": "Invalid signature"}), 403

    # Parse and process webhook
    try:
        event = request.json
        logger.info(f"Webhook received: {event_type} (delivery: {delivery_id})")

        # Handle different event types
        if event_type == "task.completed":
            handle_task_completed(event)
        elif event_type == "task.failed":
            handle_task_failed(event)
        elif event_type == "pr.created":
            handle_pr_created(event)
        else:
            logger.warning(f"Unknown event type: {event_type}")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({"error": "Internal error"}), 500


def handle_task_completed(event: dict):
    """Process task.completed event."""
    task_id = event["data"]["task_id"]
    commit = event["data"].get("commit_hash", "N/A")
    print(f"Task {task_id} completed! Commit: {commit}")


def handle_task_failed(event: dict):
    """Process task.failed event."""
    task_id = event["data"]["task_id"]
    error = event["data"].get("error", "Unknown error")
    print(f"Task {task_id} failed: {error}")


def handle_pr_created(event: dict):
    """Process pr.created event."""
    pr_url = event["data"].get("pr_url", "N/A")
    print(f"PR created: {pr_url}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

##### FastAPI Example

```python
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional
import logging

app = FastAPI()
WEBHOOK_SECRET = "your-shared-secret"

logger = logging.getLogger(__name__)


@app.post("/webhook")
async def handle_webhook(
    request: Request,
    x_webhook_signature_256: Optional[str] = Header(None),
    x_webhook_timestamp: Optional[str] = Header(None),
    x_webhook_event: Optional[str] = Header(None),
    x_webhook_delivery_id: Optional[str] = Header(None),
):
    """Handle Claude Task Master webhook."""
    # Validate signature
    if not x_webhook_signature_256:
        raise HTTPException(status_code=401, detail="Missing signature")

    # Get raw body
    body = await request.body()

    # Verify signature
    if not verify_webhook_signature(
        body,
        x_webhook_signature_256,
        WEBHOOK_SECRET,
        x_webhook_timestamp
    ):
        logger.warning(f"Invalid signature for delivery {x_webhook_delivery_id}")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Process event
    event = await request.json()
    logger.info(f"Received {x_webhook_event}: delivery {x_webhook_delivery_id}")

    # Handle event
    if x_webhook_event == "task.completed":
        # Your logic here
        pass

    return {"status": "success"}
```

---

#### Node.js Examples

##### Standalone Verification Function

```javascript
const crypto = require('crypto');

/**
 * Verify webhook HMAC-SHA256 signature
 *
 * @param {string|Buffer} payload - Raw request body (string or Buffer)
 * @param {string} signature - X-Webhook-Signature-256 header value
 * @param {string} secret - Shared webhook secret
 * @param {string} [timestamp] - X-Webhook-Timestamp header value
 * @param {number} [maxAge=300] - Maximum age in seconds (default 5 min)
 * @returns {boolean} True if signature is valid and fresh
 *
 * @example
 * const payload = '{"type": "task.completed"}';
 * const signature = "sha256=abc123...";
 * const secret = "my-webhook-secret";
 * const timestamp = "1704117600";
 *
 * if (verifyWebhookSignature(payload, signature, secret, timestamp)) {
 *   console.log("Webhook verified!");
 * }
 */
function verifyWebhookSignature(payload, signature, secret, timestamp, maxAge = 300) {
  // 1. Check timestamp freshness (prevent replay attacks)
  if (timestamp) {
    const webhookTime = parseInt(timestamp, 10);
    const currentTime = Math.floor(Date.now() / 1000);
    const age = Math.abs(currentTime - webhookTime);

    if (age > maxAge) {
      console.warn(`Webhook too old: ${age}s > ${maxAge}s`);
      return false;
    }
  }

  // 2. Remove "sha256=" prefix if present
  const providedSig = signature.startsWith('sha256=')
    ? signature.substring(7)
    : signature;

  // 3. Calculate expected signature
  const signedPayload = timestamp
    ? `${timestamp}.${payload}`  // Timestamped (recommended)
    : payload;                    // Simple (backward compat)

  const expected = crypto
    .createHmac('sha256', secret)
    .update(signedPayload)
    .digest('hex');

  // 4. Constant-time comparison (prevents timing attacks)
  // Both buffers must be same length for timingSafeEqual
  if (providedSig.length !== expected.length) {
    return false;
  }

  return crypto.timingSafeEqual(
    Buffer.from(providedSig, 'hex'),
    Buffer.from(expected, 'hex')
  );
}

module.exports = { verifyWebhookSignature };
```

##### Express.js Example

```javascript
const express = require('express');
const crypto = require('crypto');

const app = express();
const WEBHOOK_SECRET = 'your-shared-secret';  // Match webhook config

// IMPORTANT: Use raw body parser for signature verification
app.post('/webhook', express.raw({ type: 'application/json' }), (req, res) => {
  // Get headers
  const signature = req.headers['x-webhook-signature-256'];
  const timestamp = req.headers['x-webhook-timestamp'];
  const eventType = req.headers['x-webhook-event'];
  const deliveryId = req.headers['x-webhook-delivery-id'];

  // Validate signature
  if (!signature) {
    console.warn('Webhook received without signature');
    return res.status(401).json({ error: 'Missing signature' });
  }

  // Verify signature (use raw body!)
  const isValid = verifyWebhookSignature(
    req.body.toString(),  // Convert Buffer to string
    signature,
    WEBHOOK_SECRET,
    timestamp
  );

  if (!isValid) {
    console.warn(`Invalid signature for delivery ${deliveryId}`);
    return res.status(403).json({ error: 'Invalid signature' });
  }

  // Parse and process webhook
  try {
    const event = JSON.parse(req.body);
    console.log(`Webhook received: ${eventType} (delivery: ${deliveryId})`);

    // Handle different event types
    switch (eventType) {
      case 'task.completed':
        handleTaskCompleted(event);
        break;
      case 'task.failed':
        handleTaskFailed(event);
        break;
      case 'pr.created':
        handlePrCreated(event);
        break;
      default:
        console.warn(`Unknown event type: ${eventType}`);
    }

    res.json({ status: 'success' });

  } catch (error) {
    console.error('Error processing webhook:', error);
    res.status(500).json({ error: 'Internal error' });
  }
});

function handleTaskCompleted(event) {
  const taskId = event.data.task_id;
  const commit = event.data.commit_hash || 'N/A';
  console.log(`Task ${taskId} completed! Commit: ${commit}`);
}

function handleTaskFailed(event) {
  const taskId = event.data.task_id;
  const error = event.data.error || 'Unknown error';
  console.log(`Task ${taskId} failed: ${error}`);
}

function handlePrCreated(event) {
  const prUrl = event.data.pr_url || 'N/A';
  console.log(`PR created: ${prUrl}`);
}

app.listen(3000, () => {
  console.log('Webhook server listening on port 3000');
});
```

##### Next.js API Route Example

```javascript
// pages/api/webhook.js (or app/api/webhook/route.js for App Router)
import crypto from 'crypto';

export const config = {
  api: {
    bodyParser: false,  // Disable body parser to get raw body
  },
};

async function getRawBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function verifyWebhookSignature(payload, signature, secret, timestamp, maxAge = 300) {
  // Check timestamp
  if (timestamp) {
    const webhookTime = parseInt(timestamp, 10);
    const currentTime = Math.floor(Date.now() / 1000);
    if (Math.abs(currentTime - webhookTime) > maxAge) {
      return false;
    }
  }

  // Remove prefix
  const providedSig = signature.startsWith('sha256=')
    ? signature.substring(7)
    : signature;

  // Calculate expected
  const signedPayload = timestamp ? `${timestamp}.${payload}` : payload;
  const expected = crypto
    .createHmac('sha256', secret)
    .update(signedPayload)
    .digest('hex');

  // Compare
  return crypto.timingSafeEqual(
    Buffer.from(providedSig, 'hex'),
    Buffer.from(expected, 'hex')
  );
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const signature = req.headers['x-webhook-signature-256'];
  const timestamp = req.headers['x-webhook-timestamp'];

  if (!signature) {
    return res.status(401).json({ error: 'Missing signature' });
  }

  // Get raw body
  const rawBody = await getRawBody(req);

  // Verify signature
  if (!verifyWebhookSignature(
    rawBody.toString(),
    signature,
    process.env.WEBHOOK_SECRET,
    timestamp
  )) {
    return res.status(403).json({ error: 'Invalid signature' });
  }

  // Process webhook
  const event = JSON.parse(rawBody);
  console.log('Webhook received:', event.type);

  res.status(200).json({ status: 'success' });
}
```

---

#### TypeScript Example

```typescript
import crypto from 'crypto';
import express, { Request, Response } from 'express';

interface WebhookEvent {
  type: string;
  timestamp: string;
  data: Record<string, any>;
}

const WEBHOOK_SECRET = process.env.WEBHOOK_SECRET || 'your-shared-secret';

/**
 * Verify webhook HMAC signature
 */
function verifyWebhookSignature(
  payload: string,
  signature: string,
  secret: string,
  timestamp?: string,
  maxAge: number = 300
): boolean {
  // Check timestamp freshness
  if (timestamp) {
    const webhookTime = parseInt(timestamp, 10);
    const currentTime = Math.floor(Date.now() / 1000);
    const age = Math.abs(currentTime - webhookTime);

    if (age > maxAge) {
      console.warn(`Webhook expired: ${age}s > ${maxAge}s`);
      return false;
    }
  }

  // Remove sha256= prefix
  const providedSig = signature.startsWith('sha256=')
    ? signature.substring(7)
    : signature;

  // Calculate expected signature
  const signedPayload = timestamp ? `${timestamp}.${payload}` : payload;
  const expected = crypto
    .createHmac('sha256', secret)
    .update(signedPayload)
    .digest('hex');

  // Constant-time comparison
  if (providedSig.length !== expected.length) {
    return false;
  }

  return crypto.timingSafeEqual(
    Buffer.from(providedSig, 'hex'),
    Buffer.from(expected, 'hex')
  );
}

const app = express();

app.post('/webhook', express.raw({ type: 'application/json' }), (req: Request, res: Response) => {
  const signature = req.headers['x-webhook-signature-256'] as string;
  const timestamp = req.headers['x-webhook-timestamp'] as string;
  const eventType = req.headers['x-webhook-event'] as string;

  if (!signature) {
    return res.status(401).json({ error: 'Missing signature' });
  }

  if (!verifyWebhookSignature(req.body.toString(), signature, WEBHOOK_SECRET, timestamp)) {
    return res.status(403).json({ error: 'Invalid signature' });
  }

  const event: WebhookEvent = JSON.parse(req.body.toString());
  console.log(`Received ${eventType}:`, event);

  res.json({ status: 'success' });
});

app.listen(3000, () => console.log('Webhook server running on port 3000'));
```

---

#### Testing Your Webhook Endpoint

##### Using curl

```bash
# Set your secret
SECRET="your-webhook-secret"
TIMESTAMP=$(date +%s)
PAYLOAD='{"type":"test","data":{}}'

# Calculate signature (bash with openssl)
SIGNATURE=$(echo -n "${TIMESTAMP}.${PAYLOAD}" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

# Send test webhook
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Signature-256: sha256=$SIGNATURE" \
  -H "X-Webhook-Timestamp: $TIMESTAMP" \
  -H "X-Webhook-Event: test" \
  -H "X-Webhook-Delivery-Id: test-123" \
  -d "$PAYLOAD"
```

##### Using Python

```python
import requests
import hmac
import hashlib
import time
import json

def send_test_webhook(url: str, secret: str):
    """Send a test webhook with valid signature."""
    payload = {"type": "test", "data": {}}
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()

    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.".encode() + payload_bytes

    signature = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256
    ).hexdigest()

    response = requests.post(
        url,
        json=payload,
        headers={
            "X-Webhook-Signature-256": f"sha256={signature}",
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Event": "test",
            "X-Webhook-Delivery-Id": "test-123"
        }
    )

    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

# Test
send_test_webhook("http://localhost:8080/webhook", "your-shared-secret")
```

---

#### Common Pitfalls

1. **Using parsed JSON instead of raw body**
   - ❌ `hmac.new(secret, json.dumps(request.json))`
   - ✅ `hmac.new(secret, request.get_data())`

2. **Not using constant-time comparison**
   - ❌ `signature == expected`
   - ✅ `hmac.compare_digest(signature, expected)`

3. **Forgetting the timestamp in signature**
   - ❌ `hmac.new(secret, payload)`
   - ✅ `hmac.new(secret, f"{timestamp}.".encode() + payload)`

4. **Not checking timestamp freshness**
   - Always validate timestamp to prevent replay attacks

5. **Buffer length mismatch in Node.js**
   - Check lengths before `crypto.timingSafeEqual()`

### Webhook Event Types

Claude Task Master sends these webhook events:

| Event Type | Description | When Sent |
|------------|-------------|-----------|
| `task.started` | Task execution started | Beginning of task work |
| `task.completed` | Task completed successfully | After task completion |
| `task.failed` | Task failed or blocked | On task failure |
| `pr.created` | Pull request created | After PR creation |
| `pr.merged` | Pull request merged | After successful merge |
| `session.started` | Work session started | Start of orchestrator session |
| `session.completed` | Work session completed | End of orchestrator session |

### Webhook Payload Structure

```json
{
  "type": "task.completed",
  "timestamp": "2024-01-15T10:30:00Z",
  "data": {
    "task_id": "53",
    "task_description": "Create authentication.md documentation",
    "status": "completed",
    "session_id": "abc123",
    "commit_hash": "a1b2c3d4"
  }
}
```

## Security Best Practices

### Password Management

1. **Use Strong Passwords**
   - Minimum 16 characters
   - Mix of letters, numbers, and symbols
   - Generate with password manager

2. **Production Deployments**
   - Always use `CLAUDETM_PASSWORD_HASH` (never plaintext)
   - Store hashes in secrets management (AWS Secrets Manager, HashiCorp Vault)
   - Rotate passwords regularly

3. **Environment Isolation**
   - Different passwords for dev/staging/production
   - Never commit passwords to version control
   - Use `.env` files (add to `.gitignore`)

### Network Security

1. **TLS/SSL**
   - Use HTTPS for REST API in production
   - Use WSS (WebSocket Secure) for MCP SSE
   - Configure reverse proxy (nginx, Caddy) for TLS termination

2. **Firewall Rules**
   - Restrict port access (8000, 8080) to trusted networks
   - Use VPN for remote MCP access
   - Implement rate limiting

3. **Docker Security**
   - Run containers as non-root user (done by default)
   - Use read-only volumes where possible
   - Scan images for vulnerabilities

### Webhook Security

1. **Always Use Secrets**
   - Configure `webhook_secret` for all webhooks
   - Use different secrets for different environments
   - Rotate secrets periodically

2. **Verify Signatures**
   - Always verify `X-Webhook-Signature-256` in webhook receivers
   - Check timestamp to prevent replay attacks
   - Use constant-time comparison

3. **HTTPS Only**
   - Only send webhooks to HTTPS endpoints
   - Verify SSL certificates (`verify_ssl=True`)

### Monitoring and Logging

1. **Failed Authentication Attempts**
   - Monitor logs for 401/403 errors
   - Set up alerts for repeated failures
   - Log source IPs

2. **Audit Trail**
   - Log all authenticated actions
   - Include user/source in logs
   - Retain logs for compliance

## Troubleshooting

### Common Issues

#### "Not authenticated" Error (401)

**Problem:** Missing or malformed Authorization header

**Solutions:**
```bash
# Ensure header is included
curl -H "Authorization: Bearer your-password" http://localhost:8000/status

# Check for typos in "Bearer" (case-sensitive)
# ❌ Wrong: "authorization: bearer password"
# ✅ Correct: "Authorization: Bearer password"
```

#### "Invalid credentials" Error (403)

**Problem:** Password is incorrect

**Solutions:**
```bash
# Verify password matches environment variable
echo $CLAUDETM_PASSWORD

# Check for trailing spaces/newlines
export CLAUDETM_PASSWORD="password"  # No quotes in actual usage

# For hashed passwords, ensure full hash is used
export CLAUDETM_PASSWORD_HASH='$2b$12$...'  # Single quotes prevent shell expansion
```

#### "Authentication configuration error" (500)

**Problem:** Server requires authentication but no password is configured

**Solutions:**
```bash
# Set password before starting server
export CLAUDETM_PASSWORD="your-password"
claudetm-server

# Or pass via command line (not recommended for production)
CLAUDETM_PASSWORD="password" claudetm-server
```

#### bcrypt Import Error

**Problem:** `passlib[bcrypt]` not installed

**Solutions:**
```bash
# Install API dependencies
pip install 'claude-task-master[api]'

# Or install passlib directly
pip install 'passlib[bcrypt]'
```

#### Webhook Signature Verification Failed

**Problem:** HMAC signature doesn't match

**Solutions:**
```python
# Ensure you're using the raw request body (bytes)
payload = request.get_data()  # Not request.json

# Use X-Webhook-Signature-256 (includes timestamp)
signature = request.headers.get("X-Webhook-Signature-256")

# Verify timestamp is included in signature calculation
signed_payload = f"{timestamp}.".encode() + payload

# Check secret matches on both sides
print(f"Server secret: {WEBHOOK_SECRET}")
```

### Testing Authentication

#### Test REST API Authentication

```bash
# Without authentication (should fail)
curl http://localhost:8000/status
# Expected: 401 Unauthorized

# With correct password
curl -H "Authorization: Bearer your-password" http://localhost:8000/status
# Expected: 200 OK with status JSON

# With wrong password
curl -H "Authorization: Bearer wrong" http://localhost:8000/status
# Expected: 403 Forbidden
```

#### Test Webhook Signatures

```python
from claude_task_master.webhooks.client import generate_signature, verify_signature

# Generate signature
payload = b'{"type": "test"}'
secret = "test-secret"
signature = generate_signature(payload, secret)
print(f"Signature: {signature}")

# Verify signature
is_valid = verify_signature(payload, secret, signature)
print(f"Valid: {is_valid}")  # Should be True
```

### Debug Logging

Enable debug logging to troubleshoot authentication issues:

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Or for specific module
logging.getLogger("claude_task_master.auth").setLevel(logging.DEBUG)
```

Look for these log messages:
```
DEBUG:claude_task_master.auth.middleware:PasswordAuthMiddleware initialized: require_auth=True
DEBUG:claude_task_master.auth.middleware:Missing or invalid Authorization header for GET /status
DEBUG:claude_task_master.auth.middleware:Authentication successful for GET /status
WARNING:claude_task_master.auth.middleware:Invalid password attempt for POST /webhooks
```

## Related Documentation

- [Docker Deployment Guide](docker.md) - Docker setup with authentication
- [API Reference](api-reference.md) - REST API endpoint documentation
- [Webhooks Guide](webhooks.md) - Webhook events and configuration
- [Security Policy](../SECURITY.md) - Security measures and reporting

## Support

For authentication issues:
1. Check this troubleshooting guide
2. Review server logs with debug logging enabled
3. Open an issue on [GitHub](https://github.com/developerz-ai/claude-task-master/issues)
