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

    # Post replies to comments using resolution file (if comments were addressed)
    if saved_comment_count > 0:
        pr_context.post_comment_replies(pr_number)

    return True
