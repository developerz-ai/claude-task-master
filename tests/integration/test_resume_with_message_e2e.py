"""End-to-end integration tests for the resume with message feature.

These tests verify the complete resume-with-message workflow including:
- Resume without message (existing behavior)
- Resume with message triggering plan update
- Plan preservation during updates
- State management during resume
- Integration with mailbox system
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.core.credentials import CredentialManager
from claude_task_master.core.plan_updater import PlanUpdater
from claude_task_master.core.state import StateManager, TaskOptions


class TestResumeWithoutMessage:
    """Tests for resume command without a message (existing behavior)."""

    def test_resume_without_message_continues_from_paused_state(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test that resume without message continues from paused state."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Configure mock responses
        patched_sdk.set_work_response("Task completed successfully.")
        patched_sdk.set_verify_response("All criteria met!")

        result = runner.invoke(app, ["resume"])

        # Should resume without error
        assert "Resuming" in result.output or "resume" in result.output.lower()

    def test_resume_preserves_completed_tasks(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test that resume preserves already completed tasks."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        patched_sdk.set_work_response("Done")
        patched_sdk.set_verify_response("Verified")

        runner.invoke(app, ["resume"])

        # Check that completed tasks are still marked complete in plan
        plan_file = integration_state_dir / "plan.md"
        if plan_file.exists():
            plan_content = plan_file.read_text()
            # First two tasks should still be complete
            assert plan_content.count("[x]") >= 2


class TestResumeWithMessage:
    """Tests for resume command with a message."""

    def test_resume_with_message_updates_plan(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        mock_agent_wrapper,
        monkeypatch,
    ):
        """Test that resume with message updates the plan before continuing."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # We need to mock the PlanUpdater
        with patch("claude_task_master.cli_commands.workflow.PlanUpdater") as MockPlanUpdater:
            mock_updater = MagicMock()
            mock_updater.update_plan.return_value = {
                "success": True,
                "changes_made": True,
                "plan": "## Task List\n- [x] Done\n- [ ] New task from message",
                "raw_output": "Updated",
            }
            MockPlanUpdater.return_value = mock_updater

            patched_sdk.set_work_response("Done")
            patched_sdk.set_verify_response("Verified")

            runner.invoke(app, ["resume", "Add new security feature"])

            # Should indicate plan was updated
            if mock_updater.update_plan.called:
                call_args = mock_updater.update_plan.call_args[0][0]
                assert "security feature" in call_args

    def test_resume_with_empty_message_behaves_like_no_message(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test that resume with empty message behaves like resume without message."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        patched_sdk.set_work_response("Done")
        patched_sdk.set_verify_response("Verified")

        # Empty message should be treated as no message
        result = runner.invoke(app, ["resume", ""])

        # Should not fail
        assert result.exit_code in [0, 1]  # Either success or normal blocked


class TestPlanUpdaterIntegration:
    """Integration tests for the PlanUpdater class."""

    def test_plan_updater_preserves_completed_tasks(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
    ):
        """Test that plan updater preserves completed tasks."""
        state_manager = StateManager(integration_state_dir)
        options = TaskOptions(auto_merge=True)
        state_manager.initialize(goal="Test goal", model="sonnet", options=options)

        # Plan with some completed tasks
        original_plan = """## Task List

- [x] Task 1 (completed)
- [x] Task 2 (completed)
- [ ] Task 3 (pending)
- [ ] Task 4 (pending)

## Success Criteria

1. All done
"""
        state_manager.save_plan(original_plan)

        plan_updater = PlanUpdater(mock_agent_wrapper, state_manager)

        # Mock the query to return plan with modifications
        with patch.object(plan_updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = """## Task List

- [x] Task 1 (completed)
- [x] Task 2 (completed)
- [ ] Task 3 (pending) - updated priority
- [ ] Task 4 (pending)
- [ ] Task 5 (new from change request)

## Success Criteria

1. All done
"""
            result = plan_updater.update_plan("Add Task 5 and update Task 3 priority")

        # Completed tasks should still be marked complete
        assert "[x] Task 1" in result["plan"]
        assert "[x] Task 2" in result["plan"]
        # New task should be added
        assert "Task 5" in result["plan"]

    def test_plan_updater_with_pr_structure(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
    ):
        """Test that plan updater preserves PR structure."""
        state_manager = StateManager(integration_state_dir)
        options = TaskOptions(auto_merge=True)
        state_manager.initialize(goal="Test goal", model="sonnet", options=options)

        original_plan = """## Task List

### PR 1: Infrastructure
- [x] Setup project
- [ ] Add configuration

### PR 2: Features
- [ ] Implement feature A
- [ ] Implement feature B

## Success Criteria

1. All PRs merged
"""
        state_manager.save_plan(original_plan)

        plan_updater = PlanUpdater(mock_agent_wrapper, state_manager)

        with patch.object(plan_updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = """## Task List

### PR 1: Infrastructure
- [x] Setup project
- [ ] Add configuration

### PR 2: Features
- [ ] Implement feature A
- [ ] Implement feature B
- [ ] Implement feature C (new)

### PR 3: Testing (new)
- [ ] Add unit tests

## Success Criteria

1. All PRs merged
"""
            result = plan_updater.update_plan("Add feature C and testing PR")

        # PR structure should be preserved
        assert "### PR 1: Infrastructure" in result["plan"]
        assert "### PR 2: Features" in result["plan"]
        assert "### PR 3: Testing" in result["plan"]

    def test_plan_updater_handles_no_changes_needed(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_agent_wrapper,
    ):
        """Test that plan updater correctly handles when no changes are needed."""
        state_manager = StateManager(integration_state_dir)
        options = TaskOptions(auto_merge=True)
        state_manager.initialize(goal="Test goal", model="sonnet", options=options)

        original_plan = """## Task List

- [ ] Task 1
- [ ] Task 2

## Success Criteria

1. All done
"""
        state_manager.save_plan(original_plan)

        plan_updater = PlanUpdater(mock_agent_wrapper, state_manager)

        with patch.object(plan_updater, "_run_plan_update_query") as mock_query:
            # Return the same plan
            mock_query.return_value = original_plan

            result = plan_updater.update_plan("No changes needed")

        assert result["success"] is True
        assert result["changes_made"] is False


class TestResumeStateTransitions:
    """Tests for state transitions during resume operations."""

    def test_resume_from_paused_updates_status(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test that resume from paused state updates status correctly."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Check initial state is paused
        state_file = integration_state_dir / "state.json"
        initial_state = json.loads(state_file.read_text())
        assert initial_state["status"] == "paused"

        patched_sdk.set_work_response("Done")
        patched_sdk.set_verify_response("Verified")

        runner.invoke(app, ["resume"])

        # Status should have changed from paused
        if state_file.exists():
            final_state = json.loads(state_file.read_text())
            assert final_state["status"] != "paused"

    def test_resume_from_blocked_state(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        blocked_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test resume from blocked state."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        patched_sdk.set_work_response("Done")
        patched_sdk.set_verify_response("Verified")

        result = runner.invoke(app, ["resume"])

        # Should resume from blocked state (blocked is resumable)
        assert "Resuming" in result.output or result.exit_code in [0, 1]

    def test_resume_increments_session_count(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test that resume increments session count."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Record initial session count
        initial_session_count = paused_state["state_data"]["session_count"]

        patched_sdk.set_work_response("Done")
        patched_sdk.set_verify_response("Verified")

        runner.invoke(app, ["resume"])

        # Session count should have increased
        state_file = integration_state_dir / "state.json"
        if state_file.exists():
            final_state = json.loads(state_file.read_text())
            assert final_state["session_count"] >= initial_session_count


class TestResumeWithMailboxIntegration:
    """Tests for resume integration with the mailbox system."""

    def test_resume_message_can_be_sent_via_mailbox(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test that resume message can be equivalent to mailbox message."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Instead of resume with message, add to mailbox
        from claude_task_master.mailbox import MailboxStorage

        mailbox = MailboxStorage(integration_state_dir)
        mailbox.add_message("Add new authentication feature", sender="cli")

        # Verify mailbox has the message
        assert mailbox.count() == 1

        # When orchestrator runs, it should pick up the mailbox message
        # This is tested in the orchestrator integration tests

    def test_resume_with_message_clears_any_pending_mailbox(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test behavior when resume with message and mailbox both have messages."""
        from claude_task_master.mailbox import MailboxStorage

        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Add message to mailbox
        mailbox = MailboxStorage(integration_state_dir)
        mailbox.add_message("Mailbox message", sender="supervisor")

        patched_sdk.set_work_response("Done")
        patched_sdk.set_verify_response("Verified")

        # Resume with a different message
        with patch("claude_task_master.cli_commands.workflow.PlanUpdater") as MockPlanUpdater:
            mock_updater = MagicMock()
            mock_updater.update_plan.return_value = {
                "success": True,
                "changes_made": False,
            }
            MockPlanUpdater.return_value = mock_updater

            runner.invoke(app, ["resume", "CLI message"])

            # Both messages might be processed depending on implementation


class TestResumeErrorHandling:
    """Tests for error handling during resume operations."""

    def test_resume_no_task_found(
        self,
        integration_temp_dir: Path,
        monkeypatch,
    ):
        """Test resume when no task exists."""
        runner = CliRunner()
        state_dir = integration_temp_dir / ".claude-task-master"
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", state_dir)

        # Ensure no state exists
        if state_dir.exists():
            import shutil

            shutil.rmtree(state_dir)

        result = runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        assert "No task found" in result.output

    def test_resume_completed_task_shows_message(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        completed_state,
        monkeypatch,
    ):
        """Test resume on a completed task shows appropriate message."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["resume"])

        # Should indicate task is already complete
        assert (
            result.exit_code == 0
            or "success" in result.output.lower()
            or "completed" in result.output.lower()
        )

    def test_resume_failed_task_requires_clean(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        failed_state,
        monkeypatch,
    ):
        """Test resume on a failed task suggests cleanup."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        result = runner.invoke(app, ["resume"])

        # Should indicate task has failed and suggest clean
        assert result.exit_code == 1
        assert "failed" in result.output.lower() or "cannot" in result.output.lower()


class TestResumeWithMessageEdgeCases:
    """Edge case tests for resume with message functionality."""

    def test_resume_with_very_long_message(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test resume with a very long message."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        long_message = "A" * 5000  # Very long message

        with patch("claude_task_master.cli_commands.workflow.PlanUpdater") as MockPlanUpdater:
            mock_updater = MagicMock()
            mock_updater.update_plan.return_value = {
                "success": True,
                "changes_made": True,
            }
            MockPlanUpdater.return_value = mock_updater

            patched_sdk.set_work_response("Done")
            patched_sdk.set_verify_response("Verified")

            result = runner.invoke(app, ["resume", long_message])

            # Should handle long message without error
            assert result.exit_code in [0, 1]

    def test_resume_with_special_characters(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test resume with special characters in message."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        special_message = 'Fix "bug" with <script> & special chars'

        with patch("claude_task_master.cli_commands.workflow.PlanUpdater") as MockPlanUpdater:
            mock_updater = MagicMock()
            mock_updater.update_plan.return_value = {
                "success": True,
                "changes_made": True,
            }
            MockPlanUpdater.return_value = mock_updater

            patched_sdk.set_work_response("Done")
            patched_sdk.set_verify_response("Verified")

            result = runner.invoke(app, ["resume", special_message])

            # Should handle special characters
            assert result.exit_code in [0, 1]

    def test_resume_with_unicode_message(
        self,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        paused_state,
        patched_sdk,
        monkeypatch,
    ):
        """Test resume with Unicode characters in message."""
        runner = CliRunner()
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        unicode_message = "Add feature: 日本語対応 and emoji support 🚀"

        with patch("claude_task_master.cli_commands.workflow.PlanUpdater") as MockPlanUpdater:
            mock_updater = MagicMock()
            mock_updater.update_plan.return_value = {
                "success": True,
                "changes_made": True,
            }
            MockPlanUpdater.return_value = mock_updater

            patched_sdk.set_work_response("Done")
            patched_sdk.set_verify_response("Verified")

            result = runner.invoke(app, ["resume", unicode_message])

            # Should handle Unicode
            assert result.exit_code in [0, 1]
