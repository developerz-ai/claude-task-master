"""Pydantic request/response models for the REST API.

This module defines all request and response models used by the FastAPI
REST API endpoints. Models are organized by operation type:

Request Models:
- PauseRequest: Pause a running task
- StopRequest: Stop a task with optional cleanup
- ResumeRequest: Resume a paused/blocked task
- ConfigUpdateRequest: Update task configuration
- TaskInitRequest: Initialize a new task
- CloneRepoRequest: Clone a git repository to the workspace
- SetupRepoRequest: Set up a cloned repository for development
- PlanRepoRequest: Create a plan for a repository (read-only)

Response Models:
- TaskStatusResponse: Full task status information
- ControlResponse: Generic control operation response
- PlanResponse: Task plan content
- LogsResponse: Log content
- ProgressResponse: Progress summary
- ContextResponse: Accumulated context/learnings
- HealthResponse: Server health status
- ErrorResponse: Standard error response
- CloneRepoResponse: Result of cloning a repository
- SetupRepoResponse: Result of setting up a repository
- PlanRepoResponse: Result of planning for a repository

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
# Repo Setup Request Models
# =============================================================================


class CloneRepoRequest(BaseModel):
    """Request model for cloning a git repository.

    Clones a repository to the workspace for AI developer environments.
    Default target is ~/workspace/claude-task-master/{repo-name}.

    Attributes:
        url: Git repository URL (HTTPS or SSH format).
        target_dir: Optional custom target directory path.
            If not provided, defaults to ~/workspace/claude-task-master/{repo-name}.
        branch: Optional branch to checkout after cloning.
    """

    url: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Git repository URL (HTTPS or SSH format)",
        examples=[
            "https://github.com/user/repo.git",
            "git@github.com:user/repo.git",
        ],
    )
    target_dir: str | None = Field(
        default=None,
        max_length=4096,
        description="Optional custom target directory path. "
        "Defaults to ~/workspace/claude-task-master/{repo-name}",
        examples=[
            "~/workspace/claude-task-master/my-project",
            "/home/user/projects/my-app",
        ],
    )
    branch: str | None = Field(
        default=None,
        max_length=256,
        description="Optional branch to checkout after cloning",
        examples=["main", "develop", "feature/new-feature"],
    )


class SetupRepoRequest(BaseModel):
    """Request model for setting up a cloned repository for development.

    Detects the project type and performs appropriate setup:
    - Creates virtual environment (for Python projects)
    - Installs dependencies (pip, npm, pnpm, yarn, bun)
    - Runs setup scripts (setup-hooks.sh, setup.sh, etc.)

    Attributes:
        work_dir: Path to the cloned repository directory.
    """

    work_dir: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Path to the cloned repository directory to set up",
        examples=[
            "~/workspace/claude-task-master/my-project",
            "/home/user/projects/my-app",
        ],
    )


class PlanRepoRequest(BaseModel):
    """Request model for creating a plan for a repository.

    Creates a plan without executing any work. Uses read-only tools
    (Read, Glob, Grep) to analyze the codebase and outputs a structured
    plan with tasks and success criteria.

    Use this after cloning and setting up a repo to plan work before
    execution, or to get a plan for a new goal in an existing repository.

    Attributes:
        work_dir: Path to the repository directory to plan for.
        goal: The goal/task description to plan for.
        model: Model to use for planning (default: opus for best quality).
    """

    work_dir: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Path to the repository directory to plan for",
        examples=[
            "~/workspace/claude-task-master/my-project",
            "/home/user/projects/my-app",
        ],
    )
    goal: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The goal/task description to plan for",
        examples=[
            "Implement user authentication with JWT",
            "Add dark mode support to the UI",
            "Fix the database connection pooling issue",
        ],
    )
    model: str = Field(
        default="opus",
        pattern="^(opus|sonnet|haiku)$",
        description="Model to use for planning (opus, sonnet, haiku)",
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


# =============================================================================
# Mailbox Request/Response Models
# =============================================================================


class SendMailboxMessageRequest(BaseModel):
    """Request model for sending a message to the mailbox.

    Attributes:
        content: The message content describing the change request.
        sender: Identifier of the sender (default: "anonymous").
        priority: Message priority (0=low, 1=normal, 2=high, 3=urgent).
        metadata: Optional additional metadata.
    """

    content: str = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="The message content describing the change request",
        examples=["Please also add tests for the new feature", "Prioritize the bug fix"],
    )
    sender: str = Field(
        default="anonymous",
        max_length=256,
        description="Identifier of the sender",
        examples=["supervisor-agent", "user@example.com", "monitoring-system"],
    )
    priority: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Message priority (0=low, 1=normal, 2=high, 3=urgent)",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional additional metadata",
    )


class SendMailboxMessageResponse(BaseModel):
    """Response model for sending a message to the mailbox.

    Attributes:
        success: Whether the message was sent successfully.
        message_id: The ID of the created message.
        message: Human-readable result message.
        error: Error message if request failed.
    """

    success: bool
    message_id: str | None = None
    message: str | None = None
    error: str | None = None


class MailboxMessagePreview(BaseModel):
    """Preview of a mailbox message for status responses.

    Attributes:
        id: Message ID.
        sender: Message sender.
        content_preview: Truncated message content.
        priority: Message priority level.
        timestamp: When the message was created.
    """

    id: str
    sender: str
    content_preview: str
    priority: int
    timestamp: datetime


class MailboxStatusResponse(BaseModel):
    """Response model for mailbox status check.

    Attributes:
        success: Whether the request succeeded.
        count: Number of pending messages.
        messages: List of message previews.
        last_checked: When the mailbox was last checked.
        total_messages_received: Total count of messages ever received.
        error: Error message if request failed.
    """

    success: bool
    count: int = 0
    messages: list[MailboxMessagePreview] = []
    last_checked: datetime | None = None
    total_messages_received: int = 0
    error: str | None = None


class ClearMailboxResponse(BaseModel):
    """Response model for clearing the mailbox.

    Attributes:
        success: Whether the operation succeeded.
        messages_cleared: Number of messages that were cleared.
        message: Human-readable result message.
        error: Error message if operation failed.
    """

    success: bool
    messages_cleared: int = 0
    message: str | None = None
    error: str | None = None


# =============================================================================
# Repo Setup Response Models
# =============================================================================


class CloneRepoResponse(BaseModel):
    """Response model for cloning a git repository.

    Attributes:
        success: Whether the clone operation succeeded.
        message: Human-readable result message.
        repo_url: The repository URL that was cloned.
        target_dir: The directory where the repo was cloned to.
        branch: The branch that was checked out (if specified).
        error: Error message if clone failed.
    """

    success: bool
    message: str
    repo_url: str | None = None
    target_dir: str | None = None
    branch: str | None = None
    error: str | None = None


class SetupRepoResponse(BaseModel):
    """Response model for setting up a repository for development.

    Attributes:
        success: Whether the setup operation succeeded.
        message: Human-readable result message.
        work_dir: The directory that was set up.
        steps_completed: List of setup steps that were completed.
        venv_path: Path to the virtual environment (if created).
        dependencies_installed: Whether dependencies were successfully installed.
        setup_scripts_run: List of setup scripts that were executed.
        error: Error message if setup failed.
    """

    success: bool
    message: str
    work_dir: str | None = None
    steps_completed: list[str] = []
    venv_path: str | None = None
    dependencies_installed: bool = False
    setup_scripts_run: list[str] = []
    error: str | None = None


class PlanRepoResponse(BaseModel):
    """Response model for creating a plan for a repository.

    Attributes:
        success: Whether the planning operation succeeded.
        message: Human-readable result message.
        work_dir: The repository directory that was analyzed.
        goal: The goal that was planned for.
        plan: The generated plan (markdown with task checkboxes).
        criteria: The success criteria for the plan.
        run_id: The run ID for the created task state.
        error: Error message if planning failed.
    """

    success: bool
    message: str
    work_dir: str | None = None
    goal: str | None = None
    plan: str | None = None
    criteria: str | None = None
    run_id: str | None = None
    error: str | None = None
