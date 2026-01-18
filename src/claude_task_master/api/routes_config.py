"""Configuration update endpoint for Claude Task Master REST API.

This module provides the PATCH /config endpoint for runtime configuration updates.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from claude_task_master.api.models import (
    ConfigUpdateRequest,
    ControlResponse,
    ErrorResponse,
)
from claude_task_master.core.state import StateManager

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


def create_config_router() -> APIRouter:
    """Create router for configuration endpoint.

    Returns:
        APIRouter configured with config endpoint.

    Raises:
        ImportError: If FastAPI is not installed.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI not installed. Install with: pip install claude-task-master[api]"
        )

    router = APIRouter(tags=["Config"])

    @router.patch(
        "/config",
        response_model=ControlResponse,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request"},
            404: {"model": ErrorResponse, "description": "No active task found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Update Configuration",
        description="Update task configuration options at runtime.",
    )
    async def patch_config(
        request: Request, update: ConfigUpdateRequest
    ) -> ControlResponse | JSONResponse:
        """Update task configuration.

        Updates the task options with the provided values. Only the fields
        specified in the request are updated; other options remain unchanged.

        Args:
            request: The FastAPI request object.
            update: Configuration update request.

        Returns:
            ControlResponse with update details.

        Raises:
            400: If no updates provided.
            404: If no active task exists.
            500: If an error occurs updating configuration.
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

            # Check if there are any updates
            if not update.has_updates():
                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="invalid_request",
                        message="No configuration updates provided",
                        suggestion="Include at least one field to update in the request body",
                    ).model_dump(),
                )

            # Build update dict
            updates_dict = update.to_update_dict()
            previous_status = state.status

            # Apply updates to options
            options_dict = state.options.model_dump()
            options_dict.update(updates_dict)

            # Update state options
            from claude_task_master.core.state import TaskOptions

            state.options = TaskOptions(**options_dict)
            state_manager.save_state(state)

            # Build response
            updated_fields = list(updates_dict.keys())
            fields_str = ", ".join(updated_fields)

            return ControlResponse(
                success=True,
                operation="update_config",
                message=f"Configuration updated: {fields_str}",
                previous_status=previous_status,
                new_status=state.status,
                details={"updated": updates_dict},
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
