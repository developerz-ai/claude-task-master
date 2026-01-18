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

Usage:
    from claude_task_master.api.routes import create_info_router

    router = create_info_router()
    app.include_router(router)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from claude_task_master import __version__
from claude_task_master.api.models import (
    ContextResponse,
    ErrorResponse,
    HealthResponse,
    LogsResponse,
    PlanResponse,
    ProgressResponse,
    TaskOptionsResponse,
    TaskProgressInfo,
    TaskStatus,
    TaskStatusResponse,
    WorkflowStage,
)
from claude_task_master.core.state import StateManager

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

    logger.debug("Registered info routes: /status, /plan, /logs, /progress, /context, /health")
