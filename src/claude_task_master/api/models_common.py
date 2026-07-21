"""Common enums, validation helpers, and base response models for the REST API.

Shared foundations used by the other api/models_*.py sub-modules:
- Validation helpers (_validate_within_workspace, _validate_model_field)
- Enums (TaskStatus, WorkflowStage, LogLevel, LogFormat)
- Base response models (ErrorResponse, APIInfo)
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

__all__ = [
    # Helpers
    "_validate_within_workspace",
    "_validate_model_field",
    # Enums
    "TaskStatus",
    "WorkflowStage",
    "LogLevel",
    "LogFormat",
    # Models
    "ErrorResponse",
    "APIInfo",
    "TaskProgressInfo",
    "WebhookStatusInfo",
]


# =============================================================================
# Validation Helpers
# =============================================================================


def _validate_within_workspace(value: str) -> str:
    """Validate that *value* resolves inside the repo workspace base.

    Used by repo request models to reject path-traversal escapes (e.g.
    ``target_dir="/etc"`` or ``"../../root"``) at request-parse time, mirroring
    the confinement enforced in ``mcp.tools``.

    Args:
        value: The user-supplied filesystem path.

    Returns:
        The original value, unchanged, when it is inside the workspace base.

    Raises:
        ValueError: If the path escapes the workspace base (surfaced as HTTP 422).
    """
    from claude_task_master.mcp.tools import (
        WorkspaceConfinementError,
        _resolve_within_workspace,
    )

    try:
        _resolve_within_workspace(value)
    except WorkspaceConfinementError as exc:
        raise ValueError(str(exc)) from exc
    return value


def _validate_model_field(value: str) -> str:
    """Validate *value* against the shared model registry.

    Routes the REST request models through the one
    :func:`~claude_task_master.core.agent_models.validate_model` path, so the API
    accepts exactly the identifiers the rest of the system does (every
    ``ModelType`` value) instead of a hard-coded ``opus|sonnet|haiku`` regex that
    silently rejected ``fable`` and ``sonnet_1m``.

    Args:
        value: The user-supplied model identifier.

    Returns:
        The original value, unchanged, when it names a recognised model.

    Raises:
        ValueError: If the model is not recognised (surfaced as HTTP 422).
    """
    from claude_task_master.core.agent_models import validate_model

    validate_model(value)
    return value


# =============================================================================
# Enums
# =============================================================================


class TaskStatus(StrEnum):
    """Valid task status values."""

    PLANNING = "planning"
    WORKING = "working"
    BLOCKED = "blocked"
    PAUSED = "paused"
    STOPPED = "stopped"
    SUCCESS = "success"
    FAILED = "failed"


class WorkflowStage(StrEnum):
    """Valid workflow stage values for PR lifecycle."""

    WORKING = "working"
    PR_CREATED = "pr_created"
    WAITING_CI = "waiting_ci"
    CI_FAILED = "ci_failed"
    WAITING_REVIEWS = "waiting_reviews"
    ADDRESSING_REVIEWS = "addressing_reviews"
    RESOLVING_CONFLICTS = "resolving_conflicts"
    READY_TO_MERGE = "ready_to_merge"
    MERGED = "merged"


class LogLevel(StrEnum):
    """Valid log level values."""

    QUIET = "quiet"
    NORMAL = "normal"
    VERBOSE = "verbose"


class LogFormat(StrEnum):
    """Valid log format values."""

    TEXT = "text"
    JSON = "json"


# =============================================================================
# Base Response Models
# =============================================================================


class ErrorResponse(BaseModel):
    """Standard error response model.

    Used for all error responses across the API.

    Attributes:
        success: Always False for error responses.
        error: Error type/code.
        message: Human-readable error message.
        detail: Additional error details (optional).
        suggestion: Suggested action to resolve the error.
    """

    success: bool = False
    error: str
    message: str
    detail: str | None = None
    suggestion: str | None = None


class APIInfo(BaseModel):
    """API information for documentation.

    Attributes:
        name: API name.
        version: API version.
        description: API description.
        docs_url: URL to API documentation (None if docs disabled).
    """

    name: str = "Claude Task Master API"
    version: str
    description: str = "REST API for Claude Task Master task orchestration"
    docs_url: str | None = "/docs"


# =============================================================================
# Shared Status Models (used in TaskStatusResponse and route helpers)
# =============================================================================


class TaskProgressInfo(BaseModel):
    """Task progress information.

    Attributes:
        completed: Number of completed tasks.
        total: Total number of tasks.
        progress: Human-readable progress string (e.g., "3/10").
    """

    completed: int
    total: int
    progress: str = Field(examples=["3/10", "0/5", "No tasks"])


class WebhookStatusInfo(BaseModel):
    """Webhook status summary information.

    Attributes:
        total: Total number of configured webhooks.
        enabled: Number of enabled webhooks.
        disabled: Number of disabled webhooks.
    """

    total: int = Field(description="Total number of configured webhooks")
    enabled: int = Field(description="Number of enabled webhooks")
    disabled: int = Field(description="Number of disabled webhooks")
