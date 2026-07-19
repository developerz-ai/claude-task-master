"""Tests for start-command input validation in cli_commands.workflow."""

from __future__ import annotations

import re

import pytest
import typer

from claude_task_master.cli import app
from claude_task_master.cli_commands.workflow import _validate_budget, _validate_goal


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
