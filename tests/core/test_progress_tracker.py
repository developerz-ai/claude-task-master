"""Tests for progress tracker / stall detection."""

import time

import pytest

from claude_task_master.core.progress_tracker import (
    ExecutionTracker,
    ProgressState,
    SessionMetrics,
    TrackerConfig,
)


class TestSessionMetrics:
    """Tests for SessionMetrics."""

    def test_duration(self):
        """Test duration calculation."""
        metrics = SessionMetrics(
            session_id=1,
            task_index=0,
            task_description="Test task",
            start_time=100.0,
            end_time=110.0,
        )
        assert metrics.duration == 10.0

    def test_duration_ongoing(self):
        """Test duration for ongoing session."""
        metrics = SessionMetrics(
            session_id=1,
            task_index=0,
            task_description="Test task",
            start_time=time.time() - 5,
        )
        assert 4.9 < metrics.duration < 5.5

    def test_total_tokens(self):
        """Test total tokens calculation."""
        metrics = SessionMetrics(
            session_id=1,
            task_index=0,
            task_description="Test",
            tokens_input=100,
            tokens_output=50,
        )
        assert metrics.total_tokens == 150

    def test_estimated_cost(self):
        """Test cost estimation uses Opus 4 rates ($15/M input, $75/M output)."""
        metrics = SessionMetrics(
            session_id=1,
            task_index=0,
            task_description="Test",
            tokens_input=1_000_000,  # 1M input tokens
            tokens_output=100_000,  # 100K output tokens
        )
        # $15/M input + $75/M output = $15 + $7.5 = $22.5
        assert metrics.estimated_cost == pytest.approx(22.5, rel=0.01)

    def test_estimated_cost_opus_rates(self):
        """Test cost estimation uses Opus 4 rates ($15/M input, $75/M output)."""
        metrics = SessionMetrics(
            session_id=1,
            task_index=0,
            task_description="Test",
            tokens_input=1_000_000,  # 1M input tokens
            tokens_output=1_000_000,  # 1M output tokens
        )
        # $15/M input + $75/M output = $15 + $75 = $90
        assert metrics.estimated_cost == pytest.approx(90.0, rel=0.01)


