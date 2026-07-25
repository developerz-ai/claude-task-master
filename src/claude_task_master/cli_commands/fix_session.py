"""Fix session logic for fix-pr command."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from ..core import console
from ..core.agent import AgentWrapper, ModelType

if TYPE_CHECKING:
    from ..core.pr_context import PRContextManager
    from ..core.state import StateManager
    from ..github import GitHubClient


def get_current_branch() -> str | None:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def pending_changes_summary(max_lines: int = 20) -> str:
    """Short listing of uncommitted changes, or "" when clean/unreadable.

    Fails open on purpose: an unreadable repo must not stall a merge, only a
    *definite* dirty tree should.
    """
    try:
        # rstrip only: a leading space is the status column (" M path"), and
        # stripping it misaligns the first line against every other one.
        out = subprocess.run(
            ["git", "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.rstrip()
    except Exception:
        return ""
    if not out.strip():
        return ""
    lines = out.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... and {len(lines) - max_lines} more"]
    return "\n".join(lines)


def fix_session_undelivered_reason(branch: str | None) -> str | None:
    """Why a fix session didn't deliver: uncommitted work, or an unpushed fix.

    The CLI mirror of ``_GitOps._fix_session_unfinished_reason``. It stays a
    plain function rather than sharing that mixin because ``fix-pr`` runs
    without a stage handler — but the contract it enforces is identical, and it
    matters for the same reason: replying to review threads marks them resolved
    on GitHub, so doing that for a fix still sitting in the working tree tells
    the merge loop the review is handled when it is not.

    Unknown states (unreadable repo, no upstream) return None — the caller
    proceeds rather than refusing to work in a repo it cannot measure.
    """

    def _git(*args: str, timeout: int = 30) -> str | None:
        try:
            return subprocess.run(
                ["git", *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            ).stdout.strip()
        except Exception:
            return None

    if _git("status", "--porcelain", timeout=15):
        return "uncommitted changes left behind"
    if branch and _git("fetch", "origin", branch, timeout=120) is not None:
        unpushed = _git("rev-list", "--count", f"origin/{branch}..HEAD")
        if unpushed and unpushed.isdigit() and int(unpushed) > 0:
            return f"{unpushed} commit(s) never pushed"
    return None


def run_fix_session(
    agent: AgentWrapper,
    github_client: GitHubClient,
    state_manager: StateManager,
    pr_context: PRContextManager,
    pr_number: int,
    ci_failed: bool,
    comment_count: int,
    has_conflicts: bool = False,
) -> bool:
    """Run agent session to fix CI failures, comments, and/or merge conflicts.

    Downloads both CI failures and comments (if present) so the agent can
    address everything in one session.

    Args:
        agent: Agent wrapper for running work sessions.
        github_client: GitHub client for API calls.
        state_manager: State manager for persistence.
        pr_context: PR context manager for saving CI logs and comments.
        pr_number: PR number being fixed.
        ci_failed: Whether CI has failed.
        comment_count: Number of unresolved comments.
        has_conflicts: Whether there are merge conflicts.

    Returns:
        True if agent ran, False if nothing actionable was found.
    """
    pr_dir = state_manager.get_pr_dir(pr_number)
    task_sections = []
    has_actionable_work = False

    # Handle merge conflicts
    if has_conflicts:
        console.error("Merge Conflicts - Agent will resolve...")
        task_sections.append("""## Merge Conflicts
`git fetch origin` → `git merge origin/main` → resolve conflicts → run tests → commit.""")
        has_actionable_work = True

    # Always download CI failures if CI failed
    if ci_failed:
        console.error("CI Failed - Downloading failure logs...")
        pr_context.save_ci_failures(pr_number, _also_save_comments=False)
        ci_path = f"{pr_dir}/ci/"
        task_sections.append(f"""## CI Failures
Logs: `{ci_path}` (Glob `*.txt`, Read only failing files).
Fix ALL failures — tests, lint, types. Pre-existing issues count too.""")
        has_actionable_work = True

    # Always download comments if there are unresolved threads
    saved_comment_count = 0
    if comment_count > 0:
        console.warning(f"{comment_count} unresolved comment(s) - Downloading...")
        saved_comment_count = pr_context.save_pr_comments(pr_number, _also_save_ci=False)
        console.detail(f"Saved {saved_comment_count} actionable comment(s) for review")

        if saved_comment_count > 0:
            comments_path = f"{pr_dir}/comments/"
            resolve_json_path = f"{pr_dir}/resolve-comments.json"
            task_sections.append(f"""## Review Comments
Comments: `{comments_path}` (Glob `*.txt`, Read each).
For each: fix it OR explain why not.

Write resolution file: `{resolve_json_path}`
```json
{{"pr": {pr_number}, "resolutions": [
  {{"thread_id": "FROM_COMMENT_FILE", "action": "fixed|explained|skipped", "message": "..."}}
]}}
```
DO NOT resolve threads via GraphQL — orchestrator handles that from the JSON.""")
            has_actionable_work = True

    # Guard against loops when nothing actionable
    if not has_actionable_work:
        if comment_count > 0 and saved_comment_count == 0:
            console.warning(
                "No actionable comments to address (may be bot status updates or already addressed)."
            )
            console.warning("Unresolved threads may need manual review on GitHub.")
        return False

    # Build combined task description
    task_description = f"""PR #{pr_number} needs fixes.

{chr(10).join(task_sections)}

Read → fix all → test/lint → commit → push. End with: TASK COMPLETE"""

    console.info("Running agent to fix all issues...")
    current_branch = get_current_branch()
    agent.run_work_session(
        task_description=task_description,
        context="",
        model_override=ModelType.OPUS,
        required_branch=current_branch,
        create_pr=False,
        push_only=True,
    )

    # Verify the session delivered before telling GitHub the review is handled.
    # post_comment_replies resolves the threads; doing that for a fix still in
    # the working tree walks the merge loop onto the previous push's green CI.
    undelivered = fix_session_undelivered_reason(current_branch)
    if undelivered:
        console.warning(f"Fix session left work undelivered ({undelivered})")
        console.detail("Not resolving review threads — the fix has not reached the PR")
        return False

    # Post replies to comments using resolution file (if comments were addressed)
    if saved_comment_count > 0:
        pr_context.post_comment_replies(pr_number)

    return True
