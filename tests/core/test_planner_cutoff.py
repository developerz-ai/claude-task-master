"""Tests for the cut-off-planning-session guard in Planner.create_plan.

A planning session the SDK cuts off (max turns, budget cap, mid-run error)
returns a task list that simply stops partway through. `run_planning_phase`
reported no success flag at all, so that half-written plan was persisted as if
complete — and every later stage treats `plan.md` as the whole job, so the
missing tasks are never noticed. Reachable in practice since sessions carry a
turn cap (`CLAUDETM_MAX_TURNS`) and an optional budget cap.

Kept out of `test_planner.py`, which is already at the repo's 500-line ceiling.
"""

from __future__ import annotations

import pytest

from claude_task_master.core.planner import Planner


@pytest.fixture
def planner(mock_agent_wrapper, state_manager):
    return Planner(agent=mock_agent_wrapper, state_manager=state_manager)


def _result(plan: str, *, success: bool | None, subtype: str | None = None) -> dict:
    out: dict = {"plan": plan, "criteria": "criteria", "raw_output": "..."}
    if success is not None:
        out["success"] = success
        out["subtype"] = subtype
    return out


class TestPlanningSessionCutOff:
    """A cut-off session must never leave a truncated plan behind."""

    def test_truncated_plan_is_not_saved(self, planner, mock_agent_wrapper, state_manager):
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_agent_wrapper.run_planning_phase.return_value = _result(
            "## Task List\n- [ ] Task 1\n- [ ] Task 2 (cut off mid-",
            success=False,
            subtype="error_max_turns",
        )

        planner.create_plan("Some goal")

        assert state_manager.load_plan() is None

    def test_existing_plan_survives_a_cut_off_replan(
        self, planner, mock_agent_wrapper, state_manager
    ):
        """Overwriting a good plan with a truncation is the worst outcome."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_plan("## Task List\n- [x] Done\n- [ ] Pending\n")
        mock_agent_wrapper.run_planning_phase.return_value = _result(
            "## Task List\n- [ ] Only", success=False, subtype="error_during_execution"
        )

        planner.create_plan("Some goal")

        assert "- [x] Done" in (state_manager.load_plan() or "")

    def test_successful_plan_is_saved(self, planner, mock_agent_wrapper, state_manager):
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_agent_wrapper.run_planning_phase.return_value = _result(
            "## Task List\n- [ ] Task 1\n", success=True
        )

        planner.create_plan("Some goal")

        assert "- [ ] Task 1" in (state_manager.load_plan() or "")

    def test_absent_success_key_still_saves(self, planner, mock_agent_wrapper, state_manager):
        """Older result shapes keep working — only an explicit False blocks."""
        state_manager.state_dir.mkdir(exist_ok=True)
        mock_agent_wrapper.run_planning_phase.return_value = _result(
            "## Task List\n- [ ] Task 1\n", success=None
        )

        planner.create_plan("Some goal")

        assert "- [ ] Task 1" in (state_manager.load_plan() or "")
