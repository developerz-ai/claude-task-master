"""Conversation Manager - Multi-turn conversations via ClaudeSDKClient.

Manages conversation sessions for task groups, allowing Claude to maintain
context across multiple tasks within the same group.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from . import console
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .config_loader import get_config
from .rate_limit import RateLimitConfig
from .subagents import get_agents_for_working_dir

if TYPE_CHECKING:
    from .hooks import HookMatcher
    from .logger import TaskLogger


class ConversationError(Exception):
    """Base exception for conversation-related errors."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class SDKImportError(ConversationError):
    """Raised when the Claude Agent SDK cannot be imported."""

    def __init__(self, original_error: Exception | None = None):
        self.original_error = original_error
        details = str(original_error) if original_error else None
        super().__init__(
            "claude-agent-sdk not installed or cannot be imported",
            details or "Install with: pip install claude-agent-sdk",
        )


class QueryExecutionError(ConversationError):
    """Raised when a query execution fails."""

    def __init__(self, message: str, original_error: Exception | None = None):
        self.original_error = original_error
        details = str(original_error) if original_error else None
        super().__init__(message, details)


# Model types (duplicated here to avoid circular imports)
class ModelType:
    """Available Claude models - simplified enum for conversation module."""

    SONNET = "sonnet"
    OPUS = "opus"
    HAIKU = "haiku"


# Default working tools
DEFAULT_TOOLS = [
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
    "Skill",
]


