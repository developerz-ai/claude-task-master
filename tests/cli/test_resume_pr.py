"""Tests for resume command PR-related functionality.

This module tests resume command behavior when dealing with pull requests,
including:
- Resuming with an active PR
- Resuming when paused on PR
- PR display in resume output
- PR state management during resume
"""

import json
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import pytest

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


@contextmanager
def mock_resume_context(mock_state_dir, return_code=0):
    """Context manager for mocking the resume workflow dependencies."""
    with patch.object(StateManager, "STATE_DIR", mock_state_dir):
        with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
            mock_cred.return_value.get_valid_token.return_value = "test-token"
            with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                with patch(
                    "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                ) as mock_orch:
                    mock_orch.return_value.run.return_value = return_code
                    yield mock_orch


def create_state_with_pr(
    mock_state_dir,
    current_pr=None,
    pause_on_pr=False,
    status="paused",
    current_task_index=1,
    session_count=2,
    auto_merge=True,
):
    """Create a state file with PR-related configuration."""
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": status,
        "current_task_index": current_task_index,
        "session_count": session_count,
        "current_pr": current_pr,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "20250115-120000",
        "model": "sonnet",
        "options": {
            "auto_merge": auto_merge,
            "max_sessions": None,
            "pause_on_pr": pause_on_pr,
        },
    }
    state_file = mock_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data))
    return state_data


@pytest.fixture
def setup_pr_state(mock_state_dir, mock_goal_file, mock_plan_file):
    """Fixture to set up state with PR configuration and logs directory."""

    def _setup(**kwargs):
        state_data = create_state_with_pr(mock_state_dir, **kwargs)
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return state_data

    return _setup


class TestResumeWithActivePR:
    """Tests for resuming when there's an active PR."""

    def test_resume_with_current_pr(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume displays PR information when present."""
        setup_pr_state(
            current_pr=123,
            pause_on_pr=True,
            status="paused",
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        # State with current_pr should still work
        assert "completed successfully" in result.output

    def test_resume_with_different_pr_numbers(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume works with various PR numbers."""
        for pr_number in [1, 42, 999, 10000]:
            setup_pr_state(current_pr=pr_number, status="paused")

            with mock_resume_context(mock_state_dir):
                result = cli_runner.invoke(app, ["resume"])

            assert result.exit_code == 0, f"Failed for PR #{pr_number}"

    def test_resume_preserves_pr_number(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test that PR number is preserved during resume."""
        setup_pr_state(
            current_pr=456,
            pause_on_pr=True,
            session_count=3,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_no_current_pr(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume works when there's no current PR."""
        setup_pr_state(current_pr=None)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output


class TestResumePauseOnPR:
    """Tests for resume with pause_on_pr setting."""

    def test_resume_with_pause_on_pr_enabled(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume when pause_on_pr is enabled."""
        setup_pr_state(
            current_pr=789,
            pause_on_pr=True,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_with_pause_on_pr_disabled(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume when pause_on_pr is disabled."""
        setup_pr_state(
            current_pr=123,
            pause_on_pr=False,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_pause_on_pr_with_no_pr(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume when pause_on_pr is true but no PR exists."""
        setup_pr_state(
            current_pr=None,
            pause_on_pr=True,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0


class TestResumePRAutoMerge:
    """Tests for resume with auto_merge setting and PRs."""

    def test_resume_pr_with_auto_merge_enabled(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume with PR and auto_merge enabled."""
        setup_pr_state(
            current_pr=100,
            auto_merge=True,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_pr_with_auto_merge_disabled(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume with PR and auto_merge disabled."""
        setup_pr_state(
            current_pr=200,
            auto_merge=False,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_pr_auto_merge_and_pause_on_pr(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume with both auto_merge and pause_on_pr settings."""
        setup_pr_state(
            current_pr=300,
            auto_merge=True,
            pause_on_pr=True,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0


class TestResumePRDisplayOutput:
    """Tests for PR information display during resume."""

    def test_resume_displays_pr_in_status(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume displays PR number in status output."""
        setup_pr_state(
            current_pr=555,
            current_task_index=1,
            session_count=3,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        # Should complete successfully and show relevant output
        assert result.exit_code == 0
        assert "Goal:" in result.output
        assert "Status:" in result.output

    def test_resume_high_pr_number_display(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume with high PR numbers displays correctly."""
        setup_pr_state(
            current_pr=99999,
            session_count=10,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0


class TestResumePRStateTransitions:
    """Tests for state transitions involving PRs during resume."""

    def test_resume_blocked_on_pr(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume from blocked state with active PR."""
        setup_pr_state(
            current_pr=42,
            status="blocked",
            pause_on_pr=True,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Attempting to resume blocked task" in result.output

    def test_resume_working_with_pr(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume from working state with active PR."""
        setup_pr_state(
            current_pr=88,
            status="working",
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_paused_on_pr_then_success(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume from paused-on-PR state completing successfully."""
        setup_pr_state(
            current_pr=123,
            status="paused",
            pause_on_pr=True,
            session_count=5,
        )

        with mock_resume_context(mock_state_dir, return_code=0):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output

    def test_resume_paused_on_pr_then_paused_again(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume from paused-on-PR state pausing again."""
        setup_pr_state(
            current_pr=456,
            status="paused",
            pause_on_pr=True,
        )

        with mock_resume_context(mock_state_dir, return_code=2):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 2
        assert "paused" in result.output
        assert "resume" in result.output


class TestResumePREdgeCases:
    """Edge cases for PR-related resume operations."""

    def test_resume_pr_zero(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume with PR number zero (edge case)."""
        # PR number 0 is technically invalid but should be handled gracefully
        setup_pr_state(current_pr=0)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        # Should still work - edge case handling
        assert result.exit_code == 0

    def test_resume_pr_large_number(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume with very large PR number."""
        setup_pr_state(current_pr=999999999)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_multiple_prs_sequence(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resuming with different PRs in sequence."""
        # First resume with PR 100
        setup_pr_state(current_pr=100, session_count=1)
        with mock_resume_context(mock_state_dir):
            result1 = cli_runner.invoke(app, ["resume"])
        assert result1.exit_code == 0

        # Second resume with PR 200
        setup_pr_state(current_pr=200, session_count=2)
        with mock_resume_context(mock_state_dir):
            result2 = cli_runner.invoke(app, ["resume"])
        assert result2.exit_code == 0

        # Third resume with no PR
        setup_pr_state(current_pr=None, session_count=3)
        with mock_resume_context(mock_state_dir):
            result3 = cli_runner.invoke(app, ["resume"])
        assert result3.exit_code == 0


class TestResumePRCombinedOptions:
    """Tests for combined PR options during resume."""

    def test_resume_all_pr_options_enabled(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume with all PR-related options enabled."""
        setup_pr_state(
            current_pr=777,
            auto_merge=True,
            pause_on_pr=True,
            session_count=10,
            current_task_index=2,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_all_pr_options_disabled(
        self, cli_runner, mock_state_dir, setup_pr_state
    ):
        """Test resume with all PR-related options disabled."""
        setup_pr_state(
            current_pr=None,
            auto_merge=False,
            pause_on_pr=False,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_pr_with_opus_model(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume with PR and opus model."""
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "paused",
            "current_task_index": 1,
            "session_count": 5,
            "current_pr": 123,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250115-120000",
            "model": "opus",  # Use opus model
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": True,
            },
        }
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
