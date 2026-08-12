"""Usage-limit detection — a refused session is an account condition, not a task failure.

When a Claude subscription exhausts its session/usage window, the CLI answers
every query instantly with a notice like::

    You've hit your session limit · resets 1pm (America/Bogota)

and the SDK reports the terminal result as an error. Nothing about the *task*
failed — the whole account is refused until the stated reset — so treating the
session like an ordinary cut-off is how a live run once burned every retry
budget in ninety seconds, checked four untouched tasks off as complete, and
blocked with a message that never mentioned the limit.

The pieces:

- :func:`detect_usage_limit` recognizes the notice in a session's output
  (scanning only the tail, so a long real session that merely *mentions*
  limits early on is not misread).
- :func:`run_query_riding_out_usage_limits` is the chokepoint the agent phase
  layer routes every query through: a refused query waits until the stated
  reset (interruptible) and re-runs, so no caller ever has to know the limit
  happened. Bounded by ``CLAUDETM_USAGE_LIMIT_MAX_WAITS`` consecutive waits.
- The working stage keeps its own safety net (``loop_working_stage``): a
  refused session that *does* leak through — an interrupted wait, an exhausted
  wait budget — is never charged to the task's retry budget and never checked
  off.

Env overrides (anything unset, unparseable or ``<= 0`` falls back — a typo in
an env var must never change a run's semantics):

- ``CLAUDETM_USAGE_LIMIT_DEFAULT_WAIT_SEC`` (1800): wait when the notice
  carries no parseable reset time.
- ``CLAUDETM_USAGE_LIMIT_MAX_WAIT_SEC`` (21600): cap on a single wait, so a
  misparsed reset time cannot sleep a run for a week.
- ``CLAUDETM_USAGE_LIMIT_MAX_WAITS`` (48): consecutive wait-and-retry rounds
  per query before giving up and handing the refused result to the caller.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from . import console
from .shutdown import interruptible_sleep

if TYPE_CHECKING:
    from .agent_message import MessageProcessor

#: Only the tail of a session's output is scanned. A refused session's whole
#: output IS the notice; a real session that discusses usage limits mid-way
#: (claudetm working on claudetm, say) must not be misread as refused.
TAIL_SCAN_CHARS = 1000

#: Wait when the notice gives no parseable reset time. Polling again is one
#: instantly-refused query, so a modest interval costs almost nothing.
DEFAULT_WAIT_SEC = 30 * 60

#: Cap on a single wait — protection against a misparsed reset time, not a
#: statement about how long limits last. Longer limits simply wait again.
MAX_WAIT_SEC = 6 * 60 * 60

#: Padding past the stated reset, since "resets 1pm" is minute-granular.
RESET_BUFFER_SEC = 120

#: Floor so a reset time in the immediate past still backs off briefly.
MIN_WAIT_SEC = 60

#: Consecutive wait-and-retry rounds per query. 48 rounds outlasts a weekly
#: window even on the default 30-minute fallback cadence; it exists so a
#: false-positive detection cannot wait literally forever.
DEFAULT_MAX_CONSECUTIVE_WAITS = 48

# The phrasings Claude Code / the API use for an exhausted plan window:
#   "You've hit your session limit · resets 1pm (America/Bogota)"
#   "You've reached your usage limit."
#   "5-hour limit reached ∙ resets 11pm"
#   "Claude AI usage limit reached|1755021600"   (API 429 body, epoch attached)
_LIMIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"you'?ve hit your[^.\n]{0,40}?\blimit\b", re.IGNORECASE),
    re.compile(r"you'?ve reached your[^.\n]{0,40}?\blimit\b", re.IGNORECASE),
    re.compile(
        r"\b(?:session|usage|weekly|monthly|5[ -]hour)\b[^.\n]{0,20}?\blimit reached\b",
        re.IGNORECASE,
    ),
    re.compile(r"claude (?:ai )?usage limit reached", re.IGNORECASE),
)

# "resets 1pm (America/Bogota)", "resets at 1:30pm", "resets 13:00". Minutes or
# a meridiem is required — a bare "resets 9" is too ambiguous to act on.
_RESET_CLOCK_RE = re.compile(
    r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b(?:\s*\(([^)]{1,64})\))?",
    re.IGNORECASE,
)
# API 429 body: "Claude AI usage limit reached|<epoch seconds or millis>".
_RESET_EPOCH_RE = re.compile(r"limit reached\|(\d{10,13})\b", re.IGNORECASE)


@dataclass(frozen=True)
class UsageLimitNotice:
    """A recognized usage-limit refusal.

    Attributes:
        message: The matched notice line, for logging.
        reset_at: Timezone-aware moment the limit lifts, when parseable.
    """

    message: str
    reset_at: datetime | None


def _env_positive_number(name: str, default: float) -> float:
    """Read a positive number from the environment, falling back on garbage."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _tzinfo_for(name: str | None) -> Any:
    """Resolve a parenthesized zone name ("America/Bogota") to a tzinfo.

    Falls back to the machine's local zone — the CLI prints the reset in the
    user's configured zone, which on the same machine is usually local anyway.
    """
    if name:
        try:
            from zoneinfo import ZoneInfo  # noqa: PLC0415 — stdlib, cheap

            return ZoneInfo(name.strip())
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo


