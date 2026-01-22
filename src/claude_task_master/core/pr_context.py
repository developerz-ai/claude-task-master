"""PR Context Manager - Handle PR comments, CI logs, and resolution posting."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING

from . import console

if TYPE_CHECKING:
    from ..github import GitHubClient
    from .state import StateManager


class PRContextManager:
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

    def save_ci_failures(self, pr_number: int | None, *, _also_save_comments: bool = True) -> None:
        """Save CI failure logs to files for Claude to read.

        Args:
            pr_number: The PR number.
            _also_save_comments: Internal flag to also save comments (prevents recursion).
        """
        if pr_number is None:
            return

        # Also save comments when saving CI failures (for complete context)
        if _also_save_comments:
            self.save_pr_comments(pr_number, _also_save_ci=False)

        # Clear old CI logs to avoid stale data
        try:
            pr_dir = self.state_manager.get_pr_dir(pr_number)
            ci_dir = pr_dir / "ci"
            if ci_dir.exists():
                shutil.rmtree(ci_dir)
        except Exception:
            pass  # Best effort cleanup

        try:
            failed_logs = self.github_client.get_failed_run_logs(max_lines=50)
        except Exception:
            failed_logs = "Could not retrieve CI logs"

        try:
            pr_status = self.github_client.get_pr_status(pr_number)
            for check in pr_status.check_details:
                conclusion = (check.get("conclusion") or "").upper()
                if conclusion in ("FAILURE", "ERROR"):
                    self.state_manager.save_ci_failure(
                        pr_number,
                        check.get("name", "unknown"),
                        failed_logs,
                    )
        except Exception as e:
            console.warning(f"Could not save CI failures: {e}")

    def save_pr_comments(self, pr_number: int | None, *, _also_save_ci: bool = True) -> int:
        """Fetch and save PR comments to files for Claude to read.

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

        # Clear old comments to avoid stale data
        try:
            pr_dir = self.state_manager.get_pr_dir(pr_number)
            comments_dir = pr_dir / "comments"
            if comments_dir.exists():
                shutil.rmtree(comments_dir)
            # Also remove old summary file
            summary_file = pr_dir / "comments_summary.txt"
            if summary_file.exists():
                summary_file.unlink()
        except Exception:
            pass  # Best effort cleanup

        try:
            # Get repository info
            result = subprocess.run(
                ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                check=True,
                capture_output=True,
                text=True,
            )
            repo_info = result.stdout.strip()
            owner, repo = repo_info.split("/")

            # GraphQL query to get structured comments with thread IDs
            query = """
            query($owner: String!, $repo: String!, $pr: Int!) {
              repository(owner: $owner, name: $repo) {
                pullRequest(number: $pr) {
                  reviewThreads(first: 100) {
                    nodes {
                      id
                      isResolved
                      comments(first: 10) {
                        nodes {
                          id
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

            result = subprocess.run(
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
                check=True,
                capture_output=True,
                text=True,
            )

            data = json.loads(result.stdout)
            threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]

            # Get already-addressed thread IDs to skip them
            addressed_threads = self.state_manager.get_addressed_threads(pr_number)

            # Convert to list of comment dicts - ONLY unresolved, actionable threads
            comments = []
            for thread in threads:
                if thread["isResolved"]:
                    continue  # Skip resolved threads
                thread_id = thread.get("id")

                # Skip threads we've already addressed (replied to)
                if thread_id in addressed_threads:
                    continue

                for comment in thread["comments"]["nodes"]:
                    body = comment["body"]
                    author = comment["author"]["login"] if comment.get("author") else "unknown"

                    # Skip non-actionable bot comments
                    if self._is_non_actionable_comment(author, body):
                        continue

                    comments.append(
                        {
                            "thread_id": thread_id,
                            "comment_id": comment.get("id"),
                            "author": author,
                            "body": body,
                            "path": comment.get("path"),
                            "line": comment.get("line"),
                            "is_resolved": False,
                        }
                    )

            # Save to files
            self.state_manager.save_pr_comments(pr_number, comments)
            return len(comments)

        except Exception as e:
            console.warning(f"Could not save PR comments: {e}")
            return 0

    def post_comment_replies(self, pr_number: int | None) -> None:
        """Post replies to comments based on resolve-comments.json.

        Args:
            pr_number: The PR number.
        """
        if pr_number is None:
            return

        try:
            pr_dir = self.state_manager.get_pr_dir(pr_number)
            resolve_file = pr_dir / "resolve-comments.json"

            if not resolve_file.exists():
                console.detail("No resolve-comments.json found, skipping reply posting")
                return

            with open(resolve_file) as f:
                data = json.load(f)

            resolutions = data.get("resolutions", [])
            if not resolutions:
                return

            # Get current thread resolution status from GitHub
            already_resolved = self._get_resolved_thread_ids(pr_number)

            console.info(f"Posting replies to {len(resolutions)} comments...")

            # Track successfully addressed thread IDs
            addressed_thread_ids: list[str] = []

            for resolution in resolutions:
                thread_id = resolution.get("thread_id")
                action = resolution.get("action", "fixed")
                message = resolution.get("message", "Addressed")

                if not thread_id:
                    continue

                # Skip threads that are already resolved on GitHub
                if thread_id in already_resolved:
                    console.detail(f"  Thread {thread_id[:20]}... already resolved, skipping")
                    addressed_thread_ids.append(thread_id)
                    continue

                # Build reply message
                action_emoji = {
                    "fixed": "✅",
                    "explained": "💬",
                    "skipped": "⏭️",
                }.get(action, "✅")

                reply_body = f"{action_emoji} **{action.capitalize()}**: {message}"

                try:
                    self._post_thread_reply(thread_id, reply_body)
                    console.detail(f"  Posted reply to thread {thread_id[:20]}...")

                    # Mark this thread as addressed so we don't re-download it
                    addressed_thread_ids.append(thread_id)

                    # Resolve thread if action is "fixed" or "explained"
                    # Both indicate the comment has been addressed (either by code change or explanation)
                    if action in ("fixed", "explained"):
                        try:
                            self.resolve_thread(thread_id)
                            console.detail(f"  Resolved thread {thread_id[:20]}...")
                        except Exception as resolve_err:
                            console.warning(f"  Failed to resolve thread: {resolve_err}")
                except Exception as e:
                    console.warning(f"  Failed to post reply: {e}")

            # Persist addressed thread IDs to avoid re-downloading them
            if addressed_thread_ids:
                self.state_manager.mark_threads_addressed(pr_number, addressed_thread_ids)
                console.detail(f"Marked {len(addressed_thread_ids)} threads as addressed")

            # Delete the resolve-comments.json after processing to prevent re-processing
            # New comments from CodeRabbit or reviewers will be fetched fresh next cycle
            try:
                resolve_file.unlink()
                console.detail("Deleted resolve-comments.json after processing")
            except Exception as del_err:
                console.warning(f"Could not delete resolve-comments.json: {del_err}")

        except Exception as e:
            console.warning(f"Could not post comment replies: {e}")

    def _post_thread_reply(self, thread_id: str, body: str) -> None:
        """Post a reply to a review thread.

        Args:
            thread_id: The GraphQL thread ID.
            body: The reply message body.
        """
        # Use GraphQL mutation to add a reply
        mutation = """
        mutation($threadId: ID!, $body: String!) {
          addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $threadId, body: $body}) {
            comment {
              id
            }
          }
        }
        """

        subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={mutation}",
                "-F",
                f"threadId={thread_id}",
                "-F",
                f"body={body}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def resolve_thread(self, thread_id: str) -> None:
        """Resolve a review thread.

        Args:
            thread_id: The GraphQL thread ID to resolve.
        """
        mutation = """
        mutation($threadId: ID!) {
          resolveReviewThread(input: {threadId: $threadId}) {
            thread {
              isResolved
            }
          }
        }
        """

        subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={mutation}",
                "-F",
                f"threadId={thread_id}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def _get_resolved_thread_ids(self, pr_number: int) -> set[str]:
        """Get IDs of threads that are already resolved on GitHub.

        Args:
            pr_number: The PR number.

        Returns:
            Set of thread IDs that are already resolved.
        """
        try:
            result = subprocess.run(
                ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                check=True,
                capture_output=True,
                text=True,
            )
            repo_info = result.stdout.strip()
            owner, repo = repo_info.split("/")

            query = """
            query($owner: String!, $repo: String!, $pr: Int!) {
              repository(owner: $owner, name: $repo) {
                pullRequest(number: $pr) {
                  reviewThreads(first: 100) {
                    nodes {
                      id
                      isResolved
                    }
                  }
                }
              }
            }
            """

            result = subprocess.run(
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
                check=True,
                capture_output=True,
                text=True,
            )

            data = json.loads(result.stdout)
            threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]

            return {t["id"] for t in threads if t["isResolved"]}

        except Exception as e:
            console.warning(f"Could not fetch resolved threads: {e}")
            return set()

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
            ci_files = list(ci_dir.glob("*.txt"))
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