class ConversationManager:
    """Manages ClaudeSDKClient for multi-turn conversations within task groups.

    Each task group (e.g., "Schema & Model Fixes") gets a single conversation,
    allowing Claude to remember context from previous tasks in the same group.
    This is faster and provides better context than starting fresh for each task.

    Usage:
        async with conversation_manager.conversation(group_id="group_1") as conv:
            result1 = await conv.query_task(task1, context)
            result2 = await conv.query_task(task2, context)  # Remembers task1

    When moving to a new group, the previous conversation is closed and a new
    one is started.
    """

    def __init__(
        self,
        working_dir: str,
        model: str = "sonnet",
        hooks: dict[str, list[HookMatcher]] | None = None,
        logger: TaskLogger | None = None,
        rate_limit_config: RateLimitConfig | None = None,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
        verbose: bool = False,
    ):
        """Initialize conversation manager.

        Args:
            working_dir: Working directory for file operations.
            model: Default model to use ("sonnet", "opus", "haiku").
            hooks: Optional hooks configuration.
            logger: Optional logger for recording activity.
            rate_limit_config: Rate limiting configuration.
            circuit_breaker_config: Circuit breaker configuration.
            verbose: Show detailed tool output (default: False).
        """
        self.working_dir = working_dir
        self.model = model
        self.hooks = hooks
        self.logger = logger
        self.verbose = verbose
        self.rate_limit_config = rate_limit_config or RateLimitConfig.default()
        self.circuit_breaker = CircuitBreaker(
            name="claude_conversation",
            config=circuit_breaker_config or CircuitBreakerConfig.default(),
        )

        # SDK components - imported lazily
        self._sdk_client_class: type | None = None
        self._options_class: type | None = None

        # Track current group for logging (can't reuse clients across event loops)
        self._active_group: str | None = None

    def _ensure_sdk_imported(self) -> None:
        """Ensure the Claude Agent SDK is imported."""
        if self._sdk_client_class is not None:
            return

        try:
            import claude_agent_sdk

            self._sdk_client_class = claude_agent_sdk.ClaudeSDKClient
            self._options_class = claude_agent_sdk.ClaudeAgentOptions
        except ImportError as e:
            raise SDKImportError(e) from e
        except AttributeError as e:
            raise ConversationError(
                "Failed to initialize SDK component: ClaudeSDKClient",
                str(e),
            ) from e

    def _get_model_name(self, model: str | None = None) -> str:
        """Convert model string to API model name using global config.

        Model names are loaded from configuration, which can be:
        - Set in `.claude-task-master/config.json`
        - Overridden via environment variables (CLAUDETM_MODEL_SONNET, etc.)

        Args:
            model: Optional model override. If None, uses self.model.

        Returns:
            The API model name string from configuration.
        """
        target_model = model or self.model
        config = get_config()
        model_map = {
            "sonnet": config.models.sonnet,
            "opus": config.models.opus,
            "haiku": config.models.haiku,
        }
        return model_map.get(target_model, config.models.sonnet)

    def _create_options(
        self,
        tools: list[str],
        model_override: str | None = None,
    ) -> Any:
        """Create ClaudeAgentOptions for a conversation."""
        self._ensure_sdk_imported()
        model_name = self._get_model_name(model_override)

        if self._options_class is None:
            raise ConversationError("SDK not initialized")

        # Load subagents from .claude/agents/ directory
        agents = get_agents_for_working_dir(self.working_dir)

        return self._options_class(
            allowed_tools=tools,
            permission_mode="bypassPermissions",
            model=model_name,
            cwd=str(self.working_dir),
            setting_sources=["user", "local", "project"],
            hooks=self.hooks,
            agents=agents if agents else None,
        )

    @asynccontextmanager
    async def conversation(
        self,
        group_id: str,
        tools: list[str] | None = None,
        model_override: str | None = None,
    ) -> AsyncIterator[ConversationSession]:
        """Context manager for a conversation session.

        If the group_id matches the active conversation, reuses it.
        Otherwise, closes the previous conversation and starts a new one.

        Args:
            group_id: Unique identifier for the task group.
            tools: List of tools to enable (defaults to working tools).
            model_override: Optional model override for this conversation.

        Yields:
            ConversationSession for sending queries.
        """
        self._ensure_sdk_imported()

        effective_tools = tools or DEFAULT_TOOLS

        # NOTE: We cannot reuse clients across asyncio.run() calls because each
        # asyncio.run() creates a new event loop. The client from a previous
        # event loop cannot be used in a new one. For true conversation reuse,
        # we'd need a persistent event loop architecture.
        #
        # For now, create a fresh client each time but track the group for logging.
        if self._active_group == group_id:
            console.detail(f"Continuing work in group: {group_id}")
        else:
            console.info(f"Starting conversation for group: {group_id}")
        options = self._create_options(effective_tools, model_override)

        if self._sdk_client_class is None:
            raise ConversationError("SDK not initialized")

        # Change to working directory
        original_dir = os.getcwd()
        client = None
        try:
            os.chdir(self.working_dir)

            client = self._sdk_client_class(options=options)
            await client.connect()

            self._active_group = group_id

            yield ConversationSession(
                client=client,
                manager=self,
                group_id=group_id,
            )
        finally:
            os.chdir(original_dir)
            # Always disconnect - can't reuse across event loops
            if client is not None:
                try:
                    await client.disconnect()
                except Exception as e:
                    console.warning(f"Error disconnecting: {e}")

    async def close_all(self) -> None:
        """Close any active conversation.

        Note: With the current architecture using asyncio.run() per task,
        connections are closed after each task. This method is kept for
        API compatibility and future persistent event loop support.
        """
        self._active_group = None

    @property
    def active_group(self) -> str | None:
        """Get the currently active group ID."""
        return self._active_group

    @property
    def has_active_conversation(self) -> bool:
        """Check if there's an active conversation group."""
        return self._active_group is not None


