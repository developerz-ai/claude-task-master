"""Work Loop Orchestrator - Main loop driving work sessions until completion."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from . import console
from .agent import AgentError, AgentWrapper, ModelType, TaskComplexity, parse_task_complexity
from .key_listener import check_escape, reset_escape, start_listening, stop_listening
from .planner import Planner
from .state import StateError, StateManager, TaskState

if TYPE_CHECKING:
    from ..github.client import GitHubClient
    from .logger import TaskLogger

# =============================================================================
# Custom Exception Classes
# =============================================================================


class OrchestratorError(Exception):
    """Base exception for all orchestrator-related errors."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class PlanParsingError(OrchestratorError):
    """Raised when plan parsing fails."""

    def __init__(self, message: str, plan_content: str | None = None):
        self.plan_content = plan_content
        details = None
        if plan_content:
            # Show a preview of the problematic plan content
            preview = plan_content[:200] + "..." if len(plan_content) > 200 else plan_content
            details = f"Plan content preview: {preview}"
        super().__init__(message, details)


class NoPlanFoundError(OrchestratorError):
    """Raised when no plan file exists."""

    def __init__(self) -> None:
        super().__init__(
            "No plan found",
            "The plan file does not exist. Please run the planning phase first.",
        )


class NoTasksFoundError(PlanParsingError):
    """Raised when the plan contains no tasks."""

    def __init__(self, plan_content: str | None = None):
        super().__init__(
            "No tasks found in plan",
            plan_content,
        )


class TaskIndexOutOfBoundsError(OrchestratorError):
    """Raised when task index is out of bounds."""

    def __init__(self, task_index: int, total_tasks: int):
        self.task_index = task_index
        self.total_tasks = total_tasks
        super().__init__(
            f"Task index {task_index} is out of bounds",
            f"Plan has {total_tasks} tasks (indices 0-{total_tasks - 1}).",
        )


class WorkSessionError(OrchestratorError):
    """Raised when a work session fails."""

    def __init__(self, task_index: int, task_description: str, original_error: Exception):
        self.task_index = task_index
        self.task_description = task_description
        self.original_error = original_error
        super().__init__(
            f"Work session failed for task #{task_index + 1}: {task_description}",
            f"Error: {type(original_error).__name__}: {original_error}",
        )


class StateRecoveryError(OrchestratorError):
    """Raised when state recovery fails."""

    def __init__(self, reason: str, original_error: Exception | None = None):
        self.original_error = original_error
        details = f"Reason: {reason}"
        if original_error:
            details += f" | Original error: {type(original_error).__name__}: {original_error}"
        super().__init__(
            "Failed to recover orchestrator state",
            details,
        )


class MaxSessionsReachedError(OrchestratorError):
    """Raised when max sessions limit is reached."""

    def __init__(self, max_sessions: int, current_session: int):
        self.max_sessions = max_sessions
        self.current_session = current_session
        super().__init__(
            f"Max sessions ({max_sessions}) reached",
            f"Currently at session {current_session}. Consider increasing max_sessions or resuming manually.",
        )


class VerificationFailedError(OrchestratorError):
    """Raised when success criteria verification fails."""

    def __init__(self, criteria: str, details: str | None = None):
        self.criteria = criteria
        super().__init__(
            "Success criteria verification failed",
            details or f"Criteria not met: {criteria[:100]}..."
            if len(criteria) > 100
            else criteria,
        )


class PRWorkflowError(OrchestratorError):
    """Raised when PR workflow operations fail."""

    def __init__(self, pr_number: int, stage: str, message: str):
        self.pr_number = pr_number
        self.stage = stage
        super().__init__(
            f"PR #{pr_number} workflow error at {stage}",
            message,
        )


class CITimeoutError(OrchestratorError):
    """Raised when CI checks timeout."""

    def __init__(self, pr_number: int, timeout_seconds: int):
        self.pr_number = pr_number
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"CI checks timed out for PR #{pr_number}",
            f"Waited {timeout_seconds} seconds. Check CI status manually.",
        )


