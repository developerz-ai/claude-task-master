"""Which PR merge-pr operates on, including the opt-in "open one" path."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest
import typer

from claude_task_master.cli_commands.pr_resolution import resolve_pr_number

MODULE = "claude_task_master.cli_commands.pr_resolution"


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["cmd"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestExplicitInput:
    def test_number_wins_without_touching_git(self) -> None:
        client = MagicMock()
        assert resolve_pr_number(client, "52") == 52
        client.get_pr_for_current_branch.assert_not_called()

    def test_url_is_parsed(self) -> None:
        client = MagicMock()
        assert resolve_pr_number(client, "https://github.com/owner/repo/pull/52") == 52

    def test_garbage_input_exits(self) -> None:
        client = MagicMock()
        with pytest.raises(typer.Exit) as exc:
            resolve_pr_number(client, "not-a-pr")
        assert exc.value.exit_code == 1


class TestCurrentBranch:
    def test_detects_branch_pr(self) -> None:
        client = MagicMock()
        client.get_pr_for_current_branch.return_value = 9
        assert resolve_pr_number(client, None) == 9


class TestBranchWithoutPR:
    """A branch with no PR: report by default, open one only when asked."""

    @patch(f"{MODULE}.subprocess.run")
    @patch(f"{MODULE}.get_current_branch", return_value="feature/x")
    def test_no_pr_reports_and_creates_nothing(
        self, _branch: MagicMock, run: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        client = MagicMock()
        client.get_pr_for_current_branch.return_value = None

        with pytest.raises(typer.Exit) as exc:
            resolve_pr_number(client, None)
        assert exc.value.exit_code == 1
        run.assert_not_called()
        assert "--create-pr" in capsys.readouterr().out

    @patch(f"{MODULE}.pending_changes_summary", return_value="")
    @patch(f"{MODULE}.run_git")
    @patch(f"{MODULE}.subprocess.run")
    @patch(f"{MODULE}.get_current_branch", return_value="feature/x")
    def test_create_pr_pushes_and_opens(
        self,
        _branch: MagicMock,
        run: MagicMock,
        run_git: MagicMock,
        _pending: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        client = MagicMock()
        client.get_pr_for_current_branch.return_value = None
        run_git.return_value = _proc()
        run.return_value = _proc(stdout="https://github.com/owner/repo/pull/77\n")

        assert resolve_pr_number(client, None, create_pr=True) == 77
        assert run_git.call_args.args[:3] == ("push", "-u", "origin")
        assert run.call_args.args[0] == ["gh", "pr", "create", "--fill"]
        output = capsys.readouterr().out
        assert "OPENED PR #77" in output
        assert "WILL BE OPENED" in output

    @patch(f"{MODULE}.pending_changes_summary", return_value="")
    @patch(f"{MODULE}.run_git")
    @patch(f"{MODULE}.subprocess.run")
    @patch(f"{MODULE}.get_current_branch", return_value="feature/x")
    def test_failed_push_never_creates_a_pr(
        self,
        _branch: MagicMock,
        run: MagicMock,
        run_git: MagicMock,
        _pending: MagicMock,
    ) -> None:
        client = MagicMock()
        client.get_pr_for_current_branch.return_value = None
        run_git.return_value = _proc(returncode=1, stderr="rejected")

        with pytest.raises(typer.Exit) as exc:
            resolve_pr_number(client, None, create_pr=True)
        assert exc.value.exit_code == 1
        run.assert_not_called()

    @patch(f"{MODULE}.pending_changes_summary", return_value="")
    @patch(f"{MODULE}.run_git")
    @patch(f"{MODULE}.subprocess.run")
    @patch(f"{MODULE}.get_current_branch", return_value="feature/x")
    def test_failed_creation_exits(
        self,
        _branch: MagicMock,
        run: MagicMock,
        run_git: MagicMock,
        _pending: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        client = MagicMock()
        client.get_pr_for_current_branch.return_value = None
        run_git.return_value = _proc()
        run.return_value = _proc(returncode=1, stderr="No commits between main and feature/x")

        with pytest.raises(typer.Exit) as exc:
            resolve_pr_number(client, None, create_pr=True)
        assert exc.value.exit_code == 1
        assert "No commits between" in capsys.readouterr().out

    @patch(f"{MODULE}.subprocess.run")
    @patch(f"{MODULE}.get_current_branch", return_value="main")
    def test_create_pr_refuses_on_default_branch(self, _branch: MagicMock, run: MagicMock) -> None:
        client = MagicMock()
        client.get_pr_for_current_branch.return_value = None

        with pytest.raises(typer.Exit) as exc:
            resolve_pr_number(client, None, create_pr=True)
        assert exc.value.exit_code == 1
        run.assert_not_called()
