"""GitHub Integration Layer - Main GitHubClient with initialization, merge, and delegation.

This module provides the main GitHubClient class that:
- Handles gh CLI initialization and authentication
- Provides core command execution infrastructure
- Implements merge operations
- Delegates PR and CI operations to specialized mixins

The client uses composition via mixins:
- PROperationsMixin: PR creation, status, and comments
- CIOperationsMixin: Workflow runs, CI status, and logs
"""

import random
import re
import subprocess
import time
from enum import StrEnum

from .client_ci import CIOperationsMixin, WorkflowRun
from .client_pr import PROperationsMixin, PRStatus
from .exceptions import (
    GitHubAuthError,
    GitHubError,
    GitHubMergeError,
    GitHubNotFoundError,
    GitHubTimeoutError,
)

# Default timeout for gh CLI commands (30 seconds)
DEFAULT_GH_TIMEOUT = 30

# Number of times to poll PR state after enabling auto-merge
AUTO_MERGE_CONFIRM_ATTEMPTS = 6

# Seconds between auto-merge confirmation polls
AUTO_MERGE_CONFIRM_DELAY = 10

# Rate-limit handling: GitHub answers primary/secondary rate limits with HTTP
# 403/429, which gh surfaces on stderr. We retry with backoff so a long CI wait
# neither hammers a throttled API nor fails spuriously on a transient limit.
RATE_LIMIT_MAX_RETRIES = 5
RATE_LIMIT_BASE_DELAY = 2.0  # seconds; grows exponentially per attempt
RATE_LIMIT_MAX_DELAY = 60.0  # cap for any single backoff sleep

# Substrings GitHub uses in its 403/429 rate-limit / abuse responses.
_RATE_LIMIT_MARKERS = (
    "rate limit exceeded",
    "secondary rate limit",
    "abuse detection",
    "http 429",
    "too many requests",
)

# Matches a "Retry-After: <seconds>" hint when gh echoes the response header.
_RETRY_AFTER_RE = re.compile(r"retry[-\s]?after:?\s*(\d+)", re.IGNORECASE)


def _is_rate_limit_error(stderr: str) -> bool:
    """Return True if gh stderr indicates a GitHub rate limit (403/429).

    Args:
        stderr: Captured stderr from a failed gh command.

    Returns:
        True when the message matches a known rate-limit marker.
    """
    if not stderr:
        return False
    lowered = stderr.lower()
    return any(marker in lowered for marker in _RATE_LIMIT_MARKERS)


def _parse_retry_after(stderr: str) -> float | None:
    """Extract a Retry-After delay (seconds) from gh stderr, if present.

    Args:
        stderr: Captured stderr from a failed gh command.

    Returns:
        The Retry-After value in seconds, or None when absent/unparseable.
    """
    if not stderr:
        return None
    match = _RETRY_AFTER_RE.search(stderr)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _compute_rate_limit_delay(attempt: int, retry_after: float | None) -> float:
    """Compute how long to sleep before retrying a rate-limited command.

    Honors an explicit Retry-After value when GitHub provides one; otherwise
    uses exponential backoff with equal jitter to avoid synchronized retries
    across concurrent instances.

    Args:
        attempt: Zero-based retry attempt number.
        retry_after: Server-provided Retry-After delay in seconds, if any.

    Returns:
        Delay in seconds, capped at RATE_LIMIT_MAX_DELAY.
    """
    if retry_after is not None and retry_after > 0:
        return min(retry_after, RATE_LIMIT_MAX_DELAY)
    backoff = min(RATE_LIMIT_BASE_DELAY * (2**attempt), RATE_LIMIT_MAX_DELAY)
    # Equal jitter: half fixed, half random → delay in [backoff/2, backoff].
    half = backoff / 2
    return float(half + random.uniform(0, half))


class AutoMergeResult(StrEnum):
    """Outcome of attempting to merge a PR via GitHub auto-merge.

    Attributes:
        MERGED: The PR was confirmed merged (state is MERGED).
        SCHEDULED: The auto-merge command succeeded, but the PR was not yet
            merged after bounded confirmation polling; GitHub will merge it
            once all required checks pass.
        FAILED: The auto-merge attempt failed; callers should fall back to
            a direct merge.
    """

    MERGED = "merged"
    SCHEDULED = "scheduled"
    FAILED = "failed"


# Re-export for backward compatibility
__all__ = [
    "DEFAULT_GH_TIMEOUT",
    "AutoMergeResult",
    "GitHubClient",
    "GitHubError",
    "GitHubTimeoutError",
    "GitHubAuthError",
    "GitHubNotFoundError",
    "GitHubMergeError",
    "PRStatus",
    "WorkflowRun",
]


