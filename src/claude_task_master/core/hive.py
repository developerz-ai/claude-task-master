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
import shutil
from typing import Literal, cast

__all__ = [
    "DEFAULT_HIVE_MAX_PARALLEL",
    "DEFAULT_HIVE_WORKER_EFFORT",
    "DEFAULT_HIVE_WORKER_MAX_TURNS",
    "HIVE_MAX_PARALLEL_ENV",
    "HIVE_WORKER_EFFORT_ENV",
    "HIVE_WORKER_MAX_TURNS_ENV",
    "describe_machine",
    "fan_out_enabled",
    "hive_max_parallel",
    "hive_worker_effort",
    "hive_worker_max_turns",
]


#: Effort levels the SDK accepts (``AgentDefinition.effort``). ``"inherit"`` is
#: ours, not the SDK's: it means "set nothing and follow the session".
EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]

_VALID_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max"})


# One knob: 1 lead + up to this many workers running at once.
DEFAULT_HIVE_MAX_PARALLEL: int = 10

HIVE_MAX_PARALLEL_ENV = "CLAUDETM_HIVE_MAX_PARALLEL"

#: Per-worker turn budget when the session's own cap is unknown or disabled.
#:
#: Workers carry big self-contained pieces, so the budget is sized for real work
#: (healthy solo sessions run tens of turns). It exists to stop a runaway worker
#: from burning the session's aggregate limits on everyone else's behalf — which
#: is why the *usual* value is derived from that aggregate rather than fixed:
#: see :func:`hive_worker_max_turns`.
DEFAULT_HIVE_WORKER_MAX_TURNS: int = 200

#: Share of the session's turn budget one worker may take, as a divisor. The
#: session cap (``MAX_TURNS``, 400) counts the lead *and* every subagent, so a
#: flat 200-turn worker meant two busy workers could exhaust the whole session
#: on their own — ending it with ``error_max_turns``, nothing committed, and the
#: entire fanned-out task re-run at N agents' cost. Five gives a realistic team
#: (a lead plus three or four workers) room to finish inside one session.
_WORKER_TURN_SHARE: int = 5

#: Floor for the derived budget. Below this a worker cannot finish a real piece,
#: and a worker that runs out mid-piece costs more than one that never started.
_MIN_WORKER_MAX_TURNS: int = 40

HIVE_WORKER_MAX_TURNS_ENV = "CLAUDETM_HIVE_WORKER_MAX_TURNS"

#: Reasoning effort each worker runs at (``AgentDefinition.effort``).
#:
#: Left unset, a worker inherits the *session's* effort, and the session's is
#: keyed off its model — so a ``[coding]`` task put every worker on Opus at
#: ``"max"``, the deepest thinking tier, for every turn it took. That is the
#: right tier for the lead, which is deciding how to cut the work; it is not
#: the right tier for a worker, whose piece arrives already specified, with its
#: file set and the API surface to conform to handed over in the brief. The
#: model is unchanged (``"inherit"``, so Opus stays Opus) — only the per-turn
#: thinking depth is dialled from "max" to "high", which is still an extended
#: reasoning tier. Set :data:`HIVE_WORKER_EFFORT_ENV` to ``max`` to restore the
#: old behaviour, or to ``inherit`` to go back to following the session.
DEFAULT_HIVE_WORKER_EFFORT: EffortLevel = "high"

HIVE_WORKER_EFFORT_ENV = "CLAUDETM_HIVE_WORKER_EFFORT"


def fan_out_enabled(parallel: bool, push_only: bool) -> bool:
    """Whether this work session may split its task across workers.

    The single source of truth for the question, because two places have to
    agree on it and used not to: the prompt builder (does the session get the
    fan-out brief?) and the query builder (does the session get the
    ``hive-worker`` agent definition at all?). While only the prompt consulted
    it, ``--no-parallel`` removed the brief but left the worker registered and
    the Agent tool available — so a session told nothing about fan-out could
    still fan out, and push-only fix sessions, documented as never fanning out,
    were observed doing exactly that.

    Args:
        parallel: ``TaskOptions.parallel`` — the user's opt-out.
        push_only: True for a fix session (CI, review, conflict), which adds one
            focused commit to an existing PR and is never worth cutting up.

    Returns:
        True when the session may dispatch workers.
    """
    return parallel and not push_only


