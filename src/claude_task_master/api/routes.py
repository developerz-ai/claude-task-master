"""REST API routes for Claude Task Master.

This module defines API endpoint routes that can be registered with a FastAPI app.
Each route function takes the necessary dependencies and returns the configured router.

Endpoints:
- GET /status: Get current task status
- GET /plan: Get task plan content
- GET /logs: Get log content
- GET /progress: Get progress summary
- GET /context: Get accumulated context/learnings
- GET /health: Health check endpoint
- POST /task/init: Initialize a new task
- DELETE /task: Delete/cleanup current task
- POST /control/stop: Stop a running task with optional cleanup
- POST /control/resume: Resume a paused or blocked task
- PATCH /config: Update runtime configuration options
- POST /repo/clone: Clone a git repository to workspace
- POST /repo/setup: Set up a cloned repository for development
- POST /repo/plan: Create a plan for a repository (read-only)

Usage:
    from claude_task_master.api.routes import (
        create_info_router,
        create_control_router,
        create_task_router,
    )

    router = create_info_router()
    app.include_router(router)

    control_router = create_control_router()
    app.include_router(control_router)

    task_router = create_task_router()
    app.include_router(task_router)
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_task_master import __version__
from claude_task_master.api.models import (
    ClearMailboxResponse,
    ConfigUpdateRequest,
    ContextResponse,
    ControlResponse,
    ErrorResponse,
    HealthResponse,
    LogsResponse,
    MailboxMessagePreview,
    MailboxStatusResponse,
    PlanResponse,
    ProgressResponse,
    ResumeRequest,
    SendMailboxMessageRequest,
    SendMailboxMessageResponse,
    StopRequest,
    TaskDeleteResponse,
    TaskInitRequest,
    TaskInitResponse,
    TaskOptionsResponse,
    TaskProgressInfo,
    TaskStatus,
    TaskStatusResponse,
    WebhookStatusInfo,
    WorkflowStage,
)
from claude_task_master.api.routes_repo import create_repo_router
from claude_task_master.api.routes_webhooks import create_webhooks_router
from claude_task_master.core.agent import ModelType
from claude_task_master.core.control import ControlManager
from claude_task_master.core.credentials import CredentialManager
from claude_task_master.core.state import StateManager, TaskOptions

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI, Query, Request
    from fastapi.responses import JSONResponse

# Import FastAPI - using try/except for graceful degradation
try:
    from fastapi import APIRouter, Query, Request
    from fastapi.responses import JSONResponse

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def _parse_plan_tasks(plan: str) -> list[tuple[str, bool]]:
    """Parse task checkboxes from plan markdown.

    Args:
        plan: The plan content in markdown format.

    Returns:
        List of (task_description, is_completed) tuples.
    """
    tasks: list[tuple[str, bool]] = []
    for line in plan.splitlines():
        line = line.strip()
        if line.startswith("- [ ] "):
            tasks.append((line[6:], False))
        elif line.startswith("- [x] ") or line.startswith("- [X] "):
            tasks.append((line[6:], True))
    return tasks


def _get_state_manager(request: Request) -> StateManager:
    """Get state manager from request, using working directory from app state.

    Args:
        request: The FastAPI request object.

    Returns:
        StateManager instance configured for the app's working directory.
    """
    working_dir: Path = getattr(request.app.state, "working_dir", Path.cwd())
    state_dir = working_dir / ".claude-task-master"
    return StateManager(state_dir=state_dir)


def _get_webhook_status(request: Request) -> WebhookStatusInfo | None:
    """Get webhook configuration status summary.

    Args:
        request: The FastAPI request object.

    Returns:
        WebhookStatusInfo with counts of total/enabled/disabled webhooks,
        or None if webhooks file doesn't exist or can't be loaded.
    """
    working_dir: Path = getattr(request.app.state, "working_dir", Path.cwd())
    webhooks_file = working_dir / ".claude-task-master" / "webhooks.json"

    if not webhooks_file.exists():
        return None

    try:
        with open(webhooks_file) as f:
            data = json.load(f)
            webhooks: dict[str, dict[str, Any]] = data.get("webhooks", {})

        total = len(webhooks)
        enabled = sum(1 for wh in webhooks.values() if wh.get("enabled", True))
        disabled = total - enabled

        return WebhookStatusInfo(
            total=total,
            enabled=enabled,
            disabled=disabled,
        )
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load webhook status: {e}")
        return None


# =============================================================================
# Info Router (Status, Plan, Logs, Progress, Context, Health)
# =============================================================================


def create_info_router() -> APIRouter:
    """Create router for info endpoints.

    These are read-only endpoints that provide information about the
    current task state without modifying anything.

    Returns:
        APIRouter configured with info endpoints.

    Raises:
        ImportError: If FastAPI is not installed.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI not installed. Install with: pip install claude-task-master[api]"
        )

    router = APIRouter(tags=["Info"])

    @router.get(
        "/status",
        response_model=TaskStatusResponse,
        responses={
            404: {"model": ErrorResponse, "description": "No active task found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Get Task Status",
        description="Get comprehensive status information about the current task.",
    )
    async def get_status(request: Request) -> TaskStatusResponse | JSONResponse:
        """Get current task status.

        Returns comprehensive information about the current task including:
        - Goal and current status
        - Model being used
        - Session count and current task index
        - PR information (if applicable)
        - Task options/configuration
        - Task progress (completed/total)
        - Webhook configuration status (total/enabled/disabled counts)

        Returns:
            TaskStatusResponse with full task status information.

        Raises:
            404: If no active task exists.
            500: If an error occurs loading state.
        """
        state_manager = _get_state_manager(request)

        if not state_manager.exists():
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )

        try:
            state = state_manager.load_state()
            goal = state_manager.load_goal()

            # Calculate task progress from plan
            tasks_info: TaskProgressInfo | None = None
            plan = state_manager.load_plan()
            if plan:
                tasks = _parse_plan_tasks(plan)
                completed = sum(1 for _, done in tasks if done)
                total = len(tasks)
                tasks_info = TaskProgressInfo(
                    completed=completed,
                    total=total,
                    progress=f"{completed}/{total}" if total > 0 else "No tasks",
                )

            # Convert status and workflow_stage to enums with defensive error handling
            try:
                status_enum = TaskStatus(state.status)
            except ValueError as e:
                logger.error(f"Invalid status value '{state.status}' in persisted state")
                raise ValueError(f"Corrupted state: invalid status '{state.status}'") from e

            workflow_stage_enum = None
            if state.workflow_stage:
                try:
                    workflow_stage_enum = WorkflowStage(state.workflow_stage)
                except ValueError as e:
                    logger.error(
                        f"Invalid workflow_stage value '{state.workflow_stage}' in persisted state"
                    )
                    raise ValueError(
                        f"Corrupted state: invalid workflow_stage '{state.workflow_stage}'"
                    ) from e

            # Load webhook status
            webhooks_info = _get_webhook_status(request)

            return TaskStatusResponse(
                success=True,
                goal=goal,
                status=status_enum,
                model=state.model,
                current_task_index=state.current_task_index,
                session_count=state.session_count,
                run_id=state.run_id,
                current_pr=state.current_pr,
                workflow_stage=workflow_stage_enum,
                options=TaskOptionsResponse(
                    auto_merge=state.options.auto_merge,
                    max_sessions=state.options.max_sessions,
                    pause_on_pr=state.options.pause_on_pr,
                    enable_checkpointing=state.options.enable_checkpointing,
                    log_level=state.options.log_level,
                    log_format=state.options.log_format,
                    pr_per_task=state.options.pr_per_task,
                ),
                created_at=state.created_at,
                updated_at=state.updated_at,
                tasks=tasks_info,
                webhooks=webhooks_info,
            )

        except Exception as e:
            logger.exception("Error loading task status")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to load task status",
                    detail=str(e),
                ).model_dump(),
            )

    @router.get(
        "/plan",
        response_model=PlanResponse,
        responses={
            404: {"model": ErrorResponse, "description": "No active task or plan found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Get Task Plan",
        description="Get the current task plan with markdown checkboxes.",
    )
    async def get_plan(request: Request) -> PlanResponse | JSONResponse:
        """Get task plan content.

        Returns the plan markdown content with task checkboxes
        indicating completion status.

        Returns:
            PlanResponse with plan content.

        Raises:
            404: If no active task or plan exists.
            500: If an error occurs loading the plan.
        """
        state_manager = _get_state_manager(request)

        if not state_manager.exists():
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )

        try:
            plan = state_manager.load_plan()

            if not plan:
                return JSONResponse(
                    status_code=404,
                    content=ErrorResponse(
                        error="not_found",
                        message="No plan found",
                        suggestion="Task may still be in planning phase",
                    ).model_dump(),
                )

            return PlanResponse(success=True, plan=plan)

        except Exception as e:
            logger.exception("Error loading task plan")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to load task plan",
                    detail=str(e),
                ).model_dump(),
            )

    @router.get(
        "/logs",
        response_model=LogsResponse,
        responses={
            404: {"model": ErrorResponse, "description": "No active task or logs found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Get Logs",
        description="Get log content from the current run.",
    )
    async def get_logs(
        request: Request,
        tail: int = Query(
            default=100,
            ge=1,
            le=10000,
            description="Number of lines to return from the end of the log",
        ),
    ) -> LogsResponse | JSONResponse:
        """Get log content.

        Returns the last N lines from the current run's log file.

        Args:
            tail: Number of lines to return (default: 100, max: 10000).

        Returns:
            LogsResponse with log content and file path.

        Raises:
            404: If no active task or log file exists.
            500: If an error occurs reading logs.
        """
        state_manager = _get_state_manager(request)

        if not state_manager.exists():
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )

        try:
            state = state_manager.load_state()
            log_file = state_manager.get_log_file(state.run_id)

            if not log_file.exists():
                return JSONResponse(
                    status_code=404,
                    content=ErrorResponse(
                        error="not_found",
                        message="No log file found",
                        suggestion="Task may not have started execution yet",
                    ).model_dump(),
                )

            with open(log_file) as f:
                lines = f.readlines()

            # Return last N lines
            log_content = "".join(lines[-tail:])

            return LogsResponse(
                success=True,
                log_content=log_content,
                log_file=str(log_file),
            )

        except Exception as e:
            logger.exception("Error loading logs")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to load logs",
                    detail=str(e),
                ).model_dump(),
            )

    @router.get(
        "/progress",
        response_model=ProgressResponse,
        responses={
            404: {"model": ErrorResponse, "description": "No active task found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Get Progress",
        description="Get human-readable progress summary.",
    )
    async def get_progress(request: Request) -> ProgressResponse | JSONResponse:
        """Get progress summary.

        Returns the human-readable progress summary showing what has been
        accomplished and what remains.

        Returns:
            ProgressResponse with progress content.

        Raises:
            404: If no active task exists.
            500: If an error occurs loading progress.
        """
        state_manager = _get_state_manager(request)

        if not state_manager.exists():
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )

        try:
            progress = state_manager.load_progress()

            if not progress:
                return ProgressResponse(
                    success=True,
                    progress=None,
                    message="No progress recorded yet",
                )

            return ProgressResponse(success=True, progress=progress)

        except Exception as e:
            logger.exception("Error loading progress")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to load progress",
                    detail=str(e),
                ).model_dump(),
            )

    @router.get(
        "/context",
        response_model=ContextResponse,
        responses={
            404: {"model": ErrorResponse, "description": "No active task found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Get Context",
        description="Get accumulated context and learnings.",
    )
    async def get_context(request: Request) -> ContextResponse | JSONResponse:
        """Get accumulated context.

        Returns the accumulated context and learnings that inform
        future sessions.

        Returns:
            ContextResponse with context content.

        Raises:
            404: If no active task exists.
            500: If an error occurs loading context.
        """
        state_manager = _get_state_manager(request)

        if not state_manager.exists():
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )

        try:
            context = state_manager.load_context()

            if not context:
                return ContextResponse(
                    success=True,
                    context=None,
                )

            return ContextResponse(success=True, context=context)

        except Exception as e:
            logger.exception("Error loading context")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to load context",
                    detail=str(e),
                ).model_dump(),
            )

    @router.get(
        "/health",
        response_model=HealthResponse,
        summary="Health Check",
        description="Health check endpoint for monitoring and load balancers.",
    )
    async def get_health(request: Request) -> HealthResponse:
        """Health check endpoint.

        Returns server health information including:
        - Server status (healthy, degraded, unhealthy)
        - Version information
        - Uptime in seconds
        - Number of active tasks

        This endpoint is suitable for load balancer health checks
        and monitoring systems.

        Returns:
            HealthResponse with health status.
        """
        uptime: float | None = None
        if hasattr(request.app.state, "start_time"):
            uptime = time.time() - request.app.state.start_time

        active_tasks: int = getattr(request.app.state, "active_tasks", 0)

        # Check if state directory exists to determine if a task is active
        state_manager = _get_state_manager(request)
        status = "healthy"
        if state_manager.exists():
            try:
                state = state_manager.load_state()
                if state.status in ("blocked", "failed"):
                    status = "degraded"
            except Exception:
                # Can't load state - might be degraded
                status = "degraded"

        return HealthResponse(
            status=status,
            version=__version__,
            server_name="claude-task-master-api",
            uptime_seconds=uptime,
            active_tasks=active_tasks,
        )

    return router


