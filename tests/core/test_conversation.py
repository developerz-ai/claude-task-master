"""Tests for conversation module - conversation handling.

This module tests the ConversationManager and ConversationSession classes
which manage multi-turn conversations with the Claude Agent SDK.

Tests cover:
- ConversationError hierarchy
- ModelType constants and MODEL_NAMES mapping
- ConversationManager initialization and configuration
- SDK lazy loading and import handling
- ConversationSession message processing
- Tool detail formatting
- Tool result summary formatting
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_task_master.core.circuit_breaker import CircuitBreakerConfig
from claude_task_master.core.conversation import (
    DEFAULT_TOOLS,
    MODEL_NAMES,
    ConversationError,
    ConversationManager,
    ConversationSession,
    ModelType,
    QueryExecutionError,
    SDKImportError,
)
from claude_task_master.core.rate_limit import RateLimitConfig

# =============================================================================
# Test ConversationError Hierarchy
# =============================================================================


class TestConversationError:
    """Tests for ConversationError base class."""

    def test_error_with_message_only(self):
        """Should create error with message only."""
        error = ConversationError("Something went wrong")
        assert error.message == "Something went wrong"
        assert error.details is None
        assert str(error) == "Something went wrong"

    def test_error_with_message_and_details(self):
        """Should create error with message and details."""
        error = ConversationError("Failed", "More info")
        assert error.message == "Failed"
        assert error.details == "More info"
        assert "Failed" in str(error)
        assert "More info" in str(error)

    def test_format_message_includes_details(self):
        """Should format message to include details."""
        error = ConversationError("Error occurred", "Check configuration")
        formatted = error._format_message()
        assert "Error occurred" in formatted
        assert "Details:" in formatted
        assert "Check configuration" in formatted


class TestSDKImportError:
    """Tests for SDKImportError."""

    def test_error_without_original(self):
        """Should create error without original error."""
        error = SDKImportError()
        assert error.original_error is None
        assert "claude-agent-sdk not installed" in error.message
        assert "Install with: pip install" in str(error)

    def test_error_with_original(self):
        """Should capture original error."""
        original = ImportError("Module not found")
        error = SDKImportError(original)
        assert error.original_error is original
        assert error.details is not None
        assert "Module not found" in error.details


class TestQueryExecutionError:
    """Tests for QueryExecutionError."""

    def test_error_without_original(self):
        """Should create error without original error."""
        error = QueryExecutionError("Query failed")
        assert error.message == "Query failed"
        assert error.original_error is None
        assert error.details is None

    def test_error_with_original(self):
        """Should capture original error."""
        original = RuntimeError("Connection lost")
        error = QueryExecutionError("Query failed", original)
        assert error.original_error is original
        assert error.details is not None
        assert "Connection lost" in error.details


# =============================================================================
# Test Model Constants
# =============================================================================


class TestModelConstants:
    """Tests for model type constants."""

    def test_model_type_constants(self):
        """Should have correct model type constants."""
        assert ModelType.SONNET == "sonnet"
        assert ModelType.OPUS == "opus"
        assert ModelType.HAIKU == "haiku"

    def test_model_names_mapping(self):
        """Should have correct model name mapping."""
        assert "sonnet" in MODEL_NAMES
        assert "opus" in MODEL_NAMES
        assert "haiku" in MODEL_NAMES
        # Verify format matches Claude model naming convention
        assert "claude-" in MODEL_NAMES["sonnet"]
        assert "claude-" in MODEL_NAMES["opus"]
        assert "claude-" in MODEL_NAMES["haiku"]

    def test_default_tools(self):
        """Should have expected default tools."""
        expected_tools = [
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
            "Task",
            "TodoWrite",
            "WebSearch",
            "WebFetch",
            "Skill",
        ]
        for tool in expected_tools:
            assert tool in DEFAULT_TOOLS


# =============================================================================
# Test ConversationManager Initialization
# =============================================================================


class TestConversationManagerInit:
    """Tests for ConversationManager initialization."""

    def test_init_basic(self, temp_dir):
        """Should initialize with required arguments."""
        manager = ConversationManager(working_dir=str(temp_dir))
        assert manager.working_dir == str(temp_dir)
        assert manager.model == "sonnet"  # Default
        assert manager.hooks is None
        assert manager.logger is None
        assert manager.verbose is False

    def test_init_with_all_options(self, temp_dir):
        """Should initialize with all options."""
        hooks: Any = {"test": []}
        mock_logger = MagicMock()
        rate_config = RateLimitConfig.default()
        cb_config = CircuitBreakerConfig.default()

        manager = ConversationManager(
            working_dir=str(temp_dir),
            model="opus",
            hooks=hooks,
            logger=mock_logger,
            rate_limit_config=rate_config,
            circuit_breaker_config=cb_config,
            verbose=True,
        )

        assert manager.model == "opus"
        assert manager.hooks is hooks
        assert manager.logger is mock_logger
        assert manager.verbose is True

    def test_init_sdk_not_loaded_yet(self, temp_dir):
        """Should not load SDK on init."""
        manager = ConversationManager(working_dir=str(temp_dir))
        assert manager._sdk_client_class is None
        assert manager._options_class is None

    def test_init_active_group_none(self, temp_dir):
        """Should have no active group on init."""
        manager = ConversationManager(working_dir=str(temp_dir))
        assert manager._active_group is None


# =============================================================================
# Test SDK Import Handling
# =============================================================================


class TestSDKImport:
    """Tests for SDK lazy loading."""

    def test_ensure_sdk_imported_success(self, temp_dir):
        """Should successfully import SDK when available."""
        manager = ConversationManager(working_dir=str(temp_dir))

        mock_sdk = MagicMock()
        mock_sdk.ClaudeSDKClient = MagicMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            manager._ensure_sdk_imported()

        assert manager._sdk_client_class is mock_sdk.ClaudeSDKClient
        assert manager._options_class is mock_sdk.ClaudeAgentOptions

    def test_ensure_sdk_imported_already_loaded(self, temp_dir):
        """Should not re-import if already loaded."""
        manager = ConversationManager(working_dir=str(temp_dir))
        manager._sdk_client_class = MagicMock()
        manager._options_class = MagicMock()

        original_class = manager._sdk_client_class

        # This should be a no-op
        manager._ensure_sdk_imported()

        assert manager._sdk_client_class is original_class

    def test_ensure_sdk_imported_import_error(self, temp_dir):
        """Should raise SDKImportError on ImportError."""
        manager = ConversationManager(working_dir=str(temp_dir))

        with patch.dict("sys.modules"):
            import sys

            # Remove the module if it exists
            if "claude_agent_sdk" in sys.modules:
                del sys.modules["claude_agent_sdk"]

            with patch("builtins.__import__", side_effect=ImportError("No module")):
                with pytest.raises(SDKImportError):
                    manager._ensure_sdk_imported()

    def test_ensure_sdk_imported_attribute_error(self, temp_dir):
        """Should raise ConversationError on missing attribute."""
        manager = ConversationManager(working_dir=str(temp_dir))

        mock_sdk = MagicMock(spec=[])  # Empty spec - no attributes
        del mock_sdk.ClaudeSDKClient  # Ensure attribute doesn't exist

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with pytest.raises(ConversationError) as exc_info:
                manager._ensure_sdk_imported()

            assert "ClaudeSDKClient" in str(exc_info.value)


# =============================================================================
# Test Model Name Resolution
# =============================================================================


class TestGetModelName:
    """Tests for _get_model_name method."""

    def test_get_model_name_default(self, temp_dir):
        """Should return default model name."""
        manager = ConversationManager(working_dir=str(temp_dir), model="sonnet")
        name = manager._get_model_name()
        assert name == MODEL_NAMES["sonnet"]

    def test_get_model_name_override(self, temp_dir):
        """Should use override when provided."""
        manager = ConversationManager(working_dir=str(temp_dir), model="sonnet")
        name = manager._get_model_name("opus")
        assert name == MODEL_NAMES["opus"]

    def test_get_model_name_unknown(self, temp_dir):
        """Should fallback to sonnet for unknown model."""
        manager = ConversationManager(working_dir=str(temp_dir))
        name = manager._get_model_name("unknown-model")
        assert name == MODEL_NAMES["sonnet"]


# =============================================================================
# Test Options Creation
# =============================================================================


class TestCreateOptions:
    """Tests for _create_options method."""

    def test_create_options_basic(self, temp_dir):
        """Should create options with correct settings."""
        manager = ConversationManager(working_dir=str(temp_dir))

        mock_sdk = MagicMock()
        mock_options_class = MagicMock()
        mock_sdk.ClaudeSDKClient = MagicMock()
        mock_sdk.ClaudeAgentOptions = mock_options_class

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with patch(
                "claude_task_master.core.conversation.get_agents_for_working_dir", return_value=None
            ):
                manager._create_options(["Read", "Write"])

        mock_options_class.assert_called_once()
        call_kwargs = mock_options_class.call_args.kwargs
        assert call_kwargs["allowed_tools"] == ["Read", "Write"]
        assert call_kwargs["permission_mode"] == "bypassPermissions"
        assert call_kwargs["cwd"] == str(temp_dir)

    def test_create_options_with_model_override(self, temp_dir):
        """Should use model override in options."""
        manager = ConversationManager(working_dir=str(temp_dir), model="sonnet")

        mock_sdk = MagicMock()
        mock_options_class = MagicMock()
        mock_sdk.ClaudeSDKClient = MagicMock()
        mock_sdk.ClaudeAgentOptions = mock_options_class

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with patch(
                "claude_task_master.core.conversation.get_agents_for_working_dir", return_value=None
            ):
                manager._create_options(["Read"], model_override="opus")

        call_kwargs = mock_options_class.call_args.kwargs
        assert call_kwargs["model"] == MODEL_NAMES["opus"]

    def test_create_options_with_subagents(self, temp_dir):
        """Should include subagents when available."""
        manager = ConversationManager(working_dir=str(temp_dir))

        mock_sdk = MagicMock()
        mock_options_class = MagicMock()
        mock_sdk.ClaudeSDKClient = MagicMock()
        mock_sdk.ClaudeAgentOptions = mock_options_class

        mock_agents = [{"name": "test-agent"}]

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with patch(
                "claude_task_master.core.conversation.get_agents_for_working_dir",
                return_value=mock_agents,
            ):
                manager._create_options(["Read"])

        call_kwargs = mock_options_class.call_args.kwargs
        assert call_kwargs["agents"] == mock_agents

    def test_create_options_sdk_not_initialized(self, temp_dir):
        """Should raise error if SDK not initialized."""
        manager = ConversationManager(working_dir=str(temp_dir))
        manager._sdk_client_class = MagicMock()
        manager._options_class = None

        with pytest.raises(ConversationError) as exc_info:
            manager._create_options(["Read"])

        assert "not initialized" in str(exc_info.value)


# =============================================================================
# Test Conversation Context Manager
# =============================================================================


class TestConversationContextManager:
    """Tests for conversation context manager."""

    @pytest.mark.asyncio
    async def test_conversation_creates_client(self, temp_dir):
        """Should create and connect client."""
        manager = ConversationManager(working_dir=str(temp_dir))

        mock_client = AsyncMock()
        mock_sdk_class = MagicMock(return_value=mock_client)

        manager._sdk_client_class = mock_sdk_class
        manager._options_class = MagicMock(return_value=MagicMock())

        with patch(
            "claude_task_master.core.conversation.get_agents_for_working_dir", return_value=None
        ):
            async with manager.conversation("group-1") as session:
                assert session.group_id == "group-1"
                mock_client.connect.assert_called_once()

        mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_conversation_sets_active_group(self, temp_dir):
        """Should set active group during conversation."""
        manager = ConversationManager(working_dir=str(temp_dir))

        mock_client = AsyncMock()
        manager._sdk_client_class = MagicMock(return_value=mock_client)
        manager._options_class = MagicMock(return_value=MagicMock())

        with patch(
            "claude_task_master.core.conversation.get_agents_for_working_dir", return_value=None
        ):
            async with manager.conversation("test-group"):
                assert manager._active_group == "test-group"

    @pytest.mark.asyncio
    async def test_conversation_restores_cwd(self, temp_dir, monkeypatch):
        """Should restore original working directory."""
        import os

        original_cwd = os.getcwd()

        manager = ConversationManager(working_dir=str(temp_dir))

        mock_client = AsyncMock()
        manager._sdk_client_class = MagicMock(return_value=mock_client)
        manager._options_class = MagicMock(return_value=MagicMock())

        with patch(
            "claude_task_master.core.conversation.get_agents_for_working_dir", return_value=None
        ):
            async with manager.conversation("group-1"):
                pass

        assert os.getcwd() == original_cwd

    @pytest.mark.asyncio
    async def test_conversation_disconnects_on_error(self, temp_dir):
        """Should disconnect client even on error."""
        manager = ConversationManager(working_dir=str(temp_dir))

        mock_client = AsyncMock()
        manager._sdk_client_class = MagicMock(return_value=mock_client)
        manager._options_class = MagicMock(return_value=MagicMock())

        with patch(
            "claude_task_master.core.conversation.get_agents_for_working_dir", return_value=None
        ):
            try:
                async with manager.conversation("group-1"):
                    raise ValueError("Test error")
            except ValueError:
                pass

        mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_conversation_handles_disconnect_error(self, temp_dir):
        """Should handle disconnect errors gracefully."""
        manager = ConversationManager(working_dir=str(temp_dir))

        mock_client = AsyncMock()
        mock_client.disconnect.side_effect = Exception("Disconnect failed")
        manager._sdk_client_class = MagicMock(return_value=mock_client)
        manager._options_class = MagicMock(return_value=MagicMock())

        with patch(
            "claude_task_master.core.conversation.get_agents_for_working_dir", return_value=None
        ):
            with patch("claude_task_master.core.conversation.console"):
                # Should not raise
                async with manager.conversation("group-1"):
                    pass


# =============================================================================
# Test Manager Properties
# =============================================================================


class TestManagerProperties:
    """Tests for ConversationManager properties."""

    def test_active_group_property(self, temp_dir):
        """Should return active group."""
        manager = ConversationManager(working_dir=str(temp_dir))
        assert manager.active_group is None

        manager._active_group = "test-group"
        assert manager.active_group == "test-group"

    def test_has_active_conversation_false(self, temp_dir):
        """Should return False when no active conversation."""
        manager = ConversationManager(working_dir=str(temp_dir))
        assert manager.has_active_conversation is False

    def test_has_active_conversation_true(self, temp_dir):
        """Should return True when has active conversation."""
        manager = ConversationManager(working_dir=str(temp_dir))
        manager._active_group = "test-group"
        assert manager.has_active_conversation is True

    @pytest.mark.asyncio
    async def test_close_all_clears_active_group(self, temp_dir):
        """Should clear active group on close_all."""
        manager = ConversationManager(working_dir=str(temp_dir))
        manager._active_group = "test-group"

        await manager.close_all()

        assert manager._active_group is None


# =============================================================================
# Test ConversationSession
# =============================================================================


class TestConversationSessionInit:
    """Tests for ConversationSession initialization."""

    def test_init_basic(self, temp_dir):
        """Should initialize with required arguments."""
        manager = ConversationManager(working_dir=str(temp_dir))
        mock_client = MagicMock()

        session = ConversationSession(client=mock_client, manager=manager, group_id="test-group")

        assert session.client is mock_client
        assert session.manager is manager
        assert session.group_id == "test-group"
        assert session._query_count == 0

    def test_query_count_property(self, temp_dir):
        """Should return query count."""
        manager = ConversationManager(working_dir=str(temp_dir))
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        assert session.query_count == 0
        session._query_count = 5
        assert session.query_count == 5


# =============================================================================
# Test Query Task
# =============================================================================


class TestQueryTask:
    """Tests for query_task method."""

    @pytest.mark.asyncio
    async def test_query_task_success(self, temp_dir):
        """Should execute query and return result."""
        manager = ConversationManager(working_dir=str(temp_dir))
        mock_client = MagicMock()
        mock_client.query = AsyncMock()

        # Create mock result message
        mock_result_message = MagicMock()
        mock_result_message.__class__.__name__ = "ResultMessage"
        mock_result_message.result = "Task completed"
        mock_result_message.content = []

        # receive_response returns an async iterator directly (not a coroutine)
        mock_client.receive_response = MagicMock(
            return_value=AsyncIteratorMock([mock_result_message])
        )

        session = ConversationSession(client=mock_client, manager=manager, group_id="test-group")

        with patch("claude_task_master.core.conversation.console"):
            result = await session.query_task("Do something")

        assert result == "Task completed"
        assert session._query_count == 1
        mock_client.query.assert_called_once_with("Do something")

    @pytest.mark.asyncio
    async def test_query_task_increments_count(self, temp_dir):
        """Should increment query count on each call."""
        manager = ConversationManager(working_dir=str(temp_dir))
        mock_client = MagicMock()
        mock_client.query = AsyncMock()

        # receive_response returns an async iterator directly (not a coroutine)
        mock_client.receive_response = MagicMock(return_value=AsyncIteratorMock([]))

        session = ConversationSession(client=mock_client, manager=manager, group_id="test-group")

        with patch("claude_task_master.core.conversation.console"):
            await session.query_task("Query 1")
            # Reset the mock for second call
            mock_client.receive_response = MagicMock(return_value=AsyncIteratorMock([]))
            await session.query_task("Query 2")

        assert session._query_count == 2

    @pytest.mark.asyncio
    async def test_query_task_raises_on_error(self, temp_dir):
        """Should raise QueryExecutionError on failure."""
        manager = ConversationManager(working_dir=str(temp_dir))
        mock_client = AsyncMock()
        mock_client.query.side_effect = RuntimeError("Connection failed")

        session = ConversationSession(client=mock_client, manager=manager, group_id="test-group")

        with patch("claude_task_master.core.conversation.console"):
            with pytest.raises(QueryExecutionError) as exc_info:
                await session.query_task("Query")

        assert "Connection failed" in str(exc_info.value)


# =============================================================================
# Test Message Processing
# =============================================================================


class TestProcessMessage:
    """Tests for _process_message method."""

    def test_process_text_block(self, temp_dir):
        """Should process TextBlock content."""
        manager = ConversationManager(working_dir=str(temp_dir))
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        text_block = MagicMock()
        text_block.__class__.__name__ = "TextBlock"
        text_block.text = "Hello world"

        message = MagicMock()
        message.__class__.__name__ = "AssistantMessage"
        message.content = [text_block]

        with patch("claude_task_master.core.conversation.console"):
            result = session._process_message(message, "")

        assert "Hello world" in result

    def test_process_tool_use_block(self, temp_dir):
        """Should process ToolUseBlock content."""
        mock_logger = MagicMock()
        manager = ConversationManager(working_dir=str(temp_dir), logger=mock_logger)
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        tool_block = MagicMock()
        tool_block.__class__.__name__ = "ToolUseBlock"
        tool_block.name = "Read"
        tool_block.input = {"file_path": "/test/file.py"}

        message = MagicMock()
        message.__class__.__name__ = "AssistantMessage"
        message.content = [tool_block]

        with patch("claude_task_master.core.conversation.console"):
            session._process_message(message, "")

        mock_logger.log_tool_use.assert_called_once_with("Read", {"file_path": "/test/file.py"})

    def test_process_tool_result_block_success(self, temp_dir):
        """Should process successful ToolResultBlock."""
        mock_logger = MagicMock()
        manager = ConversationManager(working_dir=str(temp_dir), logger=mock_logger)
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        result_block = MagicMock()
        result_block.__class__.__name__ = "ToolResultBlock"
        result_block.is_error = False
        result_block.tool_use_id = "tool-123"
        result_block.content = None

        message = MagicMock()
        message.__class__.__name__ = "AssistantMessage"
        message.content = [result_block]

        with patch("claude_task_master.core.conversation.console"):
            session._process_message(message, "")

        mock_logger.log_tool_result.assert_called_once_with("tool-123", "completed")

    def test_process_tool_result_block_error(self, temp_dir):
        """Should process error ToolResultBlock."""
        mock_logger = MagicMock()
        manager = ConversationManager(working_dir=str(temp_dir), logger=mock_logger)
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        result_block = MagicMock()
        result_block.__class__.__name__ = "ToolResultBlock"
        result_block.is_error = True
        result_block.tool_use_id = "tool-456"

        message = MagicMock()
        message.__class__.__name__ = "AssistantMessage"
        message.content = [result_block]

        with patch("claude_task_master.core.conversation.console"):
            session._process_message(message, "")

        mock_logger.log_tool_result.assert_called_once_with("tool-456", "ERROR")

    def test_process_result_message(self, temp_dir):
        """Should extract result from ResultMessage."""
        manager = ConversationManager(working_dir=str(temp_dir))
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        message = MagicMock()
        message.__class__.__name__ = "ResultMessage"
        message.result = "Final result"
        message.content = []

        with patch("claude_task_master.core.conversation.console"):
            result = session._process_message(message, "prior text")

        assert result == "Final result"


# =============================================================================
# Test Tool Detail Formatting
# =============================================================================


class TestFormatToolDetail:
    """Tests for _format_tool_detail method."""

    @pytest.fixture
    def session(self, temp_dir):
        """Create a session for testing."""
        manager = ConversationManager(working_dir=str(temp_dir))
        return ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

    def test_format_bash_tool(self, session):
        """Should format Bash tool details."""
        result = session._format_tool_detail("Bash", {"command": "ls -la"})
        assert "ls -la" in result

    def test_format_bash_long_command(self, session):
        """Should truncate long Bash commands."""
        long_cmd = "x" * 300
        result = session._format_tool_detail("Bash", {"command": long_cmd})
        assert len(result) < 260
        assert "..." in result

    def test_format_read_tool(self, session):
        """Should format Read tool details."""
        result = session._format_tool_detail("Read", {"file_path": "/test/file.py"})
        assert "/test/file.py" in result

    def test_format_write_tool(self, session):
        """Should format Write tool details."""
        result = session._format_tool_detail("Write", {"file_path": "/test/output.txt"})
        assert "/test/output.txt" in result

    def test_format_edit_tool(self, session):
        """Should format Edit tool details."""
        result = session._format_tool_detail("Edit", {"file_path": "/test/edit.py"})
        assert "/test/edit.py" in result

    def test_format_glob_tool(self, session):
        """Should format Glob tool details."""
        result = session._format_tool_detail("Glob", {"pattern": "*.py", "path": "/src"})
        assert "*.py" in result
        assert "/src" in result

    def test_format_grep_tool(self, session):
        """Should format Grep tool details."""
        result = session._format_tool_detail("Grep", {"pattern": "def foo", "path": "/tests"})
        assert "def foo" in result
        assert "/tests" in result

    def test_format_unknown_tool(self, session):
        """Should format unknown tool with first key-value."""
        result = session._format_tool_detail("CustomTool", {"arg1": "value1", "arg2": "value2"})
        assert "arg1" in result
        assert "value1" in result

    def test_format_empty_input(self, session):
        """Should return empty string for empty input."""
        result = session._format_tool_detail("Read", {})
        assert result == ""


# =============================================================================
# Test Tool Result Summary Formatting
# =============================================================================


class TestFormatToolResultSummary:
    """Tests for _format_tool_result_summary method."""

    def test_summary_returns_empty_when_not_verbose(self, temp_dir):
        """Should return empty string when not verbose."""
        manager = ConversationManager(working_dir=str(temp_dir), verbose=False)
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        block = MagicMock()
        block.content = "Some content"

        result = session._format_tool_result_summary(block)
        assert result == ""

    def test_summary_returns_empty_for_no_content(self, temp_dir):
        """Should return empty string when no content."""
        manager = ConversationManager(working_dir=str(temp_dir), verbose=True)
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        block = MagicMock()
        block.content = None

        result = session._format_tool_result_summary(block)
        assert result == ""

    def test_summary_handles_string_content(self, temp_dir):
        """Should handle string content."""
        manager = ConversationManager(working_dir=str(temp_dir), verbose=True)
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        block = MagicMock()
        block.content = "Line 1\nLine 2\nLine 3"

        result = session._format_tool_result_summary(block)
        assert "Line" in result

    def test_summary_handles_list_content_with_text(self, temp_dir):
        """Should handle list content with text attribute."""
        manager = ConversationManager(working_dir=str(temp_dir), verbose=True)
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        item = MagicMock()
        item.text = "Test text"
        block = MagicMock()
        block.content = [item]

        result = session._format_tool_result_summary(block)
        assert "Test text" in result

    def test_summary_handles_list_content_strings(self, temp_dir):
        """Should handle list content with strings."""
        manager = ConversationManager(working_dir=str(temp_dir), verbose=True)
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        block = MagicMock()
        block.content = ["String content"]

        result = session._format_tool_result_summary(block)
        assert "String content" in result

    def test_summary_detects_edit_summary(self, temp_dir):
        """Should detect and return edit summary lines."""
        manager = ConversationManager(working_dir=str(temp_dir), verbose=True)
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        block = MagicMock()
        block.content = "Some prefix\nAdded 5 lines to file.py\nMore content"

        result = session._format_tool_result_summary(block)
        assert "Added" in result or "line" in result

    def test_summary_shows_last_lines(self, temp_dir):
        """Should show last few lines for long output."""
        manager = ConversationManager(working_dir=str(temp_dir), verbose=True)
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        lines = [f"Line {i}" for i in range(10)]
        block = MagicMock()
        block.content = "\n".join(lines)

        result = session._format_tool_result_summary(block)
        # Should indicate there are more lines
        assert "..." in result or "lines" in result
        # Should show later lines
        assert "Line 9" in result or "Line 8" in result

    def test_summary_truncates_long_lines(self, temp_dir):
        """Should truncate very long lines."""
        manager = ConversationManager(working_dir=str(temp_dir), verbose=True)
        session = ConversationSession(client=MagicMock(), manager=manager, group_id="test-group")

        long_line = "x" * 200
        block = MagicMock()
        block.content = long_line

        result = session._format_tool_result_summary(block)
        # Each line should be truncated
        assert len(result.split("\n")[-1]) <= 100


# =============================================================================
# Async Helper
# =============================================================================


class AsyncIteratorMock:
    """Mock async iterator for testing."""

    def __init__(self, items: list[Any]):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item
