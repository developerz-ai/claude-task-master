"""Tests for the hive module - batching a PR group into one lead session.

Failure cases first: every path that must NOT produce a batch, and every way a
completion manifest must fail to check off a task.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from claude_task_master.core.hive import (
    DEFAULT_HIVE_MAX_PARALLEL,
    HIVE_MANIFEST_LINE,
    HIVE_MANIFEST_PREFIX,
    HIVE_MAX_PARALLEL_ENV,
    HIVE_MIN_BATCH_TASKS,
    HiveBatch,
    has_completion_manifest,
    hive_max_parallel,
    parse_completed_task_numbers,
    plan_hive_batch,
)
from claude_task_master.core.task_group import ParsedTask, parse_tasks_with_groups

# =============================================================================
# Test Fixtures / helpers
# =============================================================================


def make_task(
    index: int,
    description: str = "Do the thing",
    group_id: str = "pr_1",
    group_name: str = "First PR",
    is_complete: bool = False,
) -> ParsedTask:
    """Build a ParsedTask without going through the plan parser."""
    return ParsedTask(
        index=index,
        description=description,
        group_id=group_id,
        group_name=group_name,
        is_complete=is_complete,
    )


@pytest.fixture
def two_group_tasks() -> list[ParsedTask]:
    """Two PR groups, three tasks each, all incomplete."""
    return [
        make_task(0, "`[coding]` A1", "pr_1", "First PR"),
        make_task(1, "`[coding]` A2", "pr_1", "First PR"),
        make_task(2, "`[quick]` A3", "pr_1", "First PR"),
        make_task(3, "`[coding]` B1", "pr_2", "Second PR"),
        make_task(4, "`[general]` B2", "pr_2", "Second PR"),
        make_task(5, "`[general]` B3", "pr_2", "Second PR"),
    ]


# =============================================================================
# plan_hive_batch - the cases that must NOT batch
# =============================================================================


class TestPlanHiveBatchRefusals:
    """Every path that must fall back to the ordinary single-task loop."""

    def test_disabled_returns_none(self, two_group_tasks: list[ParsedTask]) -> None:
        """Opt-in flag off: never batch, however many tasks remain."""
        assert plan_hive_batch(two_group_tasks, 0, enabled=False) is None

    def test_pr_per_task_returns_none(self, two_group_tasks: list[ParsedTask]) -> None:
        """One PR per task is incompatible with batching a group."""
        assert plan_hive_batch(two_group_tasks, 0, enabled=True, pr_per_task=True) is None

    def test_single_remaining_task_hits_the_floor(self, two_group_tasks: list[ParsedTask]) -> None:
        """The last task of a group alone is below HIVE_MIN_BATCH_TASKS."""
        assert plan_hive_batch(two_group_tasks, 2, enabled=True) is None

    def test_floor_is_two(self) -> None:
        """The mechanical floor backs the prompt guidance; document its value."""
        assert HIVE_MIN_BATCH_TASKS == 2

    def test_index_past_end_returns_none(self, two_group_tasks: list[ParsedTask]) -> None:
        """Out-of-range index must not raise."""
        assert plan_hive_batch(two_group_tasks, 6, enabled=True) is None
        assert plan_hive_batch(two_group_tasks, 99, enabled=True) is None

    def test_negative_index_returns_none(self, two_group_tasks: list[ParsedTask]) -> None:
        """A negative index is out of range, not a Python tail slice."""
        assert plan_hive_batch(two_group_tasks, -1, enabled=True) is None

    def test_empty_task_list_returns_none(self) -> None:
        """No tasks at all: nothing to batch."""
        assert plan_hive_batch([], 0, enabled=True) is None

    def test_all_remaining_complete_returns_none(self) -> None:
        """A group whose remaining tasks are all done has nothing to fan out."""
        tasks = [
            make_task(0, "A1", "pr_1"),
            make_task(1, "A2", "pr_1", is_complete=True),
            make_task(2, "A3", "pr_1", is_complete=True),
        ]
        assert plan_hive_batch(tasks, 1, enabled=True) is None

    def test_current_task_complete_and_one_left_returns_none(self) -> None:
        """The current task being complete does not lift the floor."""
        tasks = [
            make_task(0, "A1", "pr_1", is_complete=True),
            make_task(1, "A2", "pr_1"),
        ]
        assert plan_hive_batch(tasks, 0, enabled=True) is None


# =============================================================================
# plan_hive_batch - the batches it does produce
# =============================================================================


class TestPlanHiveBatch:
    """Batch construction rules."""

    def test_batches_remaining_tasks_of_group(self, two_group_tasks: list[ParsedTask]) -> None:
        """From the group's first task, the whole group is the batch."""
        batch = plan_hive_batch(two_group_tasks, 0, enabled=True)

        assert batch is not None
        assert batch.indices == (0, 1, 2)
        assert batch.size == 3
        assert batch.group_name == "First PR"

    def test_excludes_other_groups(self, two_group_tasks: list[ParsedTask]) -> None:
        """A batch never crosses a PR boundary — one batch, one PR."""
        batch = plan_hive_batch(two_group_tasks, 3, enabled=True)

        assert batch is not None
        assert batch.indices == (3, 4, 5)
        assert batch.group_name == "Second PR"

    def test_excludes_tasks_before_current_index(self, two_group_tasks: list[ParsedTask]) -> None:
        """Tasks already passed are not re-run, complete or not."""
        batch = plan_hive_batch(two_group_tasks, 1, enabled=True)

        assert batch is not None
        assert batch.indices == (1, 2)

    def test_skips_completed_tasks_leaving_a_gap(self) -> None:
        """A batch need not be contiguous: a done task may sit in the middle."""
        tasks = [
            make_task(0, "A1", "pr_1"),
            make_task(1, "A2", "pr_1", is_complete=True),
            make_task(2, "A3", "pr_1"),
            make_task(3, "A4", "pr_1"),
        ]
        batch = plan_hive_batch(tasks, 0, enabled=True)

        assert batch is not None
        assert batch.indices == (0, 2, 3)
        assert batch.size == 3

    def test_interleaved_groups_are_not_merged(self) -> None:
        """Membership is by group_id, so a repeated-heading instance stays apart."""
        tasks = [
            make_task(0, "A1", "pr_1", "First PR"),
            make_task(1, "B1", "pr_2", "Second PR"),
            make_task(2, "A2", "pr_1#2", "First PR again"),
            make_task(3, "A3", "pr_1#2", "First PR again"),
        ]
        batch = plan_hive_batch(tasks, 2, enabled=True)

        assert batch is not None
        assert batch.indices == (2, 3)
        assert batch.group_name == "First PR again"

    def test_descriptions_are_complexity_stripped(self, two_group_tasks: list[ParsedTask]) -> None:
        """The lead gets task text, not the routing tag."""
        batch = plan_hive_batch(two_group_tasks, 0, enabled=True)

        assert batch is not None
        assert batch.descriptions == ("A1", "A2", "A3")
        assert len(batch.descriptions) == len(batch.indices)

    def test_numbers_are_one_based(self, two_group_tasks: list[ParsedTask]) -> None:
        """The manifest speaks in 1-based plan numbers."""
        batch = plan_hive_batch(two_group_tasks, 3, enabled=True)

        assert batch is not None
        assert batch.numbers == (4, 5, 6)

    def test_last_index_is_the_group_closer(self, two_group_tasks: list[ParsedTask]) -> None:
        """last_index is the task whose completion ends the PR group."""
        batch = plan_hive_batch(two_group_tasks, 0, enabled=True)

        assert batch is not None
        assert batch.last_index == 2

    def test_batch_is_frozen(self, two_group_tasks: list[ParsedTask]) -> None:
        """HiveBatch is immutable — callers pass it around freely."""
        batch = plan_hive_batch(two_group_tasks, 0, enabled=True)

        assert batch is not None
        with pytest.raises(FrozenInstanceError):
            batch.group_name = "mutated"  # type: ignore[misc]

    def test_ungrouped_plan_batches_the_default_group(self) -> None:
        """A plan with no PR headings is one 'default' group."""
        tasks = [
            make_task(0, "A1", "default", "Default"),
            make_task(1, "A2", "default", "Default"),
        ]
        batch = plan_hive_batch(tasks, 0, enabled=True)

        assert batch is not None
        assert batch.indices == (0, 1)

    def test_works_on_real_parsed_plan(self) -> None:
        """End-to-end against the actual plan parser."""
        plan = """### PR 1: Schema

- [x] `[coding]` Create migration
- [ ] `[coding]` Update model
- [ ] `[quick]` Update fixture

### PR 2: Service

- [ ] `[general]` Fix service spec
"""
        tasks, _groups = parse_tasks_with_groups(plan)
        batch = plan_hive_batch(tasks, 1, enabled=True)

        assert batch is not None
        assert batch.indices == (1, 2)
        assert batch.numbers == (2, 3)
        assert batch.descriptions == ("Update model", "Update fixture")
        assert batch.group_name == "Schema"

    def test_real_plan_last_group_below_floor(self) -> None:
        """A one-task PR group falls back to the ordinary path."""
        plan = """### PR 1: Schema

- [ ] `[coding]` Update model

### PR 2: Service

- [ ] `[general]` Fix service spec
"""
        tasks, _groups = parse_tasks_with_groups(plan)
        assert plan_hive_batch(tasks, 0, enabled=True) is None


