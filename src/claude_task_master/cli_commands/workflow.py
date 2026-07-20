"""Workflow commands for Claude Task Master — start and resume.

Public API is unchanged: all names that were importable from this module before
the split remain importable here via explicit re-exports.

Implementation lives in the focused sub-modules:
- :mod:`.workflow_helpers` — shared utility functions
- :mod:`.workflow_start` — :func:`start` command
- :mod:`.workflow_resume` — :func:`resume` command
"""

from __future__ import annotations

import typer

from .workflow_helpers import (  # noqa: F401
    _display_exit_message,
    _initialize_components,
    _initialize_logger,
    _run_work_loop,
    _validate_budget,
    _validate_goal,
    _validate_log_options,
    auto_merge_notice,
    console,
)
from .workflow_resume import resume  # noqa: F401
from .workflow_start import start  # noqa: F401


def register_workflow_commands(app: typer.Typer) -> None:
    """Register workflow commands with the Typer app."""
    app.command()(start)
    app.command()(resume)


__all__ = [
    "console",
    "auto_merge_notice",
    "_initialize_logger",
    "_initialize_components",
    "_run_work_loop",
    "_display_exit_message",
    "_validate_log_options",
    "_validate_goal",
    "_validate_budget",
    "start",
    "resume",
    "register_workflow_commands",
]
