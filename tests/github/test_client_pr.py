"""Tests for GitHub client PR creation, status, and comments functionality."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.github.client import (
    GitHubTimeoutError,
    PRStatus,
)
from claude_task_master.github.exceptions import GitHubError

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

    def test_pr_status_new_fields_have_defaults(self):
        """Test that new PRStatus fields fall back to sensible defaults."""
        status = PRStatus(
            number=1,
            ci_state="SUCCESS",
            unresolved_threads=0,
            check_details=[],
        )
        assert status.state == "OPEN"
        assert status.resolved_threads == 0
        assert status.total_threads == 0
        assert status.checks_passed == 0
        assert status.checks_failed == 0
        assert status.checks_pending == 0
        assert status.checks_skipped == 0
        assert status.mergeable == "UNKNOWN"
        assert status.merge_state_status == "UNKNOWN"
        assert status.base_branch == "main"
        assert status.title == ""
        assert status.url == ""
        assert status.head_branch == ""
        assert status.merged_at is None

    def test_pr_status_new_fields_set_explicitly(self):
        """Test creating PRStatus with the new fields set explicitly."""
        status = PRStatus(
            number=42,
            state="MERGED",
            ci_state="SUCCESS",
            unresolved_threads=1,
            resolved_threads=3,
            total_threads=4,
            checks_passed=2,
            checks_failed=1,
            checks_pending=1,
            checks_skipped=1,
            check_details=[],
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            base_branch="develop",
            title="My PR",
            url="https://github.com/owner/repo/pull/42",
            head_branch="feature-x",
            merged_at="2026-07-18T12:00:00Z",
        )
        assert status.state == "MERGED"
        assert status.resolved_threads == 3
        assert status.total_threads == 4
        assert status.checks_passed == 2
        assert status.checks_failed == 1
        assert status.checks_pending == 1
        assert status.checks_skipped == 1
        assert status.mergeable == "MERGEABLE"
        assert status.merge_state_status == "CLEAN"
        assert status.base_branch == "develop"
        assert status.title == "My PR"
        assert status.url == "https://github.com/owner/repo/pull/42"
        assert status.head_branch == "feature-x"
        assert status.merged_at == "2026-07-18T12:00:00Z"

    def test_pr_status_new_fields_in_model_dump(self):
        """Test that new fields are included in serialized output."""
        status = PRStatus(
            number=7,
            ci_state="PENDING",
            unresolved_threads=0,
            check_details=[],
            mergeable="CONFLICTING",
            merge_state_status="DIRTY",
        )
        data = status.model_dump()
        assert data["mergeable"] == "CONFLICTING"
        assert data["merge_state_status"] == "DIRTY"
        assert data["state"] == "OPEN"
        assert data["checks_pending"] == 0
        assert data["merged_at"] is None


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
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Error creating PR",
            )
            with pytest.raises(GitHubError) as exc_info:
                github_client.create_pr("Title", "Body")
            assert "Error creating PR" in str(exc_info.value)

    def test_create_pr_parses_url_with_trailing_output(self, github_client):
        """Test that the PR number is parsed from gh output with extra text."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Creating pull request\nhttps://github.com/owner/repo/pull/42\n",
                stderr="",
            )
            pr_number = github_client.create_pr("Title", "Body")
            assert pr_number == 42

    def test_create_pr_garbage_output_raises_github_error(self, github_client):
        """Test that unparseable gh output raises GitHubError with the raw output."""
        raw_output = "no pull request was created\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=raw_output,
                stderr="",
            )
            with pytest.raises(GitHubError) as exc_info:
                github_client.create_pr("Title", "Body")
            assert raw_output.strip() in str(exc_info.value)

    def test_create_pr_pull_mention_without_number_raises_github_error(self, github_client):
        """Test that a '/pull/' mention without a trailing number raises GitHubError."""
        raw_output = "see https://github.com/owner/repo/pull/ for details\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=raw_output,
                stderr="",
            )
            with pytest.raises(GitHubError) as exc_info:
                github_client.create_pr("Title", "Body")
            assert "Could not parse PR URL" in str(exc_info.value)

    def test_create_pr_empty_output_raises_github_error(self, github_client):
        """Test that empty gh output raises GitHubError even on success exit code."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr="",
            )
            with pytest.raises(GitHubError) as exc_info:
                github_client.create_pr("Title", "Body")
            assert "Could not parse PR URL" in str(exc_info.value)

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
# GitHubClient.get_required_status_checks Tests
# =============================================================================


class TestGitHubClientGetRequiredStatusChecks:
    """Tests for required status checks retrieval from branch protection."""

    def test_get_required_status_checks_success(self, github_client):
        """Test getting required status checks returns the parsed list."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(["lint", "tests"]),
                    stderr="",
                )
                checks = github_client.get_required_status_checks("main")

                assert checks == ["lint", "tests"]
                call_args = mock_run.call_args
                assert call_args[0][0] == [
                    "gh",
                    "api",
                    "repos/owner/repo/branches/main/protection/required_status_checks",
                    "--jq",
                    ".contexts",
                ]

    def test_get_required_status_checks_non_list_json_returns_empty(self, github_client):
        """Test that non-list JSON output returns an empty list."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps({"contexts": ["lint"]}),
                    stderr="",
                )
                checks = github_client.get_required_status_checks("main")

                assert checks == []

    def test_get_required_status_checks_not_found_returns_empty(self, github_client):
        """Test that a 404 'not found' response means no branch protection."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr='{"message": "Not Found", "documentation_url": "https://..."}',
                )
                checks = github_client.get_required_status_checks("main")

                assert checks == []

    def test_get_required_status_checks_branch_not_protected_returns_empty(self, github_client):
        """Test that 'branch not protected' stderr returns an empty list."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Branch not protected",
                )
                checks = github_client.get_required_status_checks("main")

                assert checks == []

    def test_get_required_status_checks_auth_failure_raises(self, github_client):
        """Test that an auth failure raises GitHubError with the stderr message."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Resource not accessible by integration",
                )
                with pytest.raises(GitHubError) as exc_info:
                    github_client.get_required_status_checks("main")
                assert "Resource not accessible by integration" in str(exc_info.value)

    def test_get_required_status_checks_timeout_propagates(self, github_client):
        """Test that a command timeout raises GitHubTimeoutError."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=15)
                with pytest.raises(GitHubTimeoutError) as exc_info:
                    github_client.get_required_status_checks("main")
                assert "timed out" in str(exc_info.value)

    def test_get_required_status_checks_rate_limit_raises(self, github_client):
        """Test that a rate limit error propagates as GitHubError with the stderr message."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="API rate limit exceeded for user ID 123.",
                )
                with pytest.raises(GitHubError) as exc_info:
                    github_client.get_required_status_checks("main")
                assert "API rate limit exceeded" in str(exc_info.value)

    def test_get_required_status_checks_error_includes_branch_name(self, github_client):
        """Test that propagated errors mention the base branch that was queried."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Resource not accessible by integration",
                )
                with pytest.raises(GitHubError) as exc_info:
                    github_client.get_required_status_checks("release/1.x")
                assert "'release/1.x'" in str(exc_info.value)
                assert "Resource not accessible by integration" in str(exc_info.value)

    def test_get_required_status_checks_malformed_json_raises(self, github_client):
        """Test that malformed JSON output propagates a JSONDecodeError."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="{ not valid json }",
                    stderr="",
                )
                with pytest.raises(json.JSONDecodeError):
                    github_client.get_required_status_checks("main")