class TestTrackerConfig:
    """Tests for TrackerConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = TrackerConfig.default()
        assert config.stall_threshold_seconds == 300.0
        assert config.max_same_task_attempts == 3

    def test_strict_config(self):
        """Test strict configuration."""
        config = TrackerConfig.strict()
        assert config.stall_threshold_seconds == 120.0
        assert config.max_same_task_attempts == 2


class TestExecutionTracker:
    """Tests for ExecutionTracker."""

    def test_start_session(self):
        """Test starting a session."""
        tracker = ExecutionTracker()
        tracker.start_session(
            session_id=1,
            task_index=0,
            task_description="Test task",
        )

        assert tracker._current_session is not None
        assert tracker._current_session.session_id == 1
        assert tracker._task_attempts[0] == 1

    def test_end_session(self):
        """Test ending a session."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")

        metrics = tracker.end_session(outcome="success")

        assert metrics is not None
        assert metrics.outcome == "success"
        assert tracker._current_session is None
        assert len(tracker._sessions) == 1

    def test_record_api_call(self):
        """Test recording API call."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")

        tracker.record_api_call(tokens_in=100, tokens_out=50)

        assert tracker._current_session is not None
        assert tracker._current_session.api_calls == 1
        assert tracker._current_session.tokens_input == 100
        assert tracker._current_session.tokens_output == 50

    def test_record_tool_call(self):
        """Test recording tool call."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")

        tracker.record_tool_call("Read")

        assert tracker._current_session is not None
        assert tracker._current_session.tool_calls == 1

    def test_record_error(self):
        """Test recording error."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")

        tracker.record_error()

        assert tracker._current_session is not None
        assert tracker._current_session.errors == 1

    def test_check_progress_healthy(self):
        """Test checking healthy progress."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")

        state = tracker.check_progress()

        assert state == ProgressState.HEALTHY

    def test_check_progress_loop_detected(self):
        """Test loop detection."""
        config = TrackerConfig(max_same_task_attempts=2)
        tracker = ExecutionTracker(config=config)

        # Same task 3 times
        for i in range(3):
            tracker.start_session(i, 0, "Test")
            tracker.end_session()

        tracker.start_session(4, 0, "Test")
        state = tracker.check_progress()

        assert state == ProgressState.LOOP_DETECTED

    def test_check_progress_stalled(self):
        """Test stall detection."""
        config = TrackerConfig(stall_threshold_seconds=0.01)
        tracker = ExecutionTracker(config=config)
        tracker.start_session(1, 0, "Test")

        # Wait for stall
        time.sleep(0.02)

        state = tracker.check_progress()

        assert state == ProgressState.STALLED

    def test_check_progress_slow(self):
        """Test slow progress detection."""
        config = TrackerConfig(slow_threshold_seconds=0.01, stall_threshold_seconds=100)
        tracker = ExecutionTracker(config=config)
        tracker.start_session(1, 0, "Test")

        time.sleep(0.02)
        # Record activity to avoid stall
        tracker.record_api_call()

        state = tracker.check_progress()

        assert state == ProgressState.SLOW

    def test_check_progress_regressing(self):
        """Test regression detection."""
        tracker = ExecutionTracker()

        # Progress forward
        tracker.start_session(1, 5, "Task 5")
        tracker.record_task_progress(5)
        tracker.end_session()

        # Start session with earlier task
        tracker.start_session(2, 3, "Task 3")

        state = tracker.check_progress()

        assert state == ProgressState.REGRESSING

    def test_get_diagnostics(self):
        """Test getting diagnostics."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")

        diagnostics = tracker.get_diagnostics()

        assert diagnostics["current_session"] is not None
        assert diagnostics["total_sessions"] == 0
        assert diagnostics["progress_state"] == "healthy"

    def test_get_summary(self):
        """Test getting summary."""
        tracker = ExecutionTracker()

        # Complete a few sessions
        for i in range(3):
            tracker.start_session(i, i, f"Task {i}")
            tracker.record_api_call(tokens_in=100, tokens_out=50)
            tracker.end_session(outcome="success")

        summary = tracker.get_summary()

        assert summary["total_sessions"] == 3
        assert summary["total_tokens"] == 450
        assert summary["success_rate"] == 100.0

    def test_get_summary_empty(self):
        """Test summary with no sessions."""
        tracker = ExecutionTracker()
        summary = tracker.get_summary()

        assert summary["total_sessions"] == 0
        assert summary["success_rate"] == 0

    def test_should_abort_loop(self):
        """Test abort on loop detection."""
        config = TrackerConfig(max_same_task_attempts=1)
        tracker = ExecutionTracker(config=config)

        tracker.start_session(1, 0, "Test")
        tracker.end_session()
        tracker.start_session(2, 0, "Test")

        should_abort, reason = tracker.should_abort()

        assert should_abort
        assert "Loop detected" in reason

    def test_should_abort_stall(self):
        """Test abort on stall."""
        config = TrackerConfig(stall_threshold_seconds=0.01)
        tracker = ExecutionTracker(config=config)
        tracker.start_session(1, 0, "Test")

        time.sleep(0.02)

        should_abort, reason = tracker.should_abort()

        assert should_abort
        assert "Stalled" in reason

    def test_should_not_abort_healthy(self):
        """Test no abort when healthy."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")

        should_abort, reason = tracker.should_abort()

        assert not should_abort
        assert reason == ""

    def test_get_cost_report(self):
        """Test cost report generation."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")
        tracker.record_api_call(tokens_in=1000, tokens_out=500)
        tracker.end_session(outcome="success")

        report = tracker.get_cost_report()

        assert "Cost Report" in report
        assert "Total Sessions: 1" in report

    def test_reset(self):
        """Test resetting tracker."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")
        tracker.end_session()

        tracker.reset()

        assert len(tracker._sessions) == 0
        assert len(tracker._task_attempts) == 0

    def test_check_progress_loop_detected_without_active_session(self):
        """Test loop detection fires after the session has ended."""
        config = TrackerConfig(max_same_task_attempts=2)
        tracker = ExecutionTracker(config=config)

        # Same task 3 times, exceeding max_same_task_attempts
        for i in range(3):
            tracker.start_session(i, 0, "Test")
            tracker.end_session()

        # Record the last known task so the safety net works between sessions
        tracker.record_task_progress(0)

        assert tracker._current_session is None
        state = tracker.check_progress()

        assert state == ProgressState.LOOP_DETECTED

    def test_should_abort_loop_detected_without_active_session(self):
        """Test abort on loop detection after the session has ended."""
        config = TrackerConfig(max_same_task_attempts=2)
        tracker = ExecutionTracker(config=config)

        for i in range(3):
            tracker.start_session(i, 0, "Test")
            tracker.end_session()

        tracker.record_task_progress(0)

        assert tracker._current_session is None
        should_abort, reason = tracker.should_abort()

        assert should_abort
        assert "loop" in reason.lower()

    def test_check_progress_stalled_without_active_session(self, monkeypatch):
        """Test stall detection fires without an active session."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")
        tracker.end_session()

        monkeypatch.setattr(tracker, "_last_progress_time", time.time() - 10000.0)

        assert tracker._current_session is None
        state = tracker.check_progress()

        assert state == ProgressState.STALLED

    def test_check_progress_healthy_without_active_session(self):
        """Test healthy state between sessions with recent progress."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")
        tracker.record_task_progress(0)
        tracker.end_session()

        assert tracker._current_session is None
        state = tracker.check_progress()

        assert state == ProgressState.HEALTHY

    def test_check_progress_stalled_on_fresh_tracker_without_session(self, monkeypatch):
        """Test stall detection with no session ever started."""
        tracker = ExecutionTracker()

        monkeypatch.setattr(tracker, "_last_progress_time", time.time() - 10000.0)

        assert tracker._current_session is None
        state = tracker.check_progress()

        assert state == ProgressState.STALLED

    def test_should_abort_stalled_without_active_session(self, monkeypatch):
        """Test abort on stall without an active session."""
        tracker = ExecutionTracker()
        tracker.start_session(1, 0, "Test")
        tracker.end_session()

        monkeypatch.setattr(tracker, "_last_progress_time", time.time() - 10000.0)

        should_abort, _reason = tracker.should_abort()

        assert should_abort

    def test_should_abort_max_duration_exceeded(self, monkeypatch):
        """Test abort reason when the hard session timeout is exceeded."""
        config = TrackerConfig(
            stall_threshold_seconds=10000.0,
            slow_threshold_seconds=60.0,
            max_session_duration=120.0,
        )
        tracker = ExecutionTracker(config=config)
        tracker.start_session(1, 0, "Test")

        session = tracker._current_session
        assert session is not None
        monkeypatch.setattr(session, "start_time", time.time() - 200.0)

        should_abort, reason = tracker.should_abort()

        assert should_abort
        assert "Stalled" in reason

    def test_check_progress_max_duration_exceeded_returns_stalled(self, monkeypatch):
        """Test max_session_duration takes precedence over slow threshold."""
        config = TrackerConfig(
            stall_threshold_seconds=10000.0,
            slow_threshold_seconds=60.0,
            max_session_duration=120.0,
        )
        tracker = ExecutionTracker(config=config)
        tracker.start_session(1, 0, "Test")

        session = tracker._current_session
        assert session is not None
        # Duration exceeds both slow_threshold and max_session_duration, but
        # recent activity keeps it under the inactivity stall threshold.
        monkeypatch.setattr(session, "start_time", time.time() - 200.0)

        state = tracker.check_progress()

        assert state == ProgressState.STALLED

    def test_check_progress_under_all_thresholds_healthy(self):
        """Test healthy state when session is under all thresholds."""
        config = TrackerConfig(
            stall_threshold_seconds=1000.0,
            slow_threshold_seconds=100.0,
            max_session_duration=500.0,
        )
        tracker = ExecutionTracker(config=config)
        tracker.start_session(1, 0, "Test")

        state = tracker.check_progress()

        assert state == ProgressState.HEALTHY

    def test_check_progress_only_slow_threshold_exceeded_slow(self, monkeypatch):
        """Test slow state when only slow_threshold_seconds is exceeded."""
        config = TrackerConfig(
            stall_threshold_seconds=10000.0,
            slow_threshold_seconds=60.0,
            max_session_duration=1000.0,
        )
        tracker = ExecutionTracker(config=config)
        tracker.start_session(1, 0, "Test")

        session = tracker._current_session
        assert session is not None
        # Recent activity, duration past slow threshold but under max duration.
        monkeypatch.setattr(session, "start_time", time.time() - 100.0)

        state = tracker.check_progress()

        assert state == ProgressState.SLOW
