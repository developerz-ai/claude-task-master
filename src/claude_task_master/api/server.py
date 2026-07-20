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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_task_master import __version__
from claude_task_master.api.models import APIInfo
from claude_task_master.api.routes import register_routes
from claude_task_master.api.server_config import (
    API_HOST,
    API_PORT,
    AUTH_MIDDLEWARE_AVAILABLE,
    CORS_ORIGINS,
    FASTAPI_AVAILABLE,
    _configure_auth,
    _configure_cors,
    _log_api_config,
    _parse_cors_origins,
    lifespan,
)
from claude_task_master.auth import is_auth_enabled

if TYPE_CHECKING:
    from fastapi import FastAPI

try:
    from fastapi import FastAPI

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)

__all__ = [
    "create_app",
    "run_server",
    "get_app",
    "main",
    # Re-exports from server_config (keep backward-compat for any direct imports)
    "API_HOST",
    "API_PORT",
    "CORS_ORIGINS",
    "FASTAPI_AVAILABLE",
    "AUTH_MIDDLEWARE_AVAILABLE",
    "_log_api_config",
    "_parse_cors_origins",
    "_configure_cors",
    "_configure_auth",
    "lifespan",
]


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
    if not FASTAPI_AVAILABLE:
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
            "- Plan, logs, progress, and context access\n"
            "- Health checks"
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if include_docs else None,
        redoc_url="/redoc" if include_docs else None,
        openapi_url="/openapi.json" if include_docs else None,
    )

    # Store working directory and include_docs flag in app state
    app.state.working_dir = work_dir
    app.state.include_docs = include_docs

    # Configure middleware (order matters - middleware added first runs last)
    # CORS must be added before auth so that CORS headers are added to 401/403 responses
    _configure_cors(app, cors_origins)

    # Configure authentication if password is set
    # Auth middleware is added after CORS, so it runs before CORS in the request cycle
    # This allows CORS to handle preflight (OPTIONS) requests without auth
    auth_enabled = _configure_auth(app)
    app.state.auth_enabled = auth_enabled

    # ==========================================================================
    # Core Endpoints (Root endpoint only - other endpoints via routes)
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
        # Get docs URL from app state (will be None if docs are disabled)
        docs_url = app.docs_url if app.state.include_docs else None

        return APIInfo(
            name="Claude Task Master API",
            version=__version__,
            description="REST API for Claude Task Master task orchestration",
            docs_url=docs_url,
        )

    # Register routes from routes module
    register_routes(app)

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
    effective_cors = cors_origins if cors_origins is not None else _parse_cors_origins(CORS_ORIGINS)

    # Check if auth is actually enforceable (configured AND middleware available)
    auth_configured = is_auth_enabled()
    auth_enabled = AUTH_MIDDLEWARE_AVAILABLE and auth_configured
    if auth_configured and not AUTH_MIDDLEWARE_AVAILABLE:
        logger.warning(
            "Password authentication is configured but middleware is unavailable. "
            "Install claude-task-master[api] to enforce auth."
        )

    # Log API configuration
    _log_api_config(effective_host, effective_port, effective_cors, auth_enabled)

    # Refuse non-localhost binding without enforceable authentication.
    # Mirrors mcp/server.py:run_server so both transports fail closed.
    if effective_host not in ("127.0.0.1", "localhost", "::1"):
        if not auth_enabled:
            logger.error(
                f"API server cannot bind to non-localhost address ({effective_host}) "
                "without authentication. Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH."
            )
            raise SystemExit(1)
        logger.info(f"API server binding to {effective_host} with password authentication enabled.")

    if reload:
        # Reload mode requires import string with factory so uvicorn can spawn
        # reload subprocesses. Passing an app instance disables reload silently.

        # Set environment variables so the factory picks them up (uvicorn doesn't forward args)
        if working_dir:
            os.environ["_CLAUDETM_WORKING_DIR"] = str(working_dir)
        if cors_origins:
            os.environ["CLAUDETM_CORS_ORIGINS"] = ",".join(cors_origins)

        uvicorn.run(
            "claude_task_master.api.server:get_app",
            factory=True,
            host=effective_host,
            port=effective_port,
            reload=True,
            log_level=log_level,
        )
    else:
        # Create the app directly for non-reload mode
        app = create_app(working_dir=working_dir, cors_origins=cors_origins)

        # Run with uvicorn
        uvicorn.run(
            app,
            host=effective_host,
            port=effective_port,
            reload=False,
            log_level=log_level,
        )


# =============================================================================
# App Instance for CLI/Import
# =============================================================================


def get_app(**kwargs: Any) -> FastAPI:
    """Get or create the FastAPI application instance.

    This function is useful for CLI commands and as a uvicorn factory.

    In reload mode, uvicorn calls this without arguments, so it falls back to
    environment variables set by run_server() for working_dir and cors_origins.

    Args:
        **kwargs: Arguments passed to create_app().

    Returns:
        FastAPI application instance.

    Example:
        # In uvicorn CLI:
        # uvicorn claude_task_master.api.server:get_app --factory
    """
    # Prefer kwargs, but fall back to environment variables for reload mode
    working_dir = kwargs.get("working_dir") or os.getenv("_CLAUDETM_WORKING_DIR")
    cors_origins_str = os.getenv("CLAUDETM_CORS_ORIGINS")

    # Remove from kwargs to avoid duplicate passing
    kwargs.pop("working_dir", None)
    kwargs.pop("cors_origins", None)

    # Parse cors_origins from env var if present
    cors_origins = None
    if cors_origins_str:
        cors_origins = _parse_cors_origins(cors_origins_str)

    return create_app(working_dir=working_dir, cors_origins=cors_origins, **kwargs)


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
    parser.add_argument(
        "--password",
        help="Password for API authentication (sets CLAUDETM_PASSWORD env var)",
    )

    args = parser.parse_args()

    # If --password provided, set the environment variable for auth middleware
    if args.password:
        os.environ["CLAUDETM_PASSWORD"] = args.password

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