# =============================================================================
# parse_completed_task_numbers - the ways it must refuse
# =============================================================================


class TestParseCompletedTaskNumbersRefusals:
    """A wrong parse silently mass-checks-off tasks; these must all be empty."""

    def test_singular_task_complete_does_not_match(self) -> None:
        """`TASK COMPLETE` is the EXISTING single-task sentinel — never a manifest."""
        assert parse_completed_task_numbers("Done.\nTASK COMPLETE", [1, 2, 3]) == []

    def test_singular_task_complete_with_numbers_does_not_match(self) -> None:
        """Even decorated with numbers, the singular sentinel is not a manifest."""
        assert parse_completed_task_numbers("TASK COMPLETE: 1, 2", [1, 2]) == []

    def test_no_manifest_returns_empty(self) -> None:
        """No manifest at all: callers fall back to single-task behaviour."""
        output = "I edited some files and ran the tests. All green."
        assert parse_completed_task_numbers(output, [1, 2, 3]) == []

    def test_empty_output_returns_empty(self) -> None:
        assert parse_completed_task_numbers("", [1, 2, 3]) == []

    def test_empty_allowed_returns_empty(self) -> None:
        """Nothing is allowed, so nothing may be checked off."""
        assert parse_completed_task_numbers("TASKS COMPLETE: 1, 2", []) == []

    def test_unknown_numbers_are_dropped(self) -> None:
        """A number outside the batch must never check off a task."""
        assert parse_completed_task_numbers("TASKS COMPLETE: 1, 7, 99", [1, 2, 3]) == [1]

    def test_all_unknown_numbers_yield_empty(self) -> None:
        assert parse_completed_task_numbers("TASKS COMPLETE: 42, 43", [1, 2]) == []

    def test_manifest_with_no_numbers_returns_empty(self) -> None:
        """`TASKS COMPLETE: none` claims nothing."""
        assert parse_completed_task_numbers("TASKS COMPLETE: none", [1, 2]) == []

    def test_trailing_prose_numbers_are_not_captured(self) -> None:
        """Scanning stops at the first non-number token."""
        result = parse_completed_task_numbers("TASKS COMPLETE: 1, 2 (of 4 attempted)", [1, 2, 4])
        assert result == [1, 2]

    def test_word_boundary_not_matched(self) -> None:
        """Random prose mentioning the words must not become a manifest."""
        output = "The TASKSCOMPLETE flag is unrelated: 1, 2"
        assert parse_completed_task_numbers(output, [1, 2]) == []


