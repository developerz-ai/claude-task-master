"""Pydantic request/response models for the REST API.

This module defines all request and response models used by the FastAPI
REST API endpoints. Models are organized by operation type:

Request Models:
- PauseRequest: Pause a running task
- StopRequest: Stop a task with optional cleanup
- ResumeRequest: Resume a paused/blocked task
- ConfigUpdateRequest: Update task configuration
- TaskInitRequest: Initialize a new task

Response Models:
- TaskStatusResponse: Full task status information
- ControlResponse: Generic control operation response
- PlanResponse: Task plan content
- LogsResponse: Log content
- ProgressResponse: Progress summary
- ContextResponse: Accumulated context/learnings
- HealthResponse: Server health status
- ErrorResponse: Standard error response

Usage:
    from claude_task_master.api.models import (
        PauseRequest,
        TaskStatusResponse,
        ErrorResponse,
    )

    @app.post("/control/pause", response_model=ControlResponse)
    async def pause_task(request: PauseRequest):
        ...
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# Enums
# =============================================================================


class TaskStatus(str, Enum):
    """Valid task status values."""

    PLANNING = "planning"
    WORKING = "working"
    BLOCKED = "blocked"
    PAUSED = "paused"
    STOPPED = "stopped"
    SUCCESS = "success"
    FAILED = "failed"


class WorkflowStage(str, Enum):
    """Valid workflow stage values for PR lifecycle."""

    WORKING = "working"
    PR_CREATED = "pr_created"
    WAITING_CI = "waiting_ci"
    CI_FAILED = "ci_failed"
    WAITING_REVIEWS = "waiting_reviews"
    ADDRESSING_REVIEWS = "addressing_reviews"
    READY_TO_MERGE = "ready_to_merge"
    MERGED = "merged"


class LogLevel(str, Enum):
    """Valid log level values."""

    QUIET = "quiet"
    NORMAL = "normal"
    VERBOSE = "verbose"


class LogFormat(str, Enum):
    """Valid log format values."""

    TEXT = "text"
    JSON = "json"


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

    Currently has no required fields, but exists for API consistency
    and future extensibility.
    """

    pass


class ConfigUpdateRequest(BaseModel):
    """Request model for updating task configuration.

    Only specified fields are updated; others retain their current values.
    At least one field must be provided.

    Attributes:
        auto_merge: Whether to auto-merge PRs when approved.
        max_sessions: Maximum number of work sessions before pausing.
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
    max_sessions: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Maximum number of work sessions before pausing",
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
        pattern="^(opus|sonnet|haiku)$",
        description="Model to use (opus, sonnet, haiku)",
    )
    auto_merge: bool = Field(
        default=True,
        description="Whether to auto-merge PRs when approved",
    )
    max_sessions: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Maximum number of work sessions before pausing",
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
        pause_on_pr: Whether to pause after creating PR for manual review.
        enable_checkpointing: Whether state checkpointing is enabled.
        log_level: Current log level.
        log_format: Current log format.
        pr_per_task: Whether to create PR per task vs per group.
    """

    auto_merge: bool
    max_sessions: int | None
    pause_on_pr: bool
    enable_checkpointing: bool
    log_level: str
    log_format: str
    pr_per_task: bool


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


# =============================================================================
# API Metadata Models
# =============================================================================


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