# =============================================================================
# GitHubClient.get_pr_body / update_pr_body Tests
# =============================================================================


class TestGitHubClientPRBody:
    """Tests for reading and rewriting a PR body."""

    def test_get_pr_body_uses_null_safe_jq(self, github_client):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Body text\n", stderr="")
            body = github_client.get_pr_body(7)
            assert body == "Body text"
            # `.body // ""` avoids the literal "null" gh -q prints for a body-less PR.
            assert mock_run.call_args[0][0] == [
                "gh",
                "pr",
                "view",
                "7",
                "--json",
                "body",
                "-q",
                '.body // ""',
            ]

    def test_update_pr_body(self, github_client):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            github_client.update_pr_body(7, "New body")
            assert mock_run.call_args[0][0] == ["gh", "pr", "edit", "7", "--body", "New body"]


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

    def test_get_pr_status_populates_new_fields(self, github_client):
        """Test that new PRStatus fields are populated from the GraphQL response."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "state": "OPEN",
                        "mergeable": "MERGEABLE",
                        "mergeStateStatus": "CLEAN",
                        "baseRefName": "develop",
                        "title": "Add feature",
                        "url": "https://github.com/owner/repo/pull/99",
                        "headRefName": "feature-branch",
                        "mergedAt": None,
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
                                                        "detailsUrl": "https://example.com/1",
                                                    },
                                                    {
                                                        "__typename": "CheckRun",
                                                        "name": "lint",
                                                        "status": "COMPLETED",
                                                        "conclusion": "SUCCESS",
                                                        "detailsUrl": "https://example.com/2",
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
                        "reviewThreads": {
                            "nodes": [
                                {"isResolved": False, "comments": {"nodes": []}},
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
                status = github_client.get_pr_status(99)

                assert status.state == "OPEN"
                assert status.mergeable == "MERGEABLE"
                assert status.merge_state_status == "CLEAN"
                assert status.base_branch == "develop"
                assert status.title == "Add feature"
                assert status.url == "https://github.com/owner/repo/pull/99"
                assert status.head_branch == "feature-branch"
                assert status.merged_at is None
                assert status.total_threads == 2
                assert status.unresolved_threads == 1
                assert status.resolved_threads == 1
                assert status.checks_failed == 1
                assert status.checks_passed == 1
                assert status.checks_pending == 1
                assert status.checks_skipped == 0

    def test_get_pr_status_merged_pr_fields(self, github_client):
        """Test that a merged PR reports MERGED state and merged_at timestamp."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "state": "MERGED",
                        "mergeable": "UNKNOWN",
                        "mergeStateStatus": "UNKNOWN",
                        "baseRefName": "main",
                        "title": "Done",
                        "url": "https://github.com/owner/repo/pull/5",
                        "headRefName": "old-feature",
                        "mergedAt": "2026-07-17T09:30:00Z",
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
                status = github_client.get_pr_status(5)

                assert status.state == "MERGED"
                assert status.merged_at == "2026-07-17T09:30:00Z"

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
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="GraphQL error",
                )
                with pytest.raises(GitHubError) as exc_info:
                    github_client.get_pr_status(123)
                assert "GraphQL error" in str(exc_info.value)

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


