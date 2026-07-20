"""MCP server runner, entry-point helpers, and network-transport wrappers.

Provides:

- :data:`TransportType` — Literal type for the three transport modes
- :func:`_get_authenticated_app` — wraps a FastMCP instance in a Starlette app
- :func:`_run_network_transport_async` — async uvicorn runner for network transports
- :func:`_log_server_config` — log startup config
- :func:`run_server` — top-level server launcher
- :func:`main` — CLI entry point (``claudetm-mcp-server``)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from starlette.applications import Starlette

# Import auth utilities - optional, only needed for network transports
try:
    from claude_task_master.auth import is_auth_enabled
    from claude_task_master.mcp.auth import add_auth_middleware, check_auth_config

    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    is_auth_enabled = lambda: False  # noqa: E731
    add_auth_middleware = None  # type: ignore[assignment]
    check_auth_config = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Security: Default host for network transports
MCP_HOST = os.getenv("CLAUDETM_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("CLAUDETM_MCP_PORT", "8080"))

# Transport type alias
TransportType = Literal["stdio", "sse", "streamable-http"]


def _get_authenticated_app(
    mcp: FastMCP,
    transport: TransportType,
    mount_path: str | None = None,
) -> Starlette:
    """Get the Starlette app with authentication middleware if configured.

    Args:
        mcp: The FastMCP server instance.
        transport: The transport type (sse or streamable-http).
        mount_path: Optional mount path for SSE transport.

    Returns:
        Starlette application with optional authentication middleware.
    """
    # Get the appropriate app based on transport
    if transport == "sse":
        app = mcp.sse_app(mount_path)
    else:  # streamable-http
        app = mcp.streamable_http_app()

    # Add authentication middleware if enabled
    if AUTH_AVAILABLE and is_auth_enabled() and add_auth_middleware is not None:
        logger.info("Adding password authentication to MCP server")
        add_auth_middleware(app)

    return app


async def _run_network_transport_async(
    mcp: FastMCP,
    transport: TransportType,
    host: str,
    port: int,
    mount_path: str | None = None,
) -> None:
    """Run the MCP server with network transport and authentication.

    This is an async function that runs the server with uvicorn,
    adding authentication middleware for network transports.

    Args:
        mcp: The FastMCP server instance.
        transport: The transport type (sse or streamable-http).
        host: Host to bind to.
        port: Port to bind to.
        mount_path: Optional mount path for SSE transport.
    """
    import uvicorn

    # Get the app with authentication
    app = _get_authenticated_app(mcp, transport, mount_path)

    # Run with uvicorn
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=mcp.settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


def _log_server_config(
    transport: TransportType,
    host: str,
    port: int,
    auth_enabled: bool,
) -> None:
    """Log server configuration at startup.

    Args:
        transport: The transport type.
        host: The host address.
        port: The port number.
        auth_enabled: Whether authentication is enabled.
    """
    logger.info("=" * 50)
    logger.info("MCP Server Configuration:")
    logger.info(f"  Transport: {transport}")
    if transport != "stdio":
        logger.info(f"  Host: {host}")
        logger.info(f"  Port: {port}")
        logger.info(f"  Password Auth: {'enabled' if auth_enabled else 'disabled'}")
    logger.info("=" * 50)


def run_server(
    name: str = "claude-task-master",
    working_dir: str | None = None,
    transport: TransportType = "stdio",
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Run the MCP server.

    Args:
        name: Server name for identification.
        working_dir: Working directory for task execution.
        transport: Transport type (stdio, sse, streamable-http).
        host: Host to bind to (only for network transports). Defaults to 127.0.0.1.
        port: Port to bind to (only for network transports). Defaults to 8080.

    Security:
        For network transports (sse, streamable-http):
        - Defaults to localhost binding for security
        - AUTHENTICATION REQUIRED: Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH
          to enable password-based authentication
        - Clients must provide password as Bearer token: Authorization: Bearer <password>
        - When binding to non-localhost addresses, authentication is REQUIRED for security
        - Default authentication is disabled - must be explicitly enabled via
          CLAUDETM_PASSWORD env var or --password CLI arg
    """
    import anyio

    from claude_task_master.mcp.server import create_server  # noqa: PLC0415

    effective_host = host or MCP_HOST
    effective_port = port or MCP_PORT

    # Check authentication configuration for network transports
    if transport != "stdio" and AUTH_AVAILABLE and check_auth_config is not None:
        auth_enabled, warning = check_auth_config(transport, effective_host)
        if warning:
            logger.warning(warning)
    else:
        auth_enabled = AUTH_AVAILABLE and is_auth_enabled()

    # Log configuration
    _log_server_config(transport, effective_host, effective_port, auth_enabled)

    # Enforce auth for non-localhost network binds (as promised in docstring)
    if transport != "stdio" and effective_host not in ("127.0.0.1", "localhost", "::1"):
        if not auth_enabled:
            logger.error(
                f"MCP server cannot bind to non-localhost address ({effective_host}) "
                "without authentication. Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH."
            )
            raise SystemExit(1)

    # Create the MCP server
    mcp = create_server(name=name, working_dir=working_dir)

    # Configure host/port in FastMCP settings for network transports
    if transport != "stdio":
        mcp.settings.host = effective_host
        mcp.settings.port = effective_port

    # Run based on transport type
    if transport == "stdio":
        # stdio transport - no authentication needed, use FastMCP directly
        mcp.run(transport="stdio")
    else:
        # Network transports - use custom runner with authentication
        anyio.run(
            lambda: _run_network_transport_async(mcp, transport, effective_host, effective_port)
        )


def main() -> None:
    """Main entry point for running the MCP server standalone."""
    import argparse

    parser = argparse.ArgumentParser(description="Run Claude Task Master MCP server")
    parser.add_argument(
        "--name",
        default="claude-task-master",
        help="Server name",
    )
    parser.add_argument(
        "--working-dir",
        help="Working directory for task execution",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport type (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=MCP_HOST,
        help=f"Host to bind to for network transports (default: {MCP_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=MCP_PORT,
        help=f"Port to bind to for network transports (default: {MCP_PORT})",
    )
    parser.add_argument(
        "--password",
        help=(
            "Password for MCP authentication (sets CLAUDETM_PASSWORD env var). "
            "Required for secure access when using network transports."
        ),
    )

    args = parser.parse_args()

    # If --password provided, set the environment variable for auth middleware
    if args.password:
        os.environ["CLAUDETM_PASSWORD"] = args.password

    run_server(
        name=args.name,
        working_dir=args.working_dir,
        transport=args.transport,
        host=args.host,
        port=args.port,
    )
