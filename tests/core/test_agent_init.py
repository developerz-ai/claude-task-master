"""Tests for AgentWrapper initialization and SDK import handling.

This module contains tests for:
- AgentWrapper initialization with various parameters
- SDK import error handling
- Working directory error handling during initialization
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_task_master.core.agent import AgentWrapper, ModelType
from claude_task_master.core.agent_exceptions import (
    SDKImportError,
    SDKInitializationError,
    WorkingDirectoryError,
)
from claude_task_master.core.rate_limit import RateLimitConfig

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
        """Test initialization without claude-agent-sdk raises SDKImportError."""
        # Patch the import to simulate missing module
        with patch.dict("sys.modules", {"claude_agent_sdk": None}):
            with pytest.raises(SDKImportError) as exc_info:
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

    def test_init_with_custom_rate_limit_config(self):
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

    def test_init_with_default_rate_limit_config(self):
        """Test default rate limit configuration values."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
            )

        default_config = RateLimitConfig.default()
        assert agent.rate_limit_config.max_retries == default_config.max_retries
        assert agent.rate_limit_config.initial_backoff == default_config.initial_backoff
        assert agent.rate_limit_config.max_backoff == default_config.max_backoff


# =============================================================================
# AgentWrapper SDK Import Tests
# =============================================================================


class TestAgentWrapperSDKImport:
    """Tests for SDK import error handling."""

    def test_missing_query_attribute(self):
        """Test error when SDK is missing query attribute."""
        mock_sdk = MagicMock(spec=[])  # Empty spec means no attributes
        del mock_sdk.query

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with pytest.raises(SDKInitializationError) as exc_info:
                AgentWrapper(
                    access_token="test-token",
                    model=ModelType.SONNET,
                )

        assert exc_info.value.component == "query"

    def test_missing_options_class(self):
        """Test error when SDK is missing ClaudeAgentOptions."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        del mock_sdk.ClaudeAgentOptions

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with pytest.raises(SDKInitializationError) as exc_info:
                AgentWrapper(
                    access_token="test-token",
                    model=ModelType.SONNET,
                )

        assert exc_info.value.component == "ClaudeAgentOptions"

    def test_query_not_callable(self):
        """Test error when query is not callable."""
        mock_sdk = MagicMock()
        mock_sdk.query = "not a function"
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            with pytest.raises(SDKInitializationError) as exc_info:
                AgentWrapper(
                    access_token="test-token",
                    model=ModelType.SONNET,
                )

        assert exc_info.value.component == "query"

    def test_sdk_import_error_basic(self):
        """Test SDKImportError without original error."""
        error = SDKImportError()
        assert "claude-agent-sdk not installed" in error.message
        assert error.original_error is None

    def test_sdk_import_error_with_original(self):
        """Test SDKImportError with original exception."""
        original = ImportError("No module named 'claude_agent_sdk'")
        error = SDKImportError(original)
        assert error.original_error == original
        assert "claude_agent_sdk" in str(error)


# =============================================================================
# AgentWrapper Working Directory Error Tests
# =============================================================================


class TestAgentWrapperWorkingDirectoryErrors:
    """Tests for working directory error handling."""

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
                working_dir="/nonexistent/directory",
            )
        return agent

    @pytest.mark.asyncio
    async def test_working_directory_not_found(self, agent):
        """Test error when working directory doesn't exist."""
        with pytest.raises(WorkingDirectoryError) as exc_info:
            await agent._query_executor._execute_query("test prompt", ["Read"])

        assert exc_info.value.path == "/nonexistent/directory"
        assert "change to" in exc_info.value.operation

    @pytest.mark.asyncio
    async def test_working_directory_permission_error(self, temp_dir):
        """Test error when working directory has permission issues."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
            )

        # Mock os.chdir to raise PermissionError
        with patch("os.chdir", side_effect=PermissionError("Permission denied")):
            with pytest.raises(WorkingDirectoryError) as exc_info:
                await agent._query_executor._execute_query("test prompt", ["Read"])

            assert "access" in exc_info.value.operation

    @pytest.mark.asyncio
    async def test_directory_restored_after_error(self, temp_dir):
        """Test working directory is restored even after query error."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        original_dir = os.getcwd()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
            )

        # Create async generator that raises an error
        async def mock_query_gen(*args, **kwargs):
            raise ValueError("Test error")
            yield  # Make it a generator

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        from claude_task_master.core.agent_exceptions import QueryExecutionError

        with pytest.raises(QueryExecutionError):
            await agent._run_query("test prompt", ["Read"])

        # Should be back in original directory
        assert os.getcwd() == original_dir

    @pytest.mark.asyncio
    async def test_directory_restored_after_success(self, temp_dir):
        """Test working directory is restored after successful query."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        original_dir = os.getcwd()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
            )

        # Create async generator that yields a mock message
        async def mock_query_gen(*args, **kwargs):
            yield MagicMock(content=None)

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        await agent._run_query("test prompt", ["Read"])

        # Should be back in original directory
        assert os.getcwd() == original_dir
