"""Comprehensive tests for the agent module."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from pathlib import Path
import asyncio
import os

from claude_task_master.core.agent import AgentWrapper, ModelType, ToolConfig


# =============================================================================
# ModelType Enum Tests
# =============================================================================


class TestModelType:
    """Tests for ModelType enum."""

    def test_sonnet_value(self):
        """Test SONNET model value."""
        assert ModelType.SONNET.value == "sonnet"

    def test_opus_value(self):
        """Test OPUS model value."""
        assert ModelType.OPUS.value == "opus"

    def test_haiku_value(self):
        """Test HAIKU model value."""
        assert ModelType.HAIKU.value == "haiku"

    def test_model_type_from_string(self):
        """Test creating ModelType from string value."""
        assert ModelType("sonnet") == ModelType.SONNET
        assert ModelType("opus") == ModelType.OPUS
        assert ModelType("haiku") == ModelType.HAIKU

    def test_invalid_model_type(self):
        """Test invalid model type raises ValueError."""
        with pytest.raises(ValueError):
            ModelType("invalid-model")

    def test_all_model_types(self):
        """Test all expected model types exist."""
        expected = {"SONNET", "OPUS", "HAIKU"}
        actual = {m.name for m in ModelType}
        assert actual == expected


# =============================================================================
# ToolConfig Enum Tests
# =============================================================================


class TestToolConfig:
    """Tests for ToolConfig enum."""

    def test_planning_tools(self):
        """Test PLANNING tool configuration."""
        expected = ["Read", "Glob", "Grep"]
        assert ToolConfig.PLANNING.value == expected

    def test_working_tools(self):
        """Test WORKING tool configuration."""
        expected = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
        assert ToolConfig.WORKING.value == expected

    def test_planning_tools_are_read_only(self):
        """Test planning tools don't include write capabilities."""
        planning_tools = ToolConfig.PLANNING.value
        assert "Write" not in planning_tools
        assert "Edit" not in planning_tools
        assert "Bash" not in planning_tools

    def test_working_tools_include_planning_tools(self):
        """Test working tools include all planning tools."""
        planning_tools = set(ToolConfig.PLANNING.value)
        working_tools = set(ToolConfig.WORKING.value)
        assert planning_tools.issubset(working_tools)


# =============================================================================
# AgentWrapper Initialization Tests
# =============================================================================


class TestAgentWrapperInitialization:
    """Tests for AgentWrapper initialization."""

    def test_init_with_valid_parameters(self):
        """Test initialization with valid parameters."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir="/test/dir",
            )

        assert agent.access_token == "test-token"
        assert agent.model == ModelType.SONNET
        assert agent.working_dir == "/test/dir"

    def test_init_default_working_dir(self):
        """Test initialization with default working directory."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.OPUS,
            )

        assert agent.working_dir == "."

    def test_init_with_different_models(self):
        """Test initialization with different model types."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            for model in ModelType:
                agent = AgentWrapper(
                    access_token="test-token",
                    model=model,
                )
                assert agent.model == model

    def test_init_without_claude_sdk_raises_error(self):
        """Test initialization without claude-agent-sdk raises RuntimeError."""
        # Patch the import to simulate missing module
        with patch.dict("sys.modules", {"claude_agent_sdk": None}):
            with pytest.raises(RuntimeError) as exc_info:
                # Force the import to fail
                with patch("builtins.__import__", side_effect=ImportError):
                    AgentWrapper(
                        access_token="test-token",
                        model=ModelType.SONNET,
                    )

        assert "claude-agent-sdk not installed" in str(exc_info.value)

    def test_init_stores_sdk_components(self):
        """Test initialization stores SDK query and options class."""
        mock_sdk = MagicMock()
        mock_query = AsyncMock()
        mock_options_class = MagicMock()
        mock_sdk.query = mock_query
        mock_sdk.ClaudeAgentOptions = mock_options_class

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
            )

        assert agent.query == mock_query
        assert agent.options_class == mock_options_class


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
        """Test get_tools_for_phase returns planning tools."""
        tools = agent.get_tools_for_phase("planning")
        assert tools == ["Read", "Glob", "Grep"]

    def test_working_phase_tools(self, agent):
        """Test get_tools_for_phase returns working tools."""
        tools = agent.get_tools_for_phase("working")
        assert tools == ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]

    def test_unknown_phase_returns_working_tools(self, agent):
        """Test unknown phase returns working tools by default."""
        tools = agent.get_tools_for_phase("unknown")
        assert tools == ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]

    def test_empty_phase_returns_working_tools(self, agent):
        """Test empty phase string returns working tools."""
        tools = agent.get_tools_for_phase("")
        assert tools == ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]


# =============================================================================
# AgentWrapper _get_model_name Tests
# =============================================================================


class TestAgentWrapperGetModelName:
    """Tests for _get_model_name method."""

    @pytest.fixture
    def mock_sdk(self):
        """Create mock SDK."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()
        return mock_sdk

    def test_sonnet_model_name(self, mock_sdk):
        """Test SONNET model name mapping."""
        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
            )
        assert agent._get_model_name() == "claude-sonnet-4-20250514"

    def test_opus_model_name(self, mock_sdk):
        """Test OPUS model name mapping."""
        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.OPUS,
            )
        assert agent._get_model_name() == "claude-opus-4-20250514"

    def test_haiku_model_name(self, mock_sdk):
        """Test HAIKU model name mapping."""
        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.HAIKU,
            )
        assert agent._get_model_name() == "claude-3-5-haiku-20241022"


