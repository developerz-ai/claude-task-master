"""Tests for mailbox durability: plan-update safety and re-enqueue guarantees.

Covers three behaviours introduced in the slice-05 (mailbox durability) PR:

1. **Peek-not-consume** – ``get_messages`` is non-destructive; only
   ``remove_messages`` actually dequeues.  A failed plan update (exception,
   ValueError, garbage LLM response) must not silently lose messages.

2. **Garbage-LLM guard** – ``_is_safe_update`` rejects responses that have no
   tasks or that drop completed tasks; ``update_plan`` never writes plan.md in
   those cases (verified against real files on disk, not mocked state).

3. **Index reconciliation** – ``_relocate_task_index`` keeps the run pointer
   stable across plan insertions, deletions, and edge cases.

Style: follows tests/mailbox/test_merger.py — ``from __future__ import
annotations``, class-per-behaviour, one-liner docstring per test function.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.plan_updater import PlanUpdater
from claude_task_master.core.state import StateManager
from claude_task_master.mailbox.storage import MailboxStorage

# ---------------------------------------------------------------------------
# Shared test plans
# ---------------------------------------------------------------------------

_SIMPLE_PLAN = "- [ ] Task A\n- [ ] Task B\n"
_PLAN_WITH_DONE = "- [x] Done task\n- [ ] Pending task\n"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state_mgr(state_dir):
    """Real StateManager backed by the test's temp state_dir."""
    return StateManager(state_dir=state_dir)


@pytest.fixture
def mock_updater():
    """PlanUpdater with fully mocked dependencies (no file I/O)."""
    return PlanUpdater(agent=MagicMock(), state_manager=MagicMock(), logger=None)


@pytest.fixture
def real_updater(state_mgr):
    """PlanUpdater backed by a real StateManager that writes plan files to disk.

    Non-plan accessors (goal, state) are stubbed so tests do not need to
    initialise the full task state — only plan.md operations are real.
    """
    # Keep the real StateManager's plan I/O (load_plan, save_plan, backup_plan).
    # Stub the accessors that are not relevant to file-safety tests.
    state_mgr.load_goal = MagicMock(return_value="test goal")
    state_mgr.load_state = MagicMock(return_value=MagicMock(options=None))
    return PlanUpdater(agent=MagicMock(), state_manager=state_mgr, logger=None)


# ===========================================================================
# 1. Peek-not-consume (failed update re-enqueue)
# ===========================================================================


