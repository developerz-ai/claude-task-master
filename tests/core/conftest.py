"""Pytest fixtures for agent-related tests.

This module provides shared fixtures for tests in the tests/core directory,
particularly for AgentWrapper testing. These fixtures help reduce duplication
across test_agent_*.py files.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_task_master.core.agent import AgentWrapper, ModelType
from claude_task_master.core.rate_limit import RateLimitConfig

# =============================================================================
# Mock SDK Fixtures
# =============================================================================


@pytest.fixture
def mock_sdk():
    """Create a mock Claude Agent SDK with query and options class.

    Returns:
        MagicMock: A mock SDK with query as AsyncMock and ClaudeAgentOptions.
    """
    mock = MagicMock()
    mock.query = AsyncMock()
    mock.ClaudeAgentOptions = MagicMock()
    return mock


@pytest.fixture
def mock_sdk_in_modules(mock_sdk):
    """Patch sys.modules with the mock SDK.

    This context manager patches sys.modules so that
    'import claude_agent_sdk' returns the mock SDK.

    Yields:
        MagicMock: The mock SDK module.
    """
    with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
        yield mock_sdk


# =============================================================================
# Agent Fixtures
# =============================================================================


@pytest.fixture
def agent_with_temp_dir(temp_dir, mock_sdk):
    """Create an AgentWrapper instance with a temporary working directory.

    This is the most commonly used fixture for agent tests that need
    a valid working directory.

    Args:
        temp_dir: Temporary directory fixture from root conftest.py
        mock_sdk: Mock SDK fixture

    Returns:
        AgentWrapper: An AgentWrapper instance configured with test defaults.
    """
    with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
        return AgentWrapper(
            access_token="test-token",
            model=ModelType.SONNET,
            working_dir=str(temp_dir),
        )


@pytest.fixture
def agent_default_working_dir(mock_sdk):
    """Create an AgentWrapper instance with default working directory.

    Useful for tests that don't need a specific working directory
    or are testing initialization behavior.

    Args:
        mock_sdk: Mock SDK fixture

    Returns:
        AgentWrapper: An AgentWrapper instance with default working directory.
    """
    with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
        return AgentWrapper(
            access_token="test-token",
            model=ModelType.SONNET,
        )


@pytest.fixture
def agent_with_fast_retry(temp_dir, mock_sdk):
    """Create an AgentWrapper instance with fast retry settings for testing.

    This fixture configures the agent with minimal backoff times
    to speed up retry-related tests.

    Args:
        temp_dir: Temporary directory fixture
        mock_sdk: Mock SDK fixture

    Returns:
        AgentWrapper: An AgentWrapper with fast retry configuration.
    """
    rate_limit_config = RateLimitConfig(
        max_retries=2,
        initial_backoff=0.1,  # Fast backoff for tests
        max_backoff=0.5,
    )

    with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
        return AgentWrapper(
            access_token="test-token",
            model=ModelType.SONNET,
            working_dir=str(temp_dir),
            rate_limit_config=rate_limit_config,
        )


@pytest.fixture
def agent_with_nonexistent_dir(mock_sdk):
    """Create an AgentWrapper instance with a nonexistent working directory.

    This fixture is useful for testing error handling when the
    working directory doesn't exist.

    Args:
        mock_sdk: Mock SDK fixture

    Returns:
        AgentWrapper: An AgentWrapper with an invalid working directory.
    """
    with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
        return AgentWrapper(
            access_token="test-token",
            model=ModelType.SONNET,
            working_dir="/nonexistent/directory",
        )


# =============================================================================
# Message Block Fixtures
# =============================================================================


@pytest.fixture
def mock_text_block():
    """Create a mock TextBlock.

    Returns:
        MagicMock: A mock TextBlock with configurable text property.
    """

    def _create(text: str = "Hello, world!"):
        block = MagicMock()
        type(block).__name__ = "TextBlock"
        block.text = text
        return block

    return _create


@pytest.fixture
def mock_tool_use_block():
    """Create a mock ToolUseBlock.

    Returns:
        MagicMock: A mock ToolUseBlock with configurable name property.
    """

    def _create(name: str = "Read"):
        block = MagicMock()
        type(block).__name__ = "ToolUseBlock"
        block.name = name
        return block

    return _create


@pytest.fixture
def mock_tool_result_block():
    """Create a mock ToolResultBlock.

    Returns:
        MagicMock: A mock ToolResultBlock with configurable is_error property.
    """

    def _create(is_error: bool = False):
        block = MagicMock()
        type(block).__name__ = "ToolResultBlock"
        block.is_error = is_error
        return block

    return _create


@pytest.fixture
def mock_result_message():
    """Create a mock ResultMessage.

    Returns:
        MagicMock: A mock ResultMessage with configurable result property.
    """

    def _create(result: str = "Final result"):
        message = MagicMock()
        type(message).__name__ = "ResultMessage"
        message.result = result
        message.content = None
        return message

    return _create


@pytest.fixture
def mock_message_with_content():
    """Create a mock message with configurable content list.

    Returns:
        Callable: A factory function that creates mock messages.
    """

    def _create(content: list | None = None, message_type: str = "AssistantMessage"):
        message = MagicMock()
        type(message).__name__ = message_type
        message.content = content
        return message

    return _create


# =============================================================================
# Query Generator Fixtures
# =============================================================================


@pytest.fixture
def mock_query_generator():
    """Create a mock async generator for query responses.

    Returns:
        Callable: A factory that creates async generators yielding specified messages.
    """

    def _create(messages: list):
        async def query_gen(*args, **kwargs):
            for message in messages:
                yield message

        return query_gen

    return _create


@pytest.fixture
def mock_query_generator_with_error():
    """Create a mock async generator that raises an exception.

    Returns:
        Callable: A factory that creates async generators that raise exceptions.
    """

    def _create(error: Exception, after_messages: list | None = None):
        after_messages = after_messages or []

        async def query_gen(*args, **kwargs):
            for message in after_messages:
                yield message
            raise error

        return query_gen

    return _create


# =============================================================================
# Planning Phase Fixtures
# =============================================================================


@pytest.fixture
def sample_planning_result():
    """Sample planning result with tasks and criteria.

    Returns:
        str: A formatted planning result string.
    """
    return """## Task List

- [ ] Setup project structure
- [ ] Implement core logic
- [ ] Add tests

## Success Criteria

1. All tests pass
2. Documentation complete
"""


@pytest.fixture
def sample_planning_result_minimal():
    """Minimal planning result with single task.

    Returns:
        str: A minimal planning result string.
    """
    return """## Task List

- [ ] Task 1

## Success Criteria

1. Done
"""


# =============================================================================
# Model Fixtures
# =============================================================================


@pytest.fixture(params=list(ModelType))
def all_model_types(request):
    """Parameterized fixture that yields all ModelType values.

    This allows tests to run against all model types automatically.

    Yields:
        ModelType: Each model type in sequence.
    """
    return request.param
