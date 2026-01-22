"""Tests for GitHub client PR creation, status, and comments functionality."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.github.client import (
    GitHubTimeoutError,
    PRStatus,
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
# GitHubClient.create_pr Tests
# =============================================================================


class TestGitHubClientCreatePR:
    """Tests for PR creation functionality."""

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

    def test_create_pr_timeout_raises_error(self, github_client):
        """Test that PR creation timeout raises GitHubTimeoutError."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=60)
            with pytest.raises(GitHubTimeoutError) as exc_info:
                github_client.create_pr("Title", "Body")
            assert "timed out" in str(exc_info.value)

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
                title="Fix: japanese and emoji",
                body="Contains unicode: alphabeta chinese korean",
            )
            assert pr_number == 1

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


# =============================================================================
# GitHubClient.get_pr_status Tests
# =============================================================================


class TestGitHubClientGetPRStatus:
    """Tests for PR status retrieval."""

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

    def test_get_pr_status_multiple_check_runs(self, github_client):
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
# GitHubClient.get_pr_comments Tests
# =============================================================================


def _make_rest_comment(
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


def _make_graphql_resolved_response(resolved_map: dict[int, bool]) -> dict:
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

    def test_get_pr_comments_unresolved_only(self, github_client):
        """Test getting only unresolved PR comments."""
        # REST API response (all comments)
        rest_comments = [
            _make_rest_comment(1, "reviewer1", "Please fix this", "src/main.py", 42),
            _make_rest_comment(2, "reviewer2", "Looks good now", "src/utils.py", 10),
        ]
        # GraphQL response (resolved status: comment 1 unresolved, comment 2 resolved)
        graphql_response = _make_graphql_resolved_response({1: False, 2: True})

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
            _make_rest_comment(1, "reviewer1", "Unresolved comment", "src/main.py", 42),
            _make_rest_comment(2, "reviewer2", "Resolved comment", "src/utils.py", 10),
        ]
        graphql_response = _make_graphql_resolved_response({1: False, 2: True})

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
            _make_rest_comment(1, "developer", "This needs refactoring", "src/handler.py", 100),
        ]
        graphql_response = _make_graphql_resolved_response({1: False})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                comments = github_client.get_pr_comments(1)

                # Check formatting elements
                assert "**developer**" in comments
                assert "src/handler.py" in comments
                assert "100" in comments
                assert "This needs refactoring" in comments

    def test_get_pr_comments_bot_user_marker(self, github_client):
        """Test that bot users are properly marked."""
        rest_comments = [
            _make_rest_comment(1, "codecov[bot]", "Coverage report", None, None),
        ]
        graphql_response = _make_graphql_resolved_response({1: False})

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
            _make_rest_comment(1, "reviewer1", "First comment", "src/main.py", 10),
            _make_rest_comment(2, "reviewer2", "Second comment", "src/main.py", 10),
        ]
        graphql_response = _make_graphql_resolved_response({1: False, 2: False})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                comments = github_client.get_pr_comments(1)

                assert "reviewer1" in comments
                assert "First comment" in comments
                assert "reviewer2" in comments
                assert "Second comment" in comments

    def test_get_pr_comments_no_comments(self, github_client):
        """Test when there are no review comments."""
        rest_comments: list = []
        graphql_response = {
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
            _make_rest_comment(1, "reviewer", "General PR comment", None, None),
        ]
        graphql_response = _make_graphql_resolved_response({1: False})

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
            _make_rest_comment(1, "user1", "Comment 1", "file1.py", 1),
            _make_rest_comment(2, "user2", "Comment 2", "file2.py", 2),
        ]
        graphql_response = _make_graphql_resolved_response({1: False, 2: False})

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
            _make_rest_comment(1, "user", "", "file.py", 1),
        ]
        graphql_response = _make_graphql_resolved_response({1: False})

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=json.dumps(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                # Should not raise, just return formatted output
                comments = github_client.get_pr_comments(1)
                assert "user" in comments
