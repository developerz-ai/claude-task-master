"""Console output utilities with colored prefixes.

Prefixes:
- [claudetm HH:MM:SS] cyan - orchestrator messages
- [claude HH:MM:SS] orange - Claude's tool usage
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


def _prefix() -> str:
    """Generate orchestrator prefix [claudetm] with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    return f"{CYAN}{BOLD}[claudetm {timestamp}]{RESET}"


def _claude_prefix() -> str:
    """Generate Claude prefix [claude] with timestamp (orange)."""
    timestamp = datetime.now().strftime("%H:%M:%S")
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
    """Print streaming text (no prefix, for Claude's output)."""
    print(text, end=end, flush=flush)


def newline() -> None:
    """Print a newline."""
    print()
