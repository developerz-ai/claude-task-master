"""Regression tests for stall detection during external waits.

The stall detector measures time since the last *agent* progress signal, but
whole stages of the PR workflow (polling CI, polling reviews, checking
mergeability, or running a non-working agent session) report nothing to it.
These tests pin the behaviour that made a healthy 2-hour CI wait abort after
five minutes.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.orchestrator import WorkLoopOrchestrator
from claude_task_master.core.state import TaskOptions


@pytest.fixture
def orchestrator(mock_agent_wrapper, state_manager, planner, mock_github_client):
    """Orchestrator wired to mocks over a bare (uninitialized) state manager."""
    return WorkLoopOrchestrator(
        agent=mock_agent_wrapper,
        state_manager=state_manager,
        planner=planner,
        github_client=mock_github_client,
    )


def _init_state(state_manager, sample_task_options, *, stage: str):
    """Initialize a state file parked in ``stage`` with one pending task."""
    state_manager.state_dir.mkdir(exist_ok=True)
    state_manager.initialize(
        goal="Test", model="sonnet", options=TaskOptions(**sample_task_options)
    )
    state_manager.save_plan("- [ ] Task 1")
    state = state_manager.load_state()
    state.status = "working"
    state.workflow_stage = stage
    state.current_pr = 42
    state_manager.save_state(state)
    return state


def _patch_loop():
    """Patch the loop's terminal-IO helpers so run() is testable."""
    return (
        patch(
            "claude_task_master.core.orchestrator_loop.is_cancellation_requested",
            return_value=False,
        ),
        patch("claude_task_master.core.orchestrator_loop.start_listening"),
        patch("claude_task_master.core.orchestrator_loop.stop_listening"),
        patch("claude_task_master.core.orchestrator_loop.register_handlers"),
        patch("claude_task_master.core.orchestrator_loop.unregister_handlers"),
        patch("claude_task_master.core.orchestrator_loop.reset_shutdown"),
        patch("claude_task_master.core.orchestrator_loop.console", MagicMock()),
    )


class TestStallDuringExternalWait:
    """Waiting on GitHub must not be mistaken for a hang."""

    @pytest.mark.timeout(10)
    @pytest.mark.parametrize("stage", ["waiting_ci", "waiting_reviews", "ready_to_merge"])
    def test_wait_stage_does_not_abort_as_stalled(
        self, stage, orchestrator, state_manager, sample_task_options
    ):
        """Regression: a run parked in waiting_ci was blocked with "Stalled: no
        progress for 369 seconds" five minutes into a CI wait, even though CI
        polling is bounded by CI_POLL_TIMEOUT (120 minutes).
        """
        _init_state(state_manager, sample_task_options, stage=stage)
        # No agent activity for longer than the 300s stall threshold.
        orchestrator.tracker._last_progress_time = time.time() - 400

        cycles = []

        def fake_cycle(state):
            cycles.append(state.workflow_stage)
            return 0  # end the run so the test terminates

        patches = _patch_loop()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            with patch.object(orchestrator, "_run_workflow_cycle", side_effect=fake_cycle):
                result = orchestrator.run()

        assert cycles == [stage], "the wait stage should have been polled, not aborted"
        assert result == 0

    @pytest.mark.timeout(10)
    def test_genuine_stall_in_working_stage_still_aborts(
        self, orchestrator, state_manager, sample_task_options
    ):
        """The exemption is scoped to wait stages — a stalled working stage
        must still block the run."""
        _init_state(state_manager, sample_task_options, stage="working")
        orchestrator.tracker._last_progress_time = time.time() - 400

        patches = _patch_loop()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            with patch.object(orchestrator, "_run_workflow_cycle", return_value=0) as cycle:
                result = orchestrator.run()

        assert result == 1
        cycle.assert_not_called()
        assert state_manager.load_state().status == "blocked"

    @pytest.mark.timeout(10)
    def test_stage_transition_heartbeats_the_tracker(
        self, orchestrator, state_manager, sample_task_options
    ):
        """Regression: a long non-working agent session (CI fix, review
        addressing, conflict resolution) reports nothing to the tracker, so the
        cycle after it was judged stalled. Advancing the stage is progress.
        """
        _init_state(state_manager, sample_task_options, stage="ci_failed")

        calls = []

        def fake_cycle(state):
            calls.append(state.workflow_stage)
            if len(calls) == 1:
                # A CI-fix session that runs longer than the stall threshold
                # and reports nothing to the tracker, then advances the stage.
                orchestrator.tracker._last_progress_time = time.time() - 400
                state.workflow_stage = "working"
                return None
            return 0

        patches = _patch_loop()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            with patch.object(orchestrator, "_run_workflow_cycle", side_effect=fake_cycle):
                result = orchestrator.run()

        assert calls == ["ci_failed", "working"], "second cycle was aborted as a stall"
        assert result == 0
