"""Tests for AgentWrapper tool configuration and message processing.

This module contains tests for:
- Model name mapping (_get_model_name method)
- Custom rate limit configuration
- Message processing edge cases
- Integration tests for tool usage
- Phase tool restrictions
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_task_master.core.agent import AgentWrapper, ModelType, ToolConfig
from claude_task_master.core.rate_limit import RateLimitConfig

# =============================================================================
# AgentWrapper Model Name Tests
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
        assert agent._get_model_name() == "claude-sonnet-4-5-20250929"

    def test_opus_model_name(self, mock_sdk):
        """Test OPUS model name mapping."""
        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.OPUS,
            )
        assert agent._get_model_name() == "claude-opus-4-5-20251101"

    def test_haiku_model_name(self, mock_sdk):
        """Test HAIKU model name mapping."""
        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.HAIKU,
            )
        assert agent._get_model_name() == "claude-haiku-4-5-20251001"

    def test_model_name_contains_claude(self, mock_sdk):
        """Test all model names contain 'claude'."""
        for model_type in ModelType:
            with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
                agent = AgentWrapper(
                    access_token="test-token",
                    model=model_type,
                )
            model_name = agent._get_model_name()
            assert "claude" in model_name

    def test_model_name_contains_model_type(self, mock_sdk):
        """Test model names contain the model type identifier."""
        model_identifiers = {
            ModelType.SONNET: "sonnet",
            ModelType.OPUS: "opus",
            ModelType.HAIKU: "haiku",
        }

        for model_type, identifier in model_identifiers.items():
            with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
                agent = AgentWrapper(
                    access_token="test-token",
                    model=model_type,
                )
            model_name = agent._get_model_name()
            assert identifier in model_name


# =============================================================================
# AgentWrapper Custom Configuration Tests
# =============================================================================


class TestAgentWrapperCustomConfiguration:
    """Tests for custom retry and backoff configuration."""

    def test_custom_rate_limit_config(self):
        """Test initialization with custom RateLimitConfig."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        rate_limit_config = RateLimitConfig(max_retries=5)

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                rate_limit_config=rate_limit_config,
            )

        assert agent.rate_limit_config.max_retries == 5

    def test_custom_initial_backoff(self):
        """Test initialization with custom initial_backoff."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        rate_limit_config = RateLimitConfig(initial_backoff=2.0)

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                rate_limit_config=rate_limit_config,
            )

        assert agent.rate_limit_config.initial_backoff == 2.0

    def test_custom_max_backoff(self):
        """Test initialization with custom max_backoff."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        rate_limit_config = RateLimitConfig(max_backoff=60.0)

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                rate_limit_config=rate_limit_config,
            )

        assert agent.rate_limit_config.max_backoff == 60.0

    def test_aggressive_rate_limit_config(self):
        """Test initialization with aggressive rate limiting."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        rate_limit_config = RateLimitConfig.aggressive()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                rate_limit_config=rate_limit_config,
            )

        assert agent.rate_limit_config == rate_limit_config
        assert agent.rate_limit_config.max_retries == 5

    def test_all_custom_config_options(self):
        """Test initialization with all custom configuration options."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        rate_limit_config = RateLimitConfig(
            max_retries=10,
            initial_backoff=0.5,
            max_backoff=120.0,
            backoff_multiplier=3.0,
        )

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.OPUS,
                working_dir="/custom/path",
                rate_limit_config=rate_limit_config,
            )

        assert agent.model == ModelType.OPUS
        assert agent.working_dir == "/custom/path"
        assert agent.rate_limit_config.max_retries == 10
        assert agent.rate_limit_config.initial_backoff == 0.5
        assert agent.rate_limit_config.max_backoff == 120.0
        assert agent.rate_limit_config.backoff_multiplier == 3.0


# =============================================================================
# Message Processing Edge Cases Tests
# =============================================================================


