# =============================================================================
# Claude Task Master - Multi-stage Dockerfile
# =============================================================================
# This Dockerfile creates a production-ready image for Claude Task Master
# that runs the unified server (REST API + MCP server).
#
# Build:   docker build -t claudetm .
# Run:     docker run -p 8000:8000 -p 8080:8080 -v ~/.claude:/home/claudetm/.claude claudetm
#
# Environment Variables:
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
FROM python:3.12-slim AS builder

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
FROM python:3.12-slim AS runtime

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
    HOME=/home/claudetm

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

# Create directories for volumes
RUN mkdir -p /home/claudetm/.claude /app/project && \
    chown -R claudetm:claudetm /home/claudetm /app

# Switch to non-root user
USER claudetm

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
