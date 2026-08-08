"""Hive-batch helpers for the work session.

Kept out of :mod:`.task_runner_session` so that module stays one readable
"run the current task" path: everything here is the *batch* shape of two
decisions the single-task path already makes — which model to route to, and
what text to hand the agent as its task.

Pure functions, no I/O — the batching rules themselves live in :mod:`.hive`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .agent_models import TaskComplexity

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .hive import HiveBatch
    from .task_group import ParsedTask

__all__ = [
    "build_hive_task_description",
    "hive_batch_complexity",
]


# Highest first. A hive lead does not run one task, it runs the batch: it plans
# the fan-out, judges which write sets are disjoint, reviews what the workers
# produced and owns the single commit. Routing that on the *first* task's tag
# would hand a batch containing a `[coding]` task to Haiku whenever the batch
# happened to open with a `[quick]` one. Routing on the hardest task in the
# batch can only over-provision, and over-provisioning a coordinator is the
# cheap mistake.
_COMPLEXITY_RANK: dict[TaskComplexity, int] = {
    TaskComplexity.CODING: 3,
    TaskComplexity.DEBUGGING_QA: 2,
    TaskComplexity.GENERAL: 1,
    TaskComplexity.QUICK: 0,
}


def hive_batch_complexity(
    parsed_tasks: Sequence[ParsedTask],
    batch: HiveBatch,
) -> TaskComplexity:
    """Return the highest complexity tag across the batch's tasks.

    Args:
        parsed_tasks: All tasks parsed from the plan, indexed by plan position.
        batch: The batch about to be handed to a hive lead.

    Returns:
        The most demanding :class:`TaskComplexity` in the batch. Falls back to
        ``CODING`` (the smartest tier) when the batch's indices cannot be
        resolved — the same "prefer the smarter model when uncertain" default
        :func:`~.agent_models.parse_task_complexity` uses for an untagged task.
    """
    complexities = [
        parsed_tasks[index].complexity for index in batch.indices if 0 <= index < len(parsed_tasks)
    ]
    if not complexities:
        return TaskComplexity.CODING
    return max(complexities, key=lambda complexity: _COMPLEXITY_RANK.get(complexity, 0))


def build_hive_task_description(
    goal: str,
    batch: HiveBatch,
    parsed_tasks: Sequence[ParsedTask],
    retry_note: str = "",
) -> str:
    """Build the task text handed to a hive lead session.

    The list is numbered with the *plan* numbers (1-based), because those are
    the numbers the lead has to quote back in its completion manifest — any
    other numbering makes the manifest unparseable against the batch.

    Args:
        goal: The run's overall goal.
        batch: The batch to work.
        parsed_tasks: All parsed tasks, used for each task's context references.
        retry_note: Optional note about a previous unfinished session.

    Returns:
        The task description (prompt-agnostic; the fan-out instructions and the
        manifest contract are added by the work prompt builder).
    """
    lines = [f"Goal: {goal}", ""]
    lines.append(
        f"PR group: {batch.group_name} — {batch.size} remaining task(s), all yours this session."
    )
    lines.append("")
    for number, description in zip(batch.numbers, batch.descriptions, strict=False):
        lines.append(f"Task #{number}: {description}")
        index = number - 1
        if 0 <= index < len(parsed_tasks):
            for ref in parsed_tasks[index].context_lines:
                lines.append(f"  - {ref}")
    if retry_note:
        lines.append(retry_note)
    lines.append("")
    lines.append("Please complete these tasks.")
    return "\n".join(lines)
