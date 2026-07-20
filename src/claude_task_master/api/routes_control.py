"""Control endpoints: stop, resume, and update configuration.

These endpoints allow runtime control of task execution.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from claude_task_master.api.models import (
    ConfigUpdateRequest,
    ControlResponse,
    ErrorResponse,
    ResumeRequest,
    StopRequest,
)
from claude_task_master.api.routes_helpers import _get_state_manager, _get_task_service
from claude_task_master.core.services import ServiceOutcome, TaskService

if TYPE_CHECKING:
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse

# Import FastAPI - using try/except for graceful degradation
try:
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)

__all__ = ["create_control_router"]


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
        """Stop a running task."""
        result = _get_task_service(request).stop(
            reason=stop_request.reason, cleanup=stop_request.cleanup
        )

        if result.outcome is ServiceOutcome.NOT_FOUND:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )
        if result.outcome is ServiceOutcome.INVALID:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="invalid_operation",
                    message=result.message,
                    suggestion="Task may be in a terminal state or already stopped",
                ).model_dump(),
            )
        if not result.success:
            logger.error("Error stopping task: %s", result.error)
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to stop task",
                    detail=result.error,
                ).model_dump(),
            )

        control_result = result.data["result"]
        return ControlResponse(
            success=control_result.success,
            message=control_result.message,
            operation=control_result.operation,
            previous_status=control_result.previous_status,
            new_status=control_result.new_status,
            details=control_result.details,
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
        """Resume a paused or blocked task."""
        result = _get_task_service(request).resume()

        if result.outcome is ServiceOutcome.NOT_FOUND:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )
        if result.outcome is ServiceOutcome.INVALID:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="invalid_operation",
                    message=result.message,
                    suggestion="Task may be in a terminal state or already running",
                ).model_dump(),
            )
        if not result.success:
            logger.error("Error resuming task: %s", result.error)
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to resume task",
                    detail=result.error,
                ).model_dump(),
            )

        control_result = result.data["result"]
        return ControlResponse(
            success=control_result.success,
            message=control_result.message,
            operation=control_result.operation,
            previous_status=control_result.previous_status,
            new_status=control_result.new_status,
            details=control_result.details,
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
        """Update task configuration at runtime."""
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

        result = TaskService(state_manager).update_config(**config_update.to_update_dict())

        if result.outcome is ServiceOutcome.NOT_FOUND:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="Start a new task with 'claudetm start <goal>'",
                ).model_dump(),
            )
        if result.outcome is ServiceOutcome.INVALID:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="invalid_configuration",
                    message="Invalid configuration option",
                    detail=result.error,
                ).model_dump(),
            )
        if not result.success:
            logger.error("Error updating configuration: %s", result.error)
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to update configuration",
                    detail=result.error,
                ).model_dump(),
            )

        control_result = result.data["result"]
        return ControlResponse(
            success=control_result.success,
            message=control_result.message,
            operation=control_result.operation,
            previous_status=control_result.previous_status,
            new_status=control_result.new_status,
            details=control_result.details,
        )

    return router
