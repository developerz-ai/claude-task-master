"""Tests for handle_releasing_stage and handle_release_fix_stage.

This file covers edge cases that complement the broader workflow-stage tests in
test_workflow_stages.py (which already covers the happy-path and counter-
persistence scenarios).  Focus here:

- No release guide → immediate skip / advance
- interruptible_sleep interrupted → early None return
- Per-PR release checks extracted from plan.md and injected into prompt
- PR title fetched and injected into prompt
- GitHub API exception during PR title fetch (graceful degradation)
- run_release_check exception → advance (never blocks pipeline)
- SKIP status in output → advance (not blocked)
- handle_release_fix_stage exception from run_work_session → advance
- handle_release_fix_stage routes via run_work_session (not run_release_check)
- handle_release_fix_stage resets current_pr for re-discovery
- handle_release_fix_stage transitions to pr_created after fix session
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.agent import ModelType
from claude_task_master.core.state import TaskOptions, TaskState
from claude_task_master.core.workflow_stages import WorkflowStageHandler

# ---------------------------------------------------------------------------
# Shared fixtures (mirror the minimal set from test_workflow_stages.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_real_sleep() -> Generator[None, None, None]:
    """Prevent any un-patched time.sleep from blocking tests."""
    with patch("time.sleep"):
        yield


@pytest.fixture
def mock_agent() -> MagicMock:
    """Mock agent — release checks return PASS by default."""
    agent = MagicMock()
    agent.run_release_check = MagicMock(
        return_value={"output": "RELEASE_CHECK: PASS", "success": True}
    )
    agent.run_work_session = MagicMock(return_value={"output": "Fix done", "success": True})
    return agent


@pytest.fixture
def mock_github_client() -> MagicMock:
    """Mock GitHub client — PR title returns a sensible default."""
    client = MagicMock()
    pr_status = MagicMock()
    pr_status.title = "feat: add cool feature"
    client.get_pr_status = MagicMock(return_value=pr_status)
    return client


@pytest.fixture
def mock_pr_context() -> MagicMock:
    """Minimal PR context mock."""
    ctx = MagicMock()
    ctx.get_combined_feedback = MagicMock(return_value=(False, False, None))
    return ctx


@pytest.fixture
def task_state(state_manager) -> TaskState:
    """A TaskState pre-configured for the releasing stage."""
    now = datetime.now().isoformat()
    options = TaskOptions(auto_merge=True, enable_release=True, max_sessions=10)
    state = TaskState(
        status="working",
        workflow_stage="releasing",
        current_task_index=0,
        session_count=1,
        current_pr=42,
        created_at=now,
        updated_at=now,
        run_id="test-run",
        model="sonnet",
        options=options,
    )
    return state


@pytest.fixture
def workflow_handler(mock_agent, state_manager, mock_github_client, mock_pr_context):
    """WorkflowStageHandler wired with mocks."""
    return WorkflowStageHandler(
        agent=mock_agent,
        state_manager=state_manager,
        github_client=mock_github_client,
        pr_context=mock_pr_context,
    )


@pytest.fixture
def release_ready(
    state_manager: MagicMock, task_state: TaskState, mock_github_client: MagicMock
) -> TaskState:
    """Persist a release guide + minimal plan so handle_releasing_stage can run."""
    state_manager.state_dir.mkdir(exist_ok=True)
    state_manager.save_plan("- [ ] Task 1")
    state_manager.save_release_guide("# Release Guide\n\n1. Check /health")
    return task_state


# ===========================================================================
# TestReleasingStageNoReleaseGuide
# ===========================================================================


class TestReleasingStageNoReleaseGuide:
    """Without a release guide the stage must skip and advance immediately."""

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_no_guide_advances_to_next_task(
        self, mock_console, mock_sleep, workflow_handler, state_manager, task_state
    ) -> None:
        """No release guide → advance to next task without sleeping or checking."""
        state_manager.state_dir.mkdir(exist_ok=True)
        # Deliberately do NOT save a release guide.

        result = workflow_handler.handle_releasing_stage(task_state)

        assert result is None
        assert task_state.workflow_stage == "working"
        assert task_state.current_task_index == 1
        mock_sleep.assert_not_called()

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_no_guide_never_calls_release_check(
        self, mock_console, mock_sleep, workflow_handler, state_manager, task_state, mock_agent
    ) -> None:
        """run_release_check must not be called when no guide is present."""
        state_manager.state_dir.mkdir(exist_ok=True)

        workflow_handler.handle_releasing_stage(task_state)

        mock_agent.run_release_check.assert_not_called()


# ===========================================================================
# TestReleasingStageInterruptedSleep
# ===========================================================================


class TestReleasingStageInterruptedSleep:
    """interruptible_sleep returning False means shutdown was requested."""

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_interrupted_sleep_returns_none(
        self, mock_console, mock_sleep, workflow_handler, release_ready, mock_agent
    ) -> None:
        """When sleep is interrupted (returns False) the stage exits with None
        and does NOT run the release check."""
        mock_sleep.return_value = False

        result = workflow_handler.handle_releasing_stage(release_ready)

        assert result is None
        mock_agent.run_release_check.assert_not_called()

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_interrupted_sleep_does_not_advance(
        self, mock_console, mock_sleep, workflow_handler, release_ready
    ) -> None:
        """State should not be mutated when sleep is interrupted."""
        mock_sleep.return_value = False
        original_index = release_ready.current_task_index

        workflow_handler.handle_releasing_stage(release_ready)

        assert release_ready.current_task_index == original_index
        assert release_ready.workflow_stage == "releasing"


# ===========================================================================
# TestReleasingStageSkipStatus
# ===========================================================================


class TestReleasingStageSkipStatus:
    """A SKIP status in the release-check output must advance, not fail."""

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_skip_advances_to_next_task(
        self, mock_console, mock_sleep, workflow_handler, release_ready, mock_agent
    ) -> None:
        """RELEASE_CHECK: SKIP → advance to working."""
        mock_sleep.return_value = True
        mock_agent.run_release_check.return_value = {
            "output": "RELEASE_CHECK: SKIP — nothing to verify",
            "success": True,
        }

        result = workflow_handler.handle_releasing_stage(release_ready)

        assert result is None
        assert release_ready.workflow_stage == "working"
        assert release_ready.current_task_index == 1

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_skip_does_not_set_release_fix_stage(
        self, mock_console, mock_sleep, workflow_handler, release_ready, mock_agent
    ) -> None:
        """A SKIP must not send state to release_fix."""
        mock_sleep.return_value = True
        mock_agent.run_release_check.return_value = {
            "output": "RELEASE_CHECK: SKIP",
            "success": True,
        }

        workflow_handler.handle_releasing_stage(release_ready)

        assert release_ready.workflow_stage != "release_fix"


# ===========================================================================
# TestReleasingStageExceptionHandling
# ===========================================================================


class TestReleasingStageExceptionHandling:
    """Exceptions from run_release_check must never block the pipeline."""

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_release_check_exception_advances(
        self, mock_console, mock_sleep, workflow_handler, release_ready, mock_agent
    ) -> None:
        """An exception in run_release_check → advance to next task."""
        mock_sleep.return_value = True
        mock_agent.run_release_check.side_effect = RuntimeError("SDK down")

        result = workflow_handler.handle_releasing_stage(release_ready)

        assert result is None
        assert release_ready.workflow_stage == "working"
        assert release_ready.current_task_index == 1

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_release_check_exception_does_not_enter_release_fix(
        self, mock_console, mock_sleep, workflow_handler, release_ready, mock_agent
    ) -> None:
        """Exception path must never route to release_fix."""
        mock_sleep.return_value = True
        mock_agent.run_release_check.side_effect = Exception("timeout")

        workflow_handler.handle_releasing_stage(release_ready)

        assert release_ready.workflow_stage != "release_fix"


# ===========================================================================
# TestReleasingStagePerPRChecks
# ===========================================================================


class TestReleasingStagePerPRChecks:
    """Per-PR release checks from plan.md are extracted and injected into prompt."""

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_per_pr_checks_appear_in_prompt(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        task_state,
        mock_agent,
    ) -> None:
        """When plan.md has a PR 1 release-checks section it must reach the prompt."""
        state_manager.state_dir.mkdir(exist_ok=True)
        plan = "## PR 1: add feature\n- [ ] Task 1\n\n**Release checks:**\n- curl /health → 200\n"
        state_manager.save_plan(plan)
        state_manager.save_release_guide("# Release Guide\n\n1. Check /health")
        mock_sleep.return_value = True

        workflow_handler.handle_releasing_stage(task_state)

        call_args = mock_agent.run_release_check.call_args
        prompt = call_args.args[0]
        assert "/health" in prompt

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_no_matching_pr_group_still_runs_check(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        state_manager,
        task_state,
        mock_agent,
    ) -> None:
        """If no PR group matches, the check still runs (without per-PR section)."""
        state_manager.state_dir.mkdir(exist_ok=True)
        # Plan with PR 2 only — current task is in PR 1, so no match.
        state_manager.save_plan(
            "## PR 2: something else\n- [ ] Task 1\n\n**Release checks:**\n- check db\n"
        )
        state_manager.save_release_guide("# Release Guide\n\nCheck /health")
        mock_sleep.return_value = True

        result = workflow_handler.handle_releasing_stage(task_state)

        # Should still call release check (without per-PR checks injected).
        mock_agent.run_release_check.assert_called_once()
        assert result is None


# ===========================================================================
# TestReleasingStagePromptContent
# ===========================================================================


class TestReleasingStagePromptContent:
    """The built prompt must include expected markers."""

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_prompt_contains_release_verification_marker(
        self, mock_console, mock_sleep, workflow_handler, release_ready, mock_agent
    ) -> None:
        """The built prompt must contain the 'RELEASE VERIFICATION' header."""
        mock_sleep.return_value = True

        workflow_handler.handle_releasing_stage(release_ready)

        prompt = mock_agent.run_release_check.call_args.args[0]
        assert "RELEASE VERIFICATION" in prompt

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_release_check_uses_sonnet_model(
        self, mock_console, mock_sleep, workflow_handler, release_ready, mock_agent
    ) -> None:
        """Release verification must use the Sonnet model (fast, not Opus)."""
        mock_sleep.return_value = True

        workflow_handler.handle_releasing_stage(release_ready)

        kwargs = mock_agent.run_release_check.call_args.kwargs
        assert kwargs.get("model_override") == ModelType.SONNET

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_pr_title_included_in_prompt(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        release_ready,
        mock_agent,
        mock_github_client,
    ) -> None:
        """PR title from GitHub is injected into the prompt for context."""
        mock_sleep.return_value = True
        pr_status = MagicMock()
        pr_status.title = "feat: unique-title-xyz"
        mock_github_client.get_pr_status.return_value = pr_status

        workflow_handler.handle_releasing_stage(release_ready)

        prompt = mock_agent.run_release_check.call_args.args[0]
        assert "unique-title-xyz" in prompt

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_github_error_fetching_title_still_runs_check(
        self,
        mock_console,
        mock_sleep,
        workflow_handler,
        release_ready,
        mock_agent,
        mock_github_client,
    ) -> None:
        """If GitHub raises while getting PR title, check still runs without blocking."""
        mock_sleep.return_value = True
        mock_github_client.get_pr_status.side_effect = Exception("GitHub down")

        result = workflow_handler.handle_releasing_stage(release_ready)

        mock_agent.run_release_check.assert_called_once()
        assert result is None


# ===========================================================================
# TestReleasingStageMaxAttemptsAtLimit
# ===========================================================================


class TestReleasingStageMaxAttemptsCap:
    """When release_fix_attempts already equals max_release_fixes, skip the fix cycle."""

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_at_cap_advances_instead_of_entering_release_fix(
        self, mock_console, mock_sleep, workflow_handler, release_ready, mock_agent
    ) -> None:
        """After 5 fix attempts, a FAIL result advances rather than creating fix #6."""
        mock_sleep.return_value = True
        mock_agent.run_release_check.return_value = {
            "output": "RELEASE_CHECK: FAIL — /health 503",
            "success": True,
        }
        release_ready.release_fix_attempts = 5  # already at max

        result = workflow_handler.handle_releasing_stage(release_ready)

        assert result is None
        assert release_ready.workflow_stage == "working"  # advanced, not release_fix
        assert release_ready.current_task_index == 1


