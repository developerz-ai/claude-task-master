"""MCP-specific authentication handler for Claude Task Master.

This module provides authentication middleware for MCP network transports
(SSE and streamable-http). It uses the shared password authentication
module to validate Bearer tokens in the Authorization header.

The middleware wraps the Starlette apps created by FastMCP to add
authentication before MCP protocol handling.

Security Notes:
    - Authentication is only enforced for network transports (SSE, streamable-http)
    - stdio transport is inherently secure and does not require authentication
    - The health endpoint (/health) is public for monitoring purposes
    - MCP-specific paths like /sse and /mcp are protected when auth is enabled
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.applications import Starlette

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# MCP-specific public paths that don't require authentication
# These are typically health/readiness endpoints for container orchestration
MCP_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/healthz",
        "/ready",
        "/livez",
    }
)


# =============================================================================
# Middleware Application
# =============================================================================


def add_auth_middleware(
    app: Starlette,
    public_paths: frozenset[str] | None = None,
) -> Starlette:
    """Add password authentication middleware to a Starlette app.

    This function wraps an existing Starlette app (from FastMCP) with
    our PasswordAuthMiddleware to enforce Bearer token authentication.

    Args:
        app: The Starlette application to wrap (from FastMCP.sse_app() or
            FastMCP.streamable_http_app()).
        public_paths: Set of paths that don't require authentication.
            Defaults to MCP_PUBLIC_PATHS.

    Returns:
        The same Starlette app with authentication middleware added.

    Raises:
        ImportError: If Starlette or auth middleware is not available.

    Example:
        >>> from mcp.server.fastmcp import FastMCP
        >>> mcp = FastMCP("my-server")
        >>> app = mcp.sse_app()
        >>> app_with_auth = add_auth_middleware(app)
    """
    # Import here to avoid circular imports and handle optional deps
    try:
        from claude_task_master.auth.middleware import PasswordAuthMiddleware
    except ImportError as e:
        raise ImportError(
            "Authentication middleware not available. "
            "Install with: pip install 'claude-task-master[api]'"
        ) from e

    # Use provided paths or default MCP public paths
    paths = public_paths if public_paths is not None else MCP_PUBLIC_PATHS

    # Add the middleware
    app.add_middleware(PasswordAuthMiddleware, public_paths=paths)

    logger.debug(f"Added authentication middleware to MCP app with {len(paths)} public paths")

    return app


def is_auth_required_for_transport(transport: str) -> bool:
    """Check if authentication should be required for a transport type.

    Authentication is only relevant for network transports (SSE, streamable-http).
    stdio transport is inherently secure as it uses local process communication.

    Args:
        transport: The transport type ("stdio", "sse", "streamable-http").

    Returns:
        True if authentication should be enforced, False otherwise.
    """
    return transport.lower() in ("sse", "streamable-http")


def check_auth_config(transport: str, host: str) -> tuple[bool, str | None]:
    """Check authentication configuration and return status with any warnings.

    This function checks if authentication is properly configured for the
    given transport and host combination.

    Args:
        transport: The transport type being used.
        host: The host address the server will bind to.

    Returns:
        Tuple of (auth_enabled, warning_message).
        - auth_enabled: True if authentication is configured and will be used.
        - warning_message: Warning message if configuration is insecure, None otherwise.
    """
    from claude_task_master.auth import is_auth_enabled

    # Check if this transport requires auth
    if not is_auth_required_for_transport(transport):
        return False, None

    auth_enabled = is_auth_enabled()
    is_localhost = host in ("127.0.0.1", "localhost", "::1")

    # Generate appropriate warnings
    warning = None
    if not auth_enabled:
        if is_localhost:
            # Localhost without auth is acceptable but worth noting
            warning = (
                "MCP server running without authentication. "
                "This is acceptable for localhost but consider enabling "
                "authentication for security. Set CLAUDETM_PASSWORD or "
                "CLAUDETM_PASSWORD_HASH environment variable."
            )
        else:
            # Non-localhost without auth is a security concern
            warning = (
                f"MCP server binding to non-localhost address ({host}) "
                "without authentication. This is a security risk. "
                "Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH environment variable."
            )

    return auth_enabled, warning
