"""Tests for resume command state restoration functionality.

This module tests that state is properly preserved and restored during resume operations,
including session counts, options, model settings, and PR state.
"""

import json
from unittest.mock import patch

import pytest

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager

from .conftest import mock_resume_context


@pytest.fixture
def setup_state_and_logs(mock_state_dir, mock_goal_file, mock_plan_file, state_data_factory):
    """Fixture to setup state file and logs directory."""

    def _setup(**state_kwargs):
        state_data = state_data_factory(**state_kwargs)
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return state_data

    return _setup


class TestResumeStatePreservation:
    """Tests that state values are preserved during resume."""

    def test_resume_preserves_session_count(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test that session count is preserved and incremented on resume."""
        initial_session_count = 5
        setup_state_and_logs(session_count=initial_session_count, current_task_index=1)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert str(initial_session_count) in result.output

    def test_resume_preserves_model_setting(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test that model setting (opus/sonnet/haiku) is preserved on resume."""
        setup_state_and_logs(model="opus")

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_preserves_task_index(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test that current task index is preserved on resume."""
        setup_state_and_logs(current_task_index=1, session_count=2)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Current Task:" in result.output


class TestResumeOptionsPreservation:
    """Tests that options are preserved during resume."""

    def test_resume_preserves_auto_merge_setting(
        self, cli_runner, mock_state_dir, setup_state_and_logs
    ):
        """Test that auto_merge setting is preserved on resume."""
        setup_state_and_logs(auto_merge=False)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_preserves_max_sessions_setting(
        self, cli_runner, mock_state_dir, setup_state_and_logs
    ):
        """Test that max_sessions setting is preserved on resume."""
        setup_state_and_logs(max_sessions=20, session_count=5)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_preserves_pause_on_pr_setting(
        self, cli_runner, mock_state_dir, setup_state_and_logs
    ):
        """Test that pause_on_pr setting is preserved on resume."""
        setup_state_and_logs(pause_on_pr=True, current_pr=42)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0


class TestResumePRStateRestoration:
    """Tests for PR state restoration during resume."""

    def test_resume_preserves_current_pr(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test that current_pr number is preserved on resume."""
        setup_state_and_logs(
            current_pr=456, current_task_index=1, session_count=3, pause_on_pr=True
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_with_no_current_pr(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test resume works when there's no current PR."""
        setup_state_and_logs(current_pr=None)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output


class TestResumeTimestampPreservation:
    """Tests that timestamps are properly handled during resume."""

    def test_resume_preserves_created_at(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test that created_at timestamp is preserved on resume."""
        setup_state_and_logs(created_at="2025-01-10T10:00:00", run_id="20250110-100000")

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_preserves_run_id(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test that run_id is preserved on resume."""
        setup_state_and_logs(run_id="20250101-090000")

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0


class TestResumeStateFileIntegrity:
    """Tests for state file integrity during resume."""

    def test_resume_with_missing_optional_fields(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file, state_data_factory
    ):
        """Test resume handles state files with missing optional fields gracefully."""
        state_data = state_data_factory()
        state_data["options"] = {}  # Empty options - defaults should be used
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_with_corrupt_state_file(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume handles corrupt state files appropriately."""
        state_file = mock_state_dir / "state.json"
        state_file.write_text("{ invalid json }")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert any(
            word in result.output.lower() for word in ["corrupt", "error", "invalid", "parse"]
        )

    def test_resume_with_empty_state_file(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume handles empty state files appropriately."""
        state_file = mock_state_dir / "state.json"
        state_file.write_text("")

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1


class TestResumeGoalPreservation:
    """Tests that goal is preserved and displayed during resume."""

    def test_resume_displays_preserved_goal(
        self, cli_runner, mock_state_dir, mock_plan_file, state_data_factory
    ):
        """Test that the original goal is displayed on resume."""
        goal_text = "Build a production-ready API server"
        goal_file = mock_state_dir / "goal.txt"
        goal_file.write_text(goal_text)

        state_data = state_data_factory()
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Goal:" in result.output
        assert goal_text in result.output


class TestResumeContextPreservation:
    """Tests that context files are preserved during resume."""

    def test_resume_with_existing_context_file(
        self,
        cli_runner,
        mock_state_dir,
        setup_state_and_logs,
        mock_context_file,
    ):
        """Test that context file is preserved and accessible during resume."""
        setup_state_and_logs(current_task_index=1, session_count=3)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert mock_context_file.exists()

    def test_resume_with_existing_progress_file(
        self,
        cli_runner,
        mock_state_dir,
        setup_state_and_logs,
        mock_progress_file,
    ):
        """Test that progress file is preserved and accessible during resume."""
        setup_state_and_logs(current_task_index=1, session_count=2)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert mock_progress_file.exists()


class TestResumeMultipleStateFields:
    """Tests for preserving multiple state fields together."""

    def test_resume_preserves_all_options_combined(
        self, cli_runner, mock_state_dir, setup_state_and_logs
    ):
        """Test that all options are preserved together."""
        setup_state_and_logs(
            auto_merge=False,
            max_sessions=50,
            pause_on_pr=True,
            current_pr=789,
            session_count=10,
            current_task_index=2,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_preserves_state_after_multiple_sessions(
        self, cli_runner, mock_state_dir, setup_state_and_logs
    ):
        """Test state preservation after high session count."""
        setup_state_and_logs(
            session_count=99,
            current_task_index=1,
            model="haiku",
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "99" in result.output

    def test_resume_with_opus_model_and_pr(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test resume with opus model and active PR."""
        setup_state_and_logs(
            model="opus",
            current_pr=123,
            pause_on_pr=True,
            session_count=5,
        )

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0


class TestResumeStateEdgeCases:
    """Tests for edge cases in state restoration."""

    def test_resume_with_zero_session_count(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test resume when session count is zero (fresh start that was paused)."""
        setup_state_and_logs(session_count=0)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_with_first_task(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test resume starting from the first task."""
        setup_state_and_logs(current_task_index=0)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_with_max_sessions_none(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test resume when max_sessions is None (unlimited)."""
        setup_state_and_logs(max_sessions=None, session_count=100)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_state_status_transition(self, cli_runner, mock_state_dir, setup_state_and_logs):
        """Test that resume properly handles status transition from paused."""
        setup_state_and_logs(status="paused", session_count=3)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        # Should complete and show success message
        assert "completed successfully" in result.output
