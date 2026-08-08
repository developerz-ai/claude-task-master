"""Hive check-off mixin for the working stage.

The working stage checks off exactly one task per session — unless a hive lead
ran a whole PR-group batch, in which case *what the session actually finished*
has to be read back out of the lead's completion manifest. That reading is the
one place where an agent's own report influences state, so it lives here on its
own, with the rules that make it safe stated in full.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import console
from .hive import HiveBatch, has_completion_manifest, parse_completed_task_numbers

if TYPE_CHECKING:
    from .orchestrator import WorkLoopOrchestrator
    from .state import TaskState


class _LoopWorkingHiveMixin:
    """Mixin providing the batch-aware check-off to the working stage."""

    _orc: WorkLoopOrchestrator  # set by OrchestratorLoop.__init__

    @staticmethod
    def _describe_completed(task_desc: str, completed_indices: list[int]) -> str:
        """Describe what a session completed, for the ``task.completed`` webhook.

        Unchanged (the task's own description) for the ordinary one-task
        session; a hive batch names every task number it closed, so a consumer
        is not told a three-task session finished one task.

        Args:
            task_desc: Description of the task the session started on.
            completed_indices: Zero-based indices checked off (non-empty).

        Returns:
            The description to publish.
        """
        if len(completed_indices) <= 1:
            return task_desc
        numbers = ", ".join(f"#{index + 1}" for index in sorted(completed_indices))
        return f"{len(completed_indices)} tasks ({numbers}) - starting with: {task_desc}"

    def _check_off_finished_tasks(
        self,
        state: TaskState,
        plan: str,
        completed_task_index: int,
        *,
        session_unfinished: bool,
    ) -> tuple[list[int], int | None]:
        """Check off what the finished session actually completed.

        One task per session outside hive mode. A hive lead runs a whole PR
        group batch, so it reports which of them it finished with a manifest
        line (``TASKS COMPLETE: 3, 4, 6``).

        Why trusting that line is safe here, given "a session's own report is
        not evidence": the manifest can only ever *narrow* a set the
        orchestrator itself computed (``batch.numbers`` — every index is an
        incomplete task of the current group, and hive-core drops anything
        outside it), and it is only read after the repository-level unfinished
        probe passed, i.e. the SDK reported a clean terminal result AND the
        working tree is clean, so the work is committed. The manifest never
        widens what may be checked off and never overrides the probe: when the
        session was cut off (``session_unfinished``) it is ignored entirely.

        Three readings of the manifest, deliberately distinct:

        - **absent** — the lead forgot the line. Fall back to exactly today's
          behaviour (check off the current task only); a missing line must
          neither mass-check-off nor stall the run.
        - **present but empty** — the lead is explicitly reporting it finished
          none of the batch. Check off *nothing*: marking a task the lead just
          said it did not do silently loses that work. The same task re-runs,
          bounded by ``--max-sessions`` and by the tracker's loop detection
          (``max_same_task_attempts``), which is the right outcome for a lead
          that keeps reporting no progress.
        - **numbers** — check those off, and report the lowest task of the
          batch still open so the caller resumes there.

        Args:
            state: Current mutable task state; ``current_task_index`` is moved
                to the highest checked-off task (the caller's downstream
                group/PR logic keys off it).
            plan: The plan markdown just loaded from disk.
            completed_task_index: The index the session started on.
            session_unfinished: True when the session failed its contract but
                the retry budget was spent — the manifest is not read at all.

        Returns:
            ``(checked_off_indices, next_working_index)``. ``next_working_index``
            is None when the group may proceed to its normal end-of-group check,
            or the index the run must continue at when the batch left tasks open.
        """
        orc = self._orc
        batch = getattr(orc.task_runner, "last_hive_batch", None)

        def _single() -> tuple[list[int], int | None]:
            orc.task_runner.mark_task_complete(plan, completed_task_index)
            console.success(f"Task #{completed_task_index + 1} marked complete in plan.md")
            return [completed_task_index], None

        # Type-checked rather than truth-tested: the attribute is read off a
        # component callers routinely substitute (a task runner double, or one
        # predating hive mode), and anything that is not a real batch must take
        # today's path instead of being fed to the manifest parser.
        if not isinstance(batch, HiveBatch) or session_unfinished:
            return _single()

        output = getattr(orc.task_runner, "last_session_output", "") or ""
        if not has_completion_manifest(output):
            console.warning(
                "Hive session reported no completion manifest - "
                f"checking off only task #{completed_task_index + 1}"
            )
            return _single()

        done = parse_completed_task_numbers(output, allowed=batch.numbers)
        if not done:
            console.warning(
                f"Hive session reported completing none of its {batch.size} tasks - "
                "nothing checked off, retrying the batch"
            )
            return [], completed_task_index

        indices = [number - 1 for number in done]
        orc.task_runner.mark_tasks_complete(plan, indices)
        numbers = ", ".join(f"#{number}" for number in done)
        console.success(
            f"Hive session completed {len(indices)}/{batch.size} tasks "
            f"({numbers}) - marked complete in plan.md"
        )
        # Downstream (`is_last_task_in_group`, the +1 advance) reads the current
        # index as "the task just completed", so point it at the highest one.
        state.current_task_index = max(indices)

        remaining = [index for index in batch.indices if index not in set(indices)]
        if not remaining:
            return indices, None
        # A task the lead skipped over sits BELOW the highest completed one, so
        # the plain +1 advance would step past it and strand it unfinished
        # forever. Resume at the lowest still-open task of the group instead —
        # for a batch with no gaps that is exactly what +1 would have produced.
        return indices, min(remaining)


__all__ = ["_LoopWorkingHiveMixin"]
