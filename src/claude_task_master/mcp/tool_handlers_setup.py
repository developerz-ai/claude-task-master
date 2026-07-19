"""setup_repo tool handler for MCP.

This module is intentionally a single-function module: ``setup_repo`` is a
large function (~380 LOC) that handles Python + Node.js + script-based project
setup and was split out from :mod:`claude_task_master.mcp.tool_handlers_repo`
to keep every file under the 500-LOC budget.

Design note — patchable globals
--------------------------------
``is_auth_enabled`` is imported into :mod:`claude_task_master.mcp.tools` and
tests patch it there.  This module reads it via a deferred lookup
(``_tools_ns()``) so patches are visible without a circular import.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Shared constant / path helpers are imported from tool_handlers_repo to
# avoid duplication and keep the auth message consistent.
from claude_task_master.mcp.tool_handlers_repo import (
    _REPO_AUTH_REQUIRED_MESSAGE,
    WorkspaceConfinementError,
    _resolve_within_workspace,
)
from claude_task_master.mcp.tool_models import SetupRepoResult

# ---------------------------------------------------------------------------
# Deferred lookup helpers (mirror of tool_handlers_repo._tools_ns/_is_auth)
# ---------------------------------------------------------------------------


def _tools_ns() -> Any:
    """Return the ``claude_task_master.mcp.tools`` module (deferred)."""
    import claude_task_master.mcp.tools as _t  # noqa: PLC0415

    return _t


def _is_auth_enabled() -> bool:
    """Delegate to ``mcp.tools.is_auth_enabled`` so test patches take effect."""
    return _tools_ns().is_auth_enabled()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# setup_repo
# ---------------------------------------------------------------------------


def setup_repo(
    work_dir: str | Path,
    run_setup_scripts: bool = False,
) -> dict[str, Any]:
    """Set up a cloned repository for development.

    Detects the project type and performs appropriate setup:
    - Creates virtual environment (for Python projects)
    - Installs dependencies (pip, npm, etc.)
    - Runs setup scripts (setup-hooks.sh, etc.) only when explicitly opted in

    Args:
        work_dir: Path to the cloned repository directory (confined to the
            workspace base).
        run_setup_scripts: Execute repo-supplied setup scripts. Disabled by
            default because running untrusted scripts is a remote-code-execution
            risk; scripts are detected but skipped unless this is True.

    Returns:
        Dictionary containing setup result with success status and details.
    """
    # Refuse when authentication is not configured: this endpoint runs
    # subprocesses and must never be reachable unauthenticated.
    if not _is_auth_enabled():
        return SetupRepoResult(
            success=False,
            message=_REPO_AUTH_REQUIRED_MESSAGE,
            work_dir=str(work_dir),
            error="authentication_required",
        ).model_dump()

    # Confine the work directory to the workspace base.
    try:
        work_path = _resolve_within_workspace(work_dir)
    except WorkspaceConfinementError as e:
        return SetupRepoResult(
            success=False,
            message=str(e),
            work_dir=str(Path(work_dir).expanduser()),
            error="path_outside_workspace",
        ).model_dump()

    steps_completed: list[str] = []
    setup_scripts_run: list[str] = []
    venv_path: str | None = None
    dependencies_installed = False

    # Validate work directory
    if not work_path.exists():
        return SetupRepoResult(
            success=False,
            message=f"Directory does not exist: {work_path}",
            work_dir=str(work_path),
            error="Work directory not found",
        ).model_dump()

    if not work_path.is_dir():
        return SetupRepoResult(
            success=False,
            message=f"Path is not a directory: {work_path}",
            work_dir=str(work_path),
            error="Path is not a directory",
        ).model_dump()

    # Detect project type based on manifest files
    is_python = (work_path / "pyproject.toml").exists() or (work_path / "setup.py").exists()
    is_node = (work_path / "package.json").exists()
    has_requirements = (work_path / "requirements.txt").exists()
    has_uv_lock = (work_path / "uv.lock").exists()

    # Detect setup scripts
    setup_scripts: list[Path] = []
    scripts_dir = work_path / "scripts"
    if scripts_dir.exists():
        # Look for common setup scripts
        for script_name in ["setup-hooks.sh", "setup.sh", "install.sh", "bootstrap.sh"]:
            script_path = scripts_dir / script_name
            if script_path.exists() and script_path.is_file():
                setup_scripts.append(script_path)

    # Also check root directory for setup scripts
    for script_name in ["setup.sh", "install.sh", "bootstrap.sh"]:
        script_path = work_path / script_name
        if script_path.exists() and script_path.is_file():
            setup_scripts.append(script_path)

    try:
        # === Python Project Setup ===
        if is_python:
            steps_completed.append("Detected Python project")

            # Check for uv (preferred) or fall back to standard venv + pip
            has_uv = shutil.which("uv") is not None

            if has_uv:
                # Use uv for virtual environment and dependency management
                steps_completed.append("Using uv for dependency management")

                # Create venv with uv if not exists
                venv_dir = work_path / ".venv"
                if not venv_dir.exists():
                    result = subprocess.run(
                        ["uv", "venv", str(venv_dir)],
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=60,
                    )
                    if result.returncode != 0:
                        return SetupRepoResult(
                            success=False,
                            message=f"Failed to create venv with uv: {result.stderr}",
                            work_dir=str(work_path),
                            steps_completed=steps_completed,
                            error=result.stderr,
                        ).model_dump()
                    steps_completed.append("Created virtual environment with uv")
                else:
                    steps_completed.append("Virtual environment already exists")

                venv_path = str(venv_dir)

                # Install dependencies with uv
                # Prefer uv sync for uv-managed projects, otherwise uv pip install
                if has_uv_lock or (work_path / "pyproject.toml").exists():
                    # Use uv sync for projects with pyproject.toml
                    sync_cmd = ["uv", "sync"]
                    # Try to install all extras if available
                    if (work_path / "pyproject.toml").exists():
                        sync_cmd.append("--all-extras")

                    result = subprocess.run(
                        sync_cmd,
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=300,
                    )
                    if result.returncode == 0:
                        dependencies_installed = True
                        steps_completed.append("Installed dependencies with uv sync")
                    else:
                        # Fall back to basic uv sync without extras
                        result = subprocess.run(
                            ["uv", "sync"],
                            cwd=work_path,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=300,
                        )
                        if result.returncode == 0:
                            dependencies_installed = True
                            steps_completed.append("Installed dependencies with uv sync (basic)")
                        else:
                            steps_completed.append(f"Warning: uv sync failed: {result.stderr}")
                elif has_requirements:
                    result = subprocess.run(
                        ["uv", "pip", "install", "-r", "requirements.txt"],
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=300,
                    )
                    if result.returncode == 0:
                        dependencies_installed = True
                        steps_completed.append("Installed dependencies from requirements.txt")
                    else:
                        steps_completed.append(f"Warning: pip install failed: {result.stderr}")
            else:
                # Fall back to standard Python venv + pip
                steps_completed.append("Using standard venv + pip")

                venv_dir = work_path / ".venv"
                if not venv_dir.exists():
                    result = subprocess.run(
                        ["python3", "-m", "venv", str(venv_dir)],
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=120,
                    )
                    if result.returncode != 0:
                        return SetupRepoResult(
                            success=False,
                            message=f"Failed to create venv: {result.stderr}",
                            work_dir=str(work_path),
                            steps_completed=steps_completed,
                            error=result.stderr,
                        ).model_dump()
                    steps_completed.append("Created virtual environment")
                else:
                    steps_completed.append("Virtual environment already exists")

                venv_path = str(venv_dir)
                # Use platform-appropriate path for pip
                pip_path = (
                    venv_dir
                    / ("Scripts" if sys.platform == "win32" else "bin")
                    / ("pip.exe" if sys.platform == "win32" else "pip")
                )

                # Install dependencies with pip
                if (work_path / "pyproject.toml").exists():
                    # Install project in editable mode with dev extras
                    result = subprocess.run(
                        [str(pip_path), "install", "-e", ".[dev]"],
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=300,
                    )
                    if result.returncode == 0:
                        dependencies_installed = True
                        steps_completed.append("Installed project with pip (editable + dev)")
                    else:
                        # Try without dev extras
                        result = subprocess.run(
                            [str(pip_path), "install", "-e", "."],
                            cwd=work_path,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=300,
                        )
                        if result.returncode == 0:
                            dependencies_installed = True
                            steps_completed.append("Installed project with pip (editable)")
                        else:
                            steps_completed.append(
                                f"Warning: pip install failed: {result.stderr}"
                            )
                elif has_requirements:
                    result = subprocess.run(
                        [str(pip_path), "install", "-r", "requirements.txt"],
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=300,
                    )
                    if result.returncode == 0:
                        dependencies_installed = True
                        steps_completed.append("Installed dependencies from requirements.txt")
                    else:
                        steps_completed.append(f"Warning: pip install failed: {result.stderr}")

        # === Node.js Project Setup ===
        if is_node:
            steps_completed.append("Detected Node.js project")

            # Check for package managers (lock files indicate preferred manager)
            has_pnpm_lock = (work_path / "pnpm-lock.yaml").exists()
            has_yarn_lock = (work_path / "yarn.lock").exists()
            has_bun_lock = (work_path / "bun.lockb").exists()

            # Determine which package manager to use
            if has_bun_lock and shutil.which("bun"):
                pkg_manager = "bun"
                install_cmd = ["bun", "install"]
            elif has_pnpm_lock and shutil.which("pnpm"):
                pkg_manager = "pnpm"
                install_cmd = ["pnpm", "install"]
            elif has_yarn_lock and shutil.which("yarn"):
                pkg_manager = "yarn"
                install_cmd = ["yarn", "install"]
            elif shutil.which("npm"):
                pkg_manager = "npm"
                install_cmd = ["npm", "install"]
            else:
                steps_completed.append("Warning: No Node.js package manager found")
                pkg_manager = None
                install_cmd = None

            if install_cmd:
                result = subprocess.run(
                    install_cmd,
                    cwd=work_path,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=300,
                )
                if result.returncode == 0:
                    dependencies_installed = True
                    steps_completed.append(f"Installed dependencies with {pkg_manager}")
                else:
                    steps_completed.append(
                        f"Warning: {pkg_manager} install failed: {result.stderr}"
                    )

        # === Run Setup Scripts ===
        # Executing repo-supplied scripts is a remote-code-execution vector, so it
        # is gated behind an explicit opt-in. When disabled, scripts are detected
        # but never run.
        if setup_scripts and not run_setup_scripts:
            steps_completed.append(
                f"Detected {len(setup_scripts)} setup script(s) but skipped execution "
                "(set run_setup_scripts=true to run them)"
            )
        elif run_setup_scripts:
            for script in setup_scripts:
                try:
                    # Make script executable (skip on Windows where chmod is not needed)
                    if sys.platform != "win32":
                        script.chmod(script.stat().st_mode | 0o755)

                    result = subprocess.run(
                        [str(script)],
                        cwd=work_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=120,
                    )
                    if result.returncode == 0:
                        setup_scripts_run.append(str(script.relative_to(work_path)))
                        steps_completed.append(f"Ran setup script: {script.name}")
                    else:
                        steps_completed.append(
                            f"Warning: Setup script {script.name} failed: {result.stderr}"
                        )
                except Exception as e:
                    steps_completed.append(f"Warning: Could not run {script.name}: {e}")

        # Determine overall success
        # Success if we detected a project type and either installed deps or ran scripts
        success = len(steps_completed) > 0 and (
            dependencies_installed or len(setup_scripts_run) > 0
        )

        if not is_python and not is_node:
            steps_completed.append("No recognized project type (Python or Node.js)")
            if setup_scripts_run:
                success = True  # Still success if we ran setup scripts
            else:
                success = False

        message = (
            f"Setup completed for {work_path.name}"
            if success
            else f"Setup incomplete for {work_path.name}"
        )

        return SetupRepoResult(
            success=success,
            message=message,
            work_dir=str(work_path),
            steps_completed=steps_completed,
            venv_path=venv_path,
            dependencies_installed=dependencies_installed,
            setup_scripts_run=setup_scripts_run,
        ).model_dump()

    except subprocess.TimeoutExpired as e:
        return SetupRepoResult(
            success=False,
            message=f"Setup timed out: {e}",
            work_dir=str(work_path),
            steps_completed=steps_completed,
            venv_path=venv_path,
            dependencies_installed=dependencies_installed,
            setup_scripts_run=setup_scripts_run,
            error="Operation timed out",
        ).model_dump()

    except Exception as e:
        return SetupRepoResult(
            success=False,
            message=f"Setup failed: {e}",
            work_dir=str(work_path),
            steps_completed=steps_completed,
            venv_path=venv_path,
            dependencies_installed=dependencies_installed,
            setup_scripts_run=setup_scripts_run,
            error=str(e),
        ).model_dump()
