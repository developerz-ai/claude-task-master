"""Tests for AgentWrapper planning, working, and verification phases.

This module contains tests for:
- Tool configurations for different phases (planning, working, verification)
- Prompt building for each phase
- Plan and criteria extraction
- run_planning_phase method
- run_work_session method
- verify_success_criteria method
- Phase integration and edge cases
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_task_master.core.agent import AgentWrapper, ModelType, ToolConfig

# =============================================================================
# ToolConfig Enum Tests
# =============================================================================


class TestToolConfig:
    """Tests for ToolConfig enum."""

    def test_planning_tools(self):
        """Test PLANNING tool configuration - read-only tools for exploration."""
        expected = [
            "Read",
            "Glob",
            "Grep",
            "Bash",
        ]
        assert ToolConfig.PLANNING.value == expected

    def test_working_tools(self):
        """Test WORKING tool configuration - empty list allows ALL tools."""
        # Empty list means all tools are allowed
        assert ToolConfig.WORKING.value == []

    def test_verification_tools(self):
        """Test VERIFICATION tool configuration - read tools + Bash for running tests."""
        expected = [
            "Read",
            "Glob",
            "Grep",
            "Bash",
        ]
        assert ToolConfig.VERIFICATION.value == expected

    def test_planning_has_subset_of_working_tools(self):
        """Test planning tools are restricted while working allows all tools."""
        planning_tools = set(ToolConfig.PLANNING.value)
        # Working phase uses empty list (all tools allowed)
        # Planning has specific tools, so it's more restricted
        assert len(planning_tools) > 0  # Planning has specific restrictions
        assert len(ToolConfig.WORKING.value) == 0  # Working allows all

    def test_verification_has_subset_of_working_tools(self):
        """Test verification tools are restricted while working allows all tools."""
        verification_tools = set(ToolConfig.VERIFICATION.value)
        # Working phase uses empty list (all tools allowed)
        # Verification has specific tools, so it's more restricted
        assert len(verification_tools) > 0  # Verification has specific restrictions
        assert len(ToolConfig.WORKING.value) == 0  # Working allows all
        # Verification has Bash but no Write/Edit
        assert "Bash" in verification_tools
        assert "Write" not in verification_tools
        assert "Edit" not in verification_tools


# =============================================================================
# AgentWrapper get_tools_for_phase Tests
# =============================================================================


class TestAgentWrapperGetToolsForPhase:
    """Tests for get_tools_for_phase method."""

    @pytest.fixture
    def agent(self):
        """Create an AgentWrapper instance for testing."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            return AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
            )

    def test_planning_phase_tools(self, agent):
        """Test get_tools_for_phase returns planning tools including Bash for checks."""
        tools = agent.get_tools_for_phase("planning")
        expected = [
            "Read",
            "Glob",
            "Grep",
            "Bash",
        ]
        assert tools == expected

    def test_verification_phase_tools(self, agent):
        """Test get_tools_for_phase returns verification tools (read + Bash)."""
        tools = agent.get_tools_for_phase("verification")
        expected = [
            "Read",
            "Glob",
            "Grep",
            "Bash",
        ]
        assert tools == expected

    def test_working_phase_tools(self, agent):
        """Test get_tools_for_phase returns working tools (empty list = all tools)."""
        tools = agent.get_tools_for_phase("working")
        # Empty list means all tools are allowed
        assert tools == []

    def test_unknown_phase_returns_working_tools(self, agent):
        """Test unknown phase returns working tools by default (empty list = all tools)."""
        tools = agent.get_tools_for_phase("unknown")
        # Empty list means all tools are allowed
        assert tools == []

    def test_empty_phase_returns_working_tools(self, agent):
        """Test empty phase string returns working tools (empty list = all tools)."""
        tools = agent.get_tools_for_phase("")
        # Empty list means all tools are allowed
        assert tools == []


# =============================================================================
# Prompt Building Tests (uses prompts module directly since methods were extracted)
# =============================================================================


