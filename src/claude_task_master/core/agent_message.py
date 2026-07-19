"""Agent Message Processing - Handles message parsing and formatting.

This module contains the message processing logic extracted from AgentWrapper,
following the Single Responsibility Principle (SRP). It handles:
- Processing messages from the query stream
- Formatting tool details for display
- Console output for tool usage and results
"""

import os
from typing import TYPE_CHECKING, Any

from . import console

if TYPE_CHECKING:
    from .logger import TaskLogger


class MessageProcessor:
    """Handles processing of messages from the Claude Agent SDK query stream.

    This class is responsible for parsing messages, displaying tool usage,
    and accumulating result text from the query stream.
    """

    def __init__(self, logger: "TaskLogger | None" = None):
        """Initialize the message processor.

        Args:
            logger: Optional TaskLogger for capturing tool usage and responses.
        """
        self.logger = logger
        # Terminal outcome of the most recently processed ResultMessage.
        # Callers derive session success from this instead of assuming it.
        # Reset per query via reset_result_state(). Defaults describe "no
        # terminal result seen yet": is_error=False so a session whose
        # ResultMessage is lost (SDK bug #30333) is still treated as success
        # from its accumulated text, matching prior behavior.
        self.last_result_is_error: bool = False
        self.last_result_subtype: str | None = None
        # Actual cost/token data from the most recent ResultMessage.
        # None until a ResultMessage is processed; stays None when the SDK
        # omits the field (e.g. error results or older SDK versions).
        self.last_total_cost_usd: float | None = None
        self.last_input_tokens: int = 0
        self.last_output_tokens: int = 0

    def reset_result_state(self) -> None:
        """Clear captured terminal-result state before a new query.

        A single MessageProcessor is reused across successive queries, so this
        must run before each query to stop a prior session's error outcome from
        leaking into the next session's derived success.
        """
        self.last_result_is_error = False
        self.last_result_subtype = None
        self.last_total_cost_usd = None
        self.last_input_tokens = 0
        self.last_output_tokens = 0

    def process_message(self, message: Any, result_text: str) -> str:
        """Process a message from the query stream.

        Handles different message types:
        - TextBlock: Claude's text response - accumulated to result
        - ToolUseBlock: Tool invocation - logged and displayed
        - ToolResultBlock: Tool result - displayed with success/error status
        - ResultMessage: Final result - captured as result text

        Args:
            message: The message to process from the SDK stream.
            result_text: The accumulated result text so far.

        Returns:
            Updated result text after processing this message.
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
                    tool_detail = self.format_tool_detail(block.name, tool_input)
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

        # Handle RateLimitEvent typed messages from SDK v0.1.49+
        if message_type == "RateLimitEvent":
            retry_after = getattr(message, "retry_after", None)
            message_text = getattr(message, "message", "")
            if retry_after:
                console.warning(f"Rate limited: {message_text} (retry in {retry_after}s)")
            else:
                console.warning(f"Rate limited: {message_text}")
            if self.logger:
                self.logger.log_tool_use("RateLimitEvent", {"retry_after": retry_after})
            return result_text

        # Collect final result from ResultMessage
        # Important: Only use message.result if we have no accumulated text,
        # or if message.result contains content not in our accumulated text.
        # This preserves verification markers (VERIFICATION_RESULT: PASS/FAIL)
        # that may be output in earlier TextBlocks.
        if message_type == "ResultMessage":
            # Capture the terminal outcome so callers can derive session
            # success from the SDK instead of hardcoding it. ``is_error`` is
            # authoritative: it is True for error_max_turns /
            # error_during_execution / error_max_budget_usd, and for API
            # errors even when ``subtype`` stays "success".
            self.last_result_is_error = bool(getattr(message, "is_error", False))
            self.last_result_subtype = getattr(message, "subtype", None)
            if self.last_result_is_error:
                detail = self.last_result_subtype or "unknown"
                console.warning(f"Session ended with error result: {detail}")
                if self.logger:
                    self.logger.log_tool_result("ResultMessage", f"is_error subtype={detail}")

            # Extract actual cost and token usage (SDK v0.1+ ResultMessage fields).
            # total_cost_usd is the authoritative figure; usage carries per-token
            # counts for display. Both are optional — older SDK versions or error
            # results may omit them, so we guard with getattr.
            cost_usd = getattr(message, "total_cost_usd", None)
            if cost_usd is not None:
                self.last_total_cost_usd = float(cost_usd)
            usage = getattr(message, "usage", None)
            if usage is not None:
                self.last_input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                self.last_output_tokens = int(getattr(usage, "output_tokens", 0) or 0)

            # Log stop_reason for diagnostics (SDK v0.1.46+)
            stop_reason = getattr(message, "stop_reason", None)
            if stop_reason and self.logger:
                self.logger.log_tool_result("ResultMessage", f"stop_reason={stop_reason}")
            if stop_reason and stop_reason not in ("end_turn", "tool_use"):
                console.detail(f"Session ended: {stop_reason}")

            if hasattr(message, "result") and message.result:
                # If we have no accumulated text, use the result
                if not result_text.strip():
                    result_text = message.result
                    console.newline()  # Add newline after completion
                # If message.result contains verification markers we're missing,
                # prefer message.result (it might be more complete)
                elif (
                    "verification_result:" in message.result.lower()
                    and "verification_result:" not in result_text.lower()
                ):
                    result_text = message.result
                    console.newline()  # Add newline after completion
                # Otherwise keep our accumulated text (it has the markers)

        return result_text

    @staticmethod
    def _relative_path(path: str) -> str:
        """Convert an absolute path to a relative path if possible.

        Args:
            path: The path to convert.

        Returns:
            Relative path if under cwd, otherwise the original path.
        """
        if not path:
            return path
        try:
            cwd = os.getcwd()
            if os.path.isabs(path) and path.startswith(cwd):
                rel = os.path.relpath(path, cwd)
                return rel if rel else path
            return path
        except (ValueError, OSError):
            return path

    def format_tool_detail(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Format tool input for display.

        Shows the most relevant parameter for each tool type to provide
        helpful context without overwhelming output.

        Args:
            tool_name: The name of the tool being invoked.
            tool_input: The input parameters for the tool.

        Returns:
            A formatted string showing the key parameter, e.g., "→ path/to/file"
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
            path = self._relative_path(tool_input.get("file_path", ""))
            return f"→ {path}"
        elif tool_name == "Write":
            path = self._relative_path(tool_input.get("file_path", ""))
            return f"→ {path}"
        elif tool_name == "Edit":
            path = self._relative_path(tool_input.get("file_path", ""))
            return f"→ {path}"
        elif tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            path = self._relative_path(tool_input.get("path", "."))
            return f"→ {pattern} in {path}"
        elif tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            path = self._relative_path(tool_input.get("path", "."))
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


def create_message_processor(logger: "TaskLogger | None" = None) -> MessageProcessor:
    """Factory function to create a MessageProcessor instance.

    Args:
        logger: Optional TaskLogger for capturing tool usage.

    Returns:
        A configured MessageProcessor instance.
    """
    return MessageProcessor(logger=logger)
