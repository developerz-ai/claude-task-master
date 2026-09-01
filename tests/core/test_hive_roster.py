"""Tests for the hive roster — the live view of a lead's worker team.

Failure cases first, because this module renders diagnostics for an unattended
run: a crash in the status display would take down a session that was otherwise
working, which is strictly worse than showing no status. So every entry point is
tested with an unknown id, a missing field and outright garbage before anything
is tested with well-formed input.

Time is injected, never slept on. The suite runs under ``--timeout=2`` with
several agents on the box, so a test that waits on a real clock is a flake; the
fake clock also makes "a worker has been running for four minutes" a one-line
setup instead of an impossibility.
"""

from __future__ import annotations

import math

import pytest

from claude_task_master.core.hive_roster import (
    DEFAULT_ROSTER_INTERVAL_SEC,
    MAX_ACTIVITY_CHARS,
    ROSTER_INTERVAL_ENV,
    HiveRoster,
    format_elapsed,
    format_tokens,
    roster_interval_sec,
)


class FakeClock:
    """A monotonic clock the test drives by hand."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def _default_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test against the default interval unless it says otherwise.

    The env var is process-wide, so a developer with it set would otherwise see
    a different suite than CI does.
    """
    monkeypatch.delenv(ROSTER_INTERVAL_ENV, raising=False)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def roster(clock: FakeClock) -> HiveRoster:
    return HiveRoster(clock=clock)


# =============================================================================
# roster_interval_sec - a typo must never end an unattended run
# =============================================================================