class ConversationSession:
    """A session within an active conversation.

    Provides methods to send queries and process responses while maintaining
    conversation context across multiple tasks in the same group.
    """

    def __init__(
        self,
        client: Any,  # ClaudeSDKClient
        manager: ConversationManager,
        group_id: str,
    ):
        """Initialize conversation session.

        Args:
            client: The ClaudeSDKClient instance.
            manager: Parent ConversationManager.
            group_id: The group this session belongs to.
        """
        self.client = client
        self.manager = manager
        self.group_id = group_id
        self._query_count = 0

    @property
    def query_count(self) -> int:
        """Number of queries sent in this session."""
        return self._query_count

    async def query_task(
        self,
        prompt: str,
        model_override: str | None = None,
    ) -> str:
        """Send a task query within this conversation.

        Claude will remember all previous queries in this conversation,
        providing context continuity within the task group.

        Args:
            prompt: The task prompt to send.
            model_override: Optional model override (note: may not take effect
                           mid-conversation depending on SDK behavior).

        Returns:
            The result text from the query.
        """
        self._query_count += 1
        result_text = ""

        console.detail(f"Conversation query #{self._query_count} in group '{self.group_id}'")

        try:
            # Send query (conversation context is maintained by the client)
            await self.client.query(prompt)

            # Process response
            async for message in self.client.receive_response():
                result_text = self._process_message(message, result_text)

        except Exception as e:
            console.error(f"Query failed: {e}")
            raise QueryExecutionError(f"Conversation query failed: {e}", e) from e

        return result_text

    def _process_message(self, message: Any, result_text: str) -> str:
        """Process a message from the response stream.

        Args:
            message: The message to process.
            result_text: Accumulated result text.

        Returns:
            Updated result text.
        """
        message_type = type(message).__name__

        if hasattr(message, "content") and message.content:
            for block in message.content:
                block_type = type(block).__name__

                if block_type == "TextBlock":
                    console.claude_text(block.text.strip(), flush=True)
                    result_text += block.text
                elif block_type == "ToolUseBlock":
                    console.newline()
                    tool_input = getattr(block, "input", {})
                    tool_detail = self._format_tool_detail(block.name, tool_input)
                    console.tool(f"Using tool: {block.name} {tool_detail}", flush=True)
                    if self.manager.logger:
                        self.manager.logger.log_tool_use(block.name, tool_input)
                elif block_type == "ToolResultBlock":
                    if block.is_error:
                        console.tool_result("Tool error", is_error=True)
                        if self.manager.logger:
                            self.manager.logger.log_tool_result(block.tool_use_id, "ERROR")
                    else:
                        # Show tool result summary if available
                        summary = self._format_tool_result_summary(block)
                        if summary:
                            console.tool_result(summary)
                        else:
                            console.tool_result("Tool completed")
                        if self.manager.logger:
                            self.manager.logger.log_tool_result(block.tool_use_id, "completed")

        # Collect final result from ResultMessage
        if message_type == "ResultMessage":
            if hasattr(message, "result"):
                result_text = message.result
                console.newline()

        return result_text

    def _format_tool_result_summary(self, block: Any) -> str:
        """Format tool result into a summary like Claude Code does.

        Shows last few lines of actual output content when verbose mode enabled.

        Args:
            block: The ToolResultBlock.

        Returns:
            Summary string with preview of output (if verbose), else empty string.
        """
        # Only show detailed output in verbose mode
        if not self.manager.verbose:
            return ""

        content = getattr(block, "content", None)
        if not content:
            return ""

        # Handle content as list of content blocks or string
        text = ""
        if isinstance(content, list):
            for item in content:
                if hasattr(item, "text"):
                    text += item.text
                elif isinstance(item, str):
                    text += item
        elif isinstance(content, str):
            text = content

        if not text:
            return ""

        import re

        # Look for edit summaries (Added X lines, removed Y lines)
        edit_match = re.search(r"(Added|Changed|Removed).*?(line|lines)", text, re.IGNORECASE)
        if edit_match:
            for line in text.split("\n"):
                if "line" in line.lower() and (
                    "added" in line.lower()
                    or "removed" in line.lower()
                    or "changed" in line.lower()
                ):
                    return line.strip()[:80]

        # Show last few lines of actual output (most relevant - test results, etc.)
        all_lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
        if not all_lines:
            return ""

        # Take last 3 non-empty lines
        last_lines = all_lines[-3:]
        preview_lines = []

        if len(all_lines) > 3:
            preview_lines.append(f"... ({len(all_lines)} lines)")

        for line in last_lines:
            if len(line) > 77:
                line = line[:74] + "..."
            preview_lines.append(line)

        return "\n   ⎿  ".join(preview_lines)

    def _format_tool_detail(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Format tool input for display."""
        if not tool_input:
            return ""

        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            if len(cmd) > 250:
                cmd = cmd[:247] + "..."
            return f"→ {cmd}"
        elif tool_name in ("Read", "Write", "Edit"):
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
            if tool_input:
                first_key = next(iter(tool_input))
                first_val = str(tool_input[first_key])[:50]
                return f"→ {first_key}={first_val}"
            return ""
