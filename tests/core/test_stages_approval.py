"""Tests for the review-decision gate on auto-merge (issue #146).

``auto_merge`` was documented everywhere as "merges when CI passes **and the PR
is approved**", but nothing in the code had ever seen a review decision: the
PR-status query selected ``reviewThreads`` only. The real gate was — and still
is — CI green plus zero unresolved review threads.

A hard "require an approval" gate is not the fix: this repo's own ``main``
requires an approving review that no unattended run can obtain, which is exactly
why ``--admin`` exists, so requiring one would deadlock every run. Only
``CHANGES_REQUESTED`` is acted on: a human actively pushed back, so it fires only
when someone acted, and merging over it is wrong.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

_MERGE = "claude_task_master.core.stages.merge_stage"


@pytest.fixture(autouse=True)
def _quiet() -> Generator[None, None, None]:
    with (
        patch("time.sleep"),
        patch(f"{_MERGE}.console"),
        patch(f"{_MERGE}.interruptible_sleep", return_value=True),
        patch("claude_task_master.core.stages.git_ops.console"),
        patch("claude_task_master.core.stages.merge_cleanup.console"),
    ):
        yield


@pytest.fixture
def mock_github_client() -> MagicMock:
    client = MagicMock()
    client.merge_pr = MagicMock()
    return client


@pytest.fixture
def handler(state_manager, mock_github_client) -> WorkflowStageHandler:
    state_manager.state_dir.mkdir(exist_ok=True)
    return WorkflowStageHandler(
        agent=MagicMock(),
        state_manager=state_manager,
        github_client=mock_github_client,
        pr_context=MagicMock(),
    )


@pytest.fixture
def state(sample_task_options) -> TaskState:
    now = datetime.now().isoformat()
    options = TaskOptions(**sample_task_options)
    options.auto_merge = True
    return TaskState(
        status="working",
        workflow_stage="ready_to_merge",
        current_task_index=0,
        session_count=1,
        current_pr=42,
        created_at=now,
        updated_at=now,
        run_id="test-run-id",
        model="sonnet",
        options=options,
    )


def _pr_status(
    review_decision: str | None,
    changes_requested_by: list[str] | None = None,
    changes_requested_bots: list[str] | None = None,
    changes_requested_complete: bool = True,
) -> MagicMock:
    status = MagicMock()
    # Default to "who requested changes is unreadable", which must keep blocking.
    status.changes_requested_by = changes_requested_by or []
    status.changes_requested_bots = changes_requested_bots or []
    status.changes_requested_complete = changes_requested_complete
    status.number = 42
    status.state = "OPEN"
    status.ci_state = "SUCCESS"
    status.mergeable = "MERGEABLE"
    status.merge_state_status = "CLEAN"
    status.base_branch = "main"
    status.head_branch = "feat/x"
    status.unresolved_threads = 0
    status.check_details = []
    status.review_decision = review_decision
    return status


def _merged() -> MagicMock:
    merged = MagicMock()
    merged.state = "MERGED"
    return merged


class TestChangesRequestedIsNeverAutoMerged:
    """A reviewer pressed "Request changes" — the run must not merge over it."""

    def test_changes_requested_blocks_without_merging(self, handler, state, mock_github_client):
        mock_github_client.get_pr_status.return_value = _pr_status("CHANGES_REQUESTED")

        result = handler.handle_ready_to_merge_stage(state)

        assert result == 1
        assert state.status == "blocked"
        mock_github_client.merge_pr.assert_not_called()
        # Stage is unchanged: dismissing/approving on GitHub is what clears this,
        # and the next cycle then re-enters ready_to_merge and proceeds.
        assert state.workflow_stage == "ready_to_merge"

    def test_admin_does_not_override_changes_requested(self, handler, state, mock_github_client):
        """--admin passes branch protection; it is not consent to merge over a review."""
        state.options.admin_merge = True
        mock_github_client.get_pr_status.return_value = _pr_status("CHANGES_REQUESTED")

        result = handler.handle_ready_to_merge_stage(state)

        assert result == 1
        mock_github_client.merge_pr.assert_not_called()

    def test_manual_merge_run_is_untouched(self, handler, state, mock_github_client):
        """auto_merge=False pauses for the human as before — no new block."""
        state.options.auto_merge = False
        mock_github_client.get_pr_status.return_value = _pr_status("CHANGES_REQUESTED")

        result = handler.handle_ready_to_merge_stage(state)

        assert result == 2
        assert state.status == "paused"

    def test_sync_before_merge_is_not_spent_on_a_blocked_pr(
        self, handler, state, mock_github_client
    ):
        """The gate runs before the stale-branch sync, so no session/CI round is wasted."""
        state.options.sync_before_merge = True
        status = _pr_status("CHANGES_REQUESTED")
        status.merge_state_status = "BEHIND"
        mock_github_client.get_pr_status.return_value = status

        result = handler.handle_ready_to_merge_stage(state)

        assert result == 1
        assert state.workflow_stage != "resolving_conflicts"
        assert state.branch_sync_attempts == 0


class TestEveryOtherDecisionBehavesAsBefore:
    """APPROVED / REVIEW_REQUIRED / no decision must merge exactly as today."""

    @pytest.mark.parametrize("decision", ["APPROVED", "REVIEW_REQUIRED", None])
    def test_merges(self, handler, state, mock_github_client, decision):
        mock_github_client.get_pr_status.side_effect = [_pr_status(decision), _merged()]

        result = handler.handle_ready_to_merge_stage(state)

        assert result is None
        assert state.workflow_stage == "merged"
        mock_github_client.merge_pr.assert_called_once_with(42, admin=False)

    def test_unreadable_decision_never_blocks_a_merge(self, handler, state, mock_github_client):
        """A lookup that degrades to a non-string must merge, not wedge."""
        status = _pr_status(None)
        status.review_decision = object()  # not a str: unparsed/unavailable
        mock_github_client.get_pr_status.side_effect = [status, _merged()]

        result = handler.handle_ready_to_merge_stage(state)

        assert result is None
        mock_github_client.merge_pr.assert_called_once()

    def test_lowercase_decision_still_recognised(self, handler, state, mock_github_client):
        """Case is GitHub's; the gate must not depend on it."""
        mock_github_client.get_pr_status.return_value = _pr_status("changes_requested")

        result = handler.handle_ready_to_merge_stage(state)

        assert result == 1
        mock_github_client.merge_pr.assert_not_called()


