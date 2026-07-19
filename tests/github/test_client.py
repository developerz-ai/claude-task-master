"""Comprehensive tests for the GitHub client module."""

import json
import subprocess
from enum import Enum
from unittest.mock import MagicMock, patch

import pytest

import claude_task_master.github.client as github_client_module
from claude_task_master.github.client import (
    RATE_LIMIT_MAX_DELAY,
    RATE_LIMIT_MAX_RETRIES,
    AutoMergeResult,
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubMergeError,
    GitHubNotFoundError,
    GitHubTimeoutError,
    PRStatus,
    _compute_rate_limit_delay,
    _is_rate_limit_error,
    _parse_retry_after,
)

# =============================================================================
# PRStatus Model Tests
# =============================================================================


class TestPRStatusModel:
    """Tests for the PRStatus Pydantic model."""

    def test_pr_status_creation_with_required_fields(self):
        """Test creating PRStatus with all required fields."""
        status = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[],
        )
        assert status.number == 123
        assert status.ci_state == "SUCCESS"
        assert status.unresolved_threads == 0
        assert status.check_details == []

    def test_pr_status_with_check_details(self):
        """Test creating PRStatus with check details."""
        check_details = [
            {
                "name": "tests",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "url": "https://example.com/check/1",
            },
            {
                "name": "lint",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "url": "https://example.com/check/2",
            },
        ]
        status = PRStatus(
            number=456,
            ci_state="FAILURE",
            unresolved_threads=2,
            check_details=check_details,
        )
        assert len(status.check_details) == 2
        assert status.check_details[0]["name"] == "tests"
        assert status.check_details[1]["conclusion"] == "FAILURE"

    def test_pr_status_model_dump(self):
        """Test that model can be serialized to dict."""
        status = PRStatus(
            number=789,
            ci_state="PENDING",
            unresolved_threads=5,
            check_details=[{"name": "build", "status": "IN_PROGRESS"}],
        )
        data = status.model_dump()
        assert data["number"] == 789
        assert data["ci_state"] == "PENDING"
        assert data["unresolved_threads"] == 5
        assert len(data["check_details"]) == 1

    def test_pr_status_validation_missing_number(self):
        """Test that missing number raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            PRStatus(  # type: ignore[call-arg]
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            )
        assert "number" in str(exc_info.value)

    def test_pr_status_validation_missing_ci_state(self):
        """Test that missing ci_state raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            PRStatus(  # type: ignore[call-arg]
                number=123,
                unresolved_threads=0,
                check_details=[],
            )
        assert "ci_state" in str(exc_info.value)

    def test_pr_status_validation_invalid_number_type(self):
        """Test that invalid number type raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            PRStatus(
                number="not-a-number",  # type: ignore[arg-type]
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            )
        assert "number" in str(exc_info.value)

    def test_pr_status_various_ci_states(self):
        """Test PRStatus with various CI states."""
        for state in ["PENDING", "SUCCESS", "FAILURE", "ERROR"]:
            status = PRStatus(
                number=1,
                ci_state=state,
                unresolved_threads=0,
                check_details=[],
            )
            assert status.ci_state == state


# =============================================================================
# GitHubClient Initialization Tests
# =============================================================================


class TestGitHubClientInit:
    """Tests for GitHubClient initialization and gh CLI check."""

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
            # Check that the GitHub CLI URL is mentioned (using regex for proper URL validation)
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


# =============================================================================
# GitHubClient.create_pr Tests
# =============================================================================


class TestGitHubClientCreatePR:
    """Tests for PR creation functionality."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_create_pr_success(self, github_client):
        """Test successful PR creation."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/42\n",
                stderr="",
            )
            pr_number = github_client.create_pr(
                title="Test PR",
                body="This is a test PR",
                base="main",
            )
            assert pr_number == 42
            # Verify the command was called with the right arguments
            call_args = mock_run.call_args
            assert call_args[0][0] == [
                "gh",
                "pr",
                "create",
                "--title",
                "Test PR",
                "--body",
                "This is a test PR",
                "--base",
                "main",
            ]
            assert call_args[1]["timeout"] == 60

    def test_create_pr_different_base_branch(self, github_client):
        """Test PR creation with a different base branch."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/123\n",
                stderr="",
            )
            pr_number = github_client.create_pr(
                title="Feature PR",
                body="New feature",
                base="develop",
            )
            assert pr_number == 123
            # Verify the base branch was passed correctly
            call_args = mock_run.call_args[0][0]
            assert "--base" in call_args
            assert "develop" in call_args

    def test_create_pr_default_base_branch(self, github_client):
        """Test PR creation uses main as default base branch."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/1\n",
                stderr="",
            )
            github_client.create_pr(
                title="Test",
                body="Test body",
            )
            call_args = mock_run.call_args[0][0]
            assert "--base" in call_args
            assert "main" in call_args

    def test_create_pr_extracts_number_from_url(self, github_client):
        """Test that PR number is correctly extracted from various URL formats."""
        test_cases = [
            ("https://github.com/owner/repo/pull/1\n", 1),
            ("https://github.com/owner/repo/pull/999\n", 999),
            ("https://github.com/org-name/repo-name/pull/12345\n", 12345),
        ]
        for url, expected_number in test_cases:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=url,
                    stderr="",
                )
                pr_number = github_client.create_pr("Title", "Body")
                assert pr_number == expected_number

    def test_create_pr_failure_subprocess_error(self, github_client):
        """Test PR creation handles subprocess errors."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "gh pr create", stderr="Error creating PR"
            )
            with pytest.raises(subprocess.CalledProcessError):
                github_client.create_pr("Title", "Body")

    def test_create_pr_with_special_characters_in_title(self, github_client):
        """Test PR creation with special characters in title."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/5\n",
                stderr="",
            )
            pr_number = github_client.create_pr(
                title="Fix: Bug #123 (critical) & security",
                body="Fixes issue",
            )
            assert pr_number == 5

    def test_create_pr_with_multiline_body(self, github_client):
        """Test PR creation with multiline body."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/7\n",
                stderr="",
            )
            body = """## Summary
- Added new feature
- Fixed bugs

## Testing
All tests pass"""
            pr_number = github_client.create_pr(title="Multi-line PR", body=body)
            assert pr_number == 7


