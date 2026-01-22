"""Tests for the PlanUpdater class."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_task_master.core.plan_updater import PlanUpdater


class TestPlanUpdaterInit:
    """Tests for PlanUpdater initialization."""

    def test_init_with_all_components(self):
        """Test initialization with all components."""
        agent = MagicMock()
        state_manager = MagicMock()
        logger = MagicMock()

        updater = PlanUpdater(agent, state_manager, logger=logger)

        assert updater.agent is agent
        assert updater.state_manager is state_manager
        assert updater.logger is logger

    def test_init_without_logger(self):
        """Test initialization without logger."""
        agent = MagicMock()
        state_manager = MagicMock()

        updater = PlanUpdater(agent, state_manager)

        assert updater.agent is agent
        assert updater.state_manager is state_manager
        assert updater.logger is None

    def test_init_with_none_agent_raises_no_error(self):
        """Test initialization with None agent (no validation in __init__)."""
        state_manager = MagicMock()
        updater = PlanUpdater(None, state_manager)
        assert updater.agent is None

    def test_init_with_none_state_manager_raises_no_error(self):
        """Test initialization with None state_manager (no validation in __init__)."""
        agent = MagicMock()
        updater = PlanUpdater(agent, None)
        assert updater.state_manager is None


class TestPlanUpdaterUpdatePlan:
    """Tests for PlanUpdater.update_plan method."""

    def test_update_plan_no_existing_plan(self):
        """Test update_plan raises error when no plan exists."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = None

        updater = PlanUpdater(agent, state_manager)

        with pytest.raises(ValueError, match="No plan exists"):
            updater.update_plan("Add a new feature")

    def test_update_plan_empty_plan_raises_error(self):
        """Test update_plan raises error when plan is empty string."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with pytest.raises(ValueError, match="No plan exists"):
            updater.update_plan("Add a new feature")

    def test_update_plan_success(self):
        """Test update_plan successfully updates the plan."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Build a feature"
        state_manager.load_context.return_value = "Previous context"

        updater = PlanUpdater(agent, state_manager)

        # Mock the query execution
        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = (
                "## Task List\n- [ ] Task 1\n- [ ] Task 2 (new)\n\nPLAN UPDATE COMPLETE"
            )

            result = updater.update_plan("Add task 2")

        assert result["success"] is True
        assert "Task 2" in result["plan"]
        assert result["changes_made"] is True
        state_manager.save_plan.assert_called_once()

    def test_update_plan_no_changes(self):
        """Test update_plan when no changes are needed."""
        agent = MagicMock()
        state_manager = MagicMock()
        original_plan = "## Task List\n- [ ] Task 1"
        state_manager.load_plan.return_value = original_plan
        state_manager.load_goal.return_value = "Build a feature"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        # Mock returning the same plan
        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = original_plan

            result = updater.update_plan("No changes needed")

        assert result["success"] is True
        assert result["changes_made"] is False
        state_manager.save_plan.assert_not_called()

    def test_update_plan_with_logger(self):
        """Test update_plan logs operations."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""
        logger = MagicMock()

        updater = PlanUpdater(agent, state_manager, logger=logger)

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = "## Task List\n- [ ] Task 1\n- [ ] Task 2"

            updater.update_plan("Add task")

        # Should log the update using log_prompt and log_response
        assert logger.log_prompt.call_count >= 1 or logger.log_response.call_count >= 1

    def test_update_plan_logs_when_changes_made(self):
        """Test update_plan logs appropriately when changes are made."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""
        logger = MagicMock()

        updater = PlanUpdater(agent, state_manager, logger=logger)

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = "## Task List\n- [ ] Task 1\n- [ ] Task 2"
            updater.update_plan("Add task")

        # Check log_response was called with success message
        logger.log_response.assert_called()
        call_args = logger.log_response.call_args[0][0]
        assert "updated" in call_args.lower() or "saved" in call_args.lower()

    def test_update_plan_logs_when_no_changes(self):
        """Test update_plan logs appropriately when no changes are needed."""
        agent = MagicMock()
        state_manager = MagicMock()
        original_plan = "## Task List\n- [ ] Task 1"
        state_manager.load_plan.return_value = original_plan
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""
        logger = MagicMock()

        updater = PlanUpdater(agent, state_manager, logger=logger)

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = original_plan
            updater.update_plan("No changes")

        # Check log_response was called
        logger.log_response.assert_called()
        call_args = logger.log_response.call_args[0][0]
        assert "no change" in call_args.lower()

    def test_update_plan_with_whitespace_differences(self):
        """Test update_plan correctly handles whitespace differences."""
        agent = MagicMock()
        state_manager = MagicMock()
        original_plan = "## Task List\n- [ ] Task 1"
        state_manager.load_plan.return_value = original_plan
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        # Mock returning plan with extra whitespace
        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = "## Task List\n- [ ] Task 1\n\n"
            result = updater.update_plan("No changes")

        # Should not count as changes (stripped comparison)
        assert result["changes_made"] is False

    def test_update_plan_without_goal(self):
        """Test update_plan works when no goal is set."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = None
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = "## Task List\n- [ ] Task 1\n- [ ] Task 2"
            result = updater.update_plan("Add task")

        assert result["success"] is True

    def test_update_plan_without_context(self):
        """Test update_plan works when no context is set."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Build feature"
        state_manager.load_context.return_value = None

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = "## Task List\n- [ ] Task 1\n- [ ] Task 2"
            result = updater.update_plan("Add task")

        assert result["success"] is True

    def test_update_plan_returns_raw_output(self):
        """Test update_plan includes raw_output in result."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        raw_output = (
            "Some preamble\n\n## Task List\n- [ ] Task 1\n- [ ] Task 2\n\nPLAN UPDATE COMPLETE"
        )
        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = raw_output
            result = updater.update_plan("Add task")

        assert result["raw_output"] == raw_output

    def test_update_plan_preserves_completed_tasks(self):
        """Test update_plan preserves completed tasks in the plan."""
        agent = MagicMock()
        state_manager = MagicMock()
        original_plan = "## Task List\n- [x] Completed Task\n- [ ] Pending Task"
        state_manager.load_plan.return_value = original_plan
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        updated_plan = "## Task List\n- [x] Completed Task\n- [ ] Pending Task\n- [ ] New Task"
        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = updated_plan
            result = updater.update_plan("Add new task")

        assert "[x] Completed Task" in result["plan"]


class TestPlanUpdaterExtractPlan:
    """Tests for PlanUpdater._extract_updated_plan method."""

    def test_extract_plan_with_task_list(self):
        """Test extraction when Task List header is present."""
        agent = MagicMock()
        state_manager = MagicMock()
        updater = PlanUpdater(agent, state_manager)

        result = "Some preamble\n\n## Task List\n- [ ] Task 1\n- [ ] Task 2"
        extracted = updater._extract_updated_plan(result)

        assert extracted.startswith("## Task List")
        assert "Task 1" in extracted
        assert "Task 2" in extracted
        assert "preamble" not in extracted

    def test_extract_plan_with_complete_marker(self):
        """Test extraction removes PLAN UPDATE COMPLETE marker."""
        agent = MagicMock()
        state_manager = MagicMock()
        updater = PlanUpdater(agent, state_manager)

        result = "## Task List\n- [ ] Task 1\n\nPLAN UPDATE COMPLETE"
        extracted = updater._extract_updated_plan(result)

        assert "PLAN UPDATE COMPLETE" not in extracted
        assert "Task 1" in extracted

    def test_extract_plan_without_markers(self):
        """Test extraction when no markers are present."""
        agent = MagicMock()
        state_manager = MagicMock()
        updater = PlanUpdater(agent, state_manager)

        result = "- [ ] Task 1\n- [ ] Task 2"
        extracted = updater._extract_updated_plan(result)

        assert "Task 1" in extracted
        assert "Task 2" in extracted

    def test_extract_plan_with_multiple_task_list_headers(self):
        """Test extraction uses the first Task List header."""
        agent = MagicMock()
        state_manager = MagicMock()
        updater = PlanUpdater(agent, state_manager)

        result = "Preamble\n## Task List\n- [ ] Task 1\n\n## Task List (duplicate)\n- [ ] Task 2"
        extracted = updater._extract_updated_plan(result)

        assert extracted.startswith("## Task List")

    def test_extract_plan_with_marker_in_middle(self):
        """Test extraction handles marker not at end."""
        agent = MagicMock()
        state_manager = MagicMock()
        updater = PlanUpdater(agent, state_manager)

        result = "## Task List\n- [ ] Task 1\nPLAN UPDATE COMPLETE\nExtra text"
        extracted = updater._extract_updated_plan(result)

        assert "PLAN UPDATE COMPLETE" not in extracted
        assert "Extra text" not in extracted
        assert "Task 1" in extracted

    def test_extract_plan_strips_whitespace(self):
        """Test extraction strips leading/trailing whitespace."""
        agent = MagicMock()
        state_manager = MagicMock()
        updater = PlanUpdater(agent, state_manager)

        result = "\n\n  ## Task List\n- [ ] Task 1\n\n  "
        extracted = updater._extract_updated_plan(result)

        assert extracted.startswith("## Task List")
        assert not extracted.endswith("  ")

    def test_extract_plan_with_empty_result(self):
        """Test extraction handles empty result."""
        agent = MagicMock()
        state_manager = MagicMock()
        updater = PlanUpdater(agent, state_manager)

        result = ""
        extracted = updater._extract_updated_plan(result)

        assert extracted == ""

    def test_extract_plan_with_only_marker(self):
        """Test extraction handles result with only marker."""
        agent = MagicMock()
        state_manager = MagicMock()
        updater = PlanUpdater(agent, state_manager)

        result = "PLAN UPDATE COMPLETE"
        extracted = updater._extract_updated_plan(result)

        assert extracted == ""

    def test_extract_plan_preserves_pr_structure(self):
        """Test extraction preserves PR grouping structure."""
        agent = MagicMock()
        state_manager = MagicMock()
        updater = PlanUpdater(agent, state_manager)

        result = """## Task List

