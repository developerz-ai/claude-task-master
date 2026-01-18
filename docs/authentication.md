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

```bash
# Set your password
PASSWORD="your-secure-password"

# Make authenticated request
curl -H "Authorization: Bearer $PASSWORD" \
  http://localhost:8000/status

# Example with JSON payload
curl -X POST \
  -H "Authorization: Bearer $PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{"webhook_url": "https://example.com/webhook"}' \
  http://localhost:8000/webhooks
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

#### Claude Desktop Configuration

For stdio transport (no authentication):

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

For SSE transport with authentication:

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
        "CLAUDETM_PASSWORD": "your-secure-password"
      }
    }
  }
}
```

#### Python MCP Client

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# For stdio (no auth needed)
server_params = StdioServerParameters(
    command="claudetm-mcp",
    args=["--transport", "stdio"]
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        # Use session...
```

For network transports, add authentication header to the HTTP client.

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

#### Python Example

```python
import hmac
import hashlib
import json
import time

def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
    timestamp: str = None,
    max_age: int = 300  # 5 minutes
) -> bool:
    """Verify webhook HMAC signature.

    Args:
        payload: Raw request body (bytes)
        signature: X-Webhook-Signature-256 header value
        secret: Shared webhook secret
        timestamp: X-Webhook-Timestamp header value
        max_age: Maximum age of webhook in seconds (default 300)

    Returns:
        True if signature is valid, False otherwise
    """
    # Check timestamp freshness (prevent replay attacks)
    if timestamp:
        webhook_time = int(timestamp)
        current_time = int(time.time())
        if abs(current_time - webhook_time) > max_age:
            return False

    # Remove "sha256=" prefix if present
    if signature.startswith("sha256="):
        signature = signature[7:]

    # Calculate expected signature
    if timestamp:
        # Timestamped signature (recommended)
        signed_payload = f"{timestamp}.".encode() + payload
    else:
        # Simple signature
        signed_payload = payload

    expected = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256
    ).hexdigest()

    # Constant-time comparison
    return hmac.compare_digest(signature, expected)

# Example usage in Flask/FastAPI
from flask import Flask, request

app = Flask(__name__)
WEBHOOK_SECRET = "your-shared-secret"

@app.route("/webhook", methods=["POST"])
def handle_webhook():
    # Get signature and timestamp from headers
    signature = request.headers.get("X-Webhook-Signature-256")
    timestamp = request.headers.get("X-Webhook-Timestamp")

    if not signature:
        return {"error": "Missing signature"}, 401

    # Verify signature
    if not verify_webhook_signature(
        request.get_data(),
        signature,
        WEBHOOK_SECRET,
        timestamp
    ):
        return {"error": "Invalid signature"}, 403

    # Process webhook
    event = request.json
    print(f"Received event: {event['type']}")

    return {"status": "success"}
```

#### Node.js Example

```javascript
const crypto = require('crypto');
const express = require('express');

const app = express();
const WEBHOOK_SECRET = 'your-shared-secret';

function verifyWebhookSignature(payload, signature, secret, timestamp, maxAge = 300) {
  // Check timestamp freshness
  if (timestamp) {
    const webhookTime = parseInt(timestamp);
    const currentTime = Math.floor(Date.now() / 1000);
    if (Math.abs(currentTime - webhookTime) > maxAge) {
      return false;
    }
  }

  // Remove "sha256=" prefix
  const providedSig = signature.startsWith('sha256=')
    ? signature.substring(7)
    : signature;

  // Calculate expected signature
  const signedPayload = timestamp
    ? `${timestamp}.${payload}`
    : payload;

  const expected = crypto
    .createHmac('sha256', secret)
    .update(signedPayload)
    .digest('hex');

  // Constant-time comparison
  return crypto.timingSafeEqual(
    Buffer.from(providedSig),
    Buffer.from(expected)
  );
}

app.post('/webhook', express.raw({ type: 'application/json' }), (req, res) => {
  const signature = req.headers['x-webhook-signature-256'];
  const timestamp = req.headers['x-webhook-timestamp'];

  if (!signature) {
    return res.status(401).json({ error: 'Missing signature' });
  }

  // Verify signature
  if (!verifyWebhookSignature(
    req.body.toString(),
    signature,
    WEBHOOK_SECRET,
    timestamp
  )) {
    return res.status(403).json({ error: 'Invalid signature' });
  }

  // Process webhook
  const event = JSON.parse(req.body);
  console.log(`Received event: ${event.type}`);

  res.json({ status: 'success' });
});

app.listen(3000);
```

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
