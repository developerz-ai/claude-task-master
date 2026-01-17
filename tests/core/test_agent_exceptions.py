"""Tests for agent exception classes.

This module tests the exception hierarchy in agent_exceptions.py:
- AgentError (base exception)
- SDKImportError - SDK import failures
- SDKInitializationError - SDK initialization failures
- QueryExecutionError - Query execution failures
- APIRateLimitError - Rate limit errors
- APIConnectionError - Connection errors
- APITimeoutError - Timeout errors
- APIAuthenticationError - Authentication errors
- APIServerError - Server errors (5xx)
- ContentFilterError - Content filtering errors
- WorkingDirectoryError - Working directory errors
- TRANSIENT_ERRORS - Tuple of retryable errors
"""

import pytest

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
    __all__,
)

# =============================================================================
# AgentError Base Exception Tests
# =============================================================================


class TestAgentError:
    """Tests for AgentError base exception class."""

    def test_message_only(self):
        """Test AgentError with message only."""
        error = AgentError("Test error")
        assert error.message == "Test error"
        assert error.details is None
        assert str(error) == "Test error"

    def test_message_with_details(self):
        """Test AgentError with message and details."""
        error = AgentError("Test error", "Additional details")
        assert error.message == "Test error"
        assert error.details == "Additional details"
        assert "Test error" in str(error)
        assert "Details:" in str(error)
        assert "Additional details" in str(error)

    def test_inherits_from_exception(self):
        """Test AgentError inherits from Exception."""
        error = AgentError("Test")
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self):
        """Test AgentError can be raised and caught."""
        with pytest.raises(AgentError, match="Raised error") as exc_info:
            raise AgentError("Raised error", "With details")
        assert exc_info.value.details == "With details"

    def test_format_message_without_details(self):
        """Test _format_message returns message when no details."""
        error = AgentError("Just message")
        assert str(error) == "Just message"

    def test_format_message_with_details(self):
        """Test _format_message includes details properly."""
        error = AgentError("Main message", "Extra info")
        formatted = str(error)
        assert "Main message" in formatted
        assert "Details:" in formatted
        assert "Extra info" in formatted

    def test_empty_message(self):
        """Test AgentError with empty message."""
        error = AgentError("")
        assert error.message == ""
        assert str(error) == ""

    def test_empty_details(self):
        """Test AgentError with empty string details."""
        error = AgentError("Message", "")
        # Empty string is falsy, so details not included
        assert error.details == ""


# =============================================================================
# SDKImportError Tests
# =============================================================================


class TestSDKImportError:
    """Tests for SDKImportError exception class."""

    def test_without_original_error(self):
        """Test SDKImportError without original error."""
        error = SDKImportError()
        assert "claude-agent-sdk not installed" in error.message
        assert error.original_error is None
        # Should suggest installation when no original error
        assert "pip install" in str(error)

    def test_with_original_error(self):
        """Test SDKImportError with original exception."""
        original = ImportError("No module named 'claude_agent_sdk'")
        error = SDKImportError(original)
        assert error.original_error == original
        assert "claude_agent_sdk" in str(error)

    def test_inherits_from_agent_error(self):
        """Test SDKImportError inherits from AgentError."""
        error = SDKImportError()
        assert isinstance(error, AgentError)
        assert isinstance(error, Exception)

    def test_preserves_original_traceback_info(self):
        """Test that original error is preserved for debugging."""
        original = ImportError("Missing dependency xyz")
        error = SDKImportError(original)
        assert error.original_error is original
        assert "Missing dependency xyz" in str(error)

    def test_with_module_not_found_error(self):
        """Test SDKImportError with ModuleNotFoundError."""
        original = ModuleNotFoundError("No module named 'claude_agent_sdk'")
        error = SDKImportError(original)
        assert isinstance(error.original_error, ModuleNotFoundError)


# =============================================================================
# SDKInitializationError Tests
# =============================================================================


