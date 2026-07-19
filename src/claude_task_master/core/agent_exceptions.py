"""Agent Exception Classes - Custom exceptions for agent operations.

This module provides a hierarchy of exceptions for handling various error conditions
that can occur during Claude Agent SDK interactions.

Exception Hierarchy:
    AgentError (base)
    ├── SDKImportError - SDK cannot be imported
    ├── SDKInitializationError - SDK components cannot be initialized
    ├── WorkingDirectoryError - Working directory issues
    └── QueryExecutionError - Query execution failures
        ├── APIRateLimitError - Rate limit exceeded
        ├── APIConnectionError - Connection failures
        ├── APITimeoutError - Request timeouts
        ├── APIAuthenticationError - Auth failures
        ├── APIServerError - Server errors (5xx)
        ├── ContentFilterError - Content filtering blocks
        └── ModelUnavailableError - Requested model unavailable (fallback-chain recoverable)
"""


class AgentError(Exception):
    """Base exception for all agent-related errors."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class SDKImportError(AgentError):
    """Raised when the Claude Agent SDK cannot be imported."""

    def __init__(self, original_error: Exception | None = None):
        self.original_error = original_error
        details = str(original_error) if original_error else None
        super().__init__(
            "claude-agent-sdk not installed or cannot be imported",
            details or "Install with: pip install claude-agent-sdk",
        )


class SDKInitializationError(AgentError):
    """Raised when SDK components cannot be initialized."""

    def __init__(self, component: str, original_error: Exception):
        self.component = component
        self.original_error = original_error
        super().__init__(
            f"Failed to initialize SDK component: {component}",
            str(original_error),
        )


class QueryExecutionError(AgentError):
    """Raised when a query execution fails."""

    def __init__(self, message: str, original_error: Exception | None = None):
        self.original_error = original_error
        details = str(original_error) if original_error else None
        super().__init__(message, details)


class APIRateLimitError(QueryExecutionError):
    """Raised when API rate limit is exceeded."""

    def __init__(self, retry_after: float | None = None, original_error: Exception | None = None):
        self.retry_after = retry_after
        message = "API rate limit exceeded"
        if retry_after:
            message += f" (retry after {retry_after} seconds)"
        super().__init__(message, original_error)


class APIConnectionError(QueryExecutionError):
    """Raised when there's a connection error to the API."""

    def __init__(self, original_error: Exception):
        super().__init__(
            "Failed to connect to Claude API",
            original_error,
        )


class APITimeoutError(QueryExecutionError):
    """Raised when API request times out."""

    def __init__(self, timeout: float, original_error: Exception | None = None):
        self.timeout = timeout
        super().__init__(
            f"API request timed out after {timeout} seconds",
            original_error,
        )


class StreamStallError(APITimeoutError):
    """Raised when the SDK stream goes idle beyond the stall timeout.

    A distinct subclass of APITimeoutError so the stream-stall counter can be
    checked via isinstance() rather than float-equality on the timeout value,
    which breaks when CLAUDETM_STREAM_IDLE_TIMEOUT_SEC is overridden to the
    same value used by _classify_api_error's 30.0-second default.
    """

    def __init__(self, timeout: float, original_error: Exception | None = None):
        super().__init__(timeout, original_error)
        self.message = f"Stream idle for {timeout:.0f}s - upstream stall detected"


class APIAuthenticationError(QueryExecutionError):
    """Raised when API authentication fails."""

    def __init__(self, original_error: Exception | None = None):
        super().__init__(
            "API authentication failed - check your credentials",
            original_error,
        )


class APIServerError(QueryExecutionError):
    """Raised when the API server returns a 5xx error."""

    def __init__(self, status_code: int, original_error: Exception | None = None):
        self.status_code = status_code
        super().__init__(
            f"API server error (HTTP {status_code})",
            original_error,
        )


class ContentFilterError(QueryExecutionError):
    """Raised when output is blocked by content filtering policy.

    This error is NOT retryable - the content itself triggered the filter.
    See: https://privacy.claude.com/en/articles/9205721-why-am-i-receiving-an-output-blocked-by-content-filtering-policy-error
    """

    def __init__(self, original_error: Exception | None = None):
        super().__init__(
            "Output blocked by content filtering policy. "
            "Try rephrasing your request or breaking it into smaller tasks. "
            "See: https://privacy.claude.com/en/articles/9205721",
            original_error,
        )


class ModelUnavailableError(QueryExecutionError):
    """Raised when the requested model is unavailable (unknown/not-found id).

    This is NOT a transient API-health error and must not be retried against the
    same model. The query executor recovers by walking the fallback chain
    (get_fallback_chain) to the next model; it is deliberately excluded from
    TRANSIENT_ERRORS so it is handled by that dedicated path instead of a plain
    backoff-retry of the same unavailable model.
    """

    def __init__(self, original_error: Exception | None = None):
        super().__init__(
            "Requested model is unavailable (unknown or not-found model id)",
            original_error,
        )


class WorkingDirectoryError(AgentError):
    """Raised when there's an issue with the working directory."""

    def __init__(self, path: str, operation: str, original_error: Exception):
        self.path = path
        self.operation = operation
        self.original_error = original_error
        super().__init__(
            f"Failed to {operation} working directory: {path}",
            str(original_error),
        )


# Convenience tuple of transient (retryable) errors
TRANSIENT_ERRORS = (
    APIRateLimitError,
    APIConnectionError,
    APITimeoutError,
    APIServerError,
)


class ConsecutiveFailuresError(AgentError):
    """Raised when too many consecutive API failures occur.

    This error is raised when the retry logic detects 3 consecutive
    API failures within a short time window, indicating persistent issues.
    """

    def __init__(self, failure_count: int, last_error: Exception | None = None):
        self.failure_count = failure_count
        self.last_error = last_error
        details = str(last_error) if last_error else None
        super().__init__(
            f"API failed {failure_count} consecutive times - stopping execution",
            details,
        )


# All exception classes for easy imports
__all__ = [
    "AgentError",
    "SDKImportError",
    "SDKInitializationError",
    "QueryExecutionError",
    "APIRateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "StreamStallError",
    "APIAuthenticationError",
    "APIServerError",
    "ContentFilterError",
    "ModelUnavailableError",
    "WorkingDirectoryError",
    "ConsecutiveFailuresError",
    "TRANSIENT_ERRORS",
]
