"""Exception classes for the task runner."""

from __future__ import annotations


class TaskRunnerError(Exception):
    """Base exception for task runner errors."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class NoPlanFoundError(TaskRunnerError):
    """Raised when no plan file exists."""

    def __init__(self) -> None:
        super().__init__(
            "No plan found",
            "The plan file does not exist. Please run the planning phase first.",
        )


class NoTasksFoundError(TaskRunnerError):
    """Raised when the plan contains no tasks."""

    def __init__(self, plan_content: str | None = None):
        details = None
        if plan_content:
            preview = plan_content[:200] + "..." if len(plan_content) > 200 else plan_content
            details = f"Plan content preview: {preview}"
        super().__init__("No tasks found in plan", details)


class WorkSessionError(TaskRunnerError):
    """Raised when a work session fails."""

    def __init__(self, task_index: int, task_description: str, original_error: Exception):
        self.task_index = task_index
        self.task_description = task_description
        self.original_error = original_error
        super().__init__(
            f"Work session failed for task #{task_index + 1}: {task_description}",
            f"Error: {type(original_error).__name__}: {original_error}",
        )


__all__ = [
    "TaskRunnerError",
    "NoPlanFoundError",
    "NoTasksFoundError",
    "WorkSessionError",
]
