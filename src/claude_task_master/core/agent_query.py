"""Agent Query Execution - Handles query execution with retry logic.

This module contains the query execution logic extracted from AgentWrapper,
following the Single Responsibility Principle (SRP). It handles:
- Query execution with retries
- Circuit breaker integration
- Working directory management
- API error classification
"""

import asyncio
import os
from typing import TYPE_CHECKING, Any

from . import console
from .agent_exceptions import (
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
from .circuit_breaker import (
    CircuitBreakerError,
    CircuitState,
)

if TYPE_CHECKING:
    from .agent_models import ModelType
    from .circuit_breaker import CircuitBreaker
    from .hooks import HookMatcher
    from .logger import TaskLogger
    from .rate_limit import RateLimitConfig


class AgentQueryExecutor:
    """Handles query execution with retry logic and circuit breaker.

    This class is responsible for executing queries against the Claude Agent SDK,
    handling transient errors with exponential backoff, and managing the circuit
    breaker for fault tolerance.
    """

    def __init__(
        self,
        query_func: Any,
        options_class: Any,
        working_dir: str,
        model: "ModelType",
        rate_limit_config: "RateLimitConfig",
        circuit_breaker: "CircuitBreaker",
        hooks: dict[str, list["HookMatcher"]] | None = None,
        logger: "TaskLogger | None" = None,
    ):
        """Initialize the query executor.

        Args:
            query_func: The SDK query function to use.
            options_class: The SDK options class for creating query options.
            working_dir: Working directory for file operations.
            model: The default model to use for queries.
            rate_limit_config: Rate limiting configuration.
            circuit_breaker: Circuit breaker instance for fault tolerance.
            hooks: Optional hooks dictionary for ClaudeAgentOptions.
            logger: Optional TaskLogger for capturing tool usage.
        """
        self.query = query_func
        self.options_class = options_class
        self.working_dir = working_dir
        self.model = model
        self.rate_limit_config = rate_limit_config
        self.circuit_breaker = circuit_breaker
        self.hooks = hooks
        self.logger = logger

    async def run_query(
        self,
        prompt: str,
        tools: list[str],
        model_override: "ModelType | None" = None,
        get_model_name_func: Any = None,
        get_agents_func: Any = None,
        process_message_func: Any = None,
    ) -> str:
        """Run query with retry logic for transient errors.

        Args:
            prompt: The prompt to send to the model.
            tools: List of tools to enable.
            model_override: Optional model to use instead of default.
            get_model_name_func: Function to convert ModelType to API model name.
            get_agents_func: Function to get subagents for working directory.
            process_message_func: Function to process messages from query stream.

        Returns:
            The result text from the query.

        Raises:
            WorkingDirectoryError: If working directory cannot be accessed.
            QueryExecutionError: If the query fails after all retries.
            APIAuthenticationError: If authentication fails (not retried).
        """
        return await self._run_query_with_retry(
            prompt,
            tools,
            model_override,
            get_model_name_func,
            get_agents_func,
            process_message_func,
        )

    async def _run_query_with_retry(
        self,
        prompt: str,
        tools: list[str],
        model_override: "ModelType | None" = None,
        get_model_name_func: Any = None,
        get_agents_func: Any = None,
        process_message_func: Any = None,
    ) -> str:
        """Execute query with exponential backoff retry for transient errors.

        Uses circuit breaker pattern to prevent cascading failures when the
        API is consistently failing.

        Args:
            prompt: The prompt to send to the model.
            tools: List of tools to enable.
            model_override: Optional model to use instead of default.
            get_model_name_func: Function to convert ModelType to API model name.
            get_agents_func: Function to get subagents for working directory.
            process_message_func: Function to process messages from query stream.

        Returns:
            The result text from the query.

        Raises:
            WorkingDirectoryError: If working directory cannot be accessed.
            QueryExecutionError: If the query fails after all retries.
            CircuitBreakerError: If circuit breaker is open.
        """
        # Check circuit breaker state first
        if self.circuit_breaker.is_open:
            time_until_retry = self.circuit_breaker.time_until_retry
            console.warning(
                f"Circuit breaker open - API unavailable. Retry in {time_until_retry:.0f}s"
            )
            raise CircuitBreakerError(
                f"Circuit '{self.circuit_breaker.name}' is open",
                CircuitState.OPEN,
                time_until_retry,
            )

        last_error: Exception | None = None
        max_retries = self.rate_limit_config.max_retries

        for attempt in range(max_retries + 1):
            try:
                # Execute through circuit breaker
                with self.circuit_breaker:
                    return await self._execute_query(
                        prompt,
                        tools,
                        model_override,
                        get_model_name_func,
                        get_agents_func,
                        process_message_func,
                    )
            except CircuitBreakerError:
                # Circuit breaker tripped - don't retry
                console.warning("Circuit breaker opened due to repeated failures")
                raise
            except TRANSIENT_ERRORS as e:
                last_error = e
                if attempt < max_retries:
                    # Calculate backoff using rate limit config
                    sleep_time = self.rate_limit_config.calculate_backoff(attempt)
                    console.newline()
                    console.warning(
                        f"Transient error (attempt {attempt + 1}/{max_retries + 1}): {e.message}",
                        flush=True,
                    )
                    console.detail(f"Retrying in {sleep_time:.1f} seconds...", flush=True)
                    await asyncio.sleep(sleep_time)
                else:
                    # Out of retries
                    console.newline()
                    console.error(
                        f"Failed after {max_retries + 1} attempts: {e.message}",
                        flush=True,
                    )
                    raise
            except (
                APIAuthenticationError,
                ContentFilterError,
                SDKImportError,
                SDKInitializationError,
            ):
                # These errors should not be retried
                raise
            except AgentError:
                # Other agent errors - re-raise as is
                raise
            except Exception as e:
                # Unexpected errors - wrap and raise
                raise QueryExecutionError(
                    f"Unexpected error during query execution: {type(e).__name__}",
                    e,
                ) from e

        # Should not reach here, but just in case
        if last_error:
            raise last_error
        raise QueryExecutionError("Query failed with unknown error")

    async def _execute_query(
        self,
        prompt: str,
        tools: list[str],
        model_override: "ModelType | None" = None,
        get_model_name_func: Any = None,
        get_agents_func: Any = None,
        process_message_func: Any = None,
    ) -> str:
        """Execute a single query attempt.

        Args:
            prompt: The prompt to send to the model.
            tools: List of tools to enable.
            model_override: Optional model to use instead of default.
            get_model_name_func: Function to convert ModelType to API model name.
            get_agents_func: Function to get subagents for working directory.
            process_message_func: Function to process messages from query stream.

        Returns:
            The result text from the query.

        Raises:
            WorkingDirectoryError: If working directory cannot be accessed.
            APIRateLimitError: If rate limited.
            APIConnectionError: If connection fails.
            APITimeoutError: If request times out.
            APIAuthenticationError: If authentication fails.
            APIServerError: If server returns 5xx error.
            QueryExecutionError: For other query errors.
        """
        result_text = ""
        original_dir = os.getcwd()

        # Determine which model to use
        effective_model = model_override or self.model

        # Get model name using provided function or default
        if get_model_name_func:
            model_name = get_model_name_func(effective_model)
        else:
            model_name = self._default_get_model_name(effective_model)

        # Log the model and tools being used
        tools_str = ", ".join(tools) if tools else "all"
        console.detail(
            f"Using model: {effective_model.value} ({model_name}) | Tools: {tools_str}",
            flush=True,
        )

        try:
            # Change to working directory
            try:
                os.chdir(self.working_dir)
            except FileNotFoundError as e:
                raise WorkingDirectoryError(self.working_dir, "change to", e) from e
            except PermissionError as e:
                raise WorkingDirectoryError(self.working_dir, "access", e) from e
            except OSError as e:
                raise WorkingDirectoryError(self.working_dir, "change to", e) from e

            # Load subagents from .claude/agents/ directory
            if get_agents_func:
                agents = get_agents_func(self.working_dir)
            else:
                agents = None

            # Create options with model specification and subagents
            try:
                options = self.options_class(
                    allowed_tools=tools,
                    permission_mode="bypassPermissions",  # For MVP, bypass permissions
                    model=model_name,  # Specify the model to use
                    cwd=str(self.working_dir),  # Project directory for CLAUDE.md
                    setting_sources=["user", "local", "project"],  # Load all settings/skills
                    hooks=self.hooks,  # Compatible HookMatcher
                    agents=agents if agents else None,  # Programmatic subagents
                )
            except Exception as e:
                raise SDKInitializationError("ClaudeAgentOptions", e) from e

            # Execute query
            try:
                async for message in self.query(prompt=prompt, options=options):
                    if process_message_func:
                        result_text = process_message_func(message, result_text)
                    else:
                        result_text = self._default_process_message(message, result_text)
            except Exception as e:
                # Classify the error
                raise self._classify_api_error(e) from e

        finally:
            # Always restore original directory
            try:
                os.chdir(original_dir)
            except OSError:
                # Best effort to restore directory - don't mask original error
                pass

        return result_text

    def _default_get_model_name(self, model: "ModelType") -> str:
        """Default model name mapping.

        Args:
            model: The ModelType to convert.

        Returns:
            The API model name string.
        """
        from .agent_models import ModelType

        model_map = {
            ModelType.SONNET: "claude-sonnet-4-5-20250929",
            ModelType.OPUS: "claude-opus-4-5-20251101",
            ModelType.HAIKU: "claude-haiku-4-5-20251001",
        }
        return model_map.get(model, "claude-sonnet-4-5-20250929")

    def _default_process_message(self, message: Any, result_text: str) -> str:
        """Default message processing - just accumulates text.

        Args:
            message: The message to process.
            result_text: The accumulated result text.

        Returns:
            Updated result text.
        """
        message_type = type(message).__name__

        if hasattr(message, "content") and message.content:
            for block in message.content:
                block_type = type(block).__name__
                if block_type == "TextBlock":
                    result_text += block.text

        if message_type == "ResultMessage":
            if hasattr(message, "result"):
                result_text = message.result

        return result_text

    def _classify_api_error(self, error: Exception) -> AgentError:
        """Classify an API error into a specific error type.

        Args:
            error: The original exception.

        Returns:
            A classified AgentError subclass.
        """
        error_str = str(error).lower()
        error_type = type(error).__name__

        # Check for content filtering errors (not retryable)
        if "content filtering" in error_str or "output blocked" in error_str:
            return ContentFilterError(error)

        # Check for rate limiting
        if "rate" in error_str and "limit" in error_str:
            # Try to extract retry-after if present
            retry_after = None
            if hasattr(error, "retry_after"):
                retry_after = error.retry_after
            return APIRateLimitError(retry_after, error)

        # Check for authentication errors
        if any(kw in error_str for kw in ["auth", "unauthorized", "403", "401"]):
            return APIAuthenticationError(error)

        # Check for timeout errors
        if "timeout" in error_str or error_type in ("TimeoutError", "AsyncioTimeoutError"):
            return APITimeoutError(30.0, error)

        # Check for connection errors
        if any(kw in error_str for kw in ["connect", "connection", "network"]):
            return APIConnectionError(error)

        # Check for server errors (5xx)
        if "500" in error_str or "502" in error_str or "503" in error_str or "504" in error_str:
            # Try to extract status code
            for code in [500, 502, 503, 504]:
                if str(code) in error_str:
                    return APIServerError(code, error)
            return APIServerError(500, error)

        # Default to generic query execution error
        return QueryExecutionError(f"API error: {error}", error)