class TestPromptBuilding:
    """Tests for prompt building using centralized prompts module."""

    def test_build_planning_prompt_includes_goal(self):
        """Test build_planning_prompt includes the goal."""
        from claude_task_master.core.prompts import build_planning_prompt

        goal = "Build a REST API"
        prompt = build_planning_prompt(goal=goal, context=None)

        assert "Build a REST API" in prompt

    def test_build_planning_prompt_includes_context(self):
        """Test build_planning_prompt includes the context."""
        from claude_task_master.core.prompts import build_planning_prompt

        context = "Previous session completed setup."
        prompt = build_planning_prompt(goal="Test goal", context=context)

        assert "Previous session completed setup." in prompt

    def test_build_planning_prompt_includes_task_list_format(self):
        """Test build_planning_prompt includes task list format instructions."""
        from claude_task_master.core.prompts import build_planning_prompt

        prompt = build_planning_prompt(goal="Test goal", context=None)

        # Uses centralized prompts.py format
        assert "Create Task List" in prompt  # Step 2: Create Task List
        assert "- [ ]" in prompt
        assert "Success Criteria" in prompt

    def test_build_planning_prompt_includes_exploration_instruction(self):
        """Test build_planning_prompt includes exploration instruction."""
        from claude_task_master.core.prompts import build_planning_prompt

        prompt = build_planning_prompt(goal="Test goal", context=None)

        # Must explore codebase before creating tasks
        assert "Explore" in prompt
        assert "READ ONLY" in prompt or "Read" in prompt

    def test_build_planning_prompt_mentions_tools(self):
        """Test build_planning_prompt mentions available tools."""
        from claude_task_master.core.prompts import build_planning_prompt

        prompt = build_planning_prompt(goal="Test goal", context=None)

        assert "Read" in prompt
        assert "Glob" in prompt
        assert "Grep" in prompt

    def test_build_work_prompt_includes_task(self):
        """Test build_work_prompt includes the task description."""
        from claude_task_master.core.prompts import build_work_prompt

        task = "Implement user authentication"
        prompt = build_work_prompt(task_description=task, context=None, pr_comments=None)

        assert "Implement user authentication" in prompt

    def test_build_work_prompt_includes_context(self):
        """Test build_work_prompt includes context."""
        from claude_task_master.core.prompts import build_work_prompt

        context = "Using FastAPI framework."
        prompt = build_work_prompt(task_description="Test task", context=context, pr_comments=None)

        assert "Using FastAPI framework." in prompt

    def test_build_work_prompt_includes_pr_comments(self):
        """Test build_work_prompt includes PR comments when provided."""
        from claude_task_master.core.prompts import build_work_prompt

        pr_comments = "Please add error handling for edge cases."
        prompt = build_work_prompt(
            task_description="Test task", context=None, pr_comments=pr_comments
        )

        # Uses centralized prompts.py format
        assert "PR Review Feedback" in prompt
        assert "Please add error handling for edge cases." in prompt

    def test_build_work_prompt_without_pr_comments(self):
        """Test build_work_prompt without PR comments."""
        from claude_task_master.core.prompts import build_work_prompt

        prompt = build_work_prompt(task_description="Test task", context=None, pr_comments=None)

        assert "PR Review Feedback" not in prompt

    def test_build_work_prompt_mentions_tools(self):
        """Test build_work_prompt mentions git and common commands."""
        from claude_task_master.core.prompts import build_work_prompt

        prompt = build_work_prompt(task_description="Test task", context=None, pr_comments=None)

        # Check for key workflow elements instead of tool names
        assert "git" in prompt
        assert "commit" in prompt
        assert "Edit" in prompt
        assert "Write" in prompt


# =============================================================================
# AgentPhaseExecutor Extract Methods Tests
# =============================================================================


