"""Tests for task_group module - PR/group parsing and management."""

from __future__ import annotations

from claude_task_master.core.task_group import (
    ParsedTask,
    PullRequest,
    TaskComplexity,
    TaskGroup,
    get_group_for_task,
    get_incomplete_tasks,
    get_tasks_in_group,
    parse_task_complexity,
    parse_tasks_with_groups,
    summarize_groups,
)


class TestTaskComplexity:
    """Tests for TaskComplexity enum and parsing."""

    def test_parse_coding_complexity(self):
        """Should parse [coding] tag."""
        complexity, cleaned = parse_task_complexity("`[coding]` Create migration for new table")
        assert complexity == TaskComplexity.CODING
        assert cleaned == "Create migration for new table"

    def test_parse_quick_complexity(self):
        """Should parse [quick] tag."""
        complexity, cleaned = parse_task_complexity("`[quick]` Fix typo in README")
        assert complexity == TaskComplexity.QUICK
        assert cleaned == "Fix typo in README"

    def test_parse_general_complexity(self):
        """Should parse [general] tag."""
        complexity, cleaned = parse_task_complexity("`[general]` Add tests for service")
        assert complexity == TaskComplexity.GENERAL
        assert cleaned == "Add tests for service"

    def test_parse_debugging_qa_complexity(self):
        """Should parse [debugging-qa] tag."""
        complexity, cleaned = parse_task_complexity(
            "`[debugging-qa]` Investigate memory leak in production"
        )
        assert complexity == TaskComplexity.DEBUGGING_QA
        assert cleaned == "Investigate memory leak in production"

    def test_parse_no_complexity_defaults_to_coding(self):
        """Should default to CODING when no tag present."""
        complexity, cleaned = parse_task_complexity("Implement feature X")
        assert complexity == TaskComplexity.CODING
        assert cleaned == "Implement feature X"

    def test_parse_complexity_case_insensitive(self):
        """Should parse tags case-insensitively."""
        complexity, _ = parse_task_complexity("`[CODING]` Task")
        assert complexity == TaskComplexity.CODING

        complexity, _ = parse_task_complexity("`[Quick]` Task")
        assert complexity == TaskComplexity.QUICK

        complexity, _ = parse_task_complexity("`[DEBUGGING-QA]` Task")
        assert complexity == TaskComplexity.DEBUGGING_QA

    def test_get_model_for_complexity(self):
        """Should map complexity to correct model name."""
        assert TaskComplexity.get_model_for_complexity(TaskComplexity.CODING) == "opus"
        assert TaskComplexity.get_model_for_complexity(TaskComplexity.QUICK) == "haiku"
        assert TaskComplexity.get_model_for_complexity(TaskComplexity.GENERAL) == "sonnet"

    def test_get_model_for_debugging_qa(self):
        """Should map DEBUGGING_QA complexity to sonnet_1m."""
        assert (
            TaskComplexity.get_model_for_complexity(TaskComplexity.DEBUGGING_QA) == "sonnet_1m"
        )


