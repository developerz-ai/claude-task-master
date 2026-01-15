"""Tests to verify conftest fixtures work correctly."""

import pytest
from pathlib import Path


class TestDirectoryFixtures:
    """Tests for directory fixtures."""

    def test_temp_dir_exists(self, temp_dir):
        """Test temp_dir fixture provides existing directory."""
        assert temp_dir.exists()
        assert temp_dir.is_dir()

    def test_state_dir_exists(self, state_dir):
        """Test state_dir fixture provides existing directory."""
        assert state_dir.exists()
        assert state_dir.is_dir()
        assert state_dir.name == ".claude-task-master"

    def test_logs_dir_exists(self, logs_dir):
        """Test logs_dir fixture provides existing directory."""
        assert logs_dir.exists()
        assert logs_dir.is_dir()
        assert logs_dir.name == "logs"


class TestCredentialsFixtures:
    """Tests for credentials fixtures."""

    def test_mock_credentials_data_structure(self, mock_credentials_data):
        """Test mock credentials data has expected structure."""
        assert "claudeAiOauth" in mock_credentials_data
        oauth = mock_credentials_data["claudeAiOauth"]
        assert "accessToken" in oauth
        assert "refreshToken" in oauth
        assert "expiresAt" in oauth
        assert "tokenType" in oauth

    def test_mock_credentials_file_exists(self, mock_credentials_file):
        """Test mock credentials file is created."""
        assert mock_credentials_file.exists()
        assert mock_credentials_file.is_file()

    def test_mock_expired_credentials_data_is_expired(self, mock_expired_credentials_data):
        """Test expired credentials have past timestamp."""
        from datetime import datetime

        expires_at = mock_expired_credentials_data["claudeAiOauth"]["expiresAt"]
        expires_datetime = datetime.fromtimestamp(expires_at / 1000)
        assert expires_datetime < datetime.now()


class TestStateFixtures:
    """Tests for state fixtures."""

    def test_sample_task_options(self, sample_task_options):
        """Test sample task options fixture."""
        assert "auto_merge" in sample_task_options
        assert "max_sessions" in sample_task_options
        assert "pause_on_pr" in sample_task_options

    def test_sample_task_state(self, sample_task_state):
        """Test sample task state fixture."""
        assert "status" in sample_task_state
        assert "current_task_index" in sample_task_state
        assert "run_id" in sample_task_state
        assert "model" in sample_task_state
        assert "options" in sample_task_state

    def test_sample_goal(self, sample_goal):
        """Test sample goal fixture."""
        assert isinstance(sample_goal, str)
        assert len(sample_goal) > 0

    def test_sample_plan_has_tasks(self, sample_plan):
        """Test sample plan contains checkbox tasks."""
        assert "- [ ]" in sample_plan or "- [x]" in sample_plan
        assert "## Task List" in sample_plan
        assert "## Success Criteria" in sample_plan


class TestStateManagerFixtures:
    """Tests for state manager fixtures."""

    def test_state_manager_fixture(self, state_manager):
        """Test state manager fixture is created."""
        from claude_task_master.core.state import StateManager

        assert isinstance(state_manager, StateManager)

    def test_initialized_state_manager(self, initialized_state_manager):
        """Test initialized state manager has state."""
        state = initialized_state_manager.load_state()
        assert state is not None
        assert state.status == "planning"

    def test_initialized_state_manager_has_goal(self, initialized_state_manager):
        """Test initialized state manager has goal."""
        goal = initialized_state_manager.load_goal()
        assert goal is not None
        assert len(goal) > 0


class TestAgentFixtures:
    """Tests for agent fixtures."""

    def test_mock_agent_wrapper_has_methods(self, mock_agent_wrapper):
        """Test mock agent wrapper has required methods."""
        assert hasattr(mock_agent_wrapper, "run_planning_phase")
        assert hasattr(mock_agent_wrapper, "run_work_session")
        assert hasattr(mock_agent_wrapper, "verify_success_criteria")
        assert hasattr(mock_agent_wrapper, "get_tools_for_phase")

    def test_mock_agent_wrapper_returns_expected(self, mock_agent_wrapper):
        """Test mock agent wrapper returns expected values."""
        result = mock_agent_wrapper.run_planning_phase("test goal")
        assert "plan" in result
        assert "criteria" in result
        assert "raw_output" in result


class TestPlannerFixtures:
    """Tests for planner fixtures."""

    def test_planner_fixture(self, planner):
        """Test planner fixture is created."""
        from claude_task_master.core.planner import Planner

        assert isinstance(planner, Planner)


class TestOrchestratorFixtures:
    """Tests for orchestrator fixtures."""

    def test_orchestrator_fixture(self, orchestrator):
        """Test orchestrator fixture is created."""
        from claude_task_master.core.orchestrator import WorkLoopOrchestrator

        assert isinstance(orchestrator, WorkLoopOrchestrator)


class TestLoggerFixtures:
    """Tests for logger fixtures."""

    def test_log_file_path(self, log_file):
        """Test log file path fixture."""
        assert log_file.suffix == ".txt"
        assert "run-test" in log_file.name

    def test_task_logger_fixture(self, task_logger):
        """Test task logger fixture is created."""
        from claude_task_master.core.logger import TaskLogger

        assert isinstance(task_logger, TaskLogger)

    def test_task_logger_can_write(self, task_logger):
        """Test task logger can write to log file."""
        task_logger.start_session(1, "test")
        assert task_logger.log_file.exists()


class TestContextAccumulatorFixtures:
    """Tests for context accumulator fixtures."""

    def test_context_accumulator_fixture(self, context_accumulator):
        """Test context accumulator fixture is created."""
        from claude_task_master.core.context_accumulator import ContextAccumulator

        assert isinstance(context_accumulator, ContextAccumulator)


class TestGitHubFixtures:
    """Tests for GitHub fixtures."""

    def test_mock_github_client_has_methods(self, mock_github_client):
        """Test mock GitHub client has required methods."""
        assert hasattr(mock_github_client, "create_pr")
        assert hasattr(mock_github_client, "get_pr_status")
        assert hasattr(mock_github_client, "get_pr_comments")
        assert hasattr(mock_github_client, "merge_pr")

    def test_sample_pr_graphql_response_structure(self, sample_pr_graphql_response):
        """Test sample PR GraphQL response has expected structure."""
        assert "data" in sample_pr_graphql_response
        assert "repository" in sample_pr_graphql_response["data"]
        assert "pullRequest" in sample_pr_graphql_response["data"]["repository"]


class TestCLIFixtures:
    """Tests for CLI fixtures."""

    def test_cli_runner_fixture(self, cli_runner):
        """Test CLI runner fixture is created."""
        from typer.testing import CliRunner

        assert isinstance(cli_runner, CliRunner)

    def test_cli_app_fixture(self, cli_app):
        """Test CLI app fixture is created."""
        from typer import Typer

        assert isinstance(cli_app, Typer)


class TestIsolatedFilesystem:
    """Tests for isolated filesystem fixture."""

    def test_isolated_filesystem(self, isolated_filesystem):
        """Test isolated filesystem fixture changes cwd."""
        import os

        assert Path(os.getcwd()) == isolated_filesystem


class TestMultipleLogFiles:
    """Tests for multiple log files fixture."""

    def test_multiple_log_files_count(self, multiple_log_files):
        """Test multiple log files fixture creates 15 files."""
        assert len(multiple_log_files) == 15

    def test_multiple_log_files_exist(self, multiple_log_files):
        """Test all log files exist."""
        for log_file in multiple_log_files:
            assert log_file.exists()
            assert log_file.is_file()
