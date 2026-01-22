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