def _comments_to_ndjson(comments: list[dict]) -> str:
    """Convert REST comment list to NDJSON (one object per line).

    Matches the output of ``gh api --paginate --jq '.[]'``.
    """
    import json as _json

    return "\n".join(_json.dumps(c) for c in comments)


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
                    MagicMock(returncode=0, stdout=_comments_to_ndjson(rest_comments), stderr=""),
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
                    MagicMock(returncode=0, stdout=_comments_to_ndjson(rest_comments), stderr=""),
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
                    MagicMock(returncode=0, stdout=_comments_to_ndjson(rest_comments), stderr=""),
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
                    MagicMock(returncode=0, stdout=_comments_to_ndjson(rest_comments), stderr=""),
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
                    MagicMock(returncode=0, stdout=_comments_to_ndjson(rest_comments), stderr=""),
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
        graphql_response: dict = {
            "data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}
        }

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=_comments_to_ndjson(rest_comments), stderr=""),
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
                    MagicMock(returncode=0, stdout=_comments_to_ndjson(rest_comments), stderr=""),
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
                    MagicMock(returncode=0, stdout=_comments_to_ndjson(rest_comments), stderr=""),
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
                    MagicMock(returncode=0, stdout=_comments_to_ndjson(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(graphql_response), stderr=""),
                ]
                # Should not raise, just return formatted output
                comments = github_client.get_pr_comments(1)
                assert "user" in comments


# =============================================================================
# cwd threading tests: get_pr_status / _get_repo_info
# =============================================================================


