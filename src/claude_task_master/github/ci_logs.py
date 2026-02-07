"""CI Log Downloader - Download logs from failed CI jobs.

This module provides functionality to download complete logs from failed
GitHub Actions jobs without truncation or ZIP extraction.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class CIJob:
    """Represents a GitHub Actions job."""

    id: int
    name: str
    status: str  # queued, in_progress, completed
    conclusion: str | None  # success, failure, cancelled, etc.
    run_id: int


@dataclass
class ErrorBlock:
    """Represents an error block extracted from logs."""

    content: str
    line_number: int
    context_before: int
    context_after: int


class CILogDownloader:
    """Downloads and manages CI logs for failed jobs.

    This class follows the Single Responsibility Principle by focusing solely
    on downloading and extracting CI logs from failed jobs.

    Key features:
    - Downloads logs for ONLY failed jobs (not all jobs)
    - Uses per-job API (no ZIP extraction needed)
    - Extracts error blocks with context
    - No temporary files to clean up
    """

    def __init__(self, repo: str, timeout: int = 60):
        """Initialize the CI log downloader.

        Args:
            repo: Repository in format 'owner/repo'.
            timeout: Command timeout in seconds (default: 60).
        """
        self.repo = repo
        self.timeout = timeout

    def get_failed_jobs(self, run_id: int) -> list[CIJob]:
        """Get list of failed jobs for a workflow run.

        Args:
            run_id: The workflow run ID.

        Returns:
            List of CIJob objects for failed jobs only.

        Raises:
            GitHubError: If API call fails.
            GitHubTimeoutError: If command times out.
        """
        from .exceptions import GitHubError, GitHubTimeoutError

        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{self.repo}/actions/runs/{run_id}/jobs"],
                capture_output=True,
                text=True,
                check=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise GitHubTimeoutError(f"Timeout getting jobs for run {run_id}") from e
        except subprocess.CalledProcessError as e:
            raise GitHubError(f"Failed to get jobs: {e.stderr}") from e

        data = json.loads(result.stdout)
        jobs = data.get("jobs", [])

        # Filter to only failed jobs (exclude cancelled - those were intentionally stopped)
        failed_jobs = []
        for job in jobs:
            conclusion = job.get("conclusion")
            # Only include actual failures, not cancelled jobs
            if conclusion in ("failure", "timed_out", "action_required"):
                failed_jobs.append(
                    CIJob(
                        id=job["id"],
                        name=job["name"],
                        status=job.get("status", "completed"),
                        conclusion=conclusion,
                        run_id=run_id,
                    )
                )

        return failed_jobs

    def download_job_logs(self, job_id: int) -> str:
        """Download complete logs for a specific job.

        Args:
            job_id: The job ID.

        Returns:
            Complete log content as string.

        Raises:
            GitHubError: If API call fails or no logs available.
            GitHubTimeoutError: If command times out.
        """
        from .exceptions import GitHubError, GitHubTimeoutError

        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{self.repo}/actions/jobs/{job_id}/logs"],
                capture_output=True,
                check=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise GitHubTimeoutError(f"Timeout downloading logs for job {job_id}") from e
        except subprocess.CalledProcessError as e:
            # Decode stderr if it's bytes
            stderr = (
                e.stderr.decode("utf-8", errors="replace")
                if isinstance(e.stderr, bytes)
                else str(e.stderr)
            )
            raise GitHubError(f"Failed to download job logs: {stderr}") from e

        # Decode bytes to string
        logs = result.stdout.decode("utf-8", errors="replace")

        if not logs.strip():
            raise GitHubError(f"No log content available for job {job_id}")

        return logs

    def extract_error_blocks(self, logs: str, context_lines: int = 3) -> list[ErrorBlock]:
        """Extract error blocks with context from logs.

        Args:
            logs: Complete log content.
            context_lines: Number of lines before/after error to include.

        Returns:
            List of ErrorBlock objects containing errors and context.
        """
        lines = logs.splitlines()
        error_blocks = []

        i = 0
        while i < len(lines):
            line = lines[i]

            # Check if this line contains an error indicator
            if self._is_error_line(line):
                # Calculate context range
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)

                # Extract block content
                block_lines = lines[start:end]
                content = "\n".join(block_lines)

                error_blocks.append(
                    ErrorBlock(
                        content=content,
                        line_number=i + 1,  # 1-indexed
                        context_before=i - start,
                        context_after=end - i - 1,
                    )
                )

                # Skip past this block to avoid overlapping extracts
                i = end
            else:
                i += 1

        return error_blocks

    def _is_error_line(self, line: str) -> bool:
        """Check if a line indicates an error.

        Args:
            line: Log line to check.

        Returns:
            True if line contains error indicators.
        """
        error_indicators = [
            "##[error]",
            "Exit status",
            "Error:",
            "error:",
            "ERROR:",
            "FAIL",
            "Failed",
            "AssertionError",
        ]

        return any(indicator in line for indicator in error_indicators)

    def download_failed_run_logs(
        self,
        run_id: int,
        output_dir: Path | None = None,
        max_lines_per_file: int = 500,
    ) -> dict[str, str]:
        """Download logs for all failed jobs in a run.

        Args:
            run_id: The workflow run ID.
            output_dir: Optional directory to save logs. If provided, logs
                       are split into chunks and saved to files.
            max_lines_per_file: Maximum lines per log file (default: 500).
                               Logs are split into multiple files to keep
                               them manageable for AI processing.

        Returns:
            Dictionary mapping job names to log content.

        Raises:
            GitHubError: If API calls fail or no logs could be retrieved.
            GitHubTimeoutError: If commands timeout.
        """
        from .exceptions import GitHubError

        failed_jobs = self.get_failed_jobs(run_id)

        if not failed_jobs:
            return {}

        logs_by_job = {}
        download_errors = []

        for job in failed_jobs:
            try:
                logs = self.download_job_logs(job.id)
                logs_by_job[job.name] = logs

                # Save to file if output_dir provided
                if output_dir:
                    self._save_logs_chunked(
                        logs=logs,
                        job_name=job.name,
                        output_dir=output_dir,
                        max_lines_per_file=max_lines_per_file,
                    )

            except Exception as e:
                # Track errors but continue with other jobs
                download_errors.append(f"{job.name}: {str(e)}")
                continue

        # If all downloads failed, raise an error
        if not logs_by_job and failed_jobs:
            error_msg = (
                f"Failed to download logs for {len(failed_jobs)} jobs: {'; '.join(download_errors)}"
            )
            raise GitHubError(error_msg)

        return logs_by_job

    def _save_logs_chunked(
        self,
        logs: str,
        job_name: str,
        output_dir: Path,
        max_lines_per_file: int,
    ) -> None:
        """Save logs split into manageable chunks.

        Instead of saving one huge file, split into:
        job_name/
          .jobname (original name metadata)
          1.log (500 lines)
          2.log (500 lines)
          3.log (remaining lines)

        Args:
            logs: Complete log content.
            job_name: Original name of the job (may contain spaces/slashes).
            output_dir: Base output directory.
            max_lines_per_file: Maximum lines per file.
        """
        # Create job directory with sanitized name
        safe_name = job_name.replace(" ", "_").replace("/", "_")
        job_dir = output_dir / safe_name
        job_dir.mkdir(parents=True, exist_ok=True)

        # Save original job name for display purposes
        (job_dir / ".jobname").write_text(job_name, encoding="utf-8")

        # Split logs into lines
        lines = logs.splitlines(keepends=True)

        # Write chunks
        chunk_num = 1
        for i in range(0, len(lines), max_lines_per_file):
            chunk = lines[i : i + max_lines_per_file]
            chunk_file = job_dir / f"{chunk_num}.log"
            chunk_file.write_text("".join(chunk), encoding="utf-8")
            chunk_num += 1

    def get_error_summary(self, run_id: int, max_errors_per_job: int = 5) -> str:
        """Get a summary of errors from all failed jobs.

        Args:
            run_id: The workflow run ID.
            max_errors_per_job: Maximum error blocks to include per job.

        Returns:
            Formatted string with error summary.

        Raises:
            GitHubError: If API calls fail.
            GitHubTimeoutError: If commands timeout.
        """
        failed_jobs = self.get_failed_jobs(run_id)

        if not failed_jobs:
            return "No failed jobs found."

        summary_parts = [f"Failed jobs: {len(failed_jobs)}\n"]

        for job in failed_jobs:
            try:
                logs = self.download_job_logs(job.id)
                error_blocks = self.extract_error_blocks(logs)

                summary_parts.append(f"\n## {job.name}")
                summary_parts.append(f"Errors found: {len(error_blocks)}\n")

                # Show first N error blocks
                for block in error_blocks[:max_errors_per_job]:
                    summary_parts.append(f"```\n{block.content}\n```\n")

                if len(error_blocks) > max_errors_per_job:
                    remaining = len(error_blocks) - max_errors_per_job
                    summary_parts.append(f"... and {remaining} more errors\n")

            except Exception as e:
                summary_parts.append(f"\nError downloading logs: {e}\n")

        return "\n".join(summary_parts)