class TestSDKInitializationError:
    """Tests for SDKInitializationError exception class."""

    def test_basic(self):
        """Test SDKInitializationError with component and error."""
        original = AttributeError("query not found")
        error = SDKInitializationError("query", original)
        assert error.component == "query"
        assert error.original_error == original
        assert "query" in error.message

    def test_inherits_from_agent_error(self):
        """Test SDKInitializationError inherits from AgentError."""
        error = SDKInitializationError("test", ValueError("test"))
        assert isinstance(error, AgentError)

    def test_different_components(self):
        """Test SDKInitializationError with different SDK components."""
        components = ["query", "ClaudeAgentOptions", "MessageHandler", "StreamProcessor"]
        for component in components:
            error = SDKInitializationError(component, ValueError("failed"))
            assert component in error.message
            assert error.component == component

    def test_preserves_original_error_details(self):
        """Test that original error details are preserved."""
        original = TypeError("Expected callable, got str")
        error = SDKInitializationError("query", original)
        assert "Expected callable, got str" in str(error)


# =============================================================================
# QueryExecutionError Tests
# =============================================================================


class TestQueryExecutionError:
    """Tests for QueryExecutionError exception class."""

    def test_message_only(self):
        """Test QueryExecutionError with message only."""
        error = QueryExecutionError("Query failed")
        assert error.message == "Query failed"
        assert error.original_error is None

    def test_with_original_error(self):
        """Test QueryExecutionError with original exception."""
        original = RuntimeError("API error")
        error = QueryExecutionError("Query failed", original)
        assert error.original_error == original

    def test_inherits_from_agent_error(self):
        """Test QueryExecutionError inherits from AgentError."""
        error = QueryExecutionError("Test")
        assert isinstance(error, AgentError)

    def test_includes_original_in_str(self):
        """Test QueryExecutionError string representation includes original."""
        original = ValueError("Invalid parameter")
        error = QueryExecutionError("Query failed", original)
        error_str = str(error)
        assert "Query failed" in error_str
        assert "Invalid parameter" in error_str


# =============================================================================
# APIRateLimitError Tests
# =============================================================================


class TestAPIRateLimitError:
    """Tests for APIRateLimitError exception class."""

    def test_without_retry_after(self):
        """Test APIRateLimitError without retry_after."""
        error = APIRateLimitError()
        assert "rate limit" in error.message.lower()
        assert error.retry_after is None

    def test_with_retry_after(self):
        """Test APIRateLimitError with retry_after."""
        error = APIRateLimitError(retry_after=30.0)
        assert error.retry_after == 30.0
        assert "30" in error.message

    def test_inherits_from_query_execution_error(self):
        """Test APIRateLimitError inherits from QueryExecutionError."""
        error = APIRateLimitError()
        assert isinstance(error, QueryExecutionError)
        assert isinstance(error, AgentError)

    def test_is_transient(self):
        """Test APIRateLimitError is in TRANSIENT_ERRORS."""
        assert APIRateLimitError in TRANSIENT_ERRORS

    def test_with_original_error(self):
        """Test APIRateLimitError with original exception."""
        original = Exception("429 Too Many Requests")
        error = APIRateLimitError(retry_after=60.0, original_error=original)
        assert error.retry_after == 60.0
        assert error.original_error == original

    def test_various_retry_durations(self):
        """Test APIRateLimitError with various retry_after values."""
        durations = [1.0, 30.0, 60.0, 120.0, 300.0]
        for duration in durations:
            error = APIRateLimitError(retry_after=duration)
            assert error.retry_after == duration


# =============================================================================
# APIConnectionError Tests
# =============================================================================


