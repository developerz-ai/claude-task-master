"""Tests for git_exclude — repo-local exclusion of the state directory."""

from __future__ import annotations

import subprocess
from pathlib import Path

from claude_task_master.core.git_exclude import ensure_state_dir_git_excluded


def _git_init(path: Path) -> None:
    """Initialize a bare-minimum git repo at *path* for testing."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True, timeout=10)


class TestEnsureStateDirGitExcluded:
    """Tests for ensure_state_dir_git_excluded."""

    def test_adds_entry_in_git_repo(self, temp_dir: Path) -> None:
        """The state dir is appended to .git/info/exclude in a git repo."""
        _git_init(temp_dir)
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir()

        assert ensure_state_dir_git_excluded(state_dir) is True

        exclude = (temp_dir / ".git" / "info" / "exclude").read_text()
        assert ".claude-task-master/" in exclude.splitlines()

    def test_idempotent_no_duplicate(self, temp_dir: Path) -> None:
        """Running twice does not duplicate the entry."""
        _git_init(temp_dir)
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir()

        assert ensure_state_dir_git_excluded(state_dir) is True
        assert ensure_state_dir_git_excluded(state_dir) is True

        exclude = (temp_dir / ".git" / "info" / "exclude").read_text()
        assert exclude.count(".claude-task-master/") == 1

    def test_preserves_existing_content(self, temp_dir: Path) -> None:
        """Existing exclude lines are kept when appending."""
        _git_init(temp_dir)
        exclude_path = temp_dir / ".git" / "info" / "exclude"
        exclude_path.write_text("*.log\nbuild/\n")
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir()

        assert ensure_state_dir_git_excluded(state_dir) is True

        lines = exclude_path.read_text().splitlines()
        assert "*.log" in lines
        assert "build/" in lines
        assert ".claude-task-master/" in lines

    def test_appends_on_own_line_without_trailing_newline(self, temp_dir: Path) -> None:
        """A file with no trailing newline still gets the entry on its own line."""
        _git_init(temp_dir)
        exclude_path = temp_dir / ".git" / "info" / "exclude"
        exclude_path.write_text("*.log")  # no trailing newline
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir()

        assert ensure_state_dir_git_excluded(state_dir) is True

        lines = exclude_path.read_text().splitlines()
        assert lines[0] == "*.log"
        assert ".claude-task-master/" in lines

    def test_non_git_dir_returns_false(self, temp_dir: Path) -> None:
        """Outside a git repo the helper reports False and never raises."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir()

        assert ensure_state_dir_git_excluded(state_dir) is False

    def test_git_binary_missing_returns_false(self, temp_dir: Path, monkeypatch) -> None:
        """A missing git binary is tolerated (returns False, no raise)."""

        def _boom(*_args, **_kwargs):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(subprocess, "run", _boom)
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir()

        assert ensure_state_dir_git_excluded(state_dir) is False
