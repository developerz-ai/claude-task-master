"""CI helper functions for fix-pr command."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ..core import console

if TYPE_CHECKING:
    from ..github import GitHubClient, PRStatus


# Polling intervals
CI_POLL_INTERVAL = 10  # seconds between CI checks (matches orchestrator)
CI_START_WAIT = 30  # seconds to wait for CI to start after push


def is_check_pending(check: dict[str, Any]) -> bool:
    """Check if a CI check or status is still pending.

    Handles both CheckRun (GitHub Actions) and StatusContext (external services like CodeRabbit).

    CheckRun states:
        - status: QUEUED, IN_PROGRESS, COMPLETED
        - conclusion: success, failure, etc. (only set when COMPLETED)

    StatusContext states:
        - state: PENDING, EXPECTED, SUCCESS, FAILURE, ERROR
        - Maps to both status and conclusion in our normalized format

    Args:
        check: Normalized check detail dictionary.

    Returns:
        True if the check is still pending, False if complete.
    """
    status = (check.get("status") or "").upper()
    conclusion = check.get("conclusion")

    # StatusContext with PENDING or EXPECTED state is still waiting
    # (These get mapped to both status and conclusion)
    if status in ("PENDING", "EXPECTED"):
        return True

    # CheckRun is pending if not completed or has no conclusion yet
    if status not in ("COMPLETED",) and conclusion is None:
        return True

    return False


def wait_for_ci_complete(github_client: GitHubClient, pr_number: int) -> PRStatus:
    """Wait for all CI checks to complete.

    Fetches required checks from branch protection and waits for all of them
    to report, even if they haven't started yet (like CodeRabbit).

    Args:
        github_client: GitHub client for API calls.
        pr_number: PR number to check.

    Returns:
        Final PRStatus after all checks complete.
    """
    console.info(f"Waiting for CI checks on PR #{pr_number}...")

    # Get required checks from branch protection (once at start)
    status = github_client.get_pr_status(pr_number)
    required_checks = set(github_client.get_required_status_checks(status.base_branch))

    while True:
        status = github_client.get_pr_status(pr_number)

        # Get reported check names
        reported = {check.get("name", "") for check in status.check_details}

        # Find required checks that haven't reported yet
        missing = required_checks - reported

        # Count pending checks (in progress or not yet complete)
        pending = [
            check.get("name", "unknown")
            for check in status.check_details
            if is_check_pending(check)
        ]

        # All pending = running checks + missing required checks
        all_waiting = list(missing) + pending

        if not all_waiting:
            # All checks reported - verify no conflicts
            if status.mergeable == "CONFLICTING":
                console.warning("⚠ PR has merge conflicts")
            return status

        # Build status summary
        passed = status.checks_passed
        failed = status.checks_failed
        status_parts = []
        if passed:
            status_parts.append(f"{passed} passed")
        if failed:
            status_parts.append(f"{failed} failed")
        status_summary = f" ({', '.join(status_parts)})" if status_parts else ""

        # Show what we're waiting for
        console.info(
            f"⏳ Waiting for {len(all_waiting)} check(s): "
            f"{', '.join(all_waiting[:3])}{'...' if len(all_waiting) > 3 else ''}"
            f"{status_summary}"
        )

        time.sleep(CI_POLL_INTERVAL)
