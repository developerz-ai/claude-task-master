"""Tests for the comments CLI command."""

from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.cli import app


class TestCommentsCommand:
    """Tests for the comments command."""

    def test_comments_no_pr_found(self, cli_runner, tmp_path, monkeypatch):
        """Test comments returns failure when no PR is found."""
        monkeypatch.chdir(tmp_path)

        with (
            patch("claude_task_master.core.state.StateManager.exists", return_value=False),
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_for_current_branch",
                return_value=None,
            ),
        ):
            mock_check.return_value = None

            result = cli_runner.invoke(app, ["comments"])

        assert result.exit_code == 1
        assert "No PR found" in result.output

    def test_comments_with_pr_option_shows_comments(self, cli_runner, tmp_path, monkeypatch):
        """Test comments with --pr option shows PR comments."""
        monkeypatch.chdir(tmp_path)

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_comments",
                return_value="**alice** on src/main.py:10\nPlease add a docstring\n",
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_check.return_value = None

            # Mock gh pr view for PR info
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Test PR", "url": "https://github.com/owner/repo/pull/123"}',
            )

            result = cli_runner.invoke(app, ["comments", "--pr", "123"])

        assert result.exit_code == 0
        assert "PR Review Comments" in result.output
        assert "#123" in result.output
        assert "Test PR" in result.output

    def test_comments_with_no_comments(self, cli_runner, tmp_path, monkeypatch):
        """Test comments when there are no comments."""
        monkeypatch.chdir(tmp_path)

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_comments",
                return_value="",
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_check.return_value = None

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Test PR", "url": "https://github.com/owner/repo/pull/123"}',
            )

            result = cli_runner.invoke(app, ["comments", "--pr", "123"])

        assert result.exit_code == 0
        assert "No unresolved review comments" in result.output

    def test_comments_all_option_shows_resolved(self, cli_runner, tmp_path, monkeypatch):
        """Test comments --all shows all comments including resolved."""
        monkeypatch.chdir(tmp_path)

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_comments",
                return_value="",
            ) as mock_get_comments,
            patch("subprocess.run") as mock_run,
        ):
            mock_check.return_value = None

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Test PR", "url": "https://github.com/owner/repo/pull/123"}',
            )

            result = cli_runner.invoke(app, ["comments", "--pr", "123", "--all"])

        # Verify that get_pr_comments was called with only_unresolved=False
        mock_get_comments.assert_called_once_with(123, only_unresolved=False)
        assert result.exit_code == 0
        assert "Filter:" in result.output and "all" in result.output

    def test_comments_from_current_branch(self, cli_runner, tmp_path, monkeypatch):
        """Test comments gets PR from current branch when not in state."""
        monkeypatch.chdir(tmp_path)

        with (
            patch("claude_task_master.core.state.StateManager.exists", return_value=False),
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_for_current_branch",
                return_value=456,
            ),
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_comments",
                return_value="",
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_check.return_value = None

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Feature PR", "url": "https://github.com/owner/repo/pull/456"}',
            )

            result = cli_runner.invoke(app, ["comments"])

        assert result.exit_code == 0
        assert "#456" in result.output

    def test_comments_from_task_state(self, cli_runner, tmp_path, monkeypatch):
        """Test comments gets PR from task state when available."""
        monkeypatch.chdir(tmp_path)

        mock_state = MagicMock()
        mock_state.current_pr = 789

        with (
            patch("claude_task_master.core.state.StateManager.exists", return_value=True),
            patch(
                "claude_task_master.core.state.StateManager.load_state",
                return_value=mock_state,
            ),
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_comments",
                return_value="",
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_check.return_value = None

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "State PR", "url": "https://github.com/owner/repo/pull/789"}',
            )

            result = cli_runner.invoke(app, ["comments"])

        assert result.exit_code == 0
        assert "#789" in result.output

    def test_comments_github_error(self, cli_runner, tmp_path, monkeypatch):
        """Test comments handles GitHub errors gracefully."""
        monkeypatch.chdir(tmp_path)

        from claude_task_master.github.exceptions import GitHubError

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_comments",
                side_effect=GitHubError(
                    "API rate limit exceeded", command=["gh", "api"], exit_code=1
                ),
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_check.return_value = None

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Test PR", "url": "https://github.com/owner/repo/pull/123"}',
            )

            result = cli_runner.invoke(app, ["comments", "--pr", "123"])

        assert result.exit_code == 1
        assert "Error fetching PR comments" in result.output

    def test_comments_multiple_comments_displayed(self, cli_runner, tmp_path, monkeypatch):
        """Test comments displays multiple comments in panels."""
        monkeypatch.chdir(tmp_path)

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_comments",
                return_value=(
                    "**alice** on src/main.py:10\nPlease add a docstring\n"
                    "\n---\n\n"
                    "**bob** on src/utils.py:25\nConsider using a context manager\n"
                ),
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_check.return_value = None

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Test PR", "url": "https://github.com/owner/repo/pull/123"}',
            )

            result = cli_runner.invoke(app, ["comments", "--pr", "123"])

        assert result.exit_code == 0
        # Comments are displayed in panels
        assert "Comment 1" in result.output
        assert "Comment 2" in result.output

    def test_comments_short_options(self, cli_runner, tmp_path, monkeypatch):
        """Test comments with short option flags."""
        monkeypatch.chdir(tmp_path)

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_comments",
                return_value="",
            ) as mock_get_comments,
            patch("subprocess.run") as mock_run,
        ):
            mock_check.return_value = None

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Test PR", "url": "https://github.com/owner/repo/pull/123"}',
            )

            result = cli_runner.invoke(app, ["comments", "-p", "123", "-a"])

        mock_get_comments.assert_called_once_with(123, only_unresolved=False)
        assert result.exit_code == 0

    def test_comments_no_comments_with_all_option(self, cli_runner, tmp_path, monkeypatch):
        """Test comments --all when there are no comments shows different message."""
        monkeypatch.chdir(tmp_path)

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_comments",
                return_value="",
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_check.return_value = None

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Test PR", "url": "https://github.com/owner/repo/pull/123"}',
            )

            result = cli_runner.invoke(app, ["comments", "--pr", "123", "--all"])

        assert result.exit_code == 0
        assert "No review comments on this PR" in result.output


@pytest.fixture
def cli_runner():
    """Provide a Typer CLI test runner."""
    from typer.testing import CliRunner

    return CliRunner()
