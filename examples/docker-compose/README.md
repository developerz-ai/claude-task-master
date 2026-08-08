# Docker Compose Examples

This directory contains production-ready Docker Compose configurations for various deployment scenarios of Claude Task Master.

## Available Examples

1. **[basic-production.yml](#basic-production)** - Simple production setup with essential features
2. **[production-with-nginx.yml](#production-with-nginx)** - Production setup with Nginx reverse proxy and SSL
3. **[production-with-caddy.yml](#production-with-caddy)** - Production setup with Caddy reverse proxy (auto-SSL)
4. **[production-monitoring.yml](#production-with-monitoring)** - Production with Prometheus and Grafana monitoring
5. **[production-ha.yml](#high-availability-setup)** - High-availability setup with multiple replicas
6. **[development.yml](#development-environment)** - Development environment with hot reload

## Quick Start

```bash
# Navigate to examples directory
cd examples/docker-compose

# Copy the example you want to use
cp basic-production.yml docker-compose.yml

# One-time: create the agent's own scoped credential in a named volume
docker volume create claudetm-profiles
docker run --rm \
  -v claudetm-profiles:/home/claudetm/.claudetm \
  -e CLAUDETM_API_KEY="$AGENT_API_KEY" \
  ghcr.io/developerz-ai/claude-task-master:latest \
  claudetm profile add agent --type api-key \
    --base-url https://your-gateway.example/anthropic

# Create .env file with your configuration
# (the API key is NOT stored here - it lives in the claudetm-profiles volume)
cat > .env <<EOF
CLAUDETM_PROFILE=agent
CLAUDETM_PASSWORD=your-secure-password
CLAUDETM_WEBHOOK_URL=https://webhook.example.com/claudetm
CLAUDETM_WEBHOOK_SECRET=your-webhook-secret
PROJECT_PATH=/path/to/your/project
EOF

# Start the services
docker compose up -d

# View logs
docker compose logs -f claudetm

# Check status
docker compose ps

# Stop services
docker compose down
```

## Prerequisites

Before using any of these examples, ensure you have:

1. **Docker and Docker Compose installed**
   ```bash
   docker --version  # Should be 20.10+
   docker compose version  # Should be 2.0+
   ```

2. **A scoped agent credential (an API key + base URL)**

   The container authenticates with its **own** credential — never a human's
   `~/.claude/.credentials.json`. That file holds a personal OAuth bearer token:
   a container given it runs as, and bills, that person's Claude account, the
   token cannot be scoped down, and rotating it breaks their own Claude login.
   This has already caused a real cross-developer credential leak.

   Issue one key per consumer, revocable and rotatable on its own. Where the key
   comes from is outside this repository — it may be an Anthropic API key created
   for the agent, or a key minted by a central Claude gateway your organisation
   runs; provisioning is documented wherever that gateway lives.

   Store it in a claudetm `api-key` profile inside a named volume (one time,
   non-interactive — `profile add` reads `CLAUDETM_API_KEY` from the environment
   instead of prompting):

   ```bash
   docker volume create claudetm-profiles

   docker run --rm \
     -v claudetm-profiles:/home/claudetm/.claudetm \
     -e CLAUDETM_API_KEY="$AGENT_API_KEY" \
     ghcr.io/developerz-ai/claude-task-master:latest \
     claudetm profile add agent --type api-key \
       --base-url https://your-gateway.example/anthropic

   # Verify
   docker run --rm -v claudetm-profiles:/home/claudetm/.claudetm \
     ghcr.io/developerz-ai/claude-task-master:latest \
     claudetm profile list
   ```

   Omit `--base-url` to talk to `api.anthropic.com` directly. All examples then
   mount `claudetm-profiles:/home/claudetm/.claudetm` and select the profile with
   `CLAUDETM_PROFILE`. See [docs/docker.md](../../docs/docker.md) for the full
   setup, rotation and troubleshooting guide.

3. **Git configuration**
   ```bash
   # Set up git config if not already done
   git config --global user.name "Your Name"
   git config --global user.email "your.email@example.com"
   ```

4. **GitHub CLI authentication** (for PR operations)
   ```bash
   # Install and authenticate GitHub CLI
   gh auth login
   gh auth status
   ```

## Basic Production

**File:** `basic-production.yml`

Minimal production setup with:
- Password authentication
- Health checks
- Proper volume mounts
- Log rotation

**Usage:**
```bash
# Start
CLAUDETM_PASSWORD=your-password docker compose -f basic-production.yml up -d

# Stop
docker compose -f basic-production.yml down
```

## Production with Nginx

**File:** `production-with-nginx.yml`

Production setup with Nginx reverse proxy:
- SSL/TLS termination
- HTTP to HTTPS redirect
- Rate limiting
- Static file caching
- WebSocket/SSE support for MCP

**Setup:**
```bash
# 1. Obtain SSL certificates (Let's Encrypt)
sudo certbot certonly --standalone -d claudetm.example.com

# 2. Configure .env
cat > .env <<EOF
CLAUDETM_PASSWORD=your-password
DOMAIN=claudetm.example.com
SSL_CERT_PATH=/etc/letsencrypt/live/claudetm.example.com/fullchain.pem
SSL_KEY_PATH=/etc/letsencrypt/live/claudetm.example.com/privkey.pem
EOF

# 3. Start services
docker compose -f production-with-nginx.yml up -d
```

**Access:**
- REST API: https://claudetm.example.com/api
- API Docs: https://claudetm.example.com/api/docs
- MCP Server: https://claudetm.example.com/mcp/sse

## Production with Caddy

**File:** `production-with-caddy.yml`

Production setup with Caddy (automatic SSL):
- Automatic SSL certificates (Let's Encrypt)
- Automatic HTTP to HTTPS redirect
- Simpler configuration than Nginx
- Built-in security headers

**Usage:**
```bash
# Configure domain
export DOMAIN=claudetm.example.com
export CLAUDETM_PASSWORD=your-password

# Start services (Caddy will automatically obtain SSL)
docker compose -f production-with-caddy.yml up -d
```

## Production with Monitoring

**File:** `production-monitoring.yml`

Production setup with observability:
- Prometheus for metrics collection
- Grafana for visualization
- Pre-configured dashboards
- Alert rules

**Components:**
- Claude Task Master
- Prometheus
- Grafana
- Node Exporter (system metrics)

**Access:**
- Claude Task Master: http://localhost:8000
- Grafana: http://localhost:3000 (admin/admin)
- Prometheus: http://localhost:9090

**Setup:**
```bash
# Start all services
docker compose -f production-monitoring.yml up -d

# Access Grafana
open http://localhost:3000
# Login: admin/admin (change on first login)

# Import Claude Task Master dashboard
# Dashboard ID: (will be created in future release)
```

## High Availability Setup

**File:** `production-ha.yml`

High-availability setup for production:
- Multiple Claude Task Master replicas
- Load balancing
- Shared volume for state
- Health checks and auto-restart
- Rolling updates

**Usage:**
```bash
# Start with 3 replicas
docker compose -f production-ha.yml up -d --scale claudetm=3

# Check replicas
docker compose -f production-ha.yml ps

# View logs from all replicas
docker compose -f production-ha.yml logs -f claudetm

# Rolling restart
docker compose -f production-ha.yml up -d --no-deps --scale claudetm=3 --force-recreate
```

## Development Environment

**File:** `development.yml`

Development environment with:
- Hot reload on code changes
- Debug logging
- No authentication (for ease of development)
- Volume mounts for source code
- Development tools pre-installed

**Usage:**
```bash
# Start development environment
docker compose -f development.yml up

# Rebuild on changes
docker compose -f development.yml up --build

# Run tests
docker compose -f development.yml exec claudetm pytest

# Access shell
docker compose -f development.yml exec claudetm bash
```

## Environment Variables

All examples support these environment variables:

### Required (Production)
- `CLAUDETM_PASSWORD` - Password for authentication
- `CLAUDETM_PROFILE` - Name of the agent's api-key profile in the `claudetm-profiles` volume (default: `agent`)

### Optional
- `PROJECT_PATH` - Path to your project (default: current directory)
- `CLAUDETM_LOG_LEVEL` - Log level: debug, info, warning, error (default: info)
- `CLAUDETM_WEBHOOK_URL` - Webhook endpoint URL
- `CLAUDETM_WEBHOOK_SECRET` - Webhook HMAC secret
- `CLAUDETM_CORS_ORIGINS` - Comma-separated CORS origins
- `CLAUDETM_REST_PORT` - REST API port (default: 8000)
- `CLAUDETM_MCP_PORT` - MCP server port (default: 8080)
- `CLAUDETM_MCP_TRANSPORT` - MCP transport: sse or streamable-http (default: sse)

### Example .env File

```bash
# Authentication (REQUIRED for production)
CLAUDETM_PASSWORD=your-secure-password-min-16-chars

# Agent credential: the api-key profile to run under.
# The key itself lives in the claudetm-profiles volume, never in this file.
CLAUDETM_PROFILE=agent

# Project Configuration
PROJECT_PATH=/home/user/my-project

# Server Configuration
CLAUDETM_LOG_LEVEL=info
CLAUDETM_REST_PORT=8000
CLAUDETM_MCP_PORT=8080
CLAUDETM_MCP_TRANSPORT=sse

# Webhooks
CLAUDETM_WEBHOOK_URL=https://webhook.example.com/claudetm
CLAUDETM_WEBHOOK_SECRET=your-webhook-secret

# CORS (for web clients)
CLAUDETM_CORS_ORIGINS=http://localhost:3000,https://app.example.com

# Task Configuration
CLAUDETM_TARGET_BRANCH=main
CLAUDETM_AUTO_MERGE=true
CLAUDETM_MAX_SESSIONS=10

# Reverse Proxy (if using Nginx/Caddy)
DOMAIN=claudetm.example.com
SSL_CERT_PATH=/etc/letsencrypt/live/claudetm.example.com/fullchain.pem
SSL_KEY_PATH=/etc/letsencrypt/live/claudetm.example.com/privkey.pem
```

## Security Best Practices

1. **Always use strong passwords in production**
   ```bash
   # Generate a secure password
   openssl rand -base64 32
   ```

2. **Never commit .env files to version control**
   ```bash
   echo ".env" >> .gitignore
   ```

3. **Use Docker secrets for sensitive data**
   ```bash
   echo "your-password" | docker secret create claudetm_password -
   ```

4. **Enable SSL/TLS in production**
   - Use Nginx or Caddy examples
   - Obtain valid SSL certificates
   - Force HTTPS only

5. **Restrict network access**
   ```yaml
   # Only expose ports to localhost
   ports:
     - "127.0.0.1:8000:8000"
     - "127.0.0.1:8080:8080"
   ```

6. **Keep images updated**
   ```bash
   # Pull latest version
   docker compose pull
   docker compose up -d
   ```

7. **Monitor and rotate logs**
   ```yaml
   logging:
     driver: json-file
     options:
       max-size: "10m"
       max-file: "3"
   ```

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose logs claudetm

# Check configuration
docker compose config

# Verify the agent credential is present and active
docker compose exec claudetm claudetm profile list
docker compose exec claudetm ls -la /home/claudetm/.claudetm/
```

A "Claude CLI credentials not found" error means no api-key profile was found —
the `claudetm-profiles` volume is missing or empty, or `CLAUDETM_PROFILE` names a
profile that was never created. Re-run the profile setup in Prerequisites; do
**not** work around it by mounting a personal `~/.claude`.

### Authentication errors

```bash
# Verify password is set
docker compose exec claudetm env | grep CLAUDETM_PASSWORD

# Test authentication
curl -H "Authorization: Bearer your-password" http://localhost:8000/health
```

### Volume permission issues

```bash
# Check permissions
ls -ld /path/to/project

# Fix ownership (if needed)
sudo chown -R 1000:1000 /path/to/project
```

### SSL certificate issues (Nginx/Caddy)

```bash
# Verify certificates exist
ls -la /etc/letsencrypt/live/claudetm.example.com/

# Test Nginx config
docker compose exec nginx nginx -t

# Reload Nginx
docker compose exec nginx nginx -s reload
```

## Updating

```bash
# Pull latest images
docker compose pull

# Restart with new images
docker compose up -d

# Or rebuild from source
docker compose up -d --build
```

## Backup and Restore

### Backup state

```bash
# Backup .claude-task-master directory
docker compose exec claudetm tar -czf - /app/project/.claude-task-master > backup-$(date +%Y%m%d).tar.gz

# Backup volumes
docker run --rm -v claudetm_project:/data -v $(pwd):/backup alpine tar -czf /backup/project-backup.tar.gz /data
```

### Restore state

```bash
# Restore from backup
docker compose exec -T claudetm tar -xzf - -C /app/project < backup-20240101.tar.gz
```

## Additional Resources

- [Docker Documentation](../docs/docker.md) - Complete Docker deployment guide
- [Authentication Guide](../docs/authentication.md) - Authentication setup and configuration
- [Webhooks Guide](../docs/webhooks.md) - Webhook configuration and events
- [API Reference](../docs/api-reference.md) - REST API documentation

## Support

- **Issues:** [GitHub Issues](https://github.com/developerz-ai/claude-task-master/issues)
- **Discussions:** [GitHub Discussions](https://github.com/developerz-ai/claude-task-master/discussions)
