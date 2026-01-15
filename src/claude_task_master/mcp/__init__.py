"""MCP (Model Context Protocol) server for Claude Task Master.

This module provides an MCP server that exposes claudetm functionality
as tools that other Claude instances can use.
"""

from claude_task_master.mcp.server import create_server, run_server

__all__ = ["create_server", "run_server"]
