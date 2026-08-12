"""Tests for usage-limit detection and the wait-and-retry query chokepoint.

Regression: when a subscription hit its session window, every session ended in
seconds with only "You've hit your session limit · resets 1pm (America/Bogota)"
as output. The loop read each one as an ordinary unfinished session, burned the
retry budget of task after task in under two minutes, checked four untouched
tasks off as complete, and blocked with a message that never named the cause.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from claude_task_master.core.usage_limit import (
    DEFAULT_WAIT_SEC,
    MAX_WAIT_SEC,
    MIN_WAIT_SEC,
    RESET_BUFFER_SEC,
    detect_usage_limit,
    run_query_riding_out_usage_limits,
    wait_for_reset,
    wait_seconds,
)

_MODULE = "claude_task_master.core.usage_limit"

#: The exact notice observed in the live run this guards against.
SESSION_LIMIT_LINE = "You've hit your session limit · resets 1pm (America/Bogota)"

_NOW_UTC = datetime(2026, 8, 12, 9, 52, tzinfo=UTC)


class TestDetectUsageLimit:
    def test_detects_the_observed_session_limit_line(self):
        notice = detect_usage_limit(SESSION_LIMIT_LINE, now=_NOW_UTC)
        assert notice is not None
        assert "session limit" in notice.message

    def test_detects_reached_your_limit_variant(self):
        assert detect_usage_limit("You've reached your usage limit.") is not None

    def test_detects_five_hour_limit_reached_variant(self):
        assert detect_usage_limit("5-hour limit reached ∙ resets 11pm") is not None

    def test_detects_api_429_body_with_epoch(self):
        epoch = int(_NOW_UTC.timestamp()) + 3600
        notice = detect_usage_limit(f"Claude AI usage limit reached|{epoch}", now=_NOW_UTC)
        assert notice is not None
        assert notice.reset_at is not None
        assert abs((notice.reset_at - _NOW_UTC).total_seconds() - 3600) < 2

    def test_ordinary_session_output_is_not_a_limit(self):
        assert detect_usage_limit("All tests pass. Commit abc123.\n\nTASK COMPLETE") is None

    def test_empty_and_none_are_not_limits(self):
        assert detect_usage_limit("") is None
        assert detect_usage_limit(None) is None

    def test_phrase_outside_the_tail_is_ignored(self):
        # A real session that merely quoted limit phrasing early on must not
        # be misread as refused — only the output's tail counts.
        output = SESSION_LIMIT_LINE + "\n" + ("x" * 2000) + "\nTASK COMPLETE"
        assert detect_usage_limit(output) is None


class TestResetParsing:
    def test_clock_reset_parses_in_stated_zone(self):
        notice = detect_usage_limit("session limit reached · resets 1pm (UTC)", now=_NOW_UTC)
        assert notice is not None
        assert notice.reset_at is not None
        assert notice.reset_at == _NOW_UTC.replace(hour=13, minute=0, second=0, microsecond=0)

    def test_reset_already_past_rolls_to_next_day(self):
        now = _NOW_UTC.replace(hour=14)
        notice = detect_usage_limit("session limit reached · resets 1pm (UTC)", now=now)
        assert notice is not None
        assert notice.reset_at is not None
        assert notice.reset_at.date() == (now + timedelta(days=1)).date()
        assert notice.reset_at.hour == 13

    def test_bare_hour_without_meridiem_or_minutes_is_ignored(self):
        notice = detect_usage_limit("You've hit your usage limit, resets 9", now=_NOW_UTC)
        assert notice is not None
        assert notice.reset_at is None

    def test_unknown_zone_name_still_yields_a_reset(self):
        notice = detect_usage_limit(
            "You've hit your session limit · resets 1pm (Not/AZone)", now=_NOW_UTC
        )
        assert notice is not None
        assert notice.reset_at is not None


class TestWaitSeconds:
    def test_wait_targets_the_stated_reset_plus_buffer(self):
        notice = detect_usage_limit("session limit reached · resets 1pm (UTC)", now=_NOW_UTC)
        assert notice is not None
        expected = (13 - 9) * 3600 - 52 * 60 + RESET_BUFFER_SEC
        assert wait_seconds(notice, now=_NOW_UTC) == expected

    def test_unparseable_reset_falls_back_to_default(self):
        notice = detect_usage_limit("You've reached your usage limit.")
        assert notice is not None
        assert wait_seconds(notice) == DEFAULT_WAIT_SEC

    def test_long_wait_is_capped(self):
        now = _NOW_UTC.replace(hour=14)
        notice = detect_usage_limit("session limit reached · resets 1pm (UTC)", now=now)
        assert notice is not None
        assert wait_seconds(notice, now=now) == MAX_WAIT_SEC

    def test_past_reset_still_waits_the_floor(self):
        epoch = int(_NOW_UTC.timestamp()) - 3600
        notice = detect_usage_limit(f"usage limit reached|{epoch}", now=_NOW_UTC)
        assert notice is not None
        assert wait_seconds(notice, now=_NOW_UTC) == MIN_WAIT_SEC

    def test_env_override_and_garbage_fallback(self, monkeypatch):
        notice = detect_usage_limit("You've reached your usage limit.")
        assert notice is not None
        monkeypatch.setenv("CLAUDETM_USAGE_LIMIT_DEFAULT_WAIT_SEC", "300")
        assert wait_seconds(notice) == 300
        monkeypatch.setenv("CLAUDETM_USAGE_LIMIT_DEFAULT_WAIT_SEC", "banana")
        assert wait_seconds(notice) == DEFAULT_WAIT_SEC
        monkeypatch.setenv("CLAUDETM_USAGE_LIMIT_DEFAULT_WAIT_SEC", "-5")
        assert wait_seconds(notice) == DEFAULT_WAIT_SEC


class TestWaitForReset:
    def _notice(self):
        notice = detect_usage_limit("You've reached your usage limit.")
        assert notice is not None
        return notice

    def test_completed_wait_returns_true(self):
        with (
            patch(f"{_MODULE}.interruptible_sleep", return_value=True),
            patch(
                "claude_task_master.core.key_listener.is_cancellation_requested",
                return_value=False,
            ),
            patch(f"{_MODULE}.console"),
        ):
            assert wait_for_reset(self._notice()) is True

    def test_shutdown_interrupts_the_wait(self):
        with (
            patch(f"{_MODULE}.interruptible_sleep", return_value=False),
            patch(
                "claude_task_master.core.key_listener.is_cancellation_requested",
                return_value=False,
            ),
            patch(f"{_MODULE}.console"),
        ):
            assert wait_for_reset(self._notice()) is False

    def test_escape_interrupts_the_wait(self):
        with (
            patch(f"{_MODULE}.interruptible_sleep", return_value=True),
            patch(
                "claude_task_master.core.key_listener.is_cancellation_requested",
                return_value=True,
            ),
            patch(f"{_MODULE}.console"),
        ):
            assert wait_for_reset(self._notice()) is False


class _FakeProcessor:
    """Terminal-result state driven by the fake runner below."""

    def __init__(self) -> None:
        self.last_result_is_error = False
        self.last_result_subtype: str | None = None
        self.resets = 0

    def reset_result_state(self) -> None:
        self.resets += 1
        self.last_result_is_error = False
        self.last_result_subtype = None


def _fake_query_run(script: list[tuple[str, bool]], processor: _FakeProcessor):
    """Build (start_query, runner) replaying (output, is_error) per call."""
    calls = {"n": 0}

    async def _coro() -> str:
        return ""  # pragma: no cover — closed unawaited by the fake runner

    def runner(coro) -> str:
        coro.close()
        output, is_error = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        processor.last_result_is_error = is_error
        return output

    return (lambda: _coro()), runner, calls


class TestRunQueryRidingOutUsageLimits:
    def test_clean_query_runs_once(self):
        processor = _FakeProcessor()
        start, runner, calls = _fake_query_run([("done", False)], processor)
        with patch(f"{_MODULE}.console"):
            result = run_query_riding_out_usage_limits(start, processor, runner)  # type: ignore[arg-type]
        assert result == "done"
        assert calls["n"] == 1
        assert processor.resets == 1

    def test_limit_refusal_waits_and_reruns(self):
        processor = _FakeProcessor()
        start, runner, calls = _fake_query_run(
            [(SESSION_LIMIT_LINE, True), ("real work done", False)], processor
        )
        with (
            patch(f"{_MODULE}.wait_for_reset", return_value=True) as mock_wait,
            patch(f"{_MODULE}.console"),
        ):
            result = run_query_riding_out_usage_limits(start, processor, runner)  # type: ignore[arg-type]
        assert result == "real work done"
        assert calls["n"] == 2
        assert mock_wait.call_count == 1
        # State was reset before the retry, so the refusal cannot leak into
        # the successful session's derived success.
        assert processor.resets == 2
        assert processor.last_result_is_error is False

    def test_interrupted_wait_hands_the_refusal_back(self):
        processor = _FakeProcessor()
        start, runner, calls = _fake_query_run([(SESSION_LIMIT_LINE, True)], processor)
        with (
            patch(f"{_MODULE}.wait_for_reset", return_value=False),
            patch(f"{_MODULE}.console"),
        ):
            result = run_query_riding_out_usage_limits(start, processor, runner)  # type: ignore[arg-type]
        assert result == SESSION_LIMIT_LINE
        assert calls["n"] == 1
        assert processor.last_result_is_error is True

    def test_ordinary_error_result_is_not_retried(self):
        processor = _FakeProcessor()
        start, runner, calls = _fake_query_run([("half-done work", True)], processor)
        with (
            patch(f"{_MODULE}.wait_for_reset") as mock_wait,
            patch(f"{_MODULE}.console"),
        ):
            result = run_query_riding_out_usage_limits(start, processor, runner)  # type: ignore[arg-type]
        assert result == "half-done work"
        assert calls["n"] == 1
        mock_wait.assert_not_called()

    def test_consecutive_wait_budget_bounds_the_loop(self, monkeypatch):
        monkeypatch.setenv("CLAUDETM_USAGE_LIMIT_MAX_WAITS", "2")
        processor = _FakeProcessor()
        start, runner, calls = _fake_query_run([(SESSION_LIMIT_LINE, True)], processor)
        with (
            patch(f"{_MODULE}.wait_for_reset", return_value=True) as mock_wait,
            patch(f"{_MODULE}.console"),
        ):
            result = run_query_riding_out_usage_limits(start, processor, runner)  # type: ignore[arg-type]
        assert result == SESSION_LIMIT_LINE
        assert mock_wait.call_count == 2
        assert calls["n"] == 3  # initial run + one rerun per completed wait

    def test_no_processor_returns_first_result(self):
        calls = {"n": 0}

        async def _coro() -> str:
            return ""  # pragma: no cover

        def runner(coro) -> str:
            coro.close()
            calls["n"] += 1
            return SESSION_LIMIT_LINE

        result = run_query_riding_out_usage_limits(lambda: _coro(), None, runner)
        assert result == SESSION_LIMIT_LINE
        assert calls["n"] == 1
