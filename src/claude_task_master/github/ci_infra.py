"""Detect CI failures that belong to the platform rather than to the diff.

A workflow run can go red without any code in the PR being at fault: the
runner pool is saturated and queued jobs are killed, a runner is reclaimed
mid-job, the whole run is cancelled by an outage. Those failures are
indistinguishable from a real one at the level of ``gh pr checks`` — both
report a failing check with a job URL — but no edit to the branch can fix
them, so handing them to a fix agent burns an expensive session to produce
no commit, and the poll that follows re-reads the very same run.

The signal used here is deliberately narrow: **a job that recorded zero
steps never executed anything**. GitHub populates ``steps`` as a job runs,
so an empty list means the job was killed while queued or lost its runner
before the first step. A job that genuinely failed always has at least the
setup steps, one of them concluding ``failure``.
"""

from __future__ import annotations

import json
import subprocess

# Conclusions that make a check show up red on the PR. ``cancelled`` is
# included on purpose: a run cancelled by an outage is exactly the case this
# module exists to name, and the caller has already established that the
# check is being reported as a failure.
_UNSUCCESSFUL = frozenset({"failure", "cancelled", "timed_out", "action_required"})


class CIInfraDetector:
    """Decides whether a run's red jobs ever got to execute a step."""

    def __init__(self, repo: str, timeout: int = 60):
        """Initialize the detector.

        Args:
            repo: Repository in format 'owner/repo'.
            timeout: Command timeout in seconds.
        """
        self.repo = repo
        self.timeout = timeout

    def never_ran(self, run_id: int) -> bool:
        """Return True when every unsuccessful job in the run executed no step.

        A single red job with recorded steps is enough to make this False:
        something in that job actually ran and failed, which is the fix
        agent's business.

        Args:
            run_id: The workflow run ID.

        Returns:
            True when the run's failures are infrastructural. False when any
            red job ran, when the run has no red jobs, or when the job list
            cannot be read — an unreadable run must not be waved through as
            "not the diff's fault".
        """
        jobs = self._jobs(run_id)
        if jobs is None:
            return False

        unsuccessful = [job for job in jobs if (job.get("conclusion") or "") in _UNSUCCESSFUL]
        if not unsuccessful:
            return False

        return all(not job.get("steps") for job in unsuccessful)

    def _jobs(self, run_id: int) -> list[dict] | None:
        """Fetch the run's jobs, or None when the API call fails.

        Args:
            run_id: The workflow run ID.

        Returns:
            The parsed job objects, or None if they could not be fetched.
        """
        try:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "--paginate",
                    "--jq",
                    ".jobs[]",
                    f"repos/{self.repo}/actions/runs/{run_id}/jobs",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=self.timeout,
            )
        except (subprocess.SubprocessError, OSError):
            return None

        try:
            return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        except json.JSONDecodeError:
            return None


__all__ = ["CIInfraDetector"]
