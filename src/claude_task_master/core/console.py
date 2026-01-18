"""Console output utilities with colored prefixes.

Prefixes:
- [claudetm HH:MM:SS N/M] cyan - orchestrator messages with task progress
- [claude HH:MM:SS N/M] orange - Claude's tool usage with task progress
"""

from datetime import datetime

# ANSI color codes
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
ORANGE = "\033[38;5;208m"  # Anthropic orange
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# Global task context for displaying progress in Claude prefix
_task_current: int | None = None
_task_total: int | None = None


def set_task_context(current: int, total: int) -> None:
    """Set the current task context for display in Claude prefix.

    Args:
        current: Current task number (1-indexed)
        total: Total number of tasks
    """
    global _task_current, _task_total
    _task_current = current
    _task_total = total


def clear_task_context() -> None:
    """Clear the task context (used when task execution completes)."""
    global _task_current, _task_total
    _task_current = None
    _task_total = None


def get_task_context() -> tuple[int | None, int | None]:
    """Get the current task context.

    Returns:
        Tuple of (current, total) or (None, None) if not set
    """
    return _task_current, _task_total


def _prefix() -> str:
    """Generate orchestrator prefix [claudetm] with timestamp and task counter.

    Format: [claudetm HH:MM:SS N/M] when task context is set, otherwise [claudetm HH:MM:SS]
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    if _task_current is not None and _task_total is not None:
        return f"{CYAN}{BOLD}[claudetm {timestamp} {_task_current}/{_task_total}]{RESET}"
    return f"{CYAN}{BOLD}[claudetm {timestamp}]{RESET}"


def _claude_prefix() -> str:
    """Generate Claude prefix [claude] with timestamp and task counter (orange).

    Format: [claude HH:MM:SS N/M] when task context is set, otherwise [claude HH:MM:SS]
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    if _task_current is not None and _task_total is not None:
        return f"{ORANGE}{BOLD}[claude {timestamp} {_task_current}/{_task_total}]{RESET}"
    return f"{ORANGE}{BOLD}[claude {timestamp}]{RESET}"


def info(message: str, *, end: str = "\n", flush: bool = False) -> None:
    """Print info message with prefix."""
    print(f"{_prefix()} {message}", end=end, flush=flush)


def success(message: str, *, end: str = "\n", flush: bool = False) -> None:
    """Print success message with prefix (green)."""
    print(f"{_prefix()} {GREEN}{message}{RESET}", end=end, flush=flush)


def warning(message: str, *, end: str = "\n", flush: bool = False) -> None:
    """Print warning message with prefix (yellow)."""
    print(f"{_prefix()} {YELLOW}{message}{RESET}", end=end, flush=flush)


def error(message: str, *, end: str = "\n", flush: bool = False) -> None:
    """Print error message with prefix (red)."""
    print(f"{_prefix()} {RED}{message}{RESET}", end=end, flush=flush)


def detail(message: str, *, end: str = "\n", flush: bool = False) -> None:
    """Print detail/secondary message with prefix (dim)."""
    print(f"{_prefix()} {DIM}   {message}{RESET}", end=end, flush=flush)


def tool(message: str, *, end: str = "\n", flush: bool = False) -> None:
    """Print Claude's tool usage with [claude] prefix (orange)."""
    print(f"{_claude_prefix()} {message}", end=end, flush=flush)


def stream(text: str, *, end: str = "", flush: bool = True) -> None:
    """Print streaming text (no prefix, for real-time output)."""
    print(text, end=end, flush=flush)


def claude_text(message: str, *, end: str = "\n", flush: bool = False) -> None:
    """Print Claude's text response with [claude] prefix (orange)."""
    print(f"{_claude_prefix()} {message}", end=end, flush=flush)


def tool_result(message: str, *, is_error: bool = False, flush: bool = True) -> None:
    """Print tool result with [claude] prefix."""
    if is_error:
        print(f"{_claude_prefix()} {RED}{message}{RESET}", flush=flush)
    else:
        print(f"{_claude_prefix()} {GREEN}{message}{RESET}", flush=flush)


def newline() -> None:
    """Print a newline."""
    print()