# ===========================================================================
# TestHandleReleaseFixStage
# ===========================================================================


class TestHandleReleaseFixStage:
    """Tests for handle_release_fix_stage behaviour."""

    @pytest.fixture
    def fix_state(self, state_manager: MagicMock, task_state: TaskState) -> TaskState:
        """State ready to enter the release_fix handler."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_release_guide("# Release Guide\n\nCheck /health")
        task_state.workflow_stage = "release_fix"
        task_state.release_fix_attempts = 0
        task_state.in_release_fix = False
        task_state.current_pr = 42
        task_state.release_fix_details = "Health check returned 503"
        return task_state

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_uses_run_work_session_not_release_check(
        self, mock_console, mock_sleep, workflow_handler, fix_state, mock_agent
    ) -> None:
        """Fix sessions run through run_work_session, NOT run_release_check."""
        mock_sleep.return_value = True

        workflow_handler.handle_release_fix_stage(fix_state)

        mock_agent.run_work_session.assert_called_once()
        mock_agent.run_release_check.assert_not_called()

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_transitions_to_pr_created_on_success(
        self, mock_console, mock_sleep, workflow_handler, fix_state, mock_agent
    ) -> None:
        """After a successful fix session, state moves to pr_created."""
        mock_sleep.return_value = True

        workflow_handler.handle_release_fix_stage(fix_state)

        assert fix_state.workflow_stage == "pr_created"

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_resets_current_pr_for_rediscovery(
        self, mock_console, mock_sleep, workflow_handler, fix_state, mock_agent
    ) -> None:
        """current_pr is cleared so pr_created re-discovers the fix PR's number."""
        mock_sleep.return_value = True

        workflow_handler.handle_release_fix_stage(fix_state)

        assert fix_state.current_pr is None

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_increments_attempt_counter(
        self, mock_console, mock_sleep, workflow_handler, fix_state, mock_agent
    ) -> None:
        """Each call to handle_release_fix_stage increments release_fix_attempts."""
        mock_sleep.return_value = True
        fix_state.release_fix_attempts = 2

        workflow_handler.handle_release_fix_stage(fix_state)

        assert fix_state.release_fix_attempts == 3

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_sets_in_release_fix_flag(
        self, mock_console, mock_sleep, workflow_handler, fix_state, mock_agent
    ) -> None:
        """in_release_fix is set True so a subsequent PR merge preserves the counter."""
        mock_sleep.return_value = True
        fix_state.in_release_fix = False

        workflow_handler.handle_release_fix_stage(fix_state)

        assert fix_state.in_release_fix is True

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_work_session_exception_advances(
        self, mock_console, mock_sleep, workflow_handler, fix_state, mock_agent
    ) -> None:
        """If run_work_session raises, stage advances without blocking the pipeline."""
        mock_sleep.return_value = True
        mock_agent.run_work_session.side_effect = RuntimeError("agent crashed")

        result = workflow_handler.handle_release_fix_stage(fix_state)

        assert result is None
        assert fix_state.workflow_stage == "working"
        assert fix_state.current_task_index == 1

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_interrupted_sleep_returns_none(
        self, mock_console, mock_sleep, workflow_handler, fix_state, mock_agent
    ) -> None:
        """If the post-fix sleep is interrupted, the stage returns None immediately."""
        # First sleep (the 60s post-fix wait) is interrupted.
        mock_sleep.return_value = False

        result = workflow_handler.handle_release_fix_stage(fix_state)

        assert result is None

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_fix_uses_sonnet_model(
        self, mock_console, mock_sleep, workflow_handler, fix_state, mock_agent
    ) -> None:
        """Release fix sessions use Sonnet (speed matters; Opus is overkill here)."""
        mock_sleep.return_value = True

        workflow_handler.handle_release_fix_stage(fix_state)

        kwargs = mock_agent.run_work_session.call_args.kwargs
        assert kwargs.get("model_override") == ModelType.SONNET

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_failed_checks_injected_when_present(
        self, mock_console, mock_sleep, workflow_handler, fix_state, mock_agent
    ) -> None:
        """Persisted failure details appear under '## Failed Checks' in the prompt."""
        mock_sleep.return_value = True
        fix_state.release_fix_details = "Sentry spike: NullPointerException in checkout"

        workflow_handler.handle_release_fix_stage(fix_state)

        task_desc = mock_agent.run_work_session.call_args.kwargs["task_description"]
        assert "## Failed Checks" in task_desc
        assert "NullPointerException in checkout" in task_desc

    @patch("claude_task_master.core.stages.release_stage.interruptible_sleep")
    @patch("claude_task_master.core.stages.release_stage.console")
    def test_no_release_guide_fallback_prompt_still_runs(
        self, mock_console, mock_sleep, workflow_handler, state_manager, task_state, mock_agent
    ) -> None:
        """Even without a release guide the fix prompt is built and fix runs."""
        state_manager.state_dir.mkdir(exist_ok=True)
        # No release guide saved on purpose.
        task_state.release_fix_details = "DB migration missing"
        mock_sleep.return_value = True

        result = workflow_handler.handle_release_fix_stage(task_state)

        mock_agent.run_work_session.assert_called_once()
        assert result is None
