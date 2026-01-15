"""Agent Wrapper - Encapsulates all Claude Agent SDK interactions."""

import asyncio
import os
from enum import Enum
from typing import TYPE_CHECKING, Any

from . import console

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

    # Planning now uses all tools since Claude needs full access to explore and create plans
    PLANNING = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Task", "TodoWrite"]
    WORKING = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Task", "TodoWrite"]


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
        hooks: dict[str, list["HookMatcher"]] | None = None,
        enable_safety_hooks: bool = True,
        logger: "TaskLogger | None" = None,
    ):
        """Initialize agent wrapper.

        Args:
            access_token: OAuth access token for Claude API.
            model: The Claude model to use.
            working_dir: Working directory for file operations.
            max_retries: Maximum number of retries for transient errors.
            initial_backoff: Initial backoff time in seconds.
            max_backoff: Maximum backoff time in seconds.
            hooks: Optional pre-configured hooks dictionary for ClaudeAgentOptions.
            enable_safety_hooks: If True and hooks is None, create default safety hooks.
            logger: Optional TaskLogger for capturing tool usage and responses.

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
        self.hooks = hooks
        self.enable_safety_hooks = enable_safety_hooks
        self.logger = logger

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
        """Verify if success criteria are met."""
        prompt = f"""Review the following success criteria and verify if they have been met:

{criteria}

{context}

**IMPORTANT**: Your response MUST start with one of these two lines:
- "VERIFICATION_RESULT: PASS" - if ALL criteria are met
- "VERIFICATION_RESULT: FAIL" - if ANY criterion is not met

Then provide:
1. Whether each criterion is met (✓/✗)
2. Evidence for each criterion
3. Any issues or gaps

Be strict - only say PASS if ALL criteria are truly met."""

        # Run async query
        result = asyncio.run(
            self._run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("planning"),
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
                    # Claude's text response - stream without prefix
                    console.stream(block.text)
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
                    # Tool result - show completion
                    if block.is_error:
                        console.error("Tool error", flush=True)
                        if self.logger:
                            self.logger.log_tool_result(block.tool_use_id, "ERROR")
                    else:
                        console.success("Tool completed", flush=True)
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
            ModelType.SONNET: "claude-sonnet-4-5-20250929",
            ModelType.OPUS: "claude-opus-4-5-20251101",
            ModelType.HAIKU: "claude-haiku-4-5-20251001",
        }
        return model_map.get(target_model, "claude-sonnet-4-5-20250929")

    def _build_planning_prompt(self, goal: str, context: str) -> str:
        """Build prompt for planning phase."""
        prompt = f"""You are Claude Task Master, an autonomous task orchestration system.

GOAL: {goal}

## Your Mission

You will plan and then autonomously execute a series of tasks to achieve this goal.
The workflow is: Plan → Work → Push → PR → CI/Review → Fix if needed → Repeat → Success

## Phase 1: Exploration & Understanding

First, thoroughly explore the codebase:
1. Read relevant files to understand the architecture
2. Use Glob to find file patterns
3. Use Grep to search for specific code patterns
4. Identify dependencies, tests, CI configuration, and coding standards

## Phase 2: Create the Plan

{context}

IMPORTANT SETUP:
- Add `.claude-task-master/` to .gitignore if not already present
- This directory stores task state and should not be committed

## Task List Format

Create tasks that are:
- **Atomic**: Each task should be a single PR-able unit of work
- **Testable**: Can verify completion (tests pass, lint clean, etc.)
- **Ordered**: Dependencies first, then dependent tasks
- **Tagged**: Complexity tag for model routing

Use this EXACT format:
```markdown
- [ ] `[coding]` Complex implementation requiring architecture decisions
- [ ] `[quick]` Simple fix, config change, or typo correction
- [ ] `[general]` Standard task like tests, docs, or refactoring
```

**Model Routing:**
- `[coding]` → **Opus** (smartest): New features, complex logic, debugging, architecture
- `[quick]` → **Haiku** (fastest): Config, simple edits, renaming, small fixes
- `[general]` → **Sonnet** (balanced): Tests, docs, refactoring, standard implementations

**When in doubt, use `[coding]`** - better to use a smarter model than struggle.

## PR Strategy

Group related tasks into logical PRs:
- Each PR should be focused and reviewable
- Include a task for "Create PR for [feature]" after implementation tasks
- Consider CI and code review feedback cycles

Example task flow:
```markdown
- [ ] `[coding]` Implement feature X core logic
- [ ] `[general]` Add tests for feature X
- [ ] `[quick]` Update documentation for feature X
- [ ] `[general]` Create PR for feature X, wait for CI and reviews
- [ ] `[coding]` Address PR feedback if any
```

## Success Criteria

Define 3-5 clear, measurable criteria:
1. All tests pass (`pytest` or equivalent)
2. Linting/formatting clean (`ruff`, `mypy`, etc.)
3. CI pipeline green
4. PRs merged (if applicable)
5. Specific functional requirement met

Be specific and verifiable. These will be checked at the end."""
        return prompt

    def _build_work_prompt(
        self, task_description: str, context: str, pr_comments: str | None
    ) -> str:
        """Build prompt for work session."""
        prompt = f"""You are Claude Task Master, an autonomous AI agent executing tasks.

## Current Task

{task_description}

## Context

{context}"""

        if pr_comments:
            prompt += f"""

## PR Review Comments to Address

The following feedback was received from code reviewers (CodeRabbit, human reviewers, etc.):

{pr_comments}

**Instructions for addressing reviews:**
- Read each comment carefully
- Make the requested changes or explain why not needed
- Run tests after changes to ensure nothing breaks
- Commit with a message referencing the review feedback
"""

        prompt += """

## Execution Guidelines

### 1. Understand Before Acting
- Read relevant files before modifying them
- Check existing patterns and coding standards
- Identify tests that need to pass

### 2. Make Changes
- Use Edit for existing files, Write for new files
- Follow the project's coding style
- Keep changes focused on the current task

### 3. Verify Your Work
- Run tests: `pytest`, `npm test`, or project-specific commands
- Run linting: `ruff check .`, `eslint`, etc.
- Check types if applicable: `mypy`, `tsc`

### 4. Commit Your Changes
Use conventional commits with clear messages:

```bash
git add -A && git commit -m "$(cat <<'EOF'
feat/fix/chore: Brief description (50 chars max)

- Detailed bullet points of what changed
- Why this change was needed
- Any relevant context

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### 5. Handle PR Tasks (CRITICAL)
**You MUST complete the full PR cycle before starting any new feature:**

1. **Create PR** (if not exists):
   ```bash
   git push -u origin HEAD
   gh pr create --title "..." --body "..."
   ```

2. **Wait for CI to pass**:
   ```bash
   gh pr checks --watch  # Wait for all checks
   ```

3. **Address any review feedback**:
   - Check for comments: `gh pr view --comments`
   - Make requested changes, commit, push
   - Re-run CI checks

4. **MERGE the PR before moving on**:
   ```bash
   gh pr merge --squash --delete-branch
   ```

**IMPORTANT**: Do NOT start work on a new feature while a PR is still open.
The correct workflow is: Work → PR → CI → Fix if needed → Merge → Next task

### 6. Mark Tasks Complete
After completing a task and merging any PR:
- Update plan.md to mark the task as done: `- [x]`
- Move to the next task only after the current one is fully complete

## Completion Summary

When done, provide:
1. **What was completed** - specific changes made
2. **Tests run** - commands and results
3. **Files modified** - list of changed files
4. **Git status** - commits made, push status, PR merged?
5. **Blockers** - any issues encountered"""

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