### PR 1: Infrastructure
- [x] `[quick]` Setup project
- [ ] `[coding]` Add database

### PR 2: API
- [ ] `[coding]` Add endpoints

## Success Criteria
1. All tests pass

PLAN UPDATE COMPLETE"""

        extracted = updater._extract_updated_plan(result)

        assert "### PR 1: Infrastructure" in extracted
        assert "### PR 2: API" in extracted
        assert "## Success Criteria" in extracted
        assert "PLAN UPDATE COMPLETE" not in extracted


class TestPlanUpdaterFromMessages:
    """Tests for PlanUpdater.update_plan_from_messages method."""

    def test_update_from_single_message(self):
        """Test update from a single message."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "update_plan") as mock_update:
            mock_update.return_value = {"success": True, "changes_made": True}

            updater.update_plan_from_messages(["Add new feature"])

        mock_update.assert_called_once_with("Add new feature")

    def test_update_from_multiple_messages(self):
        """Test update from multiple messages merges them."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "update_plan") as mock_update:
            mock_update.return_value = {"success": True, "changes_made": True}

            messages = ["Add feature A", "Fix bug B", "Update docs"]
            updater.update_plan_from_messages(messages)

        # Should be called with merged message
        call_args = mock_update.call_args[0][0]
        assert "Multiple change requests" in call_args
        assert "3 total" in call_args
        assert "Add feature A" in call_args
        assert "Fix bug B" in call_args
        assert "Update docs" in call_args
        assert "Change Request 1" in call_args
        assert "Change Request 2" in call_args
        assert "Change Request 3" in call_args

    def test_update_from_empty_messages(self):
        """Test update from empty messages raises error."""
        agent = MagicMock()
        state_manager = MagicMock()

        updater = PlanUpdater(agent, state_manager)

        with pytest.raises(ValueError, match="No messages provided"):
            updater.update_plan_from_messages([])

    def test_update_from_two_messages(self):
        """Test update from exactly two messages."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "update_plan") as mock_update:
            mock_update.return_value = {"success": True, "changes_made": True}

            messages = ["First message", "Second message"]
            updater.update_plan_from_messages(messages)

        call_args = mock_update.call_args[0][0]
        assert "2 total" in call_args
        assert "First message" in call_args
        assert "Second message" in call_args

    def test_update_from_messages_with_empty_strings(self):
        """Test update from messages list containing empty strings."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "update_plan") as mock_update:
            mock_update.return_value = {"success": True, "changes_made": True}

            # Include empty string - it should still be processed
            messages = ["Valid message", "", "Another valid"]
            updater.update_plan_from_messages(messages)

        mock_update.assert_called_once()

    def test_update_from_messages_returns_update_result(self):
        """Test update_plan_from_messages returns the result from update_plan."""
        agent = MagicMock()
        state_manager = MagicMock()

        updater = PlanUpdater(agent, state_manager)

        expected_result = {
            "success": True,
            "changes_made": True,
            "plan": "Updated plan",
            "raw_output": "Full output",
        }

        with patch.object(updater, "update_plan") as mock_update:
            mock_update.return_value = expected_result

            result = updater.update_plan_from_messages(["Test message"])

        assert result == expected_result

    def test_update_from_messages_with_special_characters(self):
        """Test update from messages containing special characters."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "update_plan") as mock_update:
            mock_update.return_value = {"success": True, "changes_made": True}

            messages = ["Fix bug #123", "Add 'quotes' and \"double quotes\"", "Special chars: <>&"]
            updater.update_plan_from_messages(messages)

        call_args = mock_update.call_args[0][0]
        assert "Fix bug #123" in call_args
        assert "'quotes'" in call_args
        assert '"double quotes"' in call_args


