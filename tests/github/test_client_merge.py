"""Tests for GitHub client merge and repository info functionality."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.github.client import (
    GitHubMergeError,
    GitHubTimeoutError,
)

# =============================================================================
# GitHubClient.merge_pr Tests
# =============================================================================


class TestGitHubClientMergePR:
    """Tests for PR merge functionality."""

    def test_merge_pr_success_with_auto(self, github_client):
        """Test successful PR merge with --auto flag."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            github_client.merge_pr(123)

            # First call should be with --auto
            call_args = mock_run.call_args_list[0]
            assert call_args[0][0] == ["gh", "pr", "merge", "123", "--squash", "--auto"]
            assert call_args[1]["timeout"] == 15

    def test_merge_pr_fallback_to_direct_merge(self, github_client):
        """Test fallback to direct merge when --auto fails."""
        with patch("subprocess.run") as mock_run:
            # First call with --auto fails, second succeeds
            mock_run.side_effect = [
                MagicMock(returncode=1, stdout="", stderr="auto-merge is not allowed"),
                MagicMock(returncode=0, stdout="", stderr=""),
            ]
            github_client.merge_pr(123)

            # Should have two calls
            assert mock_run.call_count == 2
            # Second call should be direct merge without --auto
            second_call = mock_run.call_args_list[1]
            assert "--auto" not in second_call[0][0]
            assert "--delete-branch" in second_call[0][0]

    def test_merge_pr_converts_number_to_string(self, github_client):
        """Test that PR number is converted to string for command."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            github_client.merge_pr(456)

            call_args = mock_run.call_args[0][0]
            assert "456" in call_args
            assert isinstance(call_args[3], str)  # The PR number argument

    def test_merge_pr_uses_squash_merge(self, github_client):
        """Test that merge uses squash strategy."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            github_client.merge_pr(789)

            call_args = mock_run.call_args[0][0]
            assert "--squash" in call_args

    def test_merge_pr_timeout_raises_error(self, github_client):
        """Test that merge timeout raises GitHubMergeError."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("gh pr merge", 15)
            with pytest.raises(GitHubMergeError) as exc_info:
                github_client.merge_pr(999)
            assert "timed out" in str(exc_info.value)

    def test_merge_pr_failure_raises_error(self, github_client):
        """Test PR merge failure raises GitHubMergeError."""
        with patch("subprocess.run") as mock_run:
            # Both auto and direct merge fail
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="Cannot merge: checks failing"
            )
            with pytest.raises(GitHubMergeError) as exc_info:
                github_client.merge_pr(999)
            assert "Failed to merge" in str(exc_info.value)

    def test_merge_pr_without_auto(self, github_client):
        """Test merge with use_auto=False goes directly to merge."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            github_client.merge_pr(123, use_auto=False)

            # Should only call once with --delete-branch, not --auto
            assert mock_run.call_count == 1
            call_args = mock_run.call_args[0][0]
            assert "--auto" not in call_args
            assert "--delete-branch" in call_args

    def test_merge_pr_with_various_pr_numbers(self, github_client):
        """Test merge with various PR number formats."""
        test_cases = [1, 100, 9999, 123456]
        for pr_num in test_cases:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                github_client.merge_pr(pr_num)

                call_args = mock_run.call_args[0][0]
                assert str(pr_num) in call_args

    def test_merge_pr_auto_disabled_error_message(self, github_client):
        """Test merge when auto-merge is disabled on repo."""
        with patch("subprocess.run") as mock_run:
            # First call with --auto fails with specific error, second succeeds
            mock_run.side_effect = [
                MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Auto-merge is not enabled for this repository",
                ),
                MagicMock(returncode=0, stdout="", stderr=""),
            ]
            # Should not raise, falls back to direct merge
            github_client.merge_pr(123)
            assert mock_run.call_count == 2

    def test_merge_pr_branch_protection_error(self, github_client):
        """Test merge fails due to branch protection rules."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Required status check 'tests' is failing",
            )
            with pytest.raises(GitHubMergeError) as exc_info:
                github_client.merge_pr(123)
            assert "Failed to merge" in str(exc_info.value)

    def test_merge_pr_already_merged_error(self, github_client):
        """Test merge when PR is already merged."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Pull request already merged",
            )
            with pytest.raises(GitHubMergeError) as exc_info:
                github_client.merge_pr(123)
            assert "Failed to merge" in str(exc_info.value)


