"""Integration tests for CLI commands with mock credentials.

This module tests the full CLI workflow with mocked credentials and Agent SDK,
verifying that commands work end-to-end with proper authentication flow.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.core.state import StateManager

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def cli_runner():
    """Provide a Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def cli_integration_setup(
    integration_temp_dir: Path,
    integration_state_dir: Path,
    mock_credentials_file: Path,
    monkeypatch,
):
    """Set up CLI integration test environment.

    Provides:
    - Temporary working directory
    - Mock state directory
    - Mock credentials file
    - Patched StateManager and CredentialManager
    """
    from claude_task_master.core.credentials import CredentialManager

    # Change to temp directory
    monkeypatch.chdir(integration_temp_dir)

    # Patch StateManager to use integration state dir
    monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

    # Patch CredentialManager to use mock credentials
    monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

    return {
        "temp_dir": integration_temp_dir,
        "state_dir": integration_state_dir,
        "credentials_file": mock_credentials_file,
    }


# =============================================================================
# Start Command Integration Tests
# =============================================================================


class TestStartCommandIntegration:
    """Integration tests for the start command with credentials."""

    def test_start_loads_credentials_successfully(
        self, cli_runner, cli_integration_setup, mock_credentials_data
    ):
        """Test start command loads and validates credentials."""
        with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
            with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                # Configure planner to fail early (we just want to test credential loading)
                mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                result = cli_runner.invoke(app, ["start", "Test goal"])

        # Should have attempted to load credentials
        assert "Loading credentials" in result.output
        # Exit code 1 because planning fails (expected)
        assert result.exit_code == 1

    def test_start_with_expired_credentials(
        self, cli_runner, integration_temp_dir, integration_state_dir, monkeypatch
    ):
        """Test start command works with expired credentials (SDK handles refresh)."""
        from datetime import timedelta

        from claude_task_master.core.credentials import CredentialManager

        # Create expired credentials
        past_timestamp = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)
        expired_creds = {
            "claudeAiOauth": {
                "accessToken": "expired-token",
                "refreshToken": "refresh-token",
                "expiresAt": past_timestamp,
                "tokenType": "Bearer",
            }
        }

        # Create credentials file
        claude_dir = integration_temp_dir / ".claude"
        claude_dir.mkdir(exist_ok=True)
        creds_file = claude_dir / ".credentials.json"
        creds_file.write_text(json.dumps(expired_creds))

        # Patch paths
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", creds_file)

        # Token refresh is handled by Claude Agent SDK, not by us
        # We just load the token and let SDK handle expiration
        with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
            with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                # Configure planner to fail early (we just want to test credential loading)
                mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                result = cli_runner.invoke(app, ["start", "Test goal"])

        # Should not fail loading credentials, even if expired
        assert "Loading credentials" in result.output

    def test_start_with_missing_credentials_file(
        self, cli_runner, integration_temp_dir, integration_state_dir, monkeypatch
    ):
        """Test start command handles missing credentials file."""
        from claude_task_master.core.credentials import CredentialManager

        # Point to non-existent credentials file
        fake_creds = integration_temp_dir / "nonexistent" / ".credentials.json"

        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", fake_creds)

        result = cli_runner.invoke(app, ["start", "Test goal"])

        assert result.exit_code == 1
        # Should suggest running doctor or show credentials error
        assert "doctor" in result.output.lower() or "credentials" in result.output.lower()

    def test_start_full_workflow_with_mock_agent(self, cli_runner, cli_integration_setup, mock_sdk):
        """Test complete start workflow with mocked agent."""
        # Configure mock SDK responses
        mock_sdk.set_planning_response(
            """## Task List

- [ ] Task 1: Setup
- [ ] Task 2: Implementation

## Success Criteria

1. All tasks complete
"""
        )
        mock_sdk.set_work_response("Task 1 completed successfully")
        mock_sdk.set_work_response("Task 2 completed successfully")

        with patch("claude_task_master.cli_commands.workflow.AgentWrapper") as mock_agent_class:
            # Create mock agent instance
            mock_agent = MagicMock()
            mock_agent_class.return_value = mock_agent

            with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner_class:
                mock_planner = MagicMock()
                mock_planner_class.return_value = mock_planner

                # Mock planning result
                mock_planner.create_plan.return_value = {
                    "plan": mock_sdk._planning_responses[0],
                    "raw_output": "Planning complete",
                }

                with patch(
                    "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                ) as mock_orch_class:
                    mock_orch = MagicMock()
                    mock_orch_class.return_value = mock_orch
                    mock_orch.run.return_value = 0  # Success

                    result = cli_runner.invoke(app, ["start", "Test integration goal"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output


# =============================================================================
# Resume Command Integration Tests
# =============================================================================


class TestResumeCommandIntegration:
    """Integration tests for the resume command with credentials."""

    def test_resume_loads_credentials_successfully(
        self, cli_runner, cli_integration_setup, pre_planned_state
    ):
        """Test resume command loads credentials."""
        with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
            with patch("claude_task_master.cli_commands.workflow.Planner"):
                with patch(
                    "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                ) as mock_orch:
                    mock_orch.return_value.run.return_value = 0

                    result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "Loading credentials" in result.output

    def test_resume_with_expired_credentials(
        self,
        cli_runner,
        integration_temp_dir,
        integration_state_dir,
        pre_planned_state,
        monkeypatch,
    ):
        """Test resume works with expired credentials (SDK handles refresh)."""
        from datetime import timedelta

        from claude_task_master.core.credentials import CredentialManager

        # Create expired credentials
        past_timestamp = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)
        expired_creds = {
            "claudeAiOauth": {
                "accessToken": "expired-token",
                "refreshToken": "refresh-token",
                "expiresAt": past_timestamp,
                "tokenType": "Bearer",
            }
        }

        claude_dir = integration_temp_dir / ".claude"
        claude_dir.mkdir(exist_ok=True)
        creds_file = claude_dir / ".credentials.json"
        creds_file.write_text(json.dumps(expired_creds))

        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", creds_file)

        # Token refresh is handled by Claude Agent SDK, not by us
        # We just load the token and let SDK handle expiration
        with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
            with patch("claude_task_master.cli_commands.workflow.Planner"):
                with patch(
                    "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                ) as mock_orch:
                    mock_orch.return_value.run.return_value = 0

                    result = cli_runner.invoke(app, ["resume"])

        # Should not fail loading credentials, even if expired
        assert "Loading credentials" in result.output

    def test_resume_paused_state_with_credentials(
        self, cli_runner, cli_integration_setup, paused_state
    ):
        """Test resuming paused task with credentials."""
        with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
            with patch("claude_task_master.cli_commands.workflow.Planner"):
                with patch(
                    "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                ) as mock_orch:
                    mock_orch.return_value.run.return_value = 0

                    result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 0
        assert "paused" in result.output.lower()
        assert "Loading credentials" in result.output

    def test_resume_blocked_state_with_credentials(
        self, cli_runner, cli_integration_setup, blocked_state
    ):
        """Test resuming blocked task with credentials."""
        with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
            with patch("claude_task_master.cli_commands.workflow.Planner"):
                with patch(
                    "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                ) as mock_orch:
                    mock_orch.return_value.run.return_value = 2

                    result = cli_runner.invoke(app, ["resume"])

        assert result.exit_code == 2
        assert "Attempting to resume blocked task" in result.output


# =============================================================================
# Status Command Integration Tests
# =============================================================================


class TestStatusCommandIntegration:
    """Integration tests for the status command."""

    def test_status_with_active_state(self, cli_runner, cli_integration_setup, pre_planned_state):
        """Test status displays information correctly."""
        result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "Task Status" in result.output
        assert "Implement user authentication" in result.output
        assert "working" in result.output

    def test_status_no_active_task(self, cli_runner, cli_integration_setup):
        """Test status when no task exists."""
        result = cli_runner.invoke(app, ["status"])

        assert result.exit_code == 1
        assert "No active task found" in result.output


# =============================================================================
# Plan Command Integration Tests
# =============================================================================


class TestPlanCommandIntegration:
    """Integration tests for the plan command."""

    def test_plan_displays_content(self, cli_runner, cli_integration_setup, pre_planned_state):
        """Test plan displays plan content."""
        result = cli_runner.invoke(app, ["plan"])

        assert result.exit_code == 0
        assert "Task Plan" in result.output
        # Check for content from the plan (tasks about authentication)
        assert "authentication" in result.output.lower() or "initialize" in result.output.lower()

    def test_plan_no_active_task(self, cli_runner, cli_integration_setup):
        """Test plan when no task exists."""
        result = cli_runner.invoke(app, ["plan"])

        assert result.exit_code == 1
        assert "No active task found" in result.output


# =============================================================================
# Logs Command Integration Tests
# =============================================================================


class TestLogsCommandIntegration:
    """Integration tests for the logs command."""

    def test_logs_displays_content(self, cli_runner, cli_integration_setup, pre_planned_state):
        """Test logs displays log content."""
        # Create a log file
        run_id = pre_planned_state["run_id"]
        logs_dir = cli_integration_setup["state_dir"] / "logs"
        log_file = logs_dir / f"run-{run_id}.txt"
        log_file.write_text("\n".join([f"Log line {i}" for i in range(50)]))

        result = cli_runner.invoke(app, ["logs", "--tail", "10"])

        assert result.exit_code == 0
        assert "Log line 49" in result.output

    def test_logs_no_log_file(self, cli_runner, cli_integration_setup, pre_planned_state):
        """Test logs when log file doesn't exist."""
        result = cli_runner.invoke(app, ["logs"])

        assert result.exit_code == 1
        assert "No log file found" in result.output


# =============================================================================
# Context Command Integration Tests
# =============================================================================


class TestContextCommandIntegration:
    """Integration tests for the context command."""

    def test_context_displays_content(self, cli_runner, cli_integration_setup, paused_state):
        """Test context displays accumulated context."""
        result = cli_runner.invoke(app, ["context"])

        assert result.exit_code == 0
        assert "Accumulated Context" in result.output
        assert "Session 1" in result.output

    def test_context_no_context_yet(self, cli_runner, cli_integration_setup, pre_planned_state):
        """Test context when no context accumulated."""
        result = cli_runner.invoke(app, ["context"])

        assert result.exit_code == 0
        assert "No context accumulated yet" in result.output


# =============================================================================
# Progress Command Integration Tests
# =============================================================================


class TestProgressCommandIntegration:
    """Integration tests for the progress command."""

    def test_progress_displays_content(self, cli_runner, cli_integration_setup, paused_state):
        """Test progress displays progress summary."""
        result = cli_runner.invoke(app, ["progress"])

        assert result.exit_code == 0
        assert "Progress" in result.output
        assert "Session" in result.output

    def test_progress_no_progress_yet(self, cli_runner, cli_integration_setup, pre_planned_state):
        """Test progress when no progress recorded."""
        result = cli_runner.invoke(app, ["progress"])

        assert result.exit_code == 0
        assert "No progress recorded yet" in result.output


# =============================================================================
# Clean Command Integration Tests
# =============================================================================


class TestCleanCommandIntegration:
    """Integration tests for the clean command."""

    def test_clean_with_force(self, cli_runner, cli_integration_setup, pre_planned_state):
        """Test clean removes state directory."""
        state_dir = cli_integration_setup["state_dir"]
        assert state_dir.exists()

        result = cli_runner.invoke(app, ["clean", "--force"])

        assert result.exit_code == 0
        assert "cleaned" in result.output
        assert not state_dir.exists()

    def test_clean_with_confirmation(self, cli_runner, cli_integration_setup, pre_planned_state):
        """Test clean with user confirmation."""
        state_dir = cli_integration_setup["state_dir"]

        result = cli_runner.invoke(app, ["clean"], input="y\n")

        assert result.exit_code == 0
        assert not state_dir.exists()

    def test_clean_cancelled(self, cli_runner, cli_integration_setup, pre_planned_state):
        """Test clean when user cancels."""
        state_dir = cli_integration_setup["state_dir"]

        result = cli_runner.invoke(app, ["clean"], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.output
        assert state_dir.exists()


# =============================================================================
# Doctor Command Integration Tests
# =============================================================================


class TestDoctorCommandIntegration:
    """Integration tests for the doctor command."""

    def test_doctor_with_valid_credentials(self, cli_runner, cli_integration_setup):
        """Test doctor validates credentials."""
        with patch("claude_task_master.utils.doctor.SystemDoctor.run_checks") as mock_checks:
            mock_checks.return_value = True

            result = cli_runner.invoke(app, ["doctor"])

        assert result.exit_code == 0

    def test_doctor_with_failed_checks(self, cli_runner, cli_integration_setup):
        """Test doctor when checks fail."""
        with patch("claude_task_master.utils.doctor.SystemDoctor.run_checks") as mock_checks:
            mock_checks.return_value = False

            result = cli_runner.invoke(app, ["doctor"])

        assert result.exit_code == 1


# =============================================================================
# Multi-Command Workflow Tests
# =============================================================================


class TestMultiCommandWorkflow:
    """Integration tests for multiple CLI commands in sequence."""

    def test_start_status_plan_clean_workflow(self, cli_runner, cli_integration_setup, mock_sdk):
        """Test complete workflow: start -> status -> plan -> clean."""
        # Configure mock SDK
        plan_content = """## Task List

- [ ] Task 1

## Success Criteria

1. Done
"""
        mock_sdk.set_planning_response(plan_content)

        # Step 1: Start
        with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
            with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                # Create real planner to actually save plan file
                def create_plan_side_effect(goal):
                    state_manager = StateManager()
                    state_manager.save_plan(plan_content)
                    return {
                        "plan": plan_content,
                        "raw_output": "Planning complete",
                    }

                mock_planner.return_value.create_plan.side_effect = create_plan_side_effect

                with patch(
                    "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                ) as mock_orch:
                    mock_orch.return_value.run.return_value = 2  # Paused

                    start_result = cli_runner.invoke(app, ["start", "Test workflow"])

        assert start_result.exit_code == 2

        # Step 2: Status
        status_result = cli_runner.invoke(app, ["status"])
        assert status_result.exit_code == 0
        assert "Test workflow" in status_result.output

        # Step 3: Plan
        plan_result = cli_runner.invoke(app, ["plan"])
        assert plan_result.exit_code == 0
        # Just check that plan is displayed
        assert "Task Plan" in plan_result.output

        # Step 4: Clean
        clean_result = cli_runner.invoke(app, ["clean", "-f"])
        assert clean_result.exit_code == 0

        # Step 5: Verify cleaned
        status_after_clean = cli_runner.invoke(app, ["status"])
        assert status_after_clean.exit_code == 1

    def test_resume_after_pause_workflow(self, cli_runner, cli_integration_setup, paused_state):
        """Test resume workflow after pause."""
        # Step 1: Check status
        status_result = cli_runner.invoke(app, ["status"])
        assert status_result.exit_code == 0
        assert "paused" in status_result.output

        # Step 2: Resume
        with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
            with patch("claude_task_master.cli_commands.workflow.Planner"):
                with patch(
                    "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                ) as mock_orch:
                    mock_orch.return_value.run.return_value = 0

                    resume_result = cli_runner.invoke(app, ["resume"])

        assert resume_result.exit_code == 0
        assert "completed successfully" in resume_result.output


# =============================================================================
# Credential Validation Tests
# =============================================================================


class TestCredentialValidation:
    """Tests for credential validation in CLI commands."""

    def test_valid_token_structure(self, cli_runner, cli_integration_setup):
        """Test that valid token structure is accepted."""
        # Verify credentials file has correct structure
        creds_file = cli_integration_setup["credentials_file"]
        creds_data = json.loads(creds_file.read_text())

        assert "claudeAiOauth" in creds_data
        assert "accessToken" in creds_data["claudeAiOauth"]
        assert "expiresAt" in creds_data["claudeAiOauth"]

        # Start command should accept these credentials
        with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
            with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                result = cli_runner.invoke(app, ["start", "Test"])

        # Should fail at planning, not credentials
        assert "Loading credentials" in result.output

    def test_malformed_credentials_file(
        self, cli_runner, integration_temp_dir, integration_state_dir, monkeypatch
    ):
        """Test handling of malformed credentials file."""
        from claude_task_master.core.credentials import CredentialManager

        # Create malformed credentials file
        claude_dir = integration_temp_dir / ".claude"
        claude_dir.mkdir(exist_ok=True)
        creds_file = claude_dir / ".credentials.json"
        creds_file.write_text("invalid json{")

        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", creds_file)

        result = cli_runner.invoke(app, ["start", "Test"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_missing_oauth_field(
        self, cli_runner, integration_temp_dir, integration_state_dir, monkeypatch
    ):
        """Test handling of credentials missing claudeAiOauth field."""
        from claude_task_master.core.credentials import CredentialManager

        # Create credentials without claudeAiOauth
        claude_dir = integration_temp_dir / ".claude"
        claude_dir.mkdir(exist_ok=True)
        creds_file = claude_dir / ".credentials.json"
        creds_file.write_text(json.dumps({"someOtherField": "value"}))

        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", creds_file)

        result = cli_runner.invoke(app, ["start", "Test"])

        assert result.exit_code == 1
        assert "Error" in result.output


# =============================================================================
# Error Recovery Tests
# =============================================================================


class TestErrorRecovery:
    """Tests for error recovery in CLI commands."""

    def test_resume_after_credential_fix(
        self,
        cli_runner,
        integration_temp_dir,
        integration_state_dir,
        pre_planned_state,
        monkeypatch,
    ):
        """Test resuming after fixing missing credentials."""
        from datetime import timedelta

        from claude_task_master.core.credentials import CredentialManager

        # Initially use missing credentials
        claude_dir = integration_temp_dir / ".claude"
        claude_dir.mkdir(exist_ok=True)
        creds_file = claude_dir / ".credentials.json"

        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", creds_file)

        # First attempt should fail (missing credentials file)
        result1 = cli_runner.invoke(app, ["resume"])
        assert result1.exit_code == 1
        assert "Credentials not found" in result1.output or "Error" in result1.output

        # Fix credentials by creating the file
        future_timestamp = int((datetime.now() + timedelta(hours=1)).timestamp() * 1000)
        valid_creds = {
            "claudeAiOauth": {
                "accessToken": "valid-token",
                "refreshToken": "refresh",
                "expiresAt": future_timestamp,
                "tokenType": "Bearer",
            }
        }
        creds_file.write_text(json.dumps(valid_creds))

        # Second attempt should succeed
        with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
            with patch("claude_task_master.cli_commands.workflow.Planner"):
                with patch(
                    "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                ) as mock_orch:
                    mock_orch.return_value.run.return_value = 0

                    result2 = cli_runner.invoke(app, ["resume"])

        assert result2.exit_code == 0