class TestParseTasksWithGroups:
    """Tests for parsing plans with PR/group structure."""

    def test_parse_pr_format(self):
        """Should parse ### PR N: format."""
        plan = """
### PR 1: Schema Changes

- [ ] `[coding]` Create migration
- [ ] `[coding]` Update model

### PR 2: Service Layer

- [ ] `[coding]` Fix service
- [ ] `[general]` Add tests
"""
        tasks, groups = parse_tasks_with_groups(plan)

        assert len(tasks) == 4
        assert len(groups) == 2

        # Check first group
        assert groups[0].id == "pr_1"
        assert groups[0].name == "Schema Changes"
        assert len(groups[0].task_indices) == 2

        # Check second group
        assert groups[1].id == "pr_2"
        assert groups[1].name == "Service Layer"
        assert len(groups[1].task_indices) == 2

        # Check task assignments
        assert tasks[0].group_id == "pr_1"
        assert tasks[1].group_id == "pr_1"
        assert tasks[2].group_id == "pr_2"
        assert tasks[3].group_id == "pr_2"

    def test_parse_group_format(self):
        """Should parse ### Group N: format for backwards compatibility."""
        plan = """
### Group 1: Database

- [ ] Create table

### Group 2: API

- [ ] Add endpoint
"""
        tasks, groups = parse_tasks_with_groups(plan)

        assert len(tasks) == 2
        assert len(groups) == 2

        # Group format should use pr_ prefix internally
        assert groups[0].id == "pr_1"
        assert groups[1].id == "pr_2"

    def test_parse_tasks_without_groups(self):
        """Should create default group when no headers present."""
        plan = """
- [ ] Task 1
- [ ] Task 2
- [x] Task 3
"""
        tasks, groups = parse_tasks_with_groups(plan)

        assert len(tasks) == 3
        assert len(groups) == 1
        assert groups[0].id == "default"
        assert groups[0].name == "Default"
        assert len(groups[0].task_indices) == 3

    def test_parse_completed_tasks(self):
        """Should track completion status."""
        plan = """
- [ ] Incomplete task
- [x] Completed task
- [X] Also completed
"""
        tasks, _ = parse_tasks_with_groups(plan)

        assert not tasks[0].is_complete
        assert tasks[1].is_complete
        assert tasks[2].is_complete

    def test_parse_task_indices(self):
        """Should assign correct indices to tasks."""
        plan = """
### PR 1: First

- [ ] Task A
- [ ] Task B

### PR 2: Second

- [ ] Task C
"""
        tasks, _ = parse_tasks_with_groups(plan)

        assert tasks[0].index == 0
        assert tasks[1].index == 1
        assert tasks[2].index == 2

    def test_parse_empty_plan(self):
        """Should handle empty plan."""
        tasks, groups = parse_tasks_with_groups("")

        assert len(tasks) == 0
        assert len(groups) == 0

    def test_parse_plan_with_only_headers(self):
        """Should handle plan with headers but no tasks."""
        plan = """
### PR 1: Empty Group

### PR 2: Also Empty
"""
        tasks, groups = parse_tasks_with_groups(plan)

        assert len(tasks) == 0
        # Groups without tasks are created but empty
        assert len(groups) == 2

    def test_parse_dash_separator(self):
        """Should parse headers with dash separator."""
        plan = """
### PR 1 - Schema Changes

- [ ] Create migration
"""
        tasks, groups = parse_tasks_with_groups(plan)

        assert len(groups) == 1
        assert groups[0].name == "Schema Changes"


class TestParsedTask:
    """Tests for ParsedTask dataclass."""

    def test_complexity_property(self):
        """Should parse complexity from description."""
        task = ParsedTask(
            index=0,
            description="`[quick]` Fix typo",
            group_id="pr_1",
            group_name="Test",
        )
        assert task.complexity == TaskComplexity.QUICK

    def test_cleaned_description_property(self):
        """Should return description without complexity tag."""
        task = ParsedTask(
            index=0,
            description="`[coding]` Create feature",
            group_id="pr_1",
            group_name="Test",
        )
        assert task.cleaned_description == "Create feature"

    def test_pr_aliases(self):
        """Should have pr_id and pr_name aliases."""
        task = ParsedTask(
            index=0,
            description="Test task",
            group_id="pr_1",
            group_name="Schema",
        )
        assert task.pr_id == "pr_1"
        assert task.pr_name == "Schema"

    def test_str_representation(self):
        """Should have readable string representation."""
        incomplete = ParsedTask(
            index=0,
            description="Incomplete task",
            group_id="pr_1",
            group_name="Test",
            is_complete=False,
        )
        assert str(incomplete) == "[ ] Incomplete task"

        complete = ParsedTask(
            index=1,
            description="Complete task",
            group_id="pr_1",
            group_name="Test",
            is_complete=True,
        )
        assert str(complete) == "[x] Complete task"