class TestRosterIntervalSec:
    def test_default_when_unset(self) -> None:
        assert roster_interval_sec() == DEFAULT_ROSTER_INTERVAL_SEC

    def test_default_value(self) -> None:
        assert DEFAULT_ROSTER_INTERVAL_SEC == 60

    def test_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "15")
        assert roster_interval_sec() == 15

    def test_whitespace_tolerated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "  30 ")
        assert roster_interval_sec() == 30

    def test_zero_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unlike hive's knob, 0 is meaningful here: turn the roster off."""
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "0")
        assert roster_interval_sec() == 0

    def test_negative_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "-5")
        assert roster_interval_sec() == DEFAULT_ROSTER_INTERVAL_SEC

    def test_garbage_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "often")
        assert roster_interval_sec() == DEFAULT_ROSTER_INTERVAL_SEC

    def test_empty_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "")
        assert roster_interval_sec() == DEFAULT_ROSTER_INTERVAL_SEC

    def test_float_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "2.5")
        assert roster_interval_sec() == DEFAULT_ROSTER_INTERVAL_SEC

    def test_env_read_at_call_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Not frozen at import: a test (or a run) may set it per-process."""
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "10")
        assert roster_interval_sec() == 10
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "20")
        assert roster_interval_sec() == 20


# =============================================================================
# format_elapsed - never negative, never absurd
# =============================================================================


class TestFormatElapsed:
    def test_negative_is_zero(self) -> None:
        """A clock that went backwards renders 0s, not a negative duration."""
        assert format_elapsed(-42.0) == "0s"

    def test_nan_is_zero(self) -> None:
        assert format_elapsed(math.nan) == "0s"

    def test_infinity_is_zero(self) -> None:
        assert format_elapsed(math.inf) == "0s"

    def test_garbage_is_zero(self) -> None:
        assert format_elapsed("later") == "0s"  # type: ignore[arg-type]

    def test_zero(self) -> None:
        assert format_elapsed(0) == "0s"

    def test_seconds(self) -> None:
        assert format_elapsed(47.9) == "47s"

    def test_just_under_a_minute(self) -> None:
        assert format_elapsed(59.999) == "59s"

    def test_exactly_a_minute(self) -> None:
        assert format_elapsed(60) == "1m 00s"

    def test_minutes_pad_seconds(self) -> None:
        assert format_elapsed(62) == "1m 02s"

    def test_minutes(self) -> None:
        assert format_elapsed(19 * 60 + 50) == "19m 50s"

    def test_just_under_an_hour(self) -> None:
        assert format_elapsed(3599) == "59m 59s"

    def test_exactly_an_hour(self) -> None:
        assert format_elapsed(3600) == "1h 00m"

    def test_hours_drop_seconds(self) -> None:
        assert format_elapsed(3600 + 4 * 60 + 59) == "1h 04m"

    def test_many_hours(self) -> None:
        assert format_elapsed(26 * 3600) == "26h 00m"


# =============================================================================
# format_tokens - a worker's cold start is six figures
# =============================================================================


class TestFormatTokens:
    def test_negative_is_zero(self) -> None:
        assert format_tokens(-1) == "0"

    def test_garbage_is_zero(self) -> None:
        assert format_tokens("many") == "0"  # type: ignore[arg-type]

    def test_none_is_zero(self) -> None:
        assert format_tokens(None) == "0"  # type: ignore[arg-type]

    def test_zero(self) -> None:
        assert format_tokens(0) == "0"

    def test_small(self) -> None:
        assert format_tokens(847) == "847"

    def test_just_under_a_thousand(self) -> None:
        assert format_tokens(999) == "999"

    def test_exactly_a_thousand(self) -> None:
        assert format_tokens(1000) == "1.0k"

    def test_thousands(self) -> None:
        assert format_tokens(410_249) == "410.2k"

    def test_rounding_never_yields_four_digit_k(self) -> None:
        """999_999 must not render as '1000.0k' and widen the column."""
        assert format_tokens(999_999) == "1.0M"

    def test_millions(self) -> None:
        assert format_tokens(1_240_000) == "1.2M"


# =============================================================================
# spawn / finish lifecycle
# =============================================================================


class TestLifecycle:
    def test_empty_roster_has_no_live_workers(self, roster: HiveRoster) -> None:
        assert roster.live_count == 0

    def test_spawn_counts_live(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.spawn("t2", "hive-worker", 1)
        assert roster.live_count == 2

    def test_finish_drops_out_of_live_count(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.spawn("t2", "hive-worker", 1)
        roster.finish("t1")
        assert roster.live_count == 1

    def test_finished_worker_still_rendered(self, roster: HiveRoster) -> None:
        """A returned worker's cost and outcome is exactly what a reader wants."""
        roster.spawn("t1", "hive-worker", 0)
        roster.finish("t1")
        assert any("hive-worker#1" in line for line in roster.render())

    def test_finish_freezes_elapsed(self, roster: HiveRoster, clock: FakeClock) -> None:
        roster.spawn("t1", "hive-worker", 0)
        clock.advance(62)
        roster.finish("t1")
        clock.advance(9999)
        assert any("1m 02s" in line for line in roster.render())

    def test_finish_is_idempotent(self, roster: HiveRoster, clock: FakeClock) -> None:
        roster.spawn("t1", "hive-worker", 0)
        clock.advance(62)
        roster.finish("t1")
        clock.advance(300)
        roster.finish("t1")
        assert any("1m 02s" in line for line in roster.render())

    def test_finish_unknown_id_does_not_raise(self, roster: HiveRoster) -> None:
        roster.finish("never-seen")
        assert roster.live_count == 0
        assert any("subagent#1" in line for line in roster.render())

    def test_error_finish_marked(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.finish("t1", is_error=True)
        row = next(line for line in roster.render() if "hive-worker#1" in line)
        assert row.lstrip().startswith("!")
        assert "failed" in row

    def test_clear_forgets_everything(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.clear()
        assert roster.live_count == 0
        assert roster.render() == []

    def test_default_clock_is_usable(self) -> None:
        """No injected clock: still works, without the test depending on time."""
        default = HiveRoster()
        default.spawn("t1", "hive-worker", 0)
        assert default.live_count == 1
        assert default.render()


class TestSpawnIdempotence:
    def test_respawn_does_not_restart_the_clock(self, roster: HiveRoster, clock: FakeClock) -> None:
        """A worker running for four minutes must not read as freshly started."""
        roster.spawn("t1", "hive-worker", 0)
        clock.advance(240)
        roster.spawn("t1", "hive-worker", 0)
        assert any("4m 00s" in line for line in roster.render())

    def test_respawn_does_not_zero_tokens(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage("t1", {"input_tokens": 5000, "output_tokens": 2000})
        roster.spawn("t1", "hive-worker", 0)
        row = next(line for line in roster.render() if "hive-worker#1" in line)
        assert "in 5.0k out 2.0k" in row

    def test_respawn_does_not_duplicate_the_row(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.spawn("t1", "hive-worker", 0)
        assert roster.live_count == 1
        assert len(roster.render()) == 2  # header + one row

    def test_respawn_does_not_revive_a_finished_worker(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.finish("t1")
        roster.spawn("t1", "hive-worker", 0)
        assert roster.live_count == 0

    def test_spawn_names_a_worker_adopted_earlier(self, roster: HiveRoster) -> None:
        """A worker that spoke before its dispatch was seen gets its real name."""
        roster.note_activity("t1", "reading the module")
        roster.spawn("t1", "backend-dev", 0)
        assert any("backend-dev#1" in line for line in roster.render())


# =============================================================================
# note_activity - unknown ids are adopted, text is normalised
# =============================================================================


class TestNoteActivity:
    def test_unknown_id_is_adopted_not_dropped(self, roster: HiveRoster) -> None:
        """A worker can speak before its spawning tool call is processed."""
        roster.note_activity("t9", "editing src/api/routes.py")
        assert roster.live_count == 1
        assert any("editing src/api/routes.py" in line for line in roster.render())

    def test_adopted_worker_gets_the_next_ordinal(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.note_activity("t9", "working")
        assert any("subagent#2" in line for line in roster.render())

    def test_newlines_collapsed(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.note_activity("t1", "running\n  the\tunit   tests\n")
        row = next(line for line in roster.render() if "hive-worker#1" in line)
        assert "running the unit tests" in row
        assert "\n" not in row

    def test_long_text_truncated(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.note_activity("t1", "x" * 200)
        row = next(line for line in roster.render() if "hive-worker#1" in line)
        assert "…" in row
        assert "x" * (MAX_ACTIVITY_CHARS + 1) not in row

    def test_exact_width_not_truncated(self, roster: HiveRoster) -> None:
        text = "y" * MAX_ACTIVITY_CHARS
        roster.spawn("t1", "hive-worker", 0)
        roster.note_activity("t1", text)
        assert any(text in line for line in roster.render())

    def test_blank_ignored(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.note_activity("t1", "running the unit tests")
        roster.note_activity("t1", "   \n  ")
        assert any("running the unit tests" in line for line in roster.render())

    def test_replaces_rather_than_accumulates(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.note_activity("t1", "reading files")
        roster.note_activity("t1", "writing tests")
        row = next(line for line in roster.render() if "hive-worker#1" in line)
        assert "writing tests" in row
        assert "reading files" not in row

    def test_non_string_does_not_raise(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.note_activity("t1", 42)  # type: ignore[arg-type]
        assert any("42" in line for line in roster.render())


# =============================================================================
# add_usage - both SDK shapes, garbage adds zero
# =============================================================================


class _AttrUsage:
    """An attribute-carrying usage payload (the older SDK shape)."""

    def __init__(self, **fields: int) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


class TestAddUsage:
    def _tokens(self, roster: HiveRoster) -> str:
        return next(line for line in roster.render() if "#1" in line)

    def test_none_does_not_raise(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage("t1", None)
        assert "in 0 out 0" in self._tokens(roster)

    def test_garbage_values_add_zero(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage("t1", {"input_tokens": "lots", "output_tokens": None})
        assert "in 0 out 0" in self._tokens(roster)

    def test_garbage_payload_adds_zero(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage("t1", "not a usage object")
        assert "in 0 out 0" in self._tokens(roster)

    def test_negative_values_add_zero(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage("t1", {"input_tokens": -5000, "output_tokens": -1})
        assert "in 0 out 0" in self._tokens(roster)

    def test_unknown_id_is_adopted(self, roster: HiveRoster) -> None:
        roster.add_usage("t9", {"input_tokens": 1000, "output_tokens": 1000})
        assert roster.live_count == 1
        assert "in 1.0k out 1.0k" in self._tokens(roster)

    def test_dict_shape(self, roster: HiveRoster) -> None:
        """A plain dict is what the Python SDK actually sends."""
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage("t1", {"input_tokens": 12_000, "output_tokens": 3400})
        assert "in 12.0k out 3.4k" in self._tokens(roster)

    def test_attribute_shape(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage("t1", _AttrUsage(input_tokens=12_000, output_tokens=3400))
        assert "in 12.0k out 3.4k" in self._tokens(roster)

    def test_missing_fields_add_zero(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage("t1", _AttrUsage(output_tokens=500))
        assert "in 0 out 500" in self._tokens(roster)

    def test_cache_tokens_counted_as_input(self, roster: HiveRoster) -> None:
        """A worker's cold start is mostly cache reads; omitting them lies."""
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage(
            "t1",
            {
                "input_tokens": 2000,
                "cache_read_input_tokens": 400_000,
                "cache_creation_input_tokens": 8000,
                "output_tokens": 1000,
            },
        )
        assert "in 410.0k out 1.0k" in self._tokens(roster)

    def test_cache_tokens_on_attribute_shape(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage("t1", _AttrUsage(input_tokens=1000, cache_read_input_tokens=9000))
        assert "in 10.0k out 0" in self._tokens(roster)

    def test_accumulates_across_calls(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage("t1", {"input_tokens": 1000, "output_tokens": 100})
        roster.add_usage("t1", {"input_tokens": 2000, "output_tokens": 200})
        roster.add_usage("t1", None)
        roster.add_usage("t1", {"cache_read_input_tokens": 7000})
        assert "in 10.0k out 300" in self._tokens(roster)

    def test_usage_after_finish_still_counted(self, roster: HiveRoster) -> None:
        """The result carrying the final usage arrives with the finish, or after."""
        roster.spawn("t1", "hive-worker", 0)
        roster.finish("t1")
        roster.add_usage("t1", {"input_tokens": 5000, "output_tokens": 500})
        assert "in 5.0k out 500" in self._tokens(roster)


# =============================================================================
# due() - the throttle
# =============================================================================


class TestDue:
    def test_empty_roster_is_never_due(self, roster: HiveRoster) -> None:
        """Polling before any worker exists must not spend the first window."""
        assert roster.due() is False

    def test_empty_roster_does_not_consume_the_interval(
        self, roster: HiveRoster, clock: FakeClock
    ) -> None:
        assert roster.due() is False
        clock.advance(1)
        roster.spawn("t1", "hive-worker", 0)
        assert roster.due() is True

    def test_first_call_with_workers_is_due(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        assert roster.due() is True

    def test_second_call_within_interval_is_not_due(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        assert roster.due() is True
        assert roster.due() is False

    def test_due_again_after_the_interval(self, roster: HiveRoster, clock: FakeClock) -> None:
        roster.spawn("t1", "hive-worker", 0)
        assert roster.due() is True
        clock.advance(DEFAULT_ROSTER_INTERVAL_SEC - 1)
        assert roster.due() is False
        clock.advance(1)
        assert roster.due() is True

    def test_force_ignores_the_interval(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        assert roster.due() is True
        assert roster.due(force=True) is True

    def test_force_resets_the_timer(self, roster: HiveRoster, clock: FakeClock) -> None:
        roster.spawn("t1", "hive-worker", 0)
        assert roster.due(force=True) is True
        clock.advance(DEFAULT_ROSTER_INTERVAL_SEC - 1)
        assert roster.due() is False

    def test_custom_interval(
        self, roster: HiveRoster, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "10")
        roster.spawn("t1", "hive-worker", 0)
        assert roster.due() is True
        clock.advance(10)
        assert roster.due() is True

    def test_zero_disables_due_even_with_force(
        self, roster: HiveRoster, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """'Off' that a caller can override is not off."""
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "0")
        roster.spawn("t1", "hive-worker", 0)
        assert roster.due() is False
        assert roster.due(force=True) is False

    def test_unparseable_interval_falls_back(
        self, roster: HiveRoster, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "sometimes")
        roster.spawn("t1", "hive-worker", 0)
        assert roster.due() is True
        clock.advance(DEFAULT_ROSTER_INTERVAL_SEC - 1)
        assert roster.due() is False
        clock.advance(1)
        assert roster.due() is True

    def test_clear_resets_the_timer(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        assert roster.due() is True
        roster.clear()
        roster.spawn("t2", "hive-worker", 0)
        assert roster.due() is True


# =============================================================================
# render() - plain text, aligned, empty when there is nothing to say
# =============================================================================


class TestRender:
    def test_empty_when_no_workers(self, roster: HiveRoster) -> None:
        assert roster.render() == []

    def test_empty_when_disabled(self, roster: HiveRoster, monkeypatch: pytest.MonkeyPatch) -> None:
        roster.spawn("t1", "hive-worker", 0)
        monkeypatch.setenv(ROSTER_INTERVAL_ENV, "0")
        assert roster.render() == []

    def test_no_ansi_escapes(self, roster: HiveRoster) -> None:
        """Colour policy lives in console; the roster returns plain text."""
        roster.spawn("t1", "hive-worker", 0)
        roster.note_activity("t1", "running the unit tests")
        roster.spawn("t2", "backend-dev", 1)
        roster.finish("t2", is_error=True)
        assert all("\x1b" not in line for line in roster.render())

    def test_no_emoji(self, roster: HiveRoster) -> None:
        """CLAUDE.md: no emoji anywhere in the printer. ASCII marks only."""
        roster.spawn("t1", "hive-worker", 0)
        roster.spawn("t2", "backend-dev", 1)
        roster.finish("t2")
        for line in roster.render():
            assert all(ord(ch) < 0x2100 for ch in line), line

    def test_header_counts_active_and_done(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.spawn("t2", "backend-dev", 1)
        roster.spawn("t3", "hive-worker", 2)
        roster.finish("t3")
        assert roster.render()[0] == "Hive: 2 workers active, 1 done"

    def test_header_singular(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        assert roster.render()[0] == "Hive: 1 worker active"

    def test_header_all_done(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.finish("t1")
        assert roster.render()[0] == "Hive: 1 done"

    def test_one_line_per_worker(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.spawn("t2", "hive-worker", 1)
        assert len(roster.render()) == 3  # header + 2 rows

    def test_rows_in_ordinal_order(self, roster: HiveRoster) -> None:
        roster.spawn("t2", "hive-worker", 1)
        roster.spawn("t1", "backend-dev", 0)
        rows = roster.render()[1:]
        assert "backend-dev#1" in rows[0]
        assert "hive-worker#2" in rows[1]

    def test_live_marker_and_placeholder_activity(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        row = roster.render()[1]
        assert row.lstrip().startswith("~")
        assert "starting" in row

    def test_columns_align_to_the_longest_label(self, roster: HiveRoster) -> None:
        """A long specialist name must not wreck the other columns."""
        roster.spawn("t1", "hive-worker", 0)
        roster.spawn("t2", "database-migration-specialist", 1)
        roster.note_activity("t1", "editing one")
        roster.note_activity("t2", "editing two")
        rows = roster.render()[1:]
        assert rows[0].index("editing one") == rows[1].index("editing two")

    def test_columns_align_across_differing_activities(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.spawn("t2", "hive-worker", 1)
        roster.note_activity("t1", "a")
        roster.note_activity("t2", "a much longer description of the work")
        rows = roster.render()[1:]
        assert rows[0].index(" in ") == rows[1].index(" in ")

    def test_no_trailing_whitespace(self, roster: HiveRoster) -> None:
        roster.spawn("t1", "hive-worker", 0)
        roster.add_usage("t1", {"input_tokens": 1000, "output_tokens": 100})
        assert all(line == line.rstrip() for line in roster.render())

    def test_full_block(self, roster: HiveRoster, clock: FakeClock) -> None:
        """The whole thing, as a reader would see it in a log."""
        roster.spawn("t1", "hive-worker", 0)
        roster.spawn("t2", "backend-dev", 1)
        roster.add_usage("t1", {"input_tokens": 410_200, "output_tokens": 8100})
        roster.add_usage("t2", {"input_tokens": 180_200, "output_tokens": 6000})
        clock.advance(62)
        roster.spawn("t3", "hive-worker", 2)
        roster.add_usage("t3", {"input_tokens": 40_000, "output_tokens": 2200})
        roster.finish("t3")
        clock.advance(190)
        roster.note_activity("t1", "running the unit tests")
        roster.note_activity("t2", "editing src/api/routes.py")
        assert roster.render() == [
            "Hive: 2 workers active, 1 done",
            "  ~ hive-worker#1   running the unit tests      4m 12s   in 410.2k out 8.1k",
            "  ~ backend-dev#2   editing src/api/routes.py   4m 12s   in 180.2k out 6.0k",
            "  + hive-worker#3   done                            0s   in  40.0k out 2.2k",
        ]
