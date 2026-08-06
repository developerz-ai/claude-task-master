"""Tests for the attempt-budget refund in ``StateRecovery.apply_recovery``.

Regression: the per-PR attempt counters are persisted, so a stage that blocked
*because* its budget was spent blocked again the instant ``claudetm resume -f``
re-entered it — zero sessions run, the human's intervention ignored. The budgets
bound an unattended loop; a forced resume means someone looked at the run.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.state_recovery import StateRecovery

if TYPE_CHECKING:
    from pathlib import Path

_BUDGETS = (
    "ci_fix_attempts",
    "conflict_fix_attempts",
    "branch_sync_attempts",
    "pr_finish_attempts",
    "merge_cleanup_attempts",
    "fix_finish_attempts",
    "task_finish_attempts",
)


def _blocked_state() -> TaskState:
    """A run blocked with every attempt budget spent."""
    timestamp = datetime.now().isoformat()
    state = TaskState(
        status="blocked",
        current_task_index=0,
        session_count=20,
        current_pr=145,
        created_at=timestamp,
        updated_at=timestamp,
        run_id="test-run",
        model="opus",
        options=TaskOptions(),
    )
    for field in _BUDGETS:
        setattr(state, field, 3)
    return state


def _client(**status) -> MagicMock:
    client = MagicMock()
    client.get_pr_for_current_branch.return_value = 145
    client.get_pr_status.return_value = MagicMock(
        ci_state=status.get("ci_state", "SUCCESS"),
        unresolved_threads=status.get("unresolved_threads", 0),
    )
    return client


class TestApplyRecoveryRefundsBudgets:
    """`resume --force` must actually get another try."""

    def test_every_attempt_budget_is_refunded(self, temp_dir: Path):
        state = _blocked_state()

        StateRecovery(github_client=_client()).apply_recovery(state, cwd=str(temp_dir))

        assert [getattr(state, field) for field in _BUDGETS] == [0] * len(_BUDGETS)
        assert state.status == "working"

    def test_budgets_are_refunded_even_when_detection_fails(self, temp_dir: Path):
        """A GitHub outage must not cost the retry the resume was asking for."""
        state = _blocked_state()
        client = MagicMock()
        client.get_pr_for_current_branch.side_effect = RuntimeError("gh is down")

        StateRecovery(github_client=client).apply_recovery(state, cwd=str(temp_dir))

        assert [getattr(state, field) for field in _BUDGETS] == [0] * len(_BUDGETS)
        assert state.workflow_stage == "working"
