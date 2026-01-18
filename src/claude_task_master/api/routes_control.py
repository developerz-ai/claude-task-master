"""Control endpoints for Claude Task Master REST API.

This module provides the POST /control/stop and POST /control/resume endpoints
for runtime task control.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from claude_task_master.api.models import (
    ErrorResponse,
    ResumeRequest,
    StopRequest,
    TaskStatus,
)
from claude_task_master.core.state import StateManager

if TYPE_CHECKING:
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse

# Import FastAPI - using try/except for graceful degradation
try:
    from fastapi import APIRouter, Body, Request
    from fastapi.responses import JSONResponse

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)

# Module-level singletons for default request bodies
_default_stop_request = StopRequest()
_default_resume_request = ResumeRequest()


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


def create_control_router() -> APIRouter:
    """Create router for control endpoints.

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
        response_model=dict,  # Using dict instead of ControlResponse for flexibility
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request"},
            404: {"model": ErrorResponse, "description": "No active task found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Stop Task",
        description="Stop the currently running task.",
    )
    async def post_control_stop(
        request: Request,
        stop_req: StopRequest = Body(default=_default_stop_request),  # noqa: B008
    ) -> dict | JSONResponse:
        """Stop task execution.

        Stops the current task by updating its status to "stopped".
        Optionally cleans up state files.

        Args:
            request: The FastAPI request object.
            stop_req: Stop request with optional reason and cleanup flag.

        Returns:
            Response with stop confirmation.

        Raises:
            400: If task cannot be stopped.
            404: If no active task exists.
            500: If an error occurs stopping the task.
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
            previous_status = state.status

            # Check if task can be stopped
            if state.status in (TaskStatus.SUCCESS, TaskStatus.FAILED):
                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="invalid_operation",
                        message=f"Cannot stop task from {state.status} status",
                        suggestion="Task is already in a terminal state",
                    ).model_dump(),
                )

            # Update status to stopped
            state.status = TaskStatus.STOPPED.value
            state_manager.save_state(state)

            # Handle cleanup if requested
            if stop_req.cleanup:
                # Keep logs but remove other state files
                logs_dir = state_manager.state_dir / "logs"
                if logs_dir.exists():
                    # Keep logs intact
                    pass

                # Remove state files except logs
                for file_path in state_manager.state_dir.iterdir():
                    if file_path.is_file() and file_path.name != "logs":
                        file_path.unlink()

            reason_msg = f": {stop_req.reason}" if stop_req.reason else ""
            return {
                "success": True,
                "operation": "stop",
                "message": f"Task stopped successfully{reason_msg}",
                "previous_status": previous_status,
                "new_status": TaskStatus.STOPPED,
                "details": {
                    "reason": stop_req.reason,
                    "cleanup": stop_req.cleanup,
                },
            }

        except Exception as e:
            logger.exception("Error stopping task")
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
        response_model=dict,  # Using dict instead of ControlResponse for flexibility
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request"},
            404: {"model": ErrorResponse, "description": "No active task found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Resume Task",
        description="Resume a paused or stopped task.",
    )
    async def post_control_resume(
        request: Request,
        resume_req: ResumeRequest = Body(default=_default_resume_request),  # noqa: B008
    ) -> dict | JSONResponse:
        """Resume task execution.

        Resumes a task that was paused or stopped by updating its status
        back to "working".

        Args:
            request: The FastAPI request object.
            resume_req: Resume request with optional reason.

        Returns:
            Response with resume confirmation.

        Raises:
            400: If task cannot be resumed.
            404: If no active task exists.
            500: If an error occurs resuming the task.
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
            previous_status = state.status

            # Check if task can be resumed
            if state.status == TaskStatus.WORKING.value:
                # Idempotent - already working, just return success
                reason_msg = f": {resume_req.reason}" if resume_req.reason else ""
                return {
                    "success": True,
                    "operation": "resume",
                    "message": f"Task already running{reason_msg}",
                    "previous_status": previous_status,
                    "new_status": TaskStatus.WORKING,
                    "details": {"reason": resume_req.reason},
                }

            if state.status in (TaskStatus.SUCCESS, TaskStatus.FAILED):
                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="invalid_operation",
                        message=f"Cannot resume task from {state.status} status",
                        suggestion="Start a new task to continue work",
                    ).model_dump(),
                )

            # Allow resume from: paused, blocked, stopped
            if state.status not in (TaskStatus.PAUSED, TaskStatus.BLOCKED, TaskStatus.STOPPED):
                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="invalid_state",
                        message=f"Cannot resume task from {state.status} status",
                        suggestion="Task must be paused, blocked, or stopped to resume",
                    ).model_dump(),
                )

            # Update status to working
            state.status = TaskStatus.WORKING.value
            state_manager.save_state(state)

            reason_msg = f": {resume_req.reason}" if resume_req.reason else ""
            return {
                "success": True,
                "operation": "resume",
                "message": f"Task resumed successfully{reason_msg}",
                "previous_status": previous_status,
                "new_status": TaskStatus.WORKING,
                "details": {"reason": resume_req.reason},
            }

        except Exception as e:
            logger.exception("Error resuming task")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to resume task",
                    detail=str(e),
                ).model_dump(),
            )

    return router
