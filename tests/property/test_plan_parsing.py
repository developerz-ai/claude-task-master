"""Property-based tests for plan parsing.

Tests the invariants and properties of plan markdown parsing,
including task extraction and completion tracking.
"""

import re

from hypothesis import given, settings
from hypothesis import strategies as st

# Define strategies for plan content
# Use printable ASCII characters to ensure tasks are parseable
# Exclude control chars, brackets, and problematic whitespace
PRINTABLE_TASK_CHARS = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 !@#$%^&*()-_=+;:'\",.<>?/"
)

task_name_strategy = st.text(
    min_size=1,
    max_size=100,
    alphabet=PRINTABLE_TASK_CHARS,
).filter(lambda x: x.strip())  # Ensure non-empty after stripping

pr_group_name_strategy = st.text(
    min_size=1,
    max_size=50,
    alphabet=PRINTABLE_TASK_CHARS,
).filter(lambda x: x.strip())  # Ensure non-empty after stripping
task_type_strategy = st.sampled_from(["quick", "coding", "general", "review", None])


def generate_task_line(
    task_name: str, completed: bool = False, task_type: str | None = None
) -> str:
    """Generate a markdown task line."""
    checkbox = "[x]" if completed else "[ ]"
    type_prefix = f"`[{task_type}]` " if task_type else ""
    return f"- {checkbox} {type_prefix}{task_name}"


def parse_tasks(plan: str) -> list[tuple[str, bool]]:
    """Parse tasks from plan markdown.

    Returns list of (task_name, is_completed) tuples.
    """
    tasks = []
    for line in plan.split("\n"):
        line = line.strip()

        # Match task lines: - [ ] or - [x]
        match = re.match(r"^-\s*\[([ xX])\]\s*(.+)$", line)
        if match:
            is_completed = match.group(1).lower() == "x"
            task_name = match.group(2).strip()
            tasks.append((task_name, is_completed))

    return tasks


def count_completed_tasks(plan: str) -> int:
    """Count completed tasks in a plan."""
    return sum(1 for _, completed in parse_tasks(plan) if completed)


def count_total_tasks(plan: str) -> int:
    """Count total tasks in a plan."""
    return len(parse_tasks(plan))


class TestPlanParsingProperties:
    """Property-based tests for plan parsing."""

    @given(
        task_names=st.lists(task_name_strategy, min_size=0, max_size=20),
    )
    @settings(max_examples=100)
    def test_all_tasks_are_found(self, task_names: list):
        """All task lines should be found by the parser."""
        plan = "## Task List\n\n"
        for name in task_names:
            plan += generate_task_line(name) + "\n"

        parsed = parse_tasks(plan)
        assert len(parsed) == len(task_names)

    @given(
        task_count=st.integers(min_value=0, max_value=50),
        completed_count=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=100)
    def test_completed_count_matches(self, task_count: int, completed_count: int):
        """Completed task count should match actual completed tasks."""
        completed_count = min(completed_count, task_count)

        plan = "## Task List\n\n"
        for i in range(task_count):
            is_completed = i < completed_count
            plan += generate_task_line(f"Task {i}", completed=is_completed) + "\n"

        assert count_completed_tasks(plan) == completed_count
        assert count_total_tasks(plan) == task_count

    @given(
        task_names=st.lists(task_name_strategy, min_size=1, max_size=20),
        completion_flags=st.lists(st.booleans(), min_size=1, max_size=20),
    )
    @settings(max_examples=100)
    def test_completion_status_preserved(self, task_names: list, completion_flags: list):
        """Task completion status should be preserved through parsing."""
        # Match list lengths
        min_len = min(len(task_names), len(completion_flags))
        task_names = task_names[:min_len]
        completion_flags = completion_flags[:min_len]

        plan = "## Task List\n\n"
        for name, completed in zip(task_names, completion_flags, strict=True):
            plan += generate_task_line(name, completed=completed) + "\n"

        parsed = parse_tasks(plan)

        for i, (_name, completed) in enumerate(zip(task_names, completion_flags, strict=True)):
            # Task names might have the type prefix stripped
            assert parsed[i][1] == completed  # Completion status preserved

    @given(
        task_names=st.lists(task_name_strategy, min_size=0, max_size=20),
        task_types=st.lists(task_type_strategy, min_size=0, max_size=20),
    )
    @settings(max_examples=100)
    def test_task_types_dont_break_parsing(self, task_names: list, task_types: list):
        """Task type annotations should not break parsing."""
        min_len = min(len(task_names), len(task_types)) if task_types else len(task_names)
        task_names = task_names[:min_len]
        task_types = (task_types + [None] * len(task_names))[:min_len]

        plan = "## Task List\n\n"
        for name, task_type in zip(task_names, task_types, strict=True):
            plan += generate_task_line(name, task_type=task_type) + "\n"

        parsed = parse_tasks(plan)
        assert len(parsed) == min_len