class TestAgentPhaseExecutorExtractMethods:
    """Tests for plan/criteria extraction methods on AgentPhaseExecutor."""

    @pytest.fixture
    def phase_executor(self):
        """Create an AgentPhaseExecutor instance for testing."""
        from claude_task_master.core.agent_phases import AgentPhaseExecutor

        # Create a mock query executor
        mock_query_executor = MagicMock()

        return AgentPhaseExecutor(
            query_executor=mock_query_executor,
            model=ModelType.SONNET,
            logger=None,
        )

    def test_extract_plan_with_proper_format(self, phase_executor):
        """Test _extract_plan returns result with proper format."""
        result = """## Task List

- [ ] Task 1
- [ ] Task 2

## Success Criteria

1. All tests pass
"""
        extracted = phase_executor._extract_plan(result)
        assert extracted == result

    def test_extract_plan_wraps_improper_format(self, phase_executor):
        """Test _extract_plan wraps result without proper format."""
        result = "Some unformatted content"
        extracted = phase_executor._extract_plan(result)

        assert "## Task List" in extracted
        assert "Some unformatted content" in extracted

    def test_extract_criteria_with_proper_format(self, phase_executor):
        """Test _extract_criteria extracts criteria section."""
        result = """## Task List

- [ ] Task 1

## Success Criteria

1. All tests pass
2. Coverage > 80%
"""
        extracted = phase_executor._extract_criteria(result)

        assert "1. All tests pass" in extracted
        assert "2. Coverage > 80%" in extracted

    def test_extract_criteria_without_criteria_section(self, phase_executor):
        """Test _extract_criteria returns default when no criteria section."""
        result = """## Task List

- [ ] Task 1
- [ ] Task 2
"""
        extracted = phase_executor._extract_criteria(result)

        assert "All tasks in the task list are completed successfully." in extracted

    def test_extract_criteria_empty_result(self, phase_executor):
        """Test _extract_criteria with empty result."""
        extracted = phase_executor._extract_criteria("")
        assert "All tasks in the task list are completed successfully." in extracted


# =============================================================================
# AgentPhaseExecutor Parse Verification Result Tests
# =============================================================================


class TestAgentPhaseExecutorParseVerificationResult:
    """Tests for verification result parsing on AgentPhaseExecutor."""

    @pytest.fixture
    def phase_executor(self):
        """Create an AgentPhaseExecutor instance for testing."""
        from claude_task_master.core.agent_phases import AgentPhaseExecutor

        mock_query_executor = MagicMock()

        return AgentPhaseExecutor(
            query_executor=mock_query_executor,
            model=ModelType.SONNET,
            logger=None,
        )

    def test_parse_explicit_pass_marker(self, phase_executor):
        """Test parsing explicit VERIFICATION_RESULT: PASS marker."""
        result = "Some details... VERIFICATION_RESULT: PASS"
        assert phase_executor._parse_verification_result(result) is True

    def test_parse_explicit_fail_marker(self, phase_executor):
        """Test parsing explicit VERIFICATION_RESULT: FAIL marker."""
        result = "Some details... VERIFICATION_RESULT: FAIL"
        assert phase_executor._parse_verification_result(result) is False

    def test_parse_all_criteria_met(self, phase_executor):
        """Test parsing 'all criteria met' indicator."""
        result = "All criteria met successfully"
        assert phase_executor._parse_verification_result(result) is True

    def test_parse_overall_success_yes(self, phase_executor):
        """Test parsing 'Overall Success: YES' indicator."""
        result = "Overall Success: YES"
        assert phase_executor._parse_verification_result(result) is True

    def test_parse_overall_success_no(self, phase_executor):
        """Test parsing 'Overall Success: NO' indicator (should fail)."""
        result = "Overall Success: NO"
        assert phase_executor._parse_verification_result(result) is False

    def test_parse_criteria_not_met(self, phase_executor):
        """Test parsing 'criteria not met' indicator."""
        result = "Some criteria not met"
        assert phase_executor._parse_verification_result(result) is False

    def test_parse_verification_failed(self, phase_executor):
        """Test parsing 'verification failed' indicator."""
        result = "Verification failed due to errors"
        assert phase_executor._parse_verification_result(result) is False

    def test_parse_generic_success(self, phase_executor):
        """Test parsing generic 'success' indicator."""
        result = "Implementation is a success"
        assert phase_executor._parse_verification_result(result) is True

    def test_parse_negative_overrides_positive(self, phase_executor):
        """Test negative indicators override positive ones."""
        result = "Success noted but criteria not met"
        assert phase_executor._parse_verification_result(result) is False


# =============================================================================
# AgentWrapper run_planning_phase Tests
# =============================================================================