class TestAPIConnectionError:
    """Tests for APIConnectionError exception class."""

    def test_basic(self):
        """Test APIConnectionError with original exception."""
        original = ConnectionError("Connection refused")
        error = APIConnectionError(original)
        assert "connect" in error.message.lower()
        assert error.original_error == original

    def test_inherits_from_query_execution_error(self):
        """Test APIConnectionError inherits from QueryExecutionError."""
        error = APIConnectionError(ConnectionError("test"))
        assert isinstance(error, QueryExecutionError)

    def test_is_transient(self):
        """Test APIConnectionError is in TRANSIENT_ERRORS."""
        assert APIConnectionError in TRANSIENT_ERRORS

    def test_various_causes(self):
        """Test APIConnectionError with various network errors."""
        causes = [
            ConnectionRefusedError("Connection refused"),
            OSError("Network unreachable"),
            Exception("DNS resolution failed"),
            ConnectionResetError("Connection reset by peer"),
        ]
        for cause in causes:
            error = APIConnectionError(cause)
            assert isinstance(error, APIConnectionError)
            assert error.original_error == cause


# =============================================================================
# APITimeoutError Tests
# =============================================================================


class TestAPITimeoutError:
    """Tests for APITimeoutError exception class."""

    def test_basic(self):
        """Test APITimeoutError with timeout value."""
        error = APITimeoutError(timeout=30.0)
        assert error.timeout == 30.0
        assert "30" in error.message
        assert "timed out" in error.message.lower()

    def test_inherits_from_query_execution_error(self):
        """Test APITimeoutError inherits from QueryExecutionError."""
        error = APITimeoutError(timeout=10.0)
        assert isinstance(error, QueryExecutionError)

    def test_is_transient(self):
        """Test APITimeoutError is in TRANSIENT_ERRORS."""
        assert APITimeoutError in TRANSIENT_ERRORS

    def test_with_original_error(self):
        """Test APITimeoutError with original exception."""
        original = TimeoutError("Request timeout")
        error = APITimeoutError(timeout=60.0, original_error=original)
        assert error.timeout == 60.0
        assert error.original_error == original

    def test_various_durations(self):
        """Test APITimeoutError with various timeout durations."""
        timeouts = [5.0, 30.0, 60.0, 120.0, 300.0]
        for timeout in timeouts:
            error = APITimeoutError(timeout=timeout)
            assert error.timeout == timeout


# =============================================================================
# APIAuthenticationError Tests
# =============================================================================


class TestAPIAuthenticationError:
    """Tests for APIAuthenticationError exception class."""

    def test_without_original_error(self):
        """Test APIAuthenticationError without original error."""
        error = APIAuthenticationError()
        assert "authentication" in error.message.lower()
        assert error.original_error is None

    def test_with_original_error(self):
        """Test APIAuthenticationError with original exception."""
        original = PermissionError("401 Unauthorized")
        error = APIAuthenticationError(original)
        assert error.original_error == original

    def test_inherits_from_query_execution_error(self):
        """Test APIAuthenticationError inherits from QueryExecutionError."""
        error = APIAuthenticationError()
        assert isinstance(error, QueryExecutionError)

    def test_not_transient(self):
        """Test APIAuthenticationError is NOT in TRANSIENT_ERRORS."""
        # Auth errors should not be retried automatically
        assert APIAuthenticationError not in TRANSIENT_ERRORS  # type: ignore[comparison-overlap]

    def test_mentions_credentials(self):
        """Test APIAuthenticationError message mentions credentials."""
        error = APIAuthenticationError()
        assert "credentials" in error.message.lower()


# =============================================================================
# APIServerError Tests
# =============================================================================


class TestAPIServerError:
    """Tests for APIServerError exception class."""

    def test_500(self):
        """Test APIServerError with 500 status."""
        error = APIServerError(status_code=500)
        assert error.status_code == 500
        assert "500" in error.message

    def test_502(self):
        """Test APIServerError with 502 status."""
        error = APIServerError(status_code=502)
        assert error.status_code == 502
        assert "502" in error.message

    def test_503(self):
        """Test APIServerError with 503 status."""
        error = APIServerError(status_code=503)
        assert error.status_code == 503
        assert "503" in error.message

    def test_504(self):
        """Test APIServerError with 504 status."""
        error = APIServerError(status_code=504)
        assert error.status_code == 504
        assert "504" in error.message

    def test_inherits_from_query_execution_error(self):
        """Test APIServerError inherits from QueryExecutionError."""
        error = APIServerError(status_code=500)
        assert isinstance(error, QueryExecutionError)

    def test_is_transient(self):
        """Test APIServerError is in TRANSIENT_ERRORS."""
        assert APIServerError in TRANSIENT_ERRORS

    def test_with_original_error(self):
        """Test APIServerError with original exception."""
        original = Exception("Internal Server Error")
        error = APIServerError(status_code=500, original_error=original)
        assert error.status_code == 500
        assert error.original_error == original

    def test_various_5xx_codes(self):
        """Test APIServerError with various 5xx status codes."""
        codes = [500, 501, 502, 503, 504, 505, 507, 508, 511]
        for code in codes:
            error = APIServerError(status_code=code)
            assert error.status_code == code
            assert str(code) in error.message


