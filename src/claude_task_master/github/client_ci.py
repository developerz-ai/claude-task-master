"""GitHub CI Operations - workflow runs, CI status, and logs."""

import json
import subprocess
import time
from typing import Protocol

from pydantic import BaseModel


class WorkflowRun(BaseModel):
    """GitHub Actions workflow run information."""

    id: int
    name: str
    status: str  # queued, in_progress, completed
    conclusion: str | None  # success, failure, cancelled, skipped, etc.
    url: str
    head_branch: str
    event: str  # push, pull_request, etc.


class GitHubClientProtocol(Protocol):
    """Protocol defining the methods required from GitHubClient."""

    def _run_gh_command(
        self,
        cmd: list[str],
        timeout: int = 30,
        check: bool = True,
        capture_output: bool = True,
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a gh CLI command."""
        raise NotImplementedError("Protocol method must be implemented")

    def get_workflow_runs(self, limit: int = 5, branch: str | None = None) -> list["WorkflowRun"]:
        """Get workflow runs."""
        raise NotImplementedError("Protocol method must be implemented")

    def get_pr_status(self, pr_number: int) -> "PRStatusProtocol":
        """Get PR status."""
        raise NotImplementedError("Protocol method must be implemented")


class PRStatusProtocol(Protocol):
    """Protocol for PRStatus to avoid circular imports."""

    ci_state: str


class CIOperationsMixin:
    """Mixin class providing CI operations for GitHubClient.

    This class should be used with GitHubClient to add CI-related functionality.
    It depends on _run_gh_command being available.
    """

    def get_workflow_runs(
        self: GitHubClientProtocol, limit: int = 5, branch: str | None = None
    ) -> list[WorkflowRun]:
        """Get recent workflow runs.

        Args:
            limit: Maximum number of runs to return.
            branch: Optional branch filter.

        Returns:
            List of WorkflowRun objects.

        Raises:
            GitHubError: If command fails.
            GitHubTimeoutError: If command times out.
        """
        cmd = [
            "gh",
            "run",
            "list",
            "--limit",
            str(limit),
            "--json",
            "databaseId,name,status,conclusion,url,headBranch,event",
        ]
        if branch:
            cmd.extend(["--branch", branch])

        result = self._run_gh_command(cmd, timeout=30)
        data = json.loads(result.stdout)

        return [
            WorkflowRun(
                id=run["databaseId"],
                name=run["name"],
                status=run["status"],
                conclusion=run.get("conclusion"),
                url=run["url"],
                head_branch=run["headBranch"],
                event=run["event"],
            )
            for run in data
        ]

    def get_workflow_run_status(self: GitHubClientProtocol, run_id: int | None = None) -> str:
        """Get workflow run status formatted for display.

        Args:
            run_id: Specific run ID. If None, gets the latest run.

        Returns:
            Formatted status string.

        Raises:
            GitHubError: If command fails.
            GitHubTimeoutError: If command times out.
        """
        if run_id is None:
            # Get the latest run
            runs = self.get_workflow_runs(limit=1)
            if not runs:
                return "No workflow runs found."
            run_id = runs[0].id

        cmd = ["gh", "run", "view", str(run_id), "--json", "status,conclusion,jobs"]
        result = self._run_gh_command(cmd, timeout=30)
        data = json.loads(result.stdout)

        return _format_workflow_status(run_id, data)

    def get_failed_run_logs(
        self: GitHubClientProtocol, run_id: int | None = None, max_lines: int = 100
    ) -> str:
        """Get logs from failed workflow run jobs.

        Args:
            run_id: Specific run ID. If None, gets the latest failed run.
            max_lines: Maximum lines of logs to return per job.

        Returns:
            Formatted log output.

        Raises:
            GitHubTimeoutError: If command times out.
        """
        from .exceptions import GitHubTimeoutError

        # If no run_id provided, get the latest failed run
        if run_id is None:
            run_id = _find_failed_run_id(self)
            if run_id is None:
                return "No workflow runs found"

        cmd = ["gh", "run", "view", str(run_id), "--log-failed"]
        try:
            result = self._run_gh_command(cmd, timeout=60, check=False)  # Logs can be large
        except GitHubTimeoutError:
            return "Error getting logs: Command timed out"

        if result.returncode != 0:
            return f"Error getting logs: {result.stderr}"

        return _truncate_log_output(result.stdout.strip(), max_lines)

    def wait_for_ci(
        self: GitHubClientProtocol, pr_number: int | None = None, timeout: int = 300
    ) -> tuple[bool, str]:
        """Wait for CI checks to complete.

        Args:
            pr_number: PR number to check. If None, checks current branch.
            timeout: Maximum seconds to wait.

        Returns:
            Tuple of (success: bool, message: str).
        """
        start = time.time()
        while time.time() - start < timeout:
            if pr_number:
                success, message, done = _check_pr_ci_status(self, pr_number)
                if done:
                    return success, message
            else:
                success, message, done = _check_workflow_ci_status(self)
                if done:
                    return success, message

            time.sleep(10)  # Poll every 10 seconds

        return False, f"Timeout after {timeout} seconds"


def _format_workflow_status(run_id: int, data: dict) -> str:
    """Format workflow run data into a display string.

    Args:
        run_id: The workflow run ID.
        data: The workflow run data from gh CLI.

    Returns:
        Formatted status string.
    """
    status = data.get("status", "unknown")
    conclusion = data.get("conclusion", "pending")
    jobs = data.get("jobs", [])

    lines = [f"**Run #{run_id}**: {status} ({conclusion or 'in progress'})"]

    for job in jobs:
        job_status = job.get("conclusion") or job.get("status", "unknown")
        job_name = job.get("name", "Unknown Job")
        emoji = _get_job_status_emoji(job_status)
        lines.append(f"  {emoji} {job_name}: {job_status}")

    return "\n".join(lines)


def _get_job_status_emoji(job_status: str) -> str:
    """Get emoji for job status.

    Args:
        job_status: The job status string.

    Returns:
        Appropriate emoji character.
    """
    if job_status == "success":
        return "✓"
    elif job_status == "failure":
        return "✗"
    else:
        return "⏳"


def _find_failed_run_id(client: GitHubClientProtocol) -> int | None:
    """Find the ID of the latest failed workflow run.

    Args:
        client: The GitHub client instance.

    Returns:
        Run ID if found, None otherwise.
    """
    runs = client.get_workflow_runs(limit=5)
    failed_run = next(
        (r for r in runs if r.conclusion in ("failure", "cancelled")),
        None,
    )
    if failed_run:
        return int(failed_run.id)
    elif runs:
        return int(runs[0].id)  # Use latest run as fallback
    return None


def _truncate_log_output(output: str, max_lines: int) -> str:
    """Truncate log output if too long.

    Args:
        output: The log output string.
        max_lines: Maximum number of lines to keep.

    Returns:
        Truncated output with indicator if truncated.
    """
    lines = output.split("\n")
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + f"\n\n... ({len(lines) - max_lines} more lines)"
    return output


def _check_pr_ci_status(client: GitHubClientProtocol, pr_number: int) -> tuple[bool, str, bool]:
    """Check CI status for a PR.

    Args:
        client: The GitHub client instance.
        pr_number: The PR number to check.

    Returns:
        Tuple of (success, message, is_done).
    """
    # get_pr_status is defined in client_pr and added to client via mixin
    status = client.get_pr_status(pr_number)
    if status.ci_state == "SUCCESS":
        return True, "All CI checks passed!", True
    elif status.ci_state in ("FAILURE", "ERROR"):
        return False, f"CI failed with state: {status.ci_state}", True
    # Still pending
    return False, "", False


def _check_workflow_ci_status(client: GitHubClientProtocol) -> tuple[bool, str, bool]:
    """Check CI status for the current branch workflows.

    Args:
        client: The GitHub client instance.

    Returns:
        Tuple of (success, message, is_done).
    """
    runs = client.get_workflow_runs(limit=1)
    if runs:
        run = runs[0]
        if run.status == "completed":
            if run.conclusion == "success":
                return True, "Workflow run succeeded!", True
            else:
                return False, f"Workflow run failed: {run.conclusion}", True
    # Still pending or no runs
    return False, "", False
