"""Task-related request and response models for the REST API.

Covers the full task lifecycle: requests to pause/stop/resume/init/configure,
and the corresponding response models for status, plan, logs, progress, context,
health, and task management operations.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from claude_task_master.api.models_common import (
    LogFormat,
    LogLevel,
    TaskProgressInfo,
    TaskStatus,
    WebhookStatusInfo,
    WorkflowStage,
    _validate_model_field,
)

__all__ = [
    # Request models
    "PauseRequest",
    "StopRequest",
    "ResumeRequest",
    "ConfigUpdateRequest",
    "TaskInitRequest",
    # Nested component models
    "TaskOptionsResponse",
    "TaskProgressInfo",
    "WebhookStatusInfo",
    # Main response models
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
]


# =============================================================================
# Request Models
# =============================================================================


class PauseRequest(BaseModel):
    """Request model for pausing a task.

    Attributes:
        reason: Optional reason for pausing the task.
            This will be recorded in the progress file.
    """

    reason: str | None = Field(
        default=None,
        description="Optional reason for pausing the task",
        examples=["Manual pause for code review", "Waiting for dependency update"],
    )


class StopRequest(BaseModel):
    """Request model for stopping a task.

    Attributes:
        reason: Optional reason for stopping the task.
        cleanup: If True, cleanup state files after stopping.
    """

    reason: str | None = Field(
        default=None,
        description="Optional reason for stopping the task",
        examples=["Task cancelled by user", "Obsolete task - requirements changed"],
    )
    cleanup: bool = Field(
        default=False,
        description="If True, cleanup state files after stopping",
    )


class ResumeRequest(BaseModel):
    """Request model for resuming a paused or blocked task.

    Attributes:
        reason: Optional reason for resuming the task.
    """

    reason: str | None = Field(
        default=None,
        description="Optional reason for resuming the task",
    )


class ConfigUpdateRequest(BaseModel):
    """Request model for updating task configuration.

    Only specified fields are updated; others retain their current values.
    At least one field must be provided.

    Attributes:
        auto_merge: Whether to auto-merge PRs when approved.
        max_sessions: Maximum number of work sessions before pausing.
        max_prs: Maximum number of pull requests to create.
        pause_on_pr: Whether to pause after creating PR for manual review.
        enable_checkpointing: Whether to enable state checkpointing.
        log_level: Log level (quiet, normal, verbose).
        log_format: Log format (text, json).
        pr_per_task: Whether to create PR per task vs per group.
    """

    auto_merge: bool | None = Field(
        default=None,
        description="Whether to auto-merge PRs when approved",
    )
    enable_release: bool | None = Field(
        default=None,
        description="Whether to run post-merge release verification",
    )
    enable_verification: bool | None = Field(
        default=None,
        description="Whether to run final success-criteria verification + fix loop after all tasks complete",
    )
    max_sessions: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Maximum number of work sessions before pausing",
    )
    max_prs: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Maximum number of pull requests to create",
    )
    pause_on_pr: bool | None = Field(
        default=None,
        description="Whether to pause after creating PR for manual review",
    )
    enable_checkpointing: bool | None = Field(
        default=None,
        description="Whether to enable state checkpointing",
    )
    log_level: LogLevel | None = Field(
        default=None,
        description="Log level (quiet, normal, verbose)",
    )
    log_format: LogFormat | None = Field(
        default=None,
        description="Log format (text, json)",
    )
    pr_per_task: bool | None = Field(
        default=None,
        description="Whether to create PR per task vs per group",
    )

    def has_updates(self) -> bool:
        """Check if any configuration updates were provided."""
        return any(getattr(self, field) is not None for field in self.model_fields.keys())

    def to_update_dict(self) -> dict[str, bool | int | str]:
        """Convert to dictionary of non-None updates.

        Returns:
            Dictionary containing only the fields with non-None values,
            with enum values converted to strings.
        """
        updates: dict[str, bool | int | str] = {}
        for field_name in self.model_fields.keys():
            value = getattr(self, field_name)
            if value is not None:
                # Convert enums to their string values
                if isinstance(value, Enum):
                    updates[field_name] = value.value
                else:
                    updates[field_name] = value
        return updates


class TaskInitRequest(BaseModel):
    """Request model for initializing a new task.

    Attributes:
        goal: The goal to achieve.
        model: Model to use (opus, sonnet, haiku).
        auto_merge: Whether to auto-merge PRs when approved.
        max_sessions: Max work sessions before pausing.
        max_prs: Max pull requests to create.
        pause_on_pr: Pause after creating PR for manual review.
    """

    goal: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The goal to achieve",
        examples=["Fix the login form validation bug", "Add dark mode support"],
    )
    model: str = Field(
        default="opus",
        description="Model to use (opus, sonnet, fable, haiku, sonnet_1m)",
    )

    @field_validator("model")
    @classmethod
    def _check_model(cls, value: str) -> str:
        """Reject models outside the shared model registry."""
        return _validate_model_field(value)

    auto_merge: bool = Field(
        default=True,
        description="Whether to auto-merge PRs when approved",
    )
    enable_release: bool = Field(
        default=False,
        description="Whether to run post-merge release verification",
    )
    enable_verification: bool = Field(
        default=False,
        description="Whether to run final success-criteria verification + fix loop after all tasks complete",
    )
    max_sessions: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Maximum number of work sessions before pausing",
    )
    max_prs: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Maximum number of pull requests to create",
    )
    pause_on_pr: bool = Field(
        default=False,
        description="Pause after creating PR for manual review",
    )


# =============================================================================
# Response Models - Nested Components
# =============================================================================


class TaskOptionsResponse(BaseModel):
    """Task options in response models.

    Attributes:
        auto_merge: Whether to auto-merge PRs when approved.
        max_sessions: Maximum number of work sessions before pausing.
        max_prs: Maximum number of pull requests to create.
        pause_on_pr: Whether to pause after creating PR for manual review.
        enable_checkpointing: Whether state checkpointing is enabled.
        log_level: Current log level.
        log_format: Current log format.
        pr_per_task: Whether to create PR per task vs per group.
    """

    auto_merge: bool
    enable_release: bool = False
    enable_verification: bool = False
    max_sessions: int | None
    max_prs: int | None
    pause_on_pr: bool
    enable_checkpointing: bool
    log_level: str
    log_format: str
    pr_per_task: bool
    max_budget_usd: float | None = None


# =============================================================================
# Response Models - Main Responses
# =============================================================================


class TaskStatusResponse(BaseModel):
    """Response model for task status.

    Provides comprehensive information about the current task state.

    Attributes:
        success: Whether the request succeeded.
        goal: The task goal.
        status: Current task status.
        model: Model being used.
        current_task_index: Index of the current task.
        session_count: Number of work sessions completed.
        run_id: Unique run identifier.
        current_pr: Current PR number (if any).
        workflow_stage: Current workflow stage (if any).
        options: Current task options.
        created_at: When the task was created.
        updated_at: When the task was last updated.
        tasks: Task progress information.
        webhooks: Webhook configuration status summary.
    """

    success: bool = True
    goal: str
    status: TaskStatus
    model: str
    current_task_index: int
    session_count: int
    run_id: str
    current_pr: int | None = None
    workflow_stage: WorkflowStage | None = None
    options: TaskOptionsResponse
    created_at: datetime | str
    updated_at: datetime | str
    tasks: TaskProgressInfo | None = None
    webhooks: WebhookStatusInfo | None = None


class ControlResponse(BaseModel):
    """Generic response model for control operations (pause, stop, resume).

    Attributes:
        success: Whether the operation succeeded.
        message: Human-readable description of the result.
        operation: The operation that was performed.
        previous_status: The status before the operation.
        new_status: The status after the operation.
        details: Additional operation-specific details.
    """

    success: bool
    message: str
    operation: str = Field(
        examples=["pause", "stop", "resume", "update_config"],
    )
    previous_status: str | None = None
    new_status: str | None = None
    details: dict[str, Any] | None = None


class PlanResponse(BaseModel):
    """Response model for task plan.

    Attributes:
        success: Whether the request succeeded.
        plan: The plan content (markdown with checkboxes).
        error: Error message if request failed.
    """

    success: bool
    plan: str | None = None
    error: str | None = None


class LogsResponse(BaseModel):
    """Response model for log content.

    Attributes:
        success: Whether the request succeeded.
        log_content: The log content (last N lines).
        log_file: Path to the log file.
        error: Error message if request failed.
    """

    success: bool
    log_content: str | None = None
    log_file: str | None = None
    error: str | None = None


class ProgressResponse(BaseModel):
    """Response model for progress summary.

    Attributes:
        success: Whether the request succeeded.
        progress: The progress content (markdown).
        message: Additional message (e.g., "No progress recorded").
        error: Error message if request failed.
    """

    success: bool
    progress: str | None = None
    message: str | None = None
    error: str | None = None


class ContextResponse(BaseModel):
    """Response model for context/learnings.

    Attributes:
        success: Whether the request succeeded.
        context: The context content.
        error: Error message if request failed.
    """

    success: bool
    context: str | None = None
    error: str | None = None


class TaskListItem(BaseModel):
    """Individual task item in task list.

    Attributes:
        task: Task description.
        completed: Whether the task is completed.
    """

    task: str
    completed: bool


class TaskListResponse(BaseModel):
    """Response model for task list.

    Attributes:
        success: Whether the request succeeded.
        tasks: List of tasks with completion status.
        total: Total number of tasks.
        completed: Number of completed tasks.
        current_index: Index of the current task.
        error: Error message if request failed.
    """

    success: bool
    tasks: list[TaskListItem] | None = None
    total: int = 0
    completed: int = 0
    current_index: int = 0
    error: str | None = None


class HealthResponse(BaseModel):
    """Response model for health check.

    Attributes:
        status: Health status ("healthy", "degraded", "unhealthy").
        version: Server version string.
        server_name: Name of the server.
        uptime_seconds: Server uptime in seconds (if available).
        active_tasks: Number of active tasks.
        timestamp: Current server timestamp.
    """

    status: str = Field(examples=["healthy", "degraded", "unhealthy"])
    version: str
    server_name: str = "claude-task-master-api"
    uptime_seconds: float | None = None
    active_tasks: int = 0
    timestamp: datetime = Field(default_factory=datetime.now)


class TaskInitResponse(BaseModel):
    """Response model for task initialization.

    Attributes:
        success: Whether initialization succeeded.
        message: Human-readable result message.
        run_id: The run ID of the new task.
        status: Initial task status.
        error: Error message if initialization failed.
    """

    success: bool
    message: str
    run_id: str | None = None
    status: str | None = None
    error: str | None = None


class TaskDeleteResponse(BaseModel):
    """Response model for task deletion/cleanup.

    Attributes:
        success: Whether cleanup succeeded.
        message: Human-readable result message.
        files_removed: Whether files were actually removed.
        error: Error message if cleanup failed.
    """

    success: bool
    message: str
    files_removed: bool = False
    error: str | None = None
