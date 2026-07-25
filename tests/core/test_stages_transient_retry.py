"""Tests for _retry_transient — bounded retries instead of instant blocks.

claudetm is built to run unattended for hours. Three operations ended a whole
run on their *first* failure — detecting a PR, merging it, and checking out the
base after a merge — even though the usual cause (a GitHub 5xx, a rate limit,
mergeability still recomputing, a momentary index lock) resolves itself in
seconds. Each cost a human a `claudetm resume` for something that would have
worked a minute later.

A permanent failure must still block, so the budget is small and the block
still arrives — just later, and with the attempt count attached.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

_GIT_OPS = "claude_task_master.core.stages.git_ops"


@pytest.fixture(autouse=True)
def _quiet():
    with (
        patch(f"{_GIT_OPS}.console"),
        patch(f"{_GIT_OPS}.interruptible_sleep", return_value=True) as sleep,
    ):
        yield sleep


@pytest.fixture
def handler(state_manager, mock_github_client):
    state_manager.state_dir.mkdir(exist_ok=True)
    return WorkflowStageHandler(
        agent=MagicMock(),
        state_manager=state_manager,
        github_client=mock_github_client,
        pr_context=MagicMock(),
    )


@pytest.fixture
def state(sample_task_options):
    now = datetime.now().isoformat()
    return TaskState(
        status="working",
        workflow_stage="ready_to_merge",
        current_task_index=0,
        session_count=1,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=TaskOptions(**sample_task_options),
    )


class TestRetryTransient:
    def test_retries_up_to_the_budget_without_blocking(self, handler, state):
        for _ in range(handler.MAX_TRANSIENT_RETRIES):
            assert handler._retry_transient(state, "op", "boom") is None
            assert state.status == "working"

    def test_blocks_once_the_budget_is_spent(self, handler, state):
        for _ in range(handler.MAX_TRANSIENT_RETRIES):
            handler._retry_transient(state, "op", "boom")

        assert handler._retry_transient(state, "op", "boom") == 1
        assert state.status == "blocked"

    def test_each_key_has_its_own_budget(self, handler, state):
        """One flaky operation must not spend another's retries."""
        for _ in range(handler.MAX_TRANSIENT_RETRIES):
            handler._retry_transient(state, "op-a", "boom")

        assert handler._retry_transient(state, "op-b", "boom") is None
        assert state.status == "working"

    def test_success_clears_the_budget(self, handler, state):
        """A recovered operation starts fresh — flakiness must not accumulate."""
        for _ in range(handler.MAX_TRANSIENT_RETRIES):
            handler._retry_transient(state, "op", "boom")
        handler._clear_transient("op")

        assert handler._retry_transient(state, "op", "boom") is None
        assert state.status == "working"

    def test_backoff_grows_and_is_capped(self, handler, state, _quiet):
        for _ in range(handler.MAX_TRANSIENT_RETRIES):
            handler._retry_transient(state, "op", "boom")

        delays = [call.args[0] for call in _quiet.call_args_list]
        assert delays == sorted(delays), "backoff must not shrink"
        assert max(delays) <= handler.TRANSIENT_RETRY_MAX_DELAY

    def test_hint_is_shown_only_when_blocking(self, handler, state):
        with patch(f"{_GIT_OPS}.console") as console:
            handler._retry_transient(state, "op", "boom", hint="do the thing")
            assert not console.detail.called

            for _ in range(handler.MAX_TRANSIENT_RETRIES):
                handler._retry_transient(state, "op", "boom", hint="do the thing")

            console.detail.assert_called_with("do the thing")
