"""Pydantic request/response models for the REST API.

This module re-exports all models from their focused sub-modules for
backward compatibility. Import from here or from the specific sub-modules:

- ``models_common`` — shared enums, validation helpers, ErrorResponse, APIInfo
- ``models_task``   — task lifecycle request/response models
- ``models_mailbox``— mailbox request/response models
- ``models_repo``   — repository setup request/response models

Usage:
    from claude_task_master.api.models import (
        PauseRequest,
        TaskStatusResponse,
        ErrorResponse,
        CloneRepoRequest,
        CloneRepoResponse,
    )

    @app.post("/control/pause", response_model=ControlResponse)
    async def pause_task(request: PauseRequest):
        ...

    @app.post("/repo/clone", response_model=CloneRepoResponse)
    async def clone_repo(request: CloneRepoRequest):
        ...
"""

from __future__ import annotations

from claude_task_master.api.models_common import (
    APIInfo,
    ErrorResponse,
    LogFormat,
    LogLevel,
    TaskStatus,
    WorkflowStage,
    _validate_model_field,
    _validate_within_workspace,
)
from claude_task_master.api.models_mailbox import (
    ClearMailboxResponse,
    MailboxMessagePreview,
    MailboxStatusResponse,
    SendMailboxMessageRequest,
    SendMailboxMessageResponse,
)
from claude_task_master.api.models_repo import (
    CloneRepoRequest,
    CloneRepoResponse,
    DeleteCodingStyleResponse,
    PlanRepoRequest,
    PlanRepoResponse,
    SetupRepoRequest,
    SetupRepoResponse,
)
from claude_task_master.api.models_task import (
    ConfigUpdateRequest,
    ContextResponse,
    ControlResponse,
    HealthResponse,
    LogsResponse,
    PauseRequest,
    PlanResponse,
    ProgressResponse,
    ResumeRequest,
    StopRequest,
    TaskDeleteResponse,
    TaskInitRequest,
    TaskInitResponse,
    TaskListItem,
    TaskListResponse,
    TaskOptionsResponse,
    TaskProgressInfo,
    TaskStatusResponse,
    WebhookStatusInfo,
)

__all__: list[str] = [
    # Helpers (re-exported for any code that imported from here)
    "_validate_within_workspace",
    "_validate_model_field",
    # Enums
    "TaskStatus",
    "WorkflowStage",
    "LogLevel",
    "LogFormat",
    # Task request models
    "PauseRequest",
    "StopRequest",
    "ResumeRequest",
    "ConfigUpdateRequest",
    "TaskInitRequest",
    # Task component models
    "TaskOptionsResponse",
    "TaskProgressInfo",
    "WebhookStatusInfo",
    # Task response models
    "TaskStatusResponse",
    "ControlResponse",
    "PlanResponse",
    "LogsResponse",
    "ProgressResponse",
    "ContextResponse",
    "TaskListItem",
    "TaskListResponse",
    "HealthResponse",
    "TaskInitResponse",
    "TaskDeleteResponse",
    # Base response models
    "ErrorResponse",
    "APIInfo",
    # Mailbox models
    "SendMailboxMessageRequest",
    "SendMailboxMessageResponse",
    "MailboxMessagePreview",
    "MailboxStatusResponse",
    "ClearMailboxResponse",
    # Repo models
    "CloneRepoRequest",
    "SetupRepoRequest",
    "PlanRepoRequest",
    "CloneRepoResponse",
    "SetupRepoResponse",
    "PlanRepoResponse",
    "DeleteCodingStyleResponse",
]
