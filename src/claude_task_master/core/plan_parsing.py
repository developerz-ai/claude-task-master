"""Plan markdown parsing facade.

This module is the single entry point for reading task state out of a
``plan.md`` file. It is a thin facade over
:func:`claude_task_master.core.task_group.parse_tasks_with_groups`, plus a
line-based ``mark_task_complete`` that rewrites checkboxes in place.

Parsing semantics (inherited from the group parser):

- ``- [X]`` (uppercase X) counts as a task AND as complete.
- Checkbox lines inside a ``**Release checks:**`` section are ignored
  (the section ends at a blank line, a heading, or a ``---`` rule).
- Indented context bullets (``  - note``) are not tasks.
"""

from __future__ import annotations

from claude_task_master.core.task_group import parse_tasks_with_groups


def parse_task_descriptions(plan: str) -> list[str]:
    """Extract task descriptions from plan markdown.

    ``- [X]`` (uppercase X) counts as a task; checkbox lines inside a
    ``**Release checks:**`` section (until blank line/heading/``---``) are
    ignored; indented context bullets are not tasks.

    Args:
        plan: The plan markdown content.

    Returns:
        List of task description strings in order of appearance. Empty
        list for an empty plan.
    """
    tasks, _ = parse_tasks_with_groups(plan)
    return [t.description for t in tasks]


def is_task_complete(plan: str, task_index: int) -> bool:
    """Check whether the task at ``task_index`` is complete.

    ``- [X]`` (uppercase X) counts as complete; checkbox lines inside a
    ``**Release checks:**`` section (until blank line/heading/``---``) are
    ignored; indented context bullets are not tasks.

    Args:
        plan: The plan markdown content.
        task_index: Zero-based index of the task.

    Returns:
        True if the task exists and is marked complete, False otherwise
        (including out-of-range indices).
    """
    tasks, _ = parse_tasks_with_groups(plan)
    if 0 <= task_index < len(tasks):
        return tasks[task_index].is_complete
    return False


def mark_task_complete(plan: str, task_index: int) -> str:
    """Mark the task at ``task_index`` as complete and return updated markdown.

    Line-based reimplementation (does not use the group parser): lines are
    counted as tasks when their stripped form starts with ``- [ ]`` or
    ``- [x]`` (lowercase x only); the first ``- [ ]`` occurrence in the
    matching line is replaced with ``- [x]``. Note that this differs from
    the group parser: ``- [X]`` (uppercase X) lines are neither counted
    nor rewritten here, and ``**Release checks:**`` sections are not
    skipped.

    Args:
        plan: The plan markdown content.
        task_index: Zero-based index of the task to mark complete.

    Returns:
        Updated plan markdown, or the plan unchanged if ``task_index`` is
        out of range.
    """
    lines = plan.split("\n")
    count = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("- [ ]") or stripped.startswith("- [x]"):
            if count == task_index:
                lines[i] = line.replace("- [ ]", "- [x]", 1)
                break
            count += 1
    return "\n".join(lines)


def count_completed_tasks(plan: str) -> int:
    """Count completed tasks in plan markdown.

    ``- [X]`` (uppercase X) counts as complete; checkbox lines inside a
    ``**Release checks:**`` section (until blank line/heading/``---``) are
    ignored; indented context bullets are not tasks.

    Args:
        plan: The plan markdown content.

    Returns:
        Number of tasks marked complete.
    """
    tasks, _ = parse_tasks_with_groups(plan)
    return sum(1 for t in tasks if t.is_complete)
