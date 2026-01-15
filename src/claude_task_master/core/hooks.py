"""SDK Hooks - Intercept and control agent behavior with safety controls and logging.

This module provides hook implementations for the Claude Agent SDK that enable:
- Blocking dangerous shell commands before execution
- Audit logging of all tool usage
- Permission validation and approval flows
- Real-time progress tracking
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .logger import TaskLogger


# =============================================================================
# Type Definitions
# =============================================================================


class HookCallback(Protocol):
    """Protocol for hook callback functions."""

    async def __call__(
        self,
        input_data: dict[str, Any],
        tool_use_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute hook callback.

        Args:
            input_data: Event details including tool_name, tool_input, etc.
            tool_use_id: Unique ID to correlate PreToolUse and PostToolUse events.
            context: Additional context for the hook.

        Returns:
            Hook output dictionary. Return {} to allow operation unchanged.
        """
        ...


@dataclass
class HookMatcher:
    """Configuration for matching hooks to tools.

    Attributes:
        hooks: List of callback functions to execute.
        matcher: Optional regex pattern to match tool names.
        timeout: Timeout in seconds for hook execution.
    """

    hooks: list[HookCallback]
    matcher: str | None = None
    timeout: int = 60


@dataclass
class HookResult:
    """Result from a hook execution.

    Attributes:
        allowed: Whether the operation is allowed to proceed.
        reason: Explanation for the decision.
        modified_input: Optional modified tool input.
        additional_context: Optional context to add to conversation.
    """

    allowed: bool = True
    reason: str = ""
    modified_input: dict[str, Any] | None = None
    additional_context: str = ""


# =============================================================================
# Dangerous Command Patterns
# =============================================================================


@dataclass
class DangerousPattern:
    """A pattern that identifies a dangerous command.

    Attributes:
        pattern: Regex pattern to match.
        description: Human-readable description of the danger.
        severity: How dangerous (critical, high, medium, low).
    """

    pattern: str
    description: str
    severity: str = "high"


# Patterns that should be blocked by default
DEFAULT_DANGEROUS_PATTERNS: list[DangerousPattern] = [
    # Destructive file operations
    DangerousPattern(
        r"rm\s+-rf\s+/(?!\S)",  # rm -rf / (but not rm -rf /some/path)
        "Recursive deletion of root filesystem",
        "critical",
    ),
    DangerousPattern(
        r"rm\s+-rf\s+\*",
        "Recursive deletion of all files",
        "critical",
    ),
    DangerousPattern(
        r"rm\s+-rf\s+~/",
        "Recursive deletion of home directory",
        "critical",
    ),
    DangerousPattern(
        r"rm\s+-rf\s+\$HOME",
        "Recursive deletion of home directory",
        "critical",
    ),
    # Privilege escalation
    DangerousPattern(
        r"sudo\s+rm",
        "Privileged file deletion",
        "high",
    ),
    DangerousPattern(
        r"chmod\s+777",
        "Insecure permission change",
        "medium",
    ),
    DangerousPattern(
        r"chmod\s+-R\s+777",
        "Recursive insecure permission change",
        "high",
    ),
    # Dangerous disk operations
    DangerousPattern(
        r"dd\s+.*of=/dev/",
        "Direct disk write operation",
        "critical",
    ),
    DangerousPattern(
        r"mkfs\.",
        "Filesystem format operation",
        "critical",
    ),
    # Credential exposure
    DangerousPattern(
        r"curl.*\|\s*(bash|sh)",
        "Piping remote content to shell",
        "high",
    ),
    DangerousPattern(
        r"wget.*\|\s*(bash|sh)",
        "Piping remote content to shell",
        "high",
    ),
    # Git dangerous operations
    DangerousPattern(
        r"git\s+push\s+.*--force.*(main|master)|git\s+push\s+.*(main|master).*--force",
        "Force push to main/master branch",
        "high",
    ),
    DangerousPattern(
        r"git\s+reset\s+--hard",
        "Hard reset (may lose uncommitted changes)",
        "medium",
    ),
]


