"""Tests for resume command workflow continuation.

This module tests that the workflow continues correctly after resume operations,
including:
- Task progression after resume
- Multiple resume cycles
- Session limits during resume
- Multi-task workflow scenarios
- Workflow completion from various states
"""

import json
from datetime import datetime

import pytest

from claude_task_master.cli import app

from .conftest import mock_resume_context


def create_workflow_state(
    mock_state_dir,
    status="paused",
    current_task_index=0,
    session_count=1,
    current_pr=None,
    max_sessions=None,
    model="sonnet",
):
    """Create a state file for workflow testing."""
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": status,
        "current_task_index": current_task_index,
        "session_count": session_count,
        "current_pr": current_pr,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "20250115-120000",
        "model": model,
        "options": {
            "auto_merge": True,
            "max_sessions": max_sessions,
            "pause_on_pr": False,
        },
    }
    state_file = mock_state_dir / "state.json"
    state_file.write_text(json.dumps(state_data))
    return state_data


@pytest.fixture
def setup_workflow_state(mock_state_dir, mock_goal_file, mock_plan_file):
    """Fixture to set up workflow state with logs directory."""

    def _setup(**kwargs):
        state_data = create_workflow_state(mock_state_dir, **kwargs)
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return state_data

    return _setup


class TestResumeTaskProgression:
    """Tests for task progression during resume workflow."""

    def test_resume_continues_from_current_task(
        self, cli_runner, mock_state_dir, setup_workflow_state
    ):
        """Test that resume continues from the current task index."""
        setup_workflow_state(current_task_index=1, session_count=2)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Current Task:" in result.output
        assert "completed successfully" in result.output

    def test_resume_from_first_task(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test resume starting from the first task (index 0)."""
        setup_workflow_state(current_task_index=0, session_count=1)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output

    def test_resume_from_middle_task(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test resume starting from a middle task."""
        setup_workflow_state(current_task_index=1, session_count=3)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_from_last_task(self, cli_runner, mock_state_dir, mock_goal_file):
        """Test resume when already at the last task."""
        # Create a plan with exactly 2 tasks
        plan_file = mock_state_dir / "plan.md"
        plan_file.write_text("""## Task List

- [x] Task 1: Completed
- [ ] Task 2: Final task

## Success Criteria
1. All done
""")
        # Resume from last task (index 1)
        create_workflow_state(mock_state_dir, current_task_index=1, session_count=4)
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0


class TestResumeMultipleCycles:
    """Tests for multiple resume cycles."""

    def test_resume_increments_session_count(
        self, cli_runner, mock_state_dir, setup_workflow_state
    ):
        """Test that each resume is reflected in displayed session count."""
        initial_session = 5
        setup_workflow_state(session_count=initial_session, current_task_index=1)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert str(initial_session) in result.output

    def test_resume_multiple_times_pausing(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test multiple resume cycles that each pause."""
        # First resume
        setup_workflow_state(session_count=1, current_task_index=0)
        with mock_resume_context(mock_state_dir, return_code=2):
            result1 = cli_runner.invoke(app, ["resume"])
        assert result1.exit_code == 2
        assert "paused" in result1.output

        # Second resume
        setup_workflow_state(session_count=2, current_task_index=0)
        with mock_resume_context(mock_state_dir, return_code=2):
            result2 = cli_runner.invoke(app, ["resume"])
        assert result2.exit_code == 2

        # Third resume - completes
        setup_workflow_state(session_count=3, current_task_index=1)
        with mock_resume_context(mock_state_dir, return_code=0):
            result3 = cli_runner.invoke(app, ["resume"])
        assert result3.exit_code == 0
        assert "completed successfully" in result3.output

    def test_resume_cycle_pause_then_complete(
        self, cli_runner, mock_state_dir, setup_workflow_state
    ):
        """Test resume cycle: paused -> resume -> complete."""
        # Start paused
        setup_workflow_state(status="paused", session_count=2)

        # Resume and complete
        with mock_resume_context(mock_state_dir, return_code=0):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output

    def test_resume_cycle_blocked_then_complete(
        self, cli_runner, mock_state_dir, setup_workflow_state
    ):
        """Test resume cycle: blocked -> resume -> complete."""
        setup_workflow_state(status="blocked", session_count=3, current_task_index=1)

        with mock_resume_context(mock_state_dir, return_code=0):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Attempting to resume blocked task" in result.output


class TestResumeSessionLimits:
    """Tests for session limits during resume workflow."""

    def test_resume_with_max_sessions(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test resume respects max_sessions setting."""
        setup_workflow_state(session_count=5, max_sessions=10, current_task_index=1)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_near_max_sessions(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test resume when near the max_sessions limit."""
        setup_workflow_state(session_count=9, max_sessions=10, current_task_index=1)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "9" in result.output  # Session count shown

    def test_resume_unlimited_sessions(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test resume with unlimited sessions (max_sessions=None)."""
        setup_workflow_state(session_count=100, max_sessions=None, current_task_index=1)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "100" in result.output

    def test_resume_high_max_sessions(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test resume with high max_sessions value."""
        setup_workflow_state(session_count=50, max_sessions=200, current_task_index=1)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0


class TestResumeWorkflowCompletion:
    """Tests for workflow completion scenarios during resume."""

    def test_resume_completes_workflow(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test resume that completes the entire workflow."""
        setup_workflow_state(current_task_index=2, session_count=5)

        with mock_resume_context(mock_state_dir, return_code=0):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output

    def test_resume_workflow_pauses_midway(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test resume workflow that pauses midway."""
        setup_workflow_state(current_task_index=1, session_count=2)

        with mock_resume_context(mock_state_dir, return_code=2):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 2
        assert "paused" in result.output
        assert "resume" in result.output

    def test_resume_workflow_blocks(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test resume workflow that becomes blocked."""
        setup_workflow_state(current_task_index=1, session_count=3)

        with mock_resume_context(mock_state_dir, return_code=1):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "blocked" in result.output or "failed" in result.output


class TestResumeMultiTaskWorkflow:
    """Tests for multi-task workflow scenarios."""

    def test_resume_with_some_tasks_completed(self, cli_runner, mock_state_dir, mock_goal_file):
        """Test resume when some tasks are already completed."""
        # Create plan with mixed completed/incomplete tasks
        plan_file = mock_state_dir / "plan.md"
        plan_file.write_text("""## Task List

- [x] Task 1: Setup project
- [x] Task 2: Implement feature
- [ ] Task 3: Add tests
- [ ] Task 4: Documentation

## Success Criteria
1. All tests pass
""")
        create_workflow_state(
            mock_state_dir,
            current_task_index=2,
            session_count=4,  # Starting at task 3
        )
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_with_all_but_one_completed(self, cli_runner, mock_state_dir, mock_goal_file):
        """Test resume when all but one task is completed."""
        plan_file = mock_state_dir / "plan.md"
        plan_file.write_text("""## Task List

- [x] Task 1: Done
- [x] Task 2: Done
- [ ] Task 3: Final one

## Success Criteria
1. Complete
""")
        create_workflow_state(
            mock_state_dir,
            current_task_index=2,
            session_count=5,  # Last task
        )
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_single_task_workflow(self, cli_runner, mock_state_dir, mock_goal_file):
        """Test resume with a single-task workflow."""
        plan_file = mock_state_dir / "plan.md"
        plan_file.write_text("""## Task List

- [ ] Task 1: Only task

## Success Criteria
1. Done
""")
        create_workflow_state(mock_state_dir, current_task_index=0, session_count=1)
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_many_tasks_workflow(self, cli_runner, mock_state_dir, mock_goal_file):
        """Test resume with many tasks in the workflow."""
        # Create plan with 10 tasks
        tasks = "\n".join([f"- [ ] Task {i}: Step {i}" for i in range(1, 11)])
        plan_file = mock_state_dir / "plan.md"
        plan_file.write_text(f"""## Task List

{tasks}

## Success Criteria
1. All steps complete
""")
        create_workflow_state(
            mock_state_dir,
            current_task_index=5,
            session_count=10,  # Middle of workflow
        )
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0


class TestResumeWorkflowWithDifferentModels:
    """Tests for workflow continuation with different models."""

    def test_resume_workflow_with_opus(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test workflow continuation with opus model."""
        setup_workflow_state(model="opus", current_task_index=1, session_count=2)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_workflow_with_haiku(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test workflow continuation with haiku model."""
        setup_workflow_state(model="haiku", current_task_index=0, session_count=1)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_workflow_with_sonnet(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test workflow continuation with sonnet model (default)."""
        setup_workflow_state(model="sonnet", current_task_index=1, session_count=3)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0


class TestResumeWorkflowOutput:
    """Tests for workflow output during resume."""

    def test_resume_shows_resuming_message(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test that resume shows the resuming message."""
        setup_workflow_state(current_task_index=1, session_count=2)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Resuming task" in result.output
        assert "Resuming Execution" in result.output

    def test_resume_shows_loading_credentials(
        self, cli_runner, mock_state_dir, setup_workflow_state
    ):
        """Test that resume shows loading credentials message."""
        setup_workflow_state(current_task_index=0, session_count=1)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Loading credentials" in result.output

    def test_resume_shows_goal(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test that resume displays the goal."""
        setup_workflow_state(current_task_index=1, session_count=3)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Goal:" in result.output

    def test_resume_shows_status(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test that resume displays the status."""
        setup_workflow_state(status="paused", current_task_index=1, session_count=2)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Status:" in result.output

    def test_resume_shows_session_count(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test that resume displays the session count."""
        setup_workflow_state(current_task_index=1, session_count=7)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Session Count:" in result.output
        assert "7" in result.output

    def test_resume_shows_current_task_info(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test that resume displays current task information."""
        setup_workflow_state(current_task_index=2, session_count=4)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Current Task:" in result.output


class TestResumeWorkflowEdgeCases:
    """Edge cases for workflow continuation."""

    def test_resume_after_long_pause(
        self, cli_runner, mock_state_dir, mock_goal_file, mock_plan_file
    ):
        """Test resume after a workflow was paused for a long time."""
        # Create state with old timestamp
        old_timestamp = "2025-01-01T00:00:00"
        state_data = {
            "status": "paused",
            "current_task_index": 1,
            "session_count": 2,
            "current_pr": None,
            "created_at": old_timestamp,
            "updated_at": old_timestamp,
            "run_id": "20250101-000000",
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": None,
                "pause_on_pr": False,
            },
        }
        state_file = mock_state_dir / "state.json"
        state_file.write_text(json.dumps(state_data))
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_workflow_zero_session(self, cli_runner, mock_state_dir, setup_workflow_state):
        """Test resume when session count is zero (edge case)."""
        setup_workflow_state(session_count=0, current_task_index=0)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0

    def test_resume_workflow_very_high_session(
        self, cli_runner, mock_state_dir, setup_workflow_state
    ):
        """Test resume with very high session count."""
        setup_workflow_state(session_count=9999, current_task_index=1)

        with mock_resume_context(mock_state_dir):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "9999" in result.output

    def test_resume_workflow_from_task_zero_to_completion(
        self, cli_runner, mock_state_dir, setup_workflow_state
    ):
        """Test resume from task 0 all the way to completion."""
        setup_workflow_state(current_task_index=0, session_count=1)

        with mock_resume_context(mock_state_dir, return_code=0):
            result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output
