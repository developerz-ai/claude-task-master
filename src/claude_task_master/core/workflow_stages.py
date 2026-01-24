"""Workflow Stage Handlers - Handle each stage of the PR workflow."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING

from . import console
from .agent import ModelType
from .config_loader import get_config
from .shutdown import interruptible_sleep

if TYPE_CHECKING:
    from ..github import GitHubClient
    from .agent import AgentWrapper
    from .orchestrator import WebhookEmitter
    from .pr_context import PRContextManager
    from .state import StateManager, TaskState


class WorkflowStageHandler:
    """Handles individual workflow stages in the PR lifecycle.

    Workflow stages:
    1. working → Implement tasks
    2. pr_created → Create/update PR
    3. waiting_ci → Poll CI status
    4. ci_failed → Fix CI failures
    5. waiting_reviews → Wait for reviews
    6. addressing_reviews → Address review feedback
    7. ready_to_merge → Merge PR
    8. merged → Move to next task
    """

    # CI polling configuration
    CI_POLL_INTERVAL = 10  # seconds between CI status checks
    REVIEW_DELAY = 5  # seconds to wait after CI passes before checking reviews

    @staticmethod
    def _get_check_name(check: dict) -> str:
        """Get check name from either CheckRun or StatusContext.

        CheckRun has 'name' field, StatusContext has 'context' field.
        """
        return str(check.get("name") or check.get("context", "unknown"))

    @staticmethod
    def _get_current_branch() -> str | None:
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

    @staticmethod
    def _checkout_branch(branch: str, allow_recovery: bool = True) -> bool:
        """Checkout to a branch with optional recovery from dirty state.

        Args:
            branch: Branch name to checkout.
            allow_recovery: If True, attempts recovery on failure (stash changes).

        Returns:
            True if successful, False otherwise.
        """
        try:
            subprocess.run(
                ["git", "checkout", branch],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "pull"],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            if not allow_recovery:
                console.warning(f"Failed to checkout {branch}: {e}")
                return False

            # Try recovery: stash any local changes and retry
            console.info("Checkout failed, attempting recovery...")
            try:
                # Check if there are uncommitted changes
                status = subprocess.run(
                    ["git", "status", "--porcelain"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if status.stdout.strip():
                    console.info("Stashing uncommitted changes...")
                    subprocess.run(
                        ["git", "stash", "push", "-m", "claudetm: auto-stash before checkout"],
                        check=True,
                        capture_output=True,
                        text=True,
                    )

                # Retry checkout
                subprocess.run(
                    ["git", "checkout", branch],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["git", "pull"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                console.success("Recovery successful (changes stashed)")
                return True
            except subprocess.CalledProcessError as recovery_error:
                console.warning(f"Failed to checkout {branch} after recovery: {recovery_error}")
                return False

    def __init__(
        self,
        agent: AgentWrapper,
        state_manager: StateManager,
        github_client: GitHubClient,
        pr_context: PRContextManager,
        webhook_emitter: WebhookEmitter | None = None,
    ):
        """Initialize stage handler.

        Args:
            agent: The agent wrapper for running queries.
            state_manager: The state manager for persistence.
            github_client: GitHub client for PR operations.
            pr_context: PR context manager for comments/CI logs.
            webhook_emitter: Optional webhook emitter for CI events.
        """
        self.agent = agent
        self.state_manager = state_manager
        self.github_client = github_client
        self.pr_context = pr_context
        self.webhook_emitter = webhook_emitter

    def _emit_ci_event(
        self,
        event_type: str,
        pr_number: int | None,
        branch: str,
        failure_reason: str | None = None,
    ) -> None:
        """Emit a CI webhook event (ci.passed or ci.failed).

        Args:
            event_type: The event type ("ci.passed" or "ci.failed").
            pr_number: The PR number.
            branch: The branch name.
            failure_reason: Optional failure reason (for ci.failed events).
        """
        if self.webhook_emitter is None:
            return

        # Import EventType only when needed
        from ..webhooks.events import EventType

        try:
            if event_type == "ci.passed":
                self.webhook_emitter.emit(
                    EventType.CI_PASSED,
                    pr_number=pr_number or 0,
                    branch=branch,
                )
            elif event_type == "ci.failed":
                self.webhook_emitter.emit(
                    EventType.CI_FAILED,
                    pr_number=pr_number or 0,
                    branch=branch,
                    failure_reason=failure_reason,
                )
        except Exception:
            # Webhooks should never block the workflow
            pass

    def handle_pr_created_stage(self, state: TaskState) -> int | None:
        """Handle PR creation - detect PR from current branch.

        The agent worker should have already created the PR. This stage detects
        the PR and moves to CI waiting.

        If no PR is found, it means the agent failed to create one despite being
        instructed to. In this case, we block and require manual intervention.
        """
        console.info("Checking PR status...")

        # Try to detect PR number from current branch if not already set
        if state.current_pr is None:
            try:
                pr_number = self.github_client.get_pr_for_current_branch(cwd=os.getcwd())
                if pr_number:
                    console.success(f"Detected PR #{pr_number} for current branch")
                    state.current_pr = pr_number
                    self.state_manager.save_state(state)
                else:
                    # No PR found - agent failed to create one
                    console.error("No PR found for current branch!")
                    console.error("The agent was instructed to create a PR but didn't.")
                    console.detail("Manual intervention required:")
                    console.detail("  1. Push the branch: git push -u origin HEAD")
                    console.detail("  2. Create a PR: gh pr create --title 'feat: description'")
                    console.detail("  3. Resume: claudetm resume")
                    state.status = "blocked"
                    self.state_manager.save_state(state)
                    return 1
            except Exception as e:
                console.warning(f"Could not detect PR: {e}")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1

        console.detail(f"PR #{state.current_pr} - moving to CI check")
        state.workflow_stage = "waiting_ci"
        self.state_manager.save_state(state)
        return None

    def handle_waiting_ci_stage(self, state: TaskState) -> int | None:
        """Handle waiting for CI - poll CI status."""
        if state.current_pr is None:
            state.workflow_stage = "waiting_reviews"
            self.state_manager.save_state(state)
            return None

        console.info(f"Checking CI status for PR #{state.current_pr}...")

        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)

            # Check if PR was already merged (e.g., manually)
            if pr_status.state == "MERGED":
                console.success(
                    f"PR #{state.current_pr} was already merged - skipping to next task"
                )
                state.workflow_stage = "merged"
                self.state_manager.save_state(state)
                return None

            # Check if PR was closed without merging
            if pr_status.state == "CLOSED":
                console.warning(f"PR #{state.current_pr} was closed without merging")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1

            # Get required checks from branch protection
            required_checks = set(
                self.github_client.get_required_status_checks(pr_status.base_branch)
            )
            # Use _get_check_name to handle both CheckRun (name) and StatusContext (context)
            reported_checks = {
                self._get_check_name(check)
                for check in pr_status.check_details
                if self._get_check_name(check) != "unknown"
            }
            missing_required = required_checks - reported_checks

            # If required checks haven't reported yet, keep waiting
            if missing_required:
                console.info(f"Waiting for required checks: {', '.join(missing_required)}")
                console.detail(f"Next check in {self.CI_POLL_INTERVAL}s...")
                if not interruptible_sleep(self.CI_POLL_INTERVAL):
                    return None
                return None

            # Check for merge conflicts
            if pr_status.mergeable == "CONFLICTING":
                console.warning("PR has merge conflicts - needs manual resolution")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1  # Exit with error

            if pr_status.ci_state == "SUCCESS":
                console.success(
                    f"CI passed! ({pr_status.checks_passed} passed, "
                    f"{pr_status.checks_skipped} skipped)"
                )
                # Emit ci.passed webhook
                self._emit_ci_event(
                    event_type="ci.passed",
                    pr_number=state.current_pr,
                    branch=self._get_current_branch() or "",
                )
                # Wait for GitHub to publish reviews before checking
                console.detail(f"Waiting {self.REVIEW_DELAY}s for reviews to be published...")
                if not interruptible_sleep(self.REVIEW_DELAY):
                    return None
                state.workflow_stage = "waiting_reviews"
                self.state_manager.save_state(state)
                return None
            elif pr_status.ci_state in ("FAILURE", "ERROR"):
                # Wait for ALL checks to complete before handling failure
                if pr_status.checks_pending > 0:
                    console.warning(
                        f"CI has failures but {pr_status.checks_pending} checks still pending..."
                    )
                    console.detail("Waiting for all checks to complete...")
                    if not interruptible_sleep(self.CI_POLL_INTERVAL):
                        return None
                    return None  # Retry on next cycle

                console.warning(
                    f"CI failed: {pr_status.checks_failed} failed, {pr_status.checks_passed} passed"
                )
                # Collect failed check names for webhook
                failed_checks = []
                for check in pr_status.check_details:
                    conclusion = (check.get("conclusion") or "").upper()
                    if conclusion in ("FAILURE", "ERROR"):
                        check_name = self._get_check_name(check)
                        console.detail(f"  ✗ {check_name}: {conclusion}")
                        failed_checks.append(check_name)
                # Emit ci.failed webhook
                self._emit_ci_event(
                    event_type="ci.failed",
                    pr_number=state.current_pr,
                    branch=self._get_current_branch() or "",
                    failure_reason=f"Failed checks: {', '.join(failed_checks)}"
                    if failed_checks
                    else None,
                )
                state.workflow_stage = "ci_failed"
                self.state_manager.save_state(state)
                return None
            else:
                console.info(
                    f"Waiting for CI... ({pr_status.checks_pending} pending, "
                    f"{pr_status.checks_passed} passed)"
                )
                # Show individual check statuses if available
                for check in pr_status.check_details:
                    status = (check.get("status") or "").upper()
                    check_name = self._get_check_name(check)
                    if status in ("IN_PROGRESS", "PENDING"):
                        console.detail(f"  ⏳ {check_name}: running")
                    elif status == "QUEUED":
                        console.detail(f"  ⏸ {check_name}: queued")
                console.detail(f"Next check in {self.CI_POLL_INTERVAL}s...")
                if not interruptible_sleep(self.CI_POLL_INTERVAL):
                    return None  # Let main loop handle cancellation
                return None

        except Exception as e:
            console.warning(f"Error checking CI: {e}")
            console.detail("Will retry on next cycle...")
            # Stay in waiting_ci and retry - do NOT fall through to merge
            if not interruptible_sleep(self.CI_POLL_INTERVAL):
                return None
            return None

    def handle_ci_failed_stage(self, state: TaskState) -> int | None:
        """Handle CI failure - run agent to fix issues.

        This method now also fetches PR comments (from CodeRabbit, reviewers, etc.)
        when saving CI failures, so the agent can fix BOTH CI issues AND address
        review comments in a single step.
        """
        console.info("CI failed - running agent to fix...")

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

        current_branch = self._get_current_branch()
        self.agent.run_work_session(
            task_description=task_description,
            context=context,
            model_override=ModelType.OPUS,
            required_branch=current_branch,
        )

        # Wait for CI to start after push
        console.info("Waiting 30s for CI to start...")
        if not interruptible_sleep(30):
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

        # Get target branch from config for rebase instructions
        config = get_config()
        target_branch = config.git.target_branch

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

## Step 4: Verify, Commit, Rebase, and Push

1. Run tests/lint locally to verify ALL passes
2. Commit all fixes together with a descriptive message
3. **Rebase onto {target_branch} before pushing** (CRITICAL - prevents merge conflicts!):
   ```bash
   git fetch origin {target_branch}
   git rebase origin/{target_branch}
   ```
   If conflicts occur during rebase:
   - Check `git status` to see conflicted files
   - Open each file and resolve conflicts (look for `<<<<<<<` markers)
   - Usually you need BOTH changes (yours AND from {target_branch})
   - `git add <file>` after resolving each file
   - `git rebase --continue` to proceed
   - Run tests again after resolving conflicts
4. Push the fixes: `git push --force-with-lease`
5. Create a resolution summary file at: `{resolve_json_path}`

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
6. **Rebase onto {target_branch} before pushing** (CRITICAL - prevents merge conflicts!):
   ```bash
   git fetch origin {target_branch}
   git rebase origin/{target_branch}
   ```
   If conflicts occur: resolve them, `git add`, `git rebase --continue`, run tests again.
7. Push the fixes: `git push --force-with-lease`

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
5. **Rebase onto {target_branch} before pushing** (CRITICAL - prevents merge conflicts!):
   ```bash
   git fetch origin {target_branch}
   git rebase origin/{target_branch}
   ```
   If conflicts occur: resolve them, `git add`, `git rebase --continue`, run tests again.
6. Push the fixes: `git push --force-with-lease`
7. Create a resolution summary file at: `{resolve_json_path}`

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

    def handle_waiting_reviews_stage(self, state: TaskState) -> int | None:
        """Handle waiting for reviews - check for review comments."""
        if state.current_pr is None:
            state.workflow_stage = "merged"
            self.state_manager.save_state(state)
            return None

        console.info(f"Checking reviews for PR #{state.current_pr}...")

        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)

            # Check if PR was already merged (e.g., manually)
            if pr_status.state == "MERGED":
                console.success(
                    f"PR #{state.current_pr} was already merged - skipping to next task"
                )
                state.workflow_stage = "merged"
                self.state_manager.save_state(state)
                return None

            # Check if PR was closed without merging
            if pr_status.state == "CLOSED":
                console.warning(f"PR #{state.current_pr} was closed without merging")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1

            # Check if ANY checks are still pending (CI, review bots, etc)
            # A check is pending if: status is not terminal AND conclusion is None
            pending_checks = [
                self._get_check_name(check)
                for check in pr_status.check_details
                if (
                    check.get("status", "").upper()
                    not in ("COMPLETED", "SUCCESS", "FAILURE", "ERROR", "SKIPPED")
                    and check.get("conclusion") is None
                )
            ]

            if pending_checks:
                console.info(f"Waiting for checks to finish: {', '.join(pending_checks[:3])}...")
                if not interruptible_sleep(self.CI_POLL_INTERVAL):
                    return None
                return None  # Will re-check on next cycle

            # Get threads we've already addressed (to show accurate count)
            addressed_threads = self.state_manager.get_addressed_threads(state.current_pr)
            # Actionable = unresolved threads that we haven't already addressed
            actionable_threads = pr_status.unresolved_threads - len(
                [t for t in addressed_threads if t]  # Count non-empty addressed thread IDs
            )
            # Clamp to 0 in case addressed count is stale
            actionable_threads = max(0, actionable_threads)

            if actionable_threads > 0:
                console.warning(
                    f"Found {actionable_threads} actionable / "
                    f"{pr_status.total_threads} total review comments"
                )
                state.workflow_stage = "addressing_reviews"
                self.state_manager.save_state(state)
                return None
            elif pr_status.unresolved_threads > 0:
                # All unresolved threads are addressed but not yet resolved on GitHub
                # This can happen if resolution failed - retry
                console.info(
                    f"Found {pr_status.unresolved_threads} unresolved threads "
                    "(all previously addressed, will retry resolution)"
                )
                state.workflow_stage = "addressing_reviews"
                self.state_manager.save_state(state)
                return None
            else:
                if pr_status.total_threads > 0:
                    console.success(f"All {pr_status.resolved_threads} review comments resolved!")
                else:
                    console.success("No review comments!")
                state.workflow_stage = "ready_to_merge"
                self.state_manager.save_state(state)
                return None

        except Exception as e:
            console.warning(f"Error checking reviews: {e}")
            console.detail("Will retry on next cycle...")
            # Stay in waiting_reviews and retry - do NOT fall through to merge
            if not interruptible_sleep(self.CI_POLL_INTERVAL):
                return None
            return None

    def handle_addressing_reviews_stage(self, state: TaskState) -> int | None:
        """Handle addressing reviews - run agent to fix review comments."""
        console.info("Addressing review comments...")

        # Save comments to files and get actual count of actionable comments
        saved_count = self.pr_context.save_pr_comments(state.current_pr)
        console.info(f"Saved {saved_count} actionable comment(s) for review")

        # Build fix prompt
        pr_dir = self.state_manager.get_pr_dir(state.current_pr) if state.current_pr else None
        comments_path = f"{pr_dir}/comments/" if pr_dir else ".claude-task-master/debugging/"
        resolve_json_path = (
            f"{pr_dir}/resolve-comments.json"
            if pr_dir
            else ".claude-task-master/debugging/resolve-comments.json"
        )

        # Get target branch from config for rebase instructions
        config = get_config()
        target_branch = config.git.target_branch

        task_description = f"""PR #{state.current_pr} has review comments to address.

