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

import subprocess

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

# Re-export for backward compatibility
__all__ = [
    "DEFAULT_GH_TIMEOUT",
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
        try:
            result = subprocess.run(
                cmd,
                timeout=timeout,
                check=False,  # We'll handle errors ourselves
                capture_output=capture_output,
                text=True,
                cwd=cwd,
            )

            if check and result.returncode != 0:
                error_msg = (
                    result.stderr.strip()
                    if result.stderr
                    else f"Command failed with exit code {result.returncode}"
                )
                raise GitHubError(error_msg, command=cmd, exit_code=result.returncode)

            return result

        except subprocess.TimeoutExpired as e:
            raise GitHubTimeoutError(
                f"Command timed out after {timeout}s: {' '.join(cmd)}",
                command=cmd,
            ) from e

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

    def _get_repo_info(self) -> str:
        """Get current repository owner/name.

        Returns:
            Repository in owner/name format (e.g., "owner/repo").

        Raises:
            GitHubError: If command fails.
            GitHubTimeoutError: If command times out.
        """
        result = self._run_gh_command(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            timeout=15,
        )
        return result.stdout.strip()

    def merge_pr(self, pr_number: int, use_auto: bool = True, admin: bool = False) -> None:
        """Merge a pull request using squash strategy.

        This method attempts to merge the specified PR. If use_auto is True,
        it first tries to enable GitHub's auto-merge feature (which merges
        automatically when all checks pass). If auto-merge is not available
        or fails, it falls back to direct merge.

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
            # First try with --auto (enables auto-merge when checks pass)
            if self._try_auto_merge(pr_str):
                return  # Success with auto-merge enabled

        # Try direct merge (squash without --auto)
        self._direct_merge(pr_str, pr_number)

    def _try_auto_merge(self, pr_str: str) -> bool:
        """Attempt to enable auto-merge for a PR.

        Args:
            pr_str: The PR number as a string.

        Returns:
            True if auto-merge was successfully enabled, False otherwise.
        """
        try:
            self._run_gh_command(
                ["gh", "pr", "merge", pr_str, "--squash", "--auto"],
                timeout=15,  # Short timeout - --auto should be quick
            )
            return True  # Success with auto-merge enabled
        except GitHubTimeoutError:
            # --auto timed out, caller should try direct merge
            return False
        except GitHubError as e:
            # --auto not available (repo doesn't support it) or other error
            # Check for common "not supported" messages
            error_lower = str(e).lower()
            if "auto-merge is not allowed" in error_lower or "not enabled" in error_lower:
                return False
            # Some other error, still return False to try direct merge
            return False

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