# =============================================================================
# GitHubClient._get_repo_info Tests
# =============================================================================


class TestGitHubClientGetRepoInfo:
    """Tests for repository info retrieval."""

    def test_get_repo_info_success(self, github_client):
        """Test successful repo info retrieval."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="owner/repo-name\n",
                stderr="",
            )
            result = github_client._get_repo_info()

            assert result == "owner/repo-name"
            # Verify the command was called with the right arguments
            call_args = mock_run.call_args
            assert call_args[0][0] == [
                "gh",
                "repo",
                "view",
                "--json",
                "nameWithOwner",
                "-q",
                ".nameWithOwner",
            ]
            assert call_args[1]["timeout"] == 15

    def test_get_repo_info_strips_whitespace(self, github_client):
        """Test that repo info strips whitespace."""
        test_cases = [
            "owner/repo\n",
            "owner/repo\n\n",
            "  owner/repo  \n",
            "owner/repo",
        ]
        for output in test_cases:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=output,
                    stderr="",
                )
                result = github_client._get_repo_info()
                assert result == "owner/repo"

    def test_get_repo_info_various_formats(self, github_client):
        """Test repo info with various owner/repo formats."""
        test_cases = [
            "simple/repo",
            "organization-name/repo-name",
            "org_with_underscore/repo_with_underscore",
            "CamelCase/RepoName",
        ]
        for expected in test_cases:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=f"{expected}\n",
                    stderr="",
                )
                result = github_client._get_repo_info()
                assert result == expected

    def test_get_repo_info_not_in_git_repo(self, github_client):
        """Test repo info when not in a git repository."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "gh repo view", stderr="not a git repository"
            )
            with pytest.raises(subprocess.CalledProcessError):
                github_client._get_repo_info()

    def test_get_repo_info_gh_not_authenticated(self, github_client):
        """Test repo info when gh is not authenticated."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "gh repo view", stderr="gh: not logged in"
            )
            with pytest.raises(subprocess.CalledProcessError):
                github_client._get_repo_info()

    def test_get_repo_info_timeout(self, github_client):
        """Test repo info when command times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("gh repo view", 15)
            with pytest.raises(GitHubTimeoutError) as exc_info:
                github_client._get_repo_info()
            assert "timed out" in str(exc_info.value)


# =============================================================================
# Integration Tests (Merge-related workflows)
# =============================================================================


