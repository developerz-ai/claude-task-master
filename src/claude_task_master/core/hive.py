"""Hive batching - pure logic for running a PR group's tasks in one session.

claudetm normally runs one work session per task. With ``TaskOptions.parallel_tasks``
the *remaining* tasks of the current PR group are instead handed to a single
"hive lead" session: the lead reads the whole batch, decides for itself which
tasks have disjoint write sets, fans those out to ``hive-worker`` subagents in
the SAME checkout, does the rest sequentially, and is the only thing that
touches git.

This module is deliberately pure — no I/O, no git, no SDK imports at module
scope — so every rule below is trivially testable:

* :func:`plan_hive_batch` decides *whether* there is a batch worth running and
  which plan indices it covers.
* :func:`parse_completed_task_numbers` reads the lead's completion manifest back
  out of its final message.
* :func:`has_completion_manifest` says whether the lead reported at all.
* :func:`hive_max_parallel` reads the one fan-out knob.

The mechanical floor (:data:`HIVE_MIN_BATCH_TASKS`) exists because prose is not
a constraint: told "only parallelise when it pays", a lead will still spawn four
agents for four one-line edits. Below the floor the caller must fall back to the
ordinary one-task-per-session path.

Reading the manifest is a THREE-way decision, not two. An empty list from
:func:`parse_completed_task_numbers` is ambiguous on its own, so callers must
pair it with :func:`has_completion_manifest`:

* **absent** (``has_completion_manifest`` False) — the lead never emitted the
  line: it forgot, it was cut off, or it ran an older prompt. Nothing was
  reported, so fall back to today's behaviour and check off exactly the one
  current task.
* **present and empty** (True, ``[]``) — ``TASKS COMPLETE:`` with nothing after
  it is the prompt's sanctioned way of saying "I finished none of them". Check
  off NOTHING. Applying the absent-case fallback here would check off a task the
  lead just told us it did not do, silently losing that work.
* **present with numbers** (True, non-empty) — check off exactly the reported
  numbers that the batch actually covered.

A non-numeric tail (an un-substituted ``<plan numbers …>`` placeholder, "none",
prose) reads as *present and empty*: the lead said something, but claimed no
task. That is the safe direction — the tasks simply re-run.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .task_group import ParsedTask

__all__ = [
    "HIVE_MIN_BATCH_TASKS",
    "DEFAULT_HIVE_MAX_PARALLEL",
    "HIVE_MAX_PARALLEL_ENV",
    "HIVE_MANIFEST_PREFIX",
    "HIVE_MANIFEST_LINE",
    "HIVE_MANIFEST_HINT",
    "HiveBatch",
    "plan_hive_batch",
    "parse_completed_task_numbers",
    "has_completion_manifest",
    "hive_max_parallel",
]


# Below this many remaining tasks a hive session costs more than it saves: the
# lead's own planning pass plus a subagent cold start, to parallelise nothing.
# A one-task batch must fall back to today's ordinary single-task path.
HIVE_MIN_BATCH_TASKS: int = 2

# One knob: 1 lead + up to this many workers running at once.
DEFAULT_HIVE_MAX_PARALLEL: int = 10

HIVE_MAX_PARALLEL_ENV = "CLAUDETM_HIVE_MAX_PARALLEL"


# The lead reports which plan tasks it actually finished by ending its output
# with a manifest line. It is deliberately PLURAL: "TASK COMPLETE" (singular) is
# the pre-existing single-task sentinel used by every other prompt in the repo,
# and matching it here would mass-check-off a whole batch off the back of one
# ordinary session's sign-off.
HIVE_MANIFEST_PREFIX = "TASKS COMPLETE"
HIVE_MANIFEST_LINE = f"{HIVE_MANIFEST_PREFIX}: <comma-separated plan task numbers>"
HIVE_MANIFEST_HINT = (
    f"End your final message with a single line listing the plan task numbers you "
    f"actually finished, e.g. `{HIVE_MANIFEST_PREFIX}: 3, 4, 6`. List only tasks that "
    f"are done, verified and included in the commit — anything omitted stays open."
)

# Matches only the plural manifest label, with optional markdown bolding /
# blockquote decoration around it. `TASK COMPLETE` cannot match: `TASKS` is
# required and `\b` after it keeps `TASKSCOMPLETE`-style noise out.
_MANIFEST_RE = re.compile(
    r"^[\s>*_#-]*\bTASKS\b\s+COMPLETE\b(?P<tail>.*)$",
    re.IGNORECASE,
)

# One number of the manifest tail, plus whatever separator preceded it:
# commas, semicolons, whitespace, a literal "and", and `#` prefixes are all
# tolerated. Scanning stops at the first token that is not a number, so trailing
# prose ("3, 4 (of 6)") cannot smuggle an extra task number in.
_MANIFEST_NUMBER_RE = re.compile(r"[\s,;]*(?:and\s+)?#?(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class HiveBatch:
    """The remaining tasks of one PR group, handed to a single hive lead session.

    Attributes:
        indices: 0-based plan indices, ascending. Every one is incomplete and in
            the same group. NOT necessarily contiguous — a completed task may
            sit in the middle of the group.
        descriptions: Complexity-tag-stripped task text, parallel to ``indices``.
        group_name: Human name of the PR group the batch belongs to.
    """

    indices: tuple[int, ...]
    descriptions: tuple[str, ...]
    group_name: str

    @property
    def size(self) -> int:
        """Number of tasks in the batch."""
        return len(self.indices)

    @property
    def numbers(self) -> tuple[int, ...]:
        """1-based plan numbers, as shown to the agent and used in the manifest."""
        return tuple(i + 1 for i in self.indices)

    @property
    def last_index(self) -> int:
        """Highest plan index in the batch (the task that closes the group)."""
        return self.indices[-1]


def plan_hive_batch(
    parsed_tasks: Sequence[ParsedTask],
    current_index: int,
    *,
    enabled: bool,
    pr_per_task: bool = False,
) -> HiveBatch | None:
    """Decide whether the current task should run as a hive batch.

    Args:
        parsed_tasks: All tasks parsed from the plan, in plan order.
        current_index: Index of the task the loop is about to run.
        enabled: ``TaskOptions.parallel_tasks``.
        pr_per_task: ``TaskOptions.pr_per_task``. One PR per task is
            incompatible with batching several tasks into one session.

    Returns:
        A :class:`HiveBatch` covering every incomplete task at or after
        ``current_index`` in the current task's group, or ``None`` when the
        caller should use the ordinary one-task-per-session path.
    """
    if not enabled or pr_per_task:
        return None
    if current_index < 0 or current_index >= len(parsed_tasks):
        return None

    current = parsed_tasks[current_index]
    group_id = current.group_id

    batch = [
        task
        for task in parsed_tasks
        if task.group_id == group_id and task.index >= current_index and not task.is_complete
    ]
    batch.sort(key=lambda task: task.index)

    if len(batch) < HIVE_MIN_BATCH_TASKS:
        return None

    return HiveBatch(
        indices=tuple(task.index for task in batch),
        descriptions=tuple(task.cleaned_description for task in batch),
        group_name=current.group_name,
    )


def _manifest_tail(output: str) -> str | None:
    """Return the text after the last manifest label, or ``None`` if absent.

    An empty string means the label was there with nothing (parseable) after it
    — the "I finished none of them" case, which is NOT the same as no manifest.
    """
    if not output:
        return None

    tail: str | None = None
    for line in output.split("\n"):
        match = _MANIFEST_RE.match(line.strip())
        if match:
            # Last manifest wins: a lead that restates its result has revised it.
            tail = match.group("tail")
    return tail


def has_completion_manifest(output: str) -> bool:
    """Whether the lead emitted a completion manifest line at all.

    Distinguishes "the lead never reported" from "the lead reported finishing
    nothing" — see the module docstring's three-way reading. The singular
    ``TASK COMPLETE`` sentinel is not a manifest and never counts here.

    Args:
        output: The lead session's full text output.

    Returns:
        True iff a ``TASKS COMPLETE`` line is present, empty tail included.
    """
    return _manifest_tail(output) is not None


def parse_completed_task_numbers(output: str, allowed: Iterable[int]) -> list[int]:
    """Parse the hive lead's completion manifest out of its final message.

    The lead ends its output with e.g. ``TASKS COMPLETE: 3, 4, 6`` (1-based plan
    numbers). Parsing is tolerant of case, markdown bolding, ``#`` prefixes and
    comma/whitespace separators, but *not* of the singular ``TASK COMPLETE``
    sentinel every other prompt in the repo uses.

    Args:
        output: The lead session's full text output.
        allowed: The plan numbers the batch actually covered. Anything outside
            this set is dropped silently — a hallucinated number must never
            check off a task the batch never touched.

    Returns:
        Deduplicated, ascending plan numbers. Empty both when there is no
        manifest and when the manifest claims nothing; pair this with
        :func:`has_completion_manifest` to tell those apart — they must not be
        handled the same way.
    """
    allowed_set = set(allowed)
    if not allowed_set:
        return []

    tail = _manifest_tail(output)
    if tail is None:
        return []

    numbers: list[int] = []
    # Drop the label's own punctuation ( ":", "**", "-" ) before scanning.
    pos = len(tail) - len(tail.lstrip(" \t:*_-"))
    while (number_match := _MANIFEST_NUMBER_RE.match(tail, pos)) is not None:
        numbers.append(int(number_match.group(1)))
        pos = number_match.end()

    return sorted({n for n in numbers if n in allowed_set})


def hive_max_parallel() -> int:
    """Maximum concurrent hive workers (1 lead + up to N workers).

    Reads ``CLAUDETM_HIVE_MAX_PARALLEL``; anything unset, unparseable or ``<= 0``
    falls back to :data:`DEFAULT_HIVE_MAX_PARALLEL`. Never raises — a typo in an
    env var must not end an unattended run.
    """
    raw = os.environ.get(HIVE_MAX_PARALLEL_ENV)
    if raw is None:
        return DEFAULT_HIVE_MAX_PARALLEL
    try:
        value = int(raw.strip())
    except (ValueError, AttributeError):
        return DEFAULT_HIVE_MAX_PARALLEL
    return value if value > 0 else DEFAULT_HIVE_MAX_PARALLEL
