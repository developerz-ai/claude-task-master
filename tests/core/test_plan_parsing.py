"""Tests for the plan_parsing module."""

from __future__ import annotations

import pytest

from claude_task_master.core.plan_parsing import (
    count_completed_tasks,
    first_incomplete_task_index,
    is_task_complete,
    mark_task_complete,
    parse_task_descriptions,
)
from claude_task_master.core.task_group import parse_tasks_with_groups


class TestFirstIncompleteTaskIndex:
    """Tests for first_incomplete_task_index."""

    def test_returns_first_unchecked_index(self):
        """Should return the index of the first not-complete task."""
        plan = "- [x] One\n- [x] Two\n- [ ] Three\n- [ ] Four"
        assert first_incomplete_task_index(plan) == 2

    def test_first_task_incomplete(self):
        """Should return 0 when the first task is incomplete."""
        plan = "- [ ] One\n- [x] Two"
        assert first_incomplete_task_index(plan) == 0

    def test_all_complete_returns_task_count(self):
        """Should return the task count when every task is complete."""
        plan = "- [x] One\n- [x] Two"
        assert first_incomplete_task_index(plan) == 2

    def test_empty_plan_returns_zero(self):
        """Should return 0 for a plan with no tasks."""
        assert first_incomplete_task_index("") == 0

    def test_ignores_release_check_boxes(self):
        """Should ignore checkbox lines inside a Release checks section."""
        plan = "- [x] Real task\n**Release checks:**\n- [ ] Deploy verified\n"
        # Only the one real task exists and it is complete → count (1).
        assert first_incomplete_task_index(plan) == 1


class TestParseTaskDescriptions:
    """Tests for parse_task_descriptions."""

    def test_mixed_list_returns_descriptions_in_order(self):
        """Should return descriptions of checked and unchecked tasks in order."""
        plan = "- [ ] First task\n- [x] Second task\n- [ ] Third task"
        assert parse_task_descriptions(plan) == ["First task", "Second task", "Third task"]

    def test_complexity_tags_preserved_verbatim(self):
        """Should keep complexity tags like `[coding]` verbatim in descriptions."""
        plan = "- [ ] `[coding]` Implement parser\n- [x] `[quick]` Fix typo"
        assert parse_task_descriptions(plan) == [
            "`[coding]` Implement parser",
            "`[quick]` Fix typo",
        ]

    def test_empty_plan_returns_empty_list(self):
        """Should return an empty list for an empty plan."""
        assert parse_task_descriptions("") == []

    def test_plan_without_checkboxes_returns_empty_list(self):
        """Should return an empty list when the plan has no checkboxes."""
        plan = "# Plan\n\nSome prose.\n- A plain bullet\n1. A numbered item"
        assert parse_task_descriptions(plan) == []

    def test_indented_checkboxes_are_parsed(self):
        """Should parse indented checkboxes (group parser strips whitespace)."""
        plan = "  - [ ] Indented task\n- [ ] Top-level task"
        assert parse_task_descriptions(plan) == ["Indented task", "Top-level task"]

    def test_uppercase_x_counts_as_task(self):
        """Should parse `- [X]` checkboxes as tasks."""
        plan = "- [X] Done task\n- [ ] Open task"
        assert parse_task_descriptions(plan) == ["Done task", "Open task"]

    @pytest.mark.parametrize(
        "terminator",
        ["\n", "## Follow-up\n", "---\n"],
        ids=["blank_line", "heading", "horizontal_rule"],
    )
    def test_release_checks_section_ignored(self, terminator: str):
        """Should ignore checkboxes inside a **Release checks:** section."""
        plan = (
            "- [ ] Real task\n"
            "**Release checks:**\n"
            "- [ ] Check CI\n"
            "- [x] Check coverage\n"
            f"{terminator}"
            "- [ ] Other real task"
        )
        assert parse_task_descriptions(plan) == ["Real task", "Other real task"]

    def test_release_checks_section_to_end_of_plan_ignored(self):
        """Should ignore release checks that run to the end of the plan."""
        plan = "- [ ] Real task\n**Release checks:**\n- [ ] Check CI\n- [ ] Check docs"
        assert parse_task_descriptions(plan) == ["Real task"]

    def test_context_sub_bullets_do_not_become_tasks(self):
        """Should not treat indented context sub-bullets under a task as tasks."""
        plan = "- [ ] Main task\n  - note about the task\n  - another detail\n- [ ] Next task"
        assert parse_task_descriptions(plan) == ["Main task", "Next task"]

    def test_empty_descriptions_are_skipped(self):
        """Should skip checkbox lines whose description is empty."""
        plan = "- [ ] \n- [ ] Real task\n- [ ]"
        assert parse_task_descriptions(plan) == ["Real task"]


