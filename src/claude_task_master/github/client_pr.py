"""GitHub PR Operations - PR creation, status, and comments.

Public API (PRStatus, PROperationsMixin) is unchanged.

Implementation split into focused sub-modules:
- :mod:`.client_pr_models` — :class:`PRStatus`, :class:`GitHubClientProtocol`
- :mod:`.client_pr_helpers` — GraphQL builders, response parsers, comment formatters
"""

from __future__ import annotations

import json
import re

from .client_pr_helpers import (  # noqa: F401 — re-exported for backward compat
    _build_pr_status_query,
    _format_pr_comments,
    _format_pr_comments_from_rest,
    _get_comment_resolved_map,
    _parse_check_contexts,
    _parse_pr_status_response,
)
from .client_pr_models import (  # noqa: F401 — re-exported for backward compat
    GitHubClientProtocol,
    PRStatus,
)


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
        match = re.search(r"/pull/(\d+)", output)
        if not match:
            from .exceptions import GitHubError  # noqa: PLC0415

            raise GitHubError(f"Could not parse PR URL from gh output: {output!r}")

        return int(match.group(1))

    def get_pr_body(self: GitHubClientProtocol, pr_number: int) -> str:
        """Return the body/description text of a PR.

        Args:
            pr_number: The PR number to read.

        Returns:
            The PR body as text (empty string if the PR has no body).
        """
        # `.body // ""` guards a null body: gh's -q applies jq raw output, which prints the
        # literal string "null" for a JSON null, so map it to an empty string instead.
        result = self._run_gh_command(
            ["gh", "pr", "view", str(pr_number), "--json", "body", "-q", '.body // ""'],
            timeout=30,
        )
        return result.stdout.rstrip("\n")

    def update_pr_body(self: GitHubClientProtocol, pr_number: int, body: str) -> None:
        """Overwrite a PR's body/description.

        Args:
            pr_number: The PR number to edit.
            body: The new body text.
        """
        self._run_gh_command(
            ["gh", "pr", "edit", str(pr_number), "--body", body],
            timeout=60,
        )

    def get_pr_status(
        self: GitHubClientProtocol, pr_number: int, cwd: str | None = None
    ) -> PRStatus:
        """Get PR status including CI checks and review comments.

        Args:
            pr_number: The PR number to check.
            cwd: Working directory (project root) for gh CLI commands.
                Defaults to the current working directory when ``None``.

        Returns:
            PRStatus with CI state, checks, and thread counts.

        Raises:
            GitHubError: If GraphQL query fails.
            GitHubTimeoutError: If command times out.
        """
        # Get repository info
        repo_info = self._get_repo_info(cwd=cwd)
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
            cwd=cwd,
        )

        data = json.loads(result.stdout)

        # Check for GraphQL errors
        if "errors" in data:
            from .exceptions import GitHubError  # noqa: PLC0415

            error_msg = data["errors"][0].get("message", "Unknown GraphQL error")
            raise GitHubError(f"GraphQL error: {error_msg}")

        pr_data = data["data"]["repository"]["pullRequest"]

        return _parse_pr_status_response(pr_number, pr_data)

    def get_required_status_checks(
        self: GitHubClientProtocol, base_branch: str = "main"
    ) -> list[str]:
        """Get required status checks from branch protection rules.

        Args:
            base_branch: The base branch to check protection for.

        Returns:
            List of required check context names; empty only when the branch has
            no protection rules or no required checks.

        Raises:
            GitHubError: If the API call fails for any reason other than missing
                branch protection (auth, rate limit, network, or ambiguous errors).
            GitHubTimeoutError: If the command times out.
        """
        from .exceptions import GitHubError  # noqa: PLC0415

        repo_info = self._get_repo_info()
        result = self._run_gh_command(
            [
                "gh",
                "api",
                f"repos/{repo_info}/branches/{base_branch}/protection/required_status_checks",
                "--jq",
                ".contexts",
            ],
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            lowered = stderr.lower()
            if "not found" in lowered or "404" in lowered or "branch not protected" in lowered:
                # Branch simply has no protection rules / no required checks
                return []
            raise GitHubError(
                f"Failed to fetch required status checks for {base_branch!r}: {stderr}"
            )
        # Parse JSON array of context names
        contexts = json.loads(result.stdout)
        return contexts if isinstance(contexts, list) else []

    def get_pr_for_current_branch(
        self: GitHubClientProtocol, cwd: str | None = None
    ) -> int | None:
        """Get PR number for the current branch, if one exists.

        Args:
            cwd: Working directory to run the command in (project root).

        Returns:
            PR number if one exists, None otherwise.
        """
        from .exceptions import GitHubError, GitHubTimeoutError  # noqa: PLC0415

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

        # Use REST API to get ALL PR review comments (like tstc).
        # --paginate concatenates pages; --jq '.[]' emits one object per line (NDJSON).
        result = self._run_gh_command(
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

        # Get resolved status from GraphQL
        resolved_map = _get_comment_resolved_map(self, repo_info, pr_number)

        # Format comments
        return _format_pr_comments_from_rest(all_comments, resolved_map, only_unresolved)


__all__ = [
    "PRStatus",
    "GitHubClientProtocol",
    "PROperationsMixin",
    "_get_comment_resolved_map",
    "_build_pr_status_query",
    "_parse_pr_status_response",
    "_parse_check_contexts",
    "_format_pr_comments",
    "_format_pr_comments_from_rest",
]
