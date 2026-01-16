"""Progress Tracker for stall/deadlock detection and cost tracking.

Monitors task execution to detect stalls, infinite loops, and tracks
resource usage (tokens, API costs) for observability.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProgressState(Enum):
    """States indicating progress health."""

    HEALTHY = "healthy"  # Making normal progress
    SLOW = "slow"  # Progress slower than expected
    STALLED = "stalled"  # No progress for extended period
    LOOP_DETECTED = "loop_detected"  # Same task repeated
    REGRESSING = "regressing"  # Going backwards


@dataclass
class SessionMetrics:
    """Metrics for a single session."""

    session_id: int
    task_index: int
    task_description: str
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    api_calls: int = 0
    tool_calls: int = 0
    errors: int = 0
    outcome: str = "unknown"  # success, failure, cancelled

    @property
    def duration(self) -> float:
        """Get session duration in seconds."""
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def total_tokens(self) -> int:
        """Get total tokens used."""
        return self.tokens_input + self.tokens_output

    @property
    def estimated_cost(self) -> float:
        """Estimate cost in USD (approximate Claude pricing)."""
        # Approximate pricing: $3/M input, $15/M output for Opus
        input_cost = (self.tokens_input / 1_000_000) * 3.0
        output_cost = (self.tokens_output / 1_000_000) * 15.0
        return input_cost + output_cost


@dataclass
class TrackerConfig:
    """Configuration for progress tracking."""

    stall_threshold_seconds: float = 300.0  # 5 minutes without progress
    slow_threshold_seconds: float = 120.0  # 2 minutes per task is slow
    max_same_task_attempts: int = 3  # Max times to retry same task
    max_session_duration: float = 1800.0  # 30 minutes max per session
    enable_cost_tracking: bool = True

    @classmethod
    def default(cls) -> TrackerConfig:
        """Default configuration."""
        return cls()

    @classmethod
    def strict(cls) -> TrackerConfig:
        """Strict configuration - detect issues faster."""
        return cls(
            stall_threshold_seconds=120.0,
            slow_threshold_seconds=60.0,
            max_same_task_attempts=2,
            max_session_duration=900.0,
        )


@dataclass
class ExecutionTracker:
    """Track progress and detect stalls/deadlocks.

    Features:
    - Detect stalled tasks (no progress for too long)
    - Detect infinite loops (same task repeated)
    - Track token usage and costs
    - Provide progress estimates

    Usage:
        tracker = ProgressTracker()

        # Start tracking a session
        tracker.start_session(session_id=1, task_index=0, task="Fix bug")

        # Update metrics during session
        tracker.record_api_call(tokens_in=1000, tokens_out=500)
        tracker.record_tool_call("Read")

        # End session
        tracker.end_session(outcome="success")

        # Check for issues
        state = tracker.check_progress()
        if state != ProgressState.HEALTHY:
            handle_issue(state)
    """

    config: TrackerConfig = field(default_factory=TrackerConfig.default)
    _sessions: list[SessionMetrics] = field(default_factory=list)
    _current_session: SessionMetrics | None = field(default=None, init=False)
    _task_attempts: dict[int, int] = field(default_factory=dict)
    _last_progress_time: float = field(default_factory=time.time)
    _last_task_index: int = field(default=-1, init=False)

    def start_session(
        self,
        session_id: int,
        task_index: int,
        task_description: str,
    ) -> None:
        """Start tracking a new session.

        Args:
            session_id: Unique session identifier.
            task_index: Current task index being worked on.
            task_description: Description of the task.
        """
        # End any existing session
        if self._current_session:
            self.end_session(outcome="interrupted")

        self._current_session = SessionMetrics(
            session_id=session_id,
            task_index=task_index,
            task_description=task_description,
        )

        # Track task attempts
        if task_index in self._task_attempts:
            self._task_attempts[task_index] += 1
        else:
            self._task_attempts[task_index] = 1

        self._last_progress_time = time.time()

    def end_session(self, outcome: str = "completed") -> SessionMetrics | None:
        """End the current session.

        Args:
            outcome: Session outcome (success, failure, cancelled, etc.)

        Returns:
            The completed session metrics, or None if no session.
        """
        if not self._current_session:
            return None

        self._current_session.end_time = time.time()
        self._current_session.outcome = outcome
        self._sessions.append(self._current_session)

        metrics = self._current_session
        self._current_session = None
        return metrics

    def record_api_call(
        self,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        """Record an API call with token usage.

        Args:
            tokens_in: Input tokens used.
            tokens_out: Output tokens generated.
        """
        if self._current_session:
            self._current_session.api_calls += 1
            self._current_session.tokens_input += tokens_in
            self._current_session.tokens_output += tokens_out
            self._last_progress_time = time.time()

    def record_tool_call(self, tool_name: str) -> None:
        """Record a tool call.

        Args:
            tool_name: Name of the tool called.
        """
        if self._current_session:
            self._current_session.tool_calls += 1
            self._last_progress_time = time.time()

    def record_error(self) -> None:
        """Record an error in the current session."""
        if self._current_session:
            self._current_session.errors += 1

    def record_task_progress(self, task_index: int) -> None:
        """Record progress to a new task.

        Args:
            task_index: The task index we progressed to.
        """
        self._last_task_index = task_index
        self._last_progress_time = time.time()

    def check_progress(self) -> ProgressState:
        """Check current progress state.

        Returns:
            Current progress state indicating health.
        """
        if not self._current_session:
            return ProgressState.HEALTHY

        task_index = self._current_session.task_index
        duration = self._current_session.duration
        time_since_progress = time.time() - self._last_progress_time

        # Check for loop detection (same task too many times)
        attempts = self._task_attempts.get(task_index, 0)
        if attempts > self.config.max_same_task_attempts:
            return ProgressState.LOOP_DETECTED

        # Check for regression (going backwards)
        if task_index < self._last_task_index:
            return ProgressState.REGRESSING

        # Check for stall (no progress for too long)
        if time_since_progress > self.config.stall_threshold_seconds:
            return ProgressState.STALLED

        # Check for slow progress
        if duration > self.config.slow_threshold_seconds:
            return ProgressState.SLOW

        # Check for session timeout
        if duration > self.config.max_session_duration:
            return ProgressState.STALLED

        return ProgressState.HEALTHY

    def get_diagnostics(self) -> dict[str, Any]:
        """Get diagnostic information for debugging.

        Returns:
            Dictionary with diagnostic data.
        """
        current = self._current_session

        return {
            "current_session": {
                "session_id": current.session_id if current else None,
                "task_index": current.task_index if current else None,
                "duration": current.duration if current else 0,
                "api_calls": current.api_calls if current else 0,
                "tool_calls": current.tool_calls if current else 0,
                "errors": current.errors if current else 0,
            }
            if current
            else None,
            "total_sessions": len(self._sessions),
            "task_attempts": dict(self._task_attempts),
            "progress_state": self.check_progress().value,
            "time_since_progress": time.time() - self._last_progress_time,
            "last_task_index": self._last_task_index,
        }

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics across all sessions.

        Returns:
            Dictionary with summary statistics.
        """
        if not self._sessions:
            return {
                "total_sessions": 0,
                "total_duration": 0,
                "total_tokens": 0,
                "total_cost": 0,
                "avg_session_duration": 0,
                "success_rate": 0,
            }

        total_duration = sum(s.duration for s in self._sessions)
        total_tokens = sum(s.total_tokens for s in self._sessions)
        total_cost = sum(s.estimated_cost for s in self._sessions)
        successes = sum(1 for s in self._sessions if s.outcome == "success")

        return {
            "total_sessions": len(self._sessions),
            "total_duration": total_duration,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "avg_session_duration": total_duration / len(self._sessions),
            "success_rate": successes / len(self._sessions) * 100,
            "total_api_calls": sum(s.api_calls for s in self._sessions),
            "total_tool_calls": sum(s.tool_calls for s in self._sessions),
            "total_errors": sum(s.errors for s in self._sessions),
        }

    def should_abort(self) -> tuple[bool, str]:
        """Check if execution should be aborted due to issues.

        Returns:
            Tuple of (should_abort, reason).
        """
        state = self.check_progress()

        if state == ProgressState.LOOP_DETECTED:
            task_idx = self._current_session.task_index if self._current_session else -1
            attempts = self._task_attempts.get(task_idx, 0)
            return (
                True,
                f"Loop detected: task {task_idx} attempted {attempts} times",
            )

        if state == ProgressState.STALLED:
            duration = time.time() - self._last_progress_time
            return (
                True,
                f"Stalled: no progress for {duration:.0f} seconds",
            )

        return (False, "")

    def get_cost_report(self) -> str:
        """Generate a cost report.

        Returns:
            Formatted cost report string.
        """
        summary = self.get_summary()
        lines = [
            "=== Cost Report ===",
            f"Total Sessions: {summary['total_sessions']}",
            f"Total Duration: {summary['total_duration']:.1f}s",
            f"Total Tokens: {summary['total_tokens']:,}",
            f"Estimated Cost: ${summary['total_cost']:.4f}",
            f"Success Rate: {summary['success_rate']:.1f}%",
            "",
            "=== Breakdown ===",
            f"API Calls: {summary.get('total_api_calls', 0)}",
            f"Tool Calls: {summary.get('total_tool_calls', 0)}",
            f"Errors: {summary.get('total_errors', 0)}",
        ]
        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all tracking data."""
        self._sessions.clear()
        self._current_session = None
        self._task_attempts.clear()
        self._last_progress_time = time.time()
        self._last_task_index = -1
