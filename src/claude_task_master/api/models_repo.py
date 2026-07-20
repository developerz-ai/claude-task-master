"""Repository setup request and response models for the REST API.

Covers cloning, setting up, and planning for git repositories in the
AI developer workflow.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from claude_task_master.api.models_common import (
    _validate_model_field,
    _validate_within_workspace,
)

__all__ = [
    # Request models
    "CloneRepoRequest",
    "SetupRepoRequest",
    "PlanRepoRequest",
    # Response models
    "CloneRepoResponse",
    "SetupRepoResponse",
    "PlanRepoResponse",
    "DeleteCodingStyleResponse",
]


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

    @field_validator("target_dir")
    @classmethod
    def _confine_target_dir(cls, v: str | None) -> str | None:
        """Reject target directories that escape the workspace base."""
        if v is None:
            return v
        return _validate_within_workspace(v)


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
    run_setup_scripts: bool = Field(
        default=False,
        description="Execute repo-supplied setup scripts (setup.sh, install.sh, "
        "setup-hooks.sh, ...). Disabled by default because running untrusted "
        "scripts is a remote-code-execution risk.",
    )

    @field_validator("work_dir")
    @classmethod
    def _confine_work_dir(cls, v: str) -> str:
        """Reject work directories that escape the workspace base."""
        return _validate_within_workspace(v)


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
        description="Model to use for planning (opus, sonnet, fable, haiku, sonnet_1m)",
    )

    @field_validator("work_dir")
    @classmethod
    def _confine_work_dir(cls, v: str) -> str:
        """Reject work directories that escape the workspace base."""
        return _validate_within_workspace(v)

    @field_validator("model")
    @classmethod
    def _check_model(cls, value: str) -> str:
        """Reject models outside the shared model registry."""
        return _validate_model_field(value)


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


class DeleteCodingStyleResponse(BaseModel):
    """Response model for deleting the coding-style.md file.

    Attributes:
        success: Whether the deletion operation succeeded.
        message: Human-readable result message.
        file_existed: Whether the file existed before deletion.
        error: Error message if deletion failed.
    """

    success: bool
    message: str
    file_existed: bool = False
    error: str | None = None