class TestIsTaskComplete:
    """Tests for is_task_complete."""

    def test_unchecked_task_returns_false(self):
        """Should return False for an unchecked `- [ ]` task."""
        plan = "- [ ] Open task\n- [x] Done task"
        assert is_task_complete(plan, 0) is False

    def test_checked_task_returns_true(self):
        """Should return True for a checked `- [x]` task."""
        plan = "- [ ] Open task\n- [x] Done task"
        assert is_task_complete(plan, 1) is True

    def test_uppercase_x_returns_true(self):
        """Should return True for an uppercase `- [X]` task."""
        plan = "- [X] Done task"
        assert is_task_complete(plan, 0) is True

    @pytest.mark.parametrize("index", [99, -1], ids=["too_large", "negative"])
    def test_out_of_range_index_returns_false(self, index: int):
        """Should return False for an out-of-range task index."""
        plan = "- [x] Done task\n- [ ] Open task"
        assert is_task_complete(plan, index) is False


class TestMarkTaskComplete:
    """Tests for mark_task_complete."""

    @pytest.mark.parametrize(
        ("index", "expected"),
        [
            (
                0,
                "- [x] Task one\n- [ ] Task two\n- [ ] Task three",
            ),
            (
                1,
                "- [ ] Task one\n- [x] Task two\n- [ ] Task three",
            ),
            (
                2,
                "- [ ] Task one\n- [ ] Task two\n- [x] Task three",
            ),
        ],
        ids=["first", "middle", "last"],
    )
    def test_marks_nth_checkbox(self, index: int, expected: str):
        """Should mark the Nth `- [ ]` as `- [x]` leaving other tasks untouched."""
        plan = "- [ ] Task one\n- [ ] Task two\n- [ ] Task three"
        assert mark_task_complete(plan, index) == expected

    @pytest.mark.parametrize("index", [99, -1], ids=["too_large", "negative"])
    def test_out_of_range_index_returns_plan_unchanged(self, index: int):
        """Should return the plan unchanged for an out-of-range task index."""
        plan = "- [ ] Task one\n- [ ] Task two"
        assert mark_task_complete(plan, index) == plan

    def test_already_checked_task_returns_plan_unchanged(self):
        """Should return the plan unchanged when the task is already checked."""
        plan = "- [x] Done task\n- [ ] Open task"
        assert mark_task_complete(plan, 0) == plan


class TestCountCompletedTasks:
    """Tests for count_completed_tasks."""

    def test_counts_lowercase_and_uppercase_x(self):
        """Should count both `- [x]` and `- [X]` tasks as completed."""
        plan = "- [x] Lower\n- [X] Upper\n- [ ] Open"
        assert count_completed_tasks(plan) == 2

    def test_empty_plan_returns_zero(self):
        """Should return 0 for an empty plan."""
        assert count_completed_tasks("") == 0

    def test_all_unchecked_returns_zero(self):
        """Should return 0 when every task is unchecked."""
        plan = "- [ ] One\n- [ ] Two\n- [ ] Three"
        assert count_completed_tasks(plan) == 0

    def test_ignores_release_checks_section(self):
        """Should not count checkboxes inside a **Release checks:** section."""
        plan = "- [x] Done\n**Release checks:**\n- [x] Check CI\n- [X] Check docs"
        assert count_completed_tasks(plan) == 1


