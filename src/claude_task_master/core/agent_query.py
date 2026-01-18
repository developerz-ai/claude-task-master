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
import time
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
    ConsecutiveFailuresError,
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
from .config_loader import get_config

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

        # Track consecutive failures within a time window
        self._consecutive_failures = 0
        self._first_failure_time: float | None = None
        self._failure_window = 60.0  # 1 minute window

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

    def _record_failure(self, error: Exception) -> None:
        """Record a failure and check if we've exceeded the threshold.

        Tracks consecutive failures within a 1-minute window. If 3 failures
        occur within this window, raises ConsecutiveFailuresError.

        Args:
            error: The error that caused the failure.

        Raises:
            ConsecutiveFailuresError: If 3 failures occur within 1 minute.
        """
        current_time = time.time()

        # Check if we're still within the failure window
        if self._first_failure_time is not None:
            time_since_first = current_time - self._first_failure_time
            if time_since_first > self._failure_window:
                # Window expired, reset counter
                self._consecutive_failures = 0
                self._first_failure_time = None

        # Record this failure
        if self._first_failure_time is None:
            self._first_failure_time = current_time

        self._consecutive_failures += 1

        # Check if we've hit the threshold
        if self._consecutive_failures >= 3:
            console.newline()
            console.error(
                "API failed 3 consecutive times within 1 minute - stopping execution",
                flush=True,
            )
            raise ConsecutiveFailuresError(3, error)

    def _reset_failures(self) -> None:
        """Reset the failure counter after a successful query."""
        self._consecutive_failures = 0
        self._first_failure_time = None

    async def _run_query_with_retry(
        self,
        prompt: str,
        tools: list[str],
        model_override: "ModelType | None" = None,
        get_model_name_func: Any = None,
        get_agents_func: Any = None,
        process_message_func: Any = None,
    ) -> str:
        """Execute query with retry logic for transient errors.

        Uses a fixed 5-second delay between retries. If 3 consecutive errors
        occur within a 1-minute window, raises ConsecutiveFailuresError to
        signal the orchestrator to exit with blocked status.

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
            ConsecutiveFailuresError: If 3 consecutive API errors occur within 1 minute.
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

        retry_delay = 5.0  # seconds

        while True:
            try:
                # Execute through circuit breaker
                with self.circuit_breaker:
                    result = await self._execute_query(
                        prompt,
                        tools,
                        model_override,
                        get_model_name_func,
                        get_agents_func,
                        process_message_func,
                    )
                    # Success - reset failure counter
                    self._reset_failures()
                    return result
            except CircuitBreakerError:
                # Circuit breaker tripped - don't retry
                console.warning("Circuit breaker opened due to repeated failures")
                raise
            except TRANSIENT_ERRORS as e:
                # Record failure (may raise ConsecutiveFailuresError)
                self._record_failure(e)

                # Still under threshold, retry
                console.newline()
                console.warning(
                    f"API error ({self._consecutive_failures}/3 in window): {e.message}",
                    flush=True,
                )
                console.detail(f"Retrying in {retry_delay:.0f} seconds...", flush=True)
                await asyncio.sleep(retry_delay)
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
                # Unexpected errors count toward consecutive failures
                self._record_failure(e)

                # Still under threshold, retry
                console.newline()
                console.warning(
                    f"Unexpected error ({self._consecutive_failures}/3 in window): {type(e).__name__}: {e}",
                    flush=True,
                )
                console.detail(f"Retrying in {retry_delay:.0f} seconds...", flush=True)
                await asyncio.sleep(retry_delay)

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
        """Default model name mapping using global config.

        Model names are loaded from configuration, which can be:
        - Set in `.claude-task-master/config.json`
        - Overridden via environment variables (CLAUDETM_MODEL_SONNET, etc.)

        Args:
            model: The ModelType to convert.

        Returns:
            The API model name string from configuration.
        """
        from .agent_models import ModelType

        config = get_config()
        model_map = {
            ModelType.SONNET: config.models.sonnet,
            ModelType.OPUS: config.models.opus,
            ModelType.HAIKU: config.models.haiku,
        }
        return model_map.get(model, config.models.sonnet)

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
