"""Tests for AgentWrapper query execution and retry logic.

This module contains tests for:
- Query execution (_run_query method)
- Retry logic with backoff
- Error classification
- Message processing
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_task_master.core.agent import AgentWrapper, ModelType
from claude_task_master.core.agent_exceptions import (
    APIAuthenticationError,
    APIConnectionError,
    APIRateLimitError,
    APIServerError,
    APITimeoutError,
    ConsecutiveFailuresError,
    ContentFilterError,
    QueryExecutionError,
)
from claude_task_master.core.rate_limit import RateLimitConfig

# =============================================================================
# AgentWrapper Query Execution Tests
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
        agent._query_executor.query = mock_query_gen

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
        agent._query_executor.query = mock_query_gen

        with pytest.raises(QueryExecutionError):
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
        agent._query_executor.options_class = capture_options

        async def mock_query_gen(*args, **kwargs):
            yield MagicMock(content=None)

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        await agent._run_query("test prompt", ["Read", "Glob"])

        assert len(options_calls) == 1
        assert options_calls[0]["allowed_tools"] == ["Read", "Glob"]
        assert options_calls[0]["permission_mode"] == "bypassPermissions"

    @pytest.mark.asyncio
    async def test_run_query_options_include_max_buffer_size(self, agent, temp_dir):
        """Test _run_query passes max_buffer_size=5MB to ClaudeAgentOptions."""
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

        assert len(options_calls) == 1
        assert options_calls[0]["max_buffer_size"] == 5 * 1024 * 1024

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
        agent._query_executor.query = mock_query_gen

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
        agent._query_executor.query = mock_query_gen

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
        agent._query_executor.query = mock_query_gen

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
        agent._query_executor.query = mock_query_gen

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
        agent._query_executor.query = mock_query_gen

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
        agent._query_executor.query = mock_query_gen

        # Should not raise
        result = await agent._run_query("test prompt", ["Read"])

        assert result == ""


# =============================================================================
# AgentWrapper Retry Logic Tests
# =============================================================================


class TestAgentWrapperRetryLogic:
    """Tests for retry logic in AgentWrapper."""

    @pytest.fixture
    def agent(self, temp_dir):
        """Create an AgentWrapper instance for testing."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            rate_limit_config = RateLimitConfig(
                max_retries=2,
                initial_backoff=0.1,  # Fast backoff for tests
                max_backoff=0.5,
            )
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
                rate_limit_config=rate_limit_config,
            )
        return agent

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit_error(self, agent, temp_dir):
        """Test retry logic on rate limit error."""
        call_count = 0

        async def mock_query_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("rate limit exceeded")
            yield MagicMock(content=None)

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await agent._run_query("test prompt", ["Read"])

        # Should have retried twice before succeeding
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self, agent, temp_dir):
        """Test retry logic on connection error."""
        call_count = 0

        async def mock_query_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("connection refused")
            yield MagicMock(content=None)

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await agent._run_query("test prompt", ["Read"])

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_timeout_error(self, agent, temp_dir):
        """Test retry logic on timeout error."""
        call_count = 0

        async def mock_query_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("Request timeout")
            yield MagicMock(content=None)

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await agent._run_query("test prompt", ["Read"])

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_server_error_500(self, agent, temp_dir):
        """Test retry logic on 500 server error."""
        call_count = 0

        async def mock_query_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("HTTP 500 Internal Server Error")
            yield MagicMock(content=None)

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await agent._run_query("test prompt", ["Read"])

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_auth_error(self, agent, temp_dir):
        """Test authentication errors are not retried."""
        call_count = 0

        async def mock_query_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("401 Unauthorized")
            yield  # Make it an async generator

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        with pytest.raises(APIAuthenticationError):
            await agent._run_query("test prompt", ["Read"])

        # Should only be called once - no retry
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, agent, temp_dir):
        """Test that ConsecutiveFailuresError is raised after max_retries + 1 failures."""
        call_count = 0

        async def mock_query_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("rate limit exceeded")
            yield  # Make it an async generator

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ConsecutiveFailuresError):
                await agent._run_query("test prompt", ["Read"])

        # max_retries=2, so 3 calls (initial + 2 retries)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_successful_first_attempt_no_retry(self, agent, temp_dir):
        """Test no retry on successful first attempt."""
        call_count = 0

        async def mock_query_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield MagicMock(content=None)

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        await agent._run_query("test prompt", ["Read"])

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_uses_exponential_backoff(self, agent, temp_dir):
        """Test that retries use exponential backoff from rate_limit_config."""
        call_count = 0
        sleep_delays = []

        async def mock_query_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("rate limit exceeded")
            yield MagicMock(content=None)

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        async def capture_sleep(delay):
            sleep_delays.append(delay)

        with patch("asyncio.sleep", side_effect=capture_sleep):
            await agent._run_query("test prompt", ["Read"])

        # rate_limit_config: initial_backoff=0.1, multiplier=2.0
        # attempt 0: 0.1 * 2^0 = 0.1
        # attempt 1: 0.1 * 2^1 = 0.2
        assert len(sleep_delays) == 2
        assert sleep_delays[0] == pytest.approx(0.1)
        assert sleep_delays[1] == pytest.approx(0.2)

    @pytest.mark.asyncio
    async def test_retry_respects_retry_after_for_rate_limits(self, agent, temp_dir):
        """Test that rate limit errors with retry_after use that value."""
        call_count = 0
        sleep_delays = []

        async def mock_query_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Simulate an error with retry_after
                raise Exception("rate limit exceeded")
            yield MagicMock(content=None)

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        # Patch _classify_api_error to return an APIRateLimitError with retry_after
        original_classify = agent._query_executor._classify_api_error

        def classify_with_retry_after(error):
            classified = original_classify(error)
            if isinstance(classified, APIRateLimitError):
                classified.retry_after = 42.0
            return classified

        agent._query_executor._classify_api_error = classify_with_retry_after

        async def capture_sleep(delay):
            sleep_delays.append(delay)

        with patch("asyncio.sleep", side_effect=capture_sleep):
            await agent._run_query("test prompt", ["Read"])

        # Should use retry_after value instead of exponential backoff
        assert len(sleep_delays) == 1
        assert sleep_delays[0] == 42.0

    @pytest.mark.asyncio
    async def test_max_retries_configurable(self, temp_dir):
        """Test that max_retries from config controls failure threshold."""
        from claude_task_master.core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            rate_limit_config = RateLimitConfig(
                max_retries=4,  # More retries than default (3+1=4 total attempts)
                initial_backoff=0.01,
                max_backoff=0.1,
            )
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=str(temp_dir),
                rate_limit_config=rate_limit_config,
            )

        # Raise circuit breaker threshold so it doesn't interfere
        agent._query_executor.circuit_breaker = CircuitBreaker(
            name="test",
            config=CircuitBreakerConfig(failure_threshold=100),
        )

        call_count = 0

        async def mock_query_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("rate limit exceeded")
            yield

        agent.query = mock_query_gen
        agent._query_executor.query = mock_query_gen

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ConsecutiveFailuresError):
                await agent._run_query("test prompt", ["Read"])

        # max_retries=4, so 5 calls (initial + 4 retries)
        assert call_count == 5