def _parse_reset_at(text: str, now: datetime) -> datetime | None:
    """Best-effort parse of the notice's reset moment.

    Args:
        text: The output tail the notice was found in.
        now: Timezone-aware current time (injected for testability).

    Returns:
        A timezone-aware datetime, or None when nothing trustworthy parses.
    """
    epoch_match = _RESET_EPOCH_RE.search(text)
    if epoch_match:
        raw = int(epoch_match.group(1))
        if raw >= 10**12:  # milliseconds
            raw //= 1000
        try:
            return datetime.fromtimestamp(raw, tz=now.tzinfo)
        except (OverflowError, OSError, ValueError):
            return None

    clock_match = _RESET_CLOCK_RE.search(text)
    if not clock_match:
        return None
    hour_raw, minute_raw, meridiem, zone_name = clock_match.groups()
    if not minute_raw and not meridiem:
        return None  # "resets 9" — too ambiguous to schedule against
    hour = int(hour_raw)
    minute = int(minute_raw) if minute_raw else 0
    if meridiem:
        meridiem = meridiem.lower()
        if hour > 12:
            return None
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
    if hour > 23 or minute > 59:
        return None

    tz = _tzinfo_for(zone_name)
    local_now = now.astimezone(tz)
    target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local_now:
        target += timedelta(days=1)
    return target


def detect_usage_limit(output: str | None, now: datetime | None = None) -> UsageLimitNotice | None:
    """Recognize a usage-limit refusal in a session's output.

    Only the output's tail is scanned (see :data:`TAIL_SCAN_CHARS`): a refused
    session's entire output is the notice, while a genuine session that quotes
    limit phrasing mid-way must not be misread.

    Args:
        output: The session's accumulated text, or None.
        now: Timezone-aware current time (injected for testability).

    Returns:
        The recognized notice, or None.
    """
    # The isinstance check is load-bearing, not decoration: callers hand in
    # ``getattr(task_runner, "last_session_output", ...)``, and tests build
    # that runner as a MagicMock whose auto-created attribute is not a string.
    if not isinstance(output, str) or not output:
        return None
    tail = output[-TAIL_SCAN_CHARS:]
    for pattern in _LIMIT_PATTERNS:
        match = pattern.search(tail)
        if match is None:
            continue
        line = next(
            (ln.strip() for ln in tail.splitlines() if pattern.search(ln)),
            match.group(0),
        )
        moment = now or datetime.now().astimezone()
        return UsageLimitNotice(message=line, reset_at=_parse_reset_at(tail, moment))
    return None


def wait_seconds(notice: UsageLimitNotice, now: datetime | None = None) -> float:
    """How long to wait before retrying a limit-refused query.

    Args:
        notice: The recognized limit notice.
        now: Timezone-aware current time (injected for testability).

    Returns:
        Seconds to wait, clamped to [MIN_WAIT_SEC, max-wait].
    """
    max_wait = _env_positive_number("CLAUDETM_USAGE_LIMIT_MAX_WAIT_SEC", MAX_WAIT_SEC)
    if notice.reset_at is None:
        default = _env_positive_number("CLAUDETM_USAGE_LIMIT_DEFAULT_WAIT_SEC", DEFAULT_WAIT_SEC)
        return min(max(default, MIN_WAIT_SEC), max_wait)
    moment = now or datetime.now().astimezone()
    delta = (notice.reset_at - moment).total_seconds() + RESET_BUFFER_SEC
    return min(max(delta, MIN_WAIT_SEC), max_wait)


