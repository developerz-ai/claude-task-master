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

__all__ = [
    "DEFAULT_HIVE_MAX_PARALLEL",
    "HIVE_MAX_PARALLEL_ENV",
    "describe_machine",
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
