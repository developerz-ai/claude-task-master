"""Tests for the pr CLI command."""

from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.cli import app
from claude_task_master.github.client_pr import PRStatus


class TestPRCommand:
    """Tests for the pr command."""

    def test_pr_no_pr_found(self, cli_runner, tmp_path, monkeypatch):
        """Test pr when no PR found for current branch."""
        monkeypatch.chdir(tmp_path)

        # Mock StateManager.exists() to return False (no task state)
        # Mock GitHubClient.get_pr_for_current_branch() to return None
        with (
            patch("claude_task_master.core.state.StateManager.exists", return_value=False),
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_for_current_branch",
                return_value=None,
            ),
        ):
            mock_check.return_value = None

            result = cli_runner.invoke(app, ["pr"])

        assert result.exit_code == 1
        assert "No PR found" in result.output

    def test_pr_with_specified_pr_number(self, cli_runner, tmp_path, monkeypatch):
        """Test pr with explicitly specified PR number."""
        monkeypatch.chdir(tmp_path)

        mock_pr_status = PRStatus(
            number=123,
            state="OPEN",
            ci_state="SUCCESS",
            unresolved_threads=0,
            resolved_threads=2,
            total_threads=2,
            checks_passed=5,
            checks_failed=0,
            checks_pending=0,
            checks_skipped=0,
            check_details=[],
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            base_branch="main",
        )

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_status",
                return_value=mock_pr_status,
            ),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_check.return_value = None

            # Mock gh pr view for title/url
            mock_subprocess.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Test PR", "url": "https://github.com/test/test/pull/123", "state": "OPEN", "isDraft": false}',
            )

            result = cli_runner.invoke(app, ["pr", "-p", "123"])

        assert result.exit_code == 0
        assert "#123" in result.output
        assert "Test PR" in result.output
        assert "SUCCESS" in result.output
        assert "MERGEABLE" in result.output
        assert "CLEAN" in result.output

    def test_pr_from_task_state(self, cli_runner, tmp_path, monkeypatch):
        """Test pr gets PR number from task state."""
        monkeypatch.chdir(tmp_path)

        mock_pr_status = PRStatus(
            number=456,
            state="OPEN",
            ci_state="PENDING",
            unresolved_threads=1,
            resolved_threads=0,
            total_threads=1,
            checks_passed=2,
            checks_failed=0,
            checks_pending=1,
            checks_skipped=0,
            check_details=[],
            mergeable="UNKNOWN",
            merge_state_status="BLOCKED",
            base_branch="main",
        )

        mock_state = MagicMock()
        mock_state.current_pr = 456

        with (
            patch("claude_task_master.core.state.StateManager.exists", return_value=True),
            patch(
                "claude_task_master.core.state.StateManager.load_state",
                return_value=mock_state,
            ),
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_status",
                return_value=mock_pr_status,
            ),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_check.return_value = None

            mock_subprocess.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "State PR", "url": "https://github.com/test/test/pull/456", "state": "OPEN", "isDraft": false}',
            )

            result = cli_runner.invoke(app, ["pr"])

        assert result.exit_code == 0
        assert "#456" in result.output
        assert "PENDING" in result.output
        assert "Unresolved" in result.output

    def test_pr_with_failed_checks(self, cli_runner, tmp_path, monkeypatch):
        """Test pr displays failed checks properly."""
        monkeypatch.chdir(tmp_path)

        mock_pr_status = PRStatus(
            number=789,
            state="OPEN",
            ci_state="FAILURE",
            unresolved_threads=0,
            resolved_threads=0,
            total_threads=0,
            checks_passed=3,
            checks_failed=2,
            checks_pending=0,
            checks_skipped=0,
            check_details=[
                {
                    "name": "lint",
                    "conclusion": "SUCCESS",
                    "url": "https://github.com/test/actions/1",
                },
                {
                    "name": "tests",
                    "conclusion": "FAILURE",
                    "url": "https://github.com/test/actions/2",
                },
                {
                    "name": "build",
                    "conclusion": "ERROR",
                    "url": "https://github.com/test/actions/3",
                },
            ],
            mergeable="MERGEABLE",
            merge_state_status="UNSTABLE",
            base_branch="develop",
        )

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_status",
                return_value=mock_pr_status,
            ),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_check.return_value = None

            mock_subprocess.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Failed PR", "url": "https://github.com/test/test/pull/789", "state": "OPEN", "isDraft": false}',
            )

            result = cli_runner.invoke(app, ["pr", "-p", "789"])

        assert result.exit_code == 0
        assert "FAILURE" in result.output
        assert "Failed Checks" in result.output
        assert "tests" in result.output
        assert "build" in result.output

    def test_pr_draft_status(self, cli_runner, tmp_path, monkeypatch):
        """Test pr displays draft status."""
        monkeypatch.chdir(tmp_path)

        mock_pr_status = PRStatus(
            number=100,
            state="OPEN",
            ci_state="SUCCESS",
            unresolved_threads=0,
            resolved_threads=0,
            total_threads=0,
            checks_passed=1,
            checks_failed=0,
            checks_pending=0,
            checks_skipped=0,
            check_details=[],
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            base_branch="main",
        )

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_status",
                return_value=mock_pr_status,
            ),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_check.return_value = None

            mock_subprocess.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Draft PR", "url": "https://github.com/test/test/pull/100", "state": "OPEN", "isDraft": true}',
            )

            result = cli_runner.invoke(app, ["pr", "-p", "100"])

        assert result.exit_code == 0
        assert "Draft" in result.output
        assert "Yes" in result.output

    def test_pr_github_error(self, cli_runner, tmp_path, monkeypatch):
        """Test pr handles GitHub errors gracefully."""
        monkeypatch.chdir(tmp_path)

        from claude_task_master.github.exceptions import GitHubError

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_status",
                side_effect=GitHubError("PR not found", command=["gh", "pr", "view"], exit_code=1),
            ),
        ):
            mock_check.return_value = None

            result = cli_runner.invoke(app, ["pr", "-p", "999"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_pr_from_current_branch(self, cli_runner, tmp_path, monkeypatch):
        """Test pr gets PR from current branch when no state."""
        monkeypatch.chdir(tmp_path)

        mock_pr_status = PRStatus(
            number=200,
            state="OPEN",
            ci_state="SUCCESS",
            unresolved_threads=0,
            resolved_threads=0,
            total_threads=0,
            checks_passed=3,
            checks_failed=0,
            checks_pending=0,
            checks_skipped=0,
            check_details=[],
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            base_branch="main",
        )

        with (
            patch("claude_task_master.core.state.StateManager.exists", return_value=False),
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_for_current_branch",
                return_value=200,
            ),
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_status",
                return_value=mock_pr_status,
            ),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_check.return_value = None

            mock_subprocess.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Branch PR", "url": "https://github.com/test/test/pull/200", "state": "OPEN", "isDraft": false}',
            )

            result = cli_runner.invoke(app, ["pr"])

        assert result.exit_code == 0
        assert "#200" in result.output
        assert "Branch PR" in result.output

    def test_pr_merged_state(self, cli_runner, tmp_path, monkeypatch):
        """Test pr displays merged state correctly."""
        monkeypatch.chdir(tmp_path)

        mock_pr_status = PRStatus(
            number=300,
            state="MERGED",
            ci_state="SUCCESS",
            unresolved_threads=0,
            resolved_threads=3,
            total_threads=3,
            checks_passed=5,
            checks_failed=0,
            checks_pending=0,
            checks_skipped=1,
            check_details=[],
            mergeable="UNKNOWN",
            merge_state_status="UNKNOWN",
            base_branch="main",
        )

        with (
            patch("claude_task_master.github.client.GitHubClient._check_gh_cli") as mock_check,
            patch(
                "claude_task_master.github.client.GitHubClient.get_pr_status",
                return_value=mock_pr_status,
            ),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_check.return_value = None

            mock_subprocess.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Merged PR", "url": "https://github.com/test/test/pull/300", "state": "MERGED", "isDraft": false}',
            )

            result = cli_runner.invoke(app, ["pr", "-p", "300"])

        assert result.exit_code == 0
        assert "MERGED" in result.output
        assert "Skipped" in result.output


@pytest.fixture
def cli_runner():
    """Provide a Typer CLI test runner."""
    from typer.testing import CliRunner

    return CliRunner()
