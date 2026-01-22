"""GitHub PR Operations - PR creation, status, and comments."""

import json
import subprocess
from typing import Any, Protocol

from pydantic import BaseModel


class PRStatus(BaseModel):
    """PR status information."""

    number: int
    state: str = "OPEN"  # OPEN, CLOSED, MERGED
    ci_state: str  # PENDING, SUCCESS, FAILURE, ERROR
    unresolved_threads: int
    resolved_threads: int = 0
    total_threads: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    checks_pending: int = 0
    checks_skipped: int = 0
    check_details: list[dict[str, Any]]
    # Mergeable status
    mergeable: str = "UNKNOWN"  # MERGEABLE, CONFLICTING, UNKNOWN
    merge_state_status: str = (
        "UNKNOWN"  # BLOCKED, BEHIND, CLEAN, DIRTY, HAS_HOOKS, UNKNOWN, UNSTABLE
    )
    base_branch: str = "main"


class GitHubClientProtocol(Protocol):
    """Protocol defining the methods required from GitHubClient."""

    def _run_gh_command(
        self,
        cmd: list[str],
        timeout: int = 30,
        check: bool = True,
        capture_output: bool = True,
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a gh CLI command."""
        raise NotImplementedError("Protocol method must be implemented")

    def _get_repo_info(self) -> str:
        """Get repository info."""
        raise NotImplementedError("Protocol method must be implemented")


class PROperationsMixin:
    """Mixin class providing PR operations for GitHubClient.

    This class should be used with GitHubClient to add PR-related functionality.
    It depends on _run_gh_command and _get_repo_info being available.
    """

    def create_pr(self: GitHubClientProtocol, title: str, body: str, base: str = "main") -> int:
        """Create a new pull request.

        Args:
            title: PR title.
            body: PR body/description.
            base: Base branch to merge into.

        Returns:
            The created PR number.

        Raises:
            GitHubError: If PR creation fails.
            GitHubTimeoutError: If command times out.
        """
        result = self._run_gh_command(
            ["gh", "pr", "create", "--title", title, "--body", body, "--base", base],
            timeout=60,  # PR creation can take a bit longer
        )

        # Extract PR number from output
        # gh CLI outputs URL like: https://github.com/owner/repo/pull/123
        output = result.stdout.strip()
        pr_number = int(output.split("/")[-1])

        return pr_number

    def get_pr_status(self: GitHubClientProtocol, pr_number: int) -> PRStatus:
        """Get PR status including CI checks and review comments.

        Args:
            pr_number: The PR number to check.

        Returns:
            PRStatus with CI state, checks, and thread counts.

        Raises:
            GitHubError: If GraphQL query fails.
            GitHubTimeoutError: If command times out.
        """
        # Get repository info
        repo_info = self._get_repo_info()
        owner, repo = repo_info.split("/")

        # Run GraphQL query
        query = _build_pr_status_query()

        result = self._run_gh_command(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"repo={repo}",
                "-F",
                f"pr={pr_number}",
            ],
            timeout=30,
        )

        data = json.loads(result.stdout)
        pr_data = data["data"]["repository"]["pullRequest"]

        return _parse_pr_status_response(pr_number, pr_data)

    def get_required_status_checks(
        self: GitHubClientProtocol, base_branch: str = "main"
    ) -> list[str]:
        """Get required status checks from branch protection rules.

        Args:
            base_branch: The base branch to check protection for.

        Returns:
            List of required check context names.
        """
        from .exceptions import GitHubError, GitHubTimeoutError

        repo_info = self._get_repo_info()
        try:
            result = self._run_gh_command(
                [
                    "gh",
                    "api",
                    f"repos/{repo_info}/branches/{base_branch}/protection/required_status_checks",
                    "--jq",
                    ".contexts",
                ],
                timeout=15,
            )
            # Parse JSON array of context names
            contexts = json.loads(result.stdout)
            return contexts if isinstance(contexts, list) else []
        except (GitHubError, GitHubTimeoutError):
            # No branch protection or no required checks
            return []

    def get_pr_for_current_branch(self: GitHubClientProtocol, cwd: str | None = None) -> int | None:
        """Get PR number for the current branch, if one exists.

        Args:
            cwd: Working directory to run the command in (project root).

        Returns:
            PR number if one exists, None otherwise.
        """
        from .exceptions import GitHubError, GitHubTimeoutError

        try:
            result = self._run_gh_command(
                ["gh", "pr", "view", "--json", "number"],
                timeout=15,
                cwd=cwd,
            )
            data = json.loads(result.stdout)
            pr_number = data.get("number")
            return int(pr_number) if pr_number is not None else None
        except (GitHubError, GitHubTimeoutError):
            # No PR exists for current branch or command failed
            return None

    def get_pr_comments(
        self: GitHubClientProtocol, pr_number: int, only_unresolved: bool = True
    ) -> str:
        """Get PR review comments formatted for Claude.

        Uses REST API to get all comments (like tstc), then enriches with
        resolved status from GraphQL.

        Args:
            pr_number: The PR number.
            only_unresolved: If True, only return unresolved comments.

        Returns:
            Formatted string of PR comments.

        Raises:
            GitHubError: If API calls fail.
            GitHubTimeoutError: If command times out.
        """
        # Get repository info
        repo_info = self._get_repo_info()

        # Use REST API to get ALL PR review comments (like tstc)
        result = self._run_gh_command(
            ["gh", "api", "--paginate", f"repos/{repo_info}/pulls/{pr_number}/comments"],
            timeout=60,
        )
        all_comments = json.loads(result.stdout)

        # Get resolved status from GraphQL
        resolved_map = _get_comment_resolved_map(self, repo_info, pr_number)

        # Format comments
        return _format_pr_comments_from_rest(all_comments, resolved_map, only_unresolved)


def _get_comment_resolved_map(
    client: GitHubClientProtocol, repo_info: str, pr_number: int
) -> dict[int, bool]:
    """Get resolved status for all comments from GraphQL.

    Returns a map of comment_id (databaseId) -> is_resolved.
    """
    owner, repo = repo_info.split("/")

    query = """
    query($owner: String!, $repo: String!, $pr: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          reviewThreads(first: 100) {
            nodes {
              isResolved
              comments(first: 100) {
                nodes {
                  databaseId
                }
              }
            }
          }
        }
      }
    }
    """

    try:
        result = client._run_gh_command(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"repo={repo}",
                "-F",
                f"pr={pr_number}",
            ],
            timeout=30,
        )

        data = json.loads(result.stdout)
        threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]

        resolved_map: dict[int, bool] = {}
        for thread in threads:
            is_resolved = thread.get("isResolved", False)
            for comment in thread.get("comments", {}).get("nodes", []):
                db_id = comment.get("databaseId")
                if db_id:
                    resolved_map[db_id] = is_resolved

        return resolved_map
    except Exception:
        return {}


def _build_pr_status_query() -> str:
    """Build GraphQL query for PR status."""
    return """
    query($owner: String!, $repo: String!, $pr: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          state
          mergeable
          mergeStateStatus
          baseRefName
          commits(last: 1) {
            nodes {
              commit {
                statusCheckRollup {
                  state
                  contexts(first: 50) {
                    nodes {
                      __typename
                      ... on CheckRun {
                        name
                        status
                        conclusion
                        detailsUrl
                      }
                      ... on StatusContext {
                        context
                        state
                        targetUrl
                      }
                    }
                  }
                }
              }
            }
          }
          reviewThreads(first: 100) {
            nodes {
              isResolved
              comments(first: 10) {
                nodes {
                  author { login }
                  body
                  path
                  line
                }
              }
            }
          }
        }
      }
    }
    """


def _parse_pr_status_response(pr_number: int, pr_data: dict[str, Any]) -> PRStatus:
    """Parse GraphQL response into PRStatus object.

    Args:
        pr_number: The PR number.
        pr_data: The pullRequest data from GraphQL response.

    Returns:
        Parsed PRStatus object.
    """
    # Parse CI status
    ci_state = "PENDING"
    check_details: list[dict[str, Any]] = []

    if pr_data["commits"]["nodes"]:
        commit = pr_data["commits"]["nodes"][0]["commit"]
        if commit["statusCheckRollup"]:
            ci_state = commit["statusCheckRollup"]["state"]
            contexts = commit["statusCheckRollup"]["contexts"]["nodes"]
            check_details = _parse_check_contexts(contexts)

    # Count review threads
    threads = pr_data["reviewThreads"]["nodes"]
    total_threads = len(threads)
    unresolved = sum(1 for thread in threads if not thread["isResolved"])
    resolved = total_threads - unresolved

    # Count check statuses (GitHub API returns uppercase values)
    checks_passed = sum(
        1 for c in check_details if (c.get("conclusion") or "").upper() in ("SUCCESS", "NEUTRAL")
    )
    checks_failed = sum(
        1
        for c in check_details
        if (c.get("conclusion") or "").upper() in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT")
    )
    checks_skipped = sum(
        1 for c in check_details if (c.get("conclusion") or "").upper() == "SKIPPED"
    )
    checks_pending = len(check_details) - checks_passed - checks_failed - checks_skipped

    # Parse PR state and mergeable status
    state = pr_data.get("state", "OPEN")
    mergeable = pr_data.get("mergeable", "UNKNOWN")
    merge_state_status = pr_data.get("mergeStateStatus", "UNKNOWN")
    base_branch = pr_data.get("baseRefName", "main")

    return PRStatus(
        number=pr_number,
        state=state,
        ci_state=ci_state,
        unresolved_threads=unresolved,
        resolved_threads=resolved,
        total_threads=total_threads,
        checks_passed=checks_passed,
        checks_failed=checks_failed,
        checks_pending=checks_pending,
        checks_skipped=checks_skipped,
        check_details=check_details,
        mergeable=mergeable,
        merge_state_status=merge_state_status,
        base_branch=base_branch,
    )


def _parse_check_contexts(contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse check contexts from GraphQL response.

    Args:
        contexts: List of check context nodes.

    Returns:
        List of normalized check detail dictionaries.
    """
    check_details = []
    for ctx in contexts:
        # Handle both CheckRun and StatusContext types
        if ctx.get("__typename") == "CheckRun":
            check_details.append(
                {
                    "name": ctx.get("name", "unknown"),
                    "status": ctx.get("status", "unknown"),
                    "conclusion": ctx.get("conclusion"),
                    "url": ctx.get("detailsUrl"),
                }
            )
        elif ctx.get("__typename") == "StatusContext":
            # StatusContext uses 'context' for name and 'state' for status
            check_details.append(
                {
                    "name": ctx.get("context", "unknown"),
                    "context": ctx.get("context", "unknown"),
                    "status": ctx.get("state", "unknown"),
                    "conclusion": ctx.get("state"),  # state is the conclusion for StatusContext
                    "url": ctx.get("targetUrl"),
                }
            )
    return check_details


