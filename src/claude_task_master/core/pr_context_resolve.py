"""Review-thread resolution and comment-reply methods for PRContextManager.

Provides :class:`_PRContextResolveMixin` with:

- :meth:`post_comment_replies`
- :meth:`_post_thread_reply`
- :meth:`resolve_thread`
- :meth:`resolve_addressed_threads`
- :meth:`_get_resolved_thread_ids`
- :meth:`_get_thread_states`
- :meth:`_resolve_threads_batched`
- :meth:`_run_resolve_batch`
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .pr_context_types import (
    _CONVERSATION_THREAD_PREFIX,
    MUTATION_BATCH_SIZE,
    _chunks,
    _ThreadState,
)

if TYPE_CHECKING:
    from ..github import GitHubClient
    from .state import StateManager


class _PRContextResolveMixin:
    """Mixin providing review-thread resolution helpers to PRContextManager.

    Console access is deferred at call time so tests can patch
    ``claude_task_master.core.pr_context.console``.
    """

    state_manager: StateManager
    github_client: GitHubClient

    # ------------------------------------------------------------------
    # Comment replies
    # ------------------------------------------------------------------

    def post_comment_replies(self, pr_number: int | None) -> None:
        """Post replies to comments based on resolve-comments.json.

        Args:
            pr_number: The PR number.
        """
        if pr_number is None:
            return

        # Deferred import so tests can patch pr_context.console
        import claude_task_master.core.pr_context as _pr  # noqa: PLC0415

        _console = _pr.console

        try:
            pr_dir = self.state_manager.get_pr_dir(pr_number)
            resolve_file = pr_dir / "resolve-comments.json"

            if not resolve_file.exists():
                _console.detail("No resolve-comments.json found, skipping reply posting")
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

            _console.info(f"Posting replies to {len(resolutions)} comments...")

            # Track successfully addressed thread IDs and threads to resolve.
            addressed_thread_ids: list[str] = []
            threads_to_resolve: list[str] = []

            for resolution in resolutions:
                thread_id = resolution.get("thread_id")
                action = resolution.get("action", "fixed")
                message = resolution.get("message", "Addressed")

                if not thread_id:
                    continue

                # Conversation (issue-level) comments aren't resolvable review
                # threads: acknowledge by marking addressed and skip the thread
                # reply/resolve GraphQL API (which would fail on a synthetic ID).
                if thread_id.startswith(_CONVERSATION_THREAD_PREFIX):
                    if thread_id not in already_addressed:
                        addressed_thread_ids.append(thread_id)
                    continue

                # Already replied to — skip. Resolving addressed-but-unresolved
                # threads is handled by resolve_addressed_threads, which only
                # resolves threads whose last comment is ours (never a thread a
                # human re-opened).
                if thread_id in already_addressed:
                    _console.detail(f"  Thread {thread_id[:20]}... already replied, skipping")
                    continue

                # Build reply message - keep it short
                action_prefix = {
                    "fixed": "Fixed:",
                    "explained": "Note:",
                    "skipped": "Skipped:",
                }.get(action, "Fixed:")

                reply_body = f"{action_prefix} {message}"

                try:
                    self._post_thread_reply(thread_id, reply_body)
                    _console.detail(f"  Posted reply to thread {thread_id[:20]}...")

                    # Mark this thread as addressed so we don't re-download it.
                    addressed_thread_ids.append(thread_id)

                    # Queue for resolution if fixed/explained and not already
                    # resolved on GitHub; the queue is resolved in aliased
                    # batches below instead of one request per thread.
                    if action in ("fixed", "explained") and thread_id not in already_resolved:
                        threads_to_resolve.append(thread_id)
                except Exception as e:
                    _console.warning(f"  Failed to post reply: {e}")

            # Resolve all queued threads in a few aliased GraphQL requests.
            if threads_to_resolve:
                self._resolve_threads_batched(threads_to_resolve)

            # Persist addressed thread IDs to avoid re-downloading them
            if addressed_thread_ids:
                self.state_manager.mark_threads_addressed(pr_number, addressed_thread_ids)
                _console.detail(f"Marked {len(addressed_thread_ids)} threads as addressed")

            # Delete the resolve-comments.json after processing to prevent re-processing
            # New comments from CodeRabbit or reviewers will be fetched fresh next cycle
            try:
                resolve_file.unlink()
                _console.detail("Deleted resolve-comments.json after processing")
            except Exception as del_err:
                _console.warning(f"Could not delete resolve-comments.json: {del_err}")

        except Exception as e:
            _console.warning(f"Could not post comment replies: {e}")

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

    # ------------------------------------------------------------------
    # Thread resolution
    # ------------------------------------------------------------------

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
        """Resolve addressed-but-unresolved threads whose last comment is ours.

        Prevents infinite re-processing of threads we replied to but failed to
        resolve. Threads where a human commented *after* our reply are left open
        and pruned from the addressed set, so their new feedback re-surfaces to
        the agent on the next fetch instead of being force-resolved away.

        Args:
            pr_number: The PR number.

        Returns:
            Number of threads resolved.
        """
        if pr_number is None:
            return 0

        # Deferred import so tests can patch pr_context.console
        import claude_task_master.core.pr_context as _pr  # noqa: PLC0415

        _console = _pr.console

        try:
            viewer_login, states = self._get_thread_states(pr_number)
            already_addressed = self.state_manager.get_addressed_threads(pr_number)

            to_resolve: list[str] = []
            to_prune: list[str] = []
            for thread_id in already_addressed:
                if thread_id.startswith(_CONVERSATION_THREAD_PREFIX):
                    continue  # Conversation comments aren't review threads.
                state = states.get(thread_id)
                if state is None or state.is_resolved:
                    continue  # Gone or already resolved — nothing to do.
                # Only auto-resolve when our own reply is the last comment. If a
                # human replied after us they re-engaged the thread: leave it
                # open and prune it so save_pr_comments re-surfaces the feedback.
                if viewer_login and state.last_comment_author == viewer_login:
                    to_resolve.append(thread_id)
                else:
                    to_prune.append(thread_id)

            if to_prune:
                self.state_manager.unmark_threads_addressed(pr_number, to_prune)
                _console.detail(f"Pruned {len(to_prune)} re-opened thread(s) from addressed set")

            resolved_count = self._resolve_threads_batched(to_resolve)
            if resolved_count:
                _console.info(f"Resolved {resolved_count} previously-addressed threads")
            return resolved_count

        except Exception as e:
            _console.warning(f"Could not resolve addressed threads: {e}")
            return 0

    def _get_resolved_thread_ids(self, pr_number: int) -> set[str]:
        """Get IDs of threads that are already resolved on GitHub.

        Args:
            pr_number: The PR number.

        Returns:
            Set of thread IDs that are already resolved.
        """
        _, states = self._get_thread_states(pr_number)
        return {thread_id for thread_id, state in states.items() if state.is_resolved}

    def _get_thread_states(self, pr_number: int) -> tuple[str | None, dict[str, _ThreadState]]:
        """Fetch each review thread's resolution status and last-comment author.

        Also returns the authenticated viewer's login so callers can tell
        whether the most recent comment on a thread is the bot's own reply.
        Paginates through all review threads to handle PRs with > 100 threads.

        Args:
            pr_number: The PR number.

        Returns:
            Tuple of ``(viewer_login, {thread_id: _ThreadState})``. viewer_login
            is None when it cannot be determined.
        """
        # Deferred import so tests can patch pr_context.console
        import claude_task_master.core.pr_context as _pr  # noqa: PLC0415

        _console = _pr.console

        viewer_login: str | None = None
        states: dict[str, _ThreadState] = {}

        try:
            repo_info = self.github_client._get_repo_info()
            owner, repo = repo_info.split("/")

            # $cursor is nullable; omit it on the first page.
            query = """
            query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
              viewer { login }
              repository(owner: $owner, name: $repo) {
                pullRequest(number: $pr) {
                  reviewThreads(first: 100, after: $cursor) {
                    pageInfo { hasNextPage endCursor }
                    nodes {
                      id
                      isResolved
                      comments(last: 1) { nodes { author { login } } }
                    }
                  }
                }
              }
            }
            """

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

                payload = data.get("data") or {}
                viewer_login = (payload.get("viewer") or {}).get("login") or viewer_login
                pr = payload["repository"]["pullRequest"]
                threads_data = pr.get("reviewThreads", {})
                page_info = threads_data.get("pageInfo", {})

                for thread in threads_data.get("nodes", []):
                    thread_id = thread.get("id")
                    if not thread_id:
                        continue
                    last_author: str | None = None
                    comment_nodes = thread.get("comments", {}).get("nodes", [])
                    if comment_nodes:
                        last_author = (comment_nodes[-1].get("author") or {}).get("login")
                    states[thread_id] = _ThreadState(
                        is_resolved=bool(thread.get("isResolved")),
                        last_comment_author=last_author,
                    )

                if not page_info.get("hasNextPage"):
                    break
                cursor = page_info.get("endCursor")

        except Exception as e:
            _console.warning(f"Could not fetch thread states: {e}")

        return viewer_login, states

    def _resolve_threads_batched(self, thread_ids: list[str]) -> int:
        """Resolve multiple review threads using aliased GraphQL mutations.

        Threads are resolved in batches of ``MUTATION_BATCH_SIZE`` within a
        single request each. If a batch request fails (e.g. one invalid ID),
        it falls back to resolving that batch's threads individually so one bad
        thread doesn't block the rest. ``resolveReviewThread`` is idempotent,
        so retrying is safe.

        Args:
            thread_ids: Review-thread IDs to resolve.

        Returns:
            Number of threads resolved.
        """
        # Deferred import so tests can patch pr_context.console
        import claude_task_master.core.pr_context as _pr  # noqa: PLC0415

        _console = _pr.console

        resolved = 0
        for batch in _chunks(thread_ids, MUTATION_BATCH_SIZE):
            try:
                self._run_resolve_batch(batch)
                resolved += len(batch)
                for thread_id in batch:
                    _console.detail(f"  Resolved addressed thread {thread_id[:20]}...")
            except Exception:
                # Batch failed — resolve individually so one bad ID isn't fatal.
                for thread_id in batch:
                    try:
                        self.resolve_thread(thread_id)
                        resolved += 1
                        _console.detail(f"  Resolved addressed thread {thread_id[:20]}...")
                    except Exception as e:
                        _console.warning(f"  Failed to resolve thread {thread_id[:20]}...: {e}")
        return resolved

    def _run_resolve_batch(self, thread_ids: list[str]) -> None:
        """Resolve a batch of threads in one aliased GraphQL mutation request.

        Args:
            thread_ids: Review-thread IDs to resolve in a single request.
        """
        if not thread_ids:
            return

        var_decls = ", ".join(f"$t{i}: ID!" for i in range(len(thread_ids)))
        fields = "\n  ".join(
            f"r{i}: resolveReviewThread(input: {{threadId: $t{i}}}) {{ thread {{ isResolved }} }}"
            for i in range(len(thread_ids))
        )
        mutation = f"mutation({var_decls}) {{\n  {fields}\n}}"

        cmd = ["gh", "api", "graphql", "-f", f"query={mutation}"]
        for i, thread_id in enumerate(thread_ids):
            cmd.extend(["-f", f"t{i}={thread_id}"])

        self.github_client._run_gh_command(cmd, timeout=30)


__all__ = ["_PRContextResolveMixin"]