class TestMessageProcessingEdgeCases:
    """Edge case tests for message processing."""

    @pytest.fixture
    def agent(self, temp_dir):
        """Create an AgentWrapper instance for testing."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            return AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
            )

    def test_process_message_empty_content_list(self, agent):
        """Test processing message with empty content list."""
        mock_message = MagicMock()
        mock_message.content = []

        result = agent._message_processor.process_message(mock_message, "Previous")

        assert result == "Previous"

    def test_process_message_mixed_block_types(self, agent, capsys):
        """Test processing message with mixed block types."""
        text_block = MagicMock()
        type(text_block).__name__ = "TextBlock"
        text_block.text = "Some text"

        tool_block = MagicMock()
        type(tool_block).__name__ = "ToolUseBlock"
        tool_block.name = "Read"

        mock_message = MagicMock()
        mock_message.content = [text_block, tool_block]

        result = agent._message_processor.process_message(mock_message, "")

        assert "Some text" in result
        captured = capsys.readouterr()
        assert "Using tool: Read" in captured.out

    def test_process_message_multiple_text_blocks(self, agent):
        """Test processing multiple TextBlock messages."""
        blocks = []
        for i in range(3):
            text_block = MagicMock()
            type(text_block).__name__ = "TextBlock"
            text_block.text = f"Part {i}"
            blocks.append(text_block)

        mock_message = MagicMock()
        mock_message.content = blocks

        result = agent._message_processor.process_message(mock_message, "")

        assert "Part 0Part 1Part 2" in result

    def test_process_message_unicode_text(self, agent):
        """Test processing message with unicode text."""
        text_block = MagicMock()
        type(text_block).__name__ = "TextBlock"
        text_block.text = "Unicode: \u65e5\u672c\u8a9e \U0001f680 \u2661"

        mock_message = MagicMock()
        mock_message.content = [text_block]

        result = agent._message_processor.process_message(mock_message, "")

        assert "\u65e5\u672c\u8a9e" in result
        assert "\U0001f680" in result

    def test_process_message_long_text(self, agent):
        """Test processing message with very long text."""
        long_text = "A" * 100000
        text_block = MagicMock()
        type(text_block).__name__ = "TextBlock"
        text_block.text = long_text

        mock_message = MagicMock()
        mock_message.content = [text_block]

        result = agent._message_processor.process_message(mock_message, "")

        assert len(result) == 100000

    def test_process_message_tool_result_success(self, agent, capsys):
        """Test processing ToolResultBlock with success."""
        success_block = MagicMock()
        type(success_block).__name__ = "ToolResultBlock"
        success_block.is_error = False

        mock_message = MagicMock()
        mock_message.content = [success_block]

        agent._message_processor.process_message(mock_message, "")
        captured = capsys.readouterr()
        assert "Tool completed" in captured.out

    def test_process_message_tool_result_error(self, agent, capsys):
        """Test processing ToolResultBlock with error."""
        error_block = MagicMock()
        type(error_block).__name__ = "ToolResultBlock"
        error_block.is_error = True

        mock_message = MagicMock()
        mock_message.content = [error_block]

        agent._message_processor.process_message(mock_message, "")
        captured = capsys.readouterr()
        assert "Tool error" in captured.out

    def test_process_message_unknown_block_type(self, agent):
        """Test processing unknown block type is handled gracefully."""
        unknown_block = MagicMock()
        type(unknown_block).__name__ = "UnknownBlock"

        mock_message = MagicMock()
        mock_message.content = [unknown_block]

        # Should not raise
        result = agent._message_processor.process_message(mock_message, "Previous")
        assert result == "Previous"

    def test_process_message_result_message_replaces_text(self, agent):
        """Test ResultMessage replaces accumulated text."""
        result_message = MagicMock()
        type(result_message).__name__ = "ResultMessage"
        result_message.result = "Final result"
        result_message.content = None

        result = agent._message_processor.process_message(result_message, "Should be replaced")

        assert result == "Final result"
        assert "Should be replaced" not in result

    def test_process_message_result_message_with_none_result(self, agent):
        """Test ResultMessage with None result overwrites accumulated text.

        Note: The implementation assigns message.result directly to result_text,
        so if result is None, the returned value will be None. This is the
        actual behavior of process_message.
        """
        result_message = MagicMock()
        type(result_message).__name__ = "ResultMessage"
        result_message.result = None
        result_message.content = None

        result = agent._message_processor.process_message(result_message, "Previous text")

        # When result is None, the implementation returns None
        assert result is None


# =============================================================================
# Tool Usage Integration Tests
# =============================================================================


class TestToolUsageIntegration:
    """Integration tests for tool usage across phases."""

    @pytest.fixture
    def agent(self, temp_dir):
        """Create an AgentWrapper instance for testing."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            return AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
            )

    @pytest.mark.asyncio
    async def test_options_created_with_correct_tools(self, agent):
        """Test query options are created with correct tools for phase."""
        options_calls = []

        def capture_options(**kwargs):
            options_calls.append(kwargs)
            return MagicMock()

        agent.options_class = capture_options
        agent._query_executor.options_class = capture_options

        async def mock_query_gen(*args, **kwargs):
            yield MagicMock(content=None)

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        # Test with planning tools
        planning_tools = ToolConfig.PLANNING.value
        await agent._run_query("test prompt", planning_tools)

        assert len(options_calls) == 1
        assert options_calls[0]["allowed_tools"] == planning_tools

    @pytest.mark.asyncio
    async def test_permission_mode_bypass(self, agent):
        """Test permission mode is set to bypassPermissions."""
        options_calls = []

        def capture_options(**kwargs):
            options_calls.append(kwargs)
            return MagicMock()

        agent.options_class = capture_options
        agent._query_executor.options_class = capture_options

        async def mock_query_gen(*args, **kwargs):
            yield MagicMock(content=None)

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        await agent._run_query("test prompt", ["Read"])

        assert options_calls[0]["permission_mode"] == "bypassPermissions"

    @pytest.mark.asyncio
    async def test_multiple_tool_uses_in_single_query(self, agent, capsys):
        """Test handling multiple tool uses in a single query."""
        # Create multiple tool use blocks
        tool_blocks = []
        for tool_name in ["Read", "Glob", "Grep"]:
            tool_block = MagicMock()
            type(tool_block).__name__ = "ToolUseBlock"
            tool_block.name = tool_name
            tool_blocks.append(tool_block)

        mock_message = MagicMock()
        mock_message.content = tool_blocks

        async def mock_query_gen(*args, **kwargs):
            yield mock_message

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        await agent._run_query("test prompt", ["Read", "Glob", "Grep"])

        captured = capsys.readouterr()
        assert "Using tool: Read" in captured.out
        assert "Using tool: Glob" in captured.out
        assert "Using tool: Grep" in captured.out

    @pytest.mark.asyncio
    async def test_tool_sequence_read_then_result(self, agent, capsys):
        """Test a typical sequence: tool use, tool result, then text result."""
        # First message: tool use
        tool_use = MagicMock()
        type(tool_use).__name__ = "ToolUseBlock"
        tool_use.name = "Read"
        msg1 = MagicMock()
        msg1.content = [tool_use]

        # Second message: tool result
        tool_result = MagicMock()
        type(tool_result).__name__ = "ToolResultBlock"
        tool_result.is_error = False
        msg2 = MagicMock()
        msg2.content = [tool_result]

        # Third message: text response
        text_block = MagicMock()
        type(text_block).__name__ = "TextBlock"
        text_block.text = "File content processed"
        msg3 = MagicMock()
        msg3.content = [text_block]

        # Final message: result
        result_msg = MagicMock()
        type(result_msg).__name__ = "ResultMessage"
        result_msg.result = "Analysis complete"
        result_msg.content = None

        async def mock_query_gen(*args, **kwargs):
            yield msg1
            yield msg2
            yield msg3
            yield result_msg

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        result = await agent._run_query("test prompt", ["Read"])

        assert result == "Analysis complete"
        captured = capsys.readouterr()
        assert "Using tool: Read" in captured.out
        assert "Tool completed" in captured.out


