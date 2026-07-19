"""Transport-neutral service layer for task and repository operations.

REST (:mod:`claude_task_master.api`) and MCP (:mod:`claude_task_master.mcp`)
share one implementation of every task and repo operation via
:class:`TaskService` and :class:`RepoService`. Each method returns a
:class:`ServiceResult` whose :class:`ServiceOutcome` each transport translates
into its own wire shape -- HTTP status codes for REST, ``dict`` payloads for MCP.
"""

from __future__ import annotations

from claude_task_master.core.services.repo_service import RepoService
from claude_task_master.core.services.results import ServiceOutcome, ServiceResult
from claude_task_master.core.services.task_service import TaskService

__all__ = [
    "RepoService",
    "ServiceOutcome",
    "ServiceResult",
    "TaskService",
]
