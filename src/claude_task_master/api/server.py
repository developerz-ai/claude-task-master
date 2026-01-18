"""FastAPI server for Claude Task Master REST API.

This module provides a FastAPI application factory and server runner for exposing
claudetm functionality as HTTP endpoints.

Key Features:
- App factory pattern for testability
- CORS configuration with environment-based origins
- Health check endpoint
- Lifespan context for startup/shutdown

Usage:
    # Create app and run with uvicorn
    from claude_task_master.api.server import create_app, run_server

    app = create_app()
    # or
    run_server(host="0.0.0.0", port=8000)
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from claude_task_master import __version__
from claude_task_master.api.models import APIInfo, HealthResponse

# Import FastAPI - using try/except for graceful degradation
try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:
    FastAPI = None
    CORSMiddleware = None

logger = logging.getLogger(__name__)

# =============================================================================
# Environment Configuration
# =============================================================================

# Server defaults
API_HOST = os.getenv("CLAUDETM_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("CLAUDETM_API_PORT", "8000"))

# CORS configuration
# Comma-separated list of allowed origins, or "*" for all
CORS_ORIGINS = os.getenv("CLAUDETM_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")

# =============================================================================
# Lifespan Context
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for FastAPI app.

    Handles startup and shutdown events, including:
    - Recording server start time for uptime tracking
    - Logging startup/shutdown messages
    - Future: graceful shutdown of running tasks

    Args:
        app: The FastAPI application instance.

    Yields:
        Control to the running application.
    """
    # Startup
    app.state.start_time = time.time()
    app.state.active_tasks = 0
    logger.info(f"Claude Task Master API v{__version__} starting up")

    yield

    # Shutdown
    logger.info("Claude Task Master API shutting down")


# =============================================================================
# CORS Configuration
# =============================================================================


def _parse_cors_origins(origins_str: str) -> list[str]:
    """Parse CORS origins from environment variable.

    Args:
        origins_str: Comma-separated list of origins or "*" for all.

    Returns:
        List of allowed origin strings.
    """
    if origins_str.strip() == "*":
        return ["*"]
    return [origin.strip() for origin in origins_str.split(",") if origin.strip()]


def _configure_cors(app: FastAPI, origins: list[str] | None = None) -> None:
    """Configure CORS middleware on the FastAPI app.

    Args:
        app: The FastAPI application instance.
        origins: List of allowed origins. If None, uses CORS_ORIGINS env var.
    """
    if CORSMiddleware is None:
        logger.warning("CORS middleware not available (FastAPI not installed)")
        return

    allowed_origins = origins if origins is not None else _parse_cors_origins(CORS_ORIGINS)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    logger.debug(f"CORS configured with origins: {allowed_origins}")


# =============================================================================
# App Factory
# =============================================================================


