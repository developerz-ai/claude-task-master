"""Repository setup REST API routes for Claude Task Master.

This module provides REST API endpoints for repository setup operations:
- POST /repo/clone: Clone a git repository to the workspace
- POST /repo/setup: Set up a cloned repository for development
- POST /repo/plan: Create a plan for a repository (read-only, no work)

These endpoints support the AI developer workflow where repositories are
cloned, set up for development, and then work is planned/executed.

Usage:
    from claude_task_master.api.routes_repo import create_repo_router

    router = create_repo_router()
    app.include_router(router, prefix="/repo")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from claude_task_master.api.models import (
    CloneRepoRequest,
    CloneRepoResponse,
    ErrorResponse,
    PlanRepoRequest,
    PlanRepoResponse,
    SetupRepoRequest,
    SetupRepoResponse,
)
from claude_task_master.mcp.tools import (
    clone_repo,
    plan_repo,
    setup_repo,
)

if TYPE_CHECKING:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

# Import FastAPI - using try/except for graceful degradation
try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)


def create_repo_router() -> APIRouter:
    """Create router for repository setup endpoints.

    These endpoints support the AI developer workflow for cloning,
    setting up, and planning work on repositories.

    Returns:
        APIRouter configured with repo setup endpoints.

    Raises:
        ImportError: If FastAPI is not installed.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI not installed. Install with: pip install claude-task-master[api]"
        )

    router = APIRouter(tags=["Repository Setup"])

    @router.post(
        "/clone",
        response_model=CloneRepoResponse,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request or clone failed"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Clone Repository",
        description=(
            "Clone a git repository to the workspace. "
            "Default target is ~/workspace/claude-task-master/{repo-name}."
        ),
    )
    async def post_clone_repo(
        clone_request: CloneRepoRequest,
    ) -> CloneRepoResponse | JSONResponse:
        """Clone a git repository.

        Clones the specified repository to the workspace directory.
        If no target directory is specified, clones to
        ~/workspace/claude-task-master/{repo-name}.

        Args:
            clone_request: Clone request with URL, optional target_dir, and branch.

        Returns:
            CloneRepoResponse with clone result including target directory path.

        Raises:
            400: If the URL is invalid or clone fails.
            500: If an unexpected error occurs.
        """
        try:
            # Use the MCP tool implementation for consistency
            result = clone_repo(
                url=clone_request.url,
                target_dir=clone_request.target_dir,
                branch=clone_request.branch,
            )

            if not result.get("success", False):
                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="clone_failed",
                        message=result.get("message", "Clone failed"),
                        detail=result.get("error"),
                        suggestion="Check the repository URL and your network connection",
                    ).model_dump(),
                )

            return CloneRepoResponse(
                success=True,
                message=result.get("message", "Repository cloned successfully"),
                repo_url=result.get("repo_url"),
                target_dir=result.get("target_dir"),
                branch=result.get("branch"),
            )

        except Exception as e:
            logger.exception("Error cloning repository")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to clone repository",
                    detail=str(e),
                ).model_dump(),
            )

    @router.post(
        "/setup",
        response_model=SetupRepoResponse,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request or setup failed"},
            404: {"model": ErrorResponse, "description": "Directory not found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Setup Repository",
        description=(
            "Set up a cloned repository for development. "
            "Detects project type and installs dependencies, creates venv, runs setup scripts."
        ),
    )
    async def post_setup_repo(
        setup_request: SetupRepoRequest,
    ) -> SetupRepoResponse | JSONResponse:
        """Set up a cloned repository for development.

        Detects the project type and performs appropriate setup:
        - Creates virtual environment (for Python projects)
        - Installs dependencies (pip, npm, pnpm, yarn, bun)
        - Runs setup scripts (setup-hooks.sh, setup.sh, etc.)

        Args:
            setup_request: Setup request with work_dir path.

        Returns:
            SetupRepoResponse with setup result including steps completed.

        Raises:
            400: If setup fails.
            404: If the work directory doesn't exist.
            500: If an unexpected error occurs.
        """
        try:
            # Use the MCP tool implementation for consistency
            result = setup_repo(work_dir=setup_request.work_dir)

            if not result.get("success", False):
                # Determine appropriate error code
                error_msg = result.get("error", "")
                if "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                    return JSONResponse(
                        status_code=404,
                        content=ErrorResponse(
                            error="not_found",
                            message=result.get("message", "Directory not found"),
                            detail=result.get("error"),
                            suggestion="Ensure the work directory exists and is accessible",
                        ).model_dump(),
                    )

                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="setup_failed",
                        message=result.get("message", "Setup failed"),
                        detail=result.get("error"),
                        suggestion="Check the project structure and dependencies",
                    ).model_dump(),
                )

            return SetupRepoResponse(
                success=True,
                message=result.get("message", "Repository setup completed"),
                work_dir=result.get("work_dir"),
                steps_completed=result.get("steps_completed", []),
                venv_path=result.get("venv_path"),
                dependencies_installed=result.get("dependencies_installed", False),
                setup_scripts_run=result.get("setup_scripts_run", []),
            )

        except Exception as e:
            logger.exception("Error setting up repository")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to set up repository",
                    detail=str(e),
                ).model_dump(),
            )

    @router.post(
        "/plan",
        response_model=PlanRepoResponse,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request or planning failed"},
            404: {"model": ErrorResponse, "description": "Directory not found"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
        summary="Plan Repository Work",
        description=(
            "Create a plan for a repository without executing any work. "
            "Uses read-only tools to analyze the codebase and generate a task list."
        ),
    )
    async def post_plan_repo(
        plan_request: PlanRepoRequest,
    ) -> PlanRepoResponse | JSONResponse:
        """Create a plan for a repository.

        Uses read-only tools (Read, Glob, Grep) to analyze the codebase
        and output a structured plan with tasks and success criteria.
        No changes are made to the repository.

        Use this after cloning and setting up a repo to plan work before
        execution, or to get a plan for a new goal in an existing repository.

        Args:
            plan_request: Plan request with work_dir, goal, and optional model.

        Returns:
            PlanRepoResponse with plan, criteria, and run_id.

        Raises:
            400: If planning fails or goal is invalid.
            404: If the work directory doesn't exist.
            500: If an unexpected error occurs.
        """
        try:
            # Use the MCP tool implementation for consistency
            result = plan_repo(
                work_dir=plan_request.work_dir,
                goal=plan_request.goal,
                model=plan_request.model,
            )

            if not result.get("success", False):
                # Determine appropriate error code
                error_msg = result.get("error", "")
                if "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                    return JSONResponse(
                        status_code=404,
                        content=ErrorResponse(
                            error="not_found",
                            message=result.get("message", "Directory not found"),
                            detail=result.get("error"),
                            suggestion="Ensure the work directory exists and is accessible",
                        ).model_dump(),
                    )

                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="planning_failed",
                        message=result.get("message", "Planning failed"),
                        detail=result.get("error"),
                        suggestion="Check the goal description and repository structure",
                    ).model_dump(),
                )

            return PlanRepoResponse(
                success=True,
                message=result.get("message", "Plan created successfully"),
                work_dir=result.get("work_dir"),
                goal=result.get("goal"),
                plan=result.get("plan"),
                criteria=result.get("criteria"),
                run_id=result.get("run_id"),
            )

        except Exception as e:
            logger.exception("Error planning repository work")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="internal_error",
                    message="Failed to create plan",
                    detail=str(e),
                ).model_dump(),
            )

    return router
