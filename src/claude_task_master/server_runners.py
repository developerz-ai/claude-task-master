"""Async server runner coroutines for the Claude Task Master unified server.

Contains:
- :func:`_run_rest_server` — runs the FastAPI/uvicorn REST API as an async task
- :func:`_run_mcp_server` — runs the MCP server as an async task
- :func:`_run_servers_async` — starts both concurrently with graceful shutdown
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


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
        import uvicorn  # noqa: PLC0415

        from claude_task_master.api.server import create_app  # noqa: PLC0415
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
        import uvicorn  # noqa: PLC0415

        from claude_task_master.mcp.server import (  # noqa: PLC0415
            _get_authenticated_app,
            create_server,
        )
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
    except BaseException:
        # Any failure (cancellation, or one server raising) must tear down the
        # sibling: gather(return_exceptions=False) propagates the first error
        # immediately and would otherwise leave the other task running
        # unmanaged until run_servers() closes the loop.
        logger.info("Shutting down servers...")
        rest_task.cancel()
        mcp_task.cancel()
        # Wait for tasks to complete cancellation
        await asyncio.gather(rest_task, mcp_task, return_exceptions=True)
        raise


__all__ = ["_run_rest_server", "_run_mcp_server", "_run_servers_async"]