class TestPlanPRGroupProperties:
    """Property-based tests for PR group parsing."""

    @given(
        group_count=st.integers(min_value=1, max_value=10),
        tasks_per_group=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=50)
    def test_tasks_in_groups_are_found(self, group_count: int, tasks_per_group: int):
        """All tasks within PR groups should be found."""
        plan = "## Task List\n\n"
        total_tasks = 0

        for g in range(group_count):
            plan += f"### PR {g + 1}: Group {g + 1}\n"
            for t in range(tasks_per_group):
                plan += generate_task_line(f"Task {g}.{t}") + "\n"
                total_tasks += 1
            plan += "\n"

        parsed = parse_tasks(plan)
        assert len(parsed) == total_tasks

    @given(
        group_names=st.lists(pr_group_name_strategy, min_size=1, max_size=5),
        tasks_per_group=st.lists(st.integers(min_value=1, max_value=10), min_size=1, max_size=5),
    )
    @settings(max_examples=50)
    def test_varying_tasks_per_group(self, group_names: list, tasks_per_group: list):
        """Different task counts per group should work correctly."""
        min_len = min(len(group_names), len(tasks_per_group))
        group_names = group_names[:min_len]
        tasks_per_group = tasks_per_group[:min_len]

        plan = "## Task List\n\n"
        total_tasks = sum(tasks_per_group)

        for g, (name, count) in enumerate(zip(group_names, tasks_per_group, strict=True)):
            plan += f"### PR {g + 1}: {name}\n"
            for _t in range(count):
                plan += generate_task_line(f"Task {g}.{_t}") + "\n"
            plan += "\n"

        parsed = parse_tasks(plan)
        assert len(parsed) == total_tasks


class TestPlanInvariants:
    """Test invariants that should always hold for plans."""

    @given(
        plan_content=st.text(min_size=0, max_size=1000),
    )
    @settings(max_examples=100, deadline=1500)
    def test_completed_never_exceeds_total(self, plan_content: str):
        """Completed tasks should never exceed total tasks."""
        completed = count_completed_tasks(plan_content)
        total = count_total_tasks(plan_content)

        assert completed <= total

    @given(
        task_names=st.lists(task_name_strategy, min_size=0, max_size=20),
    )
    @settings(max_examples=100)
    def test_empty_plan_has_no_tasks(self, task_names: list):
        """Empty or whitespace-only plan should have no tasks."""
        empty_plans = [
            "",
            "   ",
            "\n\n\n",
            "## Task List\n\n## Success Criteria\n",
            "No tasks here",
        ]

        for plan in empty_plans:
            assert count_total_tasks(plan) == 0

    @given(
        task_names=st.lists(task_name_strategy, min_size=1, max_size=20),
    )
    @settings(max_examples=50)
    def test_marking_all_complete_works(self, task_names: list):
        """Marking all tasks complete should result in 100% completion."""
        plan = "## Task List\n\n"
        for name in task_names:
            plan += generate_task_line(name, completed=True) + "\n"

        assert count_completed_tasks(plan) == len(task_names)
        assert count_total_tasks(plan) == len(task_names)

    @given(
        task_names=st.lists(task_name_strategy, min_size=1, max_size=20),
    )
    @settings(max_examples=50)
    def test_no_tasks_complete_initially(self, task_names: list):
        """New plan with no completions should have 0 completed."""
        plan = "## Task List\n\n"
        for name in task_names:
            plan += generate_task_line(name, completed=False) + "\n"

        assert count_completed_tasks(plan) == 0
        assert count_total_tasks(plan) == len(task_names)
