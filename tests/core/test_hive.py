"""Tests for the hive module — the one fan-out knob.

Failure cases first: every way the env var can be wrong must fall back to the
default rather than raise, because a typo in it must never end an unattended run.

The module used to also own PR-group *batching* (several tasks in one lead
session). That design is gone: the task is the unit of parallelism, the lead
splits its own single task, and the only thing left to bound is how many workers
it may run at once.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from claude_task_master.core.hive import (
    DEFAULT_HIVE_MAX_PARALLEL,
    HIVE_MAX_PARALLEL_ENV,
    describe_machine,
    hive_max_parallel,
)

# =============================================================================
# hive_max_parallel - the env knob
# =============================================================================


class TestHiveMaxParallel:
    """A typo in an env var must never end an unattended run."""

    def test_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(HIVE_MAX_PARALLEL_ENV, raising=False)
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "3")
        assert hive_max_parallel() == 3

    def test_whitespace_tolerated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "  4 ")
        assert hive_max_parallel() == 4

    def test_zero_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "0")
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_negative_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "-5")
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_garbage_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "lots")
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_empty_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "")
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_float_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "2.5")
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_env_read_at_call_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Not frozen at import: a run may set it per-process."""
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "2")
        assert hive_max_parallel() == 2
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "7")
        assert hive_max_parallel() == 7

    def test_default_value(self) -> None:
        assert DEFAULT_HIVE_MAX_PARALLEL == 10


# =============================================================================
# describe_machine - facts for the lead, never a decision
# =============================================================================


class TestDescribeMachine:
    """The lead sizes its own team; this only hands it the numbers.

    How many workers a task can *usefully* run at once is half a task question
    (how many disjoint seams it has) and half a hardware one (how many agent
    processes this box can actually run before they slow each other down). The
    static ceiling answers neither. So claudetm measures the machine and injects
    the figures into the fan-out brief, leaving the judgement where it belongs.

    Every probe is best-effort by design: a platform that will not report a
    figure omits it, and a machine that reports nothing renders the brief
    unchanged. Sizing a team is never a reason to fail a run.
    """

    def test_reports_cpu_model_and_cores(self) -> None:
        """Cores say how many workers fit; the model says how fast each will be."""
        result = describe_machine()
        assert "core" in result
        assert str(os.cpu_count()) in result

    def test_falls_back_to_bare_core_count_without_a_model_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A platform with no /proc/cpuinfo still reports the count."""
        monkeypatch.setattr("claude_task_master.core.hive._cpu_model", lambda: None)
        assert "CPU core" in describe_machine()

    def test_reports_memory_and_disk_on_linux(self) -> None:
        """The figures the lead actually needs: what is free, not just what exists."""
        result = describe_machine()
        assert "GB RAM free" in result
        assert "GB disk free" in result

    def test_measures_the_directory_it_is_given(self, tmp_path: Path) -> None:
        assert "GB disk free" in describe_machine(str(tmp_path))

    def test_unmeasurable_machine_degrades_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing readable → empty string, which omits the paragraph entirely."""
        monkeypatch.setattr("claude_task_master.core.hive.os.cpu_count", lambda: None)
        monkeypatch.setattr("claude_task_master.core.hive._cpu_model", lambda: None)
        monkeypatch.setattr(
            "claude_task_master.core.hive.os.getloadavg",
            lambda: (_ for _ in ()).throw(OSError("no load average")),
        )
        monkeypatch.setattr("claude_task_master.core.hive._memory_gb", lambda: None)
        monkeypatch.setattr("claude_task_master.core.hive._free_disk_gb", lambda _: None)
        assert describe_machine() == ""

    def test_a_broken_probe_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unreadable /proc or an unstattable path must not end a run."""
        monkeypatch.setattr(
            "claude_task_master.core.hive.open",
            lambda *a, **k: (_ for _ in ()).throw(OSError("denied")),
            raising=False,
        )
        assert isinstance(describe_machine("/nonexistent-path-for-test"), str)