class GitHubClient(PROperationsMixin, CIOperationsMixin):
    """Main GitHub client that handles all GitHub operations using gh CLI.

    This class provides:
    - gh CLI initialization and authentication checking
    - Core command execution with timeout handling
    - Repository information retrieval
    - PR merge operations

    PR and CI operations are provided via mixins:
    - PROperationsMixin: create_pr, get_pr_status, get_pr_for_current_branch, get_pr_comments
    - CIOperationsMixin: get_workflow_runs, get_workflow_run_status, get_failed_run_logs, wait_for_ci
    """

    def __init__(self) -> None:
        """Initialize GitHub client and verify gh CLI is available and authenticated."""
        self._check_gh_cli()
        # Cache repo info per working-directory key to avoid repeated `gh repo view` calls.
        self._repo_info_cache: dict[str | None, str] = {}

    def _run_gh_command(
        self,
        cmd: list[str],
        timeout: int = DEFAULT_GH_TIMEOUT,
        check: bool = True,
        capture_output: bool = True,
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a gh CLI command with proper timeout and error handling.

        This is the core command execution method used by all GitHub operations.
        On a GitHub 403/429 rate-limit response it retries with backoff (honoring
        Retry-After when present), bounded by RATE_LIMIT_MAX_RETRIES. A rate limit
        means the request was rejected before executing, so retrying is safe for
        every command, including merges.

        Args:
            cmd: Command and arguments to run (e.g., ["gh", "pr", "list"]).
            timeout: Timeout in seconds (default 30).
            check: Whether to raise on non-zero exit code.
            capture_output: Whether to capture stdout/stderr.
            cwd: Working directory for the command.

        Returns:
            CompletedProcess result with stdout and stderr.

        Raises:
            GitHubTimeoutError: If command times out.
            GitHubError: If command fails and check=True.
        """
        attempt = 0
        while True:
            try:
                result = subprocess.run(
                    cmd,
                    timeout=timeout,
                    check=False,  # We'll handle errors ourselves
                    capture_output=capture_output,
                    text=True,
                    cwd=cwd,
                )
            except subprocess.TimeoutExpired as e:
                raise GitHubTimeoutError(
                    f"Command timed out after {timeout}s: {' '.join(cmd)}",
                    command=cmd,
                ) from e

            if result.returncode != 0:
                stderr = result.stderr or ""
                if attempt < RATE_LIMIT_MAX_RETRIES and _is_rate_limit_error(stderr):
                    delay = _compute_rate_limit_delay(attempt, _parse_retry_after(stderr))
                    # Lazy import avoids a github<->core import cycle at module load.
                    from ..core import console

                    console.warning(
                        f"GitHub rate limit hit; retrying in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{RATE_LIMIT_MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    attempt += 1
                    continue

                if check:
                    error_msg = (
                        stderr.strip()
                        if stderr
                        else f"Command failed with exit code {result.returncode}"
                    )
                    raise GitHubError(error_msg, command=cmd, exit_code=result.returncode)

            return result

    def _check_gh_cli(self) -> None:
        """Check if gh CLI is installed and authenticated.

        This is called during initialization to ensure the gh CLI is available
        and properly authenticated before any operations are attempted.

        Raises:
            GitHubAuthError: If gh CLI is not authenticated.
            GitHubNotFoundError: If gh CLI is not installed.
            GitHubTimeoutError: If authentication check times out.
        """
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                timeout=10,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise GitHubAuthError(
                    "gh CLI not authenticated. Run 'gh auth login' first.",
                    command=["gh", "auth", "status"],
                    exit_code=result.returncode,
                )
        except subprocess.TimeoutExpired as e:
            raise GitHubTimeoutError(
                "gh auth status timed out",
                command=["gh", "auth", "status"],
            ) from e
        except FileNotFoundError as e:
            raise GitHubNotFoundError(
                "gh CLI not installed. Install from https://cli.github.com/",
                command=["gh", "auth", "status"],
            ) from e

    def _get_repo_info(self, cwd: str | None = None) -> str:
        """Get current repository owner/name (memoized per working directory).

        Results are cached per ``cwd`` value so that repeated calls within the
        same client instance avoid redundant ``gh repo view`` round-trips.

        Args:
            cwd: Working directory for the gh command. Defaults to the current
                working directory when ``None``.

        Returns:
            Repository in owner/name format (e.g., "owner/repo").

        Raises:
            GitHubError: If command fails.
            GitHubTimeoutError: If command times out.
        """
        if cwd not in self._repo_info_cache:
            result = self._run_gh_command(
                ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                timeout=15,
                cwd=cwd,
            )
            self._repo_info_cache[cwd] = result.stdout.strip()
        return self._repo_info_cache[cwd]

    def merge_pr(self, pr_number: int, use_auto: bool = True, admin: bool = False) -> None:
        """Merge a pull request using squash strategy.

        This method attempts to merge the specified PR. If use_auto is True,
        it first tries GitHub's auto-merge feature. Note that a successful
        auto-merge attempt may only SCHEDULE the merge (GitHub merges once
        required checks pass) rather than merge immediately; both outcomes
        are treated as success and this method returns normally. Only if the
        auto-merge attempt itself fails does it fall back to direct merge.

        Callers must not assume the branch is merged (or safe to delete) after
        this method returns when auto-merge was used: the merge may still be
        pending on GitHub until checks complete.

        Args:
            pr_number: The PR number to merge.
            use_auto: If True, try --auto first (enable auto-merge).
                      If that fails, fall back to direct merge.
                      Default is True.
            admin: If True, pass ``--admin`` to override the base-branch
                   protection policy (requires admin privileges on the repo).
                   Auto-merge is skipped in this mode because an admin merge is
                   an immediate, direct override. Default is False.

        Raises:
            GitHubMergeError: If merge fails after all attempts.
            GitHubTimeoutError: If merge command times out.
        """
        pr_str = str(pr_number)

        # Admin override: skip --auto and force an immediate direct merge that
        # bypasses base-branch policy (e.g. "base branch policy prohibits the merge").
        if admin:
            self._direct_merge(pr_str, pr_number, admin=True)
            return

        if use_auto:
            # First try with --auto (merges now if allowed, else schedules the
            # merge for when checks pass). Both outcomes count as success.
            if self._try_auto_merge(pr_str) is not AutoMergeResult.FAILED:
                return

        # Try direct merge (squash without --auto)
        self._direct_merge(pr_str, pr_number)

    def _try_auto_merge(self, pr_str: str) -> AutoMergeResult:
        """Attempt to merge a PR via GitHub auto-merge.

        A successful ``gh pr merge --auto`` command does not mean the PR is
        merged: GitHub may only have SCHEDULED the merge to occur once all
        required checks pass. To distinguish the two, this method polls
        ``get_pr_status`` until the PR state is MERGED, giving up after a
        bounded number of attempts.

        Args:
            pr_str: The PR number as a string.

        Returns:
            AutoMergeResult.MERGED if the PR is confirmed merged now,
            AutoMergeResult.SCHEDULED if the command succeeded but the PR was
            not yet merged after bounded polling, or AutoMergeResult.FAILED if
            the auto-merge command itself failed (caller should fall back to
            a direct merge).
        """
        try:
            self._run_gh_command(
                ["gh", "pr", "merge", pr_str, "--squash", "--auto"],
                timeout=15,  # Short timeout - --auto should be quick
            )
        except (GitHubTimeoutError, GitHubError):
            # --auto timed out, is not supported by the repo, or hit another
            # error; caller should fall back to a direct merge.
            return AutoMergeResult.FAILED

        # The command succeeded, but the PR may only be scheduled for merge.
        # Confirm by polling until the state is MERGED (bounded attempts).
        for attempt in range(1, AUTO_MERGE_CONFIRM_ATTEMPTS + 1):
            try:
                status = self.get_pr_status(int(pr_str))
                if status.state == "MERGED":
                    return AutoMergeResult.MERGED
            except Exception:
                # Treat a failed status check as not-yet-merged and retry;
                # never raise from here.
                pass
            if attempt < AUTO_MERGE_CONFIRM_ATTEMPTS:
                time.sleep(AUTO_MERGE_CONFIRM_DELAY * attempt)

        return AutoMergeResult.SCHEDULED

    def _direct_merge(self, pr_str: str, pr_number: int, admin: bool = False) -> None:
        """Perform direct merge of a PR.

        Args:
            pr_str: The PR number as a string.
            pr_number: The PR number as an integer (for error messages).
            admin: If True, append ``--admin`` to override base-branch policy.

        Raises:
            GitHubMergeError: If merge fails.
        """
        cmd = ["gh", "pr", "merge", pr_str, "--squash", "--delete-branch"]
        if admin:
            cmd.append("--admin")
        try:
            self._run_gh_command(
                cmd,
                timeout=30,
            )
        except GitHubTimeoutError as e:
            raise GitHubMergeError(
                f"PR #{pr_number} merge timed out. Manual merge may be required.",
                command=e.command,
            ) from e
        except GitHubError as e:
            raise GitHubMergeError(
                f"Failed to merge PR #{pr_number}: {e.message}",
                command=e.command,
                exit_code=e.exit_code,
            ) from e
