"""Tests for merge-pr CLI command (and fix-pr alias)."""

import re
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.cli_commands.fix_pr import _parse_pr_input

runner = CliRunner()

# Use merge-pr as the primary command in tests
COMMAND = "merge-pr"


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_pattern.sub("", text)


class TestParsePRInput:
    """Tests for _parse_pr_input function."""

    def test_none_input(self) -> None:
        """Should return None for None input."""
        assert _parse_pr_input(None) is None

    def test_plain_number(self) -> None:
        """Should parse plain number."""
        assert _parse_pr_input("123") == 123
        assert _parse_pr_input("1") == 1
        assert _parse_pr_input("99999") == 99999

    def test_github_url(self) -> None:
        """Should parse GitHub PR URL."""
        assert _parse_pr_input("https://github.com/owner/repo/pull/123") == 123
        assert _parse_pr_input("https://github.com/foo/bar/pull/1") == 1

    def test_hash_prefix(self) -> None:
        """Should parse number with # prefix."""
        assert _parse_pr_input("#123") == 123
        assert _parse_pr_input("#1") == 1

    def test_invalid_input(self) -> None:
        """Should return None for invalid input."""
        assert _parse_pr_input("abc") is None
        assert _parse_pr_input("not-a-number") is None
        assert _parse_pr_input("#abc") is None


class TestMergePRCommand:
    """Tests for merge-pr CLI command."""

    def test_help(self) -> None:
        """Should display help."""
        result = runner.invoke(app, [COMMAND, "--help"])
        output = strip_ansi(result.stdout)
        assert result.exit_code == 0
        assert "Monitor a PR" in output
        assert "--max-iterations" in output
        assert "--no-merge" in output

    def test_fix_pr_alias_works(self) -> None:
        """fix-pr should work as a hidden alias."""
        result = runner.invoke(app, ["fix-pr", "--help"])
        assert result.exit_code == 0

    @patch("claude_task_master.cli_commands.fix_pr.get_current_branch", return_value="main")
    def test_rejects_default_branch(self, mock_branch: MagicMock) -> None:
        """Should error when on main/master branch with no PR arg."""
        result = runner.invoke(app, [COMMAND])
        assert result.exit_code == 1
        output = strip_ansi(result.stdout)
        assert "default branch" in output

    @patch("claude_task_master.cli_commands.fix_pr.get_current_branch", return_value="master")
    def test_rejects_master_branch(self, mock_branch: MagicMock) -> None:
        """Should error when on master branch with no PR arg."""
        result = runner.invoke(app, [COMMAND])
        assert result.exit_code == 1
        output = strip_ansi(result.stdout)
        assert "default branch" in output

    @patch("claude_task_master.cli_commands.fix_pr.get_current_branch", return_value="feature/foo")
    @patch("claude_task_master.github.GitHubClient")
    def test_no_pr_for_branch_fails(
        self, mock_github_class: MagicMock, mock_branch: MagicMock
    ) -> None:
        """Should fail when no PR found for current branch."""
        mock_github = MagicMock()
        mock_github.get_pr_for_current_branch.return_value = None
        mock_github_class.return_value = mock_github

        result = runner.invoke(app, [COMMAND])
        assert result.exit_code == 1
        assert "No PR found" in result.stdout

    @patch("claude_task_master.cli_commands.fix_pr.get_current_branch", return_value="feature/foo")
    @patch("claude_task_master.cli_commands.fix_pr.StateManager")
    @patch("claude_task_master.cli_commands.fix_pr.CredentialManager")
    @patch("claude_task_master.github.GitHubClient")
    def test_detects_pr_from_branch(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
        mock_branch: MagicMock,
    ) -> None:
        """Should detect PR from current branch."""
        mock_github = MagicMock()
        mock_github.get_pr_for_current_branch.return_value = 52
        # Make get_pr_status raise to exit early
        mock_github.get_pr_status.side_effect = Exception("test exit")
        mock_github_class.return_value = mock_github

        # Mock credential manager to return a valid token
        mock_cred_class.return_value.get_valid_token.return_value = "test-token"

        # Mock state manager
        mock_state = MagicMock()
        mock_state.is_session_active.return_value = False
        mock_state.acquire_session_lock.return_value = True
        mock_state_class.return_value = mock_state

        result = runner.invoke(app, [COMMAND])
        # Will fail due to exception, but should have detected PR
        assert "Detected PR #52" in result.stdout

    @patch("claude_task_master.cli_commands.fix_pr.StateManager")
    @patch("claude_task_master.cli_commands.fix_pr.CredentialManager")
    @patch("claude_task_master.github.GitHubClient")
    def test_max_iterations_option(
        self,
        mock_github_class: MagicMock,
        mock_cred_class: MagicMock,
        mock_state_class: MagicMock,
    ) -> None:
        """Should accept max-iterations option."""
        mock_github = MagicMock()
        mock_github.get_pr_for_current_branch.return_value = None
        # Make get_pr_status raise to exit early (simulates reaching the loop)
        mock_github.get_pr_status.side_effect = Exception("test exit")
        mock_github_class.return_value = mock_github

        # Mock credential manager to return a valid token
        mock_cred_class.return_value.get_valid_token.return_value = "test-token"

        # Mock state manager
        mock_state = MagicMock()
        mock_state.is_session_active.return_value = False
        mock_state.acquire_session_lock.return_value = True
        mock_state_class.return_value = mock_state

        result = runner.invoke(app, [COMMAND, "123", "-m", "5"])
        # Will fail due to exception but should parse the option
        assert result.exit_code != 0
        assert "Max iterations: 5" in result.stdout
