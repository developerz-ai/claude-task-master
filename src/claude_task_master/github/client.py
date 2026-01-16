"""GitHub Integration Layer - All GitHub operations via gh CLI and GraphQL API."""

import json
import subprocess
from typing import Any

from pydantic import BaseModel


class PRStatus(BaseModel):
    """PR status information."""

    number: int
    ci_state: str  # PENDING, SUCCESS, FAILURE, ERROR
    unresolved_threads: int
    check_details: list[dict[str, Any]]


class WorkflowRun(BaseModel):
    """GitHub Actions workflow run information."""

    id: int
    name: str
    status: str  # queued, in_progress, completed
    conclusion: str | None  # success, failure, cancelled, skipped, etc.
    url: str
    head_branch: str
    event: str  # push, pull_request, etc.


class GitHubClient:
    """Handles all GitHub operations using gh CLI."""

    def __init__(self) -> None:
        """Initialize GitHub client."""
        self._check_gh_cli()

    def _check_gh_cli(self) -> None:
        """Check if gh CLI is installed and authenticated."""
        try:
            subprocess.run(
                ["gh", "auth", "status"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError("gh CLI not authenticated. Run 'gh auth login' first.") from e
        except FileNotFoundError as e:
            raise RuntimeError("gh CLI not installed. Install from https://cli.github.com/") from e

    def create_pr(self, title: str, body: str, base: str = "main") -> int:
        """Create a new pull request."""
        result = subprocess.run(
            ["gh", "pr", "create", "--title", title, "--body", body, "--base", base],
            check=True,
            capture_output=True,
            text=True,
        )

        # Extract PR number from output
        # gh CLI outputs URL like: https://github.com/owner/repo/pull/123
        output = result.stdout.strip()
        pr_number = int(output.split("/")[-1])

        return pr_number

    def get_pr_status(self, pr_number: int) -> PRStatus:
        """Get PR status including CI checks and review comments."""
        # Get repository info
        repo_info = self._get_repo_info()
        owner, repo = repo_info.split("/")

        # Run GraphQL query
        query = """
        query($owner: String!, $repo: String!, $pr: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pr) {
              commits(last: 1) {
                nodes {
                  commit {
                    statusCheckRollup {
                      state
                      contexts(first: 50) {
                        nodes {
                          ... on CheckRun {
                            name
                            status
                            conclusion
                            detailsUrl
                          }
                        }
                      }
                    }
                  }
                }
              }
              reviewThreads(first: 100) {
                nodes {
                  isResolved
                  comments(first: 10) {
                    nodes {
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
        pr_data = data["data"]["repository"]["pullRequest"]

        # Parse CI status
        ci_state = "PENDING"
        check_details = []

        if pr_data["commits"]["nodes"]:
            commit = pr_data["commits"]["nodes"][0]["commit"]
            if commit["statusCheckRollup"]:
                ci_state = commit["statusCheckRollup"]["state"]
                contexts = commit["statusCheckRollup"]["contexts"]["nodes"]
                check_details = [
                    {
                        "name": ctx["name"],
                        "status": ctx["status"],
                        "conclusion": ctx.get("conclusion"),
                        "url": ctx.get("detailsUrl"),
                    }
                    for ctx in contexts
                ]

        # Count unresolved review threads
        unresolved = sum(
            1 for thread in pr_data["reviewThreads"]["nodes"] if not thread["isResolved"]
        )

        return PRStatus(
            number=pr_number,
            ci_state=ci_state,
            unresolved_threads=unresolved,
            check_details=check_details,
        )

    def get_pr_for_current_branch(self, cwd: str | None = None) -> int | None:
        """Get PR number for the current branch, if one exists.

        Args:
            cwd: Working directory to run the command in (project root).
        """
        try:
            result = subprocess.run(
                ["gh", "pr", "view", "--json", "number"],
                check=True,
                capture_output=True,
                text=True,
                cwd=cwd,
            )
            data = json.loads(result.stdout)
            return data.get("number")
        except subprocess.CalledProcessError:
            # No PR exists for current branch
            return None

    def get_pr_comments(self, pr_number: int, only_unresolved: bool = True) -> str:
        """Get PR review comments formatted for Claude."""
        # Get repository info
        repo_info = self._get_repo_info()
        owner, repo = repo_info.split("/")

        # Run GraphQL query
        query = """
        query($owner: String!, $repo: String!, $pr: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pr) {
              reviewThreads(first: 100) {
                nodes {
                  isResolved
                  comments(first: 10) {
                    nodes {
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

        # Format comments
        formatted = []
        for thread in threads:
            if only_unresolved and thread["isResolved"]:
                continue

            for comment in thread["comments"]["nodes"]:
                author = comment["author"]["login"]
                is_bot = author.endswith("[bot]")
                bot_marker = " (bot)" if is_bot else ""

                formatted.append(
                    f"**{author}{bot_marker}** on {comment.get('path', 'PR')}:{comment.get('line', 'N/A')}\n"
                    f"{comment['body']}\n"
                )

        return "\n---\n\n".join(formatted)

    def merge_pr(self, pr_number: int) -> None:
        """Merge a pull request."""
        subprocess.run(
            ["gh", "pr", "merge", str(pr_number), "--squash", "--auto"],
            check=True,
        )

    def _get_repo_info(self) -> str:
        """Get current repository owner/name."""
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def get_workflow_runs(self, limit: int = 5, branch: str | None = None) -> list[WorkflowRun]:
        """Get recent workflow runs.

        Args:
            limit: Maximum number of runs to return.
            branch: Optional branch filter.

        Returns:
            List of WorkflowRun objects.
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

        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
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

    def get_workflow_run_status(self, run_id: int | None = None) -> str:
        """Get workflow run status formatted for display.

        Args:
            run_id: Specific run ID. If None, gets the latest run.

        Returns:
            Formatted status string.
        """
        if run_id:
            cmd = ["gh", "run", "view", str(run_id), "--json", "status,conclusion,jobs"]
        else:
            # Get the latest run
            runs = self.get_workflow_runs(limit=1)
            if not runs:
                return "No workflow runs found."
            run_id = runs[0].id
            cmd = ["gh", "run", "view", str(run_id), "--json", "status,conclusion,jobs"]

        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        data = json.loads(result.stdout)

        status = data.get("status", "unknown")
        conclusion = data.get("conclusion", "pending")
        jobs = data.get("jobs", [])

        lines = [f"**Run #{run_id}**: {status} ({conclusion or 'in progress'})"]

        for job in jobs:
            job_status = job.get("conclusion") or job.get("status", "unknown")
            job_name = job.get("name", "Unknown Job")
            emoji = "✓" if job_status == "success" else "✗" if job_status == "failure" else "⏳"
            lines.append(f"  {emoji} {job_name}: {job_status}")

        return "\n".join(lines)

    def get_failed_run_logs(self, run_id: int | None = None, max_lines: int = 100) -> str:
        """Get logs from failed workflow run jobs.

        Args:
            run_id: Specific run ID. If None, gets the latest failed run.
            max_lines: Maximum lines of logs to return per job.

        Returns:
            Formatted log output.
        """
        cmd = ["gh", "run", "view"]
        if run_id:
            cmd.append(str(run_id))
        cmd.append("--log-failed")

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return f"Error getting logs: {result.stderr}"

        # Truncate output if too long
        lines = result.stdout.strip().split("\n")
        if len(lines) > max_lines:
            return "\n".join(lines[:max_lines]) + f"\n\n... ({len(lines) - max_lines} more lines)"

        return result.stdout.strip()

    def wait_for_ci(self, pr_number: int | None = None, timeout: int = 300) -> tuple[bool, str]:
        """Wait for CI checks to complete.

        Args:
            pr_number: PR number to check. If None, checks current branch.
            timeout: Maximum seconds to wait.

        Returns:
            Tuple of (success: bool, message: str).
        """
        import time

        start = time.time()
        while time.time() - start < timeout:
            if pr_number:
                status = self.get_pr_status(pr_number)
                if status.ci_state == "SUCCESS":
                    return True, "All CI checks passed!"
                elif status.ci_state in ("FAILURE", "ERROR"):
                    return False, f"CI failed with state: {status.ci_state}"
                # Still pending, wait
            else:
                runs = self.get_workflow_runs(limit=1)
                if runs:
                    run = runs[0]
                    if run.status == "completed":
                        if run.conclusion == "success":
                            return True, "Workflow run succeeded!"
                        else:
                            return False, f"Workflow run failed: {run.conclusion}"

            time.sleep(10)  # Poll every 10 seconds

        return False, f"Timeout after {timeout} seconds"
