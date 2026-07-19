"""Orchestrator exception classes — extracted from orchestrator.py."""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base exception for all orchestrator-related errors."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class StateRecoveryError(OrchestratorError):
    """Raised when state recovery fails."""

    def __init__(self, reason: str, original_error: Exception | None = None):
        self.original_error = original_error
        details = f"Reason: {reason}"
        if original_error:
            details += f" | Original error: {type(original_error).__name__}: {original_error}"
        super().__init__("Failed to recover orchestrator state", details)


class MaxSessionsReachedError(OrchestratorError):
    """Raised when max sessions limit is reached."""

    def __init__(self, max_sessions: int, current_session: int):
        self.max_sessions = max_sessions
        self.current_session = current_session
        super().__init__(
            f"Max sessions ({max_sessions}) reached",
            f"Currently at session {current_session}. Consider increasing max_sessions.",
        )
