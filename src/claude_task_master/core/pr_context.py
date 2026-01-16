"""PR Context Manager - Handle PR comments, CI logs, and resolution posting."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from . import console

if TYPE_CHECKING:
    from ..github.client import GitHubClient
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

    def save_ci_failures(self, pr_number: int | None) -> None:
        """Save CI failure logs to files for Claude to read.

        Args:
            pr_number: The PR number.
        """
        if pr_number is None:
            return

        try:
            failed_logs = self.github_client.get_failed_run_logs(max_lines=50)
        except Exception:
            failed_logs = "Could not retrieve CI logs"

        try:
            pr_status = self.github_client.get_pr_status(pr_number)
            for check in pr_status.check_details:
                conclusion = (check.get("conclusion") or "").lower()
                if conclusion in ("failure", "error"):
                    self.state_manager.save_ci_failure(
                        pr_number,
                        check.get("name", "unknown"),
                        failed_logs,
                    )
        except Exception as e:
            console.warning(f"Could not save CI failures: {e}")

    def save_pr_comments(self, pr_number: int | None) -> None:
        """Fetch and save PR comments to files for Claude to read.

        Args:
            pr_number: The PR number.
        """
        if pr_number is None:
            return

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

            # Convert to list of comment dicts - ONLY unresolved, actionable threads
            comments = []
            for thread in threads:
                if thread["isResolved"]:
                    continue  # Skip resolved threads
                thread_id = thread.get("id")
                for comment in thread["comments"]["nodes"]:
                    body = comment["body"]
                    author = comment["author"]["login"]

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

        except Exception as e:
            console.warning(f"Could not save PR comments: {e}")

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

            console.info(f"Posting replies to {len(resolutions)} comments...")

            for resolution in resolutions:
                thread_id = resolution.get("thread_id")
                action = resolution.get("action", "fixed")
                message = resolution.get("message", "Addressed")

                if not thread_id:
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

                    # Resolve thread if action is "fixed"
                    if action == "fixed":
                        try:
                            self.resolve_thread(thread_id)
                            console.detail(f"  Resolved thread {thread_id[:20]}...")
                        except Exception as resolve_err:
                            console.warning(f"  Failed to resolve thread: {resolve_err}")
                except Exception as e:
                    console.warning(f"  Failed to post reply: {e}")

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
