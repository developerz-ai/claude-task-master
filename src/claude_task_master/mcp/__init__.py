"""MCP (Model Context Protocol) server for Claude Task Master.

This module provides an MCP server that exposes claudetm functionality
as tools that other Claude instances can use.
"""

from claude_task_master.mcp.server import create_server, run_server
from claude_task_master.mcp.tools import (
    CleanResult,
    LogsResult,
    StartTaskResult,
    TaskStatus,
    clean_task,
    get_context,
    get_logs,
    get_plan,
    get_progress,
    get_status,
    initialize_task,
    list_tasks,
    resource_context,
    resource_goal,
    resource_plan,
    resource_progress,
)

__all__ = [
    # Server
    "create_server",
    "run_server",
    # Tools
    "get_status",
    "get_plan",
    "get_logs",
    "get_progress",
    "get_context",
    "clean_task",
    "initialize_task",
    "list_tasks",
    # Resources
    "resource_goal",
    "resource_plan",
    "resource_progress",
    "resource_context",
    # Response Models
    "TaskStatus",
    "StartTaskResult",
    "CleanResult",
    "LogsResult",
]
