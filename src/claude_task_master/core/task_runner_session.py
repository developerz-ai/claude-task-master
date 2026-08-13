"""Session execution and progress update mixin for TaskRunner."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from . import console
from .agent_exceptions import AgentError
from .agent_models import TaskComplexity, parse_task_complexity
from .config_loader import get_config
from .console import clear_task_context, set_task_context
from .hive import describe_machine, hive_max_parallel
from .subagents import list_project_agents
from .task_runner_errors import WorkSessionError

if TYPE_CHECKING:
    from .agent import AgentWrapper
    from .logger import TaskLogger
    from .state import StateManager, TaskState
    from .task_group import ParsedTask, TaskGroup


#: Ceiling on the leftover-changes preview spliced into a work prompt. The text
#: is interpolated from ``git status``, whose size is a property of the repo, not
#: of claudetm: a session killed mid-way through a generated-file rewrite can
#: leave thousands of paths behind. Uncapped, that one block would crowd out the
#: task itself. Truncation is marked rather than silent, so neither the agent nor
#: a human reading the log mistakes a cut-off list for the whole tree.
LEFTOVER_PREVIEW_MAX_LINES = 40
LEFTOVER_PREVIEW_MAX_CHARS = 2000
_TRUNCATION_MARKER = "… [truncated — run `git status` yourself for the full list]"


def _capped(status: str) -> str:
    """Trim a porcelain status to something that fits in a prompt."""
    lines = status.splitlines()
    truncated = len(lines) > LEFTOVER_PREVIEW_MAX_LINES
    text = "\n".join(lines[:LEFTOVER_PREVIEW_MAX_LINES])
    if len(text) > LEFTOVER_PREVIEW_MAX_CHARS:
        text = text[:LEFTOVER_PREVIEW_MAX_CHARS]
        truncated = True
    return f"{text}\n{_TRUNCATION_MARKER}" if truncated else text


class _TaskRunnerSessionMixin:
    """Mixin providing run_work_session and update_progress to TaskRunner.

    Concrete attribute stubs allow mypy to type-check cross-mixin references;
    their real values are set by TaskRunner.__init__.
    """

    # Attribute stubs — real values provided by TaskRunner.__init__
    agent: AgentWrapper
    state_manager: StateManager
    logger: TaskLogger | None
    last_session_output: str

    # Method stubs — real implementations in TaskRunner
    def parse_tasks(self, plan: str) -> list[str]:
        """Parse tasks from plan markdown."""
        raise NotImplementedError

    def is_task_complete(self, plan: str, task_index: int) -> bool:
        """Check if a task is already marked as complete."""
        raise NotImplementedError

    def _get_group_context(
        self,
        state: TaskState,
        plan: str | None = None,
        task_index: int | None = None,
    ) -> dict | None:
        """Get PR group context for a task (defaults to the current one)."""
        raise NotImplementedError

    def _get_parsed_tasks(self, plan: str) -> tuple[list[ParsedTask], list[TaskGroup]]:
        """Get parsed tasks and groups, with caching."""
        raise NotImplementedError

    # ------------------------------------------------------------------

    def _leftover_changes(self) -> str | None:
        """``git status --porcelain`` for the project tree, or None if unreadable.

        Probed in the project directory rather than the process cwd, which a
        caller may have moved. A failed probe (no git, not a repo, timeout) is
        never read as leftovers: inventing a half-finished tree out of a broken
        probe would tell the agent to "finish" work that does not exist.

        Returns:
            The porcelain output when the tree is dirty, else None.
        """
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "--ignore-submodules=dirty"],
                cwd=str(self.state_manager.state_dir.parent),
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            return None
        return result.stdout.strip() or None

    def _continuation_note(self, state: TaskState) -> str:
        """Tell the agent when the tree already holds a previous attempt's work.

        A session that stops before committing leaves its half-finished changes
        in the shared checkout. Re-entering that task with a plain prompt is the
        worst case: the agent reads a working tree full of edits it did not make
        and has no way to know whether to finish them, redo them, or revert
        them — so it does whichever it guesses.

        Two ways a task gets re-entered, and only one of them used to say so:

        - the orchestrator judged the session unfinished and retried it
          (``task_finish_attempts``) — a graceful path it can count; and
        - **the run died mid-session** — Ctrl+C at the wrong moment, the machine
          losing power, an OOM kill — and a human ran ``claudetm resume``.
          Nothing incremented a counter, because nothing got to run. The
          counter-only note was therefore silent in exactly the case where the
          leftover diff is largest and least explicable.

        So the note is driven by the **repository**, the same evidence every
        other stage trusts over a report: a dirty tree entering a work session
        means a previous attempt at this task stopped mid-flight, whatever the
        counters say.

        Args:
            state: Current task state (read for the retry count only).

        Returns:
            The note to splice into the task description, or "" when the tree is
            clean and no retry is in progress.
        """
        leftovers = self._leftover_changes()
        if not leftovers and not state.task_finish_attempts:
            return ""

        if state.task_finish_attempts:
            lead = (
                f"**Retry {state.task_finish_attempts}** — the previous session on this task "
                "stopped before committing."
            )
        else:
            lead = (
                "**Continuing an interrupted session** — this task was already started and the "
                "run stopped before it committed (Ctrl+C, a crash, or the machine going down)."
            )

        note = (
            f"\n{lead} `git status`/`git diff` FIRST — before you plan or edit anything. The "
            "uncommitted changes in this checkout are that attempt's work on THIS task: read "
            "them, carry on from where they stop, and ship them in your commit. Do not redo "
            "work that is already there and do not revert it. Discard a change only when you "
            "can positively identify it as a tooling dropping (a regenerated lockfile, a build "
            "artifact) rather than task work.\n"
            "\n**Never throw the leftovers away.** No `git checkout -- .`, `git restore`, "
            "`git stash`, `git reset --hard`, `git clean` — none of it is recoverable, and it "
            "is real work already done on this task. Starting over from a clean tree is the one "
            "outcome that is always wrong here.\n"
        )
        if leftovers:
            note += f"\nLeftover changes:\n```\n{_capped(leftovers)}\n```\n"
        return note

    def run_work_session(self, state: TaskState) -> str:
        """Run a single work session.

        Runs the current task via the agent wrapper.

        Args:
            state: Current task state.

        Returns:
            Status string describing what happened:

            - ``"skipped_already_complete"``: the current task was already
              checked off in the plan; only the task index was advanced.
            - ``"ran"``: an agent work session executed to completion.
            - ``"ran_incomplete"``: a session ran but the SDK reported an error
              terminal result (max turns, budget cap, mid-execution error), so
              the task cannot be assumed done. Distinct from ``"ran"`` so
              callers do not check it off.
            - ``"no_tasks_remaining"``: the task index is past the end of the
              plan; no work was started. Distinct from ``"ran"`` so callers
              only mark tasks complete when work actually ran.

        Raises:
            NoPlanFoundError: If no plan file exists.
            NoTasksFoundError: If the plan contains no tasks.
            WorkSessionError: If the work session fails.
        """
        from .task_runner_errors import NoPlanFoundError, NoTasksFoundError  # noqa: PLC0415

        # Get current task from plan
        plan = self.state_manager.load_plan()
        if not plan:
            raise NoPlanFoundError()

        try:
            tasks = self.parse_tasks(plan)
        except Exception as e:
            from .task_runner_errors import TaskRunnerError  # noqa: PLC0415

            raise TaskRunnerError(f"Failed to parse plan: {e}") from e

        if not tasks:
            raise NoTasksFoundError(plan)

        if state.current_task_index >= len(tasks):
            # All tasks processed
            return "no_tasks_remaining"

        current_task = tasks[state.current_task_index]

        # Check if task is already complete
        if self.is_task_complete(plan, state.current_task_index):
            console.newline()
            console.success(
                f"Task #{state.current_task_index + 1} already complete: {current_task}"
            )
            state.current_task_index += 1
            self.state_manager.save_state(state)
            return "skipped_already_complete"

        # Parse task complexity to determine which model to use
        complexity, cleaned_task = parse_task_complexity(current_task)
        target_model = TaskComplexity.get_model_name_for_complexity(complexity)

        # Get PR/group context for this task (reuses _get_group_context for DRY)
        group_context = self._get_group_context(state, plan)
        if group_context:
            pr_name = group_context["group_name"]
            is_last_in_group = group_context["is_last_in_group"]
            remaining_in_group = group_context["remaining_in_group"]
            completed_in_group = group_context["completed_tasks"]
        else:
            # Fallback for edge cases (shouldn't happen in normal operation)
            pr_name = "Default"
            is_last_in_group = True
            remaining_in_group = 0
            completed_in_group = []

        # Load context safely
        try:
            context = self.state_manager.load_context_for_prompt()
        except Exception as e:
            console.warning(f"Could not load context: {e}")
            context = ""

        # Build task description
        try:
            goal = self.state_manager.load_goal()
        except Exception as e:
            console.warning(f"Could not load goal: {e}")
            goal = "Complete the assigned task"

        # Get context lines from parsed task if available
        parsed_tasks, _ = self._get_parsed_tasks(plan)
        context_refs = ""
        if state.current_task_index < len(parsed_tasks):
            parsed_task = parsed_tasks[state.current_task_index]
            if parsed_task.context_lines:
                context_refs = "\nReferences:\n"
                for ref in parsed_task.context_lines:
                    context_refs += f"  - {ref}\n"

        retry_note = self._continuation_note(state)

        # A resumed task does not fan out. `retry_note` is non-empty exactly
        # when the tree already holds a previous attempt's uncommitted work, and
        # that is the worst possible ground for a fan-out: the brief argues for
        # cutting the task into big disjoint pieces, while the note explains
        # that pieces of it are already half-written by someone else. The lead
        # cannot hand a worker an exclusive file set it can vouch for, workers
        # pay a full cold start each to rediscover a diff the lead can already
        # see, and a fan-out that failed once (a backgrounded worker, an
        # overrun) re-runs at N agents' cost on the retry that exists because of
        # it. Finish the leftover work in one agent, then let the next task
        # split cleanly.
        #
        # A `[quick]` task does not fan out either. The planner has already
        # classified it as a simple fix, a config change, a small tweak — and
        # routed it to Haiku on exactly that judgement. There is no big task
        # here to cut up, so the brief's own answer is guaranteed to be "zero
        # workers"; all it can do is add ~1.4k tokens of prose about a decision
        # already made, to the cheapest sessions in the run. Fan-out stays a
        # live option for every tier above it, where the lead judges its own
        # task, which is the one place that judgement can be made.
        small_task = complexity is TaskComplexity.QUICK
        may_fan_out = state.options.parallel and not retry_note and not small_task
        if state.options.parallel and retry_note:
            console.detail("   (resuming unfinished work — this session runs solo)")
        elif state.options.parallel and small_task:
            console.detail("   (quick task — this session runs solo)")

        task_description = f"""Goal: {goal}