_REPRESENTATIVE_PLANS = [
    (
        "plain_list",
        "- [ ] Alpha\n- [x] Beta\n- [ ] Gamma",
    ),
    (
        "pr_grouped",
        "### PR 1: Schema\n- [ ] Task one\n- [x] Task two\n\n### PR 2: Service\n- [ ] Task three",
    ),
    (
        "release_checks_section",
        "- [x] Real task\n**Release checks:**\n- [x] Check CI\n\n- [ ] After section",
    ),
    (
        "release_checks_to_eof",
        "- [ ] Before checks\n**Release checks:**\n- [x] Check CI\n- [ ] Check docs",
    ),
    (
        "indented_items",
        "  - [ ] Indented task\n- [X] Top-level task\n  - context note",
    ),
    (
        "mixed_checkbox_case",
        "- [X] Upper done\n- [x] Lower done\n- [ ] Open",
    ),
    (
        "empty_descriptions",
        "- [ ] \n- [x] Kept done\n- [ ]\n- [ ] Also kept",
    ),
    (
        "context_sub_bullets",
        "- [ ] Main task\n  - detail one\n  - detail two\n- [x] Next task",
    ),
]

_representative = pytest.mark.parametrize(
    "plan",
    [plan for _, plan in _REPRESENTATIVE_PLANS],
    ids=[name for name, _ in _REPRESENTATIVE_PLANS],
)


class TestCrossParserConsistency:
    """Tests that plan_parsing stays consistent with parse_tasks_with_groups."""

    @_representative
    def test_descriptions_match_group_parser(self, plan: str):
        """Should return exactly the group parser's task descriptions."""
        tasks, _ = parse_tasks_with_groups(plan)
        assert parse_task_descriptions(plan) == [t.description for t in tasks]

    @_representative
    def test_completed_count_matches_group_parser(self, plan: str):
        """Should count exactly the tasks the group parser marks complete."""
        tasks, _ = parse_tasks_with_groups(plan)
        assert count_completed_tasks(plan) == sum(1 for t in tasks if t.is_complete)

    @_representative
    def test_is_task_complete_matches_group_parser(self, plan: str):
        """Should agree with the group parser's is_complete for every index."""
        tasks, _ = parse_tasks_with_groups(plan)
        assert tasks, "Representative plan must contain at least one task"
        for task in tasks:
            assert is_task_complete(plan, task.index) == task.is_complete

    @staticmethod
    def _expected_updated_plan(plan: str, index: int) -> str:
        """Compute the expected mark_task_complete output from its contract.

        mark_task_complete uses group-parser semantics: task lines match
        ``- [ ]``/``- [x]``/``- [X]`` with a non-empty description, and
        checkbox lines inside a ``**Release checks:**`` section are ignored.
        The first ``[ ]`` in the target line is replaced with ``[x]``.

        Args:
            plan: The original plan markdown.
            index: Zero-based task index to mark complete.

        Returns:
            Expected updated plan markdown.
        """
        import re

        task_pattern = re.compile(r"^-\s*\[([ xX])\]\s*(.+)$")
        release_checks_pattern = re.compile(r"^\*\*Release checks:?\*\*", re.IGNORECASE)

        lines = plan.split("\n")
        count = 0
        in_release_checks = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if release_checks_pattern.match(stripped):
                in_release_checks = True
                continue
            if in_release_checks:
                if not stripped or stripped.startswith("#") or stripped.startswith("---"):
                    in_release_checks = False
                else:
                    continue
            if task_pattern.match(stripped):
                if count == index:
                    lines[i] = line.replace("[ ]", "[x]", 1)
                    break
                count += 1
        return "\n".join(lines)

    @_representative
    def test_mark_task_complete_matches_line_based_contract(self, plan: str):
        """Should rewrite the Nth parser-recognized task line's checkbox."""
        tasks, _ = parse_tasks_with_groups(plan)
        unchecked = [t.index for t in tasks if not t.is_complete]
        assert unchecked, "Representative plan must contain an unchecked task"

        index = unchecked[0]
        assert mark_task_complete(plan, index) == self._expected_updated_plan(plan, index)

    @_representative
    def test_mark_task_complete_round_trip(self, plan: str):
        """Should flip exactly the target task to complete and keep the rest unchanged."""
        tasks, _ = parse_tasks_with_groups(plan)
        unchecked = [t.index for t in tasks if not t.is_complete]
        assert unchecked, "Representative plan must contain an unchecked task"

        index = unchecked[0]
        updated = mark_task_complete(plan, index)
        tasks_after, _ = parse_tasks_with_groups(updated)

        assert parse_task_descriptions(updated) == parse_task_descriptions(plan)
        assert [t.is_complete for t in tasks_after] == [
            t.is_complete or t.index == index for t in tasks
        ]
        assert count_completed_tasks(updated) == count_completed_tasks(plan) + 1