# =============================================================================
# parse_completed_task_numbers - the manifests it accepts
# =============================================================================


class TestParseCompletedTaskNumbers:
    """Tolerant parsing of the lead's completion manifest."""

    def test_basic_manifest(self) -> None:
        assert parse_completed_task_numbers("TASKS COMPLETE: 3, 4, 6", [3, 4, 5, 6]) == [3, 4, 6]

    def test_manifest_at_end_of_long_output(self) -> None:
        output = "\n".join(
            [
                "Fanned out tasks 3 and 4 to workers.",
                "Committed and pushed as abc1234.",
                "",
                "TASKS COMPLETE: 3, 4",
            ]
        )
        assert parse_completed_task_numbers(output, [3, 4, 5]) == [3, 4]

    def test_both_sentinels_on_separate_lines(self) -> None:
        """The lead emits the ordinary sentinel AND the manifest; only one parses."""
        output = "Committed 2 tasks.\nTASK COMPLETE\nTASKS COMPLETE: 3, 4"
        assert parse_completed_task_numbers(output, [3, 4, 5]) == [3, 4]

    def test_empty_manifest_claims_nothing(self) -> None:
        """`TASKS COMPLETE:` with nothing after it means 'I finished none'."""
        output = "TASK COMPLETE\nTASKS COMPLETE:"
        assert parse_completed_task_numbers(output, [3, 4]) == []
        # ...and that is NOT the same as no manifest — see TestHasCompletionManifest.
        assert has_completion_manifest(output) is True

    def test_unsubstituted_placeholder_tail_claims_nothing(self) -> None:
        """The prompt's literal placeholder must not parse as numbers."""
        output = (
            "TASK COMPLETE\n"
            "TASKS COMPLETE: <plan numbers you finished AND committed, comma-separated>"
        )
        assert parse_completed_task_numbers(output, [1, 2, 3]) == []
        assert has_completion_manifest(output) is True

    def test_case_insensitive(self) -> None:
        assert parse_completed_task_numbers("tasks complete: 1, 2", [1, 2]) == [1, 2]
        assert parse_completed_task_numbers("Tasks Complete: 1", [1, 2]) == [1]

    def test_markdown_bold_around_label(self) -> None:
        assert parse_completed_task_numbers("**TASKS COMPLETE: 1, 2**", [1, 2]) == [1, 2]

    def test_markdown_bold_label_only(self) -> None:
        assert parse_completed_task_numbers("**TASKS COMPLETE:** 1, 2", [1, 2]) == [1, 2]

    def test_hash_prefixed_numbers(self) -> None:
        assert parse_completed_task_numbers("TASKS COMPLETE: #1, #3", [1, 2, 3]) == [1, 3]

    def test_whitespace_separated_numbers(self) -> None:
        assert parse_completed_task_numbers("TASKS COMPLETE 1 2 3", [1, 2, 3]) == [1, 2, 3]

    def test_no_colon(self) -> None:
        assert parse_completed_task_numbers("TASKS COMPLETE 4", [4]) == [4]

    def test_and_separator(self) -> None:
        assert parse_completed_task_numbers("TASKS COMPLETE: 1, 2 and 3", [1, 2, 3]) == [1, 2, 3]

    def test_semicolon_separator(self) -> None:
        assert parse_completed_task_numbers("TASKS COMPLETE: 1; 2", [1, 2]) == [1, 2]

    def test_leading_indent_and_bullet(self) -> None:
        assert parse_completed_task_numbers("  - TASKS COMPLETE: 2", [1, 2]) == [2]

    def test_heading_decoration(self) -> None:
        assert parse_completed_task_numbers("## TASKS COMPLETE: 2, 3", [2, 3]) == [2, 3]

    def test_single_number(self) -> None:
        assert parse_completed_task_numbers("TASKS COMPLETE: 5", [4, 5]) == [5]

    def test_duplicates_are_deduped(self) -> None:
        assert parse_completed_task_numbers("TASKS COMPLETE: 2, 2, 3, 2", [2, 3]) == [2, 3]

    def test_result_is_ascending(self) -> None:
        assert parse_completed_task_numbers("TASKS COMPLETE: 6, 3, 4", [3, 4, 6]) == [3, 4, 6]

    def test_last_manifest_wins(self) -> None:
        """A lead that restates its result has revised it."""
        output = "TASKS COMPLETE: 1, 2, 3\nWait — task 3 was not finished.\nTASKS COMPLETE: 1, 2"
        assert parse_completed_task_numbers(output, [1, 2, 3]) == [1, 2]

    def test_last_manifest_wins_even_when_broader(self) -> None:
        output = "TASKS COMPLETE: 1\nAlso finished 2.\nTASKS COMPLETE: 1, 2"
        assert parse_completed_task_numbers(output, [1, 2]) == [1, 2]

    def test_allowed_accepts_any_iterable(self) -> None:
        """Callers pass HiveBatch.numbers, a tuple."""
        assert parse_completed_task_numbers("TASKS COMPLETE: 1, 2", (1, 2)) == [1, 2]

    def test_manifest_constants_are_consistent(self) -> None:
        """The prompt-facing constants must parse with the parser."""
        assert HIVE_MANIFEST_PREFIX == "TASKS COMPLETE"
        assert HIVE_MANIFEST_PREFIX in HIVE_MANIFEST_LINE
        assert parse_completed_task_numbers(f"{HIVE_MANIFEST_PREFIX}: 1", [1]) == [1]

    def test_round_trips_a_batch(self) -> None:
        """Numbers from a real batch survive the manifest round trip."""
        batch = HiveBatch(indices=(2, 4), descriptions=("A", "B"), group_name="PR")
        rendered = f"{HIVE_MANIFEST_PREFIX}: " + ", ".join(str(n) for n in batch.numbers)
        assert parse_completed_task_numbers(rendered, batch.numbers) == [3, 5]


