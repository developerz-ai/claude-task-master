"""Pydantic response models for MCP tool implementations.

All result types returned by the tool handler functions live here so that
callers and tests can import them without pulling in the full handler graph.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# =============================================================================
# Response Models
# =============================================================================


class TaskStatus(BaseModel):
    """Status response for get_status tool."""

    goal: str
    status: str
    model: str
    current_task_index: int
    session_count: int
    run_id: str
    current_pr: int | None = None
    workflow_stage: str | None = None
    options: dict[str, Any]


class StartTaskResult(BaseModel):
    """Result from start_task tool."""

    success: bool
    message: str
    run_id: str | None = None
    status: str | None = None


class CleanResult(BaseModel):
    """Result from clean tool."""

    success: bool
    message: str
    files_removed: bool = False


class LogsResult(BaseModel):
    """Result from get_logs tool."""

    success: bool
    log_content: str | None = None
    log_file: str | None = None
    error: str | None = None


class HealthCheckResult(BaseModel):
    """Result from health_check tool."""

    status: str
    version: str
    server_name: str
    uptime_seconds: float | None = None
    active_tasks: int = 0


class PauseTaskResult(BaseModel):
    """Result from pause_task tool."""

    success: bool
    message: str
    previous_status: str | None = None
    new_status: str | None = None
    reason: str | None = None


class StopTaskResult(BaseModel):
    """Result from stop_task tool."""

    success: bool
    message: str
    previous_status: str | None = None
    new_status: str | None = None
    reason: str | None = None
    cleanup: bool = False


class ResumeTaskResult(BaseModel):
    """Result from resume_task tool."""

    success: bool
    message: str
    previous_status: str | None = None
    new_status: str | None = None


class UpdateConfigResult(BaseModel):
    """Result from update_config tool."""

    success: bool
    message: str
    updated: dict[str, bool | int | str | None] | None = None
    current: dict[str, bool | int | str | None] | None = None
    error: str | None = None


class SendMessageResult(BaseModel):
    """Result from send_message mailbox tool."""

    success: bool
    message_id: str | None = None
    message: str | None = None
    error: str | None = None


class MailboxStatusResult(BaseModel):
    """Result from check_mailbox tool."""

    success: bool
    count: int = 0
    previews: list[dict[str, Any]] = []
    last_checked: str | None = None
    total_messages_received: int = 0
    error: str | None = None


class ClearMailboxResult(BaseModel):
    """Result from clear_mailbox tool."""

    success: bool
    messages_cleared: int = 0
    message: str | None = None
    error: str | None = None


class CloneRepoResult(BaseModel):
    """Result from clone_repo tool."""

    success: bool
    message: str
    repo_url: str | None = None
    target_dir: str | None = None
    branch: str | None = None
    error: str | None = None


class SetupRepoResult(BaseModel):
    """Result from setup_repo tool."""

    success: bool
    message: str
    work_dir: str | None = None
    steps_completed: list[str] = []
    venv_path: str | None = None
    dependencies_installed: bool = False
    setup_scripts_run: list[str] = []
    error: str | None = None


class PlanRepoResult(BaseModel):
    """Result from plan_repo tool."""

    success: bool
    message: str
    work_dir: str | None = None
    goal: str | None = None
    plan: str | None = None
    criteria: str | None = None
    run_id: str | None = None
    error: str | None = None


class DeleteCodingStyleResult(BaseModel):
    """Result from delete_coding_style tool."""

    success: bool
    message: str
    deleted: bool = False
    error: str | None = None