**Read the review comments from:** `{comments_path}`

Use Glob to find all .txt files, then Read each one to understand the feedback.

Please:
1. Read ALL comment files in the comments/ directory
2. For each comment:
   - Make the requested change, OR
   - Explain why it's not needed
3. Run tests to verify
4. Commit fixes with a descriptive message
5. **Rebase onto {target_branch} before pushing** (CRITICAL - prevents merge conflicts!):
   ```bash
   git fetch origin {target_branch}
   git rebase origin/{target_branch}
   ```
   If conflicts occur: resolve them, `git add`, `git rebase --continue`, run tests again.
6. Push the fixes: `git push --force-with-lease`
7. Create a resolution summary file at: `{resolve_json_path}`

**Resolution file format:**
```json
{{
  "pr": {state.current_pr},
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
Your job is to: fix the code, run tests, commit, push, and create the resolution JSON file.

After addressing ALL comments and creating the resolution file, end with: TASK COMPLETE"""

        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        current_branch = self._get_current_branch()
        self.agent.run_work_session(
            task_description=task_description,
            context=context,
            model_override=ModelType.OPUS,
            required_branch=current_branch,
        )

        # Post replies to comments using resolution file
        self.pr_context.post_comment_replies(state.current_pr)

        # Wait for CI to start after push
        console.info("Waiting 30s for CI to start...")
        if not interruptible_sleep(30):
            return None

        state.workflow_stage = "waiting_ci"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None

    def handle_ready_to_merge_stage(self, state: TaskState) -> int | None:
        """Handle ready to merge - merge the PR if auto_merge enabled."""
        if state.current_pr is None:
            state.workflow_stage = "merged"
            self.state_manager.save_state(state)
            return None

        # Check PR status before attempting merge
        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)

            # Check if PR was already merged (e.g., manually)
            if pr_status.state == "MERGED":
                console.success(
                    f"PR #{state.current_pr} was already merged - skipping to next task"
                )
                state.workflow_stage = "merged"
                self.state_manager.save_state(state)
                return None

            # Check if PR was closed without merging
            if pr_status.state == "CLOSED":
                console.warning(f"PR #{state.current_pr} was closed without merging")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1

            if pr_status.mergeable == "CONFLICTING":
                console.warning(f"PR #{state.current_pr} has merge conflicts!")
                console.detail("Conflicts must be resolved before merging")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1
            elif pr_status.mergeable == "UNKNOWN":
                console.info("Waiting for GitHub to calculate mergeable status...")
                if not interruptible_sleep(self.CI_POLL_INTERVAL):
                    return None
                return None  # Retry on next cycle
        except Exception as e:
            console.warning(f"Error checking mergeable status: {e}")
            # Continue trying to merge anyway

        if state.options.auto_merge:
            console.info(f"Merging PR #{state.current_pr}...")
            try:
                self.github_client.merge_pr(state.current_pr)
                console.success(f"PR #{state.current_pr} merged!")
                state.workflow_stage = "merged"
                self.state_manager.save_state(state)
                return None
            except Exception as e:
                console.warning(f"Auto-merge failed: {e}")
                console.detail("PR may need manual merge or have merge conflicts")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1
        else:
            console.info(f"PR #{state.current_pr} ready to merge (auto_merge disabled)")
            console.detail("Use 'claudetm resume' after manual merge")
            state.status = "paused"
            self.state_manager.save_state(state)
            return 2

    def handle_merged_stage(
        self, state: TaskState, mark_task_complete_fn: Callable[[str, int], None]
    ) -> int | None:
        """Handle merged state - move to next task.

        Args:
            state: Current task state.
            mark_task_complete_fn: Function to mark task complete in plan.
        """
        console.success(f"Task #{state.current_task_index + 1} complete!")

        # Mark task as complete in plan
        plan = self.state_manager.load_plan()
        if plan:
            mark_task_complete_fn(plan, state.current_task_index)

        # Clear PR context files and checkout to base branch (only if PR was merged)
        if state.current_pr is not None:
            base_branch = "main"
            try:
                # Get base branch from PR before clearing
                pr_status = self.github_client.get_pr_status(state.current_pr)
                base_branch = pr_status.base_branch
            except Exception:
                pass  # Use default main

            try:
                self.state_manager.clear_pr_context(state.current_pr)
            except Exception:
                pass  # Best effort cleanup

            # Checkout to base branch to avoid conflicts on next task
            console.info(f"Checking out to {base_branch}...")
            if not self._checkout_branch(base_branch):
                # Checkout failed even after recovery - block and require manual intervention
                console.error(f"Could not checkout to {base_branch} after PR merge")
                console.detail("Manual intervention required:")
                console.detail(f"  1. Run: git stash && git checkout {base_branch} && git pull")
                console.detail("  2. Then run: claudetm resume")
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1

            console.success(f"Switched to {base_branch}")

        # Move to next task
        state.current_task_index += 1
        state.current_pr = None
        state.workflow_stage = "working"
        self.state_manager.save_state(state)

        return None