# =============================================================================
# GitHubClient.get_pr_status Tests
# =============================================================================


class TestGitHubClientGetPRStatus:
    """Tests for PR status retrieval."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_get_pr_status_success(self, github_client, sample_pr_graphql_response):
        """Test successful PR status retrieval."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(sample_pr_graphql_response),
                    stderr="",
                )
                status = github_client.get_pr_status(123)

                assert status.number == 123
                assert status.ci_state == "SUCCESS"
                assert status.unresolved_threads == 1
                assert len(status.check_details) == 1
                assert status.check_details[0]["name"] == "tests"

    def test_get_pr_status_pending_ci(self, github_client):
        """Test PR status when CI is pending."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "commits": {
                            "nodes": [
                                {
                                    "commit": {
                                        "statusCheckRollup": {
                                            "state": "PENDING",
                                            "contexts": {
                                                "nodes": [
                                                    {
                                                        "name": "tests",
                                                        "status": "IN_PROGRESS",
                                                        "conclusion": None,
                                                        "detailsUrl": None,
                                                    }
                                                ]
                                            },
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
                    stdout=json.dumps(response),
                    stderr="",
                )
                status = github_client.get_pr_status(456)

                assert status.ci_state == "PENDING"
                assert status.unresolved_threads == 0

    def test_get_pr_status_failure_ci(self, github_client):
        """Test PR status when CI fails."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "commits": {
                            "nodes": [
                                {
                                    "commit": {
                                        "statusCheckRollup": {
                                            "state": "FAILURE",
                                            "contexts": {
                                                "nodes": [
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "tests",
                                                        "status": "COMPLETED",
                                                        "conclusion": "FAILURE",
                                                        "detailsUrl": "https://example.com/fail",
                                                    }
                                                ]
                                            },
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
                    stdout=json.dumps(response),
                    stderr="",
                )
                status = github_client.get_pr_status(789)

                assert status.ci_state == "FAILURE"
                assert status.check_details[0]["conclusion"] == "FAILURE"

    def test_get_pr_status_no_status_check_rollup(self, github_client):
        """Test PR status when no status check rollup exists."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "commits": {"nodes": [{"commit": {"statusCheckRollup": None}}]},
                        "reviewThreads": {"nodes": []},
                    }
                }
            }
        }
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(response),
                    stderr="",
                )
                status = github_client.get_pr_status(1)

                # Should default to PENDING when no rollup
                assert status.ci_state == "PENDING"
                assert status.check_details == []

    def test_get_pr_status_no_commits(self, github_client):
        """Test PR status when no commits exist."""
        response: dict = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "commits": {"nodes": []},
                        "reviewThreads": {"nodes": []},
                    }
                }
            }
        }
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(response),
                    stderr="",
                )
                status = github_client.get_pr_status(1)

                assert status.ci_state == "PENDING"
                assert status.check_details == []

    def test_get_pr_status_multiple_unresolved_threads(self, github_client):
        """Test PR status with multiple unresolved review threads."""
        response = {
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
                        "reviewThreads": {
                            "nodes": [
                                {"isResolved": False, "comments": {"nodes": []}},
                                {"isResolved": False, "comments": {"nodes": []}},
                                {"isResolved": True, "comments": {"nodes": []}},
                                {"isResolved": False, "comments": {"nodes": []}},
                            ]
                        },
                    }
                }
            }
        }
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(response),
                    stderr="",
                )
                status = github_client.get_pr_status(1)

                assert status.unresolved_threads == 3

    def test_get_pr_status_all_threads_resolved(self, github_client):
        """Test PR status when all threads are resolved."""
        response = {
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
                        "reviewThreads": {
                            "nodes": [
                                {"isResolved": True, "comments": {"nodes": []}},
                                {"isResolved": True, "comments": {"nodes": []}},
                            ]
                        },
                    }
                }
            }
        }
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(response),
                    stderr="",
                )
                status = github_client.get_pr_status(1)

                assert status.unresolved_threads == 0

    def test_get_pr_status_graphql_query_parameters(self, github_client):
        """Test that correct parameters are passed to GraphQL query."""
        response: dict = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "commits": {"nodes": []},
                        "reviewThreads": {"nodes": []},
                    }
                }
            }
        }
        with patch.object(github_client, "_get_repo_info", return_value="testowner/testrepo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(response),
                    stderr="",
                )
                github_client.get_pr_status(42)

                # Verify the call args
                call_args = mock_run.call_args[0][0]
                assert "gh" in call_args
                assert "api" in call_args
                assert "graphql" in call_args
                # Check parameters are included
                assert "-F" in call_args
                assert "owner=testowner" in call_args
                assert "repo=testrepo" in call_args
                assert "pr=42" in call_args

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
# GitHubClient.get_pr_comments Tests
# =============================================================================


def _make_rest_comment_client(
    comment_id: int, user: str, body: str, path: str | None, line: int | None
) -> dict:
    """Helper to create REST API comment format."""
    return {
        "id": comment_id,
        "user": {"login": user},
        "body": body,
        "path": path,
        "line": line,
    }


def _make_graphql_resolved_response_client(resolved_map: dict[int, bool]) -> dict:
    """Helper to create GraphQL resolved status response."""
    nodes = []
    for comment_id, is_resolved in resolved_map.items():
        nodes.append(
            {
                "isResolved": is_resolved,
                "comments": {"nodes": [{"databaseId": comment_id}]},
            }
        )
    return {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}}}


class TestGitHubClientGetPRComments:
    """Tests for PR comments retrieval using REST API + GraphQL."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_get_pr_comments_unresolved_only(self, github_client):
        """Test getting only unresolved PR comments."""
        rest_comments = [
            _make_rest_comment_client(1, "reviewer1", "Please fix this", "src/main.py", 42),
            _make_rest_comment_client(2, "reviewer2", "Looks good now", "src/utils.py", 10),
        ]
        graphql_response = _make_graphql_resolved_response_client({1: False, 2: True})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                comments = github_client.get_pr_comments(123, only_unresolved=True)

                assert "reviewer1" in comments
                assert "Please fix this" in comments
                assert "reviewer2" not in comments
                assert "Looks good now" not in comments

    def test_get_pr_comments_all_comments(self, github_client):
        """Test getting all PR comments including resolved."""
        rest_comments = [
            _make_rest_comment_client(1, "reviewer1", "Unresolved comment", "src/main.py", 42),
            _make_rest_comment_client(2, "reviewer2", "Resolved comment", "src/utils.py", 10),
        ]
        graphql_response = _make_graphql_resolved_response_client({1: False, 2: True})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                comments = github_client.get_pr_comments(123, only_unresolved=False)

                assert "reviewer1" in comments
                assert "Unresolved comment" in comments
                assert "reviewer2" in comments
                assert "Resolved comment" in comments

    def test_get_pr_comments_formatting(self, github_client):
        """Test that comments are properly formatted."""
        rest_comments = [
            _make_rest_comment_client(
                1, "developer", "This needs refactoring", "src/handler.py", 100
            ),
        ]
        graphql_response = _make_graphql_resolved_response_client({1: False})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                comments = github_client.get_pr_comments(1)

                assert "**developer**" in comments
                assert "src/handler.py" in comments
                assert "100" in comments
                assert "This needs refactoring" in comments

    def test_get_pr_comments_bot_user_marker(self, github_client):
        """Test that bot users are properly marked."""
        rest_comments = [
            _make_rest_comment_client(1, "codecov[bot]", "Coverage report", None, None),
        ]
        graphql_response = _make_graphql_resolved_response_client({1: False})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                comments = github_client.get_pr_comments(1)

                assert "(bot)" in comments
                assert "codecov[bot]" in comments

    def test_get_pr_comments_multiple_comments_in_thread(self, github_client):
        """Test handling multiple comments in a single thread."""
        rest_comments = [
            _make_rest_comment_client(1, "user1", "First comment", "file.py", 1),
            _make_rest_comment_client(2, "user2", "Reply to first", "file.py", 1),
        ]
        graphql_response = _make_graphql_resolved_response_client({1: False, 2: False})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                comments = github_client.get_pr_comments(1)

                assert "user1" in comments
                assert "First comment" in comments
                assert "user2" in comments
                assert "Reply to first" in comments

    def test_get_pr_comments_no_comments(self, github_client):
        """Test when there are no review comments."""
        rest_comments: list = []
        graphql_response: dict = {
            "data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}
        }

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                comments = github_client.get_pr_comments(1)

                assert comments == ""

    def test_get_pr_comments_missing_path_and_line(self, github_client):
        """Test handling comments without path or line information."""
        rest_comments = [
            _make_rest_comment_client(1, "reviewer", "General PR comment", None, None),
        ]
        graphql_response = _make_graphql_resolved_response_client({1: False})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                comments = github_client.get_pr_comments(1)

                assert "PR" in comments or "N/A" in comments
                assert "General PR comment" in comments

    def test_get_pr_comments_separator(self, github_client):
        """Test that comments are separated correctly."""
        rest_comments = [
            _make_rest_comment_client(1, "user1", "Comment 1", "file1.py", 1),
            _make_rest_comment_client(2, "user2", "Comment 2", "file2.py", 2),
        ]
        graphql_response = _make_graphql_resolved_response_client({1: False, 2: False})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                comments = github_client.get_pr_comments(1)

                # Check that separator is used
                assert "---" in comments

    def test_get_pr_comments_with_empty_comment_body(self, github_client):
        """Test handling comments with empty body."""
        rest_comments = [
            _make_rest_comment_client(1, "user", "", "file.py", 1),
        ]
        graphql_response = _make_graphql_resolved_response_client({1: False})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                # Should not raise, just return formatted output
                comments = github_client.get_pr_comments(1)
                assert "user" in comments


# =============================================================================
# GitHubClient.merge_pr Tests
# =============================================================================


class TestAutoMergeResultModel:
    """Tests for the AutoMergeResult enum and its export."""

    def test_auto_merge_result_is_str_enum_with_expected_members(self):
        """Test that AutoMergeResult is a str Enum with MERGED/SCHEDULED/FAILED."""
        assert issubclass(AutoMergeResult, str)
        assert issubclass(AutoMergeResult, Enum)
        assert {member.name for member in AutoMergeResult} == {"MERGED", "SCHEDULED", "FAILED"}

    def test_auto_merge_result_member_values(self):
        """Test that each outcome member carries its lowercase string value."""
        assert AutoMergeResult.MERGED.value == "merged"
        assert AutoMergeResult.SCHEDULED.value == "scheduled"
        assert AutoMergeResult.FAILED.value == "failed"
        # StrEnum members compare equal to their string values
        assert AutoMergeResult.MERGED == str(AutoMergeResult.MERGED)
        assert AutoMergeResult.SCHEDULED == str(AutoMergeResult.SCHEDULED)
        assert AutoMergeResult.FAILED == str(AutoMergeResult.FAILED)

    def test_auto_merge_result_members_are_distinct(self):
        """Test that merged/scheduled/failed outcomes are distinguishable."""
        outcomes = {
            AutoMergeResult.MERGED,
            AutoMergeResult.SCHEDULED,
            AutoMergeResult.FAILED,
        }
        assert len(outcomes) == 3
        assert len({member.value for member in outcomes}) == 3

    def test_auto_merge_result_lookups(self):
        """Test name and value lookups resolve to the right outcome members."""
        assert AutoMergeResult["MERGED"] is AutoMergeResult.MERGED
        assert AutoMergeResult["SCHEDULED"] is AutoMergeResult.SCHEDULED
        assert AutoMergeResult["FAILED"] is AutoMergeResult.FAILED
        assert AutoMergeResult("merged") is AutoMergeResult.MERGED
        assert AutoMergeResult("scheduled") is AutoMergeResult.SCHEDULED
        assert AutoMergeResult("failed") is AutoMergeResult.FAILED

    def test_auto_merge_result_invalid_value_raises(self):
        """Test that an unknown outcome value raises ValueError."""
        with pytest.raises(ValueError):
            AutoMergeResult("unknown")

    def test_auto_merge_result_in_module_all(self):
        """Test that github.client.__all__ exports AutoMergeResult."""
        assert "AutoMergeResult" in github_client_module.__all__


class TestGitHubClientTryAutoMerge:
    """Tests for GitHubClient._try_auto_merge polling behavior."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        """Patch time.sleep in github.client so polls don't block."""
        monkeypatch.setattr("claude_task_master.github.client.time.sleep", lambda _: None)

    @staticmethod
    def _make_status(state: str) -> MagicMock:
        """Build a mock PR status carrying a raw GitHub ``state`` field."""
        status = MagicMock(spec=PRStatus)
        status.state = state
        return status

    def test_try_auto_merge_returns_merged_when_poll_confirms_merge(self, github_client):
        """Poll finding state MERGED returns AutoMergeResult.MERGED."""
        merged_status = self._make_status("MERGED")
        with (
            patch.object(github_client, "_run_gh_command", return_value=MagicMock()),
            patch.object(github_client, "get_pr_status", return_value=merged_status),
        ):
            result = github_client._try_auto_merge("123")

        assert result == AutoMergeResult.MERGED

    def test_try_auto_merge_polls_until_merged(self, github_client):
        """Non-MERGED states keep polling until a MERGED state is seen."""
        open_status = self._make_status("OPEN")
        merged_status = self._make_status("MERGED")
        with (
            patch.object(github_client, "_run_gh_command", return_value=MagicMock()),
            patch.object(
                github_client,
                "get_pr_status",
                side_effect=[open_status, open_status, merged_status],
            ) as mock_status,
        ):
            result = github_client._try_auto_merge("123")

        assert result == AutoMergeResult.MERGED
        assert mock_status.call_count == 3

    def test_try_auto_merge_scheduled_when_never_merged(self, github_client):
        """Polls exhausted without MERGED returns SCHEDULED (not FAILED)."""
        open_status = self._make_status("OPEN")
        with (
            patch.object(github_client, "_run_gh_command", return_value=MagicMock()),
            patch.object(github_client, "get_pr_status", return_value=open_status) as mock_status,
        ):
            result = github_client._try_auto_merge("123")

        assert result == AutoMergeResult.SCHEDULED
        assert mock_status.call_count == 6

    def test_try_auto_merge_scheduled_when_get_pr_status_keeps_raising(
        self, github_client, monkeypatch
    ):
        """Persistent get_pr_status failure backs off and ends as SCHEDULED."""
        sleep_mock = MagicMock()
        monkeypatch.setattr("claude_task_master.github.client.time.sleep", sleep_mock)
        with (
            patch.object(github_client, "_run_gh_command", return_value=MagicMock()),
            patch.object(
                github_client,
                "get_pr_status",
                side_effect=GitHubError("boom", command=["gh"]),
            ) as mock_status,
        ):
            result = github_client._try_auto_merge("123")

        assert result == AutoMergeResult.SCHEDULED
        assert mock_status.call_count == 6
        # One backoff sleep per poll except after the final one.
        assert sleep_mock.call_count == 5
        # Backoff grows with the attempt (10 * attempt: 10, 20, 30, 40, 50).
        backoff_sleeps = [call.args[0] for call in sleep_mock.call_args_list]
        assert all(delay % 10 == 0 for delay in backoff_sleeps)
        assert any(delay > 10 for delay in backoff_sleeps)

    def test_try_auto_merge_failed_on_gh_error(self, github_client):
        """gh command failure returns FAILED and never polls."""
        with (
            patch.object(
                github_client,
                "_run_gh_command",
                side_effect=GitHubError("auto-merge is not allowed", command=["gh"]),
            ),
            patch.object(github_client, "get_pr_status") as mock_status,
        ):
            result = github_client._try_auto_merge("123")

        assert result == AutoMergeResult.FAILED
        mock_status.assert_not_called()

    def test_try_auto_merge_failed_on_gh_timeout(self, github_client):
        """gh command timeout returns FAILED and never polls."""
        with (
            patch.object(
                github_client,
                "_run_gh_command",
                side_effect=GitHubTimeoutError("timed out", command=["gh"]),
            ),
            patch.object(github_client, "get_pr_status") as mock_status,
        ):
            result = github_client._try_auto_merge("123")

        assert result == AutoMergeResult.FAILED
        mock_status.assert_not_called()


class TestGitHubClientMergePR:
    """Tests for PR merge functionality."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_merge_pr_success_with_auto(self, github_client):
        """Test successful PR merge with --auto flag (confirmed MERGED)."""
        with (
            patch.object(
                github_client,
                "_try_auto_merge",
                return_value=AutoMergeResult.MERGED,
            ) as mock_auto,
            patch.object(github_client, "_direct_merge") as mock_direct,
        ):
            github_client.merge_pr(123)

        mock_auto.assert_called_once_with("123")
        mock_direct.assert_not_called()

    def test_merge_pr_scheduled_auto_merge_skips_direct_merge(self, github_client):
        """SCHEDULED auto-merge means the merge is queued, so no direct merge."""
        with (
            patch.object(
                github_client,
                "_try_auto_merge",
                return_value=AutoMergeResult.SCHEDULED,
            ) as mock_auto,
            patch.object(github_client, "_direct_merge") as mock_direct,
        ):
            github_client.merge_pr(123)

        mock_auto.assert_called_once_with("123")
        mock_direct.assert_not_called()

    @pytest.mark.parametrize(
        ("outcome", "expects_direct_merge"),
        [
            (AutoMergeResult.MERGED, False),
            (AutoMergeResult.SCHEDULED, False),
            (AutoMergeResult.FAILED, True),
        ],
        ids=["merged", "scheduled", "failed"],
    )
    def test_merge_pr_auto_merge_outcome_drives_direct_merge_fallback(
        self, github_client, outcome, expects_direct_merge
    ):
        """Each AutoMergeResult outcome drives merge_pr's fallback decision."""
        with (
            patch.object(github_client, "_try_auto_merge", return_value=outcome) as mock_auto,
            patch.object(github_client, "_direct_merge") as mock_direct,
        ):
            github_client.merge_pr(123)

        mock_auto.assert_called_once_with("123")
        if expects_direct_merge:
            mock_direct.assert_called_once_with("123", 123)
        else:
            mock_direct.assert_not_called()

    def test_merge_pr_failed_outcome_direct_merge_raises(self, github_client):
        """FAILED outcome falls back to direct merge, which may raise."""
        with (
            patch.object(
                github_client,
                "_try_auto_merge",
                return_value=AutoMergeResult.FAILED,
            ),
            patch.object(
                github_client,
                "_direct_merge",
                side_effect=GitHubMergeError(
                    "Failed to merge PR #123: boom", command=["gh", "pr", "merge"]
                ),
            ),
            pytest.raises(GitHubMergeError, match="Failed to merge PR #123"),
        ):
            github_client.merge_pr(123)

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
        with (
            patch.object(
                github_client,
                "_try_auto_merge",
                return_value=AutoMergeResult.MERGED,
            ) as mock_auto,
            patch.object(github_client, "_direct_merge"),
        ):
            github_client.merge_pr(456)

        mock_auto.assert_called_once_with("456")

    def test_merge_pr_uses_squash_merge(self, github_client):
        """Test that merge uses squash strategy."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            github_client.merge_pr(789, use_auto=False)

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


# =============================================================================
# GitHubClient._get_repo_info Tests
# =============================================================================


class TestGitHubClientGetRepoInfo:
    """Tests for repository info retrieval."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

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

    def test_get_repo_info_various_formats(self):
        """Test repo info with various owner/repo formats (fresh client per case)."""
        test_cases = [
            "simple/repo",
            "organization-name/repo-name",
            "org_with_underscore/repo_with_underscore",
            "CamelCase/RepoName",
        ]
        for expected in test_cases:
            # Fresh client per iteration so the cache is empty each time.
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                client = GitHubClient()
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=f"{expected}\n",
                    stderr="",
                )
                result = client._get_repo_info()
                assert result == expected

    def test_get_repo_info_caches_result(self, github_client):
        """Second call with same cwd uses cache — subprocess called only once."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="owner/repo\n",
                stderr="",
            )
            result1 = github_client._get_repo_info()
            result2 = github_client._get_repo_info()

        assert result1 == "owner/repo"
        assert result2 == "owner/repo"
        mock_run.assert_called_once()  # subprocess invoked only on the first call

    def test_get_repo_info_different_cwd_not_cached(self, github_client):
        """Different cwd values bypass the per-cwd cache and fetch separately."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="owner/repo-a\n", stderr=""),
                MagicMock(returncode=0, stdout="owner/repo-b\n", stderr=""),
            ]
            result_a = github_client._get_repo_info(cwd="/path/a")
            result_b = github_client._get_repo_info(cwd="/path/b")

        assert result_a == "owner/repo-a"
        assert result_b == "owner/repo-b"
        assert mock_run.call_count == 2

    def test_get_repo_info_not_in_git_repo(self, github_client):
        """Test repo info when not in a git repository."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "gh repo view", stderr="not a git repository"
            )
            with pytest.raises(subprocess.CalledProcessError):
                github_client._get_repo_info()


# =============================================================================
# Integration Tests
# =============================================================================


class TestGitHubClientIntegration:
    """Integration tests for the complete workflow."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_full_pr_workflow(self, github_client):
        """Test creating a PR and checking its status."""
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
            github_client.merge_pr(100, use_auto=False)  # Should succeed


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestGitHubClientEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_create_pr_with_empty_body(self, github_client):
        """Test PR creation with empty body."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/1\n",
                stderr="",
            )
            pr_number = github_client.create_pr(title="Title", body="")
            assert pr_number == 1

    def test_create_pr_with_unicode_content(self, github_client):
        """Test PR creation with unicode content."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/1\n",
                stderr="",
            )
            pr_number = github_client.create_pr(
                title="Fix: 日本語 and emoji 🎉",
                body="Contains unicode: αβγ δεζ 中文 한국어",
            )
            assert pr_number == 1

    def test_get_pr_status_with_malformed_json(self, github_client):
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

    def test_get_pr_comments_with_empty_comment_body(self, github_client):
        """Test handling comments with empty body."""
        rest_comments = [
            _make_rest_comment_client(1, "user", "", "file.py", 1),
        ]
        graphql_response = _make_graphql_resolved_response_client({1: False})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                # Should not raise, just return formatted output
                comments = github_client.get_pr_comments(1)
                assert "user" in comments

    def test_pr_number_extraction_edge_cases(self, github_client):
        """Test PR number extraction from various URL edge cases."""
        test_cases = [
            ("https://github.com/a/b/pull/0", 0),  # Zero PR number
            ("https://github.com/a/b/pull/999999999", 999999999),  # Large number
        ]
        for url, expected in test_cases:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=f"{url}\n",
                    stderr="",
                )
                pr_number = github_client.create_pr("Title", "Body")
                assert pr_number == expected

    def test_subprocess_timeout(self, github_client):
        """Test handling subprocess timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=60)
            with pytest.raises(GitHubTimeoutError) as exc_info:
                github_client.create_pr("Title", "Body")
            assert "timed out" in str(exc_info.value)

    def test_multiple_check_runs_in_status(self, github_client):
        """Test PR status with multiple check runs."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "commits": {
                            "nodes": [
                                {
                                    "commit": {
                                        "statusCheckRollup": {
                                            "state": "FAILURE",
                                            "contexts": {
                                                "nodes": [
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "unit-tests",
                                                        "status": "COMPLETED",
                                                        "conclusion": "SUCCESS",
                                                        "detailsUrl": "https://example.com/1",
                                                    },
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "integration-tests",
                                                        "status": "COMPLETED",
                                                        "conclusion": "FAILURE",
                                                        "detailsUrl": "https://example.com/2",
                                                    },
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "lint",
                                                        "status": "COMPLETED",
                                                        "conclusion": "SUCCESS",
                                                        "detailsUrl": "https://example.com/3",
                                                    },
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "build",
                                                        "status": "IN_PROGRESS",
                                                        "conclusion": None,
                                                        "detailsUrl": None,
                                                    },
                                                ]
                                            },
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
                    stdout=json.dumps(response),
                    stderr="",
                )
                status = github_client.get_pr_status(1)

                assert status.ci_state == "FAILURE"
                assert len(status.check_details) == 4
                # Verify check details are captured
                names = [check["name"] for check in status.check_details]
                assert "unit-tests" in names
                assert "integration-tests" in names
                assert "lint" in names
                assert "build" in names