class WorkLoopOrchestrator:
    """Orchestrates the main work loop with full PR workflow support.

    Workflow: plan → work → PR → CI → reviews → fix → merge → next PR → success
    """

    # CI polling configuration
    CI_POLL_INTERVAL = 30  # seconds between CI status checks
    CI_TIMEOUT = 600  # 10 minutes max wait for CI
    REVIEW_POLL_INTERVAL = 60  # seconds between review checks

    def __init__(
        self,
        agent: AgentWrapper,
        state_manager: StateManager,
        planner: Planner,
        github_client: GitHubClient | None = None,
        logger: TaskLogger | None = None,
    ):
        """Initialize orchestrator.

        Args:
            agent: The agent wrapper for running queries.
            state_manager: The state manager for persistence.
            planner: The planner for planning phases.
            github_client: Optional GitHub client for PR operations.
            logger: Optional logger for recording session activity.
        """
        self.agent = agent
        self.state_manager = state_manager
        self.planner = planner
        self._github_client = github_client
        self.logger = logger

    @property
    def github_client(self) -> GitHubClient:
        """Get or lazily initialize GitHub client."""
        if self._github_client is None:
            try:
                from ..github.client import GitHubClient

                self._github_client = GitHubClient()
            except Exception as e:
                raise OrchestratorError(
                    "GitHub client not available",
                    f"Install gh CLI and run 'gh auth login': {e}",
                ) from e
        return self._github_client

    def run(self) -> int:
        """Run the main work loop until completion or blocked.

        Returns:
            0: Success - all tasks completed and verified.
            1: Blocked/Failed - max sessions reached, verification failed, or error.
            2: Paused - user interrupted with Ctrl+C.

        Raises:
            StateError: If state cannot be loaded (with automatic recovery attempt).
            OrchestratorError: For various orchestration failures.
        """
        # Attempt to load state with recovery on failure
        try:
            state = self.state_manager.load_state()
        except StateError as e:
            console.warning(f"State loading error: {e.message}")
            recovered_state = self._attempt_state_recovery()
            if recovered_state:
                console.success("State recovered from backup")
                state = recovered_state
            else:
                console.error("State recovery failed - cannot continue")
                raise StateRecoveryError("State file corrupted and no backup available", e) from e

        # Check if we've exceeded max sessions
        if state.options.max_sessions and state.session_count >= state.options.max_sessions:
            error = MaxSessionsReachedError(state.options.max_sessions, state.session_count)
            console.warning(error.message)
            return 1  # Blocked

        # Start listening for Escape key
        start_listening()
        console.detail("Press [Escape] to pause, [Ctrl+C] to interrupt")

        try:
            while not self._is_complete(state):
                # Check if user pressed Escape to pause
                if check_escape():
                    console.newline()
                    console.warning("Escape pressed - pausing...")
                    state.status = "paused"
                    self.state_manager.save_state(state)
                    backup_path = self.state_manager.create_state_backup()
                    if backup_path:
                        console.detail(f"State backup saved: {backup_path}")
                    stop_listening()
                    return 2  # Paused

                # Run the PR workflow cycle
                result = self._run_workflow_cycle(state)
                if result is not None:
                    return result

                # Check session limit
                if state.options.max_sessions and state.session_count >= state.options.max_sessions:
                    error = MaxSessionsReachedError(state.options.max_sessions, state.session_count)
                    console.warning(error.message)
                    state.status = "blocked"
                    self.state_manager.save_state(state)
                    return 1

            # All tasks complete - verify success criteria
            stop_listening()
            try:
                if self._verify_success():
                    state.status = "success"
                    self.state_manager.save_state(state)
                    self.state_manager.cleanup_on_success(state.run_id)
                    console.success("All tasks completed successfully!")
                    return 0  # Success
                else:
                    self.state_manager.load_criteria() or "unknown"
                    console.warning("Success criteria verification failed")
                    state.status = "blocked"
                    self.state_manager.save_state(state)
                    return 1  # Blocked
            except Exception as e:
                console.warning(f"Error during success verification: {e}")
                # Still mark as blocked since we can't verify
                state.status = "blocked"
                self.state_manager.save_state(state)
                return 1

        except KeyboardInterrupt:
            stop_listening()
            console.newline()
            console.warning("Interrupted by user (Ctrl+C) - pausing...")
            state.status = "paused"
            self.state_manager.save_state(state)
            # Create a backup when pausing
            backup_path = self.state_manager.create_state_backup()
            if backup_path:
                console.detail(f"State backup saved: {backup_path}")
            console.info("Use 'claudetm resume' to continue")
            return 2  # User interrupted

        except OrchestratorError as e:
            stop_listening()
            # Known orchestrator errors - already have good messages
            console.error(f"Orchestrator error: {e.message}")
            if e.details:
                console.detail(e.details)
            state.status = "failed"
            self.state_manager.save_state(state)
            return 1  # Error

        except StateError as e:
            stop_listening()
            # State-related errors
            console.error(f"State error: {e.message}")
            if e.details:
                console.detail(e.details)
            # Try to save state anyway
            try:
                state.status = "failed"
                self.state_manager.save_state(state)
            except Exception:
                console.detail("Warning: Could not save failed state")
            return 1  # Error

        except Exception as e:
            stop_listening()
            # Unexpected errors - provide detailed debugging info
            error_type = type(e).__name__
            error_msg = str(e)
            console.error(f"Unexpected error ({error_type}): {error_msg}")
            console.detail(f"Task index: {state.current_task_index}")
            console.detail(f"Session count: {state.session_count}")
            console.detail(f"Status before error: {state.status}")

            # Try to save state with failure status
            try:
                state.status = "failed"
                self.state_manager.save_state(state)
                # Create a backup for debugging
                backup_path = self.state_manager.create_state_backup()
                if backup_path:
                    console.detail(f"State backup saved: {backup_path}")
            except Exception as save_error:
                console.detail(f"Warning: Could not save failed state: {save_error}")

            return 1  # Error

    def _attempt_state_recovery(self) -> TaskState | None:
        """Attempt to recover state from backup.

        Returns:
            TaskState if recovery successful, None otherwise.
        """
        try:
            # The state manager's load_state method already attempts recovery
            # This is a secondary recovery attempt
            backup_dir = self.state_manager.backup_dir
            if not backup_dir.exists():
                return None

            # Get the most recent backup
            backups = sorted(
                backup_dir.glob("state.*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )

            if not backups:
                return None

            import json

            for backup_file in backups:
                try:
                    with open(backup_file) as f:
                        data = json.load(f)
                    return TaskState(**data)
                except Exception:
                    continue

            return None
        except Exception:
            return None

    def _run_workflow_cycle(self, state: TaskState) -> int | None:
        """Run one cycle of the PR workflow.

        Workflow stages:
        1. working → Implement tasks
        2. pr_created → Create/update PR
        3. waiting_ci → Poll CI status
        4. ci_failed → Fix CI failures
        5. waiting_reviews → Wait for reviews
        6. addressing_reviews → Address review feedback
        7. ready_to_merge → Merge PR
        8. merged → Move to next task

        Args:
            state: Current task state.

        Returns:
            Exit code (0, 1, 2) if should exit, None to continue.
        """
        # Initialize workflow stage if not set
        if state.workflow_stage is None:
            state.workflow_stage = "working"
            self.state_manager.save_state(state)

        stage = state.workflow_stage

        try:
            if stage == "working":
                return self._handle_working_stage(state)
            elif stage == "pr_created":
                return self._handle_pr_created_stage(state)
            elif stage == "waiting_ci":
                return self._handle_waiting_ci_stage(state)
            elif stage == "ci_failed":
                return self._handle_ci_failed_stage(state)
            elif stage == "waiting_reviews":
                return self._handle_waiting_reviews_stage(state)
            elif stage == "addressing_reviews":
                return self._handle_addressing_reviews_stage(state)
            elif stage == "ready_to_merge":
                return self._handle_ready_to_merge_stage(state)
            elif stage == "merged":
                return self._handle_merged_stage(state)
            else:
                console.warning(f"Unknown workflow stage: {stage}, resetting to working")
                state.workflow_stage = "working"
                self.state_manager.save_state(state)
                return None

        except NoPlanFoundError as e:
            console.error(e.message)
            state.status = "failed"
            self.state_manager.save_state(state)
            return 1
        except NoTasksFoundError as e:
            console.info(e.message)
            return None  # Continue to completion check
        except WorkSessionError as e:
            console.warning(f"Work session error: {e.message}")
            if e.details:
                console.detail(e.details)
            self.state_manager.create_state_backup()
            raise
        except AgentError as e:
            console.error(f"Agent error: {e.message}")
            if e.details:
                console.detail(e.details)
            raise WorkSessionError(
                state.current_task_index,
                self._get_current_task_description(state),
                e,
            ) from e

    def _handle_working_stage(self, state: TaskState) -> int | None:
        """Handle the working stage - implement the current task."""
        # Log session start
        if self.logger:
            self.logger.start_session(state.session_count + 1, "working")

        try:
            self._run_work_session(state)
        finally:
            # Log session end
            if self.logger:
                self.logger.end_session("completed")

        # After work session, check if we should create a PR
        # For now, always try to create/update PR after work
        state.workflow_stage = "pr_created"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None

    def _handle_pr_created_stage(self, state: TaskState) -> int | None:
        """Handle PR creation - check if PR exists or needs creation."""
        console.info("Checking PR status...")

        if state.current_pr is None:
            # Let agent create PR in next work session
            console.detail("No PR yet - agent will create one if needed")
            state.workflow_stage = "waiting_ci"
            self.state_manager.save_state(state)
            return None

        # PR exists, move to CI check
        console.detail(f"PR #{state.current_pr} exists")
        state.workflow_stage = "waiting_ci"
        self.state_manager.save_state(state)
        return None

    def _handle_waiting_ci_stage(self, state: TaskState) -> int | None:
        """Handle waiting for CI - poll CI status."""
        if state.current_pr is None:
            # No PR, skip CI check
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
                # Show failed checks
                for check in pr_status.check_details:
                    if check.get("conclusion") in ("failure", "error"):
                        console.detail(f"  ✗ {check['name']}: {check.get('conclusion')}")
                state.workflow_stage = "ci_failed"
                self.state_manager.save_state(state)
                return None
            else:
                # Still pending, wait and retry
                console.detail(f"CI pending... ({pr_status.ci_state})")
                time.sleep(self.CI_POLL_INTERVAL)
                return None

        except Exception as e:
            console.warning(f"Error checking CI: {e}")
            # Skip CI check on error, continue to reviews
            state.workflow_stage = "waiting_reviews"
            self.state_manager.save_state(state)
            return None

    def _handle_ci_failed_stage(self, state: TaskState) -> int | None:
        """Handle CI failure - run agent to fix issues."""
        console.info("CI failed - running agent to fix...")

        # Get failed logs for context
        try:
            failed_logs = self.github_client.get_failed_run_logs(max_lines=50)
        except Exception:
            failed_logs = "Could not retrieve CI logs"

        # Save CI failure logs to file for Claude to read
        if state.current_pr is not None:
            try:
                # Get failed check names
                pr_status = self.github_client.get_pr_status(state.current_pr)
                for check in pr_status.check_details:
                    if check.get("conclusion") in ("failure", "error"):
                        self.state_manager.save_ci_failure(
                            state.current_pr,
                            check.get("name", "unknown"),
                            failed_logs,
                        )
            except Exception:
                pass  # Best effort

        # Build fix prompt - point Claude to the saved context files
        pr_context_hint = ""
        if state.current_pr is not None:
            pr_dir = self.state_manager.get_pr_dir(state.current_pr)
            pr_context_hint = f"\nCI failure logs saved to: {pr_dir}/ci/"

        task_description = f"""CI has failed for PR #{state.current_pr}.
{pr_context_hint}
Failed CI logs:
{failed_logs}

Please:
1. Read the error messages carefully
2. Make the necessary fixes
3. Run tests locally to verify
4. Commit and push the fixes"""

        # Run agent with Opus for complex debugging
        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        self.agent.run_work_session(
            task_description=task_description,
            context=context,
            model_override=ModelType.OPUS,  # Use smartest model for debugging
        )

        # After fixing, go back to CI wait
        state.workflow_stage = "waiting_ci"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None

    def _handle_waiting_reviews_stage(self, state: TaskState) -> int | None:
        """Handle waiting for reviews - check for review comments."""
        if state.current_pr is None:
            # No PR, skip review check and mark task done
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
            # Skip review check on error
            state.workflow_stage = "ready_to_merge"
            self.state_manager.save_state(state)
            return None

    def _handle_addressing_reviews_stage(self, state: TaskState) -> int | None:
        """Handle addressing reviews - run agent to fix review comments."""
        console.info("Addressing review comments...")

        # Get PR comments
        comments_text = ""
        try:
            if state.current_pr is not None:
                comments_text = self.github_client.get_pr_comments(
                    state.current_pr,
                    only_unresolved=True,
                )

                # Also save comments to files for Claude to read
                # Parse the GraphQL response to get structured comments
                self._save_pr_comments_to_files(state.current_pr)
            else:
                comments_text = "No PR number available"
        except Exception:
            comments_text = "Could not retrieve review comments"

        # Build fix prompt - point Claude to the saved context files
        pr_context_hint = ""
        if state.current_pr is not None:
            pr_dir = self.state_manager.get_pr_dir(state.current_pr)
            pr_context_hint = f"\nReview comments saved to: {pr_dir}/comments/"

        task_description = f"""PR #{state.current_pr} has review comments to address.
{pr_context_hint}
Review comments:
{comments_text}

Please:
1. Read each comment carefully
2. Make the requested changes
3. Run tests to verify
4. Commit and push the fixes"""

        # Run agent
        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        self.agent.run_work_session(
            task_description=task_description,
            context=context,
            pr_comments=comments_text,
            model_override=ModelType.OPUS,  # Use smartest model for reviews
        )

        # After addressing, go back to CI wait (fixes may trigger new CI)
        state.workflow_stage = "waiting_ci"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None

    def _save_pr_comments_to_files(self, pr_number: int) -> None:
        """Fetch and save PR comments to files for Claude to read."""
        try:
            import json
            import subprocess

            # Get repository info
            result = subprocess.run(
                ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                check=True,
                capture_output=True,
                text=True,
            )
            repo_info = result.stdout.strip()
            owner, repo = repo_info.split("/")

            # GraphQL query to get structured comments
            query = """
            query($owner: String!, $repo: String!, $pr: Int!) {
              repository(owner: $owner, name: $repo) {
                pullRequest(number: $pr) {
                  reviewThreads(first: 100) {
                    nodes {
                      isResolved
                      comments(first: 10) {
                        nodes {
                          author { login }
                          body
                          path
                          line
                        }
                      }
                    }
                  }
                }
              }
            }
            """

            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "graphql",
                    "-f",
                    f"query={query}",
                    "-F",
                    f"owner={owner}",
                    "-F",
                    f"repo={repo}",
                    "-F",
                    f"pr={pr_number}",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            data = json.loads(result.stdout)
            threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]

            # Convert to list of comment dicts
            comments = []
            for thread in threads:
                is_resolved = thread["isResolved"]
                for comment in thread["comments"]["nodes"]:
                    comments.append(
                        {
                            "author": comment["author"]["login"],
                            "body": comment["body"],
                            "path": comment.get("path"),
                            "line": comment.get("line"),
                            "is_resolved": is_resolved,
                        }
                    )

            # Save to files
            self.state_manager.save_pr_comments(pr_number, comments)

        except Exception as e:
            console.warning(f"Could not save PR comments to files: {e}")

    def _handle_ready_to_merge_stage(self, state: TaskState) -> int | None:
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

    def _handle_merged_stage(self, state: TaskState) -> int | None:
        """Handle merged state - move to next task."""
        console.success(f"Task #{state.current_task_index + 1} complete!")

        # Mark task as complete in plan
        plan = self.state_manager.load_plan()
        if plan:
            self._mark_task_complete(plan, state.current_task_index)

        # Clear PR context files (comments, CI logs) after merge
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

        # Reset escape flag for next iteration
        reset_escape()

        return None

    def _get_current_task_description(self, state: TaskState) -> str:
        """Get the description of the current task.

        Args:
            state: Current task state.

        Returns:
            Task description string or placeholder if not found.
        """
        try:
            plan = self.state_manager.load_plan()
            if not plan:
                return "<unknown task>"

            tasks = self._parse_tasks(plan)
            if state.current_task_index < len(tasks):
                return tasks[state.current_task_index]
            return f"<task index {state.current_task_index}>"
        except Exception:
            return "<unknown task>"

    def _run_work_session(self, state: TaskState) -> None:
        """Run a single work session.

        Args:
            state: Current task state.

        Raises:
            NoPlanFoundError: If no plan file exists.
            NoTasksFoundError: If the plan contains no tasks.
            WorkSessionError: If the work session fails.
        """
        # Get current task from plan
        plan = self.state_manager.load_plan()
        if not plan:
            raise NoPlanFoundError()

        try:
            tasks = self._parse_tasks(plan)
        except Exception as e:
            raise PlanParsingError(f"Failed to parse plan: {e}", plan) from e

        if not tasks:
            raise NoTasksFoundError(plan)

        if state.current_task_index >= len(tasks):
            # All tasks processed
            return

        current_task = tasks[state.current_task_index]

        # Check if task is already complete
        if self._is_task_complete(plan, state.current_task_index):
            console.newline()
            console.success(
                f"Task #{state.current_task_index + 1} already complete: {current_task}"
            )
            state.current_task_index += 1
            self.state_manager.save_state(state)
            return

        # Parse task complexity to determine which model to use
        complexity, cleaned_task = parse_task_complexity(current_task)
        target_model = TaskComplexity.get_model_for_complexity(complexity)

        # Load context safely
        try:
            context = self.state_manager.load_context()
        except Exception as e:
            console.warning(f"Could not load context: {e}")
            context = ""

        # Build task description
        try:
            goal = self.state_manager.load_goal()
        except Exception as e:
            console.warning(f"Could not load goal: {e}")
            goal = "Complete the assigned task"

        task_description = f"""Goal: {goal}

Current Task (#{state.current_task_index + 1}): {cleaned_task}

Please complete this task."""

        console.newline()
        console.info(f"Working on task #{state.current_task_index + 1}: {cleaned_task}")
        console.detail(f"Complexity: {complexity.value} → Model: {target_model.value}")

        # Log the prompt
        if self.logger:
            self.logger.log_prompt(task_description)

        # Run agent work session with model routing based on complexity
        try:
            result = self.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=target_model,  # Route to appropriate model
            )
        except AgentError:
            # Log the error
            if self.logger:
                self.logger.log_error("Agent error during work session")
            # Let agent errors propagate to be wrapped by caller
            raise
        except Exception as e:
            # Log the error
            if self.logger:
                self.logger.log_error(str(e))
            raise WorkSessionError(
                state.current_task_index,
                current_task,
                e,
            ) from e

        # Log the response
        if self.logger and result.get("output"):
            self.logger.log_response(result.get("output", ""))

        # Update progress as todo list
        progress_lines = [
            "# Progress Tracker\n",
            f"**Session:** {state.session_count + 1}",
            f"**Current Task:** {state.current_task_index + 1} of {len(tasks)}\n",
            "## Task List\n",
        ]

        # Add all tasks with their status
        for i, task in enumerate(tasks):
            is_complete = self._is_task_complete(plan, i)
            is_current = i == state.current_task_index

            if is_complete:
                status = "✓"
                marker = "[x]"
            elif is_current:
                status = "→"
                marker = "[ ]"
            else:
                status = " "
                marker = "[ ]"

            progress_lines.append(f"{status} {marker} **Task {i + 1}:** {task}")

        # Add latest result if available
        if result.get("output"):
            progress_lines.extend(
                [
                    "\n## Latest Completed",
                    f"**Task {state.current_task_index + 1}:** {current_task}\n",
                    "### Summary",
                    result.get("output", "Completed"),
                ]
            )

        progress = "\n".join(progress_lines)

        # Save progress with error handling
        try:
            self.state_manager.save_progress(progress)
        except Exception as e:
            console.warning(f"Could not save progress: {e}")

        # Note: task completion and index increment are handled by _handle_merged_stage

    def _parse_tasks(self, plan: str) -> list[str]:
        """Parse tasks from plan markdown."""
        tasks = []
        for line in plan.split("\n"):
            # Look for markdown checkbox lines
            if line.strip().startswith("- [ ]") or line.strip().startswith("- [x]"):
                task = line.strip()[5:].strip()  # Remove "- [ ]" or "- [x]"
                if task:
                    tasks.append(task)
        return tasks

    def _is_task_complete(self, plan: str, task_index: int) -> bool:
        """Check if a task is already marked as complete."""
        lines = plan.split("\n")
        task_count = -1

        for line in lines:
            if line.strip().startswith("- [ ]") or line.strip().startswith("- [x]"):
                task_count += 1
                if task_count == task_index:
                    return line.strip().startswith("- [x]")

        return False

    def _mark_task_complete(self, plan: str, task_index: int) -> None:
        """Mark a task as complete in the plan."""
        lines = plan.split("\n")
        task_count = -1

        for i, line in enumerate(lines):
            if line.strip().startswith("- [ ]") or line.strip().startswith("- [x]"):
                task_count += 1
                if task_count == task_index:
                    # Mark this task as complete
                    lines[i] = line.replace("- [ ]", "- [x]", 1)
                    break

        updated_plan = "\n".join(lines)
        self.state_manager.save_plan(updated_plan)

    def _is_complete(self, state: TaskState) -> bool:
        """Check if all tasks are complete."""
        plan = self.state_manager.load_plan()
        if not plan:
            return True

        tasks = self._parse_tasks(plan)
        # Check if we've processed all tasks
        return state.current_task_index >= len(tasks)

    def _verify_success(self) -> bool:
        """Verify success criteria are met."""
        criteria = self.state_manager.load_criteria()
        if not criteria:
            return True  # No criteria specified

        context = self.state_manager.load_context()
        result = self.agent.verify_success_criteria(criteria=criteria, context=context)

        return bool(result.get("success", False))
