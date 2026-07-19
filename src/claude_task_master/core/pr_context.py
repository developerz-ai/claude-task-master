"""PR Context Manager - Handle PR comments, CI logs, and resolution posting."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

from . import console

if TYPE_CHECKING:
    from ..github import GitHubClient
    from .state import StateManager


from ..github.ci_logs import CILogDownloader


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

        Uses CILogDownloader to fetch complete logs from only failed jobs,
        split into manageable chunks (500 lines per file).

        Args:
            pr_number: The PR number.
            _also_save_comments: Internal flag to also save comments (prevents recursion).
        """
        if pr_number is None:
            return

        # Initialize paths outside try blocks to avoid NameError
        pr_dir = self.state_manager.get_pr_dir(pr_number)
        ci_dir = pr_dir / "ci"

        try:
            # Get the latest workflow run for this PR's branch
            pr_status = self.github_client.get_pr_status(pr_number)

            # Check if any CI checks failed
            _failing_conclusions = {"FAILURE", "ERROR", "TIMED_OUT"}
            has_failures = any(
                (check.get("conclusion") or "").upper() in _failing_conclusions
                for check in pr_status.check_details
            )

            if not has_failures:
                # CI is now passing — clear any stale failure logs
                if ci_dir.exists():
                    shutil.rmtree(ci_dir)
                return  # No failures to download

            # Extract run IDs from *failing* checks only (distinct set).
            # Avoids picking up a passing check's run ID when a different check fails.
            failing_checks = [
                check
                for check in pr_status.check_details
                if (check.get("conclusion") or "").upper() in _failing_conclusions
            ]
            run_ids: set[int] = set()
            for check in failing_checks:
                details_url = check.get("url", "")
                # URL format: .../actions/runs/123456/job/789
                if "/runs/" in details_url:
                    try:
                        run_ids.add(int(details_url.split("/runs/")[1].split("/")[0]))
                    except (IndexError, ValueError):
                        continue

            if not run_ids:
                # Log available check URLs for debugging
                check_urls = [
                    f"{c.get('name', 'unknown')}: {c.get('url', 'N/A')}" for c in failing_checks[:3]
                ]
                console.warning(
                    f"Could not extract run ID from failing checks. "
                    f"Sample failing checks: {', '.join(check_urls)}"
                )
                return

            run_id = max(run_ids)  # Use the most-recent run among failing ones
            console.detail(
                f"Extracted run ID {run_id} from failing checks (candidates: {sorted(run_ids)})"
            )

            # Get repository info for CILogDownloader
            console.detail("Getting repository info via gh CLI...")
            repo = self.github_client._get_repo_info()
            console.detail(f"Repository: {repo}")

            downloader = CILogDownloader(repo=repo, timeout=60)

            # Download failed job logs using CILogDownloader
            console.detail(f"Downloading CI logs for run {run_id} from {repo}...")

            # Clear old CI logs only after we have confirmed run_id and repo —
            # preserves existing data if the status/repo calls fail above.
            if ci_dir.exists():
                shutil.rmtree(ci_dir)
            ci_dir.mkdir(parents=True, exist_ok=True)

            # Download and save logs chunked (20KB per file ~5K tokens)
            logs = downloader.download_failed_run_logs(
                run_id=run_id,
                output_dir=ci_dir,
                max_chars_per_file=20_000,
            )

            if logs:
                console.detail(f"Downloaded CI logs to {ci_dir} ({len(logs)} jobs)")
            else:
                # Checks failed but no GitHub Actions jobs failed (e.g., external checks)
                console.warning(
                    f"CI checks failed but no GitHub Actions job logs available for run {run_id}. "
                    f"Failures may be from external checks (CodeRabbit, etc.)"
                )

        except Exception as e:
            import traceback

            console.warning(f"Could not save CI failures: {e}")
            console.detail(f"Full error: {traceback.format_exc()}")

        # Also save comments when saving CI failures (for complete context)
        # Do this AFTER saving CI failures to ensure CI files exist first
        if _also_save_comments:
            self.save_pr_comments(pr_number, _also_save_ci=False)

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

                body = comment.get("body", "")
                author = comment.get("user", {}).get("login", "unknown")

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

            # Get threads we've already replied to (prevents duplicate replies on crash/retry)
            already_addressed = self.state_manager.get_addressed_threads(pr_number)

            console.info(f"Posting replies to {len(resolutions)} comments...")

            # Track successfully addressed thread IDs
            addressed_thread_ids: list[str] = []

            for resolution in resolutions:
                thread_id = resolution.get("thread_id")
                action = resolution.get("action", "fixed")
                message = resolution.get("message", "Addressed")

                if not thread_id:
                    continue

                # Skip threads we've already replied to
                if thread_id in already_addressed:
                    # Still resolve if not yet resolved on GitHub (prevents infinite loop)
                    if thread_id not in already_resolved and action in ("fixed", "explained"):
                        try:
                            self.resolve_thread(thread_id)
                            console.detail(
                                f"  Resolved previously-replied thread {thread_id[:20]}..."
                            )
                        except Exception as resolve_err:
                            console.warning(f"  Failed to resolve thread: {resolve_err}")
                    else:
                        console.detail(f"  Thread {thread_id[:20]}... already replied, skipping")
                    continue

                already_resolved_on_github = thread_id in already_resolved

                # Build reply message - keep it short
                action_prefix = {
                    "fixed": "Fixed:",
                    "explained": "Note:",
                    "skipped": "Skipped:",
                }.get(action, "Fixed:")

                reply_body = f"{action_prefix} {message}"

                try:
                    self._post_thread_reply(thread_id, reply_body)
                    console.detail(f"  Posted reply to thread {thread_id[:20]}...")

                    # Mark this thread as addressed so we don't re-download it
                    addressed_thread_ids.append(thread_id)

                    # Resolve thread if action is "fixed" or "explained" and not already resolved
                    if action in ("fixed", "explained") and not already_resolved_on_github:
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

        self.github_client._run_gh_command(
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
            timeout=30,
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

        self.github_client._run_gh_command(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={mutation}",
                "-F",
                f"threadId={thread_id}",
            ],
            timeout=30,
        )

    def resolve_addressed_threads(self, pr_number: int | None) -> int:
        """Resolve threads that were already addressed but not yet resolved on GitHub.

        This prevents infinite loops where the system keeps re-running the agent
        for threads that were replied to but failed to resolve.

        Args:
            pr_number: The PR number.

        Returns:
            Number of threads resolved.
        """
        if pr_number is None:
            return 0

        try:
            already_resolved = self._get_resolved_thread_ids(pr_number)
            already_addressed = self.state_manager.get_addressed_threads(pr_number)

            # Find threads that were addressed (replied to) but not resolved
            unresolved_addressed = already_addressed - already_resolved
            if not unresolved_addressed:
                return 0

            resolved_count = 0
            for thread_id in unresolved_addressed:
                try:
                    self.resolve_thread(thread_id)
                    resolved_count += 1
                    console.detail(f"  Resolved addressed thread {thread_id[:20]}...")
                except Exception as e:
                    console.warning(f"  Failed to resolve thread {thread_id[:20]}...: {e}")

            if resolved_count:
                console.info(f"Resolved {resolved_count} previously-addressed threads")
            return resolved_count

        except Exception as e:
            console.warning(f"Could not resolve addressed threads: {e}")
            return 0

    def _get_resolved_thread_ids(self, pr_number: int) -> set[str]:
        """Get IDs of threads that are already resolved on GitHub.

        Paginates through all review threads to handle PRs with > 100 threads.

        Args:
            pr_number: The PR number.

        Returns:
            Set of thread IDs that are already resolved.
        """
        try:
            repo_info = self.github_client._get_repo_info()
            owner, repo = repo_info.split("/")

            # $cursor is nullable; omit it on the first page.
            query = """
            query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
              repository(owner: $owner, name: $repo) {
                pullRequest(number: $pr) {
                  reviewThreads(first: 100, after: $cursor) {
                    pageInfo { hasNextPage endCursor }
                    nodes {
                      id
                      isResolved
                    }
                  }
                }
              }
            }
            """

            resolved_ids: set[str] = set()
            cursor: str | None = None

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

                for t in threads:
                    if t.get("isResolved"):
                        resolved_ids.add(t["id"])

                if not page_info.get("hasNextPage"):
                    break
                cursor = page_info.get("endCursor")

            return resolved_ids

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