class TestFailedUpdateReenqueue:
    """get_messages is a non-destructive peek; only remove_messages dequeues.

    The orchestrator's peek → process → remove_messages flow guarantees that a
    transient failure (API error, ValueError, garbage LLM response) leaves the
    user's change requests in the mailbox to be retried on the next check.
    """

    def test_get_messages_does_not_consume(self, state_dir):
        """get_messages is a peek: messages survive the call unchanged."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("change A")
        storage.add_message("change B")

        # Orchestrator peeks — plan_updater is called next (may fail).
        peeked = storage.get_messages()

        assert len(peeked) == 2
        assert storage.count() == 2  # still there

    def test_remove_messages_is_the_only_consumer(self, state_dir):
        """Only an explicit remove_messages call dequeues a message."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("payload")

        # Peek.
        peeked = storage.get_messages()
        assert storage.count() == 1  # peek did not consume

        # Explicit dequeue.
        removed = storage.remove_messages([peeked[0].id])
        assert removed == 1
        assert storage.count() == 0

    def test_exception_before_remove_leaves_messages_intact(self, state_dir):
        """Simulates the orchestrator failure path: exception → no remove → messages safe."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("important plan change")

        storage.get_messages()  # orchestrator peeks — may fail before remove_messages

        # Simulate plan_updater.update_plan() raising (e.g. API failure).
        try:
            raise RuntimeError("API failure during plan update")
        except RuntimeError:
            pass  # orchestrator catches; does NOT call remove_messages

        # Messages must survive for the next orchestrator check.
        next_check = storage.get_messages()
        assert len(next_check) == 1
        assert next_check[0].content == "important plan change"

    def test_partial_remove_preserves_concurrent_arrivals(self, state_dir):
        """remove_messages by ID preserves messages that arrived during the update."""
        storage = MailboxStorage(state_dir=state_dir)

        # Orchestrator peeks at the existing set.
        storage.add_message("existing")
        peeked = storage.get_messages()

        # A new message arrives while the plan update runs.
        storage.add_message("arrived during update")

        # Successful update: remove only the peeked IDs (not a blanket clear).
        storage.remove_messages([m.id for m in peeked])

        remaining = storage.get_messages()
        assert len(remaining) == 1
        assert remaining[0].content == "arrived during update"

    def test_plan_updater_raises_does_not_touch_mailbox(self, state_dir, state_mgr):
        """PlanUpdater.update_plan raises ValueError; mailbox stays intact."""
        storage = MailboxStorage(state_dir=state_dir)
        storage.add_message("change request")

        updater = PlanUpdater(agent=MagicMock(), state_manager=state_mgr, logger=None)

        # No plan.md exists → update_plan must raise.
        with pytest.raises(ValueError, match="No plan exists"):
            updater.update_plan("some change")

        # PlanUpdater owns no mailbox reference; messages must be untouched.
        assert storage.count() == 1

    def test_multiple_messages_all_survive_failed_update(self, state_dir, state_mgr):
        """All peeked messages remain after a failed update (not just the first)."""
        storage = MailboxStorage(state_dir=state_dir)
        for i in range(5):
            storage.add_message(f"request {i}")

        peeked = storage.get_messages()
        assert len(peeked) == 5

        updater = PlanUpdater(agent=MagicMock(), state_manager=state_mgr, logger=None)
        with pytest.raises(ValueError):
            updater.update_plan("batch change")

        assert storage.count() == 5

    def test_successful_remove_after_success_clears_only_processed(self, state_dir):
        """After a successful update only the processed IDs are removed."""
        storage = MailboxStorage(state_dir=state_dir)
        id_a = storage.add_message("message A")
        id_b = storage.add_message("message B")

        # Simulate: only A was processed (B arrived concurrently).
        removed = storage.remove_messages([id_a])
        assert removed == 1

        remaining = storage.get_messages()
        assert len(remaining) == 1
        assert remaining[0].id == id_b


# ===========================================================================
# 2. Garbage-LLM guard (real file I/O)
# ===========================================================================


class TestPlanUpdateFileSafety:
    """Garbage LLM response must not overwrite plan.md on disk.

    These tests use a real StateManager (real file writes) to verify that the
    ``_is_safe_update`` gate prevents bad responses from corrupting plan.md.
    """

    def test_prose_response_leaves_file_unchanged(self, real_updater, state_dir):
        """Pure prose LLM response does not overwrite plan.md on disk."""
        plan_path = state_dir / "plan.md"
        plan_path.write_text(_SIMPLE_PLAN)

        with patch.object(
            real_updater,
            "_run_plan_update_query",
            return_value="I cannot update the plan as requested.",
        ):
            result = real_updater.update_plan("change")

        assert plan_path.read_text() == _SIMPLE_PLAN
        assert result["changes_made"] is False

    def test_header_with_no_task_lines_leaves_file_unchanged(self, real_updater, state_dir):
        """Response with ## Task List header but no checkbox lines is rejected."""
        plan_path = state_dir / "plan.md"
        plan_path.write_text(_SIMPLE_PLAN)

        with patch.object(
            real_updater, "_run_plan_update_query", return_value="## Task List\n\nNo tasks to add."
        ):
            result = real_updater.update_plan("clear")

        assert plan_path.read_text() == _SIMPLE_PLAN
        assert result["changes_made"] is False

    def test_empty_response_leaves_file_unchanged(self, real_updater, state_dir):
        """Empty string response does not overwrite plan.md."""
        plan_path = state_dir / "plan.md"
        plan_path.write_text(_SIMPLE_PLAN)

        with patch.object(real_updater, "_run_plan_update_query", return_value=""):
            result = real_updater.update_plan("add task")

        assert plan_path.read_text() == _SIMPLE_PLAN
        assert result["changes_made"] is False

    def test_dropping_completed_tasks_leaves_file_unchanged(self, real_updater, state_dir):
        """Response that un-checks completed tasks is rejected; plan.md untouched."""
        plan_path = state_dir / "plan.md"
        plan_path.write_text(_PLAN_WITH_DONE)

        # Model un-checked the completed task.
        with patch.object(
            real_updater,
            "_run_plan_update_query",
            return_value="- [ ] Done task\n- [ ] Pending task\n",
        ):
            result = real_updater.update_plan("uncheck")

        assert plan_path.read_text() == _PLAN_WITH_DONE
        assert result["changes_made"] is False

    def test_valid_update_writes_new_content(self, real_updater, state_dir):
        """A valid response (differs, has tasks, keeps completed) writes plan.md."""
        plan_path = state_dir / "plan.md"
        plan_path.write_text(_PLAN_WITH_DONE)
        updated = "- [x] Done task\n- [ ] Pending task\n- [ ] New task\n"

        with patch.object(real_updater, "_run_plan_update_query", return_value=updated):
            result = real_updater.update_plan("add new")

        assert result["changes_made"] is True
        on_disk = plan_path.read_text()
        assert "New task" in on_disk
        assert "[x] Done task" in on_disk

    def test_backup_written_before_overwrite(self, real_updater, state_dir):
        """plan.md.bak is created with the original content before plan.md is changed."""
        plan_path = state_dir / "plan.md"
        backup_path = state_dir / "plan.md.bak"
        plan_path.write_text(_SIMPLE_PLAN)
        updated = "- [ ] Task A\n- [ ] Task B\n- [ ] Task C\n"

        with patch.object(real_updater, "_run_plan_update_query", return_value=updated):
            real_updater.update_plan("add C")

        assert backup_path.exists()
        assert backup_path.read_text() == _SIMPLE_PLAN

    def test_result_plan_is_original_on_rejection(self, real_updater, state_dir):
        """result['plan'] equals the on-disk plan when the update is rejected."""
        plan_path = state_dir / "plan.md"
        plan_path.write_text(_SIMPLE_PLAN)

        with patch.object(
            real_updater, "_run_plan_update_query", return_value="Sorry, I cannot help."
        ):
            result = real_updater.update_plan("change")

        assert result["plan"].strip() == _SIMPLE_PLAN.strip()
        assert result["success"] is True

    def test_identical_response_leaves_file_unchanged(self, real_updater, state_dir):
        """Response identical to the current plan does not write and changes_made=False."""
        plan_path = state_dir / "plan.md"
        plan_path.write_text(_SIMPLE_PLAN)

        with patch.object(real_updater, "_run_plan_update_query", return_value=_SIMPLE_PLAN):
            result = real_updater.update_plan("no-op")

        assert result["changes_made"] is False
        assert plan_path.read_text() == _SIMPLE_PLAN