# =============================================================================
# ContentFilterError Tests
# =============================================================================


class TestContentFilterError:
    """Tests for ContentFilterError exception class."""

    def test_default_message(self):
        """Test ContentFilterError with default message."""
        error = ContentFilterError()
        assert "content filtering" in error.message.lower()
        # Should include documentation URL
        # CodeQL false positive: checking expected URL in error message, not user input
        expected_url = "privacy.claude.com"  # lgtm[py/incomplete-url-substring-sanitization]
        assert expected_url in error.message  # lgtm[py/incomplete-url-substring-sanitization]

    def test_with_original_error(self):
        """Test ContentFilterError with original exception."""
        original = Exception("Output blocked by content filtering policy")
        error = ContentFilterError(original)
        assert error.original_error == original
        assert error.details is not None

    def test_inherits_from_query_execution_error(self):
        """Test ContentFilterError inherits from QueryExecutionError."""
        error = ContentFilterError()
        assert isinstance(error, QueryExecutionError)
        assert isinstance(error, AgentError)

    def test_not_transient(self):
        """Test ContentFilterError is NOT in TRANSIENT_ERRORS."""
        # Content filter errors should not be retried
        assert ContentFilterError not in TRANSIENT_ERRORS  # type: ignore[comparison-overlap]

    def test_suggests_rephrasing(self):
        """Test ContentFilterError suggests rephrasing."""
        error = ContentFilterError()
        msg = error.message.lower()
        assert "rephras" in msg or "smaller tasks" in msg


# =============================================================================
# WorkingDirectoryError Tests
# =============================================================================


class TestWorkingDirectoryError:
    """Tests for WorkingDirectoryError exception class."""

    def test_basic(self):
        """Test WorkingDirectoryError with all parameters."""
        original = FileNotFoundError("Directory not found")
        error = WorkingDirectoryError("/test/dir", "change to", original)
        assert error.path == "/test/dir"
        assert error.operation == "change to"
        assert error.original_error == original
        assert "/test/dir" in error.message

    def test_inherits_from_agent_error(self):
        """Test WorkingDirectoryError inherits from AgentError."""
        error = WorkingDirectoryError("/test", "access", OSError("test"))
        assert isinstance(error, AgentError)

    def test_various_operations(self):
        """Test WorkingDirectoryError with various operations."""
        operations = ["change to", "access", "create", "delete", "read from"]
        for op in operations:
            error = WorkingDirectoryError("/test/path", op, OSError("error"))
            assert op in error.message
            assert error.operation == op

    def test_preserves_path(self):
        """Test WorkingDirectoryError preserves the path."""
        paths = ["/home/user/project", "./relative", "/tmp/test", "C:\\Windows\\Path"]
        for path in paths:
            error = WorkingDirectoryError(path, "access", OSError("error"))
            assert error.path == path
            assert path in error.message

    def test_preserves_original_error(self):
        """Test WorkingDirectoryError preserves original error."""
        original = PermissionError("Permission denied")
        error = WorkingDirectoryError("/protected", "access", original)
        assert error.original_error is original
        assert "Permission denied" in str(error)


# =============================================================================
# TRANSIENT_ERRORS Constant Tests
# =============================================================================