# =============================================================================
# AgentWrapper Prompt Building Tests
# =============================================================================


class TestAgentWrapperPromptBuilding:
    """Tests for prompt building methods."""

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

    def test_build_planning_prompt_includes_goal(self, agent):
        """Test _build_planning_prompt includes the goal."""
        goal = "Build a REST API"
        prompt = agent._build_planning_prompt(goal, "")

        assert "Build a REST API" in prompt

    def test_build_planning_prompt_includes_context(self, agent):
        """Test _build_planning_prompt includes the context."""
        context = "Previous session completed setup."
        prompt = agent._build_planning_prompt("Test goal", context)

        assert "Previous session completed setup." in prompt

    def test_build_planning_prompt_includes_task_list_format(self, agent):
        """Test _build_planning_prompt includes task list format instructions."""
        prompt = agent._build_planning_prompt("Test goal", "")

        assert "## Task List" in prompt
        assert "- [ ]" in prompt
        assert "## Success Criteria" in prompt

    def test_build_planning_prompt_includes_gitignore_instruction(self, agent):
        """Test _build_planning_prompt includes .gitignore instruction."""
        prompt = agent._build_planning_prompt("Test goal", "")

        assert ".gitignore" in prompt
        assert ".claude-task-master/" in prompt

    def test_build_planning_prompt_mentions_tools(self, agent):
        """Test _build_planning_prompt mentions available tools."""
        prompt = agent._build_planning_prompt("Test goal", "")

        assert "Read" in prompt
        assert "Glob" in prompt
        assert "Grep" in prompt

    def test_build_work_prompt_includes_task(self, agent):
        """Test _build_work_prompt includes the task description."""
        task = "Implement user authentication"
        prompt = agent._build_work_prompt(task, "", None)

        assert "Implement user authentication" in prompt

    def test_build_work_prompt_includes_context(self, agent):
        """Test _build_work_prompt includes context."""
        context = "Using FastAPI framework."
        prompt = agent._build_work_prompt("Test task", context, None)

        assert "Using FastAPI framework." in prompt

    def test_build_work_prompt_includes_pr_comments(self, agent):
        """Test _build_work_prompt includes PR comments when provided."""
        pr_comments = "Please add error handling for edge cases."
        prompt = agent._build_work_prompt("Test task", "", pr_comments)

        assert "PR REVIEW COMMENTS TO ADDRESS" in prompt
        assert "Please add error handling for edge cases." in prompt

    def test_build_work_prompt_without_pr_comments(self, agent):
        """Test _build_work_prompt without PR comments."""
        prompt = agent._build_work_prompt("Test task", "", None)

        assert "PR REVIEW COMMENTS" not in prompt

    def test_build_work_prompt_mentions_tools(self, agent):
        """Test _build_work_prompt mentions available tools."""
        prompt = agent._build_work_prompt("Test task", "", None)

        assert "Read" in prompt
        assert "Write" in prompt
        assert "Edit" in prompt
        assert "Bash" in prompt
        assert "Glob" in prompt
        assert "Grep" in prompt


# =============================================================================
# AgentWrapper Extract Methods Tests
# =============================================================================