# ===========================================================================
# 3. Index reconciliation
# ===========================================================================


class TestIndexReconciliation:
    """_relocate_task_index keeps the run pointer stable across plan rewrites.

    Exercises the pure-function layer directly so edge cases can be covered
    without needing a full update_plan round-trip with a mocked agent.
    """

    def test_task_at_same_position_unchanged(self, mock_updater):
        """Task still at the same index after an identity rewrite → same index."""
        plan = "- [ ] Alpha\n- [ ] Beta\n"
        assert mock_updater._relocate_task_index(plan, "Alpha", 0) == 0

    def test_insertion_above_shifts_index_down(self, mock_updater):
        """A task inserted above the current one increments its index."""
        updated = "- [ ] New\n- [ ] Alpha\n- [ ] Beta\n"
        # Alpha was at 0; after insertion of "New" above, it moves to 1.
        assert mock_updater._relocate_task_index(updated, "Alpha", 0) == 1

    def test_deletion_above_shifts_index_up(self, mock_updater):
        """Removing a task above the current one decrements its index."""
        updated = "- [ ] Beta\n- [ ] Gamma\n"
        # Beta was at 1; after Alpha is removed, it is at 0.
        assert mock_updater._relocate_task_index(updated, "Beta", 1) == 0

    def test_removed_current_task_falls_back_to_first_incomplete(self, mock_updater):
        """Current task deleted → fall back to first_incomplete_task_index."""
        updated = "- [x] Done\n- [ ] Remaining\n"
        # "Alpha" is gone; first incomplete task is "Remaining" at index 1.
        assert mock_updater._relocate_task_index(updated, "Alpha", 0) == 1

    def test_no_reconciliation_when_previous_index_is_none(self, mock_updater):
        """previous_index=None means reconciliation not requested → returns None."""
        assert mock_updater._relocate_task_index("- [ ] A\n", None, None) is None

    def test_all_tasks_complete_returns_past_end_sentinel(self, mock_updater):
        """All-done plan → first_incomplete_task_index equals task count."""
        updated = "- [x] A\n- [x] B\n"
        # "Gone" not present; first_incomplete = 2 (past-end sentinel).
        assert mock_updater._relocate_task_index(updated, "Gone", 0) == 2

    def test_multiple_insertions_above(self, mock_updater):
        """Several tasks inserted above the current one shift it by that count."""
        updated = "- [ ] N1\n- [ ] N2\n- [ ] N3\n- [ ] Alpha\n- [ ] Beta\n"
        # Alpha was at 0; three tasks inserted above → now at 3.
        assert mock_updater._relocate_task_index(updated, "Alpha", 0) == 3

    def test_task_desc_none_falls_back_to_first_incomplete(self, mock_updater):
        """task_desc=None (out-of-range previous index) → first incomplete."""
        updated = "- [x] Done\n- [ ] Next\n"
        # previous_index=5 is out of range → _current_task_description returns None
        # → _relocate_task_index falls back to first_incomplete_task_index = 1.
        assert mock_updater._relocate_task_index(updated, None, 5) == 1

    def test_full_round_trip_via_update_plan_insertion(self, state_dir, real_updater):
        """update_plan propagates reconciled index when a task is inserted above."""
        plan_path = state_dir / "plan.md"
        plan_path.write_text("- [ ] Alpha\n- [ ] Beta\n- [ ] Gamma\n")

        updated_plan = "- [ ] Alpha\n- [ ] Inserted\n- [ ] Beta\n- [ ] Gamma\n"
        with patch.object(real_updater, "_run_plan_update_query", return_value=updated_plan):
            result = real_updater.update_plan("insert above Beta", current_task_index=1)

        # Beta was at index 1; "Inserted" pushed it to index 2.
        assert result["changes_made"] is True
        assert result["current_task_index"] == 2

    def test_full_round_trip_via_update_plan_deletion(self, state_dir, real_updater):
        """update_plan propagates reconciled index when the current task is removed."""
        plan_path = state_dir / "plan.md"
        plan_path.write_text("- [x] Done\n- [ ] Current\n- [ ] Next\n")

        # "Current" is removed; only "Done" and "Next" remain.
        updated_plan = "- [x] Done\n- [ ] Next\n"
        with patch.object(real_updater, "_run_plan_update_query", return_value=updated_plan):
            result = real_updater.update_plan("remove Current", current_task_index=1)

        assert result["changes_made"] is True
        # "Current" gone → first_incomplete_task_index = 1 ("Next").
        assert result["current_task_index"] == 1