class TestTransientErrors:
    """Tests for TRANSIENT_ERRORS constant."""

    def test_is_tuple(self):
        """Test TRANSIENT_ERRORS is a tuple for isinstance checks."""
        assert isinstance(TRANSIENT_ERRORS, tuple)

    def test_contains_rate_limit(self):
        """Test TRANSIENT_ERRORS contains APIRateLimitError."""
        assert APIRateLimitError in TRANSIENT_ERRORS

    def test_contains_connection(self):
        """Test TRANSIENT_ERRORS contains APIConnectionError."""
        assert APIConnectionError in TRANSIENT_ERRORS

    def test_contains_timeout(self):
        """Test TRANSIENT_ERRORS contains APITimeoutError."""
        assert APITimeoutError in TRANSIENT_ERRORS

    def test_contains_server(self):
        """Test TRANSIENT_ERRORS contains APIServerError."""
        assert APIServerError in TRANSIENT_ERRORS

    def test_excludes_auth(self):
        """Test TRANSIENT_ERRORS excludes APIAuthenticationError."""
        assert APIAuthenticationError not in TRANSIENT_ERRORS  # type: ignore[comparison-overlap]

    def test_excludes_content_filter(self):
        """Test TRANSIENT_ERRORS excludes ContentFilterError."""
        assert ContentFilterError not in TRANSIENT_ERRORS  # type: ignore[comparison-overlap]

    def test_all_inherit_from_query_execution_error(self):
        """Test all TRANSIENT_ERRORS inherit from QueryExecutionError."""
        for error_class in TRANSIENT_ERRORS:
            assert issubclass(error_class, QueryExecutionError)

    def test_len(self):
        """Test TRANSIENT_ERRORS has expected number of errors."""
        assert len(TRANSIENT_ERRORS) == 4

    def test_can_use_with_isinstance(self):
        """Test TRANSIENT_ERRORS works with isinstance checks."""
        transient_instances = [
            APIRateLimitError(),
            APIConnectionError(Exception("test")),
            APITimeoutError(timeout=30.0),
            APIServerError(status_code=500),
        ]
        for instance in transient_instances:
            assert isinstance(instance, TRANSIENT_ERRORS)

        non_transient_instances = [
            APIAuthenticationError(),
            ContentFilterError(),
            QueryExecutionError("test"),
        ]
        for instance in non_transient_instances:
            assert not isinstance(instance, TRANSIENT_ERRORS)


# =============================================================================
# Module __all__ Exports Tests
# =============================================================================


class TestModuleExports:
    """Tests for module __all__ exports."""

    def test_all_contains_all_exceptions(self):
        """Test __all__ contains all exception classes."""
        expected = [
            "AgentError",
            "SDKImportError",
            "SDKInitializationError",
            "QueryExecutionError",
            "APIRateLimitError",
            "APIConnectionError",
            "APITimeoutError",
            "APIAuthenticationError",
            "APIServerError",
            "ContentFilterError",
            "WorkingDirectoryError",
        ]
        for name in expected:
            assert name in __all__, f"{name} not in __all__"

    def test_all_contains_transient_errors(self):
        """Test __all__ contains TRANSIENT_ERRORS."""
        assert "TRANSIENT_ERRORS" in __all__

    def test_all_has_expected_length(self):
        """Test __all__ has expected number of exports."""
        # 11 exception classes + TRANSIENT_ERRORS
        assert len(__all__) == 12

    def test_exported_classes_are_importable(self):
        """Test all exported names can be imported."""
        from claude_task_master.core import agent_exceptions

        for name in __all__:
            assert hasattr(agent_exceptions, name), f"{name} not importable"


# =============================================================================
# Exception Hierarchy Tests
# =============================================================================


