"""Comprehensive tests for the GitHub client module."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.github.client import GitHubClient, PRStatus

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
            PRStatus(
                ci_state="SUCCESS",
                unresolved_threads=0,
                check_details=[],
            )
        assert "number" in str(exc_info.value)

    def test_pr_status_validation_missing_ci_state(self):
        """Test that missing ci_state raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            PRStatus(
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
                number="not-a-number",
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
                check=True,
                capture_output=True,
                text=True,
            )
            assert client is not None

    def test_init_gh_cli_not_authenticated(self):
        """Test initialization when gh CLI is not authenticated."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "gh auth status", stderr="not logged in"
            )
            with pytest.raises(RuntimeError) as exc_info:
                GitHubClient()
            assert "gh CLI not authenticated" in str(exc_info.value)
            assert "gh auth login" in str(exc_info.value)

    def test_init_gh_cli_not_installed(self):
        """Test initialization when gh CLI is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("gh not found")
            with pytest.raises(RuntimeError) as exc_info:
                GitHubClient()
            assert "gh CLI not installed" in str(exc_info.value)
            assert "https://cli.github.com/" in str(exc_info.value)


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
            mock_run.assert_called_once_with(
                [
                    "gh",
                    "pr",
                    "create",
                    "--title",
                    "Test PR",
                    "--body",
                    "This is a test PR",
                    "--base",
                    "main",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

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
        response = {
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
        response = {
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


class TestGitHubClientGetPRComments:
    """Tests for PR comments retrieval."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_get_pr_comments_unresolved_only(self, github_client):
        """Test getting only unresolved PR comments."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "isResolved": False,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "author": {"login": "reviewer1"},
                                                "body": "Please fix this",
                                                "path": "src/main.py",
                                                "line": 42,
                                            }
                                        ]
                                    },
                                },
                                {
                                    "isResolved": True,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "author": {"login": "reviewer2"},
                                                "body": "Looks good now",
                                                "path": "src/utils.py",
                                                "line": 10,
                                            }
                                        ]
                                    },
                                },
                            ]
                        }
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
                comments = github_client.get_pr_comments(123, only_unresolved=True)

                assert "reviewer1" in comments
                assert "Please fix this" in comments
                assert "reviewer2" not in comments
                assert "Looks good now" not in comments

    def test_get_pr_comments_all_comments(self, github_client):
        """Test getting all PR comments including resolved."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "isResolved": False,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "author": {"login": "reviewer1"},
                                                "body": "Unresolved comment",
                                                "path": "src/main.py",
                                                "line": 42,
                                            }
                                        ]
                                    },
                                },
                                {
                                    "isResolved": True,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "author": {"login": "reviewer2"},
                                                "body": "Resolved comment",
                                                "path": "src/utils.py",
                                                "line": 10,
                                            }
                                        ]
                                    },
                                },
                            ]
                        }
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
                comments = github_client.get_pr_comments(123, only_unresolved=False)

                assert "reviewer1" in comments
                assert "Unresolved comment" in comments
                assert "reviewer2" in comments
                assert "Resolved comment" in comments

    def test_get_pr_comments_formatting(self, github_client):
        """Test that comments are properly formatted."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "isResolved": False,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "author": {"login": "developer"},
                                                "body": "This needs refactoring",
                                                "path": "src/handler.py",
                                                "line": 100,
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
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
                comments = github_client.get_pr_comments(1)

                # Check formatting elements
                assert "**developer**" in comments
                assert "src/handler.py" in comments
                assert "100" in comments
                assert "This needs refactoring" in comments

    def test_get_pr_comments_bot_user_marker(self, github_client):
        """Test that bot users are properly marked."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "isResolved": False,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "author": {"login": "codecov[bot]"},
                                                "body": "Coverage report",
                                                "path": None,
                                                "line": None,
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
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
                comments = github_client.get_pr_comments(1)

                assert "(bot)" in comments
                assert "codecov[bot]" in comments

    def test_get_pr_comments_multiple_comments_in_thread(self, github_client):
        """Test handling multiple comments in a single thread."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "isResolved": False,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "author": {"login": "user1"},
                                                "body": "First comment",
                                                "path": "file.py",
                                                "line": 1,
                                            },
                                            {
                                                "author": {"login": "user2"},
                                                "body": "Reply to first",
                                                "path": "file.py",
                                                "line": 1,
                                            },
                                        ]
                                    },
                                }
                            ]
                        }
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
                comments = github_client.get_pr_comments(1)

                assert "user1" in comments
                assert "First comment" in comments
                assert "user2" in comments
                assert "Reply to first" in comments

    def test_get_pr_comments_no_comments(self, github_client):
        """Test when there are no review threads."""
        response = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(response),
                    stderr="",
                )
                comments = github_client.get_pr_comments(1)

                assert comments == ""

    def test_get_pr_comments_missing_path_and_line(self, github_client):
        """Test handling comments without path or line information."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "isResolved": False,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "author": {"login": "reviewer"},
                                                "body": "General PR comment",
                                                "path": None,
                                                "line": None,
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
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
                comments = github_client.get_pr_comments(1)

                assert "PR" in comments or "N/A" in comments
                assert "General PR comment" in comments

    def test_get_pr_comments_separator(self, github_client):
        """Test that comments are separated correctly."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "isResolved": False,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "author": {"login": "user1"},
                                                "body": "Comment 1",
                                                "path": "file1.py",
                                                "line": 1,
                                            },
                                            {
                                                "author": {"login": "user2"},
                                                "body": "Comment 2",
                                                "path": "file2.py",
                                                "line": 2,
                                            },
                                        ]
                                    },
                                }
                            ]
                        }
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
                comments = github_client.get_pr_comments(1)

                # Check that separator is used
                assert "---" in comments


