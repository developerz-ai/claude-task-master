"""Context, task-count, and git helpers for OrchestratorLoop.

Mixin providing:
  - _get_total_tasks / _get_completed_tasks
  - _accumulate_context / _build_completed_tasks_summary
  - _get_current_branch / _get_target_branch / _checkout_to_main
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from . import console
from .plan_parsing import count_completed_tasks, is_task_complete, parse_task_descriptions
from .state import TaskState

if TYPE_CHECKING:
    from .orchestrator import WorkLoopOrchestrator

logger = logging.getLogger(__name__)


class _LoopContextMixin:
    """Mixin that provides context accumulation and utility helpers to OrchestratorLoop."""

    _orc: WorkLoopOrchestrator  # set by OrchestratorLoop.__init__

    # ------------------------------------------------------------------
    # Task-count helpers
    # ------------------------------------------------------------------

    def _get_total_tasks(self, state: TaskState) -> int:
        """Return total task count from the plan."""
        try:
            plan = self._orc.state_manager.load_plan()
            if plan:
                tasks = parse_task_descriptions(plan)
                return len(tasks)
        except Exception:
            pass
        return 0

    def _get_completed_tasks(self, state: TaskState) -> int:
        """Return completed task count from the plan.

        Falls back to ``state.current_task_index`` when the plan is unavailable.
        """
        try:
            plan = self._orc.state_manager.load_plan()
            if plan:
                return count_completed_tasks(plan)
        except Exception:
            pass
        return state.current_task_index

    # ------------------------------------------------------------------
    # Context accumulation
    # ------------------------------------------------------------------

    def _accumulate_context(self, state: TaskState) -> None:
        """Distil the just-finished work session into context.md.

        Best-effort: failures are logged and swallowed. KeyboardInterrupt
        still propagates so Ctrl+C interrupts the run.

        Args:
            state: Current task state (``session_count`` already incremented).
        """
        orc = self._orc
        session_output = getattr(orc.task_runner, "last_session_output", "") or ""
        if not session_output.strip():
            return
        try:
            existing_context = orc.context_accumulator.get_context_for_prompt()
            learnings = orc.agent.extract_session_learnings(
                session_output=session_output,
                existing_context=existing_context,
            )
            if learnings.strip():
                orc.context_accumulator.add_session_summary(state.session_count, learnings.strip())
                console.detail(f"context.md updated from session {state.session_count}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.warning("Context accumulation failed (non-fatal): %s", e)
            console.detail(f"Context accumulation skipped (non-fatal): {e}")

    def _build_completed_tasks_summary(self, state: TaskState) -> str:
        """Summarise completed tasks + merged PRs for the verification prompt.

        Args:
            state: Current task state.

        Returns:
            Markdown bullet list, or ``""`` when nothing is available.
        """
        orc = self._orc
        lines: list[str] = []
        try:
            plan = orc.state_manager.load_plan()
            if plan:
                lines.extend(
                    f"- {desc}"
                    for index, desc in enumerate(parse_task_descriptions(plan))
                    if is_task_complete(plan, index)
                )
        except Exception:
            pass

        if state.prs_created or state.prs_merged:
            pr_line = f"- PRs: {state.prs_created} created, {state.prs_merged} merged"
            if state.last_counted_pr_merged is not None:
                pr_line += f" (last merged: #{state.last_counted_pr_merged})"
            lines.append(pr_line)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Git helpers
    # ------------------------------------------------------------------

    def _get_target_branch(self) -> str:
        """Return the configured target branch (main/master/etc.)."""
        # Deferred import so tests can patch orchestrator_loop.get_config
        import claude_task_master.core.orchestrator_loop as _oloop  # noqa: PLC0415

        config = _oloop.get_config()
        return config.git.target_branch

    def _checkout_to_main(self) -> bool:
        """Checkout to the configured target branch.

        Returns:
            True if checkout succeeded, False otherwise.
        """
        # Deferred imports so tests can patch orchestrator_loop.subprocess and .console
        import claude_task_master.core.orchestrator_loop as _oloop  # noqa: PLC0415

        _subprocess = _oloop.subprocess
        _console = _oloop.console
        target_branch = self._get_target_branch()
        _console.info(f"Checking out to {target_branch}...")
        try:
            _subprocess.run(
                ["git", "checkout", target_branch],
                check=True,
                capture_output=True,
                text=True,
            )
            _subprocess.run(
                ["git", "pull"],
                check=True,
                capture_output=True,
                text=True,
            )
            _console.success(f"Switched to {target_branch}")
            return True
        except _subprocess.CalledProcessError as e:
            _console.warning(f"Failed to checkout to {target_branch}: {e}")
            return False

    @staticmethod
    def _get_current_branch() -> str | None:
        """Return the current git branch name, or None if not in a git repo."""
        # Deferred import so tests can patch orchestrator_loop.subprocess
        import claude_task_master.core.orchestrator_loop as _oloop  # noqa: PLC0415

        try:
            result = _oloop.subprocess.run(
                ["git", "branch", "--show-current"],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() or None
        except Exception:
            return None


__all__ = ["_LoopContextMixin"]
