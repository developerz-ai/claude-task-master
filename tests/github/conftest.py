"""Pytest configuration and fixtures for GitHub client tests.

This module provides shared fixtures for all GitHub client tests, organized by:
- Client initialization fixtures
- GraphQL response fixtures (for PR status, review threads, CI checks)
- Workflow run fixtures
- Common subprocess mock fixtures
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# GitHubClient Initialization Fixtures
# =============================================================================


@pytest.fixture
def github_client():
    """Provide a GitHubClient with mocked auth check.

    This fixture creates a GitHubClient instance with the gh auth check mocked
    to avoid requiring actual GitHub CLI authentication during tests.
    """
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        from claude_task_master.github.client import GitHubClient

        client = GitHubClient()
    return client


# =============================================================================
# GraphQL Response Fixtures - PR Status
# =============================================================================


@pytest.fixture
def graphql_pr_success_response() -> dict[str, Any]:
    """Provide a GraphQL response for a PR with successful CI and no unresolved threads."""
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "commits": {
                        "nodes": [
                            {
                                "commit": {
                                    "statusCheckRollup": {
                                        "state": "SUCCESS",
                                        "contexts": {
                                            "nodes": [
                                                {
                                                    "__typename": "CheckRun",
                                                    "name": "tests",
                                                    "status": "COMPLETED",
                                                    "conclusion": "SUCCESS",
                                                    "detailsUrl": "https://example.com/check/1",
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


@pytest.fixture
def graphql_pr_failure_response() -> dict[str, Any]:
    """Provide a GraphQL response for a PR with failing CI."""
    return {
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
                                                    "detailsUrl": "https://example.com/check/fail",
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


@pytest.fixture
def graphql_pr_pending_response() -> dict[str, Any]:
    """Provide a GraphQL response for a PR with pending CI."""
    return {
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
                                                    "__typename": "CheckRun",
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


@pytest.fixture
def graphql_pr_no_status_response() -> dict[str, Any]:
    """Provide a GraphQL response for a PR with no status check rollup."""
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "commits": {"nodes": [{"commit": {"statusCheckRollup": None}}]},
                    "reviewThreads": {"nodes": []},
                }
            }
        }
    }


@pytest.fixture
def graphql_pr_empty_commits_response() -> dict[str, Any]:
    """Provide a GraphQL response for a PR with no commits."""
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "commits": {"nodes": []},
                    "reviewThreads": {"nodes": []},
                }
            }
        }
    }


# =============================================================================
# GraphQL Response Fixtures - Review Threads
# =============================================================================


@pytest.fixture
def graphql_pr_with_unresolved_threads() -> dict[str, Any]:
    """Provide a GraphQL response for a PR with unresolved review threads."""
    return {
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
                            {
                                "isResolved": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "reviewer1"},
                                            "body": "Please fix this issue",
                                            "path": "src/main.py",
                                            "line": 42,
                                        }
                                    ]
                                },
                            },
                            {
                                "isResolved": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "reviewer2"},
                                            "body": "This needs refactoring",
                                            "path": "src/utils.py",
                                            "line": 100,
                                        }
                                    ]
                                },
                            },
                            {
                                "isResolved": True,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "reviewer1"},
                                            "body": "Looks good now",
                                            "path": "src/main.py",
                                            "line": 10,
                                        }
                                    ]
                                },
                            },
                        ]
                    },
                }
            }
        }
    }


@pytest.fixture
def graphql_pr_with_bot_comments() -> dict[str, Any]:
    """Provide a GraphQL response for a PR with bot comments."""
    return {
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


# =============================================================================
# Workflow Run Fixtures
# =============================================================================


@pytest.fixture
def workflow_runs_response() -> list[dict[str, Any]]:
    """Provide a sample workflow runs list response."""
    return [
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


@pytest.fixture
def workflow_run_status_response() -> dict[str, Any]:
    """Provide a sample workflow run status response with jobs."""
    return {
        "status": "completed",
        "conclusion": "success",
        "jobs": [
            {"name": "build", "status": "completed", "conclusion": "success"},
            {"name": "test", "status": "completed", "conclusion": "success"},
            {"name": "lint", "status": "completed", "conclusion": "success"},
        ],
    }


@pytest.fixture
def workflow_run_failure_response() -> dict[str, Any]:
    """Provide a sample workflow run status response with failed jobs."""
    return {
        "status": "completed",
        "conclusion": "failure",
        "jobs": [
            {"name": "build", "status": "completed", "conclusion": "success"},
            {"name": "test", "status": "completed", "conclusion": "failure"},
        ],
    }


# =============================================================================
# PRStatus Model Fixtures
# =============================================================================


@pytest.fixture
def pr_status_success():
    """Provide a PRStatus instance with successful CI."""
    from claude_task_master.github.client import PRStatus

    return PRStatus(
        number=123,
        ci_state="SUCCESS",
        unresolved_threads=0,
        check_details=[
            {"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ],
    )


@pytest.fixture
def pr_status_failure():
    """Provide a PRStatus instance with failing CI."""
    from claude_task_master.github.client import PRStatus

    return PRStatus(
        number=123,
        ci_state="FAILURE",
        unresolved_threads=0,
        check_details=[
            {"name": "tests", "status": "COMPLETED", "conclusion": "FAILURE"},
        ],
    )


@pytest.fixture
def pr_status_pending():
    """Provide a PRStatus instance with pending CI."""
    from claude_task_master.github.client import PRStatus

    return PRStatus(
        number=123,
        ci_state="PENDING",
        unresolved_threads=0,
        check_details=[],
    )


# =============================================================================
# Subprocess Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_subprocess_success():
    """Provide a mock for successful subprocess.run calls."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        yield mock_run


@pytest.fixture
def mock_subprocess_failure():
    """Provide a mock for failed subprocess.run calls."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Command failed",
        )
        yield mock_run


@pytest.fixture
def mock_repo_info(github_client):
    """Provide a context manager that mocks _get_repo_info."""
    with patch.object(github_client, "_get_repo_info", return_value="owner/repo"):
        yield github_client
