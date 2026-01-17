"""Tests for agent error classification and exception handling.

This module contains tests for:
- Exception class hierarchy (AgentError, QueryExecutionError, etc.)
- Error classification (_classify_api_error method)
- Working directory error handling
- SDK import and initialization errors
- TRANSIENT_ERRORS constant
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_task_master.core.agent import AgentWrapper, ModelType
from claude_task_master.core.agent_exceptions import (
    TRANSIENT_ERRORS,
    AgentError,
    APIAuthenticationError,
    APIConnectionError,
    APIRateLimitError,
    APIServerError,
    APITimeoutError,
    ContentFilterError,
    QueryExecutionError,
    SDKImportError,
    SDKInitializationError,
    WorkingDirectoryError,
)

# =============================================================================
# AgentError Base Exception Tests
# =============================================================================


class TestAgentError:
    """Tests for AgentError base exception class."""

    def test_agent_error_basic(self):
        """Test AgentError with message only."""
        error = AgentError("Test error")
        assert error.message == "Test error"
        assert error.details is None
        assert str(error) == "Test error"

    def test_agent_error_with_details(self):
        """Test AgentError with message and details."""
        error = AgentError("Test error", "Additional details")
        assert error.message == "Test error"
        assert error.details == "Additional details"
        assert "Test error" in str(error)
        assert "Additional details" in str(error)

    def test_agent_error_inheritance(self):
        """Test AgentError inherits from Exception."""
        error = AgentError("Test")
        assert isinstance(error, Exception)

    def test_agent_error_can_be_raised(self):
        """Test AgentError can be raised and caught."""
        with pytest.raises(AgentError, match="Raised error") as exc_info:
            raise AgentError("Raised error", "With details")
        # CodeQL false positive: pytest.raises() catches the exception and allows
        # code to continue after the with block. This IS reachable and is standard pytest.
        error = exc_info.value  # lgtm[py/unreachable-statement]
        assert error.details == "With details"

    def test_agent_error_format_message_with_details(self):
        """Test _format_message includes details properly."""
        error = AgentError("Main message", "Extra info")
        formatted = str(error)
        assert "Main message" in formatted
        assert "Details:" in formatted
        assert "Extra info" in formatted


# =============================================================================
# SDKImportError Exception Tests
# =============================================================================


class TestSDKImportError:
    """Tests for SDKImportError exception class."""

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

    def test_sdk_import_error_inheritance(self):
        """Test SDKImportError inherits from AgentError."""
        error = SDKImportError()
        assert isinstance(error, AgentError)

    def test_sdk_import_error_includes_install_hint(self):
        """Test SDKImportError suggests installation command."""
        error = SDKImportError()
        # When no original error, details should suggest installation
        assert "pip install" in str(error) or error.details is not None


# =============================================================================
# SDKInitializationError Exception Tests
# =============================================================================


class TestSDKInitializationError:
    """Tests for SDKInitializationError exception class."""

    def test_sdk_init_error_basic(self):
        """Test SDKInitializationError with component and error."""
        original = AttributeError("query not found")
        error = SDKInitializationError("query", original)
        assert error.component == "query"
        assert error.original_error == original
        assert "query" in error.message

    def test_sdk_init_error_inheritance(self):
        """Test SDKInitializationError inherits from AgentError."""
        error = SDKInitializationError("test", ValueError("test"))
        assert isinstance(error, AgentError)

    def test_sdk_init_error_different_components(self):
        """Test SDKInitializationError with different SDK components."""
        components = ["query", "ClaudeAgentOptions", "MessageHandler"]
        for component in components:
            error = SDKInitializationError(component, ValueError("failed"))
            assert component in error.message

    def test_sdk_init_error_preserves_original_error_details(self):
        """Test that original error details are preserved."""
        original = TypeError("Expected callable, got str")
        error = SDKInitializationError("query", original)
        assert "Expected callable, got str" in str(error)


# =============================================================================
# QueryExecutionError Exception Tests
# =============================================================================


class TestQueryExecutionError:
    """Tests for QueryExecutionError exception class."""

    def test_query_execution_error_basic(self):
        """Test QueryExecutionError with message only."""
        error = QueryExecutionError("Query failed")
        assert error.message == "Query failed"
        assert error.original_error is None

    def test_query_execution_error_with_original(self):
        """Test QueryExecutionError with original exception."""
        original = RuntimeError("API error")
        error = QueryExecutionError("Query failed", original)
        assert error.original_error == original

    def test_query_execution_error_inheritance(self):
        """Test QueryExecutionError inherits from AgentError."""
        error = QueryExecutionError("Test")
        assert isinstance(error, AgentError)

    def test_query_execution_error_includes_original_in_str(self):
        """Test QueryExecutionError string representation includes original."""
        original = ValueError("Invalid parameter")
        error = QueryExecutionError("Query failed", original)
        error_str = str(error)
        assert "Query failed" in error_str
        assert "Invalid parameter" in error_str


# =============================================================================
# APIRateLimitError Exception Tests
# =============================================================================


class TestAPIRateLimitError:
    """Tests for APIRateLimitError exception class."""

    def test_rate_limit_error_basic(self):
        """Test APIRateLimitError without retry_after."""
        error = APIRateLimitError()
        assert "rate limit" in error.message.lower()
        assert error.retry_after is None

    def test_rate_limit_error_with_retry_after(self):
        """Test APIRateLimitError with retry_after."""
        error = APIRateLimitError(retry_after=30.0)
        assert error.retry_after == 30.0
        assert "30" in error.message

    def test_rate_limit_error_inheritance(self):
        """Test APIRateLimitError inherits from QueryExecutionError."""
        error = APIRateLimitError()
        assert isinstance(error, QueryExecutionError)
        assert isinstance(error, AgentError)

    def test_rate_limit_error_is_transient(self):
        """Test APIRateLimitError is in TRANSIENT_ERRORS."""
        assert APIRateLimitError in TRANSIENT_ERRORS

    def test_rate_limit_error_with_original(self):
        """Test APIRateLimitError with original exception."""
        original = Exception("429 Too Many Requests")
        error = APIRateLimitError(retry_after=60.0, original_error=original)
        assert error.retry_after == 60.0


# =============================================================================
# APIConnectionError Exception Tests
# =============================================================================


class TestAPIConnectionError:
    """Tests for APIConnectionError exception class."""

    def test_connection_error_basic(self):
        """Test APIConnectionError with original exception."""
        original = ConnectionError("Connection refused")
        error = APIConnectionError(original)
        assert "connect" in error.message.lower()
        assert error.original_error == original

    def test_connection_error_inheritance(self):
        """Test APIConnectionError inherits from QueryExecutionError."""
        error = APIConnectionError(ConnectionError("test"))
        assert isinstance(error, QueryExecutionError)

    def test_connection_error_is_transient(self):
        """Test APIConnectionError is in TRANSIENT_ERRORS."""
        assert APIConnectionError in TRANSIENT_ERRORS

    def test_connection_error_various_causes(self):
        """Test APIConnectionError with various network errors."""
        causes = [
            ConnectionRefusedError("Connection refused"),
            OSError("Network unreachable"),
            Exception("DNS resolution failed"),
        ]
        for cause in causes:
            error = APIConnectionError(cause)
            assert isinstance(error, APIConnectionError)


# =============================================================================
# APITimeoutError Exception Tests
# =============================================================================


class TestAPITimeoutError:
    """Tests for APITimeoutError exception class."""

    def test_timeout_error_basic(self):
        """Test APITimeoutError with timeout value."""
        error = APITimeoutError(timeout=30.0)
        assert error.timeout == 30.0
        assert "30" in error.message
        assert "timed out" in error.message.lower()

    def test_timeout_error_inheritance(self):
        """Test APITimeoutError inherits from QueryExecutionError."""
        error = APITimeoutError(timeout=10.0)
        assert isinstance(error, QueryExecutionError)

    def test_timeout_error_is_transient(self):
        """Test APITimeoutError is in TRANSIENT_ERRORS."""
        assert APITimeoutError in TRANSIENT_ERRORS

    def test_timeout_error_with_original(self):
        """Test APITimeoutError with original exception."""
        original = TimeoutError("Request timeout")
        error = APITimeoutError(timeout=60.0, original_error=original)
        assert error.timeout == 60.0

    def test_timeout_error_various_durations(self):
        """Test APITimeoutError with various timeout durations."""
        timeouts = [5.0, 30.0, 60.0, 120.0]
        for timeout in timeouts:
            error = APITimeoutError(timeout=timeout)
            assert error.timeout == timeout
            assert str(int(timeout)) in error.message


# =============================================================================
# APIAuthenticationError Exception Tests
# =============================================================================


class TestAPIAuthenticationError:
    """Tests for APIAuthenticationError exception class."""

    def test_auth_error_basic(self):
        """Test APIAuthenticationError without original error."""
        error = APIAuthenticationError()
        assert "authentication" in error.message.lower()

    def test_auth_error_with_original(self):
        """Test APIAuthenticationError with original exception."""
        original = PermissionError("401 Unauthorized")
        error = APIAuthenticationError(original)
        assert error.original_error == original

    def test_auth_error_inheritance(self):
        """Test APIAuthenticationError inherits from QueryExecutionError."""
        error = APIAuthenticationError()
        assert isinstance(error, QueryExecutionError)

    def test_auth_error_not_transient(self):
        """Test APIAuthenticationError is NOT in TRANSIENT_ERRORS."""
        # Intentionally check that auth errors are not in transient errors
        assert APIAuthenticationError not in TRANSIENT_ERRORS  # type: ignore[comparison-overlap]

    def test_auth_error_mentions_credentials(self):
        """Test APIAuthenticationError message mentions credentials."""
        error = APIAuthenticationError()
        assert "credentials" in error.message.lower() or "authentication" in error.message.lower()


# =============================================================================
# APIServerError Exception Tests
# =============================================================================


class TestAPIServerError:
    """Tests for APIServerError exception class."""

    def test_server_error_basic(self):
        """Test APIServerError with status code."""
        error = APIServerError(status_code=500)
        assert error.status_code == 500
        assert "500" in error.message

    def test_server_error_502(self):
        """Test APIServerError with 502 status."""
        error = APIServerError(status_code=502)
        assert error.status_code == 502
        assert "502" in error.message

    def test_server_error_503(self):
        """Test APIServerError with 503 status."""
        error = APIServerError(status_code=503)
        assert error.status_code == 503
        assert "503" in error.message

    def test_server_error_inheritance(self):
        """Test APIServerError inherits from QueryExecutionError."""
        error = APIServerError(status_code=500)
        assert isinstance(error, QueryExecutionError)

    def test_server_error_is_transient(self):
        """Test APIServerError is in TRANSIENT_ERRORS."""
        assert APIServerError in TRANSIENT_ERRORS

    def test_server_error_various_codes(self):
        """Test APIServerError with various 5xx status codes."""
        codes = [500, 501, 502, 503, 504]
        for code in codes:
            error = APIServerError(status_code=code)
            assert error.status_code == code
            assert str(code) in error.message


# =============================================================================
# ContentFilterError Exception Tests
# =============================================================================


class TestContentFilterError:
    """Tests for ContentFilterError exception class."""

    def test_content_filter_error_basic(self):
        """Test ContentFilterError with default message."""
        error = ContentFilterError()
        assert "content filtering" in error.message.lower()
        # Check that the message includes the privacy URL for user documentation.
        # CodeQL false positive: This URL is an intentional, hardcoded help link -
        # not user-controlled input requiring sanitization.
        privacy_url = "privacy.claude.com"  # noqa: S105 - not a password  # lgtm[py/incomplete-url-substring-sanitization]
        assert privacy_url in error.message  # lgtm[py/incomplete-url-substring-sanitization]

    def test_content_filter_error_with_original(self):
        """Test ContentFilterError with original exception."""
        original = Exception("Output blocked by content filtering policy")
        error = ContentFilterError(original)
        assert error.original_error == original
        assert error.details is not None

    def test_content_filter_error_inheritance(self):
        """Test ContentFilterError inherits from QueryExecutionError."""
        error = ContentFilterError()
        assert isinstance(error, QueryExecutionError)
        assert isinstance(error, AgentError)

    def test_content_filter_error_not_retryable(self):
        """Test that ContentFilterError is not in transient errors."""
        # ContentFilterError should NOT be retryable
        # Intentionally check that content filter errors are not in transient errors
        assert ContentFilterError not in TRANSIENT_ERRORS  # type: ignore[comparison-overlap]

    def test_content_filter_error_suggests_rephrasing(self):
        """Test ContentFilterError suggests rephrasing."""
        error = ContentFilterError()
        assert "rephras" in error.message.lower() or "smaller tasks" in error.message.lower()


# =============================================================================
# WorkingDirectoryError Exception Tests
# =============================================================================


class TestWorkingDirectoryError:
    """Tests for WorkingDirectoryError exception class."""

    def test_working_dir_error_basic(self):
        """Test WorkingDirectoryError with all parameters."""
        original = FileNotFoundError("Directory not found")
        error = WorkingDirectoryError("/test/dir", "change to", original)
        assert error.path == "/test/dir"
        assert error.operation == "change to"
        assert error.original_error == original
        assert "/test/dir" in error.message

    def test_working_dir_error_inheritance(self):
        """Test WorkingDirectoryError inherits from AgentError."""
        error = WorkingDirectoryError("/test", "access", OSError("test"))
        assert isinstance(error, AgentError)

    def test_working_dir_error_various_operations(self):
        """Test WorkingDirectoryError with various operations."""
        operations = ["change to", "access", "create", "delete", "read from"]
        for op in operations:
            error = WorkingDirectoryError("/test/path", op, OSError("error"))
            assert op in error.message

    def test_working_dir_error_preserves_path(self):
        """Test WorkingDirectoryError preserves the path."""
        paths = ["/home/user/project", "./relative", "C:\\Windows\\Path"]
        for path in paths:
            error = WorkingDirectoryError(path, "access", OSError("error"))
            assert error.path == path
            assert path in error.message


# =============================================================================
# TRANSIENT_ERRORS Constant Tests
# =============================================================================


class TestTransientErrors:
    """Tests for TRANSIENT_ERRORS constant."""

    def test_transient_errors_contains_rate_limit(self):
        """Test TRANSIENT_ERRORS contains APIRateLimitError."""
        assert APIRateLimitError in TRANSIENT_ERRORS

    def test_transient_errors_contains_connection(self):
        """Test TRANSIENT_ERRORS contains APIConnectionError."""
        assert APIConnectionError in TRANSIENT_ERRORS

    def test_transient_errors_contains_timeout(self):
        """Test TRANSIENT_ERRORS contains APITimeoutError."""
        assert APITimeoutError in TRANSIENT_ERRORS

    def test_transient_errors_contains_server(self):
        """Test TRANSIENT_ERRORS contains APIServerError."""
        assert APIServerError in TRANSIENT_ERRORS

    def test_transient_errors_excludes_auth(self):
        """Test TRANSIENT_ERRORS excludes APIAuthenticationError."""
        # Intentionally check that auth errors are excluded from transient errors
        assert APIAuthenticationError not in TRANSIENT_ERRORS  # type: ignore[comparison-overlap]

    def test_transient_errors_excludes_content_filter(self):
        """Test TRANSIENT_ERRORS excludes ContentFilterError."""
        # Intentionally check that content filter errors are excluded from transient errors
        assert ContentFilterError not in TRANSIENT_ERRORS  # type: ignore[comparison-overlap]

    def test_transient_errors_is_tuple(self):
        """Test TRANSIENT_ERRORS is a tuple for isinstance checks."""
        assert isinstance(TRANSIENT_ERRORS, tuple)

    def test_transient_errors_all_inherit_from_query_execution_error(self):
        """Test all TRANSIENT_ERRORS inherit from QueryExecutionError."""
        for error_class in TRANSIENT_ERRORS:
            assert issubclass(error_class, QueryExecutionError)


# =============================================================================
# AgentWrapper Error Classification Tests
# =============================================================================


class TestAgentWrapperErrorClassification:
    """Tests for error classification in AgentWrapper."""

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
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIRateLimitError)

    def test_classify_rate_limit_error_variant(self, agent):
        """Test classification of rate limit error with different message."""
        error = Exception("Rate limit: too many requests")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIRateLimitError)

    def test_classify_auth_error_401(self, agent):
        """Test classification of 401 auth error."""
        error = Exception("HTTP 401 Unauthorized")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIAuthenticationError)

    def test_classify_auth_error_403(self, agent):
        """Test classification of 403 auth error."""
        error = Exception("HTTP 403 Forbidden")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIAuthenticationError)

    def test_classify_auth_error_unauthorized(self, agent):
        """Test classification of 'unauthorized' error."""
        error = Exception("Unauthorized access to API")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIAuthenticationError)

    def test_classify_timeout_error(self, agent):
        """Test classification of timeout errors."""
        error = Exception("Request timeout after 30 seconds")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APITimeoutError)

    def test_classify_timeout_error_timed_out(self, agent):
        """Test classification of 'timeout' keyword error."""
        # The implementation checks for 'timeout' keyword, not 'timed out'
        error = Exception("Request timeout exceeded")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APITimeoutError)

    def test_classify_connection_error(self, agent):
        """Test classification of connection errors."""
        error = Exception("Connection refused")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIConnectionError)

    def test_classify_network_error(self, agent):
        """Test classification of network errors."""
        error = Exception("Network unreachable")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIConnectionError)

    def test_classify_connection_failed(self, agent):
        """Test classification of 'connection failed' error."""
        error = Exception("Connection failed to server")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIConnectionError)

    def test_classify_server_error_500(self, agent):
        """Test classification of 500 server errors."""
        error = Exception("HTTP 500 Internal Server Error")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIServerError)
        assert classified.status_code == 500

    def test_classify_server_error_502(self, agent):
        """Test classification of 502 server errors."""
        error = Exception("HTTP 502 Bad Gateway")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIServerError)
        assert classified.status_code == 502

    def test_classify_server_error_503(self, agent):
        """Test classification of 503 server errors."""
        error = Exception("HTTP 503 Service Unavailable")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIServerError)
        assert classified.status_code == 503

    def test_classify_server_error_504(self, agent):
        """Test classification of 504 server errors.

        Note: If the error message contains 'timeout' (like 'Gateway Timeout'),
        it may be classified as APITimeoutError instead due to pattern matching order.
        Use a message without 'timeout' to test pure 504 classification.
        """
        error = Exception("HTTP 504 Bad Gateway")  # Avoid 'timeout' keyword
        classified = agent._classify_api_error(error)
        assert isinstance(classified, APIServerError)
        assert classified.status_code == 504

    def test_classify_content_filter_error(self, agent):
        """Test classification of content filtering errors."""
        error = Exception("Output blocked by content filtering policy")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, ContentFilterError)
        assert classified.original_error == error

    def test_classify_content_filter_error_variant(self, agent):
        """Test classification of content filtering errors with different message."""
        error = Exception("API Error: 400 content filtering blocked the response")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, ContentFilterError)

    def test_classify_unknown_error(self, agent):
        """Test classification of unknown errors."""
        error = Exception("Some unknown error")
        classified = agent._classify_api_error(error)
        assert isinstance(classified, QueryExecutionError)
        assert classified.original_error == error

    def test_classify_preserves_original_error(self, agent):
        """Test that classification preserves original error reference."""
        original = ValueError("Custom API error")
        classified = agent._classify_api_error(original)
        assert classified.original_error == original

    def test_classify_case_insensitive(self, agent):
        """Test that error classification is case-insensitive."""
        error_lower = Exception("rate limit exceeded")
        error_upper = Exception("RATE LIMIT EXCEEDED")
        error_mixed = Exception("Rate Limit Exceeded")

        for error in [error_lower, error_upper, error_mixed]:
            classified = agent._classify_api_error(error)
            assert isinstance(classified, APIRateLimitError)


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
            await agent._execute_query("test prompt", ["Read"])

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
                await agent._execute_query("test prompt", ["Read"])

            assert "access" in exc_info.value.operation

    @pytest.mark.asyncio
    async def test_working_directory_error_includes_path(self, temp_dir):
        """Test WorkingDirectoryError includes the path that failed."""
        mock_sdk = MagicMock()
        mock_sdk.query = AsyncMock()
        mock_sdk.ClaudeAgentOptions = MagicMock()

        nonexistent_path = "/path/that/does/not/exist"
        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            agent = AgentWrapper(
                access_token="test-token",
                model=ModelType.SONNET,
                working_dir=nonexistent_path,
            )

        with pytest.raises(WorkingDirectoryError) as exc_info:
            await agent._execute_query("test prompt", ["Read"])

        assert nonexistent_path in str(exc_info.value)


# =============================================================================
# AgentWrapper SDK Import Error Tests
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

    def test_sdk_import_error_handling(self):
        """Test handling when SDK import completely fails."""
        # Simulate the SDK not being installed at all
        with patch.dict("sys.modules", {"claude_agent_sdk": None}):
            with pytest.raises(SDKImportError) as exc_info:
                # Force the import to fail
                with patch("builtins.__import__", side_effect=ImportError):
                    AgentWrapper(
                        access_token="test-token",
                        model=ModelType.SONNET,
                    )

        assert "claude-agent-sdk not installed" in str(exc_info.value)


# =============================================================================
# Error Handling Edge Cases Tests
# =============================================================================


class TestErrorHandlingEdgeCases:
    """Edge case tests for error handling."""

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

    def test_classify_empty_error_message(self, agent):
        """Test classification of error with empty message."""
        error = Exception("")
        classified = agent._classify_api_error(error)
        # Should fall back to generic QueryExecutionError
        assert isinstance(classified, QueryExecutionError)

    def test_classify_none_like_error(self, agent):
        """Test classification with minimal error."""
        error = Exception()
        classified = agent._classify_api_error(error)
        assert isinstance(classified, QueryExecutionError)

    def test_error_chaining(self):
        """Test that errors can be chained properly."""
        original = ValueError("Root cause")
        query_error = QueryExecutionError("Query failed", original)
        assert query_error.original_error == original
        assert "Root cause" in str(query_error)

    def test_error_multiple_indicators(self, agent):
        """Test classification when error has multiple indicators."""
        # Error with both timeout and rate limit indicators
        # Should match first pattern checked
        error = Exception("Timeout while waiting for rate limit")
        classified = agent._classify_api_error(error)
        # The actual classification depends on implementation order
        assert isinstance(classified, (APITimeoutError, APIRateLimitError))

    def test_transient_error_isinstance_check(self):
        """Test that isinstance works with TRANSIENT_ERRORS tuple."""
        rate_limit = APIRateLimitError()
        connection = APIConnectionError(Exception("test"))
        timeout = APITimeoutError(timeout=30.0)
        server = APIServerError(status_code=500)
        auth = APIAuthenticationError()

        # Transient errors should match
        assert isinstance(rate_limit, TRANSIENT_ERRORS)
        assert isinstance(connection, TRANSIENT_ERRORS)
        assert isinstance(timeout, TRANSIENT_ERRORS)
        assert isinstance(server, TRANSIENT_ERRORS)

        # Non-transient should not match
        assert not isinstance(auth, TRANSIENT_ERRORS)