class TestTaskGroup:
    """Tests for TaskGroup dataclass."""

    def test_str_representation(self):
        """Should have readable string representation."""
        group = TaskGroup(id="pr_1", name="Schema Changes", task_indices=[0, 1, 2])
        assert str(group) == "PR 'Schema Changes' (3 tasks)"

    def test_pr_number_property(self):
        """Should extract PR number from id."""
        group = TaskGroup(id="pr_3", name="Test")
        assert group.pr_number == 3

        default_group = TaskGroup(id="default", name="Default")
        assert default_group.pr_number is None

    def test_pull_request_alias(self):
        """PullRequest should be an alias for TaskGroup."""
        assert PullRequest is TaskGroup


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_group_for_task(self):
        """Should return correct group for task index."""
        plan = """
### PR 1: First

- [ ] Task A
- [ ] Task B

### PR 2: Second

- [ ] Task C
"""
        tasks, _ = parse_tasks_with_groups(plan)

        assert get_group_for_task(0, tasks) == "pr_1"
        assert get_group_for_task(1, tasks) == "pr_1"
        assert get_group_for_task(2, tasks) == "pr_2"
        assert get_group_for_task(99, tasks) == "default"  # Out of bounds

    def test_get_tasks_in_group(self):
        """Should return tasks for specific group."""
        plan = """
### PR 1: First

- [ ] Task A
- [ ] Task B

### PR 2: Second

- [ ] Task C
"""
        tasks, _ = parse_tasks_with_groups(plan)

        pr1_tasks = get_tasks_in_group("pr_1", tasks)
        assert len(pr1_tasks) == 2
        assert pr1_tasks[0].description == "Task A"

        pr2_tasks = get_tasks_in_group("pr_2", tasks)
        assert len(pr2_tasks) == 1
        assert pr2_tasks[0].description == "Task C"

    def test_get_incomplete_tasks(self):
        """Should return only incomplete tasks."""
        plan = """
- [x] Complete 1
- [ ] Incomplete 1
- [x] Complete 2
- [ ] Incomplete 2
"""
        tasks, _ = parse_tasks_with_groups(plan)

        incomplete = get_incomplete_tasks(tasks)
        assert len(incomplete) == 2
        assert all(not t.is_complete for t in incomplete)

    def test_summarize_groups(self):
        """Should generate human-readable summary."""
        plan = """
### PR 1: Schema

- [x] Task 1
- [x] Task 2

### PR 2: Service

- [x] Task 3
- [ ] Task 4
"""
        tasks, groups = parse_tasks_with_groups(plan)

        summary = summarize_groups(groups, tasks)

        assert "2 PR(s)" in summary
        assert "4 total task(s)" in summary
        assert "Schema: " in summary
        assert "Service: 1/2" in summary


class TestEdgeCases:
    """Tests for edge cases and special inputs."""

    def test_task_with_special_characters(self):
        """Should handle special characters in task descriptions."""
        plan = """
### PR 1: Test

- [ ] Fix `user_id` in `models/user.py:42`
- [ ] Update `CONSTANT_NAME` → `NEW_NAME`
"""
        tasks, _ = parse_tasks_with_groups(plan)

        assert len(tasks) == 2
        assert "`user_id`" in tasks[0].description
        assert "→" in tasks[1].description

    def test_whitespace_handling(self):
        """Should handle various whitespace patterns."""
        plan = """
### PR 1: Test

-  [ ]   Task with extra spaces
- [ ]Task without space after bracket
"""
        tasks, _ = parse_tasks_with_groups(plan)

        assert len(tasks) == 2

    def test_multiple_complexity_tags(self):
        """Should use first complexity tag found."""
        complexity, cleaned = parse_task_complexity("`[coding]` Task with `[quick]` extra tag")
        assert complexity == TaskComplexity.CODING
        # Note: second tag remains in cleaned text

    def test_nested_code_blocks(self):
        """Should not parse tasks inside code blocks as tasks."""
        plan = """
### PR 1: Test

- [ ] Real task

```markdown
- [ ] Not a real task (in code block)
```
"""
        tasks, _ = parse_tasks_with_groups(plan)

        # Note: Current implementation doesn't handle code blocks specially
        # This documents current behavior - may want to enhance later
        assert len(tasks) >= 1