class TestPlanUpdaterQueryExecution:
    """Tests for PlanUpdater._run_plan_update_query method."""

    def test_query_uses_opus_model(self):
        """Test that plan update queries use Opus model."""
        agent = MagicMock()
        agent.get_tools_for_phase.return_value = ["Read", "Glob", "Grep", "Bash"]
        agent._get_model_name = MagicMock()
        agent._message_processor.process_message = MagicMock()

        # Create a mock query executor
        mock_executor = MagicMock()
        mock_executor.run_query = AsyncMock(return_value="## Task List\n- [ ] Task 1")
        agent._query_executor = mock_executor

        state_manager = MagicMock()

        updater = PlanUpdater(agent, state_manager)

        with patch("claude_task_master.core.plan_updater.run_async_with_cleanup") as mock_run:
            mock_run.return_value = "## Task List\n- [ ] Task 1"

            updater._run_plan_update_query("test prompt")

        # Verify run_async_with_cleanup was called
        mock_run.assert_called_once()

    def test_query_uses_planning_tools(self):
        """Test that plan update queries use planning tools."""
        agent = MagicMock()
        agent.get_tools_for_phase.return_value = ["Read", "Glob", "Grep", "Bash"]
        agent._query_executor = MagicMock()
        agent._query_executor.run_query = AsyncMock(return_value="result")
        agent._get_model_name = MagicMock()
        agent._message_processor.process_message = MagicMock()

        state_manager = MagicMock()

        updater = PlanUpdater(agent, state_manager)

        with patch("claude_task_master.core.plan_updater.run_async_with_cleanup") as mock_run:
            mock_run.return_value = "result"

            updater._run_plan_update_query("test prompt")

        # Verify tools were requested
        agent.get_tools_for_phase.assert_called_with("planning")

    def test_query_returns_string_result(self):
        """Test that _run_plan_update_query returns a string."""
        agent = MagicMock()
        agent.get_tools_for_phase.return_value = ["Read", "Glob", "Grep"]
        agent._query_executor = MagicMock()
        agent._query_executor.run_query = AsyncMock(return_value="Query result")
        agent._get_model_name = MagicMock()
        agent._message_processor.process_message = MagicMock()

        state_manager = MagicMock()

        updater = PlanUpdater(agent, state_manager)

        with patch("claude_task_master.core.plan_updater.run_async_with_cleanup") as mock_run:
            mock_run.return_value = "Query result"
            result = updater._run_plan_update_query("test prompt")

        assert isinstance(result, str)
        assert result == "Query result"


