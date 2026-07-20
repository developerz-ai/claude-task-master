"""Concrete webhook event dataclasses — task, PR, and CI events.

Contains the event dataclasses for:
  - Task lifecycle: TaskStartedEvent, TaskCompletedEvent, TaskFailedEvent
  - Pull request: PRCreatedEvent, PRMergedEvent
  - CI: CIPassedEvent, CIFailedEvent
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .event_base import WebhookEvent
from .event_types import EventType

# =============================================================================
# Task Events
# =============================================================================


@dataclass
class TaskStartedEvent(WebhookEvent):
    """Event emitted when a task begins execution.

    Attributes:
        task_index: Zero-based index of the task in the plan.
        task_description: Human-readable description of the task.
        total_tasks: Total number of tasks in the plan.
        branch: Git branch name being used (optional).
        pr_group: PR group name if task is part of a group (optional).
    """

    task_index: int = 0
    task_description: str = ""
    total_tasks: int = 0
    branch: str | None = None
    pr_group: str | None = None

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.TASK_STARTED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus task-specific data.
        """
        data = super().to_dict()
        data.update(
            {
                "task_index": self.task_index,
                "task_description": self.task_description,
                "total_tasks": self.total_tasks,
                "branch": self.branch,
                "pr_group": self.pr_group,
            }
        )
        return data


@dataclass
class TaskCompletedEvent(WebhookEvent):
    """Event emitted when a task completes successfully.

    Attributes:
        task_index: Zero-based index of the completed task.
        task_description: Human-readable description of the task.
        total_tasks: Total number of tasks in the plan.
        completed_tasks: Number of tasks completed so far.
        duration_seconds: Time taken to complete the task.
        commit_hash: Git commit hash if changes were committed (optional).
        branch: Git branch name (optional).
        pr_group: PR group name if task is part of a group (optional).
    """

    task_index: int = 0
    task_description: str = ""
    total_tasks: int = 0
    completed_tasks: int = 0
    duration_seconds: float | None = None
    commit_hash: str | None = None
    branch: str | None = None
    pr_group: str | None = None

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.TASK_COMPLETED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus task completion data.
        """
        data = super().to_dict()
        data.update(
            {
                "task_index": self.task_index,
                "task_description": self.task_description,
                "total_tasks": self.total_tasks,
                "completed_tasks": self.completed_tasks,
                "duration_seconds": self.duration_seconds,
                "commit_hash": self.commit_hash,
                "branch": self.branch,
                "pr_group": self.pr_group,
            }
        )
        return data


@dataclass
class TaskFailedEvent(WebhookEvent):
    """Event emitted when a task fails with an error.

    Attributes:
        task_index: Zero-based index of the failed task.
        task_description: Human-readable description of the task.
        error_message: Description of the failure.
        error_type: Type/classification of the error (optional).
        duration_seconds: Time elapsed before failure (optional).
        branch: Git branch name (optional).
        pr_group: PR group name if task is part of a group (optional).
        recoverable: Whether the error is potentially recoverable.
    """

    task_index: int = 0
    task_description: str = ""
    error_message: str = ""
    error_type: str | None = None
    duration_seconds: float | None = None
    branch: str | None = None
    pr_group: str | None = None
    recoverable: bool = True

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.TASK_FAILED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus failure data.
        """
        data = super().to_dict()
        data.update(
            {
                "task_index": self.task_index,
                "task_description": self.task_description,
                "error_message": self.error_message,
                "error_type": self.error_type,
                "duration_seconds": self.duration_seconds,
                "branch": self.branch,
                "pr_group": self.pr_group,
                "recoverable": self.recoverable,
            }
        )
        return data


# =============================================================================
# Pull Request Events
# =============================================================================


