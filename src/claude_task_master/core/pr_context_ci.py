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
            run_ids: set[int] = set()
            for check in failing_checks:
                # `or ""`: a StatusContext's targetUrl is often null, so the
                # key is present-but-None and would break the `in` check —
                # aborting run-ID extraction for every other failing check too.
                details_url = check.get("url") or ""
                # URL format: .../actions/runs/123456/job/789
                if "/runs/" in details_url:
                    try:
                        run_ids.add(int(details_url.split("/runs/")[1].split("/")[0]))
                    except (IndexError, ValueError):
                        continue

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

            run_id = max(run_ids)  # Use the most-recent run among failing ones
            _console.detail(
                f"Extracted run ID {run_id} from failing checks (candidates: {sorted(run_ids)})"
            )

            # Get repository info for CILogDownloader
            _console.detail("Getting repository info via gh CLI...")
            repo = self.github_client._get_repo_info()
            _console.detail(f"Repository: {repo}")

            downloader = CILogDownloader(repo=repo, timeout=60)

            # Download failed job logs using CILogDownloader
            _console.detail(f"Downloading CI logs for run {run_id} from {repo}...")

            # Clear old CI logs only after we have confirmed run_id and repo —
            # preserves existing data if the status/repo calls fail above.
            if ci_dir.exists():
                shutil.rmtree(ci_dir)
            ci_dir.mkdir(parents=True, exist_ok=True)

            # Download and save logs chunked (20KB per file ~5K tokens)
            logs = downloader.download_failed_run_logs(
                run_id=run_id,
                output_dir=ci_dir,
                max_chars_per_file=20_000,
            )

            if logs:
                _console.detail(f"Downloaded CI logs to {ci_dir} ({len(logs)} jobs)")
            else:
                # Checks failed but no GitHub Actions jobs failed (e.g., external checks)
                _console.warning(
                    f"CI checks failed but no GitHub Actions job logs available for run {run_id}. "
                    f"Failures may be from external checks (CodeRabbit, etc.)"
                )

        except Exception as e:
            import traceback  # noqa: PLC0415

            _console.warning(f"Could not save CI failures: {e}")
            _console.detail(f"Full error: {traceback.format_exc()}")

        # Also save comments when saving CI failures (for complete context)
        # Do this AFTER saving CI failures to ensure CI files exist first
        if _also_save_comments:
            self.save_pr_comments(pr_number, _also_save_ci=False)  # type: ignore[attr-defined]


__all__ = ["_PRContextCIMixin"]
