"""PR Context Manager - Handle PR comments, CI logs, and resolution posting."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

from ..github.ci_logs import CILogDownloader  # noqa: F401 — re-exported for backwards compat
from . import console
from .pr_context_ci import _PRContextCIMixin
from .pr_context_resolve import _PRContextResolveMixin
from .pr_context_types import (
    MUTATION_BATCH_SIZE,  # noqa: F401
    _chunks,  # noqa: F401
    _conversation_thread_key,
    _ThreadState,  # noqa: F401
)

if TYPE_CHECKING:
    from ..github import GitHubClient
    from .state import StateManager


class PRContextManager(_PRContextCIMixin, _PRContextResolveMixin):
    """Manages PR context data: comments, CI logs, and resolution posting."""

    def __init__(
        self,
        state_manager: StateManager,
        github_client: GitHubClient,
    ):
        """Initialize PR context manager.

        Args:
            state_manager: State manager for file persistence.
            github_client: GitHub client for API calls.
        """
        self.state_manager = state_manager
        self.github_client = github_client

    def save_pr_comments(self, pr_number: int | None, *, _also_save_ci: bool = True) -> int:
        """Fetch and save PR comments to files for Claude to read.

        Uses REST API to get all comments (like tstc), then enriches with
        resolved status from GraphQL.

        Args:
            pr_number: The PR number.
            _also_save_ci: Internal flag to also save CI failures (prevents recursion).

        Returns:
            Number of actionable comment files saved.
        """
        if pr_number is None:
            return 0

        # Also save CI failures when saving comments (for complete context)
        if _also_save_ci:
            self.save_ci_failures(pr_number, _also_save_comments=False)

        try:
            # Get repository info
            repo_info = self.github_client._get_repo_info()
            pr_dir = self.state_manager.get_pr_dir(pr_number)

            # Use REST API to get ALL PR review comments (paginated).
            # --paginate concatenates pages; --jq '.[]' emits one object per line (NDJSON).
            result = self.github_client._run_gh_command(
                [
                    "gh",
                    "api",
                    "--paginate",
                    "--jq",
                    ".[]",
                    f"repos/{repo_info}/pulls/{pr_number}/comments",
                ],
                timeout=60,
            )
            all_comments = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

            # Get resolved status from GraphQL (paginated)
            resolved_map = self._get_resolved_status_map(repo_info, pr_number)

            # Get already-addressed comment IDs to skip them
            addressed_threads = self.state_manager.get_addressed_threads(pr_number)

            # Convert to list of comment dicts - filter unresolved, actionable
            comments = []
            for comment in all_comments:
                comment_id = comment.get("id")
                # Check if this comment's thread is resolved
                is_resolved = resolved_map.get(comment_id, False)
                if is_resolved:
                    continue  # Skip resolved comments

                # Get thread ID for this comment (for tracking addressed threads)
                thread_id = self._get_thread_id_for_comment(comment_id, resolved_map)

                # Skip threads we've already addressed (replied to)
                if thread_id and thread_id in addressed_threads:
                    continue

                # `or`-guards: "body" and "user" can be present-but-None
                # (ghost/deleted accounts send "user": null).
                body = comment.get("body") or ""
                author = (comment.get("user") or {}).get("login") or "unknown"

                # Skip non-actionable bot comments
                if self._is_non_actionable_comment(author, body):
                    continue

                comments.append(
                    {
                        "thread_id": thread_id or f"comment_{comment_id}",
                        "comment_id": str(comment_id),
                        "author": author,
                        "body": body,
                        "path": comment.get("path"),
                        "line": comment.get("line") or comment.get("original_line"),
                        "is_resolved": False,
                    }
                )

            # Also surface PR *conversation* (issue-level) comments — human
            # "please also change X" feedback that lives on the issues endpoint
            # and would otherwise be invisible to the pipeline.
            comments.extend(
                self._fetch_conversation_comments(repo_info, pr_number, addressed_threads)
            )

            # Clear old comments only after a successful fetch — preserves
            # existing data if any API call above fails.
            comments_dir = pr_dir / "comments"
            if comments_dir.exists():
                shutil.rmtree(comments_dir)
            summary_file = pr_dir / "comments_summary.txt"
            if summary_file.exists():
                summary_file.unlink()

            # Save to files
            self.state_manager.save_pr_comments(pr_number, comments)
            return len(comments)

        except Exception as e:
            console.warning(f"Could not save PR comments: {e}")
            return 0

    def _fetch_conversation_comments(
        self, repo_info: str, pr_number: int, addressed_threads: set[str]
    ) -> list[dict[str, object]]:
        """Fetch PR conversation (issue-level) comments as actionable items.

        PR conversation comments live on the ``/issues/{n}/comments`` endpoint,
        separate from inline review comments. They are not part of resolvable
        review threads, so each is tracked by a synthetic
        ``issue_comment_<id>`` key in the addressed-threads set to avoid
        re-surfacing feedback the agent has already handled.

        Failures are swallowed (returning an empty list) so that missing
        conversation comments never abort the primary review-comment save.

        Args:
            repo_info: Repository in ``owner/name`` form.
            pr_number: The PR number.
            addressed_threads: Set of already-addressed thread/comment keys.

        Returns:
            List of actionable conversation-comment dicts.
        """
        try:
            result = self.github_client._run_gh_command(
                [
                    "gh",
                    "api",
                    "--paginate",
                    "--jq",
                    ".[]",
                    f"repos/{repo_info}/issues/{pr_number}/comments",
                ],
                timeout=60,
            )
        except Exception as e:
            console.warning(f"Could not fetch conversation comments: {e}")
            return []

        conversation: list[dict[str, object]] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                comment = json.loads(line)
            except json.JSONDecodeError:
                continue

            comment_id = comment.get("id")
            if comment_id is None:
                continue

            thread_key = _conversation_thread_key(comment_id)
            if thread_key in addressed_threads:
                continue  # Already handled in a prior cycle.

            # `or`-guards: ghost/deleted accounts send "user": null.
            body = comment.get("body") or ""
            author = (comment.get("user") or {}).get("login") or "unknown"
            if self._is_non_actionable_comment(author, body):
                continue

            conversation.append(
                {
                    "thread_id": thread_key,
                    "comment_id": str(comment_id),
                    "author": author,
                    "body": body,
                    "path": None,
                    "line": None,
                    "is_resolved": False,
                }
            )

        return conversation

    def _get_resolved_status_map(self, repo_info: str, pr_number: int) -> dict[int, bool]:
        """Get resolved status for all comments from GraphQL.

        Paginates through all review threads to handle PRs with > 100 threads.

        Returns:
            Map of comment_id -> is_resolved.
            Also populates ``self._thread_info`` for thread-ID lookups.
        """
        owner, repo = repo_info.split("/")

        # Store thread info: comment_id -> (is_resolved, thread_id)
        self._thread_info: dict[int, tuple[bool, str]] = {}

        # $cursor is nullable; omit it on the first page (gh cli sends null).
        query = """
        query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pr) {
              reviewThreads(first: 100, after: $cursor) {
                pageInfo { hasNextPage endCursor }
                nodes {
                  id
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

                result = self.github_client._run_gh_command(cmd, timeout=30)
                data = json.loads(result.stdout)

                pr = data["data"]["repository"]["pullRequest"]
                threads_data = pr.get("reviewThreads", {})
                threads = threads_data.get("nodes", [])
                page_info = threads_data.get("pageInfo", {})

                for thread in threads:
                    thread_id = thread.get("id", "")
                    is_resolved = thread.get("isResolved", False)
                    for comment in thread.get("comments", {}).get("nodes", []):
                        db_id = comment.get("databaseId")
                        if db_id:
                            resolved_map[db_id] = is_resolved
                            self._thread_info[db_id] = (is_resolved, thread_id)

                if not page_info.get("hasNextPage"):
                    break
                cursor = page_info.get("endCursor")

        except Exception:
            pass

        return resolved_map

    def _get_thread_id_for_comment(
        self, comment_id: int, resolved_map: dict[int, bool]
    ) -> str | None:
        """Get the thread ID for a comment."""
        info = getattr(self, "_thread_info", {}).get(comment_id)
        return info[1] if info else None

    def _is_non_actionable_comment(self, author: str, body: str) -> bool:
        """Check if a comment is non-actionable (bot status, summary, etc).

        Args:
            author: Comment author login.
            body: Comment body text.

        Returns:
            True if comment should be skipped.
        """
        # Skip very short comments (likely not actionable)
        if len(body.strip()) < 20:
            return True

        # Known bot authors with status/summary comments
        bot_authors = ["coderabbitai", "github-actions", "dependabot"]

        # Skip if from a bot and is a pure status/summary comment (not a code review)
        if author.lower() in bot_authors:
            body_lower = body.lower()
            # These indicate status updates, not code reviews
            status_only_indicators = [
                "currently processing",
                "review in progress",
                "is analyzing",
            ]
            for indicator in status_only_indicators:
                if indicator in body_lower and len(body) < 200:
                    return True

            # Skip pure summary comments (no code suggestions)
            if "walkthrough" in body_lower and "proposed fix" not in body_lower:
                return True

        return False

    def has_pr_comments(self, pr_number: int | None) -> bool:
        """Check if there are unresolved PR comments saved.

        Args:
            pr_number: The PR number.

        Returns:
            True if there are saved comment files.
        """
        if pr_number is None:
            return False

        try:
            pr_dir = self.state_manager.get_pr_dir(pr_number)
            comments_dir = pr_dir / "comments"
            if not comments_dir.exists():
                return False
            comment_files = list(comments_dir.glob("*.txt"))
            return len(comment_files) > 0
        except Exception:
            return False

    def has_ci_failures(self, pr_number: int | None) -> bool:
        """Check if there are CI failure logs saved.

        Args:
            pr_number: The PR number.

        Returns:
            True if there are saved CI failure files.
        """
        if pr_number is None:
            return False

        try:
            pr_dir = self.state_manager.get_pr_dir(pr_number)
            ci_dir = pr_dir / "ci"
            if not ci_dir.exists():
                return False
            # Check for log files in job subdirectories (new chunked format)
            ci_files = list(ci_dir.rglob("*.log"))
            return len(ci_files) > 0
        except Exception:
            return False

    def get_combined_feedback(self, pr_number: int | None) -> tuple[bool, bool, str]:
        """Get combined feedback context for CI failures and PR comments.

        This method checks both CI failures and PR comments, returning information
        about what types of feedback are present and paths to find them.

        Args:
            pr_number: The PR number.

        Returns:
            Tuple of (has_ci_failures, has_comments, pr_dir_path).
        """
        if pr_number is None:
            return (False, False, "")

        pr_dir = self.state_manager.get_pr_dir(pr_number)
        pr_dir_path = str(pr_dir)

        has_ci = self.has_ci_failures(pr_number)
        has_comments = self.has_pr_comments(pr_number)

        return (has_ci, has_comments, pr_dir_path)
