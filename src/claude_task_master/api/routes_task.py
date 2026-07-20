"""Task management endpoints: init and delete tasks.

These endpoints allow task lifecycle management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from claude_task_master.api.models import (
    ErrorResponse,
    TaskDeleteResponse,
    TaskInitRequest,
    TaskInitResponse,
)
from claude_task_master.api.routes_helpers import _get_state_manager, _get_task_service
from claude_task_master.core.services import ServiceOutcome, TaskService
from claude_task_master.core.state import TaskOptions

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

__all__ = ["create_task_router"]


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
        """Initialize a new task."""
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
            # Load credentials to verify we can authenticate.
            # Deferred lookup via the routes module so that tests can monkeypatch
            # claude_task_master.api.routes.CredentialManager and have it take effect here.
            try:
                import claude_task_master.api.routes as _routes_mod

                cred_manager = _routes_mod.CredentialManager()
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
                enable_release=task_init.enable_release,
                enable_verification=task_init.enable_verification,
                max_sessions=task_init.max_sessions,
                max_prs=task_init.max_prs,
                pause_on_pr=task_init.pause_on_pr,
                enable_checkpointing=False,  # Default to False
                log_level="normal",  # Default to normal
                log_format="text",  # Default to text
                pr_per_task=False,  # Default to False
            )
            init_result = TaskService(state_manager).init_task(
                task_init.goal, task_init.model, options
            )

            if init_result.outcome is ServiceOutcome.CONFLICT:
                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="task_exists",
                        message="A task already exists",
                        suggestion="Use DELETE /task to remove the existing task first",
                    ).model_dump(),
                )
            if not init_result.success:
                logger.error("Error initializing task: %s", init_result.error)
                return JSONResponse(
                    status_code=500,
                    content=ErrorResponse(
                        error="internal_error",
                        message="Failed to initialize task",
                        detail=init_result.error,
                    ).model_dump(),
                )

            state = init_result.data["state"]
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
        """Delete the current task."""
        # DELETE always removes the task (force=True): unlike the MCP clean tool
        # it does not gate on an active session, it releases the lock and deletes.
        result = _get_task_service(request).clean(force=True)

        if result.outcome is ServiceOutcome.NOT_FOUND:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error="not_found",
                    message="No active task found",
                    suggestion="No task to delete",
                ).model_dump(),
            )
        if not result.success:
            logger.error("Error deleting task: %s", result.error)
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to delete task",
                    detail=result.error,
                ).model_dump(),
            )

        return TaskDeleteResponse(
            success=True,
            message="Task deleted successfully",
            files_removed=result.data["files_removed"],
        )

    return router