Current Task (#{state.current_task_index + 1}): {cleaned_task}
{context_refs}{retry_note}
Please complete this task."""

        console.newline()
        console.info(f"Working on task #{state.current_task_index + 1}: {cleaned_task}")
        console.detail(
            f"PR: {pr_name} | Complexity: {complexity.value} → Model: {target_model.value}"
        )
        if not is_last_in_group:
            console.detail(f"   ({remaining_in_group} more task(s) in this PR group)")

        # Log the prompt
        if self.logger:
            self.logger.log_prompt(task_description)

        # Get current branch to pass to agent. An explicit --branch override takes
        # precedence and is marked mandated, so the work prompt instructs the agent to
        # use that exact name instead of inventing one (prevents same-task PR collisions).
        from .task_runner import get_current_branch  # noqa: PLC0415

        branch_override = state.options.branch_override
        current_branch = get_current_branch()

        # Build PR group info for agent context (always provide for better task execution)
        pr_group_info = {
            "name": pr_name,
            "branch": branch_override or current_branch,
            "branch_mandated": branch_override is not None,
            "completed_tasks": completed_in_group,
            "remaining_tasks": remaining_in_group,
        }

        # Determine if agent should create PR
        # pr_per_task=True: always create PR after each task
        # pr_per_task=False (default): only create PR on last task in group
        should_create_pr = state.options.pr_per_task or is_last_in_group

        # Set task context for Claude prefix display [claude HH:MM:SS N/M]
        set_task_context(state.current_task_index + 1, len(tasks))

        # Load coding style guide for token-efficient style injection
        try:
            coding_style = self.state_manager.load_coding_style()
        except Exception as e:
            console.warning(f"Could not load coding style: {e}")
            coding_style = None

        # Run work session with model routing based on task complexity
        try:
            model_type = target_model
            # Get target branch from config for rebase instructions
            config = get_config()
            target_branch = config.git.target_branch
            result = self.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=model_type,
                # With an override, point required_branch at it too so the prompt is consistent
                # (no "you're on main → create a branch" line fighting the mandated branch).
                required_branch=branch_override or current_branch,
                create_pr=should_create_pr,
                pr_group_info=pr_group_info,
                target_branch=target_branch,
                coding_style=coding_style,
                # Permission to split THIS task across hive-worker subagents,
                # not an instruction to. Off leaves the prompt byte-identical to
                # the single-agent one, and registers no worker definitions.
                parallel=may_fan_out,
                max_parallel=hive_max_parallel(),
                # Measured per session, not once at import: an unattended run
                # lasts days and the box it shares changes underneath it. Only
                # measured when it can be used — the brief is the only reader.
                machine=(
                    describe_machine(str(self.state_manager.state_dir.parent))
                    if may_fan_out
                    else ""
                ),
                # The project's own specialists, so the lead dispatches them
                # for matching pieces. Read per session — the project can add
                # agents while a long run is underway.
                project_agents=(
                    list_project_agents(str(self.state_manager.state_dir.parent))
                    if may_fan_out
                    else None
                ),
            )
        except AgentError:
            if self.logger:
                self.logger.log_error("Agent error during work session")
            raise
        except Exception as e:
            if self.logger:
                self.logger.log_error(str(e))
            raise WorkSessionError(
                state.current_task_index,
                current_task,
                e,
            ) from e
        finally:
            # Clear task context after work session completes
            clear_task_context()

        # Log the response
        if self.logger and result.get("output"):
            self.logger.log_response(result.get("output", ""))

        # Expose the session output so the orchestrator can distil it into
        # accumulated context.md learnings after the task is marked complete.
        self.last_session_output = result.get("output", "") or ""

        # The SDK's terminal ResultMessage is authoritative about whether the
        # session reached its own end. An error result (max turns, budget cap,
        # error_during_execution) means the agent was cut off mid-task — the
        # caller must not check the task off on the strength of it.
        if result.get("success") is False:
            subtype = result.get("subtype") or "error"
            console.warning(f"Work session ended early ({subtype}) - task is not done")
            return "ran_incomplete"

        return "ran"

    def update_progress(
        self,
        state: TaskState,
        result: dict | None = None,
    ) -> None:
        """Update progress tracker after task completion.

        Reloads plan from disk to get latest completion status.

        Args:
            state: Current task state.
            result: Optional result dict with output from work session.
        """
        # Reload plan from disk to get latest [x] markers
        plan = self.state_manager.load_plan()
        if not plan:
            return

        tasks = self.parse_tasks(plan)
        if not tasks:
            return

        current_task = (
            tasks[state.current_task_index] if state.current_task_index < len(tasks) else ""
        )

        progress_lines = [
            "# Progress Tracker\n",
            f"**Session:** {state.session_count}",
            f"**Current Task:** {state.current_task_index + 1} of {len(tasks)}\n",
            "## Task List\n",
        ]

        # Add all tasks with their status
        for i, task in enumerate(tasks):
            is_complete = self.is_task_complete(plan, i)
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

            progress_lines.append(f"- {status} {marker} **Task {i + 1}:** {task}")

        # Add latest result if available
        if result and result.get("output"):
            progress_lines.extend(
                [
                    "\n## Latest Completed",
                    f"**Task {state.current_task_index + 1}:** {current_task}\n",
                    "### Summary",
                    result.get("output", "Completed"),
                ]
            )

        progress = "\n".join(progress_lines)

        try:
            self.state_manager.save_progress(progress)
        except Exception as e:
            console.warning(f"Could not save progress: {e}")


__all__ = ["_TaskRunnerSessionMixin"]
