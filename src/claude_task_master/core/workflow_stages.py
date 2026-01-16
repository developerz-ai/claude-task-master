"""Workflow Stage Handlers - Handle each stage of the PR workflow."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from . import console
from .agent import ModelType
from .shutdown import interruptible_sleep

if TYPE_CHECKING:
    from ..github.client import GitHubClient
    from .agent import AgentWrapper
    from .orchestrator import TaskState
    from .pr_context import PRContextManager
    from .state import StateManager


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

    def __init__(
        self,
        agent: AgentWrapper,
        state_manager: StateManager,
        github_client: GitHubClient,
        pr_context: PRContextManager,
    ):
        """Initialize stage handler.

        Args:
            agent: The agent wrapper for running queries.
            state_manager: The state manager for persistence.
            github_client: GitHub client for PR operations.
            pr_context: PR context manager for comments/CI logs.
        """
        self.agent = agent
        self.state_manager = state_manager
        self.github_client = github_client
        self.pr_context = pr_context

    def handle_pr_created_stage(self, state: TaskState) -> int | None:
        """Handle PR creation - check if PR exists or needs creation."""
        console.info("Checking PR status...")

        if state.current_pr is None:
            console.detail("No PR yet - agent will create one if needed")
            state.workflow_stage = "waiting_ci"
            self.state_manager.save_state(state)
            return None

        console.detail(f"PR #{state.current_pr} exists")
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

            if pr_status.ci_state == "SUCCESS":
                console.success("CI passed!")
                state.workflow_stage = "waiting_reviews"
                self.state_manager.save_state(state)
                return None
            elif pr_status.ci_state in ("FAILURE", "ERROR"):
                console.warning(f"CI failed: {pr_status.ci_state}")
                for check in pr_status.check_details:
                    if check.get("conclusion") in ("failure", "error"):
                        console.detail(f"  ✗ {check['name']}: {check.get('conclusion')}")
                state.workflow_stage = "ci_failed"
                self.state_manager.save_state(state)
                return None
            else:
                console.info(f"Waiting for CI... (status: {pr_status.ci_state})")
                # Show individual check statuses if available
                for check in pr_status.check_details:
                    status = check.get("status", "unknown")
                    name = check.get("name", "unknown")
                    if status == "in_progress":
                        console.detail(f"  ⏳ {name}: running")
                    elif status == "queued":
                        console.detail(f"  ⏸ {name}: queued")
                console.detail(f"Next check in {self.CI_POLL_INTERVAL}s...")
                if not interruptible_sleep(self.CI_POLL_INTERVAL):
                    return None  # Let main loop handle cancellation
                return None

        except Exception as e:
            console.warning(f"Error checking CI: {e}")
            state.workflow_stage = "waiting_reviews"
            self.state_manager.save_state(state)
            return None

    def handle_ci_failed_stage(self, state: TaskState) -> int | None:
        """Handle CI failure - run agent to fix issues."""
        console.info("CI failed - running agent to fix...")

        # Save CI failure logs
        self.pr_context.save_ci_failures(state.current_pr)

        # Build fix prompt
        pr_dir = self.state_manager.get_pr_dir(state.current_pr) if state.current_pr else None
        ci_path = f"{pr_dir}/ci/" if pr_dir else ".claude-task-master/debugging/"

        task_description = f"""CI has failed for PR #{state.current_pr}.

**Read the CI failure logs from:** `{ci_path}`

Use Glob to find all .txt files, then Read each one to understand the errors.

Please:
1. Read ALL files in the ci/ directory
2. Understand the error messages
3. Make the necessary fixes
4. Run tests locally to verify
5. Commit and push the fixes

After fixing, end with: TASK COMPLETE"""

        # Run agent with Opus for complex debugging
        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        self.agent.run_work_session(
            task_description=task_description,
            context=context,
            model_override=ModelType.OPUS,
        )

        state.workflow_stage = "waiting_ci"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None

    def handle_waiting_reviews_stage(self, state: TaskState) -> int | None:
        """Handle waiting for reviews - check for review comments."""
        if state.current_pr is None:
            state.workflow_stage = "merged"
            self.state_manager.save_state(state)
            return None

        console.info(f"Checking reviews for PR #{state.current_pr}...")

        try:
            pr_status = self.github_client.get_pr_status(state.current_pr)

            if pr_status.unresolved_threads > 0:
                console.warning(f"Found {pr_status.unresolved_threads} unresolved review comments")
                state.workflow_stage = "addressing_reviews"
                self.state_manager.save_state(state)
                return None
            else:
                console.success("No unresolved reviews!")
                state.workflow_stage = "ready_to_merge"
                self.state_manager.save_state(state)
                return None

        except Exception as e:
            console.warning(f"Error checking reviews: {e}")
            state.workflow_stage = "ready_to_merge"
            self.state_manager.save_state(state)
            return None

    def handle_addressing_reviews_stage(self, state: TaskState) -> int | None:
        """Handle addressing reviews - run agent to fix review comments."""
        console.info("Addressing review comments...")

        # Save comments to files
        self.pr_context.save_pr_comments(state.current_pr)

        # Build fix prompt
        pr_dir = self.state_manager.get_pr_dir(state.current_pr) if state.current_pr else None
        comments_path = f"{pr_dir}/comments/" if pr_dir else ".claude-task-master/debugging/"
        resolve_json_path = (
            f"{pr_dir}/resolve-comments.json"
            if pr_dir
            else ".claude-task-master/debugging/resolve-comments.json"
        )

        task_description = f"""PR #{state.current_pr} has review comments to address.

**Read the review comments from:** `{comments_path}`

Use Glob to find all .txt files, then Read each one to understand the feedback.

Please:
1. Read ALL comment files in the comments/ directory
2. For each comment:
   - Make the requested change, OR
   - Explain why it's not needed
3. Run tests to verify
4. Commit and push the fixes
5. Create a resolution summary file at: `{resolve_json_path}`

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

After addressing ALL comments and creating the resolution file, end with: TASK COMPLETE"""

        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        self.agent.run_work_session(
            task_description=task_description,
            context=context,
            model_override=ModelType.OPUS,
        )

        # Post replies to comments using resolution file
        self.pr_context.post_comment_replies(state.current_pr)

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

        # Clear PR context files
        if state.current_pr is not None:
            try:
                self.state_manager.clear_pr_context(state.current_pr)
            except Exception:
                pass  # Best effort cleanup

        # Move to next task
        state.current_task_index += 1
        state.current_pr = None
        state.workflow_stage = "working"
        self.state_manager.save_state(state)

        return None