class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_base_hierarchy(self):
        """Test base exception hierarchy."""
        # All custom exceptions inherit from AgentError
        assert issubclass(SDKImportError, AgentError)
        assert issubclass(SDKInitializationError, AgentError)
        assert issubclass(QueryExecutionError, AgentError)
        assert issubclass(WorkingDirectoryError, AgentError)

    def test_query_execution_subclasses(self):
        """Test QueryExecutionError subclass hierarchy."""
        subclasses = [
            APIRateLimitError,
            APIConnectionError,
            APITimeoutError,
            APIAuthenticationError,
            APIServerError,
            ContentFilterError,
        ]
        for cls in subclasses:
            assert issubclass(cls, QueryExecutionError)
            assert issubclass(cls, AgentError)
            assert issubclass(cls, Exception)

    def test_exception_mro(self):
        """Test method resolution order for exceptions."""
        # APIRateLimitError MRO: APIRateLimitError -> QueryExecutionError -> AgentError -> Exception
        mro_names = [c.__name__ for c in APIRateLimitError.__mro__]
        assert "APIRateLimitError" in mro_names
        assert "QueryExecutionError" in mro_names
        assert "AgentError" in mro_names
        assert "Exception" in mro_names
        # QueryExecutionError should come before AgentError
        assert mro_names.index("QueryExecutionError") < mro_names.index("AgentError")

    def test_catching_base_class_catches_subclasses(self):
        """Test catching AgentError catches all subclasses."""
        exceptions_to_test = [
            SDKImportError(),
            SDKInitializationError("test", ValueError("test")),
            QueryExecutionError("test"),
            APIRateLimitError(),
            APIConnectionError(Exception("test")),
            APITimeoutError(timeout=30.0),
            APIAuthenticationError(),
            APIServerError(status_code=500),
            ContentFilterError(),
            WorkingDirectoryError("/test", "test", OSError("test")),
        ]

        for exc in exceptions_to_test:
            with pytest.raises(AgentError):
                raise exc

    def test_catching_query_execution_error_catches_api_errors(self):
        """Test catching QueryExecutionError catches API subclasses."""
        api_exceptions = [
            APIRateLimitError(),
            APIConnectionError(Exception("test")),
            APITimeoutError(timeout=30.0),
            APIAuthenticationError(),
            APIServerError(status_code=500),
            ContentFilterError(),
        ]

        for exc in api_exceptions:
            with pytest.raises(QueryExecutionError):
                raise exc


# =============================================================================
# Edge Cases and Special Behavior Tests
# =============================================================================


class TestEdgeCases:
    """Edge case tests for exception handling."""

    def test_error_chaining(self):
        """Test that errors can be chained properly."""
        original = ValueError("Root cause")
        query_error = QueryExecutionError("Query failed", original)
        assert query_error.original_error == original
        assert "Root cause" in str(query_error)

    def test_nested_exception_chaining(self):
        """Test nested exception chaining."""
        middle = RuntimeError("Processing failed")
        outer = QueryExecutionError("Query failed", middle)

        assert outer.original_error == middle
        # Middle doesn't have original_error attribute by default
        # but our QueryExecutionError preserves it

    def test_exception_repr(self):
        """Test exception representations are useful."""
        error = AgentError("Test message", "Test details")
        # Should have useful string representation
        assert "Test message" in str(error)

    def test_exception_args(self):
        """Test exception args attribute."""
        error = AgentError("Test message", "Test details")
        # Exception.args should contain the formatted message
        assert len(error.args) == 1
        assert "Test message" in error.args[0]

    def test_rate_limit_zero_retry(self):
        """Test APIRateLimitError with zero retry_after."""
        error = APIRateLimitError(retry_after=0.0)
        assert error.retry_after == 0.0
        # Note: 0.0 is falsy, so message won't include retry time
        assert "rate limit" in error.message.lower()

    def test_timeout_zero_duration(self):
        """Test APITimeoutError with zero timeout."""
        error = APITimeoutError(timeout=0.0)
        assert error.timeout == 0.0

    def test_server_error_non_5xx_code(self):
        """Test APIServerError with non-5xx code (edge case)."""
        # While semantically wrong, the class doesn't validate
        error = APIServerError(status_code=404)
        assert error.status_code == 404
        assert "404" in error.message