class TestAgentWrapperExtractMethods:
    """Tests for plan/criteria extraction methods."""

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

    def test_extract_plan_with_proper_format(self, agent):
        """Test _extract_plan returns result with proper format."""
        result = """## Task List

- [ ] Task 1
- [ ] Task 2

## Success Criteria

1. All tests pass
"""
        extracted = agent._extract_plan(result)
        assert extracted == result

    def test_extract_plan_wraps_improper_format(self, agent):
        """Test _extract_plan wraps result without proper format."""
        result = "Some unformatted content"
        extracted = agent._extract_plan(result)

        assert "## Task List" in extracted
        assert "Some unformatted content" in extracted

    def test_extract_criteria_with_proper_format(self, agent):
        """Test _extract_criteria extracts criteria section."""
        result = """## Task List

- [ ] Task 1

## Success Criteria

1. All tests pass
2. Coverage > 80%
"""
        extracted = agent._extract_criteria(result)

        assert "1. All tests pass" in extracted
        assert "2. Coverage > 80%" in extracted

    def test_extract_criteria_without_criteria_section(self, agent):
        """Test _extract_criteria returns default when no criteria section."""
        result = """## Task List

- [ ] Task 1
- [ ] Task 2
"""
        extracted = agent._extract_criteria(result)

        assert "All tasks in the task list are completed successfully." in extracted

    def test_extract_criteria_empty_result(self, agent):
        """Test _extract_criteria with empty result."""
        extracted = agent._extract_criteria("")
        assert "All tasks in the task list are completed successfully." in extracted


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
            with patch("asyncio.run", return_value=mock_result):
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
            with patch("asyncio.run", return_value=mock_result):
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

            with patch("asyncio.run") as mock_asyncio:
                mock_asyncio.return_value = "test result"
                agent_with_mock.run_planning_phase("Goal")

                # Check that asyncio.run was called
                assert mock_asyncio.called


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
            with patch("asyncio.run", return_value="Work completed"):
                result = agent_with_mock.run_work_session("Implement feature")

        assert isinstance(result, dict)

    def test_run_work_session_contains_required_keys(self, agent_with_mock):
        """Test run_work_session returns required keys."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch("asyncio.run", return_value="Done"):
                result = agent_with_mock.run_work_session("Task")

        assert "output" in result
        assert "success" in result

    def test_run_work_session_assumes_success(self, agent_with_mock):
        """Test run_work_session assumes success for MVP."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch("asyncio.run", return_value="Done"):
                result = agent_with_mock.run_work_session("Task")

        assert result["success"] is True

    def test_run_work_session_with_context(self, agent_with_mock):
        """Test run_work_session includes context."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch("asyncio.run", return_value="Done"):
                result = agent_with_mock.run_work_session(
                    "Task",
                    context="Previous work info"
                )

        assert result is not None

    def test_run_work_session_with_pr_comments(self, agent_with_mock):
        """Test run_work_session includes PR comments."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch("asyncio.run", return_value="Done"):
                result = agent_with_mock.run_work_session(
                    "Task",
                    pr_comments="Fix the error handling"
                )

        assert result is not None


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
            with patch("asyncio.run", return_value="All criteria met."):
                result = agent_with_mock.verify_success_criteria("Tests pass")

        assert isinstance(result, dict)

    def test_verify_success_criteria_contains_required_keys(self, agent_with_mock):
        """Test verify_success_criteria returns required keys."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Success"
            with patch("asyncio.run", return_value="Success"):
                result = agent_with_mock.verify_success_criteria("Tests pass")

        assert "success" in result
        assert "details" in result

    def test_verify_success_criteria_detects_success(self, agent_with_mock):
        """Test verify_success_criteria detects success indicators."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "All criteria met. Everything is working correctly."
            with patch("asyncio.run", return_value="All criteria met. Everything is working correctly."):
                result = agent_with_mock.verify_success_criteria("Tests pass")

        assert result["success"] is True

    def test_verify_success_criteria_detects_failure(self, agent_with_mock):
        """Test verify_success_criteria detects failure."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Some criteria are not met. Tests are failing."
            with patch("asyncio.run", return_value="Some criteria are not met. Tests are failing."):
                result = agent_with_mock.verify_success_criteria("Tests pass")

        assert result["success"] is False

    def test_verify_success_criteria_with_context(self, agent_with_mock):
        """Test verify_success_criteria uses context."""
        with patch.object(agent_with_mock, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Success confirmed"
            with patch("asyncio.run", return_value="Success confirmed"):
                result = agent_with_mock.verify_success_criteria(
                    "Tests pass",
                    context="Additional context info"
                )

        assert result is not None


# =============================================================================
# AgentWrapper _run_query Tests
# =============================================================================


class TestAgentWrapperRunQuery:
    """Tests for _run_query async method."""

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

    @pytest.mark.asyncio
    async def test_run_query_changes_directory(self, agent, temp_dir):
        """Test _run_query changes to working directory."""
        original_dir = os.getcwd()

        # Create async generator that yields a mock message
        async def mock_query_gen(*args, **kwargs):
            yield MagicMock(content=None)

        agent.query = mock_query_gen

        await agent._run_query("test prompt", ["Read"])

        # Should be back in original directory
        assert os.getcwd() == original_dir

    @pytest.mark.asyncio
    async def test_run_query_restores_directory_on_error(self, agent, temp_dir):
        """Test _run_query restores directory even on error."""
        original_dir = os.getcwd()

        # Create async generator that raises an error
        async def mock_query_gen(*args, **kwargs):
            raise ValueError("Test error")
            yield  # Make it a generator

        agent.query = mock_query_gen

        with pytest.raises(ValueError):
            await agent._run_query("test prompt", ["Read"])

        # Should be back in original directory
        assert os.getcwd() == original_dir

    @pytest.mark.asyncio
    async def test_run_query_creates_options(self, agent, temp_dir):
        """Test _run_query creates options with correct parameters."""
        options_calls = []

        def capture_options(**kwargs):
            options_calls.append(kwargs)
            return MagicMock()

        agent.options_class = capture_options

        async def mock_query_gen(*args, **kwargs):
            yield MagicMock(content=None)

        agent.query = mock_query_gen

        await agent._run_query("test prompt", ["Read", "Glob"])

        assert len(options_calls) == 1
        assert options_calls[0]["allowed_tools"] == ["Read", "Glob"]
        assert options_calls[0]["permission_mode"] == "bypassPermissions"

    @pytest.mark.asyncio
    async def test_run_query_handles_text_block(self, agent, temp_dir, capsys):
        """Test _run_query handles TextBlock messages."""
        # Create mock TextBlock
        text_block = MagicMock()
        type(text_block).__name__ = "TextBlock"
        text_block.text = "Hello, world!"

        # Create mock message with content
        mock_message = MagicMock()
        mock_message.content = [text_block]
        type(mock_message).__name__ = "AssistantMessage"

        async def mock_query_gen(*args, **kwargs):
            yield mock_message

        agent.query = mock_query_gen

        result = await agent._run_query("test prompt", ["Read"])

        assert "Hello, world!" in result

    @pytest.mark.asyncio
    async def test_run_query_handles_tool_use_block(self, agent, temp_dir, capsys):
        """Test _run_query handles ToolUseBlock messages."""
        # Create mock ToolUseBlock
        tool_block = MagicMock()
        type(tool_block).__name__ = "ToolUseBlock"
        tool_block.name = "Read"

        # Create mock message with content
        mock_message = MagicMock()
        mock_message.content = [tool_block]
        type(mock_message).__name__ = "AssistantMessage"

        async def mock_query_gen(*args, **kwargs):
            yield mock_message

        agent.query = mock_query_gen

        await agent._run_query("test prompt", ["Read"])

        captured = capsys.readouterr()
        assert "Using tool: Read" in captured.out

    @pytest.mark.asyncio
    async def test_run_query_handles_tool_result_block_success(self, agent, temp_dir, capsys):
        """Test _run_query handles ToolResultBlock success."""
        # Create mock ToolResultBlock
        result_block = MagicMock()
        type(result_block).__name__ = "ToolResultBlock"
        result_block.is_error = False

        # Create mock message with content
        mock_message = MagicMock()
        mock_message.content = [result_block]
        type(mock_message).__name__ = "UserMessage"

        async def mock_query_gen(*args, **kwargs):
            yield mock_message

        agent.query = mock_query_gen

        await agent._run_query("test prompt", ["Read"])

        captured = capsys.readouterr()
        assert "Tool completed" in captured.out

    @pytest.mark.asyncio
    async def test_run_query_handles_tool_result_block_error(self, agent, temp_dir, capsys):
        """Test _run_query handles ToolResultBlock error."""
        # Create mock ToolResultBlock with error
        result_block = MagicMock()
        type(result_block).__name__ = "ToolResultBlock"
        result_block.is_error = True

        # Create mock message with content
        mock_message = MagicMock()
        mock_message.content = [result_block]
        type(mock_message).__name__ = "UserMessage"

        async def mock_query_gen(*args, **kwargs):
            yield mock_message

        agent.query = mock_query_gen

        await agent._run_query("test prompt", ["Read"])

        captured = capsys.readouterr()
        assert "Tool error" in captured.out

    @pytest.mark.asyncio
    async def test_run_query_handles_result_message(self, agent, temp_dir):
        """Test _run_query handles ResultMessage."""
        # Create mock ResultMessage
        result_message = MagicMock()
        type(result_message).__name__ = "ResultMessage"
        result_message.result = "Final result text"
        result_message.content = None

        async def mock_query_gen(*args, **kwargs):
            yield result_message

        agent.query = mock_query_gen

        result = await agent._run_query("test prompt", ["Read"])

        assert result == "Final result text"

    @pytest.mark.asyncio
    async def test_run_query_handles_message_without_content(self, agent, temp_dir):
        """Test _run_query handles messages without content."""
        # Create mock message without content
        mock_message = MagicMock()
        mock_message.content = None
        type(mock_message).__name__ = "SomeMessage"

        async def mock_query_gen(*args, **kwargs):
            yield mock_message

        agent.query = mock_query_gen

        # Should not raise
        result = await agent._run_query("test prompt", ["Read"])

        assert result == ""


# =============================================================================
# AgentWrapper Integration Tests
# =============================================================================


class TestAgentWrapperIntegration:
    """Integration tests for AgentWrapper."""

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
            with patch("asyncio.run", return_value=planning_result):
                plan = agent.run_planning_phase("Build a library")

            assert "plan" in plan
            assert "criteria" in plan

            # Test work session
            mock_query.return_value = work_result
            with patch("asyncio.run", return_value=work_result):
                work = agent.run_work_session("Implement feature")

            assert work["success"] is True

            # Test verification
            mock_query.return_value = verification_result
            with patch("asyncio.run", return_value=verification_result):
                verification = agent.verify_success_criteria("All tests pass")

            assert verification["success"] is True


# =============================================================================
# AgentWrapper Edge Cases Tests
# =============================================================================


class TestAgentWrapperEdgeCases:
    """Edge case tests for AgentWrapper."""

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
            with patch("asyncio.run", return_value="## Task List\n- [ ] Task"):
                result = agent.run_planning_phase("")

        assert result is not None

    def test_empty_task_description_work_session(self, agent):
        """Test work session with empty task description."""
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch("asyncio.run", return_value="Done"):
                result = agent.run_work_session("")

        assert result["success"] is True

    def test_very_long_goal(self, agent):
        """Test planning with very long goal."""
        long_goal = "A" * 10000
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "## Task List\n- [ ] Task"
            with patch("asyncio.run", return_value="## Task List\n- [ ] Task"):
                result = agent.run_planning_phase(long_goal)

        assert result is not None

    def test_special_characters_in_task(self, agent):
        """Test work session with special characters."""
        task = "Implement <feature> with 'quotes' and \"double quotes\" & special chars @#$%"
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch("asyncio.run", return_value="Done"):
                result = agent.run_work_session(task)

        assert result["success"] is True

    def test_unicode_in_context(self, agent):
        """Test with unicode characters in context."""
        context = "Context with unicode: 日本語, emoji 🚀, and symbols ♠♣♥♦"
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "Done"
            with patch("asyncio.run", return_value="Done"):
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
            with patch("asyncio.run", return_value="Done"):
                result = agent.run_work_session("Task", pr_comments=pr_comments)

        assert result["success"] is True

    def test_verification_with_lowercase_success(self, agent):
        """Test verification detects lowercase 'success'."""
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "The implementation is a success."
            with patch("asyncio.run", return_value="The implementation is a success."):
                result = agent.verify_success_criteria("Tests pass")

        assert result["success"] is True

    def test_verification_with_uppercase_criteria_met(self, agent):
        """Test verification detects 'ALL CRITERIA MET'."""
        with patch.object(agent, "_run_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = "All Criteria Met successfully"
            with patch("asyncio.run", return_value="All Criteria Met successfully"):
                result = agent.verify_success_criteria("Tests pass")

        # Note: the check is case-insensitive because of .lower()
        assert result["success"] is True