def _format_duration(seconds: float) -> str:
    """Render seconds as a compact human duration ("2h 41m", "35m", "45s")."""
    total = int(seconds)
    if total >= 3600:
        return f"{total // 3600}h {total % 3600 // 60}m"
    if total >= 60:
        return f"{total // 60}m"
    return f"{total}s"


def wait_for_reset(notice: UsageLimitNotice) -> bool:
    """Wait out a usage limit, interruptibly.

    Sleeps in short slices so Ctrl+C/SIGTERM and the Escape key are honored
    within seconds even hours into the wait.

    Args:
        notice: The recognized limit notice.

    Returns:
        True when the wait completed; False when a shutdown or Escape
        interrupted it (the caller should hand the refused result back
        unchanged and let the run's normal pause/stop handling take over).
    """
    # Deferred import: key_listener pulls in terminal handling that tests of
    # the pure parsing above should never need.
    from .key_listener import is_cancellation_requested  # noqa: PLC0415

    seconds = wait_seconds(notice)
    until = ""
    if notice.reset_at is not None:
        until = f" (stated reset: {notice.reset_at.strftime('%H:%M %Z').strip()})"
    console.info(f"Waiting {_format_duration(seconds)} for the limit to lift{until}...")

    remaining = seconds
    while remaining > 0:
        if is_cancellation_requested():
            return False
        step = min(30.0, remaining)
        if not interruptible_sleep(step):
            return False
        remaining -= step
    return not is_cancellation_requested()


def run_query_riding_out_usage_limits(
    start_query: Callable[[], Coroutine[Any, Any, str]],
    message_processor: MessageProcessor | None,
    runner: Callable[[Coroutine[Any, Any, str]], str],
) -> str:
    """Run a query, waiting out any usage-limit refusals in between.

    The single chokepoint every agent phase routes through: when the terminal
    result is an error AND the output is a usage-limit notice, the account —
    not the task — was refused, so the query waits until the stated reset and
    runs again. Callers therefore never see a limit-refused result unless the
    wait was interrupted (shutdown/Escape) or the consecutive-wait budget ran
    out, in which case the refused result is returned unchanged and the
    caller's ordinary error handling applies.

    Also resets the processor's terminal-result state before every run, so a
    prior session's outcome can never leak into this one's derived success.

    Args:
        start_query: Zero-arg callable producing a *fresh* query coroutine
            (a coroutine cannot be awaited twice).
        message_processor: The processor capturing terminal-result state, or
            None (in which case refusals cannot be told apart from success and
            the first result is returned as-is).
        runner: Drives the coroutine to completion — callers pass their
            module-local ``run_async_with_cleanup`` binding so tests that
            patch it on the calling module keep intercepting every run.

    Returns:
        The final query's accumulated output text.
    """
    if message_processor is not None:
        message_processor.reset_result_state()
    result = runner(start_query())

    max_waits = int(
        _env_positive_number("CLAUDETM_USAGE_LIMIT_MAX_WAITS", DEFAULT_MAX_CONSECUTIVE_WAITS)
    )
    waits = 0
    while message_processor is not None and message_processor.last_result_is_error:
        notice = detect_usage_limit(result)
        if notice is None:
            break
        if waits >= max_waits:
            console.warning(
                f"Usage limit still refusing sessions after {waits} waits — giving up on "
                "waiting; the refused session is handed back to its caller"
            )
            break
        waits += 1
        console.warning(f"Session refused by a usage limit: {notice.message}")
        if not wait_for_reset(notice):
            console.warning(
                "Usage-limit wait interrupted — handing the refused session back unchanged"
            )
            break
        message_processor.reset_result_state()
        result = runner(start_query())
    return result


__all__ = [
    "DEFAULT_MAX_CONSECUTIVE_WAITS",
    "DEFAULT_WAIT_SEC",
    "MAX_WAIT_SEC",
    "MIN_WAIT_SEC",
    "RESET_BUFFER_SEC",
    "TAIL_SCAN_CHARS",
    "UsageLimitNotice",
    "detect_usage_limit",
    "run_query_riding_out_usage_limits",
    "wait_for_reset",
    "wait_seconds",
]
