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

Some of those failures clear on a re-run (a saturated pool) and some never
will (Actions disabled for the account, a billing lock). GitHub says which
in a check-run annotation — *"The job was not started because your account
is locked due to a billing issue."* — so :meth:`CIInfraDetector.external_block_reason`
reads it, and :func:`post_external_block_notice` leaves that sentence on the
PR **once** as the explanation for stopping. Re-running a permanently
blocked run is pure waste, and stopping without saying why leaves a human
to rediscover it from the logs.
"""

from __future__ import annotations

import json
import subprocess

# Annotation text that means no re-run will ever help: the account or repo is
# not allowed to run jobs at all. Kept narrow and phrase-based — a generic
# "error" match here would mistake an ordinary failure for a permanent block
# and stop a run that a re-run would have rescued.
_PERMANENT_PHRASES = (
    "account is locked",
    "billing issue",
    "payment",
    "spending limit",
    "actions is disabled",
    "actions are disabled",
    "workflows are disabled",
    "has been suspended",
    "quota",
)

# Cap on annotation lookups per run: one API call per stalled job, and a
# saturated pool can strand dozens of them. The first few carry the same
# platform-side message as the rest.
MAX_ANNOTATION_JOBS = 3

# Marks claudetm's own "CI is externally blocked" comment so a later cycle, a
# resume, or a second instance recognises it and does not post a duplicate.
# Invisible in rendered markdown.
NOTICE_MARKER = "<!-- claudetm:ci-externally-blocked -->"

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

    def external_block_reason(self, run_id: int) -> str | None:
        """Return GitHub's own reason for refusing to run the jobs, if any.

        Only a *permanent* refusal counts — an account locked for billing, a
        repo whose Actions are disabled. Those are worth recognising on sight
        because the re-run budget spent on them is guaranteed waste, and the
        message is the only thing that tells a human what to go and fix.

        A queue kill or a lost runner produces no such annotation and returns
        None, keeping the ordinary bounded re-run path.

        Args:
            run_id: The workflow run ID.

        Returns:
            The annotation text, or None when nothing says the block is
            permanent — including when the run or its annotations cannot be
            read, since "unknown" must never be reported as "give up".
        """
        jobs = self._jobs(run_id) or []
        stalled = [
            job
            for job in jobs
            if (job.get("conclusion") or "") in _UNSUCCESSFUL and not job.get("steps")
        ]
        for job in stalled[:MAX_ANNOTATION_JOBS]:
            for message in self._annotations(job):
                lowered = message.lower()
                if any(phrase in lowered for phrase in _PERMANENT_PHRASES):
                    return message.strip()
        return None

    def _annotations(self, job: dict) -> list[str]:
        """Fetch a job's check-run annotation messages, or [] when unreadable."""
        url = job.get("check_run_url") or ""
        if "/repos/" in url:
            path = "repos/" + url.split("/repos/", 1)[1]
        else:
            # The jobs API always carries check_run_url; the job id is only a
            # fallback for a trimmed payload (chiefly in tests).
            path = f"repos/{self.repo}/check-runs/{job.get('id')}"
        try:
            result = subprocess.run(
                ["gh", "api", "--paginate", "--jq", ".[].message", f"{path}/annotations"],
                capture_output=True,
                text=True,
                check=True,
                timeout=self.timeout,
            )
        except (subprocess.SubprocessError, OSError):
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]

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


def format_external_block_comment(
    run_ids: list[int], summary: str, reason: str | None = None
) -> str:
    """Build the PR comment that explains why claudetm stopped.

    Args:
        run_ids: The failing workflow runs that no diff can turn green.
        summary: One sentence saying what was tried and what it showed.
        reason: GitHub's own words for the refusal, when it gave any.

    Returns:
        Markdown body, carrying :data:`NOTICE_MARKER` so it is recognisable.
    """
    runs = ", ".join(f"`{run_id}`" for run_id in run_ids) or "the failing checks"
    quoted = f"\n> {reason}\n" if reason else ""
    return (
        f"{NOTICE_MARKER}\n"
        "### CI is red for reasons this pull request cannot fix\n\n"
        f"{summary} Affected run(s): {runs}.\n"
        f"{quoted}\n"
        "**claudetm has stopped rather than spend more agent sessions here.** Every session "
        "on this failure reaches the same conclusion — there is nothing in the diff to "
        "change — and each one costs a full model run.\n\n"
        "To continue: clear the platform-side problem (billing, Actions entitlement, runner "
        "availability), re-run the failed jobs, then `claudetm resume -f`."
    )


def _notice_exists(repo: str, pr_number: int, timeout: int) -> bool | None:
    """Whether the block notice is already on the PR (None = could not tell)."""
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "--paginate",
                "--jq",
                ".[].body",
                f"repos/{repo}/issues/{pr_number}/comments",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return NOTICE_MARKER in result.stdout


def post_external_block_notice(
    repo: str,
    pr_number: int,
    run_ids: list[int],
    summary: str,
    reason: str | None = None,
    timeout: int = 60,
) -> bool:
    """Leave the "CI is externally blocked" explanation on the PR, once.

    The block it explains is re-entered by every forced resume, so posting
    unconditionally would grow a column of identical comments. Existing
    comments are checked first, and an unreadable comment list counts as
    "already posted" — a missing explanation is a smaller harm than a comment
    per cycle.

    Args:
        repo: Repository in 'owner/repo' form.
        pr_number: The pull request number.
        run_ids: The failing workflow runs.
        summary: One sentence saying what was tried and what it showed.
        reason: GitHub's own words for the refusal, when it gave any.
        timeout: Per-command timeout in seconds.

    Returns:
        True when a comment was posted by this call, False otherwise.
    """
    if _notice_exists(repo, pr_number, timeout) is not False:
        return False
    try:
        subprocess.run(
            [
                "gh",
                "pr",
                "comment",
                str(pr_number),
                "--repo",
                repo,
                "--body",
                format_external_block_comment(run_ids, summary, reason),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return True


__all__ = [
    "MAX_ANNOTATION_JOBS",
    "NOTICE_MARKER",
    "CIInfraDetector",
    "format_external_block_comment",
    "post_external_block_notice",
]