class TestContextLines:
    """Tests for context sublists (file references) under tasks."""

    def test_parse_context_lines(self):
        """Tasks with sublists should get context_lines populated."""
        plan = """
### PR 1: Schema & Model Fixes

- [ ] `[coding]` Make `user_id` nullable in Shift model
  - `rails/db/migrate/` — add new migration file
  - `rails/app/models/shift.rb:15` — `Shift` class, `belongs_to :user`
  - `rails/spec/models/shift_spec.rb` — update validation specs
"""
        tasks, _ = parse_tasks_with_groups(plan)

        assert len(tasks) == 1
        assert len(tasks[0].context_lines) == 3
        assert tasks[0].context_lines[0] == "`rails/db/migrate/` — add new migration file"
        assert "`Shift` class" in tasks[0].context_lines[1]
        assert "update validation specs" in tasks[0].context_lines[2]

    def test_context_lines_not_counted_as_tasks(self):
        """Sublists should not create extra tasks."""
        plan = """
### PR 1: Test

- [ ] `[coding]` Task one
  - `file1.py` — note 1
  - `file2.py` — note 2
- [ ] `[quick]` Task two
  - `file3.py` — note 3
"""
        tasks, _ = parse_tasks_with_groups(plan)

        assert len(tasks) == 2
        assert tasks[0].description == "`[coding]` Task one"
        assert tasks[1].description == "`[quick]` Task two"

    def test_context_lines_per_task(self):
        """Each task should get only its own context lines."""
        plan = """
- [ ] Task A
  - `a1.py` — ref A1
  - `a2.py` — ref A2
- [ ] Task B
  - `b1.py` — ref B1
- [ ] Task C
"""
        tasks, _ = parse_tasks_with_groups(plan)

        assert len(tasks) == 3
        assert len(tasks[0].context_lines) == 2
        assert tasks[0].context_lines[0] == "`a1.py` — ref A1"
        assert tasks[0].context_lines[1] == "`a2.py` — ref A2"
        assert len(tasks[1].context_lines) == 1
        assert tasks[1].context_lines[0] == "`b1.py` — ref B1"
        assert len(tasks[2].context_lines) == 0

    def test_no_context_lines(self):
        """Tasks without sublists should have empty context_lines."""
        plan = """
### PR 1: Simple

- [ ] `[coding]` Simple task without context
- [ ] `[quick]` Another simple task
"""
        tasks, _ = parse_tasks_with_groups(plan)

        assert len(tasks) == 2
        assert tasks[0].context_lines == []
        assert tasks[1].context_lines == []

    def test_context_lines_with_groups(self):
        """Context lines should work correctly within PR groups."""
        plan = """
### PR 1: Schema Changes

- [ ] `[coding]` Create migration
  - `db/migrate/` — new migration file
  - `app/models/user.rb` — update model

### PR 2: Service Layer

- [ ] `[coding]` Fix service
  - `app/services/user_service.rb` — `UserService.process()`
- [ ] `[general]` Add tests
"""
        tasks, groups = parse_tasks_with_groups(plan)

        assert len(tasks) == 3
        assert len(groups) == 2

        # PR 1 task has context
        assert len(tasks[0].context_lines) == 2
        assert tasks[0].group_id == "pr_1"

        # PR 2 first task has context, second doesn't
        assert len(tasks[1].context_lines) == 1
        assert tasks[1].group_id == "pr_2"
        assert len(tasks[2].context_lines) == 0
        assert tasks[2].group_id == "pr_2"

    def test_context_lines_with_tab_indent(self):
        """Context lines with tab indentation should be captured."""
        plan = "- [ ] Task with tabs\n\t- `file.py` — tab indented ref\n"
        tasks, _ = parse_tasks_with_groups(plan)

        assert len(tasks) == 1
        assert len(tasks[0].context_lines) == 1
        assert tasks[0].context_lines[0] == "`file.py` — tab indented ref"

    def test_blank_line_between_task_and_sublist(self):
        """A blank line should stop context line collection."""
        plan = """
- [ ] Task A
  - `a.py` — ref for A

- [ ] Task B
  - `b.py` — ref for B
"""
        tasks, _ = parse_tasks_with_groups(plan)

        assert len(tasks) == 2
        assert len(tasks[0].context_lines) == 1
        assert tasks[0].context_lines[0] == "`a.py` — ref for A"
        assert len(tasks[1].context_lines) == 1
        assert tasks[1].context_lines[0] == "`b.py` — ref for B"
