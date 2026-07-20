"""Agent Query Execution - Handles query execution with retry logic.

This module contains the query execution logic extracted from AgentWrapper,
following the Single Responsibility Principle (SRP). It handles:
- Query execution with retries
- Circuit breaker integration
- Working directory management
- API error classification

Single-attempt execution lives in :mod:`.agent_query_execute`.
Default message processing and error classification live in :mod:`.agent_query_helpers`.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Any

from . import console
from .agent_exceptions import (
    TRANSIENT_ERRORS,
    APIAuthenticationError,
    ConsecutiveFailuresError,
    ContentFilterError,
    ModelUnavailableError,
    SDKImportError,
    SDKInitializationError,
    StreamStallError,
)
from .agent_query_execute import _AgentQueryExecuteMixin
from .agent_query_helpers import _AgentQueryHelpersMixin
from .circuit_breaker import CircuitBreakerError, CircuitState

if TYPE_CHECKING:
    from .agent_models import ModelType
    from .circuit_breaker import CircuitBreaker
    from .logger import TaskLogger
    from .rate_limit import RateLimitConfig


# Maximum gap (seconds) between consecutive messages from the SDK stream before
# we treat the stream as stalled. The SDK's wait_for_result_and_end_input
# (query.py:809) deliberately applies NO timeout; under known bug
# https://github.com/anthropics/claude-code/issues/30333 the CLI subprocess can
# drop the final result line on long sessions and the iterator parks forever.
# 30 minutes accommodates legitimate slow tool calls (full pytest, gh run watch
# on slow CI, long builds) while still catching real hangs well before infinite.
# Override via env var.
STREAM_IDLE_TIMEOUT_SEC = float(os.environ.get("CLAUDETM_STREAM_IDLE_TIMEOUT_SEC", "1800"))

# Shorter timeout that kicks in AFTER the agent has signaled end-of-turn with
# no tool calls pending. In that state the only remaining message is the
# ResultMessage — which is exactly what #30333 loses. Real-world freezes after
# "TASK COMPLETE" have been observed at 17min+ silence; a 2-min ceiling here
# catches them fast without false-triggering during real work (where messages
# flow steadily). On timeout in this state we return the accumulated text
# gracefully instead of retrying — the work IS done, retrying would re-run a
# completed task and risk duplicate PRs.
POST_COMPLETION_IDLE_TIMEOUT_SEC = float(
    os.environ.get("CLAUDETM_POST_COMPLETION_IDLE_TIMEOUT_SEC", "120")
)


class AgentQueryExecutor(_AgentQueryExecuteMixin, _AgentQueryHelpersMixin):
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
        model: ModelType,
        rate_limit_config: RateLimitConfig,
        circuit_breaker: CircuitBreaker,
        hooks: dict[str, Any] | None = None,
        logger: TaskLogger | None = None,
        max_budget_usd: float | None = None,
    ):
        """Initialize the query executor.

        Args:
            query_func: The SDK query function to use.
            options_class: The SDK options class for creating query options.
            working_dir: Working directory for file operations.
            model: The default model to use for queries.
            rate_limit_config: Rate limiting configuration.
            circuit_breaker: Circuit breaker instance for fault tolerance.
            hooks: Hooks dictionary for ClaudeAgentOptions (pass {} to disable).
            logger: Optional TaskLogger for capturing tool usage.
            max_budget_usd: Optional per-session spending cap in USD.
        """
        self.query = query_func
        self.options_class = options_class
        self.working_dir = working_dir
        self.model = model
        self.rate_limit_config = rate_limit_config
        self.circuit_breaker = circuit_breaker
        self.hooks: dict[str, Any] = hooks if hooks is not None else {}
        self.logger = logger
        self.max_budget_usd = max_budget_usd

        # Track consecutive failures within a time window
        self._consecutive_failures = 0
        self._first_failure_time: float | None = None
        self._failure_window = 60.0  # 1 minute window

        # Separate counter for stream idle-timeouts. The windowed counter above
        # would reset between timeouts (since each timeout exceeds the window),
        # so we need a hard cap to prevent infinite retry loops on persistently
        # broken upstream streams.
        self._stream_idle_timeouts = 0
        self._stream_idle_timeout_cap = 2

    async def run_query(
        self,
        prompt: str,
        tools: list[str],
        model_override: ModelType | None = None,
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

        Tracks consecutive failures within a time window. The failure threshold
        is derived from rate_limit_config.max_retries + 1 (to include the
        initial attempt). The window scales with the max total backoff time
        to avoid premature stops during long backoff sequences.

        Args:
            error: The error that caused the failure.

        Raises:
            ConsecutiveFailuresError: If too many failures occur within the window.
        """
        current_time = time.time()

        # Scale the failure window based on total possible backoff time,
        # with a minimum of 60 seconds to handle fast retries
        effective_window = max(
            self._failure_window,
            self.rate_limit_config.get_total_max_time() * 2,
        )

        # Check if we're still within the failure window
        if self._first_failure_time is not None:
            time_since_first = current_time - self._first_failure_time
            if time_since_first > effective_window:
                # Window expired, reset counter
                self._consecutive_failures = 0
                self._first_failure_time = None

        # Record this failure
        if self._first_failure_time is None:
            self._first_failure_time = current_time

        self._consecutive_failures += 1

        # Threshold: max_retries + 1 (initial attempt + retries)
        max_failures = self.rate_limit_config.max_retries + 1

        # Check if we've hit the threshold
        if self._consecutive_failures >= max_failures:
            console.newline()
            console.error(
                f"API failed {max_failures} consecutive times within "
                f"{effective_window:.0f}s window - stopping execution",
                flush=True,
            )
            raise ConsecutiveFailuresError(max_failures, error)

    def _reset_failures(self) -> None:
        """Reset the failure counter after a successful query."""
        self._consecutive_failures = 0
        self._first_failure_time = None
        self._stream_idle_timeouts = 0

    def _get_retry_delay(self, error: Exception) -> float:
        """Calculate the retry delay for a given error and attempt number.

        For rate limit errors, respects the Retry-After value from the API
        if available. Otherwise, uses exponential backoff from rate_limit_config.

        Args:
            error: The error that triggered the retry.

        Returns:
            The delay in seconds before the next retry attempt.
        """
        from .agent_exceptions import APIRateLimitError  # noqa: PLC0415

        # For rate limit errors, respect Retry-After if the API provided it.
        # Cap at max_backoff so a pathological server can't stall retries
        # indefinitely and trip the consecutive-failure window.
        if isinstance(error, APIRateLimitError) and error.retry_after:
            return min(error.retry_after, self.rate_limit_config.max_backoff)

        # Use exponential backoff from rate_limit_config
        # attempt is 0-indexed: first retry = attempt 0
        attempt = self._consecutive_failures - 1
        return self.rate_limit_config.calculate_backoff(max(0, attempt))

    async def _run_query_with_retry(
        self,
        prompt: str,
        tools: list[str],
        model_override: ModelType | None = None,
        get_model_name_func: Any = None,
        get_agents_func: Any = None,
        process_message_func: Any = None,
    ) -> str:
        """Execute query with retry logic for transient errors.

        Uses exponential backoff from rate_limit_config between retries.
        For rate limit errors, respects the Retry-After value from the API.
        If max_retries consecutive errors occur within the failure window,
        raises ConsecutiveFailuresError to signal the orchestrator to exit.

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
            ConsecutiveFailuresError: If too many consecutive API errors occur.
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

        max_failures = self.rate_limit_config.max_retries + 1  # +1 for initial attempt

        # Multi-hop fallback: on ModelUnavailableError, walk the cycle-guarded
        # fallback chain to the next untried model. The SDK's own fallback_model
        # already covers the first hop, so seed it as attempted to avoid re-trying
        # what it just tried. current_model overrides model_override as we descend.
        from .agent_models import get_fallback_chain  # noqa: PLC0415

        effective_model = model_override or self.model
        fallback_chain = get_fallback_chain(effective_model)
        attempted_models = {effective_model}
        if fallback_chain:
            attempted_models.add(fallback_chain[0])
        current_model = model_override

        while True:
            try:
                # Execute through circuit breaker
                with self.circuit_breaker:
                    result = await self._execute_query(
                        prompt,
                        tools,
                        current_model,
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
            except ModelUnavailableError as e:
                # Not an API-health failure — recover by switching models, not by
                # retrying the same one. Don't count toward the failure budget.
                next_model = next((m for m in fallback_chain if m not in attempted_models), None)
                if next_model is None:
                    console.newline()
                    console.error(
                        "All fallback models exhausted - model unavailable",
                        flush=True,
                    )
                    raise
                attempted_models.add(next_model)
                current_model = next_model
                console.newline()
                console.warning(
                    f"Model unavailable ({e.message}) - falling back to {next_model.value}",
                    flush=True,
                )
                # Retry immediately with the next model (no backoff).
                continue
            except TRANSIENT_ERRORS as e:
                # Stream idle-timeouts have their own hard cap (each one
                # takes ~10min, so the windowed counter would never trip).
                if isinstance(e, StreamStallError):
                    self._stream_idle_timeouts += 1
                    if self._stream_idle_timeouts >= self._stream_idle_timeout_cap:
                        console.error(
                            f"Stream stalled {self._stream_idle_timeouts} times - "
                            "giving up to avoid infinite retry loop",
                            flush=True,
                        )
                        raise ConsecutiveFailuresError(self._stream_idle_timeouts, e) from e

                # Record failure (may raise ConsecutiveFailuresError)
                self._record_failure(e)

                # Calculate delay using exponential backoff or Retry-After
                retry_delay = self._get_retry_delay(e)

                # Still under threshold, retry
                console.newline()
                console.warning(
                    f"API error ({self._consecutive_failures}/{max_failures} in window): {e.message}",
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
            except Exception as e:  # noqa: BLE001
                # AgentError subclasses not handled above are re-raised immediately.
                from .agent_exceptions import AgentError  # noqa: PLC0415

                if isinstance(e, AgentError):
                    raise

                # Unexpected errors count toward consecutive failures
                self._record_failure(e)

                # Calculate delay using exponential backoff
                retry_delay = self._get_retry_delay(e)

                # Still under threshold, retry
                console.newline()
                console.warning(
                    f"Unexpected error ({self._consecutive_failures}/{max_failures} in window): {type(e).__name__}: {e}",
                    flush=True,
                )
                console.detail(f"Retrying in {retry_delay:.0f} seconds...", flush=True)
                await asyncio.sleep(retry_delay)