class TestAgentWrapperRunPlanningPhase:
    """Tests for run_planning_phase method."""

    @pytest.fixture
    def agent_with_mock(self, temp_dir):
        """Create an AgentWrapper with mocked _run_query."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
            )
        return agent

    def test_run_planning_phase_returns_dict(self, agent_with_mock):
        """Test run_planning_phase returns a dictionary."""
        mock_result = """## Task List

- [ ] Setup project
- [ ] Implement feature

## Success Criteria

1. All tests pass
"""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_result
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value=mock_result,
            ):
                result = agent_with_mock.run_planning_phase("Build API")

        assert isinstance(result, dict)

    def test_run_planning_phase_contains_required_keys(self, agent_with_mock):
        """Test run_planning_phase returns required keys."""
        mock_result = """## Task List

- [ ] Task 1

## Success Criteria

1. Criterion
"""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_result
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value=mock_result,
            ):
                result = agent_with_mock.run_planning_phase("Goal")

        assert "plan" in result
        assert "criteria" in result
        assert "raw_output" in result

    def test_run_planning_phase_uses_planning_tools(self, agent_with_mock):
        """Test run_planning_phase uses planning tools."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "test result"

            async def run_query_capture(*args, **kwargs):
                return "test result"

            mock_query.side_effect = run_query_capture

            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup"
            ) as mock_asyncio:
                mock_asyncio.return_value = "test result"
                agent_with_mock.run_planning_phase("Goal")

                # Check that run_async_with_cleanup was called
                assert mock_asyncio.called

    def test_run_planning_phase_with_context(self, agent_with_mock):
        """Test run_planning_phase includes context."""
        mock_result = """## Task List

- [ ] Task 1

## Success Criteria

1. Done
"""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_result
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value=mock_result,
            ):
                result = agent_with_mock.run_planning_phase("Goal", context="Previous info")

        assert result is not None
        assert "plan" in result

    def test_run_planning_phase_extracts_plan_correctly(self, agent_with_mock):
        """Test run_planning_phase extracts plan correctly."""
        mock_result = """## Task List

- [ ] Setup database
- [ ] Create API endpoints
- [ ] Write tests

## Success Criteria

1. All endpoints respond correctly
2. 90% test coverage
"""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_result
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value=mock_result,
            ):
                result = agent_with_mock.run_planning_phase("Build API")

        assert "Setup database" in result["plan"]
        assert "Create API endpoints" in result["plan"]
        assert "All endpoints respond correctly" in result["criteria"]


# =============================================================================
# AgentWrapper run_work_session Tests
# =============================================================================


class TestAgentWrapperRunWorkSession:
    """Tests for run_work_session method."""

    @pytest.fixture
    def agent_with_mock(self, temp_dir):
        """Create an AgentWrapper with mocked methods."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
            )
        return agent

    def test_run_work_session_returns_dict(self, agent_with_mock):
        """Test run_work_session returns a dictionary."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Work completed"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="Work completed",
            ):
                result = agent_with_mock.run_work_session("Implement feature")

        assert isinstance(result, dict)

    def test_run_work_session_contains_required_keys(self, agent_with_mock):
        """Test run_work_session returns required keys."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup", return_value="Done"
            ):
                result = agent_with_mock.run_work_session("Task")

        assert "output" in result
        assert "success" in result

    def test_run_work_session_assumes_success(self, agent_with_mock):
        """Test run_work_session assumes success for MVP."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup", return_value="Done"
            ):
                result = agent_with_mock.run_work_session("Task")

        assert result["success"] is True

    def test_run_work_session_with_context(self, agent_with_mock):
        """Test run_work_session includes context."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup", return_value="Done"
            ):
                result = agent_with_mock.run_work_session("Task", context="Previous work info")

        assert result is not None

    def test_run_work_session_with_pr_comments(self, agent_with_mock):
        """Test run_work_session includes PR comments."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup", return_value="Done"
            ):
                result = agent_with_mock.run_work_session(
                    "Task", pr_comments="Fix the error handling"
                )

        assert result is not None

    def test_run_work_session_returns_output(self, agent_with_mock):
        """Test run_work_session returns the output from query."""
        expected_output = "Implemented the feature successfully with all tests passing."
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = expected_output
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value=expected_output,
            ):
                result = agent_with_mock.run_work_session("Implement feature")

        assert result["output"] == expected_output