# =============================================================================
# Hook Implementations
# =============================================================================


@dataclass
class SafetyHooks:
    """Collection of safety-focused hooks.

    Attributes:
        dangerous_patterns: Patterns to block.
        allow_sudo: Whether to allow sudo commands.
        blocked_tools: Tools that are completely blocked.
    """

    dangerous_patterns: list[DangerousPattern] = field(
        default_factory=lambda: list(DEFAULT_DANGEROUS_PATTERNS)
    )
    allow_sudo: bool = False
    blocked_tools: list[str] = field(default_factory=list)

    def check_command(self, command: str) -> HookResult:
        """Check if a bash command is safe to execute.

        Args:
            command: The command to check.

        Returns:
            HookResult indicating whether the command is allowed.
        """
        for pattern in self.dangerous_patterns:
            if re.search(pattern.pattern, command, re.IGNORECASE):
                return HookResult(
                    allowed=False,
                    reason=f"Blocked: {pattern.description} (severity: {pattern.severity})",
                )

        # Check for sudo if not allowed
        if not self.allow_sudo and re.search(r"\bsudo\b", command):
            return HookResult(
                allowed=False,
                reason="Sudo commands are not allowed",
            )

        return HookResult(allowed=True)

    async def pre_tool_use_hook(
        self,
        input_data: dict[str, Any],
        tool_use_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """PreToolUse hook for safety validation.

        Args:
            input_data: Event details.
            tool_use_id: Unique ID for this tool use.
            context: Additional context.

        Returns:
            Hook output with permission decision.
        """
        if input_data.get("hook_event_name") != "PreToolUse":
            return {}

        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        # Check if tool is completely blocked
        if tool_name in self.blocked_tools:
            return {
                "hookSpecificOutput": {
                    "hookEventName": input_data["hook_event_name"],
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"Tool '{tool_name}' is blocked",
                }
            }

        # Check bash commands for dangerous patterns
        if tool_name == "Bash":
            command = tool_input.get("command", "")
            result = self.check_command(command)

            if not result.allowed:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": input_data["hook_event_name"],
                        "permissionDecision": "deny",
                        "permissionDecisionReason": result.reason,
                    }
                }

        return {}