# =============================================================================
# GitHubClient.get_workflow_runs Tests
# =============================================================================


class TestGitHubClientGetWorkflowRuns:
    """Tests for workflow runs retrieval."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_get_workflow_runs_success(self, github_client):
        """Test successful workflow runs retrieval."""
        response = [
            {
                "databaseId": 123,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.com/owner/repo/actions/runs/123",
                "headBranch": "main",
                "event": "push",
            },
            {
                "databaseId": 124,
                "name": "CD",
                "status": "in_progress",
                "conclusion": None,
                "url": "https://github.com/owner/repo/actions/runs/124",
                "headBranch": "feature",
                "event": "pull_request",
            },
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            runs = github_client.get_workflow_runs(limit=5)

            assert len(runs) == 2
            assert runs[0].id == 123
            assert runs[0].name == "CI"
            assert runs[0].status == "completed"
            assert runs[0].conclusion == "success"
            assert runs[1].status == "in_progress"
            assert runs[1].conclusion is None

    def test_get_workflow_runs_with_branch_filter(self, github_client):
        """Test workflow runs with branch filter."""
        response = [
            {
                "databaseId": 125,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.com/owner/repo/actions/runs/125",
                "headBranch": "feature-branch",
                "event": "push",
            }
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            runs = github_client.get_workflow_runs(limit=5, branch="feature-branch")

            call_args = mock_run.call_args[0][0]
            assert "--branch" in call_args
            assert "feature-branch" in call_args
            assert len(runs) == 1

    def test_get_workflow_runs_empty_list(self, github_client):
        """Test when no workflow runs exist."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="[]",
                stderr="",
            )
            runs = github_client.get_workflow_runs()
            assert runs == []

    def test_get_workflow_runs_limit_parameter(self, github_client):
        """Test that limit parameter is passed correctly."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="[]",
                stderr="",
            )
            github_client.get_workflow_runs(limit=10)

            call_args = mock_run.call_args[0][0]
            assert "--limit" in call_args
            assert "10" in call_args


# =============================================================================
# GitHubClient.get_workflow_run_status Tests
# =============================================================================


class TestGitHubClientGetWorkflowRunStatus:
    """Tests for workflow run status retrieval."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_get_workflow_run_status_with_run_id(self, github_client):
        """Test getting status for a specific run."""
        response = {
            "status": "completed",
            "conclusion": "success",
            "jobs": [
                {"name": "build", "status": "completed", "conclusion": "success"},
                {"name": "test", "status": "completed", "conclusion": "success"},
            ],
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            status = github_client.get_workflow_run_status(run_id=123)

            assert "Run #123" in status
            assert "completed" in status
            assert "success" in status
            assert "build" in status
            assert "test" in status

    def test_get_workflow_run_status_without_run_id(self, github_client):
        """Test getting status for latest run."""
        runs_response = [
            {
                "databaseId": 999,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.com/owner/repo/actions/runs/999",
                "headBranch": "main",
                "event": "push",
            }
        ]
        status_response = {
            "status": "completed",
            "conclusion": "success",
            "jobs": [],
        }
        with patch("subprocess.run") as mock_run:
            # First call for get_workflow_runs
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(runs_response),
                stderr="",
            )

            # Then call again for status - mock returns runs first, then status
            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "list" in cmd:
                    return MagicMock(returncode=0, stdout=json.dumps(runs_response))
                else:
                    return MagicMock(returncode=0, stdout=json.dumps(status_response))

            mock_run.side_effect = side_effect

            status = github_client.get_workflow_run_status()
            assert "Run #999" in status

    def test_get_workflow_run_status_no_runs_found(self, github_client):
        """Test status when no runs exist."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="[]",
                stderr="",
            )
            status = github_client.get_workflow_run_status()
            assert "No workflow runs found" in status

    def test_get_workflow_run_status_with_failed_jobs(self, github_client):
        """Test status output for failed jobs."""
        response = {
            "status": "completed",
            "conclusion": "failure",
            "jobs": [
                {"name": "build", "status": "completed", "conclusion": "success"},
                {"name": "test", "status": "completed", "conclusion": "failure"},
            ],
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            status = github_client.get_workflow_run_status(run_id=456)

            assert "✓" in status  # Success marker for build
            assert "✗" in status  # Failure marker for test

    def test_get_workflow_run_status_in_progress(self, github_client):
        """Test status for in-progress run."""
        response = {
            "status": "in_progress",
            "conclusion": None,
            "jobs": [
                {"name": "build", "status": "in_progress", "conclusion": None},
            ],
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            status = github_client.get_workflow_run_status(run_id=789)

            assert "in_progress" in status or "in progress" in status
            assert "⏳" in status  # In-progress marker


# =============================================================================
# GitHubClient.get_failed_run_logs Tests
# =============================================================================


class TestGitHubClientGetFailedRunLogs:
    """Tests for failed run logs retrieval."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_get_failed_run_logs_with_run_id(self, github_client):
        """Test getting logs for a specific failed run."""
        log_output = """test-job\tError: Test failed
test-job\tAssertionError: expected True
test-job\t  at test_file.py:42"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=log_output,
                stderr="",
            )
            logs = github_client.get_failed_run_logs(run_id=123)

            assert "Error: Test failed" in logs
            assert "AssertionError" in logs

    def test_get_failed_run_logs_without_run_id(self, github_client):
        """Test getting logs for latest failed run."""
        log_output = "build\tCompilation failed"
        workflow_runs_response = json.dumps(
            [
                {
                    "databaseId": 123,
                    "name": "CI",
                    "status": "completed",
                    "conclusion": "failure",
                    "url": "https://example.com",
                    "headBranch": "main",
                    "event": "push",
                }
            ]
        )
        with patch("subprocess.run") as mock_run:
            # First call returns workflow runs, second returns logs
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=workflow_runs_response, stderr=""),
                MagicMock(returncode=0, stdout=log_output, stderr=""),
            ]
            result = github_client.get_failed_run_logs()

            # Check that second call (log fetch) has correct args
            call_args = mock_run.call_args_list[1][0][0]
            assert "gh" in call_args
            assert "run" in call_args
            assert "view" in call_args
            assert "123" in call_args  # Run ID
            assert "--log-failed" in call_args
            assert result == log_output

    def test_get_failed_run_logs_truncates_long_output(self, github_client):
        """Test that long logs are truncated."""
        # Create output with more than 100 lines
        log_lines = [f"Line {i}: Some error message" for i in range(200)]
        log_output = "\n".join(log_lines)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=log_output,
                stderr="",
            )
            logs = github_client.get_failed_run_logs(run_id=123, max_lines=100)

            # Should be truncated
            assert "more lines" in logs
            # Should only show first 100 lines
            assert "Line 0:" in logs
            assert "Line 99:" in logs or "Line 100:" not in logs.split("...")[0]

    def test_get_failed_run_logs_error(self, github_client):
        """Test handling of errors when getting logs."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Run not found",
            )
            logs = github_client.get_failed_run_logs(run_id=999)

            assert "Error getting logs" in logs

    def test_get_failed_run_logs_short_output(self, github_client):
        """Test that short logs are not truncated."""
        log_output = "Line 1\nLine 2\nLine 3"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=log_output,
                stderr="",
            )
            logs = github_client.get_failed_run_logs(run_id=123, max_lines=100)

            assert logs == "Line 1\nLine 2\nLine 3"
            assert "more lines" not in logs


