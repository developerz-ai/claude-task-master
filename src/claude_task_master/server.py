"""Unified server for Claude Task Master.

This module provides a unified server that runs both REST API and MCP servers
together with shared authentication configuration.

Features:
- Runs REST API (FastAPI/uvicorn) and MCP server concurrently
- Shared password authentication for both servers
- Environment variable configuration
- Single entry point for Docker containers

Usage:
    # Run from command line
    claudetm-server --password mypassword --rest-port 8000 --mcp-port 8080

    # Or programmatically
    from claude_task_master.server import run_servers
    run_servers(password="mypassword", rest_port=8000, mcp_port=8080)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from claude_task_master import __version__
from claude_task_master.auth import is_auth_enabled

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop

logger = logging.getLogger(__name__)

# =============================================================================
# Environment Configuration
# =============================================================================

# Default ports for unified server
REST_PORT = int(os.getenv("CLAUDETM_REST_PORT", "8000"))
MCP_PORT = int(os.getenv("CLAUDETM_MCP_PORT", "8080"))

# Default host - localhost for security
SERVER_HOST = os.getenv("CLAUDETM_SERVER_HOST", "127.0.0.1")


def _validate_mcp_transport(
    transport: str,
) -> Literal["sse", "streamable-http"]:
    """Validate MCP transport type.

    Args:
        transport: The transport type from environment variable.

    Returns:
        Valid transport type.

    Raises:
        ValueError: If transport is not a valid option.
    """
    valid_transports = {"sse", "streamable-http"}
    if transport not in valid_transports:
        raise ValueError(
            f"Invalid CLAUDETM_MCP_TRANSPORT={transport!r}. "
            f"Must be one of: {', '.join(sorted(valid_transports))}"
        )
    return transport  # type: ignore[return-value]


# MCP transport type for unified server
_mcp_transport_env = os.getenv("CLAUDETM_MCP_TRANSPORT", "sse")
try:
    MCP_TRANSPORT: Literal["sse", "streamable-http"] = _validate_mcp_transport(_mcp_transport_env)
except ValueError as err:
    logger.error(str(err))
    raise


# =============================================================================
# Server Runners
# =============================================================================


async def _run_rest_server(
    host: str,
    port: int,
    working_dir: Path,
    cors_origins: list[str] | None = None,
    log_level: str = "info",
) -> None:
    """Run the REST API server as an async task.

    Args:
        host: Host to bind to.
        port: Port to bind to.
        working_dir: Working directory for task execution.
        cors_origins: Optional CORS origins.
        log_level: Uvicorn log level.
    """
    try:
        import uvicorn

        from claude_task_master.api.server import create_app
    except ImportError as err:
        logger.error(
            "REST API dependencies not installed. Install with: pip install claude-task-master[api]"
        )
        raise ImportError(
            "REST API dependencies not installed. Install with: pip install claude-task-master[api]"
        ) from err

    app = create_app(working_dir=working_dir, cors_origins=cors_origins)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
    )
    server = uvicorn.Server(config)

    logger.info(f"Starting REST API server on http://{host}:{port}")
    await server.serve()


async def _run_mcp_server(
    host: str,
    port: int,
    working_dir: Path,
    transport: Literal["sse", "streamable-http"] = "sse",
    log_level: str = "info",
) -> None:
    """Run the MCP server as an async task.

    Args:
        host: Host to bind to.
        port: Port to bind to.
        working_dir: Working directory for task execution.
        transport: MCP transport type (sse or streamable-http).
        log_level: Uvicorn log level.
    """
    try:
        import uvicorn

        from claude_task_master.mcp.server import _get_authenticated_app, create_server
    except ImportError as err:
        logger.error(
            "MCP dependencies not installed. Install with: pip install claude-task-master[mcp]"
        )
        raise ImportError(
            "MCP dependencies not installed. Install with: pip install claude-task-master[mcp]"
        ) from err

    mcp = create_server(name="claude-task-master", working_dir=str(working_dir))
    mcp.settings.host = host
    mcp.settings.port = port
    # FastMCP expects uppercase log level; type: ignore for mypy as it's a string literal
    mcp.settings.log_level = log_level.upper()  # type: ignore[assignment]

    # Get the Starlette app with authentication
    app = _get_authenticated_app(mcp, transport)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
    )
    server = uvicorn.Server(config)

    logger.info(f"Starting MCP server ({transport}) on http://{host}:{port}")
    await server.serve()


async def _run_servers_async(
    rest_port: int,
    mcp_port: int,
    host: str,
    working_dir: Path,
    mcp_transport: Literal["sse", "streamable-http"],
    cors_origins: list[str] | None,
    log_level: str,
) -> None:
    """Run both servers concurrently.

    Args:
        rest_port: Port for REST API server.
        mcp_port: Port for MCP server.
        host: Host to bind both servers to.
        working_dir: Working directory for task execution.
        mcp_transport: MCP transport type.
        cors_origins: Optional CORS origins for REST API.
        log_level: Log level for both servers.
    """
    # Create tasks for both servers
    rest_task = asyncio.create_task(
        _run_rest_server(
            host=host,
            port=rest_port,
            working_dir=working_dir,
            cors_origins=cors_origins,
            log_level=log_level,
        ),
        name="rest-server",
    )

    mcp_task = asyncio.create_task(
        _run_mcp_server(
            host=host,
            port=mcp_port,
            working_dir=working_dir,
            transport=mcp_transport,
            log_level=log_level,
        ),
        name="mcp-server",
    )

    # Wait for both servers (they run until shutdown)
    try:
        await asyncio.gather(rest_task, mcp_task)
    except asyncio.CancelledError:
        # Graceful shutdown - cancel remaining tasks
        logger.info("Shutting down servers...")
        rest_task.cancel()
        mcp_task.cancel()
        # Wait for tasks to complete cancellation
        await asyncio.gather(rest_task, mcp_task, return_exceptions=True)
        raise


def _setup_signal_handlers(loop: AbstractEventLoop) -> None:
    """Set up signal handlers for graceful shutdown.

    Args:
        loop: The event loop to configure signal handlers for.
    """

    def signal_handler(sig: signal.Signals) -> None:
        logger.info(f"Received signal {sig.name}, initiating shutdown...")
        # Cancel all running tasks
        for task in asyncio.all_tasks(loop):
            task.cancel()

    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler, sig)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass


def _log_server_config(
    host: str,
    rest_port: int,
    mcp_port: int,
    mcp_transport: str,
    auth_enabled: bool,
    working_dir: Path,
) -> None:
    """Log unified server configuration at startup.

    Args:
        host: The host address.
        rest_port: REST API port.
        mcp_port: MCP server port.
        mcp_transport: MCP transport type.
        auth_enabled: Whether authentication is enabled.
        working_dir: Working directory.
    """
    logger.info("=" * 60)
    logger.info(f"Claude Task Master Unified Server v{__version__}")
    logger.info("=" * 60)
    logger.info("Server Configuration:")
    logger.info(f"  Host: {host}")
    logger.info(f"  REST API Port: {rest_port} (http://{host}:{rest_port})")
    logger.info(f"  MCP Server Port: {mcp_port} (http://{host}:{mcp_port})")
    logger.info(f"  MCP Transport: {mcp_transport}")
    logger.info(f"  Working Directory: {working_dir}")
    logger.info(f"  Password Auth: {'enabled' if auth_enabled else 'disabled'}")
    logger.info("=" * 60)

    if auth_enabled:
        logger.info("🔐 Password authentication is enabled for both servers")
    else:
        logger.warning("🔓 Password authentication is disabled")
        if host not in ("127.0.0.1", "localhost", "::1"):
            logger.warning(
                f"⚠️  Server binding to non-localhost ({host}) without authentication. "
                "Set CLAUDETM_PASSWORD for security."
            )


# =============================================================================
# Main Entry Point
# =============================================================================


def run_servers(
    rest_port: int | None = None,
    mcp_port: int | None = None,
    host: str | None = None,
    working_dir: str | Path | None = None,
    mcp_transport: Literal["sse", "streamable-http"] | None = None,
    cors_origins: list[str] | None = None,
    log_level: str = "info",
) -> None:
    """Run both REST API and MCP servers together.

    This is the main entry point for the unified server. It starts both the
    REST API server (FastAPI/uvicorn) and the MCP server concurrently with
    shared authentication configuration.

    Args:
        rest_port: Port for REST API server. Defaults to CLAUDETM_REST_PORT or 8000.
        mcp_port: Port for MCP server. Defaults to CLAUDETM_MCP_PORT or 8080.
        host: Host to bind both servers to. Defaults to CLAUDETM_SERVER_HOST or 127.0.0.1.
        working_dir: Working directory for task execution. Defaults to cwd.
        mcp_transport: MCP transport type (sse, streamable-http). Defaults to sse.
        cors_origins: List of allowed CORS origins for REST API.
        log_level: Log level for both servers (debug, info, warning, error).

    Environment Variables:
        CLAUDETM_PASSWORD: Password for authentication (shared by both servers).
        CLAUDETM_REST_PORT: Default REST API port (8000).
        CLAUDETM_MCP_PORT: Default MCP port (8080).
        CLAUDETM_SERVER_HOST: Default host (127.0.0.1).
        CLAUDETM_MCP_TRANSPORT: Default MCP transport (sse).

    Example:
        >>> import os
        >>> os.environ["CLAUDETM_PASSWORD"] = "secret"
        >>> run_servers(rest_port=8000, mcp_port=8080)

    Security:
        - When binding to non-localhost addresses, password authentication should be enabled
        - Both servers share the same authentication credentials
        - Authentication is enabled via CLAUDETM_PASSWORD environment variable
    """
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Resolve configuration
    effective_host = host or SERVER_HOST
    effective_rest_port = rest_port or REST_PORT
    effective_mcp_port = mcp_port or MCP_PORT
    effective_transport = mcp_transport or MCP_TRANSPORT
    effective_working_dir = Path(working_dir) if working_dir else Path.cwd()

    # Check authentication status
    auth_enabled = is_auth_enabled()

    # Log configuration
    _log_server_config(
        host=effective_host,
        rest_port=effective_rest_port,
        mcp_port=effective_mcp_port,
        mcp_transport=effective_transport,
        auth_enabled=auth_enabled,
        working_dir=effective_working_dir,
    )

    # Security check for non-localhost binding
    if effective_host not in ("127.0.0.1", "localhost", "::1") and not auth_enabled:
        logger.warning(
            "⚠️  Running without authentication on a network-accessible address is not recommended. "
            "Set CLAUDETM_PASSWORD to enable authentication."
        )

    # Create and run event loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Set up signal handlers for graceful shutdown
        _setup_signal_handlers(loop)

        # Run both servers
        loop.run_until_complete(
            _run_servers_async(
                rest_port=effective_rest_port,
                mcp_port=effective_mcp_port,
                host=effective_host,
                working_dir=effective_working_dir,
                mcp_transport=effective_transport,
                cors_origins=cors_origins,
                log_level=log_level,
            )
        )
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except asyncio.CancelledError:
        logger.info("Server tasks cancelled, shutting down...")
    finally:
        # Cleanup
        try:
            loop.close()
        except Exception:
            pass
        logger.info("Unified server stopped")


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> None:
    """Main entry point for the unified server CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run Claude Task Master unified server (REST API + MCP)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default settings (localhost only)
  claudetm-server

  # Run with authentication
  claudetm-server --password mypassword

  # Run on all interfaces with custom ports
  claudetm-server --host 0.0.0.0 --rest-port 8000 --mcp-port 8080 --password mypassword

  # Run with streamable-http transport for MCP
  claudetm-server --mcp-transport streamable-http --password mypassword