# =============================================================================
# Control Router (Stop)
# =============================================================================


def create_control_router() -> APIRouter:
    """Create router for control endpoints.

    These endpoints allow runtime control of task execution including
    stopping and resuming tasks.

    Returns:
        APIRouter configured with control endpoints.

    Raises:
        ImportError: If FastAPI is not installed.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI not installed. Install with: pip install claude-task-master[api]"
        )

    router = APIRouter(tags=["Control"])

    @router.post(
        "/control/stop",
        response_model=ControlResponse,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid operation for current state"},
            404: {"model": ErrorResponse, "description": "No active task found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Stop Task",
        description="Stop a running task with optional cleanup of state files.",
    )
    async def stop_task(
        request: Request, stop_request: StopRequest
    ) -> ControlResponse | JSONResponse:
        """Stop a running task.

        Stops the current task and optionally cleans up state files.
        The task must be in a stoppable state (planning, working, blocked, or paused).

        Args:
            stop_request: Stop request with optional reason and cleanup flag.

        Returns:
            ControlResponse with operation result.

        Raises:
            404: If no active task exists.
            400: If the task cannot be stopped in its current state.
            500: If an error occurs during the operation.
        """
        state_manager = _get_state_manager(request)

        if not state_manager.exists():
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )

        try:
            # Create control manager and perform stop operation
            control = ControlManager(state_manager=state_manager)
            result = control.stop(reason=stop_request.reason, cleanup=stop_request.cleanup)

            return ControlResponse(
                success=result.success,
                message=result.message,
                operation=result.operation,
                previous_status=result.previous_status,
                new_status=result.new_status,
                details=result.details,
            )

        except Exception as e:
            logger.exception("Error stopping task")

            # Check if it's a known control error
            if "Cannot stop task" in str(e):
                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="invalid_operation",
                        message=str(e),
                        suggestion="Task may be in a terminal state or already stopped",
                    ).model_dump(),
                )

            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to stop task",
                    detail=str(e),
                ).model_dump(),
            )

    @router.post(
        "/control/resume",
        response_model=ControlResponse,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid operation for current state"},
            404: {"model": ErrorResponse, "description": "No active task found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Resume Task",
        description="Resume a paused or blocked task.",
    )
    async def resume_task(
        request: Request, resume_request: ResumeRequest
    ) -> ControlResponse | JSONResponse:
        """Resume a paused or blocked task.

        Resumes the current task from paused or blocked status.
        The task must be in a resumable state (paused, stopped, blocked, or working).

        Returns:
            ControlResponse with operation result.

        Raises:
            404: If no active task exists.
            400: If the task cannot be resumed in its current state.
            500: If an error occurs during the operation.
        """
        state_manager = _get_state_manager(request)

        if not state_manager.exists():
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )

        try:
            # Create control manager and perform resume operation
            control = ControlManager(state_manager=state_manager)
            result = control.resume()

            return ControlResponse(
                success=result.success,
                message=result.message,
                operation=result.operation,
                previous_status=result.previous_status,
                new_status=result.new_status,
                details=result.details,
            )

        except Exception as e:
            logger.exception("Error resuming task")

            # Check if it's a known control error
            if "Cannot resume task" in str(e):
                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="invalid_operation",
                        message=str(e),
                        suggestion="Task may be in a terminal state or already running",
                    ).model_dump(),
                )

            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to resume task",
                    detail=str(e),
                ).model_dump(),
            )

    @router.patch(
        "/config",
        response_model=ControlResponse,
        responses={
            400: {
                "model": ErrorResponse,
                "description": "Invalid configuration or no updates provided",
            },
            404: {"model": ErrorResponse, "description": "No active task found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Update Configuration",
        description="Update runtime task configuration options.",
    )
    async def update_config(
        request: Request, config_update: ConfigUpdateRequest
    ) -> ControlResponse | JSONResponse:
        """Update task configuration at runtime.

        Updates the specified configuration options for the current task.
        Only the fields specified in the request are updated; all other
        configuration options retain their current values.

        Supported options:
        - auto_merge: Whether to auto-merge PRs when approved
        - max_sessions: Maximum number of work sessions before pausing
        - pause_on_pr: Whether to pause after creating PR for manual review
        - enable_checkpointing: Whether to enable state checkpointing
        - log_level: Log level (quiet, normal, verbose)
        - log_format: Log format (text, json)
        - pr_per_task: Whether to create PR per task vs per group

        Args:
            config_update: Configuration update request with fields to update.

        Returns:
            ControlResponse with operation result including updated values.

        Raises:
            404: If no active task exists.
            400: If no configuration updates were provided or invalid values.
            500: If an error occurs during the operation.
        """
        state_manager = _get_state_manager(request)

        if not state_manager.exists():
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )

        # Validate that at least one field is being updated
        if not config_update.has_updates():
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="invalid_request",
                    message="No configuration updates provided",
                    suggestion="Specify at least one configuration field to update",
                ).model_dump(),
            )

        try:
            # Create control manager and perform config update
            control = ControlManager(state_manager=state_manager)

            # Convert config update to kwargs dictionary
            update_kwargs = config_update.to_update_dict()
            result = control.update_config(**update_kwargs)

            return ControlResponse(
                success=result.success,
                message=result.message,
                operation=result.operation,
                previous_status=result.previous_status,
                new_status=result.new_status,
                details=result.details,
            )

        except ValueError as e:
            logger.exception("Invalid configuration update")
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="invalid_configuration",
                    message="Invalid configuration option",
                    detail=str(e),
                ).model_dump(),
            )

        except Exception as e:
            logger.exception("Error updating configuration")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to update configuration",
                    detail=str(e),
                ).model_dump(),
            )

    return router


# =============================================================================
# Task Management Router (Init, Delete)
# =============================================================================


def create_task_router() -> APIRouter:
    """Create router for task management endpoints.

    These endpoints allow task lifecycle management including
    initializing new tasks and deleting existing tasks.

    Returns:
        APIRouter configured with task management endpoints.

    Raises:
        ImportError: If FastAPI is not installed.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI not installed. Install with: pip install claude-task-master[api]"
        )

    router = APIRouter(tags=["Task Management"])

    @router.post(
        "/task/init",
        response_model=TaskInitResponse,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request or task already exists"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Initialize Task",
        description="Initialize a new task with the given goal and options.",
    )
    async def init_task(
        request: Request, task_init: TaskInitRequest
    ) -> TaskInitResponse | JSONResponse:
        """Initialize a new task.

        Creates a new task with the specified goal and configuration options.
        The task will be in 'planning' status after initialization.

        Args:
            task_init: Task initialization request with goal and options.

        Returns:
            TaskInitResponse with initialization result including run_id.

        Raises:
            400: If a task already exists or request is invalid.
            500: If an error occurs during initialization.
        """
        state_manager = _get_state_manager(request)

        # Check if task already exists
        if state_manager.exists():
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="task_exists",
                    message="A task already exists",
                    suggestion="Use DELETE /task to remove the existing task first",
                ).model_dump(),
            )

        try:
            # Validate model type
            try:
                ModelType(task_init.model)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="invalid_model",
                        message=f"Invalid model '{task_init.model}'",
                        detail="Model must be one of: opus, sonnet, haiku",
                        suggestion="Use 'opus', 'sonnet', or 'haiku'",
                    ).model_dump(),
                )

            # Load credentials to verify we can authenticate
            try:
                cred_manager = CredentialManager()
                cred_manager.get_valid_token()
            except Exception as e:
                logger.exception("Failed to load credentials")
                return JSONResponse(
                    status_code=500,
                    content=ErrorResponse(
                        error="credentials_error",
                        message="Failed to load Claude credentials",
                        detail=str(e),
                        suggestion="Ensure you have authenticated with 'claude auth'",
                    ).model_dump(),
                )

            # Initialize task state
            logger.info(f"Initializing new task: {task_init.goal}")
            options = TaskOptions(
                auto_merge=task_init.auto_merge,
                max_sessions=task_init.max_sessions,
                pause_on_pr=task_init.pause_on_pr,
                enable_checkpointing=False,  # Default to False
                log_level="normal",  # Default to normal
                log_format="text",  # Default to text
                pr_per_task=False,  # Default to False
            )
            state = state_manager.initialize(
                goal=task_init.goal, model=task_init.model, options=options
            )

            logger.info(f"Task initialized with run_id: {state.run_id}")

            return TaskInitResponse(
                success=True,
                message="Task initialized successfully",
                run_id=state.run_id,
                status=state.status,
            )

        except Exception as e:
            logger.exception("Error initializing task")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to initialize task",
                    detail=str(e),
                ).model_dump(),
            )

    @router.delete(
        "/task",
        response_model=TaskDeleteResponse,
        responses={
            404: {"model": ErrorResponse, "description": "No active task found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Delete Task",
        description="Delete the current task and cleanup all state files.",
    )
    async def delete_task(request: Request) -> TaskDeleteResponse | JSONResponse:
        """Delete the current task.

        Removes all task state files including plan, progress, context,
        and state. This operation cannot be undone.

        Returns:
            TaskDeleteResponse with deletion result.

        Raises:
            404: If no active task exists.
            500: If an error occurs during deletion.
        """
        state_manager = _get_state_manager(request)

        if not state_manager.exists():
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="No task to delete",
                ).model_dump(),
            )

        try:
            # Check if session is active
            is_active = state_manager.is_session_active()

            if is_active:
                logger.warning("Deleting task while session is active")
                # Release session lock before deletion
                state_manager.release_session_lock()

            # Remove state directory
            state_dir = state_manager.state_dir
            if state_dir.exists():
                shutil.rmtree(state_dir)
                logger.info(f"Task state deleted: {state_dir}")
                files_removed = True
            else:
                logger.warning(f"State directory not found: {state_dir}")
                files_removed = False

            return TaskDeleteResponse(
                success=True,
                message="Task deleted successfully",
                files_removed=files_removed,
            )

        except Exception as e:
            logger.exception("Error deleting task")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to delete task",
                    detail=str(e),
                ).model_dump(),
            )

    return router


