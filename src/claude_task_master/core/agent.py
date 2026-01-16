"""Agent Wrapper - Encapsulates all Claude Agent SDK interactions."""

import asyncio
import os
from enum import Enum
from typing import TYPE_CHECKING, Any

from . import console
from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitState,
)
from .prompts import build_planning_prompt, build_verification_prompt, build_work_prompt
from .rate_limit import RateLimitConfig

if TYPE_CHECKING:
    from .hooks import HookMatcher
    from .logger import TaskLogger

# =============================================================================
# Custom Exception Classes
# =============================================================================


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


# =============================================================================
# Enums
# =============================================================================


class ModelType(Enum):
    """Available Claude models."""

    SONNET = "sonnet"
    OPUS = "opus"
    HAIKU = "haiku"


class TaskComplexity(Enum):
    """Task complexity levels for model selection.

    - CODING: Complex implementation tasks → Opus (smartest)
    - QUICK: Simple fixes, config changes → Haiku (fastest/cheapest)
    - GENERAL: Moderate complexity → Sonnet (balanced)
    """

    CODING = "coding"
    QUICK = "quick"
    GENERAL = "general"

    @classmethod
    def get_model_for_complexity(cls, complexity: "TaskComplexity") -> ModelType:
        """Map task complexity to appropriate model."""
        mapping = {
            cls.CODING: ModelType.OPUS,
            cls.QUICK: ModelType.HAIKU,
            cls.GENERAL: ModelType.SONNET,
        }
        return mapping.get(complexity, ModelType.SONNET)


class ToolConfig(Enum):
    """Tool configurations for different phases."""

    # Planning uses READ-ONLY tools - Claude explores and creates plan, does NOT implement
    PLANNING = [
        "Read",
        "Glob",
        "Grep",
    ]
    # Verification uses read tools + Bash for running tests/lint (no write access)
    VERIFICATION = [
        "Read",
        "Glob",
        "Grep",
        "Bash",
    ]
    # Working phase has full tool access for implementation
    WORKING = [
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
    ]


# Model context window sizes (tokens) for auto-compact threshold calculation
# Sonnet 4/4.5 supports 1M context (available for tier 4+ users)
# See: https://www.claude.com/blog/1m-context
MODEL_CONTEXT_WINDOWS = {
    ModelType.OPUS: 200_000,  # Claude Opus 4.5: 200K context
    ModelType.SONNET: 1_000_000,  # Claude Sonnet 4/4.5: 1M context (tier 4+)
    ModelType.HAIKU: 200_000,  # Claude Haiku 4.5: 200K context
}

# Standard context windows (for users below tier 4)
MODEL_CONTEXT_WINDOWS_STANDARD = {
    ModelType.OPUS: 200_000,
    ModelType.SONNET: 200_000,
    ModelType.HAIKU: 200_000,
}

# Default compact threshold as percentage of context window
DEFAULT_COMPACT_THRESHOLD_PERCENT = 0.85  # Compact at 85% usage


def parse_task_complexity(task_description: str) -> tuple[TaskComplexity, str]:
    """Parse task complexity tag from task description.

    Looks for `[coding]`, `[quick]`, or `[general]` tags in the task.

    Args:
        task_description: The task description potentially containing a complexity tag.

    Returns:
        Tuple of (TaskComplexity, cleaned_task_description).
        Defaults to CODING if no tag found (prefer smarter model).
    """
    import re

    # Look for complexity tags in backticks: `[coding]`, `[quick]`, `[general]`
    pattern = r"`\[(coding|quick|general)\]`"
    match = re.search(pattern, task_description, re.IGNORECASE)

    if match:
        complexity_str = match.group(1).lower()
        # Remove the tag from the description
        cleaned = re.sub(pattern, "", task_description, flags=re.IGNORECASE).strip()

        complexity_map = {
            "coding": TaskComplexity.CODING,
            "quick": TaskComplexity.QUICK,
            "general": TaskComplexity.GENERAL,
        }
        return complexity_map.get(complexity_str, TaskComplexity.CODING), cleaned

    # Default to CODING (prefer smarter model when uncertain)
    return TaskComplexity.CODING, task_description


