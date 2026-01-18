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

This PR has merge conflicts that need to be resolved.

1. Run `git fetch origin` to get latest changes
2. Run `git merge origin/main` (or the base branch)
3. Resolve any conflicts in the affected files
4. Run tests to verify the merge didn't break anything
5. Commit the merge resolution""")
        has_actionable_work = True

    # Always download CI failures if CI failed
    if ci_failed:
        console.error("CI Failed - Downloading failure logs...")
        pr_context.save_ci_failures(pr_number)
        ci_path = f"{pr_dir}/ci/"
        task_sections.append(f"""## CI Failures

**Read the CI failure logs from:** `{ci_path}`

Use Glob to find all .txt files, then Read each one to understand the errors.

**IMPORTANT:** Fix ALL CI failures, even if they seem unrelated to your current work.
Your job is to keep CI green. Pre-existing issues, flaky tests, lint errors - fix them all.

- Read ALL files in the ci/ directory
- Understand ALL error messages (lint, tests, types, etc.)
- Fix everything that's failing - don't skip anything""")
        has_actionable_work = True

    # Always download comments if there are unresolved threads
    saved_comment_count = 0
    if comment_count > 0:
        console.warning(f"{comment_count} unresolved comment(s) - Downloading...")
        saved_comment_count = pr_context.save_pr_comments(pr_number)
        console.detail(f"Saved {saved_comment_count} actionable comment(s) for review")

        if saved_comment_count > 0:
            comments_path = f"{pr_dir}/comments/"
            resolve_json_path = f"{pr_dir}/resolve-comments.json"
            task_sections.append(f"""## Review Comments

**Read the review comments from:** `{comments_path}`

Use Glob to find all .txt files, then Read each one to understand the feedback.

For each comment:
- Make the requested change, OR
- Explain why it's not needed

After addressing comments, create a resolution summary file at: `{resolve_json_path}`

**Resolution file format:**
```json
{{
  "pr": {pr_number},
  "resolutions": [
    {{
      "thread_id": "THREAD_ID_FROM_COMMENT_FILE",
      "action": "fixed|explained|skipped",
      "message": "Brief explanation of what was done"
    }}
  ]
}}
```

Copy the Thread ID from each comment file into the resolution JSON.

**IMPORTANT: DO NOT resolve threads directly using GitHub GraphQL mutations.**
The orchestrator will handle thread resolution automatically after you create the resolution file.""")
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

## Instructions

1. Read ALL relevant files (CI logs and/or comments)
2. Fix ALL issues found
3. Run tests/lint locally to verify everything passes
4. Commit and push the fixes

After fixing everything, end with: TASK COMPLETE"""

    console.info("Running agent to fix all issues...")
    current_branch = get_current_branch()
    agent.run_work_session(
        task_description=task_description,
        context="",
        model_override=ModelType.OPUS,
        required_branch=current_branch,
    )

    # Post replies to comments using resolution file (if comments were addressed)
    if saved_comment_count > 0:
        pr_context.post_comment_replies(pr_number)

    return True