class TestPlanUpdaterErrorHandling:
    """Tests for error handling in PlanUpdater."""

    def test_update_plan_propagates_query_errors(self):
        """Test that errors from query execution are propagated."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.side_effect = RuntimeError("API error")

            with pytest.raises(RuntimeError, match="API error"):
                updater.update_plan("Add task")

    def test_update_plan_propagates_state_manager_errors(self):
        """Test that errors from state manager are propagated."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.side_effect = OSError("File read error")

        updater = PlanUpdater(agent, state_manager)

        with pytest.raises(OSError, match="File read error"):
            updater.update_plan("Add task")

    def test_update_plan_handles_save_errors(self):
        """Test that errors during plan save are propagated."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""
        state_manager.save_plan.side_effect = OSError("Write error")

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = "## Task List\n- [ ] Task 1\n- [ ] Task 2"

            with pytest.raises(OSError, match="Write error"):
                updater.update_plan("Add task")


class TestPlanUpdaterIntegration:
    """Integration tests for PlanUpdater with realistic scenarios."""

    def test_update_plan_with_complex_plan(self):
        """Test updating a complex plan with PR groups and multiple tasks."""
        agent = MagicMock()
        state_manager = MagicMock()

        original_plan = """## Task List

### PR 1: Infrastructure
- [x] `[quick]` Setup project structure
- [x] `[coding]` Add configuration module

