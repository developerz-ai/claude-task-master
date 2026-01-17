"""GitHub integration module."""

from .client import (
    DEFAULT_GH_TIMEOUT,
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubMergeError,
    GitHubNotFoundError,
    GitHubTimeoutError,
    PRStatus,
    WorkflowRun,
)

__all__ = [
    "DEFAULT_GH_TIMEOUT",
    "GitHubAuthError",
    "GitHubClient",
    "GitHubError",
    "GitHubMergeError",
    "GitHubNotFoundError",
    "GitHubTimeoutError",
    "PRStatus",
    "WorkflowRun",
]