# =============================================================================
# has_completion_manifest - "never reported" vs "reported nothing"
# =============================================================================


class TestHasCompletionManifest:
    """The three-way reading: absent / present-and-empty / present-with-numbers.

    Collapsing the first two is the dangerous one: the absent-case fallback
    checks off the current task, so applying it to an explicit "I finished none"
    checks off work the lead just said it did not do.
    """

    def test_absent_when_no_manifest(self) -> None:
        """Nothing reported: the caller falls back to single-task behaviour."""
        output = "I edited some files and ran the tests. All green."

        assert has_completion_manifest(output) is False
        assert parse_completed_task_numbers(output, [1, 2]) == []

    def test_absent_for_empty_output(self) -> None:
        assert has_completion_manifest("") is False

    def test_singular_sentinel_alone_is_not_a_manifest(self) -> None:
        """`TASK COMPLETE` is the ordinary end-of-session sentinel, not a report."""
        assert has_completion_manifest("Done.\nTASK COMPLETE") is False

    def test_singular_sentinel_with_numbers_is_not_a_manifest(self) -> None:
        assert has_completion_manifest("TASK COMPLETE: 1, 2") is False

    def test_present_when_empty(self) -> None:
        """Present-and-empty: check off NOTHING, do not fall back."""
        assert has_completion_manifest("TASKS COMPLETE:") is True

    def test_present_when_empty_with_trailing_whitespace(self) -> None:
        assert has_completion_manifest("TASKS COMPLETE:   \n") is True

    def test_present_when_empty_without_colon(self) -> None:
        assert has_completion_manifest("TASKS COMPLETE") is True

    def test_present_when_empty_with_markdown_bolding(self) -> None:
        assert has_completion_manifest("**TASKS COMPLETE:**") is True

    def test_present_when_empty_bold_wrapped(self) -> None:
        assert has_completion_manifest("**TASKS COMPLETE**") is True

    def test_present_when_populated(self) -> None:
        """Present-with-numbers: check off the intersection with `allowed`."""
        output = "TASKS COMPLETE: 1, 3"

        assert has_completion_manifest(output) is True
        assert parse_completed_task_numbers(output, [1, 2, 3]) == [1, 3]

    def test_present_when_numbers_are_all_unknown(self) -> None:
        """A manifest full of garbage numbers is still a manifest."""
        output = "TASKS COMPLETE: 41, 42"

        assert has_completion_manifest(output) is True
        assert parse_completed_task_numbers(output, [1, 2]) == []

    def test_present_when_tail_is_prose(self) -> None:
        """'none' is a report, not a missing report."""
        assert has_completion_manifest("TASKS COMPLETE: none") is True

    def test_present_independent_of_allowed(self) -> None:
        """Presence is a property of the output alone — no `allowed` argument."""
        assert has_completion_manifest("TASKS COMPLETE: 9") is True
        assert parse_completed_task_numbers("TASKS COMPLETE: 9", []) == []

    def test_present_for_last_of_several_manifests(self) -> None:
        assert has_completion_manifest("TASKS COMPLETE: 1\nTASKS COMPLETE:") is True


# =============================================================================
# hive_max_parallel - the env knob
# =============================================================================


class TestHiveMaxParallel:
    """A typo in an env var must never end an unattended run."""

    def test_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(HIVE_MAX_PARALLEL_ENV, raising=False)
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "3")
        assert hive_max_parallel() == 3

    def test_whitespace_tolerated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "  4 ")
        assert hive_max_parallel() == 4

    def test_zero_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "0")
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_negative_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "-5")
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_garbage_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "lots")
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_empty_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "")
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_float_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "2.5")
        assert hive_max_parallel() == DEFAULT_HIVE_MAX_PARALLEL

    def test_env_read_at_call_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Not frozen at import: a run may set it per-process."""
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "2")
        assert hive_max_parallel() == 2
        monkeypatch.setenv(HIVE_MAX_PARALLEL_ENV, "7")
        assert hive_max_parallel() == 7

    def test_default_value(self) -> None:
        assert DEFAULT_HIVE_MAX_PARALLEL == 10
