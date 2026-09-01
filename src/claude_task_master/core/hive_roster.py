"""Live roster of the workers a lead session has running — the hive, at a glance.

A fanned-out work session interleaves several ``hive-worker`` subagents into one
stream. :class:`~.console.SubagentPalette` already makes an individual line
attributable (``↳ [hive-worker#2] …``), which answers "who said this?" — but a
human watching the run still has no view of the *team*: how many workers are
alive, what each is doing right now, how long each has been at it, and what each
has burned. On an unattended run that is the difference between "the session has
been quiet for four minutes" and "four workers are mid-edit and one finished".

This module owns that view and nothing else: it is a state tracker plus a
renderer, and it **returns lines rather than printing them**. Printing here
would put a second ANSI/colour policy next to ``console``'s, the one place that
decides whether escapes are emitted at all (a redirected run writes
``.claude-task-master/logs/``, where escapes are noise) — and a renderer that
prints can only be tested by capturing stdout, while one returning ``list[str]``
is tested by reading it. The caller in ``agent_message`` does the printing.

The output is deliberately **line-oriented, not a TUI**. Claude Code repaints a
roster in place with cursor control; claudetm's console is an append-only stream
that is routinely piped into a file, so a repainting roster would render there
as a screenful of garbage per update. Instead the block is emitted whole, at
most once per :data:`DEFAULT_ROSTER_INTERVAL_SEC` (see :meth:`HiveRoster.due`) —
a periodic snapshot reads correctly both live and in a log a day later.

Nothing here may raise. It renders diagnostics for a run nobody is watching; a
crash in the status display taking down a session that was working fine would be
strictly worse than showing no status at all. Every entry point tolerates
unknown ids, missing fields and garbage values.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

__all__ = [
    "DEFAULT_ROSTER_INTERVAL_SEC",
    "MAX_ACTIVITY_CHARS",
    "ROSTER_INTERVAL_ENV",
    "HiveRoster",
    "format_elapsed",
    "format_tokens",
    "roster_interval_sec",
]


#: How often the roster block may be emitted, in seconds.
#:
#: A fan-out runs for many minutes, so this is a *heartbeat*, not an animation:
#: often enough that a stalled team is visible within a minute, rare enough that
#: the block never competes with the workers' own output for the reader's
#: attention. ``0`` in the env var turns the roster off entirely.
DEFAULT_ROSTER_INTERVAL_SEC: int = 60

ROSTER_INTERVAL_ENV = "CLAUDETM_HIVE_ROSTER_INTERVAL_SEC"

#: Width the "current activity" cell is truncated to.
#:
#: An activity string is whatever the worker last did or said, which can be a
#: paragraph. The roster is a scan-in-one-glance table; a cell that wraps makes
#: every column below it meaningless, so the text is cut rather than allowed to
#: reflow the block.
MAX_ACTIVITY_CHARS: int = 60

#: Name given to a worker adopted from an update seen before its dispatch — a
#: real subagent whose ``subagent_type`` we have not been told yet.
_UNKNOWN_NAME = "subagent"


def roster_interval_sec() -> int:
    """Seconds between roster emissions; ``0`` means the roster is disabled.

    Reads :data:`ROSTER_INTERVAL_ENV` on **every call**, never at import, as the
    repo already does elsewhere (``_env_positive_int`` in :mod:`.hive`): a
    malformed env var must degrade to the default rather than raise at import
    and take down every claudetm command, ``status`` and ``doctor`` included.
    Unlike ``hive``'s helper this one cannot reject ``0``, because ``0`` is a
    meaningful setting here — "never show the roster", for anyone who finds the
    block noisy. Negative and unparseable values still fall back to the default.

    Returns:
        The interval in seconds, or ``0`` when the roster is switched off.
    """
    raw = os.environ.get(ROSTER_INTERVAL_ENV)
    if raw is None:
        return DEFAULT_ROSTER_INTERVAL_SEC
    try:
        value = int(raw.strip())
    except (ValueError, AttributeError, TypeError):
        return DEFAULT_ROSTER_INTERVAL_SEC
    if value == 0:
        return 0
    return value if value > 0 else DEFAULT_ROSTER_INTERVAL_SEC


def format_elapsed(seconds: float) -> str:
    """Render a duration compactly: ``47s``, ``19m 50s``, ``1h 04m``.

    One unit pair, largest first, seconds dropped past the hour — the reader is
    asking "is this worker stuck?", and at that scale the seconds digit is
    noise. Minor components are zero-padded (``1m 02s``) so a column of these
    stays aligned without the caller padding it.

    The clock is :func:`time.monotonic` in production, but a negative or
    non-finite value can still arrive (timestamps from two sources, a stepped
    clock in a test). Both render as ``0s`` rather than ``-1m 60s`` or ``nans``:
    a wrong-looking zero is readable, and raising here would kill a session over
    a cosmetic.

    Args:
        seconds: Elapsed wall time.

    Returns:
        A short human-readable duration, never empty.
    """
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "0s"
    if not math.isfinite(value) or value < 0:
        return "0s"
    total = int(value)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60:02d}s"
    return f"{total // 3600}h {(total % 3600) // 60:02d}m"


def format_tokens(count: int) -> str:
    """Render a token count compactly: ``847``, ``410.2k``, ``1.2M``.

    A worker's cold start alone runs to hundreds of thousands of tokens, so raw
    digits make the column both wide and hard to compare at a glance. One decimal
    place is the useful resolution: the number answers "is this worker
    expensive?", not "exactly how expensive".

    Args:
        count: A token count. Negative, non-integral or unusable values render
            as ``"0"`` rather than raising.

    Returns:
        A short human-readable count, never empty.
    """
    try:
        value = int(count)
    except (TypeError, ValueError, OverflowError):
        return "0"
    if value < 0:
        return "0"
    if value < 1000:
        return str(value)
    # 999_950 is where one decimal place would round up to "1000.0k"; hand it to
    # the next unit instead so the column never gains a digit.
    if value < 999_950:
        return f"{value / 1000:.1f}k"
    return f"{value / 1_000_000:.1f}M"


def _normalize_activity(activity: str) -> str:
    """Collapse an activity string to one short single-line cell.

    Worker text arrives as prose with newlines and runs of spaces; a row is one
    line, so whitespace is collapsed *before* truncation (the other order spends
    the budget on indentation). Blank input returns ``""``, which the caller
    reads as "no update" and keeps the previous activity — a worker that emits
    an empty block has not stopped doing what it was doing.
    """
    try:
        collapsed = " ".join(str(activity).split())
    except (TypeError, ValueError):
        return ""
    if not collapsed:
        return ""
    if len(collapsed) <= MAX_ACTIVITY_CHARS:
        return collapsed
    return collapsed[: MAX_ACTIVITY_CHARS - 1].rstrip() + "…"


def _usage_int(usage: Any, key: str) -> int:
    """Pull one integer token field out of an SDK usage payload.

    ``usage`` is a plain dict in the Python SDK, but other shapes carry
    attributes — :mod:`.agent_message` learned this the expensive way (a
    ``getattr`` on a dict returned 0, so every cost report read zero tokens), so
    both are accepted here from the start. Anything missing, ``None`` or
    unparseable contributes 0: an incomplete payload degrades the figure, never
    the run.
    """
    if usage is None:
        return 0
    raw: Any
    if isinstance(usage, dict):
        raw = usage.get(key)
    else:
        raw = getattr(usage, key, None)
    if raw is None or isinstance(raw, bool):
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        return 0
    return value if value > 0 else 0


@dataclass
class _Worker:
    """One dispatched subagent's live state.

    Private: the roster's public surface is its methods and its rendered lines,
    so nothing outside can come to depend on this shape.
    """

    tool_use_id: str
    name: str
    ordinal: int
    started: float
    activity: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    ended: float | None = None
    is_error: bool = False

    @property
    def label(self) -> str:
        """``"<name>#<n>"`` with a 1-based ordinal, matching the stream marker.

        The roster and the per-line ``↳ [hive-worker#2]`` marker must name a
        worker identically or the reader cannot connect the two.
        """
        return f"{self.name}#{self.ordinal + 1}"


class HiveRoster:
    """Tracks the workers a lead has dispatched and renders them as a block.

    Keyed by ``tool_use_id``, exactly as :class:`~.console.SubagentPalette` is
    and for the same reason: the concurrent workers a lead spawns share one
    agent name, so the name identifies a *role*, not an instance. The id is
    minted at dispatch and constant for that worker's whole life, which is what
    lets a row keep its identity across updates. An instance is owned by one
    message processor and :meth:`clear`ed between queries, so ordinals restart
    per session rather than growing across a run.

    Finished workers stay in the block until ``clear()``. They cost one line and
    answer what the live rows cannot — "did the ones that already returned
    succeed, and what did they cost?" — which is exactly what a reader needs
    when a fan-out ends with a dirty tree.
    """

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        """Initialize an empty roster.

        Args:
            clock: Monotonic time source, injected so tests can step time
                without sleeping (this repo's pytest runs under ``--timeout=2``,
                so a test that actually waits is a flake waiting to happen).
                Defaults to :func:`time.monotonic`, which is immune to the wall
                clock being adjusted mid-session.
        """
        self._clock: Callable[[], float] = clock or time.monotonic
        self._workers: dict[str, _Worker] = {}
        self._last_emit: float | None = None

    def clear(self) -> None:
        """Forget every worker and reset the emission timer (between queries)."""
        self._workers = {}
        self._last_emit = None

    def spawn(self, tool_use_id: str, name: str, ordinal: int) -> None:
        """Record that the lead dispatched a worker.

        **Idempotent.** The same dispatch can be seen more than once (a replayed
        tool block, a caller that called :meth:`note_activity` first), and
        re-registering would restart the worker's clock and zero its tokens —
        turning a worker eight minutes into its piece into one that looks fresh,
        the single most misleading thing this display could do.

        Args:
            tool_use_id: The dispatching tool-use id; the row's identity.
            name: The ``subagent_type`` — ``"hive-worker"``, or a project
                specialist such as ``"backend-dev"``.
            ordinal: 0-based slot from ``SubagentPalette``, displayed 1-based.
        """
        existing = self._workers.get(tool_use_id)
        if existing is not None:
            # Only ever *improve* what we know; never reset the clock.
            if name and existing.name == _UNKNOWN_NAME:
                existing.name = name
            return
        self._workers[tool_use_id] = _Worker(
            tool_use_id=tool_use_id,
            name=name or _UNKNOWN_NAME,
            ordinal=ordinal if ordinal >= 0 else self._next_ordinal(),
            started=self._now(),
        )

    def note_activity(self, tool_use_id: str, activity: str) -> None:
        """Replace what this worker is shown to be doing right now.

        Called on every tool use and every text block from the worker, so the
        cell always shows the most recent thing — a roster that accumulated
        history would be a log, and the stream is already the log.

        Args:
            tool_use_id: The worker's dispatching tool-use id. Unknown ids are
                adopted rather than dropped: a worker can speak before its
                dispatching tool block has been processed, and a row named
                ``subagent`` is far better than a silently missing worker.
            activity: Free text; whitespace-collapsed and truncated. Blank
                input is ignored so the previous activity survives.
        """
        text = _normalize_activity(activity)
        worker = self._ensure(tool_use_id)
        if text:
            worker.activity = text

    def add_usage(self, tool_use_id: str, usage: Any) -> None:
        """Accumulate this worker's token usage.

        Cache tokens are summed **into the input total**. A worker's cold start
        is almost entirely cache reads — it re-reads the repo it was handed — so
        a figure counting only ``input_tokens`` reports a worker that burned half
        a million tokens as having burned a few thousand, useless as the one
        number that could justify or condemn a fan-out.

        Args:
            tool_use_id: The worker's dispatching tool-use id (adopted if new).
            usage: An SDK usage payload — dict or attribute-carrying object.
                ``None``, missing fields and garbage values all add 0.
        """
        worker = self._ensure(tool_use_id)
        worker.input_tokens += (
            _usage_int(usage, "input_tokens")
            + _usage_int(usage, "cache_read_input_tokens")
            + _usage_int(usage, "cache_creation_input_tokens")
        )
        worker.output_tokens += _usage_int(usage, "output_tokens")

    def finish(self, tool_use_id: str, *, is_error: bool = False) -> None:
        """Mark a worker as returned; its elapsed time freezes here.

        The row stays in :meth:`render` until :meth:`clear` — see the class
        docstring for why a finished worker is still worth a line.

        Args:
            tool_use_id: The worker's dispatching tool-use id (adopted if new).
            is_error: True when the worker's tool result was an error, which
                changes only the row's mark and label. The lead still has to
                verify every worker's claim on disk; this is a hint to a human,
                never a verdict.
        """
        worker = self._ensure(tool_use_id)
        if worker.ended is None:
            worker.ended = self._now()
        worker.is_error = worker.is_error or is_error

    @property
    def live_count(self) -> int:
        """How many workers are dispatched and have not yet returned."""
        return sum(1 for w in self._workers.values() if w.ended is None)

    def due(self, *, force: bool = False) -> bool:
        """Whether the caller should emit the roster now (rate limiter).

        The roster exists to be glanceable, so it must not print on every stream
        message; the caller asks this and prints only when told to.

        Two deliberate asymmetries. A disabled roster (interval ``0``) answers
        False even to ``force`` — "off" a caller can override is not off. And an
        *empty* roster answers False without consuming the interval, so a caller
        polling before any worker exists cannot spend the first window on a
        block that would have rendered as nothing.

        Args:
            force: Emit regardless of how recently the last block went out —
                for the moments worth showing on sight, such as the first
                dispatch or the last worker returning.

        Returns:
            True at most once per interval (see :func:`roster_interval_sec`).
        """
        interval = roster_interval_sec()
        if interval <= 0 or not self._workers:
            return False
        now = self._now()
        if force or self._last_emit is None or (now - self._last_emit) >= interval:
            self._last_emit = now
            return True
        return False

    def render(self) -> list[str]:
        """Render the roster block as plain lines — no ANSI, no emoji.

        Colour is the caller's business (:mod:`.console` owns that policy) and
        emoji are banned from this project's printer outright, so status is
        carried by ASCII marks: ``~`` running, ``+`` done, ``!`` failed.

        Column widths are measured from the rows rather than fixed, because a
        project specialist's name is arbitrarily long — one
        ``database-migration-specialist#3`` would push every following column
        out of alignment in a hardcoded layout.

        Returns:
            The block's lines (header first, one line per worker, ordinal
            order), or ``[]`` when there is nothing to show or the roster is
            disabled — callers can print the result unconditionally.
        """
        if roster_interval_sec() <= 0 or not self._workers:
            return []
        now = self._now()
        rows = [self._row(w, now) for w in sorted(self._workers.values(), key=_sort_key)]
        widths = [max(len(row[i]) for row in rows) for i in range(1, 5)]
        lines = [self._header()]
        for mark, label, activity, elapsed, tok_in, tok_out in rows:
            lines.append(
                f"  {mark} {label:<{widths[0]}}   {activity:<{widths[1]}}   "
                f"{elapsed:>{widths[2]}}   in {tok_in:>{widths[3]}} out {tok_out}".rstrip()
            )
        return lines

    # --- internals ----------------------------------------------------

    def _now(self) -> float:
        """Read the injected clock, tolerating one that misbehaves."""
        try:
            return float(self._clock())
        except Exception:  # A broken clock must never end a run.
            return 0.0

    def _next_ordinal(self) -> int:
        """The ordinal to give a worker we were never told the slot of."""
        if not self._workers:
            return 0
        return max(w.ordinal for w in self._workers.values()) + 1

    def _ensure(self, tool_use_id: str) -> _Worker:
        """Fetch a worker's row, adopting an unknown id as a new one.

        Adoption rather than rejection: the alternative is dropping the update,
        and a demonstrably alive worker (it just spoke) missing from the roster
        is the one failure this display cannot afford.
        """
        worker = self._workers.get(tool_use_id)
        if worker is not None:
            return worker
        worker = _Worker(
            tool_use_id=tool_use_id,
            name=_UNKNOWN_NAME,
            ordinal=self._next_ordinal(),
            started=self._now(),
        )
        self._workers[tool_use_id] = worker
        return worker

    def _header(self) -> str:
        """The count line: how many are working, how many have returned."""
        live = self.live_count
        done = len(self._workers) - live
        parts: list[str] = []
        if live:
            parts.append(f"{live} {_plural(live, 'worker')} active")
        if done:
            parts.append(f"{done} done")
        return "Hive: " + ", ".join(parts)

    def _row(self, worker: _Worker, now: float) -> tuple[str, str, str, str, str, str]:
        """One worker's cells: mark, label, activity, elapsed, in, out."""
        if worker.ended is None:
            mark = "~"
            activity = worker.activity or "starting"
            elapsed = now - worker.started
        else:
            mark = "!" if worker.is_error else "+"
            activity = "failed" if worker.is_error else "done"
            elapsed = worker.ended - worker.started
        return (
            mark,
            worker.label,
            activity,
            format_elapsed(elapsed),
            format_tokens(worker.input_tokens),
            format_tokens(worker.output_tokens),
        )


def _sort_key(worker: _Worker) -> tuple[int, str]:
    """Order rows by dispatch slot, so a worker never moves between blocks."""
    return (worker.ordinal, worker.tool_use_id)


def _plural(count: int, noun: str) -> str:
    """``"worker"`` / ``"workers"`` — English only; this is a console line."""
    return noun if count == 1 else f"{noun}s"