@dataclass
class AuditLogger:
    """Hook for logging all tool usage.

    Attributes:
        logger: Optional TaskLogger for writing audit logs.
        log_callback: Optional callback for custom logging.
        include_tool_input: Whether to include full tool input in logs.
        include_tool_output: Whether to include tool output in logs.
    """

    logger: TaskLogger | None = None
    log_callback: Callable[[dict[str, Any]], None] | None = None
    include_tool_input: bool = True
    include_tool_output: bool = False

    def _log(self, entry: dict[str, Any]) -> None:
        """Log an audit entry.

        Args:
            entry: The audit entry to log.
        """
        if self.log_callback:
            self.log_callback(entry)
        elif self.logger:
            self.logger.log_tool_use(
                tool_name=entry.get("tool", "unknown"),
                parameters=entry.get("input", {}),
            )

    async def pre_tool_use_hook(
        self,
        input_data: dict[str, Any],
        tool_use_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """PreToolUse hook for audit logging.

        Args:
            input_data: Event details.
            tool_use_id: Unique ID for this tool use.
            context: Additional context.

        Returns:
            Empty dict (allows operation, logs only).
        """
        if input_data.get("hook_event_name") != "PreToolUse":
            return {}

        entry: dict[str, Any] = {
            "event": "pre_tool_use",
            "tool_use_id": tool_use_id,
            "tool": input_data.get("tool_name"),
            "timestamp": datetime.now().isoformat(),
            "session_id": input_data.get("session_id"),
        }

        if self.include_tool_input:
            entry["input"] = input_data.get("tool_input", {})

        self._log(entry)
        return {}

    async def post_tool_use_hook(
        self,
        input_data: dict[str, Any],
        tool_use_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """PostToolUse hook for audit logging.

        Args:
            input_data: Event details.
            tool_use_id: Unique ID for this tool use.
            context: Additional context.

        Returns:
            Empty dict (allows operation, logs only).
        """
        if input_data.get("hook_event_name") != "PostToolUse":
            return {}

        entry: dict[str, Any] = {
            "event": "post_tool_use",
            "tool_use_id": tool_use_id,
            "tool": input_data.get("tool_name"),
            "timestamp": datetime.now().isoformat(),
            "is_error": input_data.get("is_error", False),
        }

        if self.include_tool_output:
            entry["output"] = input_data.get("tool_response")

        self._log(entry)
        return {}


@dataclass
class ProgressTracker:
    """Hook for tracking progress during tool execution.

    Attributes:
        on_file_modified: Callback when a file is modified.
        on_command_run: Callback when a command is run.
        on_file_read: Callback when a file is read.
    """

    on_file_modified: Callable[[str], None] | None = None
    on_command_run: Callable[[str], None] | None = None
    on_file_read: Callable[[str], None] | None = None

    async def post_tool_use_hook(
        self,
        input_data: dict[str, Any],
        tool_use_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """PostToolUse hook for progress tracking.

        Args:
            input_data: Event details.
            tool_use_id: Unique ID for this tool use.
            context: Additional context.

        Returns:
            Empty dict.
        """
        if input_data.get("hook_event_name") != "PostToolUse":
            return {}

        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        if tool_name in ("Edit", "Write") and self.on_file_modified:
            file_path = tool_input.get("file_path", "")
            if file_path:
                self.on_file_modified(file_path)

        elif tool_name == "Bash" and self.on_command_run:
            command = tool_input.get("command", "")
            if command:
                # Truncate long commands
                if len(command) > 100:
                    command = command[:97] + "..."
                self.on_command_run(command)

        elif tool_name == "Read" and self.on_file_read:
            file_path = tool_input.get("file_path", "")
            if file_path:
                self.on_file_read(file_path)

        return {}


# =============================================================================
# Hook Configuration Factory
# =============================================================================


def create_default_hooks(
    enable_safety: bool = True,
    enable_audit: bool = True,
    enable_progress: bool = True,
    logger: TaskLogger | None = None,
    progress_tracker: ProgressTracker | None = None,
    allow_sudo: bool = False,
    blocked_tools: list[str] | None = None,
) -> dict[str, list[HookMatcher]]:
    """Create default hook configuration.

    Args:
        enable_safety: Whether to enable safety hooks.
        enable_audit: Whether to enable audit logging.
        enable_progress: Whether to enable progress tracking.
        logger: Optional TaskLogger for audit logging.
        progress_tracker: Optional ProgressTracker for progress tracking.
        allow_sudo: Whether to allow sudo commands.
        blocked_tools: List of tools to completely block.

    Returns:
        Hook configuration dictionary for ClaudeAgentOptions.
    """
    pre_tool_hooks: list[HookCallback] = []
    post_tool_hooks: list[HookCallback] = []

    if enable_safety:
        safety = SafetyHooks(
            allow_sudo=allow_sudo,
            blocked_tools=blocked_tools or [],
        )
        pre_tool_hooks.append(safety.pre_tool_use_hook)

    if enable_audit:
        audit = AuditLogger(logger=logger)
        pre_tool_hooks.append(audit.pre_tool_use_hook)
        post_tool_hooks.append(audit.post_tool_use_hook)

    if enable_progress and progress_tracker:
        post_tool_hooks.append(progress_tracker.post_tool_use_hook)

    hooks: dict[str, list[HookMatcher]] = {}

    if pre_tool_hooks:
        hooks["PreToolUse"] = [HookMatcher(hooks=pre_tool_hooks)]

    if post_tool_hooks:
        hooks["PostToolUse"] = [HookMatcher(hooks=post_tool_hooks)]

    return hooks
