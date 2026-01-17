"""Tests for resume command error handling."""

from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager


class TestResumeCredentialErrors:
    """Tests for resume command credential error handling."""

    def test_resume_credential_error(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_goal_file,
        mock_plan_file,
    ):
        """Test resume handles credential errors."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.side_effect = FileNotFoundError(
                    "Credentials not found"
                )

                result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "Credentials not found" in result.output
        assert "doctor" in result.output


class TestResumeGenericErrors:
    """Tests for resume command generic exception handling."""

    def test_resume_generic_exception(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_goal_file,
        mock_plan_file,
    ):
        """Test resume handles generic exceptions."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        mock_orch.return_value.run.side_effect = RuntimeError("Unexpected error")

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "Unexpected error" in result.output


class TestResumeOrchestratorReturnCodes:
    """Tests for resume command orchestrator return code handling."""

    def test_resume_orchestrator_pauses_again(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_goal_file,
        mock_plan_file,
    ):
        """Test resume when orchestrator returns paused status."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        mock_orch.return_value.run.return_value = 2

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 2
        assert "paused" in result.output
        assert "resume" in result.output

    def test_resume_orchestrator_blocks(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_goal_file,
        mock_plan_file,
    ):
        """Test resume when orchestrator returns blocked status."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        mock_orch.return_value.run.return_value = 1

                        result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "blocked" in result.output or "failed" in result.output

    def test_resume_orchestrator_unexpected_return_code(
        self,
        cli_runner,
        temp_dir,
        mock_state_dir,
        mock_state_file,
        mock_goal_file,
        mock_plan_file,
    ):
        """Test resume handles unexpected orchestrator return codes."""
        # Create logs directory
        logs_dir = mock_state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            with patch("claude_task_master.cli_commands.workflow.CredentialManager") as mock_cred:
                mock_cred.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch(
                        "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                    ) as mock_orch:
                        # Return code 3 or higher
                        mock_orch.return_value.run.return_value = 3

                        result = cli_runner.invoke(app, ["resume"])

        # Any non-0 and non-2 should be treated as blocked/failed
        assert result.exit_code == 3
        assert "blocked" in result.output.lower() or "failed" in result.output.lower()
