"""CI failure log saving mixin for PRContextManager.

Provides :class:`_PRContextCIMixin` with :meth:`save_ci_failures`.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from ..github.ci_logs import CILogDownloader

if TYPE_CHECKING:
    from ..github import GitHubClient
    from .state import StateManager


def _run_ids_from_checks(check_details: list[dict]) -> list[int]:
    """Parse the distinct workflow run IDs out of a PR's failing checks.

    Failing checks only: a passing check's run ID would otherwise be picked up
    whenever a *different* check fails.

    Args:
        check_details: The PR status' per-check dicts.

    Returns:
        Sorted run IDs, empty when none could be parsed.
    """
    from ..github.check_tolerance import is_failed_check  # noqa: PLC0415

    run_ids: set[int] = set()
    for check in check_details:
        if not is_failed_check(check):
            continue
        # `or ""`: a StatusContext's targetUrl is often null, so the key is
        # present-but-None and would break the `in` check — aborting run-ID
        # extraction for every other failing check too.
        details_url = check.get("url") or ""
        # URL format: .../actions/runs/123456/job/789
        if "/runs/" in details_url:
            try:
                run_ids.add(int(details_url.split("/runs/")[1].split("/")[0]))
            except (IndexError, ValueError):
                continue

    return sorted(run_ids)


class _PRContextCIMixin:
    """Mixin providing CI log download/save helpers to PRContextManager.

    Console access is deferred at call time so tests can patch
    ``claude_task_master.core.pr_context.console``.
    """

    state_manager: StateManager
    github_client: GitHubClient

    # ------------------------------------------------------------------
    # CI helpers
    # ------------------------------------------------------------------

    def failing_run_ids(self, pr_number: int | None) -> list[int] | None:
        """Return the workflow run IDs behind a PR's failing checks.

        One PR commonly fans out to several workflows, so a red PR usually has
        several failing runs. Callers that need to act on the failure — read
        its logs, decide whether it is infrastructural, re-run it — have to see
        all of them: acting on one and ignoring the rest reports on whichever
        run happened to sort first, not on the failure.

        Args:
            pr_number: The PR number.

        Returns:
            Sorted run IDs; ``[]`` when the PR has no failing run to act on, and
            ``None`` when GitHub could not be asked. The two must stay distinct:
            a caller that reads a failed status lookup as "no runs" turns a
            momentary API blip into "nothing to re-run", which is a block.
        """
        if pr_number is None:
            return []

        try:
            pr_status = self.github_client.get_pr_status(pr_number)
        except Exception:
            return None

        return _run_ids_from_checks(pr_status.check_details)

    def save_ci_failures(self, pr_number: int | None, *, _also_save_comments: bool = True) -> None:
        """Save CI failure logs to files for Claude to read.

        Uses CILogDownloader to fetch complete logs from only failed jobs,
        split into manageable chunks (500 lines per file).

        Args:
            pr_number: The PR number.
            _also_save_comments: Internal flag to also save comments (prevents recursion).
        """
        if pr_number is None:
            return

        # Deferred import so tests can patch pr_context.console
        import claude_task_master.core.pr_context as _pr  # noqa: PLC0415

        _console = _pr.console

        # Initialize paths outside try blocks to avoid NameError
        pr_dir = self.state_manager.get_pr_dir(pr_number)
        ci_dir = pr_dir / "ci"

        try:
            # Get the latest workflow run for this PR's branch
            pr_status = self.github_client.get_pr_status(pr_number)

            # Check if any CI checks failed. Tolerated failures (a rate-limited
            # CodeRabbit review) have no logs to download and are not defects.
            from ..github.check_tolerance import is_failed_check  # noqa: PLC0415

            has_failures = any(is_failed_check(check) for check in pr_status.check_details)

            if not has_failures:
                # CI is now passing — clear any stale failure logs
                if ci_dir.exists():
                    shutil.rmtree(ci_dir)
                return  # No failures to download

            # Extract run IDs from *failing* checks only (distinct set).
            # Avoids picking up a passing check's run ID when a different check fails.
            failing_checks = [check for check in pr_status.check_details if is_failed_check(check)]
            run_ids = _run_ids_from_checks(pr_status.check_details)

            if not run_ids:
                # Log available check URLs for debugging
                check_urls = [
                    f"{c.get('name', 'unknown')}: {c.get('url', 'N/A')}" for c in failing_checks[:3]
                ]
                _console.warning(
                    f"Could not extract run ID from failing checks. "
                    f"Sample failing checks: {', '.join(check_urls)}"
                )
                return

            _console.detail(f"Failing checks span runs: {run_ids}")

            # Get repository info for CILogDownloader
            _console.detail("Getting repository info via gh CLI...")
            repo = self.github_client._get_repo_info()
            _console.detail(f"Repository: {repo}")

            downloader = CILogDownloader(repo=repo, timeout=60)

            # Clear old CI logs only after we have confirmed run IDs and repo —
            # preserves existing data if the status/repo calls fail above.
            if ci_dir.exists():
                shutil.rmtree(ci_dir)
            ci_dir.mkdir(parents=True, exist_ok=True)

            # Every failing run, not just one of them. A PR fans out to several
            # workflows; downloading only the highest run ID silently drops the
            # workflow that actually broke whenever a *different* one also went
            # red, and hands the fix agent an empty ci/ directory to work from.
            total_jobs = 0
            for run_id in run_ids:
                _console.detail(f"Downloading CI logs for run {run_id} from {repo}...")
                try:
                    # Download and save logs chunked (20KB per file ~5K tokens).
                    # One directory per run: job names are only unique *within* a
                    # workflow, and a repo whose workflows each define a "typecheck"
                    # job would otherwise have the last download overwrite the rest —
                    # leaving the agent reading one workflow's logs under a name that
                    # implies all of them.
                    logs = downloader.download_failed_run_logs(
                        run_id=run_id,
                        output_dir=ci_dir / f"run-{run_id}",
                        max_chars_per_file=20_000,
                    )
                except Exception as e:
                    # One unreadable run must not cost us the others' logs.
                    _console.detail(f"No logs for run {run_id}: {e}")
                    continue
                total_jobs += len(logs)

            if total_jobs:
                _console.detail(f"Downloaded CI logs to {ci_dir} ({total_jobs} jobs)")
            else:
                # Checks are red but no GitHub Actions job produced a log. Either
                # the failures are external (CodeRabbit and friends), or no job
                # ever got far enough to write one — which is what a saturated or
                # broken runner pool looks like.
                _console.warning(
                    f"CI checks failed but no GitHub Actions job logs available for "
                    f"runs {run_ids}. Failures may be from external checks "
                    f"(CodeRabbit, etc.) or from jobs that never started."
                )

        except Exception as e:
            import traceback  # noqa: PLC0415

            _console.warning(f"Could not save CI failures: {e}")
            _console.detail(f"Full error: {traceback.format_exc()}")

        # Also save comments when saving CI failures (for complete context)
        # Do this AFTER saving CI failures to ensure CI files exist first
        if _also_save_comments:
            self.save_pr_comments(pr_number, _also_save_ci=False)  # type: ignore[attr-defined]


__all__ = ["_PRContextCIMixin", "_run_ids_from_checks"]