@dataclass
class PRCreatedEvent(WebhookEvent):
    """Event emitted when a pull request is created.

    Attributes:
        pr_number: The pull request number.
        pr_url: URL to the pull request.
        pr_title: Title of the pull request.
        branch: Source branch name.
        base_branch: Target branch name.
        tasks_included: Number of tasks included in this PR.
        pr_group: PR group name (optional).
        repository: Repository name (owner/repo format, optional).
    """

    pr_number: int = 0
    pr_url: str = ""
    pr_title: str = ""
    branch: str = ""
    base_branch: str = "main"
    tasks_included: int = 0
    pr_group: str | None = None
    repository: str | None = None

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.PR_CREATED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus PR creation data.
        """
        data = super().to_dict()
        data.update(
            {
                "pr_number": self.pr_number,
                "pr_url": self.pr_url,
                "pr_title": self.pr_title,
                "branch": self.branch,
                "base_branch": self.base_branch,
                "tasks_included": self.tasks_included,
                "pr_group": self.pr_group,
                "repository": self.repository,
            }
        )
        return data


@dataclass
class PRMergedEvent(WebhookEvent):
    """Event emitted when a pull request is merged.

    Attributes:
        pr_number: The pull request number.
        pr_url: URL to the pull request.
        pr_title: Title of the pull request.
        branch: Source branch that was merged.
        base_branch: Target branch that received the merge.
        merge_commit_hash: The merge commit hash.
        merged_at: When the PR was merged (ISO 8601 format).
        pr_group: PR group name (optional).
        repository: Repository name (owner/repo format, optional).
        auto_merged: Whether this was an auto-merge.
    """

    pr_number: int = 0
    pr_url: str = ""
    pr_title: str = ""
    branch: str = ""
    base_branch: str = "main"
    merge_commit_hash: str | None = None
    merged_at: str | None = None
    pr_group: str | None = None
    repository: str | None = None
    auto_merged: bool = False

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.PR_MERGED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus PR merge data.
        """
        data = super().to_dict()
        data.update(
            {
                "pr_number": self.pr_number,
                "pr_url": self.pr_url,
                "pr_title": self.pr_title,
                "branch": self.branch,
                "base_branch": self.base_branch,
                "merge_commit_hash": self.merge_commit_hash,
                "merged_at": self.merged_at,
                "pr_group": self.pr_group,
                "repository": self.repository,
                "auto_merged": self.auto_merged,
            }
        )
        return data


# =============================================================================
# CI Events
# =============================================================================


@dataclass
class CIPassedEvent(WebhookEvent):
    """Event emitted when CI checks pass.

    Attributes:
        pr_number: The pull request number.
        pr_url: URL to the pull request.
        branch: Branch name being checked.
        check_name: Name of the CI check that passed (optional).
        check_url: URL to the CI check details (optional).
        duration_seconds: How long the CI check took (optional).
        repository: Repository name (owner/repo format, optional).
    """

    pr_number: int = 0
    pr_url: str = ""
    branch: str = ""
    check_name: str | None = None
    check_url: str | None = None
    duration_seconds: float | None = None
    repository: str | None = None

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.CI_PASSED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus CI pass data.
        """
        data = super().to_dict()
        data.update(
            {
                "pr_number": self.pr_number,
                "pr_url": self.pr_url,
                "branch": self.branch,
                "check_name": self.check_name,
                "check_url": self.check_url,
                "duration_seconds": self.duration_seconds,
                "repository": self.repository,
            }
        )
        return data


@dataclass
class CIFailedEvent(WebhookEvent):
    """Event emitted when CI checks fail.

    Attributes:
        pr_number: The pull request number.
        pr_url: URL to the pull request.
        branch: Branch name being checked.
        check_name: Name of the CI check that failed (optional).
        check_url: URL to the CI check details (optional).
        failure_reason: Description of why CI failed (optional).
        failure_log: Snippet of the failure log (optional).
        duration_seconds: How long the CI check took before failing (optional).
        repository: Repository name (owner/repo format, optional).
        recoverable: Whether the failure is potentially recoverable.
    """

    pr_number: int = 0
    pr_url: str = ""
    branch: str = ""
    check_name: str | None = None
    check_url: str | None = None
    failure_reason: str | None = None
    failure_log: str | None = None
    duration_seconds: float | None = None
    repository: str | None = None
    recoverable: bool = True

    def __post_init__(self) -> None:
        """Set event type and validate data."""
        self.event_type = EventType.CI_FAILED
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary.

        Returns:
            Dictionary with base event fields plus CI failure data.
        """
        data = super().to_dict()
        data.update(
            {
                "pr_number": self.pr_number,
                "pr_url": self.pr_url,
                "branch": self.branch,
                "check_name": self.check_name,
                "check_url": self.check_url,
                "failure_reason": self.failure_reason,
                "failure_log": self.failure_log,
                "duration_seconds": self.duration_seconds,
                "repository": self.repository,
                "recoverable": self.recoverable,
            }
        )
        return data


__all__ = [
    "TaskStartedEvent",
    "TaskCompletedEvent",
    "TaskFailedEvent",
    "PRCreatedEvent",
    "PRMergedEvent",
    "CIPassedEvent",
    "CIFailedEvent",
]
