"""GraphQL query builders, response parsers, and comment formatters for PR operations."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from .client_pr_models import GitHubClientProtocol, PRStatus


def _get_comment_resolved_map(
    client: GitHubClientProtocol, repo_info: str, pr_number: int
) -> dict[int, bool]:
    """Get resolved status for all comments from GraphQL.

    Paginates through all review threads to handle PRs with > 100 threads.

    Returns:
        Map of comment_id (databaseId) -> is_resolved.
    """
    owner, repo = repo_info.split("/")

    # $cursor is a nullable String; omit the variable on the first page
    # (gh cli treats an undefined nullable variable as null).
    query = """
    query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          reviewThreads(first: 100, after: $cursor) {
            pageInfo { hasNextPage endCursor }
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

    resolved_map: dict[int, bool] = {}
    cursor: str | None = None

    try:
        while True:
            cmd = [
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
            ]
            if cursor:
                cmd.extend(["-f", f"cursor={cursor}"])

            result = client._run_gh_command(cmd, timeout=30)
            data = json.loads(result.stdout)

            # Handle GraphQL errors gracefully
            if "errors" in data or data.get("data") is None:
                break

            pr = data["data"].get("repository", {}).get("pullRequest", {})
            threads_obj = pr.get("reviewThreads", {})
            threads = threads_obj.get("nodes", [])
            page_info = threads_obj.get("pageInfo", {})

            for thread in threads:
                is_resolved = thread.get("isResolved", False)
                for comment in thread.get("comments", {}).get("nodes", []):
                    db_id = comment.get("databaseId")
                    if db_id:
                        resolved_map[db_id] = is_resolved

            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

    except (json.JSONDecodeError, KeyError, subprocess.CalledProcessError):
        pass

    return resolved_map


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
          title
          url
          headRefName
          mergedAt
          commits(last: 1) {
            nodes {
              commit {
                statusCheckRollup {
                  state
                  contexts(first: 100) {
                    pageInfo { hasNextPage }
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
            pageInfo { hasNextPage }
            nodes {
              isResolved
              comments(first: 100) {
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
    import logging  # noqa: PLC0415

    _log = logging.getLogger(__name__)

    # Parse CI status
    ci_state = "PENDING"
    check_details: list[dict[str, Any]] = []

    commits = pr_data.get("commits", {}).get("nodes", [])
    if commits:
        commit = commits[0].get("commit", {})
        rollup = commit.get("statusCheckRollup")
        if rollup:
            ci_state = rollup.get("state", "PENDING")
            contexts_obj = rollup.get("contexts", {})
            if contexts_obj.get("pageInfo", {}).get("hasNextPage"):
                _log.warning(
                    "PR %d has >100 CI check contexts; some checks may not be reflected",
                    pr_number,
                )
            context_nodes = contexts_obj.get("nodes", [])
            check_details = _parse_check_contexts(context_nodes)

    # Count review threads
    threads_obj = pr_data.get("reviewThreads", {})
    threads_has_next = threads_obj.get("pageInfo", {}).get("hasNextPage", False)
    threads = threads_obj.get("nodes", [])
    total_threads = len(threads)
    unresolved = sum(1 for thread in threads if not thread["isResolved"])
    resolved = total_threads - unresolved

    # Refuse to report "0 unresolved" when there are pages we haven't fetched —
    # there may be unresolved threads beyond the first 100.
    if threads_has_next and unresolved == 0:
        _log.warning(
            "PR %d has >100 review threads; unresolved count is a lower bound",
            pr_number,
        )
        unresolved = 1  # Cannot confirm zero with incomplete data

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
    title = pr_data.get("title") or ""
    url = pr_data.get("url") or ""
    head_branch = pr_data.get("headRefName") or ""
    merged_at = pr_data.get("mergedAt")

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
        title=title,
        url=url,
        head_branch=head_branch,
        merged_at=merged_at,
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

        path = comment.get("path") or "PR"  # key present-but-None on non-inline comments
        line = comment.get("line") or comment.get("original_line") or "N/A"
        body = comment.get("body", "")

        formatted.append(f"**{author}{bot_marker}** on {path}:{line}\n{body}\n")

    return "\n---\n\n".join(formatted)


__all__ = [
    "_get_comment_resolved_map",
    "_build_pr_status_query",
    "_parse_pr_status_response",
    "_parse_check_contexts",
    "_format_pr_comments",
    "_format_pr_comments_from_rest",
]
