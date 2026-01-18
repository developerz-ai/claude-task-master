"""Wrapper module to execute the bash claudetm script.

This module provides a Python entry point that locates and executes the
bash wrapper script. This is necessary because `uv tool install` installs
scripts via Python entry points, but we want the bash wrapper to handle
configuration loading before Python starts.

Installation methods supported:
1. uv tool install - locates script in package data
2. pip install - locates script in package data or scripts
3. Development mode - locates script in the repo's bin/ directory

The bash wrapper (bin/claudetm) is responsible for:
- Loading .claude-task-master/config.json
- Setting environment variables (API keys, model names, etc.)
- Invoking the Python CLI (claudetm-py)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import NoReturn


def find_bash_wrapper() -> Path | None:
    """Locate the bash wrapper script.

    Search order:
    1. CLAUDETM_BASH_WRAPPER environment variable (for testing/override)
    2. Same directory as this module (editable install)
    3. Package's bin directory (relative to this file)
    4. Installed scripts directory (uv tool install / pip install)
    5. Development repo structure (../../bin/claudetm relative to this file)

    Returns:
        Path to the bash wrapper, or None if not found.
    """
    # 1. Environment variable override (for testing or custom setups)
    if env_wrapper := os.environ.get("CLAUDETM_BASH_WRAPPER"):
        wrapper_path = Path(env_wrapper)
        if wrapper_path.is_file() and os.access(wrapper_path, os.X_OK):
            return wrapper_path

    # Get the directory containing this module
    this_dir = Path(__file__).parent.resolve()

    # 2. Check in package directory (for editable installs with scripts)
    package_script = this_dir / "bin" / "claudetm"
    if package_script.is_file() and os.access(package_script, os.X_OK):
        return package_script

    # 3. Development mode: navigate up to repo root and check bin/
    # This handles the case when developing locally
    repo_root = this_dir.parent.parent  # src/claude_task_master -> repo root
    dev_script = repo_root / "bin" / "claudetm"
    if dev_script.is_file() and os.access(dev_script, os.X_OK):
        return dev_script

    # 4. Check in the same bin directory as python executable
    # This handles uv tool install where scripts go to the tool's bin dir
    python_bin_dir = Path(sys.executable).parent
    installed_script = python_bin_dir / "claudetm"
    if installed_script.is_file() and os.access(installed_script, os.X_OK):
        return installed_script

    # 5. Check common installation locations
    common_paths = [
        Path.home() / ".local" / "bin" / "claudetm",
        Path("/usr/local/bin/claudetm"),
        Path("/usr/bin/claudetm"),
    ]
    for path in common_paths:
        if path.is_file() and os.access(path, os.X_OK):
            return path

    # 6. Try to find it using 'which' command
    try:
        result = subprocess.run(
            ["which", "claudetm"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            found_path = Path(result.stdout.strip())
            if found_path.is_file() and os.access(found_path, os.X_OK):
                return found_path
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        # Silently ignore failures from 'which' command - this is just a fallback
        # search method. If 'which' isn't available or times out, we simply
        # return None to indicate the wrapper wasn't found.
        pass

    return None


def main() -> NoReturn:
    """Main entry point that executes the bash wrapper.

    This function:
    1. Locates the bash wrapper script
    2. Passes all command-line arguments to it
    3. Replaces the current process with the bash script

    If the bash wrapper cannot be found, it falls back to running
    the Python CLI directly (losing the config.json loading feature).
    """
    wrapper = find_bash_wrapper()

    if wrapper is None:
        # Fallback: run Python CLI directly (without bash wrapper features)
        # This means config.json won't be loaded before Python starts,
        # but the CLI will still work for basic operations
        print(
            "[claudetm] Warning: Bash wrapper not found. "
            "Running Python CLI directly (config.json will not be pre-loaded).",
            file=sys.stderr,
        )
        print(
            "[claudetm] Tip: Set CLAUDETM_BASH_WRAPPER env var to the wrapper path.",
            file=sys.stderr,
        )

        # Import and run the Python CLI directly
        from claude_task_master.cli import app

        app()
        sys.exit(0)

    # Execute the bash wrapper, replacing this process
    # This ensures proper signal handling and exit codes
    try:
        os.execv(str(wrapper), [str(wrapper)] + sys.argv[1:])
    except OSError as e:
        print(f"[claudetm] Error executing bash wrapper: {e}", file=sys.stderr)
        print(f"[claudetm] Wrapper path: {wrapper}", file=sys.stderr)

        # Fallback to subprocess if execv fails (e.g., on some Windows scenarios)
        try:
            result = subprocess.run(
                [str(wrapper)] + sys.argv[1:],
                check=False,
            )
            sys.exit(result.returncode)
        except Exception as sub_e:
            print(f"[claudetm] Subprocess fallback also failed: {sub_e}", file=sys.stderr)
            sys.exit(1)


def get_wrapper_path() -> str | None:
    """Get the path to the bash wrapper, or None if not found.

    This is a utility function for other code that needs to know
    where the wrapper is located.

    Returns:
        String path to the wrapper, or None if not found.
    """
    wrapper = find_bash_wrapper()
    return str(wrapper) if wrapper else None


if __name__ == "__main__":
    main()
