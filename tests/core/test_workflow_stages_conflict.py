"""Tests for AI merge-conflict resolution (_MergeStage routing + _ConflictStage).

Covers the path a CONFLICTING PR takes now that conflicts are handed to an agent
instead of blocking the run:

- ready_to_merge routes a CONFLICTING PR into resolving_conflicts and counts it
- waiting_ci does the same: the base can move while CI runs
- resolve_conflicts=False keeps the old block-for-manual-resolution behavior
- attempts are bounded by MAX_CONFLICT_FIX_ATTEMPTS, then block
- the resolution session runs push-only on the PR's head branch and returns the
  PR to waiting_ci so the push's CI run is picked up
- a session that raises blocks rather than looping
- the prompt rebases (force-push with lease) and names the real base branch
- a merely-behind PR is left alone unless --sync-before-merge is passed
- the counter resets when the task advances
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.agent import ModelType
from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler


@pytest.fixture(autouse=True)
def _no_real_sleep() -> Generator[None, None, None]:
    """Prevent any un-patched time.sleep from blocking tests."""
    with patch("time.sleep"):
        yield


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.run_work_session = MagicMock(return_value={"output": "resolved", "success": True})
    return agent


@pytest.fixture
def mock_pr_status() -> MagicMock:
    status = MagicMock()
    status.state = "OPEN"
    status.mergeable = "CONFLICTING"
    status.base_branch = "main"
    return status


@pytest.fixture
def mock_github_client(mock_pr_status: MagicMock) -> MagicMock:
    client = MagicMock()
    client.get_pr_status = MagicMock(return_value=mock_pr_status)
    client.get_pr_behind_by = MagicMock(return_value=0)
    return client


@pytest.fixture
def mock_pr_context() -> MagicMock:
    return MagicMock()


@pytest.fixture
def workflow_handler(
    mock_agent: MagicMock,
    state_manager,
    mock_github_client: MagicMock,
    mock_pr_context: MagicMock,
) -> WorkflowStageHandler:
    return WorkflowStageHandler(
        agent=mock_agent,
        state_manager=state_manager,
        github_client=mock_github_client,
        pr_context=mock_pr_context,
    )


@pytest.fixture
def task_state(state_manager) -> TaskState:
    state_manager.state_dir.mkdir(exist_ok=True)
    now = datetime.now().isoformat()
    return TaskState(
        status="working",
        workflow_stage="ready_to_merge",
        current_task_index=0,
        session_count=1,
        current_pr=42,
        created_at=now,
        updated_at=now,
        run_id="test-run",
        model="sonnet",
        options=TaskOptions(auto_merge=True),
    )


# ===========================================================================
# Routing out of waiting_ci
# ===========================================================================


class TestConflictDuringCiWait:
    """A PR can turn conflicting while CI runs — the base moves under it."""

    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_conflict_while_waiting_for_ci_routes_to_resolution(
        self, _console, workflow_handler, task_state, mock_pr_status
    ):
        """Regression: waiting_ci blocked the whole run with "PR has merge
        conflicts - needs manual resolution" and exit 1, while the agent
        resolver was wired only into ready_to_merge. A base branch moving
        during a CI wait therefore killed the run.
        """
        task_state.workflow_stage = "waiting_ci"
        mock_pr_status.ci_state = "PENDING"
        mock_pr_status.check_details = [
            {"name": "Tests", "status": "COMPLETED", "conclusion": "SUCCESS"}
        ]

        result = workflow_handler.handle_waiting_ci_stage(task_state)

        assert result is None, "the run should continue, not exit"
        assert task_state.workflow_stage == "resolving_conflicts"
        assert task_state.status == "working"
        assert task_state.conflict_fix_attempts == 1

    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_resolution_disabled_still_blocks_from_waiting_ci(
        self, _console, workflow_handler, task_state, mock_pr_status
    ):
        """--no-resolve-conflicts keeps the manual-resolution behavior here too."""
        task_state.workflow_stage = "waiting_ci"
        task_state.options.resolve_conflicts = False
        mock_pr_status.ci_state = "PENDING"
        mock_pr_status.check_details = [
            {"name": "Tests", "status": "COMPLETED", "conclusion": "SUCCESS"}
        ]

        result = workflow_handler.handle_waiting_ci_stage(task_state)

        assert result == 1
        assert task_state.status == "blocked"

    @patch("claude_task_master.core.stages.ci_stage.console")
    def test_attempts_are_bounded_from_waiting_ci(
        self, _console, workflow_handler, task_state, mock_pr_status
    ):
        """Both entry points share one counter, so a conflict that keeps coming
        back cannot loop forever regardless of which stage notices it."""
        task_state.workflow_stage = "waiting_ci"
        task_state.conflict_fix_attempts = workflow_handler.MAX_CONFLICT_FIX_ATTEMPTS
        mock_pr_status.ci_state = "PENDING"
        mock_pr_status.check_details = [
            {"name": "Tests", "status": "COMPLETED", "conclusion": "SUCCESS"}
        ]

        result = workflow_handler.handle_waiting_ci_stage(task_state)

        assert result == 1
        assert task_state.status == "blocked"


# ===========================================================================
# Routing out of ready_to_merge
# ===========================================================================


class TestConflictRouting:
    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_conflicting_pr_routes_to_resolution(
        self, _console, workflow_handler, task_state, mock_github_client
    ):
        """A CONFLICTING PR enters resolving_conflicts instead of blocking."""
        result = workflow_handler.handle_ready_to_merge_stage(task_state)

        assert result is None
        assert task_state.workflow_stage == "resolving_conflicts"
        assert task_state.status == "working"
        assert task_state.conflict_fix_attempts == 1
        mock_github_client.merge_pr.assert_not_called()

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_resolution_disabled_blocks(self, _console, workflow_handler, task_state):
        """resolve_conflicts=False keeps the manual-resolution behavior."""
        task_state.options.resolve_conflicts = False

        result = workflow_handler.handle_ready_to_merge_stage(task_state)

        assert result == 1
        assert task_state.status == "blocked"
        assert task_state.conflict_fix_attempts == 0

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_attempts_are_bounded(self, _console, workflow_handler, task_state):
        """Blocks once MAX_CONFLICT_FIX_ATTEMPTS resolution passes have run."""
        task_state.conflict_fix_attempts = workflow_handler.MAX_CONFLICT_FIX_ATTEMPTS

        result = workflow_handler.handle_ready_to_merge_stage(task_state)

        assert result == 1
        assert task_state.status == "blocked"
        # Counter is not incremented past the cap.
        assert task_state.conflict_fix_attempts == workflow_handler.MAX_CONFLICT_FIX_ATTEMPTS

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_each_conflict_increments_the_counter(self, _console, workflow_handler, task_state):
        """Successive conflict routings walk the counter toward the cap."""
        for expected in (1, 2, 3):
            task_state.workflow_stage = "ready_to_merge"
            workflow_handler.handle_ready_to_merge_stage(task_state)
            assert task_state.conflict_fix_attempts == expected


# ===========================================================================
# Staleness: green CI against an older base is not good enough
# ===========================================================================


class TestSyncBeforeMerge:
    @pytest.fixture(autouse=True)
    def _mergeable(self, mock_pr_status: MagicMock, task_state) -> Generator[None, None, None]:
        """These tests are about a clean-but-behind PR, not a conflicting one.

        Syncing a merely-behind PR is opt-in, so these tests turn it on; the
        default-off behavior has its own test below.

        The post-merge confirmation poll sleeps between polls; patch it so the
        merging paths run at test speed.
        """
        mock_pr_status.mergeable = "MERGEABLE"
        mock_pr_status.merge_state_status = "CLEAN"
        mock_pr_status.head_branch = "feature/x"
        task_state.options.sync_before_merge = True
        with patch(
            "claude_task_master.core.stages.merge_stage.interruptible_sleep", return_value=True
        ):
            yield

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_behind_base_syncs_before_merging(
        self, _console, workflow_handler, task_state, mock_github_client
    ):
        """A PR behind its base is synced, not merged."""
        mock_github_client.get_pr_behind_by.return_value = 4

        result = workflow_handler.handle_ready_to_merge_stage(task_state)

        assert result is None
        assert task_state.workflow_stage == "resolving_conflicts"
        assert task_state.branch_sync_attempts == 1
        mock_github_client.merge_pr.assert_not_called()
        mock_github_client.get_pr_behind_by.assert_called_once_with(42, "main", "feature/x")

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_up_to_date_pr_merges(self, _console, workflow_handler, task_state, mock_github_client):
        """A current branch merges without a sync detour."""
        mock_github_client.get_pr_behind_by.return_value = 0

        workflow_handler.handle_ready_to_merge_stage(task_state)

        mock_github_client.merge_pr.assert_called_once()
        assert task_state.branch_sync_attempts == 0

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_merge_state_behind_also_syncs(
        self, _console, workflow_handler, task_state, mock_github_client, mock_pr_status
    ):
        """mergeStateStatus=BEHIND triggers a sync even if the compare API says 0."""
        mock_github_client.get_pr_behind_by.return_value = 0
        mock_pr_status.merge_state_status = "BEHIND"

        result = workflow_handler.handle_ready_to_merge_stage(task_state)

        assert result is None
        assert task_state.workflow_stage == "resolving_conflicts"

    # Regression: syncing was default-on, so a PR that merged cleanly and was one
    # commit behind main still burned an agent session plus a full CI round before
    # it could land. Only a PR that genuinely cannot merge earns that session.
    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_behind_but_clean_pr_merges_by_default(
        self, _console, workflow_handler, task_state, mock_github_client
    ):
        """Without --sync-before-merge, being behind is not a reason to detour."""
        task_state.options.sync_before_merge = False
        mock_github_client.get_pr_behind_by.return_value = 1

        workflow_handler.handle_ready_to_merge_stage(task_state)

        mock_github_client.merge_pr.assert_called_once()
        assert task_state.workflow_stage != "resolving_conflicts"
        assert task_state.branch_sync_attempts == 0

    def test_sync_is_opt_in(self):
        """The default carries the policy — a fresh run does not sync."""
        from claude_task_master.core.state_models import TaskOptions

        assert TaskOptions().sync_before_merge is False

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_sync_disabled_merges_stale_pr(
        self, _console, workflow_handler, task_state, mock_github_client
    ):
        """--no-sync-before-merge merges without checking freshness."""
        task_state.options.sync_before_merge = False
        mock_github_client.get_pr_behind_by.return_value = 9

        workflow_handler.handle_ready_to_merge_stage(task_state)

        mock_github_client.merge_pr.assert_called_once()
        mock_github_client.get_pr_behind_by.assert_not_called()

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_sync_attempts_are_bounded_then_merges(
        self, _console, workflow_handler, task_state, mock_github_client
    ):
        """A base that outruns the PR does not stall it forever."""
        mock_github_client.get_pr_behind_by.return_value = 2
        task_state.branch_sync_attempts = workflow_handler.MAX_BRANCH_SYNC_ATTEMPTS

        workflow_handler.handle_ready_to_merge_stage(task_state)

        mock_github_client.merge_pr.assert_called_once()

    @patch("claude_task_master.core.stages.merge_stage.console")
    def test_compare_api_failure_does_not_block_merge(
        self, _console, workflow_handler, task_state, mock_github_client
    ):
        """A broken compare call falls through to the merge, not to a stall."""
        mock_github_client.get_pr_behind_by.side_effect = RuntimeError("api down")

        workflow_handler.handle_ready_to_merge_stage(task_state)

        mock_github_client.merge_pr.assert_called_once()

    @patch("claude_task_master.core.stages.conflict_stage.interruptible_sleep", return_value=True)
    @patch("claude_task_master.core.stages.conflict_stage.console")
    def test_sync_session_uses_the_sync_prompt(
        self, _console, _sleep, workflow_handler, task_state, mock_agent
    ):
        """A behind-but-clean PR gets the sync framing, not the conflict framing."""
        task_state.workflow_stage = "resolving_conflicts"
        task_state.branch_sync_attempts = 1

        workflow_handler.handle_resolving_conflicts_stage(task_state)

        prompt = mock_agent.run_work_session.call_args.kwargs["task_description"]
        assert "is behind `main`" in prompt
        assert "has merge conflicts" not in prompt
        assert "git rebase origin/main" in prompt

    def test_sync_prompt_explains_why_ci_is_not_enough(self, workflow_handler):
        prompt = workflow_handler._build_conflict_resolution_task(7, "main", 1, conflicted=False)

        assert "CI passed against an older main" in prompt

    # Regression: the session merged the base in, leaving a merge commit on every
    # PR that touched a moving base. It rebases now, which needs a lease-guarded
    # force-push — a plain `git push` is rejected against a rewritten branch.
    @pytest.mark.parametrize("conflicted", [True, False])
    def test_resolution_prompt_rebases_and_force_pushes(self, workflow_handler, conflicted):
        prompt = workflow_handler._build_conflict_resolution_task(
            7, "main", 1, conflicted=conflicted
        )

        assert "git rebase origin/main" in prompt
        assert "git rebase --continue" in prompt
        assert "git push --force-with-lease origin HEAD" in prompt
        assert "git merge origin/main" not in prompt

    def test_advance_to_next_task_resets_sync_counter(self, workflow_handler, task_state):
        task_state.branch_sync_attempts = 2

        workflow_handler._advance_to_next_task(task_state)

        assert task_state.branch_sync_attempts == 0


# ===========================================================================
# The resolution session
# ===========================================================================


class TestConflictResolutionStage:
    @patch("claude_task_master.core.stages.conflict_stage.interruptible_sleep", return_value=True)
    @patch("claude_task_master.core.stages.conflict_stage.console")
    def test_runs_push_only_session_and_returns_to_ci(
        self, _console, _sleep, workflow_handler, task_state, mock_agent
    ):
        """Runs a push-only session, then hands the PR back to waiting_ci."""
        task_state.workflow_stage = "resolving_conflicts"
        task_state.conflict_fix_attempts = 1

        result = workflow_handler.handle_resolving_conflicts_stage(task_state)

        assert result is None
        assert task_state.workflow_stage == "waiting_ci"
        assert task_state.session_count == 2

        kwargs = mock_agent.run_work_session.call_args.kwargs
        assert kwargs["push_only"] is True
        assert kwargs["create_pr"] is False
        assert kwargs["model_override"] is ModelType.OPUS
        assert kwargs["target_branch"] == "main"
        # Rebasing is this session's job, so the push-only boilerplate must not
        # also carry its blanket "NEVER rebase" rule.
        assert kwargs["allow_rebase"] is True

    @patch("claude_task_master.core.stages.conflict_stage.interruptible_sleep", return_value=True)
    @patch("claude_task_master.core.stages.conflict_stage.console")
    def test_session_failure_blocks(
        self, _console, _sleep, workflow_handler, task_state, mock_agent
    ):
        """An exception from the session blocks instead of looping forever."""
        task_state.workflow_stage = "resolving_conflicts"
        mock_agent.run_work_session.side_effect = RuntimeError("agent died")

        result = workflow_handler.handle_resolving_conflicts_stage(task_state)

        assert result == 1
        assert task_state.status == "blocked"

    @patch("claude_task_master.core.stages.conflict_stage.interruptible_sleep", return_value=False)
    @patch("claude_task_master.core.stages.conflict_stage.console")
    def test_interrupted_sleep_returns_early(self, _console, _sleep, workflow_handler, task_state):
        """A Ctrl+C during the post-push wait leaves the stage untouched."""
        task_state.workflow_stage = "resolving_conflicts"

        result = workflow_handler.handle_resolving_conflicts_stage(task_state)

        assert result is None
        assert task_state.workflow_stage == "resolving_conflicts"

    @patch("claude_task_master.core.stages.conflict_stage.console")
    def test_no_pr_falls_back_to_merge_stage(self, _console, workflow_handler, task_state):
        """Without a PR there is nothing to resolve — rejoin the merge path."""
        task_state.workflow_stage = "resolving_conflicts"
        task_state.current_pr = None

        result = workflow_handler.handle_resolving_conflicts_stage(task_state)

        assert result is None
        assert task_state.workflow_stage == "ready_to_merge"

    def test_base_branch_falls_back_to_main(self, workflow_handler, mock_github_client):
        """A GitHub error while reading the base branch degrades to main."""
        mock_github_client.get_pr_status.side_effect = RuntimeError("api down")

        assert workflow_handler._get_pr_base_branch(42) == "main"


# ===========================================================================
# The prompt
# ===========================================================================


class TestConflictPrompt:
    def test_prompt_rebases_and_names_base_branch(self, workflow_handler):
        prompt = workflow_handler._build_conflict_resolution_task(42, "develop", 1)

        assert "git rebase origin/develop" in prompt
        assert "gh pr create" in prompt  # explicitly forbidden
        assert "TASK COMPLETE" in prompt
        assert "attempt" not in prompt.split("## Step 1")[0].lower()

    def test_retry_prompt_flags_the_previous_pass(self, workflow_handler):
        prompt = workflow_handler._build_conflict_resolution_task(42, "main", 2)

        assert "attempt 2" in prompt
        assert "mid-rebase" in prompt


# ===========================================================================
# Counter lifecycle
# ===========================================================================


class TestConflictCounterReset:
    def test_advance_to_next_task_resets_counter(self, workflow_handler, task_state):
        task_state.conflict_fix_attempts = 2

        workflow_handler._advance_to_next_task(task_state)

        assert task_state.conflict_fix_attempts == 0
