"""Work Loop Orchestrator - Main loop driving work sessions until completion."""

from . import console
from .agent import AgentError, AgentWrapper, TaskComplexity, parse_task_complexity
from .key_listener import check_escape, start_listening, stop_listening
from .planner import Planner
from .state import StateError, StateManager, TaskState

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


class WorkLoopOrchestrator:
    """Orchestrates the main work loop."""

    def __init__(
        self,
        agent: AgentWrapper,
        state_manager: StateManager,
        planner: Planner,
    ):
        """Initialize orchestrator."""
        self.agent = agent
        self.state_manager = state_manager
        self.planner = planner

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

                # Run work session for current task with error handling
                try:
                    self._run_work_session(state)
                except NoPlanFoundError as e:
                    console.error(e.message)
                    state.status = "failed"
                    self.state_manager.save_state(state)
                    return 1
                except NoTasksFoundError as e:
                    # No tasks is actually a success case (nothing to do)
                    console.info(e.message)
                    break
                except WorkSessionError as e:
                    # Log error details but continue - agent may have partially completed
                    console.warning(f"Work session error: {e.message}")
                    if e.details:
                        console.detail(e.details)
                    # Create a backup before potentially continuing
                    self.state_manager.create_state_backup()
                    # Re-raise to be handled by outer exception handler
                    raise
                except AgentError as e:
                    # Agent-specific errors - wrap with context
                    console.error(f"Agent error during work session: {e.message}")
                    if e.details:
                        console.detail(e.details)
                    raise WorkSessionError(
                        state.current_task_index,
                        self._get_current_task_description(state),
                        e,
                    ) from e

                # Check if we need to create/update PR
                # TODO: Implement PR cycle

                # Move to next task if current is complete
                # TODO: Implement task completion check

                # Increment session count
                state.session_count += 1
                self.state_manager.save_state(state)

                # Check session limit again
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

        # Run agent work session with model routing based on complexity
        try:
            result = self.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=target_model,  # Route to appropriate model
            )
        except AgentError:
            # Let agent errors propagate to be wrapped by caller
            raise
        except Exception as e:
            raise WorkSessionError(
                state.current_task_index,
                current_task,
                e,
            ) from e

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

        # Mark task as complete and move to next
        try:
            self._mark_task_complete(plan, state.current_task_index)
        except Exception as e:
            console.warning(f"Could not mark task as complete: {e}")

        state.current_task_index += 1
        self.state_manager.save_state(state)

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
