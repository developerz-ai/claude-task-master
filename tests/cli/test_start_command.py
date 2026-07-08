"""Tests for the start CLI command."""

from unittest.mock import patch

from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.cli_commands.workflow import auto_merge_notice
from claude_task_master.core.state import StateManager

# =============================================================================
# Start Command Tests
# =============================================================================


class TestStartCommand:
    """Tests for the start command."""

    def test_start_with_existing_task(
        self, cli_runner: CliRunner, temp_dir, mock_state_dir, mock_state_file
    ):
        """Test start fails when task already exists."""
        with patch.object(StateManager, "STATE_DIR", mock_state_dir):
            result = cli_runner.invoke(app, ["start", "New goal"])

        assert result.exit_code == 1
        assert "Task already exists" in result.output
        assert "resume" in result.output or "clean" in result.output

    def test_start_shows_goal(self, cli_runner: CliRunner, temp_dir):
        """Test start shows the goal."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            # Mock the credential manager to avoid actual credential loading
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                # Mock the agent to avoid actual agent initialization
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(app, ["start", "My test goal"])

        # Should print the goal (even though it fails later)
        assert "My test goal" in result.output

    def test_auto_merge_notice_helper(self):
        """auto_merge_notice returns the full warning when on, None when off."""
        on = auto_merge_notice(True)
        assert on is not None
        assert "auto-merge is ON" in on
        # The core surprise: merges run via gh, outside the tool boundary, bypassing git-guard.
        assert "gh" in on
        assert "git-guard" in on
        # Both the per-run flag and the persistent disable are offered.
        assert "--no-auto-merge" in on
        assert "config-update --no-auto-merge" in on
        assert auto_merge_notice(False) is None

    def test_start_shows_auto_merge_banner_by_default(self, cli_runner: CliRunner, temp_dir):
        """start prints the auto-merge banner when auto-merge is on (the default)."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(app, ["start", "Test goal"])

        assert "auto-merge is ON" in result.output

    def test_start_no_auto_merge_suppresses_banner(self, cli_runner: CliRunner, temp_dir):
        """--no-auto-merge suppresses the auto-merge banner."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(app, ["start", "Test goal", "--no-auto-merge"])

        assert "auto-merge is ON" not in result.output

    def test_start_admin_persists_option(self, cli_runner: CliRunner, temp_dir):
        """--admin persists admin_merge=True in the initialized state."""
        state_dir = temp_dir / ".claude-task-master"
        with patch.object(StateManager, "STATE_DIR", state_dir):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        cli_runner.invoke(app, ["start", "Test goal", "--admin"])

            # State is initialized (with options) before planning runs, so it persists.
            state = StateManager().load_state()
        assert state.options.admin_merge is True

    def test_start_admin_default_off(self, cli_runner: CliRunner, temp_dir):
        """Without --admin, admin_merge defaults to False."""
        state_dir = temp_dir / ".claude-task-master"
        with patch.object(StateManager, "STATE_DIR", state_dir):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        cli_runner.invoke(app, ["start", "Test goal"])

            state = StateManager().load_state()
        assert state.options.admin_merge is False

    def test_start_admin_warns_when_auto_merge_disabled(self, cli_runner: CliRunner, temp_dir):
        """--admin with --no-auto-merge warns that --admin has no effect."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(
                            app, ["start", "Test goal", "--admin", "--no-auto-merge"]
                        )

        assert "no effect" in result.output

    def test_start_default_model(self, cli_runner: CliRunner, temp_dir):
        """Test start uses default model."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(app, ["start", "Test goal"])

        # Should show default model (opus is the default)
        assert "opus" in result.output

    def test_start_with_custom_model(self, cli_runner: CliRunner, temp_dir):
        """Test start with custom model option."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(app, ["start", "Test goal", "--model", "opus"])

        assert "opus" in result.output

    def test_start_credential_error(self, cli_runner: CliRunner, temp_dir):
        """Test start handles credential errors."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.side_effect = FileNotFoundError(
                    "Credentials not found"
                )

                result = cli_runner.invoke(app, ["start", "Test goal"])

        assert result.exit_code == 1
        assert "Credentials not found" in result.output
        assert "doctor" in result.output

    def test_start_with_auto_merge_false(self, cli_runner: CliRunner, temp_dir):
        """Test start with --no-auto-merge option."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(
                            app,
                            ["start", "Test goal", "--no-auto-merge"],
                        )

        assert "Auto-merge: False" in result.output

    def test_start_with_max_sessions(self, cli_runner: CliRunner, temp_dir):
        """Test start with --max-sessions option."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(
                            app,
                            ["start", "Test goal", "--max-sessions", "5"],
                        )

        # Should start without error related to max-sessions
        assert result.exit_code == 1  # Still fails at planning, but accepted option

    def test_start_with_max_prs(self, cli_runner: CliRunner, temp_dir):
        """Test start with --prs option."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(
                            app,
                            ["start", "Test goal", "--prs", "2"],
                        )

        # Should start without error related to --prs
        assert result.exit_code == 1  # Still fails at planning, but accepted option

    def test_start_with_pause_on_pr(self, cli_runner: CliRunner, temp_dir):
        """Test start with --pause-on-pr option."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception("Test stop")

                        result = cli_runner.invoke(
                            app,
                            ["start", "Test goal", "--pause-on-pr"],
                        )

        # Should start without error related to pause-on-pr
        assert result.exit_code == 1  # Still fails at planning, but accepted option


# =============================================================================
# Start Command Full Workflow Tests
# =============================================================================


class TestStartCommandWorkflow:
    """Tests for start command workflow."""

    def test_start_successful_planning(self, cli_runner: CliRunner, temp_dir):
        """Test start with successful planning phase."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.return_value = {
                            "plan": "## Tasks\n- [ ] Task 1",
                            "raw_output": "Planning output",
                        }
                        with patch(
                            "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                        ) as mock_orchestrator:
                            mock_orchestrator.return_value.run.return_value = 0

                            result = cli_runner.invoke(app, ["start", "Complete the task"])

        assert result.exit_code == 0
        assert "completed successfully" in result.output

    def test_start_orchestrator_paused(self, cli_runner: CliRunner, temp_dir):
        """Test start when orchestrator returns paused status."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.return_value = {
                            "plan": "## Tasks\n- [ ] Task 1",
                            "raw_output": "Planning output",
                        }
                        with patch(
                            "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                        ) as mock_orchestrator:
                            mock_orchestrator.return_value.run.return_value = 2

                            result = cli_runner.invoke(app, ["start", "Complete the task"])

        assert result.exit_code == 2
        assert "paused" in result.output
        assert "resume" in result.output

    def test_start_orchestrator_blocked(self, cli_runner: CliRunner, temp_dir):
        """Test start when orchestrator returns blocked status."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.return_value = {
                            "plan": "## Tasks\n- [ ] Task 1",
                            "raw_output": "Planning output",
                        }
                        with patch(
                            "claude_task_master.cli_commands.workflow.WorkLoopOrchestrator"
                        ) as mock_orchestrator:
                            mock_orchestrator.return_value.run.return_value = 1

                            result = cli_runner.invoke(app, ["start", "Complete the task"])

        assert result.exit_code == 1
        assert "blocked" in result.output or "failed" in result.output

    def test_start_planning_phase_failure(self, cli_runner: CliRunner, temp_dir):
        """Test start when planning phase fails."""
        with patch.object(StateManager, "STATE_DIR", temp_dir / ".claude-task-master"):
            with patch(
                "claude_task_master.cli_commands.workflow.CredentialManager"
            ) as mock_cred_manager:
                mock_cred_manager.return_value.get_valid_token.return_value = "test-token"
                with patch("claude_task_master.cli_commands.workflow.AgentWrapper"):
                    with patch("claude_task_master.cli_commands.workflow.Planner") as mock_planner:
                        mock_planner.return_value.create_plan.side_effect = Exception(
                            "Planning failed: API error"
                        )

                        result = cli_runner.invoke(app, ["start", "Complete the task"])

        assert result.exit_code == 1
        assert "Planning failed" in result.output