def create_app(
    working_dir: str | Path | None = None,
    cors_origins: list[str] | None = None,
    include_docs: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application.

    This is the main entry point for creating the API server. It sets up:
    - Lifespan context for startup/shutdown
    - CORS middleware
    - Health check endpoint
    - API metadata and documentation

    Args:
        working_dir: Working directory for task execution. Defaults to cwd.
        cors_origins: List of allowed CORS origins. Defaults to env var.
        include_docs: Whether to include OpenAPI docs. Default True.

    Returns:
        Configured FastAPI application instance.

    Raises:
        ImportError: If FastAPI is not installed.

    Example:
        >>> app = create_app()
        >>> # Use with uvicorn: uvicorn.run(app, host="0.0.0.0", port=8000)
    """
    if FastAPI is None:
        raise ImportError(
            "FastAPI not installed. Install with: pip install claude-task-master[api]"
        )

    # Resolve working directory
    work_dir = Path(working_dir) if working_dir else Path.cwd()

    # Create FastAPI app with metadata
    app = FastAPI(
        title="Claude Task Master API",
        description=(
            "REST API for Claude Task Master task orchestration.\n\n"
            "Provides endpoints for:\n"
            "- Task status monitoring\n"
            "- Control operations (pause, stop, resume)\n"
            "- Configuration management\n"
            "- Log and progress access"
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if include_docs else None,
        redoc_url="/redoc" if include_docs else None,
        openapi_url="/openapi.json" if include_docs else None,
    )

    # Store working directory in app state
    app.state.working_dir = work_dir

    # Configure CORS
    _configure_cors(app, cors_origins)

    # ==========================================================================
    # Core Endpoints
    # ==========================================================================

    @app.get(
        "/",
        response_model=APIInfo,
        summary="API Information",
        tags=["General"],
    )
    async def root() -> APIInfo:
        """Get API information and documentation links.

        Returns basic information about the API including name, version,
        and links to documentation.
        """
        return APIInfo(
            name="Claude Task Master API",
            version=__version__,
            description="REST API for Claude Task Master task orchestration",
            docs_url="/docs",
        )

    @app.get(
        "/health",
        response_model=HealthResponse,
        summary="Health Check",
        tags=["General"],
    )
    async def health() -> HealthResponse:
        """Health check endpoint.

        Returns server health information including:
        - Server status (healthy, degraded, unhealthy)
        - Version information
        - Uptime in seconds
        - Number of active tasks

        This endpoint is suitable for load balancer health checks
        and monitoring systems.
        """
        uptime = None
        if hasattr(app.state, "start_time"):
            uptime = time.time() - app.state.start_time

        active_tasks = getattr(app.state, "active_tasks", 0)

        return HealthResponse(
            status="healthy",
            version=__version__,
            server_name="claude-task-master-api",
            uptime_seconds=uptime,
            active_tasks=active_tasks,
        )

    # Log app creation
    logger.info(f"FastAPI app created with working_dir={work_dir}")

    return app


# =============================================================================
# Server Runner
# =============================================================================


def run_server(
    host: str | None = None,
    port: int | None = None,
    working_dir: str | Path | None = None,
    cors_origins: list[str] | None = None,
    reload: bool = False,
    log_level: str = "info",
) -> None:
    """Run the FastAPI server with uvicorn.

    Convenience function to create the app and run it with uvicorn.
    For production, consider running uvicorn directly with the app factory.

    Args:
        host: Host to bind to. Defaults to CLAUDETM_API_HOST env var or 127.0.0.1.
        port: Port to bind to. Defaults to CLAUDETM_API_PORT env var or 8000.
        working_dir: Working directory for task execution.
        cors_origins: List of allowed CORS origins.
        reload: Enable auto-reload for development.
        log_level: Uvicorn log level.

    Raises:
        ImportError: If uvicorn is not installed.

    Example:
        >>> run_server(host="0.0.0.0", port=8000)
    """
    try:
        import uvicorn
    except ImportError as err:
        raise ImportError(
            "Uvicorn not installed. Install with: pip install claude-task-master[api]"
        ) from err

    effective_host = host or API_HOST
    effective_port = port or API_PORT

    # Security warning for non-localhost binding
    if effective_host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            f"API server binding to non-localhost address ({effective_host}). "
            "Ensure proper authentication is configured."
        )

    # Create the app
    app = create_app(working_dir=working_dir, cors_origins=cors_origins)

    # Run with uvicorn
    uvicorn.run(
        app,
        host=effective_host,
        port=effective_port,
        reload=reload,
        log_level=log_level,
    )


# =============================================================================
# App Instance for CLI/Import
# =============================================================================


def get_app(**kwargs: Any) -> FastAPI:
    """Get or create the FastAPI application instance.

    This function is useful for CLI commands and as a uvicorn factory.

    Args:
        **kwargs: Arguments passed to create_app().

    Returns:
        FastAPI application instance.

    Example:
        # In uvicorn CLI:
        # uvicorn claude_task_master.api.server:get_app --factory
    """
    return create_app(**kwargs)


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> None:
    """Main entry point for running the API server standalone."""
    import argparse

    parser = argparse.ArgumentParser(description="Run Claude Task Master REST API server")
    parser.add_argument(
        "--host",
        default=API_HOST,
        help=f"Host to bind to (default: {API_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=API_PORT,
        help=f"Port to bind to (default: {API_PORT})",
    )
    parser.add_argument(
        "--working-dir",
        help="Working directory for task execution",
    )
    parser.add_argument(
        "--cors-origins",
        help="Comma-separated list of CORS origins",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
        help="Log level (default: info)",
    )

    args = parser.parse_args()

    # Parse CORS origins if provided
    cors_origins = None
    if args.cors_origins:
        cors_origins = _parse_cors_origins(args.cors_origins)

    run_server(
        host=args.host,
        port=args.port,
        working_dir=args.working_dir,
        cors_origins=cors_origins,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
