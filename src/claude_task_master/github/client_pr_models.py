"""Data models and protocol types for GitHub PR operations."""

from __future__ import annotations

import subprocess
from typing import Any, Protocol

from pydantic import BaseModel


class PRStatus(BaseModel):
    """PR status information."""

    number: int
    state: str = "OPEN"  # OPEN, CLOSED, MERGED
    ci_state: str  # PENDING, SUCCESS, FAILURE, ERROR
    unresolved_threads: int
    resolved_threads: int = 0
    total_threads: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    checks_pending: int = 0
    checks_skipped: int = 0
    check_details: list[dict[str, Any]]
    # Mergeable status
    mergeable: str = "UNKNOWN"  # MERGEABLE, CONFLICTING, UNKNOWN
    merge_state_status: str = (
        "UNKNOWN"  # BLOCKED, BEHIND, CLEAN, DIRTY, HAS_HOOKS, UNKNOWN, UNSTABLE
    )
    base_branch: str = "main"
    title: str = ""
    url: str = ""
    head_branch: str = ""
    merged_at: str | None = None


class GitHubClientProtocol(Protocol):
    """Protocol defining the methods required from GitHubClient."""

    def _run_gh_command(
        self,
        cmd: list[str],
        timeout: int = 30,
        check: bool = True,
        capture_output: bool = True,
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a gh CLI command."""
        raise NotImplementedError("Protocol method must be implemented")

    def _get_repo_info(self, cwd: str | None = None) -> str:
        """Get repository info."""
        raise NotImplementedError("Protocol method must be implemented")


__all__ = ["PRStatus", "GitHubClientProtocol"]
