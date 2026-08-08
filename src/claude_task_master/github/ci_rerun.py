"""Re-run the failed jobs of a workflow run.

The counterpart to :mod:`.ci_infra`: once a red run is known to be the
platform's fault, the only useful action is to ask GitHub to run those jobs
again. Re-running is also the right move for a red run that a fix session
looked at and declined to change — a push is what re-triggers CI, so without
one the next poll would read the same run forever.

Only the failed jobs are re-run, never the whole run: the passing jobs'
results are still valid and re-running them wastes runner minutes on the very
pool that was saturated.
"""

from __future__ import annotations

import subprocess


class CIRerunner:
    """Asks GitHub to re-run the failed jobs of a run."""

    def __init__(self, repo: str, timeout: int = 60):
        """Initialize the rerunner.

        Args:
            repo: Repository in format 'owner/repo'.
            timeout: Command timeout in seconds.
        """
        self.repo = repo
        self.timeout = timeout

    def rerun_failed_jobs(self, run_id: int) -> bool:
        """Re-run the failed jobs of a run.

        Args:
            run_id: The workflow run ID.

        Returns:
            True when GitHub accepted the request, False when it refused —
            the run may be past its retention window, or already re-running.
            A refusal is an answer; the caller can report how many runs
            actually restarted.

        Raises:
            GitHubTimeoutError: The request neither succeeded nor was refused.
                Kept distinct from a refusal because the two need opposite
                handling: a refusal is final, a timeout may already have
                restarted the run server-side, and treating it as "GitHub said
                no" would block a task whose CI is in fact re-running.
        """
        from .exceptions import GitHubTimeoutError  # noqa: PLC0415

        try:
            subprocess.run(
                ["gh", "run", "rerun", str(run_id), "--failed", "--repo", self.repo],
                capture_output=True,
                text=True,
                check=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise GitHubTimeoutError(f"Timeout re-running failed jobs for run {run_id}") from e
        except (subprocess.SubprocessError, OSError):
            return False
        return True


__all__ = ["CIRerunner"]