def _format_pr_comments(threads: list[dict[str, Any]], only_unresolved: bool) -> str:
    """Format PR review threads into a readable string.

    Args:
        threads: List of review thread nodes.
        only_unresolved: If True, only include unresolved threads.

    Returns:
        Formatted string of comments.
    """
    formatted = []
    for thread in threads:
        if only_unresolved and thread["isResolved"]:
            continue

        for comment in thread["comments"]["nodes"]:
            author = comment["author"]["login"]
            is_bot = author.endswith("[bot]")
            bot_marker = " (bot)" if is_bot else ""

            formatted.append(
                f"**{author}{bot_marker}** on {comment.get('path', 'PR')}:"
                f"{comment.get('line', 'N/A')}\n{comment['body']}\n"
            )

    return "\n---\n\n".join(formatted)


def _format_pr_comments_from_rest(
    comments: list[dict[str, Any]], resolved_map: dict[int, bool], only_unresolved: bool
) -> str:
    """Format PR review comments from REST API into a readable string.

    Args:
        comments: List of comment dicts from REST API.
        resolved_map: Map of comment_id -> is_resolved from GraphQL.
        only_unresolved: If True, only include unresolved comments.

    Returns:
        Formatted string of comments.
    """
    formatted = []
    for comment in comments:
        comment_id = comment.get("id")
        is_resolved = resolved_map.get(comment_id, False) if comment_id else False

        if only_unresolved and is_resolved:
            continue

        author = comment.get("user", {}).get("login", "unknown")
        is_bot = author.endswith("[bot]")
        bot_marker = " (bot)" if is_bot else ""

        path = comment.get("path", "PR")
        line = comment.get("line") or comment.get("original_line") or "N/A"
        body = comment.get("body", "")

        formatted.append(f"**{author}{bot_marker}** on {path}:{line}\n{body}\n")

    return "\n---\n\n".join(formatted)
