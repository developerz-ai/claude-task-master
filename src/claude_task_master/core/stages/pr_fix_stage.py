"""PRFixStageMixin — CI-failure handling and combined CI+comments task builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import console
from ..agent import ModelType
from ..shutdown import interruptible_sleep
from .ci_stage import _CIStage

if TYPE_CHECKING:
    from ..state import TaskState


class _PRFixStage(_CIStage):
    """Mixin: handle CI failures and build CI+review combined task prompts."""

    def handle_ci_failed_stage(self, state: TaskState) -> int | None:
        """Handle CI failure - run agent to fix issues.

        This method now also fetches PR comments (from CodeRabbit, reviewers, etc.)
        when saving CI failures, so the agent can fix BOTH CI issues AND address
        review comments in a single step.
        """
        console.info("CI failed - running agent to fix...")

        # Cap consecutive CI-fix cycles to avoid an infinite fix loop
        state.ci_fix_attempts += 1
        if state.ci_fix_attempts > self.MAX_CI_FIX_ATTEMPTS:
            console.error(
                f"CI failed {state.ci_fix_attempts} times — blocking, manual intervention required"
            )
            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1
        self.state_manager.save_state(state)

        # Save CI failure logs (this also saves PR comments via _also_save_comments=True)
        self.pr_context.save_ci_failures(state.current_pr)

        # Check what feedback we have (CI failures and/or comments)
        has_ci, has_comments, pr_dir_path = self.pr_context.get_combined_feedback(state.current_pr)

        # Build combined task description
        task_description = self._build_combined_ci_comments_task(
            state.current_pr, has_ci, has_comments, pr_dir_path
        )

        # Run agent with Opus for complex debugging
        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        required_branch = self._get_pr_head_branch(state)
        # Fix an EXISTING PR: push the fix to re-trigger CI, never open a new PR
        # or rebase (push_only routes through _build_push_only_execution, which
        # forbids rebasing already-reviewed commits).
        self.agent.run_work_session(
            task_description=task_description,
            context=context,
            model_override=ModelType.OPUS,
            required_branch=required_branch,
            create_pr=False,
            push_only=True,
        )

        # Wait for CI to start after push
        console.info("Waiting 60s for CI to start...")
        if not interruptible_sleep(60):
            return None

        state.workflow_stage = "waiting_ci"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None

    def _build_combined_ci_comments_task(
        self,
        pr_number: int | None,
        has_ci: bool,
        has_comments: bool,
        pr_dir_path: str,
    ) -> str:
        """Build a combined task description for CI failures and review comments.

        This ensures that both CI failures AND review comments are addressed in
        a single agent session, avoiding the need for multiple fix cycles.

        Args:
            pr_number: The PR number.
            has_ci: Whether there are CI failure logs.
            has_comments: Whether there are review comments.
            pr_dir_path: Path to the PR directory.

        Returns:
            Task description string for the agent.
        """
        ci_path = f"{pr_dir_path}/ci/" if pr_dir_path else ".claude-task-master/debugging/"
        comments_path = (
            f"{pr_dir_path}/comments/" if pr_dir_path else ".claude-task-master/debugging/"
        )
        resolve_json_path = (
            f"{pr_dir_path}/resolve-comments.json"
            if pr_dir_path
            else ".claude-task-master/debugging/resolve-comments.json"
        )

        # Build the appropriate task description based on what feedback exists
        if has_ci and has_comments:
            # Both CI failures and comments - handle together!
            return f"""CI has failed for PR #{pr_number} AND there are review comments to address.

**IMPORTANT: Fix BOTH CI failures AND address review comments in this session.**
This is more efficient than fixing them separately.

## Step 1: Read ALL Feedback

**CI Failure logs:** `{ci_path}`
**Review comments:** `{comments_path}`

Use Glob to find all .txt files in both directories, then Read each one.

## Step 2: Fix CI Failures (Priority 1)

- Read ALL files in the ci/ directory
- Understand ALL error messages (lint, tests, types, etc.)
- Fix everything that's failing - don't skip anything
- Pre-existing issues, flaky tests, lint errors - fix them all

## Step 3: Address Review Comments (Priority 2)

- Read ALL comment files in the comments/ directory
- For each comment:
  - Make the requested change, OR
  - Explain why it's not needed

## Step 4: Verify, Commit, and Push

1. Run tests/lint locally to verify ALL passes
2. Commit all fixes together with a descriptive message
3. Push to update the existing PR: `git push origin HEAD` (CI re-runs on push). Do NOT rebase or force-push — it rewrites already-reviewed commits and breaks the PR's review threads. If push is rejected: `git pull --rebase origin HEAD`, resolve conflicts, re-test, then push.
4. Create a resolution summary file at: `{resolve_json_path}`

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
The orchestrator will handle thread resolution automatically after you create the resolution file.

After fixing ALL CI issues AND addressing ALL comments, end with: TASK COMPLETE"""

        elif has_ci:
            # Only CI failures (no comments)
            return f"""CI has failed for PR #{pr_number}.

**Read the CI failure logs from:** `{ci_path}`

Use Glob to find all .txt files, then Read each one to understand the errors.

**IMPORTANT:** Fix ALL CI failures, even if they seem unrelated to your current work.
Your job is to keep CI green. Pre-existing issues, flaky tests, lint errors - fix them all.

Please:
1. Read ALL files in the ci/ directory
2. Understand ALL error messages (lint, tests, types, etc.)
3. Fix everything that's failing - don't skip anything
4. Run tests/lint locally to verify ALL passes
5. Commit fixes with a descriptive message
6. Push to update the existing PR: `git push origin HEAD` (CI re-runs on push). Do NOT rebase or force-push — it rewrites already-reviewed commits and breaks the PR's review threads. If push is rejected: `git pull --rebase origin HEAD`, resolve, re-test, then push.

After fixing, end with: TASK COMPLETE"""

        elif has_comments:
            # Only comments (rare case - CI passed but called with comments only)
            return f"""PR #{pr_number} has review comments to address.

**Read the review comments from:** `{comments_path}`

Use Glob to find all .txt files, then Read each one to understand the feedback.

Please:
1. Read ALL comment files in the comments/ directory
2. For each comment:
   - Make the requested change, OR
   - Explain why it's not needed
3. Run tests to verify
4. Commit fixes with a descriptive message
5. Push to update the existing PR: `git push origin HEAD` (CI re-runs on push). Do NOT rebase or force-push — it rewrites already-reviewed commits and breaks the PR's review threads. If push is rejected: `git pull --rebase origin HEAD`, resolve, re-test, then push.
6. Create a resolution summary file at: `{resolve_json_path}`

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
The orchestrator will handle thread resolution automatically after you create the resolution file.

After addressing ALL comments and creating the resolution file, end with: TASK COMPLETE"""

        else:
            # Neither CI failures nor comments (shouldn't happen in ci_failed stage)
            return f"""PR #{pr_number} needs attention.

Please check the PR status and ensure everything is working correctly.
Run tests/lint locally to verify.

After verifying, end with: TASK COMPLETE"""