### PR 2: Core Features
- [ ] `[coding]` Implement main logic
- [ ] `[coding]` Add error handling

## Success Criteria
1. All tests pass
2. Code coverage > 80%
"""
        state_manager.load_plan.return_value = original_plan
        state_manager.load_goal.return_value = "Build the application"
        state_manager.load_context.return_value = "Session 1: Setup complete"

        updater = PlanUpdater(agent, state_manager)

        updated_plan = """## Task List

### PR 1: Infrastructure
- [x] `[quick]` Setup project structure
- [x] `[coding]` Add configuration module

### PR 2: Core Features
- [ ] `[coding]` Implement main logic
- [ ] `[coding]` Add error handling
- [ ] `[coding]` Add logging (NEW)

### PR 3: Testing (NEW)
- [ ] `[general]` Add unit tests
- [ ] `[general]` Add integration tests

## Success Criteria
1. All tests pass
2. Code coverage > 80%
3. Logging enabled (NEW)
"""

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = updated_plan
            result = updater.update_plan("Add logging and testing tasks")

        assert result["success"] is True
        assert result["changes_made"] is True
        assert "PR 3: Testing" in result["plan"]
        assert "[x] `[quick]` Setup project structure" in result["plan"]
        state_manager.save_plan.assert_called_once()

    def test_update_plan_mailbox_scenario(self):
        """Test updating plan from multiple mailbox messages (realistic scenario)."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Build feature"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "update_plan") as mock_update:
            mock_update.return_value = {
                "success": True,
                "changes_made": True,
                "plan": "Updated plan",
                "raw_output": "Output",
            }

            # Simulate multiple messages from mailbox (different priorities)
            messages = [
                "URGENT: Fix security vulnerability in auth module",
                "Add rate limiting to API endpoints",
                "Update documentation for new features",
            ]
            result = updater.update_plan_from_messages(messages)

        assert result["success"] is True
        call_args = mock_update.call_args[0][0]
        assert "URGENT" in call_args
        assert "rate limiting" in call_args
        assert "documentation" in call_args


