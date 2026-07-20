"""MCP Tool implementations for Claude Task Master.

This module is the public surface for all MCP tool functions.  The actual
implementations live in focused sub-modules; everything is re-exported here
so that external callers and tests can keep importing from
``claude_task_master.mcp.tools`` unchanged.

Sub-modules
-----------
- :mod:`.tool_models`            — Pydantic response models
- :mod:`.tool_handlers_task`     — query/lifecycle handlers
- :mod:`.tool_handlers_control`  — pause / stop / resume / update_config
- :mod:`.tool_handlers_files`    — delete_coding_style
- :mod:`.tool_handlers_mailbox`  — send_message / check_mailbox / clear_mailbox
- :mod:`.tool_handlers_repo`     — clone_repo / plan_repo + workspace helpers
- :mod:`.tool_handlers_setup`    — setup_repo

Patchable globals
-----------------
``DEFAULT_WORKSPACE_BASE`` and ``is_auth_enabled`` live here so that tests can
override them via::

    monkeypatch.setattr(tools_mod, "DEFAULT_WORKSPACE_BASE", tmp_path)
    monkeypatch.setattr(tools_mod, "is_auth_enabled", lambda: False)

Handler functions in the sub-modules read both names through a deferred lookup
of this module (``import claude_task_master.mcp.tools``) so patches are always
visible without creating circular imports at load time.

``shutil`` is also imported here (not just in the handlers) because one test
patches ``mcp_tools.shutil.rmtree`` via ``patch.object``.
"""

from __future__ import annotations

import shutil  # noqa: F401 — tests patch mcp_tools.shutil.rmtree via patch.object
from pathlib import Path

from claude_task_master.auth.password import is_auth_enabled  # noqa: F401 — tests patch this
from claude_task_master.mcp.tool_handlers_control import (
    pause_task,
    resume_task,
    stop_task,
    update_config,
)
from claude_task_master.mcp.tool_handlers_files import delete_coding_style
from claude_task_master.mcp.tool_handlers_mailbox import (
    check_mailbox,
    clear_mailbox,
    send_message,
)
from claude_task_master.mcp.tool_handlers_repo import (
    _REPO_AUTH_REQUIRED_MESSAGE,
    WorkspaceConfinementError,
    _extract_repo_name,
    _resolve_within_workspace,
    clone_repo,
    plan_repo,
)
from claude_task_master.mcp.tool_handlers_setup import setup_repo
from claude_task_master.mcp.tool_handlers_task import (
    clean_task,
    get_context,
    get_logs,
    get_plan,
    get_progress,
    get_status,
    health_check,
    initialize_task,
    list_tasks,
    resource_context,
    resource_goal,
    resource_plan,
    resource_progress,
)
from claude_task_master.mcp.tool_models import (
    CleanResult,
    ClearMailboxResult,
    CloneRepoResult,
    DeleteCodingStyleResult,
    HealthCheckResult,
    LogsResult,
    MailboxStatusResult,
    PauseTaskResult,
    PlanRepoResult,
    ResumeTaskResult,
    SendMessageResult,
    SetupRepoResult,
    StartTaskResult,
    StopTaskResult,
    TaskStatus,
    UpdateConfigResult,
)

# ---------------------------------------------------------------------------
# Patchable workspace constant — tests patch this via:
#   monkeypatch.setattr(tools_mod, "DEFAULT_WORKSPACE_BASE", tmp_path)
# Handler functions in sub-modules read it through a deferred import of this
# module so the patched value is always visible at call time.
# ---------------------------------------------------------------------------

DEFAULT_WORKSPACE_BASE: Path = Path.home() / "workspace" / "claude-task-master"

__all__ = [
    # Patchable globals
    "DEFAULT_WORKSPACE_BASE",
    "is_auth_enabled",
    # shutil (tests patch mcp_tools.shutil)
    "shutil",
    # Response models
    "TaskStatus",
    "StartTaskResult",
    "CleanResult",
    "LogsResult",
    "HealthCheckResult",
    "PauseTaskResult",
    "StopTaskResult",
    "ResumeTaskResult",
    "UpdateConfigResult",
    "SendMessageResult",
    "MailboxStatusResult",
    "ClearMailboxResult",
    "CloneRepoResult",
    "SetupRepoResult",
    "PlanRepoResult",
    "DeleteCodingStyleResult",
    # Task handlers
    "get_status",
    "get_plan",
    "get_logs",
    "get_progress",
    "get_context",
    "clean_task",
    "initialize_task",
    "list_tasks",
    "health_check",
    # Control handlers
    "pause_task",
    "stop_task",
    "resume_task",
    "update_config",
    # File handlers
    "delete_coding_style",
    # Mailbox handlers
    "send_message",
    "check_mailbox",
    "clear_mailbox",
    # Repo helpers
    "WorkspaceConfinementError",
    "_REPO_AUTH_REQUIRED_MESSAGE",
    "_extract_repo_name",
    "_resolve_within_workspace",
    # Repo handlers
    "clone_repo",
    "setup_repo",
    "plan_repo",
    # Resources
    "resource_goal",
    "resource_plan",
    "resource_progress",
    "resource_context",
]
