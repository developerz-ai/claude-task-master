"""Task Group / PR - Group parsing and management for conversation reuse.

Tasks can be organized into PRs (Pull Requests) in the plan. Tasks within the
same PR share a conversation, allowing Claude to remember context from previous
tasks.

Plan format with PRs:
```markdown
### PR 1: Schema & Model Fixes

- [ ] `[coding]` Create migration
- [ ] `[coding]` Update model

### PR 2: Service Fixes

- [ ] `[coding]` Fix service spec
```

Also supports "Group" header format for backwards compatibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class TaskComplexity(Enum):
    """Task complexity levels for model selection.

    - CODING: Complex implementation tasks → Opus (smartest)
    - QUICK: Simple fixes, config changes → Haiku (fastest/cheapest)
    - GENERAL: Moderate complexity → Sonnet (balanced)
    - DEBUGGING_QA: Debugging/QA tasks → Sonnet 1M (deep context)
    """

    CODING = "coding"
    QUICK = "quick"
    GENERAL = "general"
    DEBUGGING_QA = "debugging-qa"

    @classmethod
    def get_model_for_complexity(cls, complexity: TaskComplexity) -> str:
        """Map task complexity to appropriate model name.

        Args:
            complexity: The task complexity level.

        Returns:
            Model name string ("opus", "sonnet", "haiku").
        """
        mapping = {
            cls.CODING: "opus",
            cls.QUICK: "haiku",
            cls.GENERAL: "sonnet",
            cls.DEBUGGING_QA: "sonnet_1m",
        }
        return mapping.get(complexity, "sonnet")


def parse_task_complexity(task_description: str) -> tuple[TaskComplexity, str]:
    """Parse task complexity tag from task description.

    Looks for `[coding]`, `[quick]`, `[general]`, or `[debugging-qa]` tags in the task.

    Args:
        task_description: The task description potentially containing a complexity tag.

    Returns:
        Tuple of (TaskComplexity, cleaned_task_description).
        Defaults to CODING if no tag found (prefer smarter model).
    """
    # Look for complexity tags in backticks: `[coding]`, `[quick]`, `[general]`, `[debugging-qa]`
    pattern = r"`\[(coding|quick|general|debugging-qa)\]`"
    match = re.search(pattern, task_description, re.IGNORECASE)

    if match:
        complexity_str = match.group(1).lower()
        # Remove the tag from the description
        cleaned = re.sub(pattern, "", task_description, flags=re.IGNORECASE).strip()

        complexity_map = {
            "coding": TaskComplexity.CODING,
            "quick": TaskComplexity.QUICK,
            "general": TaskComplexity.GENERAL,
            "debugging-qa": TaskComplexity.DEBUGGING_QA,
        }
        return complexity_map.get(complexity_str, TaskComplexity.CODING), cleaned

    # Default to CODING (prefer smarter model when uncertain)
    return TaskComplexity.CODING, task_description


@dataclass
class TaskGroup:
    """A group of related tasks that share a conversation (typically a PR).

    Tasks within the same group are executed using the same ClaudeSDKClient
    conversation, allowing Claude to remember context from previous tasks.

    Alias: This is also known as a "PR" (Pull Request) in the plan format.
    """

    id: str
    name: str
    task_indices: list[int] = field(default_factory=list)

    def __str__(self) -> str:
        return f"PR '{self.name}' ({len(self.task_indices)} tasks)"

    def __repr__(self) -> str:
        return f"TaskGroup(id={self.id!r}, name={self.name!r}, tasks={len(self.task_indices)})"

    @property
    def pr_number(self) -> int | None:
        """Extract PR number from id if available."""
        if self.id.startswith("pr_"):
            try:
                return int(self.id[3:])
            except ValueError:
                return None
        return None


# Alias for clarity
PullRequest = TaskGroup


@dataclass
class ParsedTask:
    """A task parsed from the plan with PR/group information."""

    index: int
    description: str
    group_id: str  # pr_1, pr_2, etc.
    group_name: str  # "Schema & Model Fixes", etc.
    is_complete: bool = False
    context_lines: list[str] = field(default_factory=list)

    @property
    def complexity(self) -> TaskComplexity:
        """Parse complexity from task description."""
        complexity, _ = parse_task_complexity(self.description)
        return complexity

    @property
    def cleaned_description(self) -> str:
        """Task description without complexity tag."""
        _, cleaned = parse_task_complexity(self.description)
        return cleaned

    @property
    def pr_id(self) -> str:
        """Alias for group_id for PR-centric code."""
        return self.group_id

    @property
    def pr_name(self) -> str:
        """Alias for group_name for PR-centric code."""
        return self.group_name

    def __str__(self) -> str:
        status = "[x]" if self.is_complete else "[ ]"
        return f"{status} {self.description}"


def parse_tasks_with_groups(plan: str) -> tuple[list[ParsedTask], list[TaskGroup]]:
    """Parse tasks and PRs/groups from plan markdown.

    Supports plans with explicit PRs:
    ```
    ### PR 1: Schema Changes
    - [ ] Task 1
    - [ ] Task 2

    ### PR 2: Service Fixes
    - [ ] Task 3
    ```

    Also supports "Group" format for backwards compatibility:
    ```
    ### Group 1: Schema Changes
    - [ ] Task 1
    ```

    And plans without groups (all tasks go in "default" group):
    ```
    - [ ] Task 1
    - [ ] Task 2
    ```

    Args:
        plan: The plan markdown content.

    Returns:
        Tuple of (list of ParsedTask, list of TaskGroup/PR).
    """
    tasks: list[ParsedTask] = []
    groups: list[TaskGroup] = []

    # Pattern to match PR/Group headers:
    # ### PR 1: Name, ### Group 1: Name, ## PR 1 - Name, etc.
    pr_pattern = re.compile(
        r"^#{2,3}\s+(?:PR|Group)\s*(\d+)(?::\s*|\s*[-–—]\s*)(.+)$", re.IGNORECASE
    )
    # Pattern to match tasks: - [ ] or - [x] followed by description
    task_pattern = re.compile(r"^-\s*\[([ xX])\]\s*(.+)$")

    current_group_id = "default"
    current_group_name = "Default"
    task_index = 0

    for raw_line in plan.split("\n"):
        stripped = raw_line.strip()

        # Check for PR/Group header
        pr_match = pr_pattern.match(stripped)
        if pr_match:
            pr_num = pr_match.group(1)
            pr_name = pr_match.group(2).strip()
            current_group_id = f"pr_{pr_num}"
            current_group_name = pr_name

            # Create new group if not exists
            if not any(g.id == current_group_id for g in groups):
                groups.append(TaskGroup(id=current_group_id, name=pr_name))
            continue

        # Check for task
        task_match = task_pattern.match(stripped)
        if task_match:
            is_complete = task_match.group(1).lower() == "x"
            description = task_match.group(2).strip()

            task = ParsedTask(
                index=task_index,
                description=description,
                group_id=current_group_id,
                group_name=current_group_name,
                is_complete=is_complete,
            )
            tasks.append(task)

            # Add task index to its group
            group = next((g for g in groups if g.id == current_group_id), None)
            if group is None:
                group = TaskGroup(id=current_group_id, name=current_group_name)
                groups.append(group)
            group.task_indices.append(task_index)

            task_index += 1
            continue

        # Check for context sublist item (indented bullet, not a checkbox)
        if (
            tasks
            and raw_line
            and raw_line[0] in (" ", "\t")
            and stripped.startswith("- ")
            and not stripped.startswith("- [ ]")
            and not stripped.startswith("- [x]")
            and not stripped.startswith("- [X]")
        ):
            context_text = stripped[2:].strip()
            if context_text:
                tasks[-1].context_lines.append(context_text)

    # If no explicit groups, ensure default group exists
    if not groups and tasks:
        groups.append(
            TaskGroup(
                id="default",
                name="Default",
                task_indices=list(range(len(tasks))),
            )
        )

    return tasks, groups


# Alias for PR-centric code
parse_tasks_with_prs = parse_tasks_with_groups


def get_group_for_task(task_index: int, tasks: list[ParsedTask]) -> str:
    """Get the group/PR ID for a task by its index.

    Args:
        task_index: Index of the task.
        tasks: List of parsed tasks.

    Returns:
        Group/PR ID string.
    """
    if task_index < len(tasks):
        return tasks[task_index].group_id
    return "default"


# Alias for PR-centric code
get_pr_for_task = get_group_for_task


def get_tasks_in_group(group_id: str, tasks: list[ParsedTask]) -> list[ParsedTask]:
    """Get all tasks belonging to a specific group/PR.

    Args:
        group_id: The group/PR ID to filter by.
        tasks: List of all parsed tasks.

    Returns:
        List of tasks in the specified group/PR.
    """
    return [t for t in tasks if t.group_id == group_id]


# Alias for PR-centric code
get_tasks_in_pr = get_tasks_in_group


def get_incomplete_tasks(tasks: list[ParsedTask]) -> list[ParsedTask]:
    """Get all incomplete tasks.

    Args:
        tasks: List of all parsed tasks.

    Returns:
        List of incomplete tasks.
    """
    return [t for t in tasks if not t.is_complete]


def summarize_groups(groups: list[TaskGroup], tasks: list[ParsedTask]) -> str:
    """Generate a summary of PRs/task groups.

    Args:
        groups: List of task groups/PRs.
        tasks: List of all parsed tasks.

    Returns:
        Human-readable summary string.
    """
    lines = [f"Found {len(groups)} PR(s) with {len(tasks)} total task(s):"]

    for group in groups:
        group_tasks = get_tasks_in_group(group.id, tasks)
        complete = sum(1 for t in group_tasks if t.is_complete)
        total = len(group_tasks)
        status = "✓" if complete == total else f"{complete}/{total}"
        lines.append(f"  • {group.name}: {status}")

    return "\n".join(lines)


# Alias for PR-centric code
summarize_prs = summarize_groups