class TestCwdThreading:
    """Tests that cwd is forwarded through get_pr_status → _get_repo_info."""

    def test_get_repo_info_passes_cwd_to_run_gh_command(self, github_client):
        """_get_repo_info(cwd=...) forwards the cwd arg to _run_gh_command."""
        with patch.object(
            github_client,
            "_run_gh_command",
            return_value=MagicMock(returncode=0, stdout="owner/repo\n", stderr=""),
        ) as mock_cmd:
            github_client._get_repo_info(cwd="/my/project")

        _, call_kwargs = mock_cmd.call_args
        assert call_kwargs.get("cwd") == "/my/project"

    def test_get_pr_status_passes_cwd_to_get_repo_info(
        self, github_client, sample_pr_graphql_response
    ):
        """get_pr_status(cwd=...) passes cwd to _get_repo_info and the GraphQL call."""
        received_cwds: list = []

        def fake_get_repo_info(cwd: str | None = None) -> str:
            received_cwds.append(cwd)
            return "owner/repo"

        with patch.object(github_client, "_get_repo_info", side_effect=fake_get_repo_info):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(sample_pr_graphql_response),
                    stderr="",
                )
                github_client.get_pr_status(123, cwd="/some/path")

        assert received_cwds == ["/some/path"]

    def test_get_pr_status_graphql_call_uses_cwd(self, github_client, sample_pr_graphql_response):
        """The GraphQL subprocess call in get_pr_status receives the cwd argument."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(sample_pr_graphql_response),
                    stderr="",
                )
                github_client.get_pr_status(123, cwd="/proj/root")

        # subprocess.run must have been called with cwd="/proj/root"
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("cwd") == "/proj/root"

    def test_get_pr_status_cwd_none_by_default(self, github_client, sample_pr_graphql_response):
        """get_pr_status cwd defaults to None (uses process CWD)."""
        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps(sample_pr_graphql_response),
                    stderr="",
                )
                github_client.get_pr_status(123)

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("cwd") is None


# =============================================================================
# _get_comment_resolved_map pagination (2-page comments)
# =============================================================================


def _make_graphql_threads_page(
    threads: list[tuple[int, bool]],
    has_next: bool,
    cursor: str | None = None,
) -> dict:
    """Build a GraphQL reviewThreads page response.

    Args:
        threads: List of (comment_db_id, is_resolved) tuples for this page.
        has_next: Whether there is a following page.
        cursor: The endCursor value to return (only meaningful when has_next=True).
    """
    nodes = [
        {
            "isResolved": resolved,
            "comments": {"nodes": [{"databaseId": db_id}]},
        }
        for db_id, resolved in threads
    ]
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                        "nodes": nodes,
                    }
                }
            }
        }
    }


class TestGetCommentResolvedMapPagination:
    """Tests for _get_comment_resolved_map pagination (2-page comments)."""

    def test_single_page_no_pagination(self, github_client):
        """Single-page response issues exactly one GraphQL call."""
        from claude_task_master.github.client_pr import _get_comment_resolved_map

        page = _make_graphql_threads_page([(1, False), (2, True)], has_next=False)

        with patch.object(
            github_client,
            "_run_gh_command",
            return_value=MagicMock(returncode=0, stdout=json.dumps(page), stderr=""),
        ) as mock_cmd:
            resolved_map = _get_comment_resolved_map(github_client, "owner/repo", 7)

        assert resolved_map == {1: False, 2: True}
        assert mock_cmd.call_count == 1

    def test_two_page_pagination_fetches_second_page(self, github_client):
        """When hasNextPage=True the second page is fetched with the cursor."""
        from claude_task_master.github.client_pr import _get_comment_resolved_map

        page1 = _make_graphql_threads_page([(101, False)], has_next=True, cursor="abc123")
        page2 = _make_graphql_threads_page([(102, True)], has_next=False)

        with patch.object(
            github_client,
            "_run_gh_command",
            side_effect=[
                MagicMock(returncode=0, stdout=json.dumps(page1), stderr=""),
                MagicMock(returncode=0, stdout=json.dumps(page2), stderr=""),
            ],
        ) as mock_cmd:
            resolved_map = _get_comment_resolved_map(github_client, "owner/repo", 42)

        # Both pages' comments merged into one map
        assert resolved_map == {101: False, 102: True}
        assert mock_cmd.call_count == 2

    def test_second_page_cursor_passed_in_command(self, github_client):
        """The cursor from page 1 is sent as -f cursor=<value> in the page-2 call."""
        from claude_task_master.github.client_pr import _get_comment_resolved_map

        page1 = _make_graphql_threads_page([(1, False)], has_next=True, cursor="cursor-xyz")
        page2 = _make_graphql_threads_page([(2, True)], has_next=False)

        calls: list[list[str]] = []

        def capture(cmd: list[str], **_kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            page = page1 if len(calls) == 1 else page2
            return MagicMock(returncode=0, stdout=json.dumps(page), stderr="")

        with patch.object(github_client, "_run_gh_command", side_effect=capture):
            _get_comment_resolved_map(github_client, "owner/repo", 99)

        assert len(calls) == 2
        # Page 1 must NOT include -f cursor=...
        page1_cmd = calls[0]
        assert not any("cursor=" in arg for arg in page1_cmd)
        # Page 2 must include -f cursor=cursor-xyz
        page2_cmd = calls[1]
        assert "-f" in page2_cmd
        cursor_args = [a for a in page2_cmd if a.startswith("cursor=")]
        assert cursor_args == ["cursor=cursor-xyz"]

    def test_two_page_comments_are_deduplicated_correctly(self, github_client):
        """Comments appearing on both pages with conflicting resolved-status use the last-seen value."""
        from claude_task_master.github.client_pr import _get_comment_resolved_map

        # Comment 50 appears on page 1 as unresolved and does NOT appear on page 2.
        page1 = _make_graphql_threads_page([(50, False), (51, True)], has_next=True, cursor="pg2")
        page2 = _make_graphql_threads_page([(52, False)], has_next=False)

        with patch.object(
            github_client,
            "_run_gh_command",
            side_effect=[
                MagicMock(returncode=0, stdout=json.dumps(page1), stderr=""),
                MagicMock(returncode=0, stdout=json.dumps(page2), stderr=""),
            ],
        ):
            resolved_map = _get_comment_resolved_map(github_client, "owner/repo", 1)

        assert resolved_map[50] is False
        assert resolved_map[51] is True
        assert resolved_map[52] is False

    def test_graphql_error_on_first_page_returns_empty(self, github_client):
        """A GraphQL error on the first page returns an empty map (graceful degradation)."""
        from claude_task_master.github.client_pr import _get_comment_resolved_map

        error_response = {"errors": [{"message": "Something went wrong"}]}

        with patch.object(
            github_client,
            "_run_gh_command",
            return_value=MagicMock(returncode=0, stdout=json.dumps(error_response), stderr=""),
        ):
            resolved_map = _get_comment_resolved_map(github_client, "owner/repo", 1)

        assert resolved_map == {}

    def test_get_pr_comments_integrates_two_page_resolved_map(self, github_client):
        """get_pr_comments correctly filters unresolved comments across a 2-page thread map."""
        rest_comments = [
            _make_rest_comment(101, "alice", "Fix the loop", "src/core.py", 10),
            _make_rest_comment(102, "bob", "LGTM", "src/core.py", 20),
        ]
        # Resolved status comes from two GraphQL pages
        page1 = _make_graphql_threads_page([(101, False)], has_next=True, cursor="next")
        page2 = _make_graphql_threads_page([(102, True)], has_next=False)

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                # Call 1: REST comment list, Calls 2-3: GraphQL pages 1 and 2
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout=_comments_to_ndjson(rest_comments), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(page1), stderr=""),
                    MagicMock(returncode=0, stdout=json.dumps(page2), stderr=""),
                ]
                comments = github_client.get_pr_comments(123, only_unresolved=True)

        # Comment 101 (unresolved) should be included, 102 (resolved) should not
        assert "alice" in comments
        assert "Fix the loop" in comments
        assert "bob" not in comments
        assert "LGTM" not in comments


# =============================================================================
# 51-check contexts pagination warning (hasNextPage=True on CI contexts)
# =============================================================================


def _make_pr_status_response_with_checks(check_count: int, has_next_page: bool) -> dict:
    """Build a GraphQL PR status response with the specified number of CheckRun nodes.

    Args:
        check_count: How many CheckRun nodes to include.
        has_next_page: Value for contexts.pageInfo.hasNextPage.
    """
    check_nodes = [
        {
            "__typename": "CheckRun",
            "name": f"check-{i}",
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
            "detailsUrl": f"https://example.com/check/{i}",
        }
        for i in range(check_count)
    ]
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "state": "OPEN",
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "baseRefName": "main",
                    "title": "Test PR",
                    "url": "https://github.com/owner/repo/pull/1",
                    "headRefName": "feature",
                    "mergedAt": None,
                    "commits": {
                        "nodes": [
                            {
                                "commit": {
                                    "statusCheckRollup": {
                                        "state": "SUCCESS",
                                        "contexts": {
                                            "pageInfo": {"hasNextPage": has_next_page},
                                            "nodes": check_nodes,
                                        },
                                    }
                                }
                            }
                        ]
                    },
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [],
                    },
                }
            }
        }
    }


class TestPRStatusContextsPagination:
    """Tests for get_pr_status behaviour when CI contexts have hasNextPage=True."""

    def test_51_checks_issues_warning(self, github_client, caplog):
        """get_pr_status logs a warning when contexts.hasNextPage is True."""
        import logging

        response = _make_pr_status_response_with_checks(51, has_next_page=True)

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout=json.dumps(response), stderr=""
                )
                with caplog.at_level(logging.WARNING):
                    status = github_client.get_pr_status(1)

        assert status.ci_state == "SUCCESS"
        assert len(status.check_details) == 51
        assert any(
            ">100" in rec.message or "some checks" in rec.message.lower() for rec in caplog.records
        ), "Expected a warning about truncated check contexts"

    def test_51_checks_all_counted_as_passed(self, github_client):
        """All 51 visible checks count toward checks_passed when all succeed."""
        response = _make_pr_status_response_with_checks(51, has_next_page=True)

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout=json.dumps(response), stderr=""
                )
                status = github_client.get_pr_status(1)

        assert status.checks_passed == 51
        assert status.checks_failed == 0

    def test_no_warning_when_has_next_page_false(self, github_client, caplog):
        """No warning is emitted when contexts.hasNextPage is False."""
        import logging

        response = _make_pr_status_response_with_checks(3, has_next_page=False)

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout=json.dumps(response), stderr=""
                )
                with caplog.at_level(logging.WARNING):
                    status = github_client.get_pr_status(1)

        assert len(status.check_details) == 3
        assert not any(">100" in rec.message for rec in caplog.records)

    def test_mixed_conclusions_with_has_next_page(self, github_client):
        """Checks with mixed conclusions are counted correctly even when hasNextPage=True."""
        # Build response with 2 SUCCESS, 1 FAILURE, 1 IN_PROGRESS
        check_nodes = [
            {
                "__typename": "CheckRun",
                "name": "pass-1",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "detailsUrl": "https://example.com/1",
            },
            {
                "__typename": "CheckRun",
                "name": "pass-2",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "detailsUrl": "https://example.com/2",
            },
            {
                "__typename": "CheckRun",
                "name": "fail-1",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "detailsUrl": "https://example.com/3",
            },
            {
                "__typename": "CheckRun",
                "name": "pending-1",
                "status": "IN_PROGRESS",
                "conclusion": None,
                "detailsUrl": None,
            },
        ]
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "state": "OPEN",
                        "mergeable": "MERGEABLE",
                        "mergeStateStatus": "CLEAN",
                        "baseRefName": "main",
                        "title": "Mixed",
                        "url": "https://github.com/owner/repo/pull/2",
                        "headRefName": "feature",
                        "mergedAt": None,
                        "commits": {
                            "nodes": [
                                {
                                    "commit": {
                                        "statusCheckRollup": {
                                            "state": "FAILURE",
                                            "contexts": {
                                                "pageInfo": {"hasNextPage": True},
                                                "nodes": check_nodes,
                                            },
                                        }
                                    }
                                }
                            ]
                        },
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": [],
                        },
                    }
                }
            }
        }

        with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout=json.dumps(response), stderr=""
                )
                status = github_client.get_pr_status(2)

        assert status.checks_passed == 2
        assert status.checks_failed == 1
        assert status.checks_pending == 1