# =============================================================================
# Stream Idle-Timeout Watchdog Tests
# =============================================================================


class TestStreamIdleTimeoutWatchdog:
    """Tests for the stream idle-timeout watchdog.

    Background: the upstream Claude Agent SDK's query() iterator has no built-in
    idle timeout (see query.py:809 in the SDK source). Under bug
    https://github.com/anthropics/claude-code/issues/30333 the CLI can drop the
    final ResultMessage on long sessions and the iterator parks forever. Our
    watchdog wraps __anext__() with asyncio.wait_for(timeout=N) and raises
    APITimeoutError on stall, which feeds the existing retry path. After 2
    stalls we raise ConsecutiveFailuresError to avoid infinite loops (the
    windowed counter would otherwise reset between long timeouts).

    All tests stub asyncio.sleep and patch STREAM_IDLE_TIMEOUT_SEC to keep
    runtime instant.
    """

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
    async def test_stalled_stream_raises_timeout_then_retries(self, agent):
        """A stream that never yields a message must raise APITimeoutError,
        which feeds the existing retry path (so the prompt is re-attempted).

        We can't simulate a stall via asyncio.sleep because the retry-backoff
        path patches asyncio.sleep to be instant — that would also short-circuit
        our stalling generator. Use a never-resolving Future, which the patches
        don't touch.
        """
        import asyncio as _asyncio

        attempts = 0

        async def stalling_then_succeeding(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                # First attempt: never resolve. wait_for(0.001s) will cancel
                # this and raise TimeoutError → APITimeoutError → retry.
                await _asyncio.Future()
                yield  # unreachable
            else:
                msg = MagicMock()
                type(msg).__name__ = "ResultMessage"
                msg.result = "ok"
                yield msg

        agent._query_executor.query = stalling_then_succeeding

        with (
            patch(
                "claude_task_master.core.agent_query.STREAM_IDLE_TIMEOUT_SEC", 0.001
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await agent._run_query("test prompt", ["Read"])

        assert attempts == 2
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_two_stream_stalls_raises_consecutive_failures(self, agent):
        """If the stream stalls twice in a row, we must NOT retry forever —
        the per-query stream-idle-timeout cap (2) raises
        ConsecutiveFailuresError. This is critical: each idle timeout exceeds
        the windowed failure counter, which would otherwise reset between
        stalls and let the loop run indefinitely."""
        import asyncio as _asyncio

        async def always_stalls(*args, **kwargs):
            await _asyncio.Future()
            yield  # unreachable

        agent._query_executor.query = always_stalls

        with (
            patch(
                "claude_task_master.core.agent_query.STREAM_IDLE_TIMEOUT_SEC", 0.001
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(ConsecutiveFailuresError):
                await agent._run_query("test prompt", ["Read"])

    @pytest.mark.asyncio
    async def test_aclose_called_on_stream(self, agent):
        """The iterator's aclose() must always be called so the SDK transport
        (subprocess, HTTP) is released. Without this, a long-running orchestrator
        would leak subprocess handles."""
        aclose_called = []

        class TrackingGen:
            def __init__(self):
                self._yielded = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._yielded:
                    raise StopAsyncIteration
                self._yielded = True
                msg = MagicMock()
                type(msg).__name__ = "ResultMessage"
                msg.result = "done"
                return msg

            async def aclose(self):
                aclose_called.append(True)

        def make_stream(*args, **kwargs):
            return TrackingGen()

        agent._query_executor.query = make_stream

        await agent._run_query("test prompt", ["Read"])
        assert aclose_called == [True]

    @pytest.mark.asyncio
    async def test_aclose_called_even_when_stream_raises(self, agent):
        """aclose() must run even if the stream errors mid-flight."""
        aclose_called = []

        class FailingGen:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise RuntimeError("boom")

            async def aclose(self):
                aclose_called.append(True)

        def make_stream(*args, **kwargs):
            return FailingGen()

        agent._query_executor.query = make_stream

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises((QueryExecutionError, ConsecutiveFailuresError)):
                await agent._run_query("test prompt", ["Read"])

        # aclose called at least once (per retry attempt)
        assert len(aclose_called) >= 1

    @pytest.mark.asyncio
    async def test_options_include_cli_stall_env_vars(self, agent):
        """Belt-and-suspenders: the CLI subprocess gets stall timeout env vars
        via ClaudeAgentOptions.env so it can fail-fast on internal stalls
        before our watchdog has to step in."""
        options_calls = []

        def capture_options(**kwargs):
            options_calls.append(kwargs)
            return MagicMock()

        agent._query_executor.options_class = capture_options

        async def mock_query_gen(*args, **kwargs):
            yield MagicMock(content=None)

        agent._query_executor.query = mock_query_gen

        await agent._run_query("test prompt", ["Read"])

        assert len(options_calls) == 1
        env = options_calls[0].get("env", {})
        assert "CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS" in env
        assert "API_TIMEOUT_MS" in env
        # Should match STREAM_IDLE_TIMEOUT_SEC * 1000 (ms)
        from claude_task_master.core.agent_query import STREAM_IDLE_TIMEOUT_SEC

        expected_ms = str(int(STREAM_IDLE_TIMEOUT_SEC * 1000))
        assert env["CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS"] == expected_ms
        assert env["API_TIMEOUT_MS"] == expected_ms

    @pytest.mark.asyncio
    async def test_successful_query_resets_stream_timeout_counter(self, agent):
        """A successful query must reset the stream-timeout counter so a later
        independent stall doesn't unfairly count against a fresh run."""

        # First query: 1 stall then success. After this, counter must be 0.
        import asyncio as _asyncio

        attempts = 0

        async def stall_once_then_succeed(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                await _asyncio.Future()
                yield  # unreachable
            else:
                msg = MagicMock()
                type(msg).__name__ = "ResultMessage"
                msg.result = "first"
                yield msg

        agent._query_executor.query = stall_once_then_succeed

        with (
            patch(
                "claude_task_master.core.agent_query.STREAM_IDLE_TIMEOUT_SEC", 0.001
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await agent._run_query("first", ["Read"])

        # Counter must be reset after success
        assert agent._query_executor._stream_idle_timeouts == 0


# =============================================================================
# AgentWrapper Error Classification Tests
# =============================================================================


class TestAgentWrapperErrorClassification:
    """Tests for error classification in AgentQueryExecutor."""

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

    def test_classify_rate_limit_error(self, agent):
        """Test classification of rate limit errors."""
        error = Exception("API rate limit exceeded")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, APIRateLimitError)

    def test_classify_auth_error_401(self, agent):
        """Test classification of 401 auth error."""
        error = Exception("HTTP 401 Unauthorized")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, APIAuthenticationError)

    def test_classify_auth_error_403(self, agent):
        """Test classification of 403 auth error."""
        error = Exception("HTTP 403 Forbidden")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, APIAuthenticationError)

    def test_classify_timeout_error(self, agent):
        """Test classification of timeout errors."""
        error = Exception("Request timeout after 30 seconds")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, APITimeoutError)

    def test_classify_connection_error(self, agent):
        """Test classification of connection errors."""
        error = Exception("Connection refused")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, APIConnectionError)

    def test_classify_network_error(self, agent):
        """Test classification of network errors."""
        error = Exception("Network unreachable")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, APIConnectionError)

    def test_classify_server_error_500(self, agent):
        """Test classification of 500 server errors."""
        error = Exception("HTTP 500 Internal Server Error")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, APIServerError)
        assert classified.status_code == 500

    def test_classify_server_error_502(self, agent):
        """Test classification of 502 server errors."""
        error = Exception("HTTP 502 Bad Gateway")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, APIServerError)
        assert classified.status_code == 502

    def test_classify_server_error_503(self, agent):
        """Test classification of 503 server errors."""
        error = Exception("HTTP 503 Service Unavailable")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, APIServerError)
        assert classified.status_code == 503

    def test_classify_content_filter_error(self, agent):
        """Test classification of content filtering errors."""
        error = Exception("Output blocked by content filtering policy")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, ContentFilterError)
        assert classified.original_error == error

    def test_classify_content_filter_error_variant(self, agent):
        """Test classification of content filtering errors with different message."""
        error = Exception("API Error: 400 content filtering blocked the response")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, ContentFilterError)

    def test_classify_unknown_error(self, agent):
        """Test classification of unknown errors."""
        error = Exception("Some unknown error")
        classified = agent._query_executor._classify_api_error(error)
        assert isinstance(classified, QueryExecutionError)
        assert classified.original_error == error