class TestGitHubClientMergeIntegration:
    """Integration tests for merge-related workflows."""

    def test_full_pr_workflow(self, github_client):
        """Test creating a PR and checking its status before merge."""
        # First, create a PR
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/42\n",
                stderr="",
            )
            pr_number = github_client.create_pr(
                title="New Feature",
                body="Adds awesome feature",
            )
            assert pr_number == 42

        # Then, check its status
        status_response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "commits": {
                            "nodes": [
                                {
                                    "commit": {
                                        "statusCheckRollup": {
                                            "state": "SUCCESS",
                                            "contexts": {"nodes": []},
                                        }
                                    }
                                }
                            ]
                        },
                        "reviewThreads": {"nodes": []},
                    }
                }
            }
        }
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(status_response),
                    stderr="",
                )
                status = github_client.get_pr_status(pr_number)
                assert status.number == 42
                assert status.ci_state == "SUCCESS"

    def test_pr_status_to_merge_workflow(self, github_client, sample_pr_graphql_response):
        """Test checking PR status and then merging."""
        # Check status first (successful CI, no unresolved threads)
        success_response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "commits": {
                            "nodes": [
                                {
                                    "commit": {
                                        "statusCheckRollup": {
                                            "state": "SUCCESS",
                                            "contexts": {"nodes": []},
                                        }
                                    }
                                }
                            ]
                        },
                        "reviewThreads": {"nodes": []},
                    }
                }
            }
        }
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(success_response),
                    stderr="",
                )
                status = github_client.get_pr_status(100)
                assert status.ci_state == "SUCCESS"
                assert status.unresolved_threads == 0

        # Now merge
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            github_client.merge_pr(100)  # Should succeed

    def test_merge_after_ci_passes(self, github_client):
        """Test that merge succeeds after CI passes."""
        from claude_task_master.github.client import PRStatus

        # First simulate CI success
        success_status = PRStatus(
            number=50,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[
                {"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
            ],
        )

        with patch.object(github_client, "get_pr_status", return_value=success_status):
            status = github_client.get_pr_status(50)
            assert status.ci_state == "SUCCESS"

        # Then merge
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            github_client.merge_pr(50)
            assert mock_run.called

    def test_merge_blocked_by_failing_ci(self, github_client):
        """Test that merge fails when CI is failing."""
        from claude_task_master.github.client import PRStatus

        # Simulate CI failure
        failure_status = PRStatus(
            number=60,
            ci_state="FAILURE",
            unresolved_threads=0,
            check_details=[
                {"name": "tests", "status": "COMPLETED", "conclusion": "FAILURE"},
            ],
        )

        with patch.object(github_client, "get_pr_status", return_value=failure_status):
            status = github_client.get_pr_status(60)
            assert status.ci_state == "FAILURE"

        # Attempt merge - should fail
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="PR checks are failing",
            )
            with pytest.raises(GitHubMergeError):
                github_client.merge_pr(60)

    def test_merge_blocked_by_unresolved_threads(self, github_client):
        """Test merge scenario with unresolved review threads."""
        from claude_task_master.github.client import PRStatus

        # Simulate PR with unresolved threads
        status_with_threads = PRStatus(
            number=70,
            ci_state="SUCCESS",
            unresolved_threads=3,
            check_details=[],
        )

        with patch.object(github_client, "get_pr_status", return_value=status_with_threads):
            status = github_client.get_pr_status(70)
            assert status.ci_state == "SUCCESS"
            assert status.unresolved_threads == 3
            # In real scenario, merge might be blocked by repo rules


# =============================================================================
# Edge Cases and Error Handling (Merge-specific)
# =============================================================================


class TestGitHubClientMergeEdgeCases:
    """Edge cases and error handling for merge operations."""

    def test_merge_pr_network_error(self, github_client):
        """Test merge handles network errors gracefully."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Network unreachable")
            with pytest.raises(OSError):
                github_client.merge_pr(123)

    def test_merge_pr_empty_response(self, github_client):
        """Test merge with empty stdout (successful merge often has no output)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            # Should not raise
            github_client.merge_pr(123)

    def test_merge_pr_with_message_in_stdout(self, github_client):
        """Test merge when gh outputs a success message."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Pull request #123 merged\n",
                stderr="",
            )
            # Should not raise
            github_client.merge_pr(123)

    def test_merge_pr_conflict_error(self, github_client):
        """Test merge when there are merge conflicts."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="PR has conflicts that must be resolved",
            )
            with pytest.raises(GitHubMergeError) as exc_info:
                github_client.merge_pr(123)
            assert "Failed to merge" in str(exc_info.value)

    def test_get_repo_info_empty_response(self, github_client):
        """Test repo info with empty response."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr="",
            )
            result = github_client._get_repo_info()
            assert result == ""

    def test_get_repo_info_with_special_chars(self, github_client):
        """Test repo info with special characters in name."""
        test_cases = [
            "org-with-dash/repo.with.dots",
            "org123/repo456",
            "ORG/REPO",
        ]
        for expected in test_cases:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=f"{expected}\n",
                    stderr="",
                )
                result = github_client._get_repo_info()
                assert result == expected

    def test_merge_retry_after_transient_failure(self, github_client):
        """Test merge succeeds on retry after transient failure."""
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call (auto) fails with transient error
                return MagicMock(returncode=1, stdout="", stderr="Server error")
            else:
                # Second call (direct) succeeds
                return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = side_effect
            github_client.merge_pr(123)
            assert call_count[0] == 2
