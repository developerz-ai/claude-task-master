"""Tests for GitHub client error handling - timeout, auth, network, and validation errors."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.github.client import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubMergeError,
    GitHubNotFoundError,
    GitHubTimeoutError,
    PRStatus,
)

# =============================================================================
# GitHubClient Initialization Error Tests
# =============================================================================


class TestGitHubClientInitErrors:
    """Tests for GitHubClient initialization and gh CLI check errors."""

    def test_init_gh_cli_authenticated(self):
        """Test initialization when gh CLI is authenticated."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            client = GitHubClient()
            mock_run.assert_called_once_with(
                ["gh", "auth", "status"],
                timeout=10,
                check=False,
                capture_output=True,
                text=True,
            )
            assert client is not None

    def test_init_gh_cli_not_authenticated(self):
        """Test initialization when gh CLI is not authenticated."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not logged in")
            with pytest.raises(GitHubAuthError) as exc_info:
                GitHubClient()
            assert "gh CLI not authenticated" in str(exc_info.value)
            assert "gh auth login" in str(exc_info.value)

    def test_init_gh_cli_not_installed(self):
        """Test initialization when gh CLI is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("gh not found")
            with pytest.raises(GitHubNotFoundError) as exc_info:
                GitHubClient()
            error_msg = str(exc_info.value)
            assert "gh CLI not installed" in error_msg
            # Check that the GitHub CLI URL is mentioned
            import re

            assert re.search(r"https://cli\.github\.com/?", error_msg), (
                f"Expected GitHub CLI URL in error message: {error_msg}"
            )

    def test_init_gh_cli_timeout(self):
        """Test initialization when gh auth check times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("gh auth status", 10)
            with pytest.raises(GitHubTimeoutError) as exc_info:
                GitHubClient()
            assert "timed out" in str(exc_info.value)

    def test_init_gh_cli_auth_expired(self):
        """Test initialization when gh CLI auth is expired."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="authentication token expired"
            )
            with pytest.raises(GitHubAuthError):
                GitHubClient()


# =============================================================================
# GitHubError Exception Tests
# =============================================================================


class TestGitHubErrorExceptions:
    """Tests for GitHubError exception classes."""

    def test_github_error_basic(self):
        """Test basic GitHubError creation."""
        error = GitHubError("Test error message")
        assert str(error) == "Test error message"
        assert error.message == "Test error message"
        assert error.command is None
        assert error.exit_code is None

    def test_github_error_with_command(self):
        """Test GitHubError with command info."""
        error = GitHubError(
            "Command failed",
            command=["gh", "pr", "create"],
            exit_code=1,
        )
        assert error.message == "Command failed"
        assert error.command == ["gh", "pr", "create"]
        assert error.exit_code == 1

    def test_github_timeout_error_inheritance(self):
        """Test GitHubTimeoutError inherits from GitHubError."""
        error = GitHubTimeoutError("Timed out")
        assert isinstance(error, GitHubError)
        assert str(error) == "Timed out"

    def test_github_auth_error_inheritance(self):
        """Test GitHubAuthError inherits from GitHubError."""
        error = GitHubAuthError("Not authenticated")
        assert isinstance(error, GitHubError)
        assert str(error) == "Not authenticated"

    def test_github_not_found_error_inheritance(self):
        """Test GitHubNotFoundError inherits from GitHubError."""
        error = GitHubNotFoundError("Not found")
        assert isinstance(error, GitHubError)
        assert str(error) == "Not found"

    def test_github_merge_error_inheritance(self):
        """Test GitHubMergeError inherits from GitHubError."""
        error = GitHubMergeError("Merge failed")
        assert isinstance(error, GitHubError)
        assert str(error) == "Merge failed"

    def test_github_error_exception_chaining(self):
        """Test GitHubError can chain exceptions properly."""
        original = ValueError("Original error")
        try:
            raise GitHubError("Wrapped error") from original
        except GitHubError as e:
            assert e.__cause__ is original


# =============================================================================
# Timeout Error Tests
# =============================================================================


