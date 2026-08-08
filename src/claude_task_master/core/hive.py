"""Hive fan-out knob — how wide one work session may spread itself.

claudetm runs one work session per task. Inside that session the agent is the
*lead*: it reads its one task, decides whether the work splits into pieces with
**disjoint write sets**, and hands those pieces to ``hive-worker`` subagents
running concurrently in the SAME checkout. Everything that overlaps it does
itself, and it alone touches git.

The task is the unit of parallelism, not a list of tasks — the orchestrator
still checks off exactly one task per session, so nothing about the loop
changes. That leaves this module with a single decision to own: how many
workers the lead may have running at once.

The number is a **ceiling, not a target**. Nothing here can measure how big a
task is before it runs, so how many workers a task actually deserves — zero
included — is the lead's judgement, made in the prompt (see
:mod:`.prompts_working_hive`). This module only stops that judgement from
running away.
"""

from __future__ import annotations

import os

__all__ = [
    "DEFAULT_HIVE_MAX_PARALLEL",
    "HIVE_MAX_PARALLEL_ENV",
    "hive_max_parallel",
]


# One knob: 1 lead + up to this many workers running at once.
DEFAULT_HIVE_MAX_PARALLEL: int = 10

HIVE_MAX_PARALLEL_ENV = "CLAUDETM_HIVE_MAX_PARALLEL"


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
