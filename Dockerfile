# =============================================================================
# Claude Task Master - Multi-stage Dockerfile
# =============================================================================
# This Dockerfile creates a production-ready image for Claude Task Master
# that runs the unified server (REST API + MCP server).
#
# Build:   docker build -t claudetm .
#
# Agent credential (one time): the container authenticates with its OWN scoped,
# rotatable API key, held in a claudetm "api-key" profile inside a named volume.
# It must NEVER be given a human's ~/.claude/.credentials.json -- see the note
# further down and docs/docker.md.
#
#   docker volume create claudetm-profiles
#   docker run --rm \
#     -v claudetm-profiles:/home/claudetm/.claudetm \
#     -e CLAUDETM_API_KEY="$AGENT_API_KEY" \
#     claudetm \
#     claudetm profile add agent --type api-key \
#       --base-url https://your-gateway.example/anthropic
#
# Run:
#   docker run -p 8000:8000 -p 8080:8080 \
#     -v claudetm-profiles:/home/claudetm/.claudetm \
#     -e CLAUDETM_PROFILE=agent \
#     -e GH_TOKEN="$AGENT_GITHUB_TOKEN" \
#     -v "$(pwd)":/app/project \
#     claudetm
#
# GitHub credential (per run, never baked in): the agent authenticates to
# GitHub with an INJECTED, repository-scoped, least-privilege token owned by a
# bot account (e.g. claudetm[bot]). It carries no admin scope - CI, required
# reviews and branch protection stay mandatory - and it is revoked and
# rotated independently of the Claude credential.
#
#   docker run -e GH_TOKEN="$(cat /run/secrets/claudetm_github_token)" ...
#
#   GH_TOKEN is gh's own standard variable (so git's gh-backed credential
#   helper and the agent's own gh calls authenticate the same way);
#   CLAUDETM_GITHUB_TOKEN is an accepted alias for the same value. The token is
#   never read from disk, never committed, never stored in the image and never
#   printed.
#
#   GH_CONFIG_DIR is set in the image to a claudetm-owned, empty directory
#   (/home/claudetm/.claudetm/gh), so an operator's ~/.config/gh is never read
#   and a personal "gh auth login" can never take over an agent run. A
#   container with no credential injected has no personal login to fall back
#   to: it fails closed, naming the environment variable that carries one.
#
# Environment Variables:
#   CLAUDETM_PROFILE        - Required: name of the api-key profile to run as
#   CLAUDETM_API_KEY        - Only for `claudetm profile add`: the agent's scoped
#                             API key, read from the environment so it is never
#                             baked into the image or a compose file
#   GH_TOKEN                - The injected GitHub credential (a repository-
#                             scoped, least-privilege bot token), read from the
#                             environment; never baked into the image
#   CLAUDETM_GITHUB_TOKEN   - Accepted alias for GH_TOKEN
#   GH_CONFIG_DIR           - gh's config directory, isolated in the image
#                             (default: /home/claudetm/.claudetm/gh)
#   CLAUDETM_PASSWORD       - Required: Password for API authentication
#   CLAUDETM_SERVER_HOST    - Host to bind to (default: 0.0.0.0 in container)
#   CLAUDETM_REST_PORT      - REST API port (default: 8000)
#   CLAUDETM_MCP_PORT       - MCP server port (default: 8080)
#   CLAUDETM_MCP_TRANSPORT  - MCP transport: sse or streamable-http (default: sse)
#   CLAUDETM_CORS_ORIGINS   - CORS origins for REST API (comma-separated)
#   CLAUDETM_LOG_LEVEL      - Log level: debug, info, warning, error (default: info)
#   CLAUDETM_WEBHOOK_URL    - Webhook URL for notifications (optional)
#   CLAUDETM_WEBHOOK_SECRET - Webhook HMAC secret (optional)
# =============================================================================

# Build arguments for version tracking (passed from docker build --build-arg or GitHub Actions)
ARG VERSION=dev
ARG GIT_COMMIT=unknown
ARG BUILD_DATE=unknown

# -----------------------------------------------------------------------------
# Stage 1: Builder - Install dependencies
# -----------------------------------------------------------------------------
FROM python:3.14-slim AS builder

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only requirements first (for better layer caching)
WORKDIR /build

# Copy the entire project for installation
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the package with all server dependencies
RUN pip install --upgrade pip && \
    pip install ".[mcp,api]"