class TestPlanUpdaterEdgeCases:
    """Edge case tests for PlanUpdater."""

    def test_update_plan_with_unicode_content(self):
        """Test update_plan handles Unicode content correctly."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] タスク 1 (Task 1)"
        state_manager.load_goal.return_value = "Build 日本語 feature"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = "## Task List\n- [ ] タスク 1\n- [ ] タスク 2 🚀"
            result = updater.update_plan("Add emoji task")

        assert "タスク" in result["plan"]
        assert "🚀" in result["plan"]

    def test_update_plan_with_very_long_plan(self):
        """Test update_plan handles very long plans."""
        agent = MagicMock()
        state_manager = MagicMock()

        # Create a plan with many tasks
        tasks = [f"- [ ] Task {i}: Do something important #{i}" for i in range(100)]
        long_plan = "## Task List\n\n" + "\n".join(tasks) + "\n\n## Success Criteria\n1. All done"

        state_manager.load_plan.return_value = long_plan
        state_manager.load_goal.return_value = "Complete all tasks"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = long_plan + "\n- [ ] Task 100: New task"
            result = updater.update_plan("Add one more task")

        assert result["success"] is True
        assert "Task 100" in result["plan"]

    def test_update_plan_with_code_blocks(self):
        """Test update_plan handles plans containing code blocks."""
        agent = MagicMock()
        state_manager = MagicMock()

        plan_with_code = """## Task List

- [ ] Add the following code:
  ```python
  def example():
      return "test"
  ```
- [ ] Update config

## Success Criteria
1. Code works
"""
        state_manager.load_plan.return_value = plan_with_code
        state_manager.load_goal.return_value = "Add code"
        state_manager.load_context.return_value = ""

        updater = PlanUpdater(agent, state_manager)

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = plan_with_code
            result = updater.update_plan("No changes")

        assert "```python" in result["plan"]
        assert "def example():" in result["plan"]

    def test_extract_plan_with_marker_at_end(self):
        """Test extraction handles marker at the very end."""
        agent = MagicMock()
        state_manager = MagicMock()
        updater = PlanUpdater(agent, state_manager)

        result = """Some intro text

## Task List
- [ ] Task 1
- [ ] Task 2
- [ ] Task 3

## Success Criteria
1. Done

PLAN UPDATE COMPLETE"""

        extracted = updater._extract_updated_plan(result)

        assert "## Task List" in extracted
        assert "Task 1" in extracted
        assert "Task 2" in extracted
        assert "Task 3" in extracted
        assert "## Success Criteria" in extracted
        # The marker should be removed
        assert "PLAN UPDATE COMPLETE" not in extracted
        assert not extracted.endswith("PLAN UPDATE COMPLETE")

    def test_update_plan_prompt_truncation_in_logger(self):
        """Test that long change requests are truncated in logger."""
        agent = MagicMock()
        state_manager = MagicMock()
        state_manager.load_plan.return_value = "## Task List\n- [ ] Task 1"
        state_manager.load_goal.return_value = "Goal"
        state_manager.load_context.return_value = ""
        logger = MagicMock()

        updater = PlanUpdater(agent, state_manager, logger=logger)

        long_request = "A" * 200  # Very long request

        with patch.object(updater, "_run_plan_update_query") as mock_query:
            mock_query.return_value = "## Task List\n- [ ] Task 1"
            updater.update_plan(long_request)

        # Logger should have been called with truncated message
        logger.log_prompt.assert_called()
        logged_msg = logger.log_prompt.call_args[0][0]
        assert "..." in logged_msg  # Should be truncated
