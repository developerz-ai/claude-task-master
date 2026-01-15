"""Work Loop Orchestrator - Main loop driving work sessions until completion."""

from typing import Optional
from .agent import AgentWrapper
from .state import StateManager, TaskState
from .planner import Planner


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
        """Run the main work loop until completion or blocked."""
        state = self.state_manager.load_state()

        # Check if we've exceeded max sessions
        if state.options.max_sessions and state.session_count >= state.options.max_sessions:
            print(f"Max sessions ({state.options.max_sessions}) reached")
            return 1  # Blocked

        try:
            while not self._is_complete(state):
                # Run work session for current task
                self._run_work_session(state)

                # Check if we need to create/update PR
                # TODO: Implement PR cycle

                # Move to next task if current is complete
                # TODO: Implement task completion check

                # Increment session count
                state.session_count += 1
                self.state_manager.save_state(state)

                # Check session limit again
                if state.options.max_sessions and state.session_count >= state.options.max_sessions:
                    print(f"Max sessions ({state.options.max_sessions}) reached")
                    state.status = "blocked"
                    self.state_manager.save_state(state)
                    return 1

            # All tasks complete - verify success criteria
            if self._verify_success():
                state.status = "success"
                self.state_manager.save_state(state)
                self.state_manager.cleanup_on_success(state.run_id)
                return 0  # Success

            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1  # Blocked

        except KeyboardInterrupt:
            state.status = "paused"
            self.state_manager.save_state(state)
            return 2  # User interrupted

        except Exception as e:
            print(f"Error: {e}")
            state.status = "failed"
            self.state_manager.save_state(state)
            return 1  # Error

    def _run_work_session(self, state: TaskState) -> None:
        """Run a single work session."""
        # Get current task from plan
        plan = self.state_manager.load_plan()
        if not plan:
            raise ValueError("No plan found")

        tasks = self._parse_tasks(plan)
        if state.current_task_index >= len(tasks):
            # All tasks processed
            return

        current_task = tasks[state.current_task_index]

        # Check if task is already complete
        if self._is_task_complete(plan, state.current_task_index):
            print(f"\n✓ Task #{state.current_task_index + 1} already complete: {current_task}")
            state.current_task_index += 1
            self.state_manager.save_state(state)
            return

        # Load context
        context = self.state_manager.load_context()

        # Build task description
        goal = self.state_manager.load_goal()
        task_description = f"""Goal: {goal}

Current Task (#{state.current_task_index + 1}): {current_task}

Please complete this task."""

        print(f"\nWorking on task #{state.current_task_index + 1}: {current_task}")

        # Run agent work session
        result = self.agent.run_work_session(
            task_description=task_description,
            context=context,
        )

        # Update progress as todo list
        progress_lines = [
            "# Progress Tracker\n",
            f"**Session:** {state.session_count + 1}",
            f"**Current Task:** {state.current_task_index + 1} of {len(tasks)}\n",
            "## Task List\n"
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
        if result.get('output'):
            progress_lines.extend([
                "\n## Latest Completed",
                f"**Task {state.current_task_index + 1}:** {current_task}\n",
                "### Summary",
                result.get('output', 'Completed')
            ])

        progress = "\n".join(progress_lines)
        self.state_manager.save_progress(progress)

        # Mark task as complete and move to next
        self._mark_task_complete(plan, state.current_task_index)
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

        return result.get("success", False)