class TestBotChangesRequestedDoesNotBlock:
    """Regression: a review bot's CHANGES_REQUESTED blocked green PRs forever.

    claudetm answers a bot's comments and resolves its threads, but no bot comes
    back to dismiss its own review, so `reviewDecision` stayed CHANGES_REQUESTED
    and the run blocked on a fully-addressed, green PR. Three PRs blocked this way
    in one night; two of the reviews were CodeRabbit quota notices, the same
    condition already discounted on the CI axis.
    """

    def test_bot_only_changes_requested_merges(self, handler, state, mock_github_client):
        mock_github_client.get_pr_status.side_effect = [
            _pr_status(
                "CHANGES_REQUESTED",
                changes_requested_by=["coderabbitai"],
                changes_requested_bots=["coderabbitai"],
            ),
            _merged(),
        ]

        result = handler.handle_ready_to_merge_stage(state)

        assert state.status != "blocked"
        assert result != 1
        mock_github_client.merge_pr.assert_called_once()

    def test_human_among_bots_still_blocks(self, handler, state, mock_github_client):
        """The gate exists for the human. One is enough, however many bots agree."""
        mock_github_client.get_pr_status.return_value = _pr_status(
            "CHANGES_REQUESTED",
            changes_requested_by=["coderabbitai", "sebi"],
            changes_requested_bots=["coderabbitai"],
        )

        result = handler.handle_ready_to_merge_stage(state)

        assert result == 1
        assert state.status == "blocked"
        mock_github_client.merge_pr.assert_not_called()

    def test_unreadable_reviewers_still_blocks(self, handler, state, mock_github_client):
        """Not knowing who requested changes is not the same as nobody having."""
        mock_github_client.get_pr_status.return_value = _pr_status("CHANGES_REQUESTED")

        result = handler.handle_ready_to_merge_stage(state)

        assert result == 1
        assert state.status == "blocked"
        mock_github_client.merge_pr.assert_not_called()

    def test_bot_login_suffix_counts_as_a_bot(self, handler, state, mock_github_client):
        """An integration reporting itself as a User still reads as a bot."""
        mock_github_client.get_pr_status.side_effect = [
            _pr_status(
                "CHANGES_REQUESTED",
                changes_requested_by=["coderabbitai[bot]"],
                changes_requested_bots=["coderabbitai[bot]"],
            ),
            _merged(),
        ]

        result = handler.handle_ready_to_merge_stage(state)

        assert result != 1
        assert state.status != "blocked"
        mock_github_client.merge_pr.assert_called_once()

    def test_partial_attribution_still_blocks(self, handler, state, mock_github_client):
        """A dropped reviewer could be the one human, so all-bots is not provable."""
        mock_github_client.get_pr_status.return_value = _pr_status(
            "CHANGES_REQUESTED",
            changes_requested_by=["coderabbitai"],
            changes_requested_bots=["coderabbitai"],
            changes_requested_complete=False,
        )

        result = handler.handle_ready_to_merge_stage(state)

        assert result == 1
        assert state.status == "blocked"
        mock_github_client.merge_pr.assert_not_called()