# =============================================================================
# AgentWrapper verify_success_criteria Tests
# =============================================================================


class TestAgentWrapperVerifySuccessCriteria:
    """Tests for verify_success_criteria method."""

    @pytest.fixture
    def agent_with_mock(self, temp_dir):
        """Create an AgentWrapper with mocked methods."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
            )
        return agent

    def test_verify_success_criteria_returns_dict(self, agent_with_mock):
        """Test verify_success_criteria returns a dictionary."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "All criteria met."
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="All criteria met.",
            ):
                result = agent_with_mock.verify_success_criteria("Tests pass")

        assert isinstance(result, dict)

    def test_verify_success_criteria_contains_required_keys(self, agent_with_mock):
        """Test verify_success_criteria returns required keys."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Success"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="Success",
            ):
                result = agent_with_mock.verify_success_criteria("Tests pass")

        assert "success" in result
        assert "details" in result

    def test_verify_success_criteria_detects_success(self, agent_with_mock):
        """Test verify_success_criteria detects success indicators."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "All criteria met. Everything is working correctly."
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="All criteria met. Everything is working correctly.",
            ):
                result = agent_with_mock.verify_success_criteria("Tests pass")

        assert result["success"] is True

    def test_verify_success_criteria_detects_failure(self, agent_with_mock):
        """Test verify_success_criteria detects failure."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Some criteria are not met. Tests are failing."
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="Some criteria are not met. Tests are failing.",
            ):
                result = agent_with_mock.verify_success_criteria("Tests pass")

        assert result["success"] is False

    def test_verify_success_criteria_with_context(self, agent_with_mock):
        """Test verify_success_criteria uses context."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Success confirmed"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="Success confirmed",
            ):
                result = agent_with_mock.verify_success_criteria(
                    "Tests pass", context="Additional context info"
                )

        assert result is not None

    def test_verify_success_criteria_uses_verification_tools(self, agent_with_mock):
        """Test verify_success_criteria uses verification tools (read + Bash)."""
        # The verification phase should use tools that can run tests
        tools = agent_with_mock.get_tools_for_phase("verification")
        assert "Bash" in tools  # Can run tests
        assert "Read" in tools  # Can read files
        assert "Write" not in tools  # Cannot modify files


# =============================================================================
# AgentWrapper Phase Integration Tests
# =============================================================================


class TestAgentWrapperPhaseIntegration:
    """Integration tests for AgentWrapper phases."""

    @pytest.fixture
    def agent(self, temp_dir):
        """Create an AgentWrapper instance for testing."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
            )
        return agent

    def test_full_planning_to_verification_workflow(self, agent):
        """Test complete workflow from planning to verification."""
        planning_result = """## Task List

- [ ] Setup project structure
- [ ] Implement core logic
- [ ] Add tests

## Success Criteria

1. All tests pass
2. Documentation complete
"""
        work_result = "Completed all tasks successfully."
        verification_result = "All criteria met. Project is complete."

        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            # Test planning
            mock_query.return_value = planning_result
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value=planning_result,
            ):
                plan = agent.run_planning_phase("Build a library")

            assert "plan" in plan
            assert "criteria" in plan

            # Test work session
            mock_query.return_value = work_result
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value=work_result,
            ):
                work = agent.run_work_session("Implement feature")

            assert work["success"] is True

            # Test verification
            mock_query.return_value = verification_result
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value=verification_result,
            ):
                verification = agent.verify_success_criteria("All tests pass")

            assert verification["success"] is True

    def test_multiple_work_sessions(self, agent):
        """Test multiple work sessions in sequence."""
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            tasks = ["Task 1", "Task 2", "Task 3"]
            results = []

            for task in tasks:
                mock_query.return_value = f"Completed {task}"
                with patch(
                    "claude_task_master.core.agent_phases.run_async_with_cleanup",
                    return_value=f"Completed {task}",
                ):
                    result = agent.run_work_session(task)
                    results.append(result)

            assert len(results) == 3
            for result in results:
                assert result["success"] is True

    def test_planning_to_multiple_tasks_workflow(self, agent):
        """Test planning phase followed by multiple task executions."""
        planning_result = """## Task List