class AgentWrapper:
    """Wraps Claude Agent SDK for task execution."""

    # Transient error types that should be retried
    TRANSIENT_ERRORS = (
        APIRateLimitError,
        APIConnectionError,
        APITimeoutError,
        APIServerError,
    )

    def __init__(
        self,
        access_token: str,
        model: ModelType,
        working_dir: str = ".",
        rate_limit_config: RateLimitConfig | None = None,
        hooks: dict[str, list["HookMatcher"]] | None = None,
        enable_safety_hooks: bool = True,
        logger: "TaskLogger | None" = None,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
    ):
        """Initialize agent wrapper.

        Args:
            access_token: OAuth access token for Claude API.
            model: The Claude model to use.
            working_dir: Working directory for file operations.
            rate_limit_config: Rate limiting configuration. Uses defaults if None.
            hooks: Optional pre-configured hooks dictionary for ClaudeAgentOptions.
            enable_safety_hooks: If True and hooks is None, create default safety hooks.
            logger: Optional TaskLogger for capturing tool usage and responses.
            circuit_breaker_config: Optional circuit breaker config for fault tolerance.

        Raises:
            SDKImportError: If claude-agent-sdk is not installed.
            SDKInitializationError: If SDK components cannot be initialized.
        """
        self.access_token = access_token
        self.model = model
        self.working_dir = working_dir
        self.rate_limit_config = rate_limit_config or RateLimitConfig.default()
        self.hooks = hooks
        self.enable_safety_hooks = enable_safety_hooks
        self.logger = logger

        # Initialize circuit breaker for API fault tolerance
        self.circuit_breaker = CircuitBreaker(
            name="claude_api",
            config=circuit_breaker_config or CircuitBreakerConfig.default(),
        )

        # Import Claude Agent SDK with improved error handling
        self._import_sdk()

        # Initialize default hooks if not provided and safety enabled
        if self.hooks is None and self.enable_safety_hooks:
            self._init_default_hooks()

        # Note: The Claude Agent SDK will automatically use credentials from
        # ~/.claude/.credentials.json if no ANTHROPIC_API_KEY is set

    def _init_default_hooks(self) -> None:
        """Initialize default safety and audit hooks.

        This method is called when hooks are not explicitly provided and
        enable_safety_hooks is True. It sets up basic safety controls.
        """
        try:
            from .hooks import create_default_hooks

            self.hooks = create_default_hooks(
                enable_safety=True,
                enable_audit=False,  # Audit logging is handled by TaskLogger
                enable_progress=False,  # Progress tracking is handled by orchestrator
            )
        except ImportError:
            # If hooks module fails to import, continue without hooks
            self.hooks = None

    def _import_sdk(self) -> None:
        """Import and initialize the Claude Agent SDK.

        Raises:
            SDKImportError: If the SDK cannot be imported.
            SDKInitializationError: If SDK components are missing or invalid.
        """
        try:
            import claude_agent_sdk
        except ImportError as e:
            raise SDKImportError(e) from e
        except Exception as e:
            raise SDKImportError(e) from e

        # Validate required components exist
        try:
            self.query = claude_agent_sdk.query
        except AttributeError as e:
            raise SDKInitializationError("query", e) from e

        try:
            self.options_class = claude_agent_sdk.ClaudeAgentOptions
        except AttributeError as e:
            raise SDKInitializationError("ClaudeAgentOptions", e) from e

        # Verify the query is callable
        if not callable(self.query):
            raise SDKInitializationError(
                "query",
                ValueError("query must be callable"),
            )

    def run_planning_phase(self, goal: str, context: str = "") -> dict[str, Any]:
        """Run planning phase with read-only tools.

        Always uses Opus (smartest model) for planning to ensure
        high-quality task breakdown and complexity classification.
        """
        # Build prompt for planning
        prompt = self._build_planning_prompt(goal, context)

        # Always use Opus for planning (smartest model)
        console.info("Planning with Opus (smartest model)...")

        # Run async query with Opus override
        result = asyncio.run(
            self._run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("planning"),
                model_override=ModelType.OPUS,  # Always use Opus for planning
            )
        )

        # Parse result to extract plan and criteria
        return {
            "plan": self._extract_plan(result),
            "criteria": self._extract_criteria(result),
            "raw_output": result,
        }

    def run_work_session(
        self,
        task_description: str,
        context: str = "",
        pr_comments: str | None = None,
        model_override: ModelType | None = None,
    ) -> dict[str, Any]:
        """Run a work session with full tools.

        Args:
            task_description: Description of the task to complete.
            context: Additional context for the task.
            pr_comments: PR review comments to address (if any).
            model_override: Optional model to use instead of default.
                           Used for dynamic model routing based on task complexity.

        Returns:
            Dict with 'output' and 'success' keys.
        """
        # Build prompt for work session
        prompt = self._build_work_prompt(task_description, context, pr_comments)

        # Run async query with optional model override
        result = asyncio.run(
            self._run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("working"),
                model_override=model_override,
            )
        )

        return {
            "output": result,
            "success": True,  # For MVP, assume success
            "model_used": (model_override or self.model).value,
        }

    def verify_success_criteria(self, criteria: str, context: str = "") -> dict[str, Any]:
        """Verify if success criteria are met.

        Uses verification tools (Read, Glob, Grep, Bash) to actually run tests
        and lint checks as specified in the verification prompt.
        """
        # Build prompt using centralized prompts module
        prompt = build_verification_prompt(criteria=criteria, tasks_summary=context)

        # Run async query with verification tools (read + bash for running tests)
        result = asyncio.run(
            self._run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("verification"),
            )
        )

        # Parse the verification result - look for explicit PASS/FAIL marker
        result_lower = result.lower()

        # Look for our explicit marker first
        if "verification_result: pass" in result_lower:
            success = True
        elif "verification_result: fail" in result_lower:
            success = False
        else:
            # Fallback: check for clear negative vs positive indicators
            # The key issue is catching "Overall Success: NO" while still
            # detecting genuine success
            negative_indicators = [
                "not met",
                "not all criteria",
                "criteria not met",
                "overall success: no",
                "criteria not satisfied",
                "verification failed",
                "cannot verify",
            ]
            positive_indicators = [
                "all criteria met",
                "all criteria verified",
                "overall success: yes",
                "verification successful",
                "success",  # Generic success indicator
            ]

            # Check for negative indicators first (these are disqualifying)
            has_negative = any(ind in result_lower for ind in negative_indicators)

            # Check for positive indicators
            has_positive = any(ind in result_lower for ind in positive_indicators)

            # Succeed if we have positive indicators without clear negatives
            # The key fix: "Overall Success: NO" will trigger has_negative
            success = has_positive and not has_negative

        return {
            "success": success,
            "details": result,
        }

    async def _run_query(
        self, prompt: str, tools: list[str], model_override: ModelType | None = None
    ) -> str:
        """Run query with retry logic for transient errors.

        Args:
            prompt: The prompt to send to the model.
            tools: List of tools to enable.
            model_override: Optional model to use instead of default.

        Returns:
            The result text from the query.

        Raises:
            WorkingDirectoryError: If working directory cannot be accessed.
            QueryExecutionError: If the query fails after all retries.
            APIAuthenticationError: If authentication fails (not retried).
        """
        return await self._run_query_with_retry(prompt, tools, model_override)

    async def _run_query_with_retry(
        self, prompt: str, tools: list[str], model_override: ModelType | None = None
    ) -> str:
        """Execute query with exponential backoff retry for transient errors.

        Uses circuit breaker pattern to prevent cascading failures when the
        API is consistently failing.

        Args:
            prompt: The prompt to send to the model.
            tools: List of tools to enable.
            model_override: Optional model to use instead of default.

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
                    return await self._execute_query(prompt, tools, model_override)
            except CircuitBreakerError:
                # Circuit breaker tripped - don't retry
                console.warning("Circuit breaker opened due to repeated failures")
                raise
            except self.TRANSIENT_ERRORS as e:
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
        self, prompt: str, tools: list[str], model_override: ModelType | None = None
    ) -> str:
        """Execute a single query attempt.

        Args:
            prompt: The prompt to send to the model.
            tools: List of tools to enable.
            model_override: Optional model to use instead of default.

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
        model_name = self._get_model_name(effective_model)

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

            # Create options with model specification
            try:
                options = self.options_class(
                    allowed_tools=tools,
                    permission_mode="bypassPermissions",  # For MVP, bypass permissions
                    model=model_name,  # Specify the model to use
                    cwd=str(self.working_dir),  # Project directory for CLAUDE.md
                    setting_sources=["project"],  # Load CLAUDE.md from project directory
                    hooks=self.hooks,  # type: ignore[arg-type]  # Compatible HookMatcher
                )
            except Exception as e:
                raise SDKInitializationError("ClaudeAgentOptions", e) from e

            # Execute query
            try:
                async for message in self.query(prompt=prompt, options=options):
                    result_text = self._process_message(message, result_text)
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

    def _process_message(self, message: Any, result_text: str) -> str:
        """Process a message from the query stream.

        Args:
            message: The message to process.
            result_text: The accumulated result text.

        Returns:
            Updated result text.
        """
        message_type = type(message).__name__

        if hasattr(message, "content") and message.content:
            # Assistant or User messages with content
            for block in message.content:
                block_type = type(block).__name__

                if block_type == "TextBlock":
                    # Claude's text response - show with [claude] prefix
                    console.claude_text(block.text.strip(), flush=True)
                    result_text += block.text
                elif block_type == "ToolUseBlock":
                    # Tool being invoked - show details
                    console.newline()
                    tool_input = getattr(block, "input", {})
                    tool_detail = self._format_tool_detail(block.name, tool_input)
                    console.tool(f"Using tool: {block.name} {tool_detail}", flush=True)
                    # Log to file if logger is available
                    if self.logger:
                        self.logger.log_tool_use(block.name, tool_input)
                elif block_type == "ToolResultBlock":
                    # Tool result - show completion with [claude] prefix
                    if block.is_error:
                        console.tool_result("Tool error", is_error=True)
                        if self.logger:
                            self.logger.log_tool_result(block.tool_use_id, "ERROR")
                    else:
                        console.tool_result("Tool completed")
                        if self.logger:
                            self.logger.log_tool_result(block.tool_use_id, "completed")

        # Collect final result from ResultMessage
        if message_type == "ResultMessage":
            if hasattr(message, "result"):
                result_text = message.result
                console.newline()  # Add newline after completion

        return result_text

    def _format_tool_detail(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Format tool input for display.

        Shows the most relevant parameter for each tool type.
        """
        if not tool_input:
            return ""

        # Map tool names to their most relevant parameters
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            # Truncate long commands
            if len(cmd) > 250:
                cmd = cmd[:247] + "..."
            return f"→ {cmd}"
        elif tool_name == "Read":
            path = tool_input.get("file_path", "")
            return f"→ {path}"
        elif tool_name == "Write":
            path = tool_input.get("file_path", "")
            return f"→ {path}"
        elif tool_name == "Edit":
            path = tool_input.get("file_path", "")
            return f"→ {path}"
        elif tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", ".")
            return f"→ {pattern} in {path}"
        elif tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", ".")
            return f"→ '{pattern}' in {path}"
        elif tool_name == "WebSearch":
            query = tool_input.get("query", "")
            # Truncate long queries
            if len(query) > 100:
                query = query[:97] + "..."
            return f"→ '{query}'"
        elif tool_name == "WebFetch":
            url = tool_input.get("url", "")
            # Truncate long URLs
            if len(url) > 100:
                url = url[:97] + "..."
            return f"→ {url}"
        else:
            # For unknown tools, show first key-value if available
            if tool_input:
                first_key = next(iter(tool_input))
                first_val = str(tool_input[first_key])[:50]
                return f"→ {first_key}={first_val}"
            return ""

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

    def get_tools_for_phase(self, phase: str) -> list[str]:
        """Get appropriate tools for the given phase."""
        if phase == "planning":
            return ToolConfig.PLANNING.value
        elif phase == "verification":
            return ToolConfig.VERIFICATION.value
        else:
            return ToolConfig.WORKING.value

    def _get_model_name(self, model: ModelType | None = None) -> str:
        """Convert ModelType to API model name.

        Args:
            model: Optional model override. If None, uses self.model.

        Returns:
            The API model name string.
        """
        target_model = model or self.model
        model_map = {
            ModelType.SONNET: "claude-sonnet-4-5-20250929",
            ModelType.OPUS: "claude-opus-4-5-20251101",
            ModelType.HAIKU: "claude-haiku-4-5-20251001",
        }
        return model_map.get(target_model, "claude-sonnet-4-5-20250929")

    def _build_planning_prompt(self, goal: str, context: str) -> str:
        """Build prompt for planning phase.

        Delegates to centralized prompts module for maintainability.
        """
        return build_planning_prompt(goal=goal, context=context if context else None)

    def _build_work_prompt(
        self, task_description: str, context: str, pr_comments: str | None
    ) -> str:
        """Build prompt for work session.

        Delegates to centralized prompts module for maintainability.
        """
        return build_work_prompt(
            task_description=task_description,
            context=context if context else None,
            pr_comments=pr_comments,
        )

    def _extract_plan(self, result: str) -> str:
        """Extract task list from planning result."""
        # For MVP, return the full result - we'll parse later
        if "## Task List" in result:
            return result

        # If no proper format, wrap it
        return f"## Task List\n\n{result}"

    def _extract_criteria(self, result: str) -> str:
        """Extract success criteria from planning result."""
        # Look for success criteria section
        if "## Success Criteria" in result:
            parts = result.split("## Success Criteria")
            if len(parts) > 1:
                return parts[1].strip()

        # Default criteria if none specified
        return "All tasks in the task list are completed successfully."