Environment Variables:
  CLAUDETM_PASSWORD       Password for authentication (or use --password)
  CLAUDETM_SERVER_HOST    Default host (127.0.0.1)
  CLAUDETM_REST_PORT      Default REST API port (8000)
  CLAUDETM_MCP_PORT       Default MCP port (8080)
  CLAUDETM_MCP_TRANSPORT  Default MCP transport (sse)
  CLAUDETM_CORS_ORIGINS   CORS origins for REST API (comma-separated)
""",
    )

    parser.add_argument(
        "--host",
        default=SERVER_HOST,
        help=f"Host to bind both servers to (default: {SERVER_HOST})",
    )
    parser.add_argument(
        "--rest-port",
        type=int,
        default=REST_PORT,
        help=f"Port for REST API server (default: {REST_PORT})",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=MCP_PORT,
        help=f"Port for MCP server (default: {MCP_PORT})",
    )
    parser.add_argument(
        "--mcp-transport",
        choices=["sse", "streamable-http"],
        default=MCP_TRANSPORT,
        help=f"MCP transport type (default: {MCP_TRANSPORT})",
    )
    parser.add_argument(
        "--working-dir",
        help="Working directory for task execution (default: current directory)",
    )
    parser.add_argument(
        "--cors-origins",
        help="Comma-separated list of CORS origins for REST API",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="info",
        help="Log level (default: info)",
    )
    parser.add_argument(
        "--password",
        help="Password for authentication (sets CLAUDETM_PASSWORD env var)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()

    # If --password provided, set the environment variable for auth
    if args.password:
        os.environ["CLAUDETM_PASSWORD"] = args.password

    # Parse CORS origins if provided
    cors_origins = None
    if args.cors_origins:
        cors_origins = [origin.strip() for origin in args.cors_origins.split(",") if origin.strip()]

    # Run servers
    run_servers(
        rest_port=args.rest_port,
        mcp_port=args.mcp_port,
        host=args.host,
        working_dir=args.working_dir,
        mcp_transport=args.mcp_transport,
        cors_origins=cors_origins,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