- [ ] Task A
- [ ] Task B

## Success Criteria

1. All tasks done
"""
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            # Planning phase
            mock_query.return_value = planning_result
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value=planning_result,
            ):
                plan = agent.run_planning_phase("Complete project")

            # Parse tasks from plan
            assert "Task A" in plan["plan"]
            assert "Task B" in plan["plan"]

            # Execute tasks
            mock_query.return_value = "Task completed"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="Task completed",
            ):
                work_a = agent.run_work_session("Task A")
                work_b = agent.run_work_session("Task B")

            assert work_a["success"] is True
            assert work_b["success"] is True


# =============================================================================
# AgentWrapper Phase Edge Cases Tests
# =============================================================================


class TestAgentWrapperPhaseEdgeCases:
    """Edge case tests for AgentWrapper phases."""

    @pytest.fixture
    def agent(self, temp_dir):
        """Create an AgentWrapper instance for testing."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
            )
        return agent

    def test_empty_goal_planning(self, agent):
        """Test planning with empty goal."""
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "## Task List\n- [ ] Task"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="## Task List\n- [ ] Task",
            ):
                result = agent.run_planning_phase("")

        assert result is not None

    def test_empty_task_description_work_session(self, agent):
        """Test work session with empty task description."""
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup", return_value="Done"
            ):
                result = agent.run_work_session("")

        assert result["success"] is True

    def test_very_long_goal(self, agent):
        """Test planning with very long goal."""
        long_goal = "A" * 10000
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "## Task List\n- [ ] Task"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="## Task List\n- [ ] Task",
            ):
                result = agent.run_planning_phase(long_goal)

        assert result is not None

    def test_special_characters_in_task(self, agent):
        """Test work session with special characters."""
        task = "Implement <feature> with 'quotes' and \"double quotes\" & special chars @#$%"
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup", return_value="Done"
            ):
                result = agent.run_work_session(task)

        assert result["success"] is True

    def test_unicode_in_context(self, agent):
        """Test with unicode characters in context."""
        context = "Context with unicode: \u65e5\u672c\u8a9e, emoji \U0001f680, and symbols \u2660\u2663\u2665\u2666"
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup", return_value="Done"
            ):
                result = agent.run_work_session("Task", context=context)

        assert result["success"] is True

    def test_multiline_pr_comments(self, agent):
        """Test work session with multiline PR comments."""
        pr_comments = """Line 1: Fix this error
Line 2: Add error handling
Line 3: Update documentation

Also consider:
- Adding tests
- Improving coverage
"""
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup", return_value="Done"
            ):
                result = agent.run_work_session("Task", pr_comments=pr_comments)

        assert result["success"] is True

    def test_verification_with_lowercase_success(self, agent):
        """Test verification detects lowercase 'success'."""
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "The implementation is a success."
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="The implementation is a success.",
            ):
                result = agent.verify_success_criteria("Tests pass")

        assert result["success"] is True

    def test_verification_with_uppercase_criteria_met(self, agent):
        """Test verification detects 'ALL CRITERIA MET'."""
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "All Criteria Met successfully"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="All Criteria Met successfully",
            ):
                result = agent.verify_success_criteria("Tests pass")

        # Note: the check is case-insensitive because of .lower()
        assert result["success"] is True

    def test_empty_criteria_verification(self, agent):
        """Test verification with empty criteria."""
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "All criteria met"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="All criteria met",
            ):
                result = agent.verify_success_criteria("")

        assert result is not None

    def test_very_long_criteria(self, agent):
        """Test verification with very long criteria."""
        long_criteria = "Criterion: " + "x" * 5000
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "All criteria met"
            with patch(
                "claude_task_master.core.agent_phases.run_async_with_cleanup",
                return_value="All criteria met",
            ):
                result = agent.verify_success_criteria(long_criteria)

        assert result is not None
        assert result["success"] is True
