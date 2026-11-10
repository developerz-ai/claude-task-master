"""Tests for start-command input validation in cli_commands.workflow."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import typer

from claude_task_master.cli import app
from claude_task_master.cli_commands.workflow import _validate_budget, _validate_goal

README = Path(__file__).resolve().parents[2] / "README.md"

# --checkpointing is dead and being removed, so it is deliberately undocumented.
_UNDOCUMENTED_START_FLAGS = {"--checkpointing", "--help"}


def _normalize(text: str) -> str:
    """Strip ANSI + box-border chars and collapse whitespace.

    Rich renders click errors inside a bordered box, wrapping long messages and
    inserting ``│`` border glyphs mid-sentence. Removing the box-drawing block
    (U+2500–U+257F) lets substring assertions match regardless of terminal width.
    """
    no_ansi = re.sub(r"\x1b\[[0-9;]*m", "", text)
    no_box = re.sub(r"[─-╿]", " ", no_ansi)
    return re.sub(r"\s+", " ", no_box)


class TestValidateGoal:
    """Unit tests for the _validate_goal callback."""

    def test_accepts_non_empty_goal(self):
        """A normal goal passes through unchanged."""
        assert _validate_goal("Add auth") == "Add auth"

    def test_rejects_empty_goal(self):
        """An empty goal raises BadParameter."""
        with pytest.raises(typer.BadParameter):
            _validate_goal("")

    def test_rejects_whitespace_goal(self):
        """A whitespace-only goal raises BadParameter."""
        with pytest.raises(typer.BadParameter):
            _validate_goal("   \t ")


class TestValidateBudget:
    """Unit tests for the _validate_budget callback."""

    def test_accepts_positive_budget(self):
        """A positive budget passes through unchanged."""
        assert _validate_budget(5.0) == 5.0

    def test_accepts_none_budget(self):
        """An unset budget (None) is allowed."""
        assert _validate_budget(None) is None

    def test_rejects_zero_budget(self):
        """A zero budget raises BadParameter."""
        with pytest.raises(typer.BadParameter):
            _validate_budget(0)

    def test_rejects_negative_budget(self):
        """A negative budget raises BadParameter."""
        with pytest.raises(typer.BadParameter):
            _validate_budget(-1.5)


def _live_start_flags() -> set[str]:
    """Every long flag the live ``start`` command accepts."""
    start = getattr(typer.main.get_command(app), "commands")["start"]  # noqa: B009
    flags: set[str] = set()
    for param in start.params:
        # Typer vendors click, so duck-type: the goal Argument has no "--" opts.
        names = (*getattr(param, "opts", []), *getattr(param, "secondary_opts", []))
        flags.update(n for n in names if n.startswith("--"))
    return flags


def _readme_start_table_flags() -> set[str]:
    """Long flags named in the Start Options table of the README."""
    text = README.read_text(encoding="utf-8")
    section = text.split("### Start Options", 1)[1]
    section = re.split(r"^#{3,4} ", section, maxsplit=1, flags=re.MULTILINE)[0]
    flags: set[str] = set()
    for line in section.splitlines():
        if line.startswith("|"):
            first_cell = line.split("|")[1]
            flags.update(re.findall(r"--[a-z][a-z0-9-]*", first_cell))
    return flags


class TestStartOptionsDocumented:
    """The README Start Options table must not drift from the live command."""

    def test_every_start_flag_is_in_readme_table(self):
        """A start option missing from the README table fails this test."""
        live = _live_start_flags() - _UNDOCUMENTED_START_FLAGS
        missing = sorted(live - _readme_start_table_flags())
        assert not missing, f"README 'Start Options' table is missing: {', '.join(missing)}"

    def test_readme_table_names_no_unknown_flag(self):
        """A flag documented in the table must still exist on the command."""
        unknown = sorted(_readme_start_table_flags() - _live_start_flags())
        assert not unknown, f"README table lists removed flags: {', '.join(unknown)}"


class TestStartInputValidation:
    """End-to-end parse-time rejection of invalid start options."""

    def test_max_sessions_zero_rejected(self, cli_runner):
        """--max-sessions 0 is rejected at parse time (not treated as unlimited)."""
        result = cli_runner.invoke(app, ["start", "Task", "--max-sessions", "0"])
        assert result.exit_code == 2
        assert "max-sessions" in _normalize(result.output)

    def test_max_sessions_negative_rejected(self, cli_runner):
        """A negative --max-sessions is rejected at parse time."""
        result = cli_runner.invoke(app, ["start", "Task", "--max-sessions", "-1"])
        assert result.exit_code == 2

    def test_max_prs_zero_rejected(self, cli_runner):
        """--prs 0 is rejected at parse time."""
        result = cli_runner.invoke(app, ["start", "Task", "--prs", "0"])
        assert result.exit_code == 2
        assert "prs" in _normalize(result.output)

    def test_budget_zero_rejected(self, cli_runner):
        """--budget 0 is rejected at parse time with a clear message."""
        result = cli_runner.invoke(app, ["start", "Task", "--budget", "0"])
        assert result.exit_code == 2
        assert "greater than 0" in _normalize(result.output)

    def test_budget_negative_rejected(self, cli_runner):
        """A negative --budget is rejected at parse time."""
        result = cli_runner.invoke(app, ["start", "Task", "--budget", "-2.5"])
        assert result.exit_code == 2

    def test_empty_goal_rejected(self, cli_runner):
        """An empty goal argument is rejected at parse time."""
        result = cli_runner.invoke(app, ["start", ""])
        assert result.exit_code == 2
        assert "goal must not be empty" in _normalize(result.output)

    def test_whitespace_goal_rejected(self, cli_runner):
        """A whitespace-only goal argument is rejected at parse time."""
        result = cli_runner.invoke(app, ["start", "   "])
        assert result.exit_code == 2
        assert "goal must not be empty" in _normalize(result.output)