# =============================================================================
# GitHubClient.wait_for_ci Tests
# =============================================================================


class TestGitHubClientWaitForCI:
    """Tests for CI waiting functionality."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_wait_for_ci_success_with_pr(self, github_client):
        """Test waiting for CI with PR number - success case."""
        success_status = PRStatus(
            number=123,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[],
        )
        with patch.object(github_client, "get_pr_status", return_value=success_status):
            success, message = github_client.wait_for_ci(pr_number=123, timeout=60)

            assert success is True
            assert "passed" in message

    def test_wait_for_ci_failure_with_pr(self, github_client):
        """Test waiting for CI with PR number - failure case."""
        failure_status = PRStatus(
            number=123,
            ci_state="FAILURE",
            unresolved_threads=0,
            check_details=[],
        )
        with patch.object(github_client, "get_pr_status", return_value=failure_status):
            success, message = github_client.wait_for_ci(pr_number=123, timeout=60)

            assert success is False
            assert "failed" in message.lower() or "FAILURE" in message

    def test_wait_for_ci_error_state(self, github_client):
        """Test waiting for CI with ERROR state."""
        error_status = PRStatus(
            number=123,
            ci_state="ERROR",
            unresolved_threads=0,
            check_details=[],
        )
        with patch.object(github_client, "get_pr_status", return_value=error_status):
            success, message = github_client.wait_for_ci(pr_number=123, timeout=60)

            assert success is False
            assert "ERROR" in message

    def test_wait_for_ci_timeout(self, github_client):
        """Test waiting for CI times out."""
        pending_status = PRStatus(
            number=123,
            ci_state="PENDING",
            unresolved_threads=0,
            check_details=[],
        )
        with patch.object(github_client, "get_pr_status", return_value=pending_status):
            with patch("time.sleep"):  # Don't actually sleep
                with patch("time.time") as mock_time:
                    # Simulate timeout
                    mock_time.side_effect = [0, 0, 100, 200, 300, 400]
                    success, message = github_client.wait_for_ci(pr_number=123, timeout=1)

                    assert success is False
                    assert "Timeout" in message

    def test_wait_for_ci_workflow_success(self, github_client):
        """Test waiting for CI without PR - workflow success."""
        from claude_task_master.github.client import WorkflowRun

        success_run = WorkflowRun(
            id=456,
            name="CI",
            status="completed",
            conclusion="success",
            url="https://github.com/owner/repo/actions/runs/456",
            head_branch="main",
            event="push",
        )
        with patch.object(github_client, "get_workflow_runs", return_value=[success_run]):
            success, message = github_client.wait_for_ci(timeout=60)

            assert success is True
            assert "succeeded" in message

    def test_wait_for_ci_workflow_failure(self, github_client):
        """Test waiting for CI without PR - workflow failure."""
        from claude_task_master.github.client import WorkflowRun

        failed_run = WorkflowRun(
            id=456,
            name="CI",
            status="completed",
            conclusion="failure",
            url="https://github.com/owner/repo/actions/runs/456",
            head_branch="main",
            event="push",
        )
        with patch.object(github_client, "get_workflow_runs", return_value=[failed_run]):
            success, message = github_client.wait_for_ci(timeout=60)

            assert success is False
            assert "failed" in message.lower()


# =============================================================================
# Rate-limit backoff Tests
# =============================================================================


class TestRateLimitHelpers:
    """Tests for the rate-limit detection and backoff helper functions."""

    def test_is_rate_limit_error_detects_markers(self) -> None:
        """Test that known 403/429 rate-limit messages are detected."""
        assert _is_rate_limit_error("HTTP 403: API rate limit exceeded for user X")
        assert _is_rate_limit_error("You have exceeded a secondary rate limit")
        assert _is_rate_limit_error("You have triggered an abuse detection mechanism")
        assert _is_rate_limit_error("HTTP 429 Too Many Requests")

    def test_is_rate_limit_error_ignores_other_errors(self) -> None:
        """Test that unrelated errors are not treated as rate limits."""
        assert not _is_rate_limit_error("fatal: not a git repository")
        assert not _is_rate_limit_error("")

    def test_parse_retry_after_extracts_seconds(self) -> None:
        """Test that a Retry-After hint is parsed from stderr."""
        assert _parse_retry_after("Retry-After: 42") == 42.0
        assert _parse_retry_after("please retry after 7 seconds") == 7.0

    def test_parse_retry_after_absent(self) -> None:
        """Test that missing Retry-After yields None."""
        assert _parse_retry_after("some other error") is None
        assert _parse_retry_after("") is None

    def test_compute_delay_honors_retry_after(self) -> None:
        """Test that an explicit Retry-After is used and capped."""
        assert _compute_rate_limit_delay(0, 5.0) == 5.0
        assert _compute_rate_limit_delay(3, 999.0) == RATE_LIMIT_MAX_DELAY

    def test_compute_delay_backoff_grows_and_is_bounded(self) -> None:
        """Test exponential backoff with equal jitter (jitter pinned to 0)."""
        with patch.object(github_client_module.random, "uniform", return_value=0.0):
            # attempt 0: backoff=2, half=1 → 1.0; attempt 2: backoff=8, half=4 → 4.0
            assert _compute_rate_limit_delay(0, None) == 1.0
            assert _compute_rate_limit_delay(2, None) == 4.0
        # Jitter keeps the delay within [backoff/2, backoff].
        with patch.object(github_client_module.random, "uniform", return_value=1.0):
            assert _compute_rate_limit_delay(0, None) == 2.0


class TestRunGhCommandRateLimit:
    """Tests for rate-limit retry behavior inside _run_gh_command."""

    def test_retries_then_succeeds(self, github_client) -> None:
        """Test that a rate-limited command is retried and eventually succeeds."""
        rate_limited = MagicMock(returncode=1, stderr="API rate limit exceeded", stdout="")
        success = MagicMock(returncode=0, stderr="", stdout="ok")
        with (
            patch("subprocess.run", side_effect=[rate_limited, success]) as mock_run,
            patch.object(github_client_module.time, "sleep") as mock_sleep,
            patch("claude_task_master.core.console.warning"),
        ):
            result = github_client._run_gh_command(["gh", "api", "x"])

        assert result.stdout == "ok"
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once()

    def test_gives_up_after_max_retries(self, github_client) -> None:
        """Test that a persistent rate limit raises after the retry budget."""
        rate_limited = MagicMock(returncode=1, stderr="secondary rate limit", stdout="")
        with (
            patch("subprocess.run", return_value=rate_limited) as mock_run,
            patch.object(github_client_module.time, "sleep") as mock_sleep,
            patch("claude_task_master.core.console.warning"),
        ):
            with pytest.raises(GitHubError):
                github_client._run_gh_command(["gh", "api", "x"])

        assert mock_run.call_count == RATE_LIMIT_MAX_RETRIES + 1
        assert mock_sleep.call_count == RATE_LIMIT_MAX_RETRIES

    def test_non_rate_limit_error_not_retried(self, github_client) -> None:
        """Test that ordinary failures are not retried."""
        failed = MagicMock(returncode=1, stderr="fatal: not found", stdout="")
        with patch("subprocess.run", return_value=failed) as mock_run:
            with pytest.raises(GitHubError):
                github_client._run_gh_command(["gh", "api", "x"])

        assert mock_run.call_count == 1

    def test_honors_retry_after_delay(self, github_client) -> None:
        """Test that the Retry-After value drives the sleep duration."""
        rate_limited = MagicMock(
            returncode=1, stderr="rate limit exceeded\nRetry-After: 3", stdout=""
        )
        success = MagicMock(returncode=0, stderr="", stdout="ok")
        with (
            patch("subprocess.run", side_effect=[rate_limited, success]),
            patch.object(github_client_module.time, "sleep") as mock_sleep,
            patch("claude_task_master.core.console.warning"),
        ):
            github_client._run_gh_command(["gh", "api", "x"])

        mock_sleep.assert_called_once_with(3.0)

    def test_abuse_detection_stderr_triggers_backoff(self, github_client) -> None:
        """The 'abuse detection' stderr marker triggers the retry loop."""
        rate_limited = MagicMock(
            returncode=1, stderr="You have triggered an abuse detection mechanism", stdout=""
        )
        success = MagicMock(returncode=0, stderr="", stdout="done")
        with (
            patch("subprocess.run", side_effect=[rate_limited, success]) as mock_run,
            patch.object(github_client_module.time, "sleep"),
            patch("claude_task_master.core.console.warning"),
        ):
            result = github_client._run_gh_command(["gh", "api", "x"])

        assert result.stdout == "done"
        assert mock_run.call_count == 2

    def test_too_many_requests_stderr_triggers_backoff(self, github_client) -> None:
        """The 'too many requests' / HTTP 429 stderr marker triggers the retry loop."""
        rate_limited = MagicMock(returncode=1, stderr="HTTP 429 Too Many Requests", stdout="")
        success = MagicMock(returncode=0, stderr="", stdout="ok")
        with (
            patch("subprocess.run", side_effect=[rate_limited, success]) as mock_run,
            patch.object(github_client_module.time, "sleep"),
            patch("claude_task_master.core.console.warning"),
        ):
            result = github_client._run_gh_command(["gh", "api", "x"])

        assert result.stdout == "ok"
        assert mock_run.call_count == 2

    def test_backoff_delay_grows_with_attempt_number(self, github_client) -> None:
        """Sleep duration is longer for later retry attempts (exponential growth)."""
        rate_limited = MagicMock(returncode=1, stderr="secondary rate limit", stdout="")
        success = MagicMock(returncode=0, stderr="", stdout="ok")

        # Three rate-limited responses then one success
        with (
            patch(
                "subprocess.run", side_effect=[rate_limited, rate_limited, rate_limited, success]
            ),
            patch.object(github_client_module.time, "sleep") as mock_sleep,
            patch("claude_task_master.core.console.warning"),
            # Pin jitter to zero so delays are deterministic
            patch.object(github_client_module.random, "uniform", return_value=0.0),
        ):
            github_client._run_gh_command(["gh", "api", "x"])

        # Three sleeps: attempt 0, 1, 2
        assert mock_sleep.call_count == 3
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        # Each delay must be strictly greater than the previous (exponential growth)
        assert delays[0] < delays[1] < delays[2]

    def test_check_false_rate_limit_still_retried(self, github_client) -> None:
        """Rate-limit retries fire even when check=False; final error result is returned."""
        rate_limited = MagicMock(returncode=1, stderr="API rate limit exceeded", stdout="")
        success = MagicMock(returncode=0, stderr="", stdout="data")
        with (
            patch("subprocess.run", side_effect=[rate_limited, success]) as mock_run,
            patch.object(github_client_module.time, "sleep"),
            patch("claude_task_master.core.console.warning"),
        ):
            # check=False: should not raise, should return the success result
            result = github_client._run_gh_command(["gh", "api", "x"], check=False)

        assert result.returncode == 0
        assert result.stdout == "data"
        assert mock_run.call_count == 2