# =============================================================================
# Phase Tool Restriction Tests
# =============================================================================


class TestPhaseToolRestrictions:
    """Tests to verify tool restrictions are correctly enforced per phase."""

    @pytest.fixture
    def agent(self, temp_dir):
        """Create an AgentWrapper instance for testing."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            return AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
            )

    def test_planning_phase_no_write_tools(self, agent):
        """Verify planning phase cannot use Write or Edit."""
        tools = agent.get_tools_for_phase("planning")
        write_tools = {"Write", "Edit"}
        used_write_tools = set(tools) & write_tools
        assert len(used_write_tools) == 0, f"Planning phase has write tools: {used_write_tools}"

    def test_verification_phase_can_run_commands(self, agent):
        """Verify verification phase can run Bash commands (for tests)."""
        tools = agent.get_tools_for_phase("verification")
        assert "Bash" in tools

    def test_verification_phase_cannot_modify(self, agent):
        """Verify verification phase cannot modify files."""
        tools = agent.get_tools_for_phase("verification")
        modify_tools = {"Write", "Edit"}
        used_modify_tools = set(tools) & modify_tools
        assert len(used_modify_tools) == 0

    def test_working_phase_has_all_tools(self, agent):
        """Verify working phase has superset of all other phase tools."""
        working_tools = set(agent.get_tools_for_phase("working"))
        planning_tools = set(agent.get_tools_for_phase("planning"))
        verification_tools = set(agent.get_tools_for_phase("verification"))

        assert planning_tools.issubset(working_tools)
        assert verification_tools.issubset(working_tools)

    def test_working_phase_exclusive_tools(self, agent):
        """Verify working phase has tools not in other phases."""
        working_tools = set(agent.get_tools_for_phase("working"))
        planning_tools = set(agent.get_tools_for_phase("planning"))
        verification_tools = set(agent.get_tools_for_phase("verification"))

        # These tools should only be in working phase
        exclusive_tools = {"Write", "Edit", "Task", "TodoWrite", "WebSearch", "WebFetch", "Skill"}

        for tool in exclusive_tools:
            assert tool in working_tools
            assert tool not in planning_tools
            assert tool not in verification_tools

    def test_case_sensitive_phase_matching(self, agent):
        """Test phase matching is case-sensitive (lowercase expected)."""
        # These should NOT match the defined phases
        tools_upper = agent.get_tools_for_phase("PLANNING")
        tools_mixed = agent.get_tools_for_phase("Planning")

        # Should fall back to WORKING tools
        assert tools_upper == ToolConfig.WORKING.value
        assert tools_mixed == ToolConfig.WORKING.value
