# Docker Deployment Guide

This guide covers deploying Claude Task Master using Docker, including the unified server that runs both the REST API and MCP server with shared authentication.

## Table of Contents

- [Quick Start](#quick-start)
- [Installation](#installation)
- [Docker Image](#docker-image)
- [Volume Mounts](#volume-mounts)
- [Environment Variables](#environment-variables)
- [Authentication](#authentication)
- [Docker Compose](#docker-compose)
- [Production Deployment](#production-deployment)
- [Troubleshooting](#troubleshooting)

## Quick Start

> [!WARNING]
> These examples mount your personal `~/.claude` credentials into the container — fine for running
> locally on your own machine, but **not** for shared, unattended, or multi-tenant hosts, where it
> leaks a human's billable OAuth token. See [Claude Credentials](#1-claude-credentials-claude) and
> [Authentication direction](#authentication-direction).

The fastest way to get started with Claude Task Master in Docker:

```bash
# Pull the image from GitHub Container Registry
docker pull ghcr.io/developerz-ai/claude-task-master:latest

# Run with default settings (no auth, development only)
docker run -d \
  --name claudetm \
  -p 8000:8000 \
  -p 8080:8080 \
  -v ~/.claude:/home/claudetm/.claude:ro \
  -v $(pwd):/app/project \
  -v ~/.gitconfig:/home/claudetm/.gitconfig:ro \
  -v ~/.config/gh:/home/claudetm/.config/gh:ro \
  ghcr.io/developerz-ai/claude-task-master:latest

# Check logs
docker logs -f claudetm

# Access the services
# REST API: http://localhost:8000
# API Docs: http://localhost:8000/docs
# MCP Server: http://localhost:8080/sse
```

**⚠️ Security Warning:** Always use password authentication in production!

```bash
# Production deployment with authentication
docker run -d \
  --name claudetm \
  -p 8000:8000 \
  -p 8080:8080 \
  -e CLAUDETM_PASSWORD=your-secure-password \
  -v ~/.claude:/home/claudetm/.claude:ro \
  -v $(pwd):/app/project \
  -v ~/.gitconfig:/home/claudetm/.gitconfig:ro \
  -v ~/.config/gh:/home/claudetm/.config/gh:ro \
  ghcr.io/developerz-ai/claude-task-master:latest
```

## Installation

### Option 1: Pull from GitHub Container Registry (Recommended)

Images are automatically published to GitHub Container Registry on each release:

```bash
# Pull latest stable version
docker pull ghcr.io/developerz-ai/claude-task-master:latest

# Pull specific version
docker pull ghcr.io/developerz-ai/claude-task-master:1.0.0

# Pull specific version with architecture
docker pull --platform linux/amd64 ghcr.io/developerz-ai/claude-task-master:latest
```

**Available Platforms:**
- `linux/amd64` - x86_64 architecture (Intel/AMD)
- `linux/arm64` - ARM64 architecture (Apple Silicon, ARM servers)

### Option 2: Build from Source

Build the Docker image locally from the repository:

```bash
# Clone the repository
git clone https://github.com/developerz-ai/claude-task-master.git
cd claude-task-master

# Build the image
docker build -t claudetm .

# Build with specific version metadata
docker build \
  --build-arg VERSION=1.0.0 \
  --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
  --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
  -t claudetm .

# Build for specific platform
docker build --platform linux/amd64 -t claudetm .
```

## Docker Image

### Image Details

- **Base Image:** `python:3.12-slim`
- **Size:** ~300MB (multi-stage build for optimization)
- **User:** Non-root user `claudetm` (UID 1000, GID 1000)
- **Working Directory:** `/app/project`
- **Entry Point:** `claudetm-server` (unified REST + MCP server)

### Multi-Stage Build

The Dockerfile uses a multi-stage build for optimal image size and security:

1. **Builder Stage** - Installs dependencies and packages
2. **Runtime Stage** - Minimal production image with only required files

### Labels and Metadata

Images include OCI-compliant labels for version tracking:

```bash
# Inspect image metadata
docker inspect ghcr.io/developerz-ai/claude-task-master:latest | jq '.[0].Config.Labels'
```

### Health Check

The image includes a built-in health check:

```bash
# Check container health
docker ps --filter name=claudetm --format "{{.Status}}"

# Manual health check
docker exec claudetm curl -f http://localhost:8000/health
```

## Volume Mounts

Claude Task Master requires several volume mounts to function properly. Understanding these volumes is critical for proper deployment.

### Required Volumes

#### 1. Claude Credentials (`~/.claude`)

> [!WARNING]
> **Mounting a human operator's `~/.claude` shares their personal OAuth bearer token with the
> container.** The agent then runs as — and bills — that person's Claude account, and anything that
> reads the container filesystem can read the token. This is acceptable only for a **single operator
> running locally on their own machine**.
>
> **Do not** use this mount for shared, unattended, multi-tenant, or CI deployments: a human's
> subscription token is not a per-consumer credential and cannot be scoped or rotated independently.
> The intended direction for unattended deployments is to authenticate through a central Claude proxy
> with a **scoped, rotatable credential issued per consumer** — never a human's subscription token.
> See [Authentication direction](#authentication-direction) below.

**Purpose:** OAuth tokens for Claude Code subscription

**Mount:** `~/.claude:/home/claudetm/.claude:ro`

**Read-only:** ✅ Yes (credentials are only read, never modified)

**⚠️ Required for Claude Code Subscription**

The Claude credentials directory contains your Claude Code subscription authentication tokens. This is **required** for the server to authenticate with Claude's API on your behalf. Without these credentials, the server cannot access Claude's agent capabilities.

**Why This is Needed:**
- Claude Task Master uses the Claude Agent SDK to execute tasks
- The SDK requires valid OAuth tokens from your Claude Code subscription
- These tokens are stored in `~/.claude/.credentials.json` by the Claude CLI
- The Docker container needs read access to these credentials to function

**Structure:**
```
~/.claude/
├── .credentials.json    # OAuth tokens (accessToken, refreshToken, expiresAt)
└── config.json          # Claude configuration (optional)
```

**Getting Credentials:**

Before running the Docker container, you must have a Claude Code subscription and authenticate with the Claude CLI to generate OAuth credentials.

1. **Subscribe to Claude Code** (if you haven't already):
   - Visit [claude.ai](https://claude.ai) and subscribe to Claude Code
   - This subscription provides access to the Claude Agent SDK used by Task Master

2. **Install and authenticate with Claude CLI**:
   ```bash
   # Install Claude CLI
   pip install claude-cli

   # Run Claude and login
   claude
   /login

   # Follow the authentication flow in your browser
   # This will create ~/.claude/.credentials.json with OAuth tokens
   ```

3. **Verify credentials were created**:
   ```bash
   ls -la ~/.claude/.credentials.json
   # Should show a file with your OAuth tokens

   # Check the credentials are valid
   cat ~/.claude/.credentials.json | jq '.claudeAiOauth.accessToken' | head -c 20
   # Should show the beginning of your access token
   ```

4. **Mount the credentials directory to Docker**:
   ```bash
   -v ~/.claude:/home/claudetm/.claude:ro
   ```

**Troubleshooting:**
- If `~/.claude/.credentials.json` doesn't exist, the authentication wasn't successful
- Try re-running the `/login` command in the Claude CLI
- Ensure you have an active Claude Code subscription
- The Docker container will fail to start if credentials are missing or invalid

**Security Note:** The credentials file contains sensitive OAuth tokens. Always mount as read-only (`:ro`) and never commit to version control. For local single-operator use only — see the warning at the top of this section and [Authentication direction](#authentication-direction).

#### Authentication direction

The `~/.claude` bind-mount is a **local-development stopgap**, not the model for shared or unattended
deployments. Mounting a human's `~/.claude/.credentials.json` means:

- The container authenticates as whoever owns that token and **bills their account**.
- The token cannot be scoped to least privilege or rotated without disrupting that person's own Claude
  login.

The target for unattended/multi-consumer deployments is to authenticate the agent through a **central
Claude proxy** with a **scoped, rotatable credential issued per consumer** — never a human's
subscription token. Under that model the container mounts and reads **no** human's
`~/.claude/.credentials.json`; the agent's credential can be revoked or rotated independently. Until
that path is wired up, treat the bind-mount as local-only and keep it off shared hosts.

**Credentials File Format:**
```json
{
  "claudeAiOauth": {
    "accessToken": "...",
    "refreshToken": "...",
    "expiresAt": 1234567890000
  }
}
```

#### 2. Project Directory

**Purpose:** Your repository/project that Claude Task Master will work on

**Mount:** `$(pwd):/app/project` or `/path/to/your/project:/app/project`

**Read-only:** ❌ No (server needs write access for commits, PRs, state)

The project directory is where Claude Task Master executes tasks, creates commits, and manages state.

**What happens in this directory:**
- `.claude-task-master/` directory created for state
- Git commits and branches created
- Code changes made during task execution
- Test runs and verification

**Example Mounts:**
```bash
# Current directory
-v $(pwd):/app/project

# Specific project path
-v /home/user/my-app:/app/project

# Windows (PowerShell)
-v ${PWD}:/app/project

# Windows (CMD)
-v %cd%:/app/project
```

### Recommended Volumes

#### 3. Git Configuration (`~/.gitconfig`)

**Purpose:** Git user configuration for commits

**Mount:** `~/.gitconfig:/home/claudetm/.gitconfig:ro`

**Read-only:** ✅ Yes

Required for proper git commit attribution. Without this, commits may fail or use incorrect author information.

**Minimal `.gitconfig` example:**
```ini
[user]
    name = Your Name
    email = your.email@example.com
```

#### 4. GitHub CLI Configuration (`~/.config/gh`)

**Purpose:** GitHub authentication for PR operations

**Mount:** `~/.config/gh:/home/claudetm/.config/gh:ro`

**Read-only:** ✅ Yes

Required for creating and managing pull requests via the GitHub CLI.

**Setup GitHub CLI:**
```bash
# Install GitHub CLI
# See: https://cli.github.com/

# Authenticate
gh auth login

# Verify authentication
gh auth status

# Check config location
ls -la ~/.config/gh/
```

### Volume Mount Examples

**Minimal Setup (Development):**
```bash
docker run -d \
  -v ~/.claude:/home/claudetm/.claude:ro \
  -v $(pwd):/app/project \
  ghcr.io/developerz-ai/claude-task-master:latest
```

**Full Setup (Production):**
```bash
docker run -d \
  -v ~/.claude:/home/claudetm/.claude:ro \
  -v /path/to/project:/app/project \
  -v ~/.gitconfig:/home/claudetm/.gitconfig:ro \
  -v ~/.config/gh:/home/claudetm/.config/gh:ro \
  -e CLAUDETM_PASSWORD=secure-password \
  ghcr.io/developerz-ai/claude-task-master:latest
```

### Volume Permissions

The container runs as user `claudetm` (UID 1000, GID 1000). Ensure mounted volumes have appropriate permissions:

```bash
# Check your UID
id -u  # Should be 1000 for seamless mounting

# If not 1000, you may need to adjust permissions
# Option 1: Change ownership (if possible)
sudo chown -R 1000:1000 /path/to/project

# Option 2: Run container with your UID (not recommended for security)
docker run --user $(id -u):$(id -g) ...
```

## Environment Variables

Configure Claude Task Master using environment variables. All variables are optional unless marked as required.

### Authentication

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLAUDETM_PASSWORD` | ⚠️ Recommended | None | Password for REST API and MCP server authentication. Required for production. |

**Example:**
```bash
-e CLAUDETM_PASSWORD=your-secure-password
```

### Server Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLAUDETM_SERVER_HOST` | No | `0.0.0.0` | Host to bind to. Use `0.0.0.0` in containers. |
| `CLAUDETM_REST_PORT` | No | `8000` | Port for REST API (FastAPI). |
| `CLAUDETM_MCP_PORT` | No | `8080` | Port for MCP server. |
| `CLAUDETM_MCP_TRANSPORT` | No | `sse` | MCP transport: `sse` or `streamable-http`. |
| `CLAUDETM_LOG_LEVEL` | No | `info` | Log level: `debug`, `info`, `warning`, `error`. |

**Example:**
```bash
-e CLAUDETM_SERVER_HOST=0.0.0.0 \
-e CLAUDETM_REST_PORT=8000 \
-e CLAUDETM_MCP_PORT=8080 \
-e CLAUDETM_MCP_TRANSPORT=sse \
-e CLAUDETM_LOG_LEVEL=info
```

### CORS Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLAUDETM_CORS_ORIGINS` | No | None | Comma-separated list of allowed CORS origins. |

**Example:**
```bash
-e CLAUDETM_CORS_ORIGINS=http://localhost:3000,https://app.example.com
```

### Webhook Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLAUDETM_WEBHOOK_URL` | No | None | URL to send webhook notifications. |
| `CLAUDETM_WEBHOOK_SECRET` | No | None | HMAC secret for webhook signature verification. |

**Example:**
```bash
-e CLAUDETM_WEBHOOK_URL=https://your-webhook.example.com/claudetm \
-e CLAUDETM_WEBHOOK_SECRET=webhook-secret-key
```

See [Webhooks Documentation](./webhooks.md) for more details on webhook events and payload formats.

### Task Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLAUDETM_TARGET_BRANCH` | No | `main` | Default target branch for pull requests. |
| `CLAUDETM_AUTO_MERGE` | No | `true` | Auto-merge PRs when CI passes and approved. |
| `CLAUDETM_MAX_SESSIONS` | No | None | Maximum number of task sessions. |

**Example:**
```bash
-e CLAUDETM_TARGET_BRANCH=develop \
-e CLAUDETM_AUTO_MERGE=false \
-e CLAUDETM_MAX_SESSIONS=10
```

### Complete Environment Variable Example

```bash
docker run -d \
  --name claudetm \
  -p 8000:8000 \
  -p 8080:8080 \
  \
  # Authentication
  -e CLAUDETM_PASSWORD=secure-password \
  \
  # Server
  -e CLAUDETM_SERVER_HOST=0.0.0.0 \
  -e CLAUDETM_REST_PORT=8000 \
  -e CLAUDETM_MCP_PORT=8080 \
  -e CLAUDETM_LOG_LEVEL=info \
  \
  # CORS
  -e CLAUDETM_CORS_ORIGINS=http://localhost:3000 \
  \
  # Webhooks
  -e CLAUDETM_WEBHOOK_URL=https://webhook.example.com/claudetm \
  -e CLAUDETM_WEBHOOK_SECRET=webhook-secret \
  \
  # Tasks
  -e CLAUDETM_TARGET_BRANCH=main \
  -e CLAUDETM_AUTO_MERGE=true \
  \
  # Volumes
  -v ~/.claude:/home/claudetm/.claude:ro \
  -v $(pwd):/app/project \
  -v ~/.gitconfig:/home/claudetm/.gitconfig:ro \
  -v ~/.config/gh:/home/claudetm/.config/gh:ro \
  \
  ghcr.io/developerz-ai/claude-task-master:latest
```

## Authentication

Claude Task Master supports password-based authentication for both the REST API and MCP server using the same shared password.

### Setting Up Authentication

**Using Environment Variable (Recommended):**
```bash
docker run -e CLAUDETM_PASSWORD=your-secure-password ...
```

**Using Docker Compose:**
```yaml
environment:
  - CLAUDETM_PASSWORD=${CLAUDETM_PASSWORD}
```

**Using .env File with Docker Compose:**
```bash
# .env file
CLAUDETM_PASSWORD=your-secure-password
```

```bash
# Start with .env
docker compose up
```

### Authentication Flow

**REST API:**
- Uses `Authorization: Bearer <password>` header
- All endpoints except `/health` require authentication
- Returns `401 Unauthorized` if missing or invalid

**MCP Server:**
- Same Bearer token authentication
- Applied to SSE and streamable-http transports
- Initial connection must include Authorization header

### Example API Requests

**Without Authentication (401 Error):**
```bash
curl http://localhost:8000/status
# Response: 401 Unauthorized
```

**With Authentication (Success):**
```bash
curl -H "Authorization: Bearer your-secure-password" \
     http://localhost:8000/status
```

**Testing Webhook Configuration:**
```bash
curl -X POST \
  -H "Authorization: Bearer your-secure-password" \
  -H "Content-Type: application/json" \
  http://localhost:8000/webhooks/test
```

### Security Best Practices

1. **Always use authentication in production**
   ```bash
   # ❌ Bad (no password)
   docker run -p 8000:8000 ghcr.io/developerz-ai/claude-task-master:latest

   # ✅ Good (with password)
   docker run -e CLAUDETM_PASSWORD=secure-password -p 8000:8000 ghcr.io/developerz-ai/claude-task-master:latest
   ```

2. **Use strong passwords**
   - Minimum 16 characters
   - Mix of letters, numbers, symbols
   - Generate with password manager

3. **Never hardcode passwords**
   ```bash
   # ❌ Bad
   docker run -e CLAUDETM_PASSWORD=password123 ...

   # ✅ Good (use environment variable)
   export CLAUDETM_PASSWORD=$(cat /path/to/secret)
   docker run -e CLAUDETM_PASSWORD ...
   ```

4. **Use secrets management**
   - Docker Swarm secrets
   - Kubernetes secrets
   - HashiCorp Vault
   - AWS Secrets Manager

5. **Enable TLS/SSL in production**
   - Use reverse proxy (nginx, Caddy)
   - Obtain SSL certificates (Let's Encrypt)
   - Force HTTPS only

See [Authentication Documentation](./authentication.md) for more details.

## Docker Compose

Docker Compose provides an easier way to manage multi-container deployments and configuration.

### Basic docker-compose.yml

Create a `docker-compose.yml` file in your project:

```yaml
services:
  claudetm:
    image: ghcr.io/developerz-ai/claude-task-master:latest
    container_name: claudetm-server
    restart: unless-stopped

    ports:
      - "8000:8000"  # REST API
      - "8080:8080"  # MCP Server

    volumes:
      - ~/.claude:/home/claudetm/.claude:ro
      - .:/app/project
      - ~/.gitconfig:/home/claudetm/.gitconfig:ro
      - ~/.config/gh:/home/claudetm/.config/gh:ro

    environment:
      - CLAUDETM_PASSWORD=${CLAUDETM_PASSWORD}
      - CLAUDETM_LOG_LEVEL=info
```

### Using the Repository's docker-compose.yml

The repository includes a comprehensive `docker-compose.yml` with all options documented:

```bash
# Clone the repository
git clone https://github.com/developerz-ai/claude-task-master.git
cd claude-task-master

# Start with environment variables
CLAUDETM_PASSWORD=secure-password docker compose up

# Or use .env file
echo "CLAUDETM_PASSWORD=secure-password" > .env
docker compose up

# Run in background
docker compose up -d

# View logs
docker compose logs -f

# Stop and remove
docker compose down
```

### Docker Compose Commands

```bash
# Start services
docker compose up

# Start in background
docker compose up -d

# Rebuild and start
docker compose up --build

# View logs
docker compose logs -f claudetm

# Stop services
docker compose down

# Stop and remove volumes
docker compose down -v

# Restart service
docker compose restart claudetm

# Execute command in container
docker compose exec claudetm claudetm-py --version
```

### Environment Variable Files

Create a `.env` file for Docker Compose:

```bash
# .env file
CLAUDETM_PASSWORD=your-secure-password
CLAUDETM_LOG_LEVEL=info
CLAUDETM_WEBHOOK_URL=https://webhook.example.com
CLAUDETM_WEBHOOK_SECRET=webhook-secret

# Custom paths
PROJECT_PATH=/path/to/your/project
CLAUDE_CREDENTIALS_PATH=/custom/path/.claude
```

```bash
# Start with .env
docker compose up
```

### Production docker-compose.yml Examples

The repository includes comprehensive production-ready docker-compose examples for various deployment scenarios. All examples are located in the `examples/docker-compose/` directory.

**Available Examples:**

1. **[basic-production.yml](../examples/docker-compose/basic-production.yml)** - Simple production setup with essential features
2. **[production-with-nginx.yml](../examples/docker-compose/production-with-nginx.yml)** - Production with Nginx reverse proxy and SSL
3. **[production-with-caddy.yml](../examples/docker-compose/production-with-caddy.yml)** - Production with Caddy (automatic SSL)
4. **[production-monitoring.yml](../examples/docker-compose/production-monitoring.yml)** - Production with Prometheus and Grafana
5. **[development.yml](../examples/docker-compose/development.yml)** - Development environment

See the **[Docker Compose Examples README](../examples/docker-compose/README.md)** for detailed documentation, usage instructions, and configuration guides for each example.

**Quick Start with Production Examples:**

```bash
# Navigate to examples directory
cd examples/docker-compose

# Copy the example you want to use
cp basic-production.yml docker-compose.yml

# Create .env file from template
cp .env.example .env
# Edit .env and set CLAUDETM_PASSWORD and other variables

# Start services
docker compose up -d

# View logs
docker compose logs -f

# Stop services
docker compose down
```

**Basic Production Example:**

```yaml
services:
  claudetm:
    image: ghcr.io/developerz-ai/claude-task-master:latest
    container_name: claudetm-server
    restart: always

    ports:
      - "8000:8000"
      - "8080:8080"

    volumes:
      - ${CLAUDE_CREDENTIALS_PATH:-~/.claude}:/home/claudetm/.claude:ro
      - ${PROJECT_PATH:-.}:/app/project
      - ~/.gitconfig:/home/claudetm/.gitconfig:ro
      - ~/.config/gh:/home/claudetm/.config/gh:ro

    environment:
      # Authentication (required)
      - CLAUDETM_PASSWORD=${CLAUDETM_PASSWORD:?Password is required}

      # Server config
      - CLAUDETM_SERVER_HOST=0.0.0.0
      - CLAUDETM_REST_PORT=8000
      - CLAUDETM_MCP_PORT=8080
      - CLAUDETM_MCP_TRANSPORT=${CLAUDETM_MCP_TRANSPORT:-sse}
      - CLAUDETM_LOG_LEVEL=${CLAUDETM_LOG_LEVEL:-info}

      # CORS
      - CLAUDETM_CORS_ORIGINS=${CLAUDETM_CORS_ORIGINS:-}

      # Webhooks
      - CLAUDETM_WEBHOOK_URL=${CLAUDETM_WEBHOOK_URL:-}
      - CLAUDETM_WEBHOOK_SECRET=${CLAUDETM_WEBHOOK_SECRET:-}

    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

networks:
  default:
    name: claudetm-network
```

For more advanced production setups including SSL/TLS, monitoring, and high availability, see the [examples directory](../examples/docker-compose/).

## Production Deployment

### Reverse Proxy with SSL

**Using Nginx:**

```nginx
# /etc/nginx/sites-available/claudetm
server {
    listen 443 ssl http2;
    server_name claudetm.example.com;

    ssl_certificate /etc/letsencrypt/live/claudetm.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/claudetm.example.com/privkey.pem;

    # REST API
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # MCP Server SSE endpoint
    location /sse {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
    }
}
```

**Using Caddy:**

```caddyfile
# Caddyfile
claudetm.example.com {
    reverse_proxy localhost:8000

    reverse_proxy /sse localhost:8080 {
        flush_interval -1
    }
}
```

### Docker Swarm Deployment

```yaml
# docker-stack.yml
version: "3.8"

services:
  claudetm:
    image: ghcr.io/developerz-ai/claude-task-master:latest
    deploy:
      replicas: 2
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
        max_attempts: 3

    ports:
      - "8000:8000"
      - "8080:8080"

    volumes:
      - type: bind
        source: /opt/claude/.claude
        target: /home/claudetm/.claude
        read_only: true
      - type: bind
        source: /opt/projects
        target: /app/project

    environment:
      - CLAUDETM_PASSWORD=${CLAUDETM_PASSWORD}

    secrets:
      - claudetm_password

secrets:
  claudetm_password:
    external: true
```

Deploy:
```bash
# Create secret
echo "your-secure-password" | docker secret create claudetm_password -

# Deploy stack
docker stack deploy -c docker-stack.yml claudetm
```

### Kubernetes Deployment

```yaml
# claudetm-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: claudetm
spec:
  replicas: 2
  selector:
    matchLabels:
      app: claudetm
  template:
    metadata:
      labels:
        app: claudetm
    spec:
      containers:
      - name: claudetm
        image: ghcr.io/developerz-ai/claude-task-master:latest
        ports:
        - containerPort: 8000
          name: rest-api
        - containerPort: 8080
          name: mcp-server
        env:
        - name: CLAUDETM_PASSWORD
          valueFrom:
            secretKeyRef:
              name: claudetm-secrets
              key: password
        - name: CLAUDETM_LOG_LEVEL
          value: "info"
        volumeMounts:
        - name: claude-credentials
          mountPath: /home/claudetm/.claude
          readOnly: true
        - name: project
          mountPath: /app/project
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
      volumes:
      - name: claude-credentials
        secret:
          secretName: claude-credentials
      - name: project
        persistentVolumeClaim:
          claimName: project-pvc

---
apiVersion: v1
kind: Service
metadata:
  name: claudetm
spec:
  selector:
    app: claudetm
  ports:
  - name: rest-api
    port: 8000
    targetPort: 8000
  - name: mcp-server
    port: 8080
    targetPort: 8080
```

### Monitoring and Logging

**Prometheus Metrics** (Future feature):
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'claudetm'
    static_configs:
      - targets: ['claudetm:8000']
```

**Centralized Logging:**
```bash
# Using Docker logging driver
docker run \
  --log-driver=syslog \
  --log-opt syslog-address=udp://logserver:514 \
  --log-opt tag="claudetm" \
  ghcr.io/developerz-ai/claude-task-master:latest
```

### Backup and Recovery

**Backup Project State:**
```bash
# Backup .claude-task-master directory
docker exec claudetm tar -czf - /app/project/.claude-task-master > backup-$(date +%Y%m%d).tar.gz

# Restore
docker exec -i claudetm tar -xzf - -C /app/project < backup-20240101.tar.gz
```

## Troubleshooting

### Common Issues

#### Container Fails to Start

**Check logs:**
```bash
docker logs claudetm
```

**Common causes:**
- Missing Claude credentials: Ensure `~/.claude/.credentials.json` exists
- Permission issues: Check volume mount permissions
- Port already in use: Change port mapping or stop conflicting services

#### Authentication Errors

**Symptom:** `401 Unauthorized` responses

**Solutions:**
1. Verify password is set:
   ```bash
   docker exec claudetm env | grep CLAUDETM_PASSWORD
   ```

2. Check Authorization header format:
   ```bash
   curl -H "Authorization: Bearer your-password" http://localhost:8000/status
   ```

3. Verify password matches:
   ```bash
   # Check server logs for auth failures
   docker logs claudetm | grep -i auth
   ```

#### Claude Credentials Not Found

**Symptom:** "Claude CLI credentials not found" error

**Solutions:**
1. Verify credentials file exists:
   ```bash
   ls -la ~/.claude/.credentials.json
   ```

2. Check volume mount:
   ```bash
   docker exec claudetm ls -la /home/claudetm/.claude/
   ```

3. Authenticate with Claude CLI:
   ```bash
   pip install claude-cli
   claude
   /login
   ```

#### Git/GitHub Operations Fail

**Symptom:** Git commits fail or PR creation fails

**Solutions:**
1. Mount git config:
   ```bash
   -v ~/.gitconfig:/home/claudetm/.gitconfig:ro
   ```

2. Mount GitHub CLI config:
   ```bash
   -v ~/.config/gh:/home/claudetm/.config/gh:ro
   ```

3. Verify GitHub authentication:
   ```bash
   gh auth status
   ```

#### Volume Permission Issues

**Symptom:** Permission denied errors in logs

**Solutions:**
1. Check volume permissions:
   ```bash
   ls -ld /path/to/project
   ```

2. Adjust ownership (if needed):
   ```bash
   sudo chown -R 1000:1000 /path/to/project
   ```

3. Run with your UID (not recommended):
   ```bash
   docker run --user $(id -u):$(id -g) ...
   ```

#### High Memory Usage

**Solutions:**
1. Limit container memory:
   ```bash
   docker run --memory=2g --memory-swap=2g ...
   ```

2. Monitor resource usage:
   ```bash
   docker stats claudetm
   ```

3. Adjust log levels:
   ```bash
   -e CLAUDETM_LOG_LEVEL=warning
   ```

### Debug Mode

Enable debug logging:
```bash
docker run -e CLAUDETM_LOG_LEVEL=debug ...
```

View detailed logs:
```bash
# Follow logs in real-time
docker logs -f claudetm

# Last 100 lines
docker logs --tail 100 claudetm

# Logs since 1 hour ago
docker logs --since 1h claudetm
```

### Interactive Shell

Access container shell for debugging:
```bash
# Execute bash shell
docker exec -it claudetm bash

# Check environment
docker exec claudetm env

# Check processes
docker exec claudetm ps aux

# Check network
docker exec claudetm netstat -tlnp
```

### Health Checks

Manually test health endpoint:
```bash
# From host
curl http://localhost:8000/health

# From container
docker exec claudetm curl http://localhost:8000/health
```

Check health status:
```bash
docker inspect --format='{{.State.Health.Status}}' claudetm
```

## Next Steps

- **[Authentication Guide](./authentication.md)** - Detailed authentication setup
- **[API Reference](./api-reference.md)** - REST API endpoint documentation
- **[Webhooks Guide](./webhooks.md)** - Webhook events and configuration
- **[Examples](../examples/)** - Usage examples and tutorials

## Support

- **Issues:** [GitHub Issues](https://github.com/developerz-ai/claude-task-master/issues)
- **Discussions:** [GitHub Discussions](https://github.com/developerz-ai/claude-task-master/discussions)
- **Documentation:** [Main README](../README.md)
