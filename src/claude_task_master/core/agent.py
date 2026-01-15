"""Agent Wrapper - Encapsulates all Claude Agent SDK interactions."""

import asyncio
import os
from enum import Enum
from typing import Any

from . import console

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

    PLANNING = ["Read", "Glob", "Grep"]
    WORKING = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]


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

    # Retry configuration for transient errors
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_INITIAL_BACKOFF = 1.0  # seconds
    DEFAULT_MAX_BACKOFF = 30.0  # seconds
    DEFAULT_BACKOFF_MULTIPLIER = 2.0

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
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
        max_backoff: float = DEFAULT_MAX_BACKOFF,
    ):
        """Initialize agent wrapper.

        Args:
            access_token: OAuth access token for Claude API.
            model: The Claude model to use.
            working_dir: Working directory for file operations.
            max_retries: Maximum number of retries for transient errors.
            initial_backoff: Initial backoff time in seconds.
            max_backoff: Maximum backoff time in seconds.

        Raises:
            SDKImportError: If claude-agent-sdk is not installed.
            SDKInitializationError: If SDK components cannot be initialized.
        """
        self.access_token = access_token
        self.model = model
        self.working_dir = working_dir
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff

        # Import Claude Agent SDK with improved error handling
        self._import_sdk()

        # Note: The Claude Agent SDK will automatically use credentials from
        # ~/.claude/.credentials.json if no ANTHROPIC_API_KEY is set

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
        """Verify if success criteria are met."""
        prompt = f"""Review the following success criteria and verify if they have been met:

{criteria}

{context}

Respond with:
1. Whether each criterion is met (yes/no)
2. Overall success (all criteria met)
3. Any issues or gaps

Format your response clearly."""

        # Run async query
        result = asyncio.run(
            self._run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("planning"),
            )
        )

        # For MVP, simple check for success indicators
        success = "all criteria met" in result.lower() or "success" in result.lower()

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

        Args:
            prompt: The prompt to send to the model.
            tools: List of tools to enable.
            model_override: Optional model to use instead of default.

        Returns:
            The result text from the query.

        Raises:
            WorkingDirectoryError: If working directory cannot be accessed.
            QueryExecutionError: If the query fails after all retries.
        """
        last_error: Exception | None = None
        backoff = self.initial_backoff

        for attempt in range(self.max_retries + 1):
            try:
                return await self._execute_query(prompt, tools, model_override)
            except self.TRANSIENT_ERRORS as e:
                last_error = e
                if attempt < self.max_retries:
                    # Calculate backoff with jitter
                    sleep_time = min(backoff, self.max_backoff)
                    console.newline()
                    console.warning(
                        f"Transient error (attempt {attempt + 1}/{self.max_retries + 1}): {e.message}",
                        flush=True,
                    )
                    console.detail(f"Retrying in {sleep_time:.1f} seconds...", flush=True)
                    await asyncio.sleep(sleep_time)
                    backoff *= self.DEFAULT_BACKOFF_MULTIPLIER
                else:
                    # Out of retries
                    console.newline()
                    console.error(
                        f"Failed after {self.max_retries + 1} attempts: {e.message}",
                        flush=True,
                    )
                    raise
            except (APIAuthenticationError, SDKImportError, SDKInitializationError):
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

        # Log the model being used
        console.detail(f"Using model: {effective_model.value} ({model_name})", flush=True)

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
                    # Claude's text response - stream without prefix
                    console.stream(block.text)
                    result_text += block.text
                elif block_type == "ToolUseBlock":
                    # Tool being invoked
                    console.newline()
                    console.tool(f"Using tool: {block.name}", flush=True)
                elif block_type == "ToolResultBlock":
                    # Tool result - show completion
                    if block.is_error:
                        console.error("Tool error", flush=True)
                    else:
                        console.success("Tool completed", flush=True)

        # Collect final result from ResultMessage
        if message_type == "ResultMessage":
            if hasattr(message, "result"):
                result_text = message.result
                console.newline()  # Add newline after completion

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
            ModelType.SONNET: "claude-sonnet-4-5-20241022",
            ModelType.OPUS: "claude-opus-4-5-20250514",
            ModelType.HAIKU: "claude-haiku-4-5-20241022",
        }
        return model_map.get(target_model, "claude-sonnet-4-5-20241022")

    def _build_planning_prompt(self, goal: str, context: str) -> str:
        """Build prompt for planning phase."""
        prompt = f"""You are Claude Task Master, an autonomous task orchestration system.

GOAL: {goal}

Your task is to:
1. Analyze the goal and understand what needs to be done
2. Explore the codebase if relevant (use Read, Glob, Grep tools)
3. Create a detailed, well-organized task list with markdown checkboxes
4. Classify each task by complexity for optimal model routing
5. Define clear, testable success criteria

IMPORTANT SETUP:
- If the project has a .gitignore file, ensure that .claude-task-master/ is added to it
- This directory contains task state and should not be committed to version control

{context}

Please create a comprehensive plan with:

## Task List

Organize tasks into logical phases if the goal is complex. Each task should be:
- **Specific and actionable** - Clear what needs to be done
- **Testable** - Can verify when complete
- **Appropriately sized** - Not too large or too small
- **Ordered logically** - Dependencies should come first
- **Classified by complexity** - Tag with appropriate model tier

Use this EXACT format (the tag is required for model routing):
- [ ] `[coding]` Task requiring complex implementation, algorithms, or architecture
- [ ] `[quick]` Simple config change, fix typo, update version number
- [ ] `[general]` Moderate task like documentation, testing, refactoring

**Complexity Classification Guide:**
- `[coding]` → Opus (smartest): New features, complex logic, debugging tricky issues, architecture decisions
- `[quick]` → Haiku (fastest): Config changes, simple edits, renaming, updating values, small fixes
- `[general]` → Sonnet (balanced): Documentation, tests, moderate refactoring, standard implementations

**Prefer `[coding]` when in doubt** - it's better to use a smarter model than struggle with a simpler one.

## Success Criteria

Define 3-5 clear, measurable criteria that indicate complete success:
1. Criterion with specific metric or outcome
2. Another criterion that can be objectively verified
...

Remember: The task list will be executed sequentially, so order matters."""
        return prompt

    def _build_work_prompt(
        self, task_description: str, context: str, pr_comments: str | None
    ) -> str:
        """Build prompt for work session."""
        prompt = f"""You are Claude Task Master working on a specific task.

CURRENT TASK: {task_description}

{context}"""

        if pr_comments:
            prompt += f"""

PR REVIEW COMMENTS TO ADDRESS:
{pr_comments}"""

        prompt += """

Please complete this task using the available tools (Read, Write, Edit, Bash, Glob, Grep).

Important instructions:
- Work autonomously and methodically
- Test your changes to verify they work
- After completing the task, COMMIT your changes with git
- Use a clear, descriptive commit message
- When you complete the task, provide a clear summary of what was done
- Report any blockers or issues encountered

Git commit format:
```bash
git add -A && git commit -m "$(cat <<'EOF'
Brief description of changes

Detailed explanation of what was done and why.

Co-Authored-By: Claude Sonnet 4.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

When done, summarize:
1. What was completed
2. Any tests run and their results
3. Any files modified
4. Git commit made"""

        return prompt

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