# =============================================================================
# AgentWrapper Process Message Tests
# =============================================================================


class TestAgentWrapperProcessMessage:
    """Tests for _process_message method."""

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

    def test_process_message_text_block(self, agent, capsys):
        """Test processing TextBlock messages."""
        text_block = MagicMock()
        type(text_block).__name__ = "TextBlock"
        text_block.text = "Hello, world!"

        mock_message = MagicMock()
        mock_message.content = [text_block]

        result = agent._message_processor.process_message(mock_message, "")

        assert result == "Hello, world!"
        captured = capsys.readouterr()
        assert "Hello, world!" in captured.out

    def test_process_message_accumulates_text(self, agent):
        """Test that text is accumulated from multiple blocks."""
        text_block1 = MagicMock()
        type(text_block1).__name__ = "TextBlock"
        text_block1.text = "First "

        text_block2 = MagicMock()
        type(text_block2).__name__ = "TextBlock"
        text_block2.text = "Second"

        mock_message = MagicMock()
        mock_message.content = [text_block1, text_block2]

        result = agent._message_processor.process_message(mock_message, "Initial ")

        assert result == "Initial First Second"

    def test_process_message_result_message(self, agent):
        """Test processing ResultMessage preserves accumulated text.

        The new behavior preserves accumulated text when it already has content,
        to ensure verification markers (VERIFICATION_RESULT: PASS/FAIL) are not lost.
        ResultMessage.result only replaces accumulated text when:
        1. Accumulated text is empty, or
        2. ResultMessage.result contains verification markers we're missing
        """
        result_message = MagicMock()
        type(result_message).__name__ = "ResultMessage"
        result_message.result = "Final result"
        result_message.content = None

        result = agent._message_processor.process_message(result_message, "Previous text")

        # New behavior: preserve accumulated text that has content
        assert result == "Previous text"

    def test_process_message_without_content(self, agent):
        """Test processing message without content."""
        mock_message = MagicMock()
        mock_message.content = None

        result = agent._message_processor.process_message(mock_message, "Unchanged")

        assert result == "Unchanged"
