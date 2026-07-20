"""Shared helper functions for API route handlers.

These utilities are used by multiple router modules and are extracted here
to avoid duplication. Each helper takes a FastAPI ``Request`` and returns
the relevant domain object or data.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_task_master.api.models import WebhookStatusInfo
from claude_task_master.core.services import TaskService
from claude_task_master.core.state import StateManager

if TYPE_CHECKING:
    from fastapi import Request

# Import FastAPI - using try/except for graceful degradation
try:
    from fastapi import Request  # noqa: F811

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)

__all__ = [
    "_get_state_manager",
    "_get_task_service",
    "_parse_plan_tasks",
    "_get_webhook_status",
]


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


def _get_task_service(request: Request) -> TaskService:
    """Build a :class:`TaskService` for the app's working directory.

    Args:
        request: The FastAPI request object.

    Returns:
        A task service bound to the request's state directory.
    """
    return TaskService(_get_state_manager(request))


def _parse_plan_tasks(plan: str) -> list[tuple[str, bool, list[str]]]:
    """Parse task checkboxes from plan markdown.

    Args:
        plan: The plan content in markdown format.

    Returns:
        List of (task_description, is_completed, context_lines) tuples.
    """
    from claude_task_master.core.task_group import parse_tasks_with_groups

    parsed_tasks, _ = parse_tasks_with_groups(plan)
    return [(t.description, t.is_complete, t.context_lines) for t in parsed_tasks]


def _get_webhook_status(request: Request) -> WebhookStatusInfo | None:
    """Get webhook configuration status summary.

    Args:
        request: The FastAPI request object.

    Returns:
        WebhookStatusInfo with counts of total/enabled/disabled webhooks,
        or None if webhooks file doesn't exist or can't be loaded.
    """
    working_dir: Path = getattr(request.app.state, "working_dir", Path.cwd())
    webhooks_file = working_dir / ".claude-task-master" / "webhooks.json"

    if not webhooks_file.exists():
        return None

    try:
        with open(webhooks_file) as f:
            data = json.load(f)
            webhooks: dict[str, dict[str, Any]] = data.get("webhooks", {})

        total = len(webhooks)
        enabled = sum(1 for wh in webhooks.values() if wh.get("enabled", True))
        disabled = total - enabled

        return WebhookStatusInfo(
            total=total,
            enabled=enabled,
            disabled=disabled,
        )
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load webhook status: {e}")
        return None
