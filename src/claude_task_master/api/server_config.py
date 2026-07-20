"""Server configuration helpers for the Claude Task Master REST API.

This module contains environment-variable defaults, the lifespan context manager,
and the CORS / authentication middleware wiring extracted from server.py to keep
each file under the 500-LOC limit.

Exported symbols are re-imported by server.py and exposed there so that
existing ``from claude_task_master.api.server import ...`` call-sites keep working.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from claude_task_master import __version__
from claude_task_master.auth import is_auth_enabled

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

try:
    from claude_task_master.auth.middleware import PasswordAuthMiddleware

    AUTH_MIDDLEWARE_AVAILABLE = True
except ImportError:
    AUTH_MIDDLEWARE_AVAILABLE = False
    PasswordAuthMiddleware = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

__all__ = [
    # Environment defaults
    "API_HOST",
    "API_PORT",
    "CORS_ORIGINS",
    # Availability flags
    "FASTAPI_AVAILABLE",
    "AUTH_MIDDLEWARE_AVAILABLE",
    # Helpers
    "_log_api_config",
    "_parse_cors_origins",
    "_configure_cors",
    "_configure_auth",
    "lifespan",
]

# =============================================================================
# Environment Configuration
# =============================================================================

# Server defaults
API_HOST = os.getenv("CLAUDETM_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("CLAUDETM_API_PORT", "8000"))

# CORS configuration
# Comma-separated list of allowed origins, or "*" for all
CORS_ORIGINS = os.getenv("CLAUDETM_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")

# NOTE: Authentication for the REST API is enforced solely by PasswordAuthMiddleware
# (CLAUDETM_PASSWORD / CLAUDETM_PASSWORD_HASH). There is deliberately no separate
# CLAUDETM_API_KEY here: that name is owned by the profile system for a real
# Anthropic API key (see cli_commands/profile.py), so reading — and especially
# logging — it from the server would collide with it and leak a credential fragment.


def _log_api_config(
    host: str, port: int, cors_origins: list[str], auth_enabled: bool = False
) -> None:
    """Log API configuration at startup.

    Args:
        host: The host address.
        port: The port number.
        cors_origins: List of CORS origins.
        auth_enabled: Whether password authentication is enabled.
    """
    logger.info("=" * 50)
    logger.info("API Configuration:")
    logger.info(f"  Host: {host}")
    logger.info(f"  Port: {port}")
    logger.info(f"  CORS Origins: {', '.join(cors_origins) if cors_origins else '(none)'}")
    logger.info(f"  Password Auth: {'enabled' if auth_enabled else 'disabled'}")
    logger.info("=" * 50)


# =============================================================================
# Lifespan Context
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for FastAPI app.

    Handles startup and shutdown events, including:
    - Recording server start time for uptime tracking
    - Logging startup/shutdown messages
    - Logging authentication status
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

    # Log authentication status on startup
    auth_enabled = getattr(app.state, "auth_enabled", False)
    if auth_enabled:
        logger.info("🔐 Password authentication is enabled")
    else:
        logger.info("🔓 Password authentication is disabled")

    yield

    # Shutdown
    logger.info("Claude Task Master API shutting down")


# =============================================================================
# Authentication Configuration
# =============================================================================


def _configure_auth(app: FastAPI) -> bool:
    """Configure authentication middleware on the FastAPI app.

    Adds PasswordAuthMiddleware if authentication is enabled via environment
    variables (CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH).

    Args:
        app: The FastAPI application instance.

    Returns:
        True if authentication was configured, False otherwise.
    """
    if not AUTH_MIDDLEWARE_AVAILABLE:
        logger.debug("Auth middleware not available (Starlette not installed)")
        return False

    if not is_auth_enabled():
        logger.debug("Password authentication not configured (no CLAUDETM_PASSWORD set)")
        return False

    # Add the password authentication middleware
    assert PasswordAuthMiddleware is not None  # ensured by AUTH_MIDDLEWARE_AVAILABLE
    app.add_middleware(PasswordAuthMiddleware)

    logger.info("Password authentication enabled")
    return True


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
    if not FASTAPI_AVAILABLE:
        logger.warning("CORS middleware not available (FastAPI not installed)")
        return

    allowed_origins = origins if origins is not None else _parse_cors_origins(CORS_ORIGINS)

    # Disable credentials when wildcard origin is used (CORS spec requirement)
    allow_credentials = "*" not in allowed_origins
    if "*" in allowed_origins:
        logger.warning(
            "CORS '*' wildcard configured; disabling allow_credentials per spec. "
            "Use explicit origins for credentialed requests."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    logger.debug(f"CORS configured with origins: {allowed_origins}")