def _env_positive_int(name: str, default: int) -> int:
    """Read a positive int from the environment, falling back on garbage.

    Never raises — a typo in an env var must not end an unattended run.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (ValueError, AttributeError):
        return default
    return value if value > 0 else default


def hive_max_parallel() -> int:
    """Maximum concurrent hive workers (1 lead + up to N workers).

    Reads ``CLAUDETM_HIVE_MAX_PARALLEL``; anything unset, unparseable or ``<= 0``
    falls back to :data:`DEFAULT_HIVE_MAX_PARALLEL`.
    """
    return _env_positive_int(HIVE_MAX_PARALLEL_ENV, DEFAULT_HIVE_MAX_PARALLEL)


def hive_worker_max_turns() -> int:
    """Turn budget each hive worker gets (``AgentDefinition.maxTurns``).

    An explicit ``CLAUDETM_HIVE_WORKER_MAX_TURNS`` wins. Otherwise the budget is
    derived from the session's own cap, because the two are spent from the same
    pot: ``max_turns`` bounds the whole query, and the terminal ``ResultMessage``
    aggregates the lead plus every subagent. A per-worker budget set independent
    of that is not a bound at all — at the old flat 200 against a 400-turn
    session, two busy workers could end the session in ``error_max_turns`` with
    nothing committed, which re-runs the entire task, fan-out included. The
    derived value is the session cap divided by :data:`_WORKER_TURN_SHARE`,
    floored at :data:`_MIN_WORKER_MAX_TURNS`.

    With the session cap disabled (``CLAUDETM_MAX_TURNS=0``) there is nothing to
    divide, so :data:`DEFAULT_HIVE_WORKER_MAX_TURNS` applies.

    Returns:
        The per-worker turn budget, always positive.
    """
    raw = os.environ.get(HIVE_WORKER_MAX_TURNS_ENV)
    if raw is not None:
        return _env_positive_int(HIVE_WORKER_MAX_TURNS_ENV, DEFAULT_HIVE_WORKER_MAX_TURNS)

    # Deferred: agent_query pulls in the config stack, and this module is a leaf
    # imported by prompt building.
    from .agent_query import MAX_TURNS  # noqa: PLC0415

    if not MAX_TURNS or MAX_TURNS <= 0:
        return DEFAULT_HIVE_WORKER_MAX_TURNS
    return max(_MIN_WORKER_MAX_TURNS, MAX_TURNS // _WORKER_TURN_SHARE)


def hive_worker_effort() -> EffortLevel | None:
    """Reasoning effort for a hive worker (``AgentDefinition.effort``).

    Reads ``CLAUDETM_HIVE_WORKER_EFFORT``. ``"inherit"`` (any case) returns None,
    which leaves the field unset so the worker follows the session's effort.
    Anything unset falls back to :data:`DEFAULT_HIVE_WORKER_EFFORT`; anything
    unrecognised falls back to it too rather than raising — a typo in an env var
    must not end an unattended run.
    """
    raw = os.environ.get(HIVE_WORKER_EFFORT_ENV)
    if raw is None:
        return DEFAULT_HIVE_WORKER_EFFORT
    value = raw.strip().lower()
    if value == "inherit":
        return None
    if value in _VALID_EFFORTS:
        return cast("EffortLevel", value)
    return DEFAULT_HIVE_WORKER_EFFORT


def describe_machine(working_dir: str | None = None) -> str:
    """One line describing the machine the workers would share, for the brief.

    The ceiling above is a static safety bound; it knows nothing about the box
    the run landed on. How many workers a task can *usefully* have at once is
    partly a hardware question — every worker is another process reading the
    repo and running its own checks against the same CPUs and the same disk, so
    past the point where they stop fitting, more workers make every one of them
    slower rather than the task faster. The lead is the only thing positioned to
    weigh that against its task's actual seams, so claudetm measures the machine
    and hands the numbers over instead of deciding for it.

    Everything here is best-effort: a platform that will not report a figure
    simply omits it, and a machine that reports nothing yields an empty string
    that renders the brief unchanged. Sizing a team is a judgement call, never a
    reason to fail a run.

    Args:
        working_dir: Directory whose filesystem is measured for free space.
            Defaults to the process cwd.

    Returns:
        A short human-readable summary (e.g. ``"8 CPU cores, load average 2.10,
        6.1/31.2 GB RAM free, 84 GB disk free"``), or ``""`` when nothing could
        be measured.
    """
    parts: list[str] = []

    cores = os.cpu_count()
    cpu = _cpu_model()
    if cores and cpu:
        parts.append(f"{cpu} ({cores} core{'s' if cores != 1 else ''})")
    elif cores:
        parts.append(f"{cores} CPU core{'s' if cores != 1 else ''}")
    elif cpu:
        parts.append(cpu)

    try:
        load = os.getloadavg()[0]
    except (OSError, AttributeError):
        pass  # No load average on this platform (e.g. Windows).
    else:
        parts.append(f"load average {load:.2f}")

    memory = _memory_gb()
    if memory:
        available, total = memory
        parts.append(f"{available:.1f}/{total:.1f} GB RAM free")

    disk = _free_disk_gb(working_dir)
    if disk is not None:
        parts.append(f"{disk:.0f} GB disk free")

    return ", ".join(parts)


def _cpu_model() -> str | None:
    """The CPU's marketing name, or None when it cannot be read.

    Cores alone say how many workers *fit*; the model says how fast each one
    will be, which is the difference between a split that pays off and one that
    just multiplies a slow build. Read from ``/proc/cpuinfo``; absent elsewhere,
    in which case the core count carries the paragraph on its own.
    """
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                key, sep, value = line.partition(":")
                if sep and key.strip() == "model name":
                    return " ".join(value.split()) or None
    except OSError:
        return None
    return None


def _memory_gb() -> tuple[float, float] | None:
    """Available and total RAM in GB, or None when unmeasurable.

    Reads ``/proc/meminfo`` rather than taking a dependency on ``psutil``:
    claudetm must install cleanly anywhere, and a missing memory figure is not
    worth a wheel. ``MemAvailable`` is the kernel's own estimate of what a new
    workload can claim without swapping — the number that matters when deciding
    whether another few agent processes fit — so it is preferred over ``MemFree``,
    which excludes reclaimable cache and reads alarmingly low on a healthy box.
    """
    fields: dict[str, float] = {}
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                key, _, rest = line.partition(":")
                if key in ("MemAvailable", "MemTotal"):
                    try:
                        fields[key] = float(rest.split()[0]) / (1024 * 1024)  # kB -> GB
                    except (IndexError, ValueError):
                        return None
                if len(fields) == 2:
                    break
    except OSError:
        return None
    if len(fields) != 2:
        return None
    return fields["MemAvailable"], fields["MemTotal"]


def _free_disk_gb(working_dir: str | None) -> float | None:
    """Free space in GB on the filesystem holding ``working_dir``, or None."""
    try:
        return shutil.disk_usage(working_dir or ".").free / (1024**3)
    except OSError:
        return None