# =============================================================================
# GitHubClient.merge_pr Tests
# =============================================================================


class TestGitHubClientMergePR:
    """Tests for PR merge functionality."""

    @pytest.fixture
    def github_client(self):
        """Provide a GitHubClient with mocked auth check."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            client = GitHubClient()
        return client

    def test_merge_pr_success(self, github_client):
        """Test successful PR merge."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            github_client.merge_pr(123)

            mock_run.assert_called_once_with(
                ["gh", "pr", "merge", "123", "--squash", "--auto"],
                check=True,
            )

    def test_merge_pr_converts_number_to_string(self, github_client):
        """Test that PR number is converted to string for command."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            github_client.merge_pr(456)

            call_args = mock_run.call_args[0][0]
            assert "456" in call_args
            assert isinstance(call_args[3], str)  # The PR number argument

    def test_merge_pr_uses_squash_merge(self, github_client):
        """Test that merge uses squash strategy."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            github_client.merge_pr(789)

            call_args = mock_run.call_args[0][0]
            assert "--squash" in call_args

    def test_merge_pr_uses_auto_merge(self, github_client):
        """Test that merge uses auto-merge flag."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            github_client.merge_pr(1)

            call_args = mock_run.call_args[0][0]
            assert "--auto" in call_args

    def test_merge_pr_failure(self, github_client):
        """Test PR merge handles failures."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "gh pr merge", stderr="Cannot merge: checks failing"
            )
            with pytest.raises(subprocess.CalledProcessError):
                github_client.merge_pr(999)

    def test_merge_pr_not_mergeable(self, github_client):
        """Test PR merge when PR is not mergeable."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "gh pr merge", stderr="Pull request is not mergeable"
            )
            with pytest.raises(subprocess.CalledProcessError) as exc_info:
                github_client.merge_pr(100)
            assert exc_info.value.returncode == 1


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
            mock_run.assert_called_once_with(
                ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                check=True,
                capture_output=True,
                text=True,
            )

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
            github_client.merge_pr(100)  # Should succeed


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
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "isResolved": False,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "author": {"login": "user"},
                                                "body": "",
                                                "path": "file.py",
                                                "line": 1,
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
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
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=30)
            with pytest.raises(subprocess.TimeoutExpired):
                github_client.create_pr("Title", "Body")

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
                                                        "name": "unit-tests",
                                                        "status": "COMPLETED",
                                                        "conclusion": "SUCCESS",
                                                        "detailsUrl": "https://example.com/1",
                                                    },
                                                    {
                                                        "name": "integration-tests",
                                                        "status": "COMPLETED",
                                                        "conclusion": "FAILURE",
                                                        "detailsUrl": "https://example.com/2",
                                                    },
                                                    {
                                                        "name": "lint",
                                                        "status": "COMPLETED",
                                                        "conclusion": "SUCCESS",
                                                        "detailsUrl": "https://example.com/3",
                                                    },
                                                    {
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
