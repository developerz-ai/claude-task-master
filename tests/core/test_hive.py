"""Tests for the hive module — the one fan-out knob.

Failure cases first: every way the env var can be wrong must fall back to the
default rather than raise, because a typo in it must never end an unattended run.

The module used to also own PR-group *batching* (several tasks in one lead
session). That design is gone: the task is the unit of parallelism, the lead
splits its own single task, and the only thing left to bound is how many workers
it may run at once.
"""

from __future__ import annotations

import pytest

from claude_task_master.core.hive import (
    DEFAULT_HIVE_MAX_PARALLEL,
    HIVE_MAX_PARALLEL_ENV,
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