class TestTimeoutErrors:
    """Tests for timeout handling across all operations."""

    def test_create_pr_timeout(self, github_client):
        """Test PR creation timeout raises GitHubTimeoutError."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=60)
            with pytest.raises(GitHubTimeoutError) as exc_info:
                github_client.create_pr("Title", "Body")
            assert "timed out" in str(exc_info.value)

    def test_get_pr_status_timeout(self, github_client):
        """Test PR status retrieval timeout."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired("gh api", 30)
                with pytest.raises(GitHubTimeoutError) as exc_info:
                    github_client.get_pr_status(123)
                assert "timed out" in str(exc_info.value)

    def test_get_pr_comments_timeout(self, github_client):
        """Test PR comments retrieval timeout."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired("gh api", 30)
                with pytest.raises(GitHubTimeoutError):
                    github_client.get_pr_comments(123)

    def test_merge_pr_timeout_auto(self, github_client):
        """Test merge timeout during auto-merge attempt."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("gh pr merge", 15)
            with pytest.raises(GitHubMergeError) as exc_info:
                github_client.merge_pr(123)
            assert "timed out" in str(exc_info.value)

    def test_merge_pr_timeout_direct(self, github_client):
        """Test merge timeout during direct merge attempt."""
        with patch("subprocess.run") as mock_run:
            # First call (auto) fails normally, second (direct) times out
            mock_run.side_effect = [
                MagicMock(returncode=1, stdout="", stderr="auto-merge not allowed"),
                subprocess.TimeoutExpired("gh pr merge", 30),
            ]
            with pytest.raises(GitHubMergeError) as exc_info:
                github_client.merge_pr(123)
            assert "timed out" in str(exc_info.value)

    def test_get_repo_info_timeout(self, github_client):
        """Test repo info timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("gh repo view", 15)
            with pytest.raises(GitHubTimeoutError) as exc_info:
                github_client._get_repo_info()
            assert "timed out" in str(exc_info.value)

    def test_get_workflow_runs_timeout(self, github_client):
        """Test workflow runs retrieval timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("gh run list", 30)
            with pytest.raises(GitHubTimeoutError):
                github_client.get_workflow_runs()

    def test_get_workflow_run_status_timeout(self, github_client):
        """Test workflow run status timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("gh run view", 30)
            with pytest.raises(GitHubTimeoutError):
                github_client.get_workflow_run_status(run_id=123)

    def test_get_failed_run_logs_timeout(self, github_client):
        """Test failed run logs timeout returns error message."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("gh run view", 60)
            result = github_client.get_failed_run_logs(run_id=123)
            assert "timed out" in result.lower() or "Error" in result


# =============================================================================
# JSON and Data Validation Error Tests
# =============================================================================