# =============================================================================
# Mailbox Router (Send, Status, Clear)
# =============================================================================


def create_mailbox_router() -> APIRouter:
    """Create router for mailbox endpoints.

    These endpoints allow external systems to send messages to the mailbox
    which will be processed after the current task completes.

    Returns:
        APIRouter configured with mailbox endpoints.

    Raises:
        ImportError: If FastAPI is not installed.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI not installed. Install with: pip install claude-task-master[api]"
        )

    router = APIRouter(tags=["Mailbox"])

    @router.post(
        "/send",
        response_model=SendMailboxMessageResponse,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Send Message to Mailbox",
        description="Send a message to the claudetm mailbox for processing after the current task.",
    )
    async def send_message(
        request: Request, message_request: SendMailboxMessageRequest
    ) -> SendMailboxMessageResponse | JSONResponse:
        """Send a message to the mailbox.

        Messages in the mailbox will be processed after the current task completes.
        Multiple messages are merged into a single change request that updates
        the plan before continuing work.

        Args:
            message_request: The message to send with content, sender, and priority.

        Returns:
            SendMailboxMessageResponse with message_id on success.

        Raises:
            400: If the request is invalid.
            500: If an error occurs sending the message.
        """
        from claude_task_master.mailbox import MailboxStorage

        working_dir: Path = getattr(request.app.state, "working_dir", Path.cwd())
        state_dir = working_dir / ".claude-task-master"

        # Validate content is not empty/whitespace only
        if not message_request.content.strip():
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="invalid_request",
                    message="Message content cannot be empty or whitespace only",
                    suggestion="Provide a non-empty message content",
                ).model_dump(),
            )

        try:
            mailbox = MailboxStorage(state_dir=state_dir)
            message_id = mailbox.add_message(
                content=message_request.content.strip(),
                sender=message_request.sender,
                priority=message_request.priority,
                metadata=message_request.metadata or {},
            )

            return SendMailboxMessageResponse(
                success=True,
                message_id=message_id,
                message=f"Message sent successfully (id: {message_id})",
            )

        except Exception as e:
            logger.exception("Error sending message to mailbox")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to send message to mailbox",
                    detail=str(e),
                ).model_dump(),
            )

    @router.get(
        "",
        response_model=MailboxStatusResponse,
        responses={
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Get Mailbox Status",
        description="Check the status of the mailbox including message count and previews.",
    )
    async def get_mailbox_status(request: Request) -> MailboxStatusResponse | JSONResponse:
        """Get mailbox status.

        Returns the number of pending messages and previews of each.

        Returns:
            MailboxStatusResponse with message count and previews.

        Raises:
            500: If an error occurs checking the mailbox.
        """
        from datetime import datetime as dt

        from claude_task_master.mailbox import MailboxStorage

        working_dir: Path = getattr(request.app.state, "working_dir", Path.cwd())
        state_dir = working_dir / ".claude-task-master"

        try:
            mailbox = MailboxStorage(state_dir=state_dir)
            status = mailbox.get_status()

            # Convert preview dicts to MailboxMessagePreview models
            previews = []
            for preview_data in status["previews"]:
                previews.append(
                    MailboxMessagePreview(
                        id=preview_data["id"],
                        sender=preview_data["sender"],
                        content_preview=preview_data["content_preview"],
                        priority=preview_data["priority"],
                        timestamp=dt.fromisoformat(preview_data["timestamp"]),
                    )
                )

            # Parse last_checked if present
            last_checked = None
            if status["last_checked"]:
                last_checked = dt.fromisoformat(status["last_checked"])

            return MailboxStatusResponse(
                success=True,
                count=status["count"],
                messages=previews,
                last_checked=last_checked,
                total_messages_received=status["total_messages_received"],
            )

        except Exception as e:
            logger.exception("Error checking mailbox status")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to check mailbox status",
                    detail=str(e),
                ).model_dump(),
            )

    @router.delete(
        "",
        response_model=ClearMailboxResponse,
        responses={
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Clear Mailbox",
        description="Clear all messages from the mailbox.",
    )
    async def clear_mailbox(request: Request) -> ClearMailboxResponse | JSONResponse:
        """Clear all messages from the mailbox.

        Returns:
            ClearMailboxResponse with number of messages cleared.

        Raises:
            500: If an error occurs clearing the mailbox.
        """
        from claude_task_master.mailbox import MailboxStorage

        working_dir: Path = getattr(request.app.state, "working_dir", Path.cwd())
        state_dir = working_dir / ".claude-task-master"

        try:
            mailbox = MailboxStorage(state_dir=state_dir)
            count = mailbox.clear()

            return ClearMailboxResponse(
                success=True,
                messages_cleared=count,
                message=f"Cleared {count} message(s) from mailbox",
            )

        except Exception as e:
            logger.exception("Error clearing mailbox")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to clear mailbox",
                    detail=str(e),
                ).model_dump(),
            )

    return router


# =============================================================================
# Router Registration
# =============================================================================


def register_routes(app: FastAPI) -> None:
    """Register all API routes with the FastAPI app.

    This function creates and registers all routers with the app.
    It's the main entry point for route registration.

    Args:
        app: The FastAPI application to register routes with.
    """
    # Create and register info router
    info_router = create_info_router()
    app.include_router(info_router)

    # Create and register control router
    control_router = create_control_router()
    app.include_router(control_router)

    # Create and register task management router
    task_router = create_task_router()
    app.include_router(task_router)

    # Create and register webhooks router
    webhooks_router = create_webhooks_router()
    app.include_router(webhooks_router, prefix="/webhooks")

    # Create and register mailbox router
    mailbox_router = create_mailbox_router()
    app.include_router(mailbox_router, prefix="/mailbox")

    # Create and register repo setup router
    repo_router = create_repo_router()
    app.include_router(repo_router, prefix="/repo")

    logger.debug("Registered info routes: /status, /plan, /logs, /progress, /context, /health")
    logger.debug("Registered control routes: /control/stop, /control/resume, /config")
    logger.debug("Registered task routes: /task/init, /task")
    logger.debug("Registered webhook routes: /webhooks, /webhooks/{id}, /webhooks/test")
    logger.debug("Registered mailbox routes: /mailbox/send, /mailbox")
    logger.debug("Registered repo routes: /repo/clone, /repo/setup, /repo/plan")
