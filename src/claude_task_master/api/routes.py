"""REST API route registration for Claude Task Master.

This module is the thin coordinator that imports focused router factories
from their respective sub-modules and registers them all with the FastAPI app.

Router sub-modules:
- routes_info.py     — GET /status, /plan, /logs, /progress, /context, /health
- routes_control.py  — POST /control/stop, /control/resume, PATCH /config
- routes_task.py     — POST /task/init, DELETE /task
- routes_mailbox.py  — POST /mailbox/send, GET /mailbox, DELETE /mailbox
- routes_webhooks.py — CRUD /webhooks + POST /webhooks/test
- routes_repo.py     — POST /repo/clone, /repo/setup, /repo/plan

Usage:
    from claude_task_master.api.routes import register_routes

    register_routes(app)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from claude_task_master.api.routes_control import create_control_router
from claude_task_master.api.routes_info import create_info_router
from claude_task_master.api.routes_mailbox import create_mailbox_router
from claude_task_master.api.routes_repo import create_repo_router
from claude_task_master.api.routes_task import create_task_router
from claude_task_master.api.routes_webhooks import create_webhooks_router

# Re-export so that monkeypatch("claude_task_master.api.routes.CredentialManager") in tests works.
# routes_task.py uses a deferred lookup of this attribute at call time.
from claude_task_master.core.credentials import (
    CredentialManager as CredentialManager,  # noqa: PLC0414
)

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

__all__ = [
    "register_routes",
    "create_info_router",
    "create_control_router",
    "create_task_router",
    "create_mailbox_router",
    "create_webhooks_router",
    "create_repo_router",
    "CredentialManager",  # re-exported for test monkeypatching
]


def register_routes(app: FastAPI) -> None:
    """Register all API routes with the FastAPI app.

    This function creates and registers all routers with the app.
    It's the main entry point for route registration.

    Args:
        app: The FastAPI application to register routes with.
    """
    # Create and register info router
    info_router = create_info_router()
    app.include_router(info_router)

    # Create and register control router
    control_router = create_control_router()
    app.include_router(control_router)

    # Create and register task management router
    task_router = create_task_router()
    app.include_router(task_router)

    # Create and register webhooks router
    webhooks_router = create_webhooks_router()
    app.include_router(webhooks_router, prefix="/webhooks")

    # Create and register mailbox router
    mailbox_router = create_mailbox_router()
    app.include_router(mailbox_router, prefix="/mailbox")

    # Create and register repo setup router
    repo_router = create_repo_router()
    app.include_router(repo_router, prefix="/repo")

    logger.debug(
        "Registered info routes: /status, /plan, /logs, /progress, /context, /health, /coding-style"
    )
    logger.debug("Registered control routes: /control/stop, /control/resume, /config")
    logger.debug("Registered task routes: /task/init, /task")
    logger.debug("Registered webhook routes: /webhooks, /webhooks/{id}, /webhooks/test")
    logger.debug("Registered mailbox routes: /mailbox/send, /mailbox")
    logger.debug("Registered repo routes: /repo/clone, /repo/setup, /repo/plan")
