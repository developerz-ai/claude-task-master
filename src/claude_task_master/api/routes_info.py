"""Read-only info endpoints: status, plan, logs, progress, context, health.

These endpoints provide information about the current task state without
modifying anything. They are safe to call at any time.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from claude_task_master import __version__
from claude_task_master.api.models import (
    ContextResponse,
    DeleteCodingStyleResponse,
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
from claude_task_master.api.routes_helpers import (
    _get_state_manager,
    _get_task_service,
    _get_webhook_status,
    _parse_plan_tasks,
)
from claude_task_master.core.services import ServiceOutcome

if TYPE_CHECKING:
    from fastapi import APIRouter, Query, Request
    from fastapi.responses import JSONResponse

# Import FastAPI - using try/except for graceful degradation
try:
    from fastapi import APIRouter, Query, Request
    from fastapi.responses import JSONResponse

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)

__all__ = ["create_info_router"]


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
        """Get current task status."""
        service = _get_task_service(request)
        status_result = service.get_status()

        if status_result.outcome is ServiceOutcome.NOT_FOUND:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )
        if not status_result.success:
            logger.error("Error loading task status")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to load task status",
                    detail=status_result.error,
                ).model_dump(),
            )

        try:
            state = status_result.data["state"]
            goal = status_result.data["goal"]

            # Calculate task progress from plan
            tasks_info: TaskProgressInfo | None = None
            plan = service.state_manager.load_plan()
            if plan:
                tasks = _parse_plan_tasks(plan)
                completed = sum(1 for _, done, _ in tasks if done)
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
                    enable_release=state.options.enable_release,
                    enable_verification=state.options.enable_verification,
                    max_sessions=state.options.max_sessions,
                    max_prs=state.options.max_prs,
                    pause_on_pr=state.options.pause_on_pr,
                    enable_checkpointing=state.options.enable_checkpointing,
                    log_level=state.options.log_level,
                    log_format=state.options.log_format,
                    pr_per_task=state.options.pr_per_task,
                    max_budget_usd=state.options.max_budget_usd,
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
        """Get task plan content."""
        result = _get_task_service(request).get_plan()

        if result.outcome is ServiceOutcome.NOT_FOUND:
            if result.message == "No plan found":
                return JSONResponse(
                    status_code=404,
                    content=ErrorResponse(
                        error="not_found",
                        message="No plan found",
                        suggestion="Task may still be in planning phase",
                    ).model_dump(),
                )
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )
        if not result.success:
            logger.error("Error loading task plan: %s", result.error)
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to load task plan",
                    detail=result.error,
                ).model_dump(),
            )

        return PlanResponse(success=True, plan=result.data["plan"])

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
        """Get log content."""
        result = _get_task_service(request).get_logs(tail)

        if result.outcome is ServiceOutcome.NOT_FOUND:
            if result.message == "No log file found":
                return JSONResponse(
                    status_code=404,
                    content=ErrorResponse(
                        error="not_found",
                        message="No log file found",
                        suggestion="Task may not have started execution yet",
                    ).model_dump(),
                )
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )
        if not result.success:
            logger.error("Error loading logs: %s", result.error)
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to load logs",
                    detail=result.error,
                ).model_dump(),
            )

        return LogsResponse(
            success=True,
            log_content=result.data["log_content"],
            log_file=result.data["log_file"],
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
        """Get progress summary."""
        result = _get_task_service(request).get_progress()

        if result.outcome is ServiceOutcome.NOT_FOUND:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )
        if not result.success:
            logger.error("Error loading progress: %s", result.error)
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to load progress",
                    detail=result.error,
                ).model_dump(),
            )

        if result.data["progress"] is None:
            return ProgressResponse(
                success=True,
                progress=None,
                message="No progress recorded yet",
            )
        return ProgressResponse(success=True, progress=result.data["progress"])

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
        """Get accumulated context."""
        result = _get_task_service(request).get_context()

        if result.outcome is ServiceOutcome.NOT_FOUND:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )
        if not result.success:
            logger.error("Error loading context: %s", result.error)
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to load context",
                    detail=result.error,
                ).model_dump(),
            )

        context = result.data["context"]
        return ContextResponse(success=True, context=context if context else None)

    @router.get(
        "/health",
        response_model=HealthResponse,
        summary="Health Check",
        description="Health check endpoint for monitoring and load balancers.",
    )
    async def get_health(request: Request) -> HealthResponse:
        """Health check endpoint."""
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

    @router.delete(
        "/coding-style",
        response_model=DeleteCodingStyleResponse,
        responses={
            404: {"model": ErrorResponse, "description": "No active task found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Delete Coding Style",
        description="Delete the coding-style.md file from the state directory.",
    )
    async def delete_coding_style(request: Request) -> DeleteCodingStyleResponse | JSONResponse:
        """Delete the coding-style.md file."""
        result = _get_task_service(request).delete_coding_style()

        if result.outcome is ServiceOutcome.NOT_FOUND:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )
        if not result.success:
            logger.error("Error deleting coding style file: %s", result.error)
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to delete coding style file",
                    detail=result.error,
                ).model_dump(),
            )

        if result.data["deleted"]:
            return DeleteCodingStyleResponse(
                success=True,
                message="Coding style file deleted successfully",
                file_existed=True,
            )
        return DeleteCodingStyleResponse(
            success=True,
            message="Coding style file did not exist",
            file_existed=False,
        )

    return router