# -----------------------------------------------------------------------------
# Stage 2: Runtime - Minimal production image
# -----------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

# Accept build arguments in runtime stage for labels
ARG VERSION=dev
ARG GIT_COMMIT=unknown
ARG BUILD_DATE=unknown

# Labels for container metadata (including version tracking from build arguments)
LABEL org.opencontainers.image.title="Claude Task Master" \
      org.opencontainers.image.description="Autonomous task orchestration system with REST API and MCP server" \
      org.opencontainers.image.url="https://github.com/developerz-ai/claude-task-master" \
      org.opencontainers.image.source="https://github.com/developerz-ai/claude-task-master" \
      org.opencontainers.image.vendor="DeveloperZ.AI" \
      org.opencontainers.image.documentation="https://github.com/developerz-ai/claude-task-master#readme" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Default server configuration for container
    CLAUDETM_SERVER_HOST=0.0.0.0 \
    CLAUDETM_REST_PORT=8000 \
    CLAUDETM_MCP_PORT=8080 \
    CLAUDETM_MCP_TRANSPORT=sse \
    CLAUDETM_LOG_LEVEL=info \
    # Path configuration
    PATH="/opt/venv/bin:$PATH" \
    # Home directory for non-root user
    HOME=/home/claudetm \
    # gh reads its configuration from here, never from an operator's
    # ~/.config/gh. The directory is created below, owned by claudetm, and
    # stays empty: a personal "gh auth login" is not a fallback for an agent
    # run.
    GH_CONFIG_DIR=/home/claudetm/.claudetm/gh \
    # Git activity is attributed to a disclosed bot identity, never to a human.
    # Override these per deployment if your organisation issues its own bot
    # identity - the point is that the agent never signs as an operator.
    GIT_AUTHOR_NAME="claudetm[bot]" \
    GIT_COMMITTER_NAME="claudetm[bot]" \
    GIT_AUTHOR_EMAIL="claudetm[bot]@users.noreply.github.com" \
    GIT_COMMITTER_EMAIL="claudetm[bot]@users.noreply.github.com"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Git is needed for Claude agent operations
    git \
    # GitHub CLI for PR operations
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd --gid 1000 claudetm && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash claudetm

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Create directories for volumes.
#
# /home/claudetm/.claudetm holds the claudetm profile registry -- the agent's own
# scoped, rotatable API key. Mount a NAMED VOLUME here (claudetm-profiles), never
# a human's ~/.claude: that directory holds a personal OAuth bearer token, so a
# container given it runs as -- and bills -- that person's Claude account, cannot
# be scoped down, and cannot be rotated without breaking their own login. That
# has already leaked a token across developers once.
#
# The directory is created here (owned by claudetm) so the named volume inherits
# non-root ownership and `claudetm profile add` can write to it. The gh/ sub
# directory is the claudetm-owned GH_CONFIG_DIR: gh reads its configuration
# from there, so the image can never read an operator's ~/.config/gh.
RUN mkdir -p /home/claudetm/.claudetm/gh /app/project && \
    chown -R claudetm:claudetm /home/claudetm /app

# Switch to non-root user
USER claudetm

# Git configuration for the agent:
#   - the bot identity, so a commit is attributed to claudetm[bot] rather than
#     to the operator whose repository is mounted. The GIT_* environment
#     variables above already say this; the config is the fallback for a tool
#     that scrubs the environment.
#   - a gh-backed credential helper, so a push authenticates with the
#     injected GH_TOKEN instead of a personal login. With no credential
#     injected the helper has nothing to offer and the push fails.
#   - the mounted project tree is owned by the operator, not by the container
#     user, so git's ownership check is relaxed for it; without this, git
#     refuses to operate on the repository the agent was asked to work on.
RUN git config --global credential.helper '!gh auth git-credential' && \
    git config --global user.name "claudetm[bot]" && \
    git config --global user.email "claudetm[bot]@users.noreply.github.com" && \
    git config --global --add safe.directory '*'

# Set working directory (project files will be mounted here)
WORKDIR /app/project

# Expose ports for REST API and MCP server
EXPOSE 8000 8080

# Health check for the REST API
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${CLAUDETM_REST_PORT}/health || exit 1

# Default command: run the unified server
# The server reads configuration from environment variables
CMD ["claudetm-server"]