class TestJSONAndValidationErrors:
    """Tests for JSON parsing and data validation errors."""

    def test_get_pr_status_malformed_json(self, github_client):
        """Test PR status handles malformed JSON response."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="{ invalid json }",
                    stderr="",
                )
                with pytest.raises(json.JSONDecodeError):
                    github_client.get_pr_status(1)

    def test_get_pr_status_empty_response(self, github_client):
        """Test PR status with empty JSON response."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="",
                    stderr="",
                )
                with pytest.raises(json.JSONDecodeError):
                    github_client.get_pr_status(1)

    def test_get_pr_comments_malformed_json(self, github_client):
        """Test PR comments handles malformed JSON response."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="not valid json at all",
                    stderr="",
                )
                with pytest.raises(json.JSONDecodeError):
                    github_client.get_pr_comments(1)

    def test_get_workflow_runs_malformed_json(self, github_client):
        """Test workflow runs handles malformed JSON response."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="[{broken json",
                stderr="",
            )
            with pytest.raises(json.JSONDecodeError):
                github_client.get_workflow_runs()

    def test_get_workflow_run_status_malformed_json(self, github_client):
        """Test workflow run status handles malformed JSON response."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="status: broken",
                stderr="",
            )
            with pytest.raises(json.JSONDecodeError):
                github_client.get_workflow_run_status(run_id=123)

    def test_pr_status_missing_required_fields(self):
        """Test PRStatus model validation with missing fields."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PRStatus(  # type: ignore[call-arg]
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            )

    def test_pr_status_invalid_number_type(self):
        """Test PRStatus model validation with invalid number type."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PRStatus(
                number="not-a-number",  # type: ignore[arg-type]
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            )


# =============================================================================
# Network and System Error Tests
# =============================================================================


class TestNetworkAndSystemErrors:
    """Tests for network and system-level errors."""

    def test_create_pr_network_error(self, github_client):
        """Test PR creation handles network errors."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Network unreachable")
            with pytest.raises(OSError):
                github_client.create_pr("Title", "Body")

    def test_get_pr_status_network_error(self, github_client):
        """Test PR status handles network errors."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = OSError("Connection refused")
                with pytest.raises(OSError):
                    github_client.get_pr_status(123)

    def test_merge_pr_network_error(self, github_client):
        """Test merge handles network errors."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Network unreachable")
            with pytest.raises(OSError):
                github_client.merge_pr(123)

    def test_get_workflow_runs_network_error(self, github_client):
        """Test workflow runs handles network errors."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("DNS resolution failed")
            with pytest.raises(OSError):
                github_client.get_workflow_runs()

    def test_create_pr_subprocess_error(self, github_client):
        """Test PR creation handles subprocess errors."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "gh pr create", stderr="Error creating PR"
            )
            with pytest.raises(subprocess.CalledProcessError):
                github_client.create_pr("Title", "Body")

    def test_get_pr_status_subprocess_error(self, github_client):
        """Test PR status handles subprocess errors."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.CalledProcessError(
                    1, "gh api graphql", stderr="GraphQL error"
                )
                with pytest.raises(subprocess.CalledProcessError):
                    github_client.get_pr_status(123)


# =============================================================================
# gh CLI Command Error Tests
# =============================================================================


class TestGhCLICommandErrors:
    """Tests for gh CLI command-specific errors."""

    def test_create_pr_no_upstream(self, github_client):
        """Test PR creation when branch has no upstream."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="fatal: The current branch has no upstream branch",
            )
            with pytest.raises(GitHubError) as exc_info:
                github_client.create_pr("Title", "Body")
            assert "upstream" in str(exc_info.value).lower()

    def test_create_pr_already_exists(self, github_client):
        """Test PR creation when PR already exists for branch."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="a pull request for branch already exists",
            )
            with pytest.raises(GitHubError) as exc_info:
                github_client.create_pr("Title", "Body")
            assert "already exists" in str(exc_info.value)

    def test_get_repo_info_not_git_repo(self, github_client):
        """Test repo info when not in a git repository."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="not a git repository",
            )
            with pytest.raises(GitHubError) as exc_info:
                github_client._get_repo_info()
            assert "git repository" in str(exc_info.value).lower()

    def test_get_pr_for_current_branch_no_pr(self, github_client):
        """Test getting PR for current branch when no PR exists."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="no pull requests found for branch",
            )
            result = github_client.get_pr_for_current_branch()
            # Should return None, not raise
            assert result is None

    def test_get_pr_for_current_branch_timeout(self, github_client):
        """Test getting PR for current branch when request times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("gh pr view", 15)
            result = github_client.get_pr_for_current_branch()
            # Should return None on timeout, not raise
            assert result is None

    def test_get_workflow_runs_no_runs(self, github_client):
        """Test getting workflow runs when none exist."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="[]",
                stderr="",
            )
            runs = github_client.get_workflow_runs()
            assert runs == []

    def test_get_failed_run_logs_run_not_found(self, github_client):
        """Test getting logs when run doesn't exist."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Run not found",
            )
            result = github_client.get_failed_run_logs(run_id=999999)
            assert "Error getting logs" in result

    def test_get_failed_run_logs_no_failed_jobs(self, github_client):
        """Test getting failed logs when no jobs failed."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",  # No failed job logs
                stderr="",
            )
            result = github_client.get_failed_run_logs(run_id=123)
            # Should return empty or minimal output
            assert result == "" or "No" in result or result.strip() == ""


# =============================================================================
# Error Recovery and Edge Case Tests
# =============================================================================


class TestErrorRecoveryAndEdgeCases:
    """Tests for error recovery and edge case handling."""

    def test_merge_fallback_on_auto_merge_error(self, github_client):
        """Test merge falls back to direct merge when auto-merge fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=1, stdout="", stderr="auto-merge is not allowed"),
                MagicMock(returncode=0, stdout="", stderr=""),
            ]
            # Should not raise, should fall back
            github_client.merge_pr(123)
            assert mock_run.call_count == 2

    def test_merge_fallback_on_auto_not_enabled(self, github_client):
        """Test merge falls back when auto-merge is not enabled."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=1, stdout="", stderr="Auto-merge is not enabled"),
                MagicMock(returncode=0, stdout="", stderr=""),
            ]
            github_client.merge_pr(123)
            assert mock_run.call_count == 2

    def test_merge_both_attempts_fail(self, github_client):
        """Test merge raises error when both auto and direct fail."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Cannot merge: checks still pending",
            )
            with pytest.raises(GitHubMergeError) as exc_info:
                github_client.merge_pr(123)
            assert "Failed to merge" in str(exc_info.value)

    def test_get_failed_run_logs_without_run_id_no_failed(self, github_client):
        """Test getting failed logs without run_id when no failed runs."""
        runs_response = json.dumps(
            [
                {
                    "databaseId": 123,
                    "name": "CI",
                    "status": "completed",
                    "conclusion": "success",
                    "url": "https://example.com",
                    "headBranch": "main",
                    "event": "push",
                }
            ]
        )
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=runs_response, stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),  # No failed logs
            ]
            github_client.get_failed_run_logs()
            # Should use latest run as fallback
            assert mock_run.call_count == 2

    def test_get_failed_run_logs_without_run_id_no_runs(self, github_client):
        """Test getting failed logs without run_id when no runs exist."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="[]",
                stderr="",
            )
            result = github_client.get_failed_run_logs()
            assert "No workflow runs found" in result

    def test_run_gh_command_check_false_no_raise(self, github_client):
        """Test _run_gh_command with check=False doesn't raise on error."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="some error",
            )
            # Use internal method with check=False
            result = github_client._run_gh_command(["gh", "test"], check=False)
            # Should not raise, should return the result
            assert result.returncode == 1

    def test_run_gh_command_check_true_raises(self, github_client):
        """Test _run_gh_command with check=True raises on error."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="command failed",
            )
            with pytest.raises(GitHubError) as exc_info:
                github_client._run_gh_command(["gh", "test"], check=True)
            assert "command failed" in str(exc_info.value)

    def test_run_gh_command_empty_stderr_fallback_message(self, github_client):
        """Test _run_gh_command uses fallback message when stderr is empty."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="",  # Empty stderr
            )
            with pytest.raises(GitHubError) as exc_info:
                github_client._run_gh_command(["gh", "test"])
            assert "exit code" in str(exc_info.value).lower()
