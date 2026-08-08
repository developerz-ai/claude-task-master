"""Console output utilities with colored prefixes.

Prefixes:
- [claudetm HH:MM:SS N/M] cyan - orchestrator messages with task progress
- [claude HH:MM:SS N/M] orange - Claude's tool usage with task progress
- ↳ [agent#N] per-worker color - a subagent's output inside a lead session

Color disabling (:func:`color_enabled`) is honored by the **subagent** markers
only. The prefixes above have always emitted escapes unconditionally and are
left exactly as they were: the lead's stream is the baseline every existing
expectation is written against. The subagent markers are new, so they can be
correct from the start — which matters because a piped or redirected run is
precisely how ``.claude-task-master/logs/`` and shell captures get written.
"""

import os
import sys
from collections.abc import Sequence
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

# Palette for concurrent subagent markers, in assignment order.
#
# Deliberately disjoint from the semantic colors above: CYAN/ORANGE mean
# "orchestrator"/"lead", and GREEN/RED/YELLOW mean success/error/warning, so
# reusing any of them would make a worker's name read as a status. These are
# 256-color entries chosen to stay apart from each other and from ORANGE (208)
# on both light and dark terminals.
SUBAGENT_PALETTE: tuple[str, ...] = (
    "\033[38;5;39m",  # azure
    "\033[38;5;170m",  # orchid
    "\033[38;5;42m",  # spring green
    "\033[38;5;178m",  # gold
    "\033[38;5;204m",  # rose
    "\033[38;5;111m",  # periwinkle
)


def color_enabled() -> bool:
    """Whether ANSI escapes should be emitted for the new (subagent) coloring.

    The standard rule, since this project had no color switch of its own:
    ``NO_COLOR`` set to a non-empty value disables color (no-color.org), and so
    does a stdout that is not a terminal — a redirect into a log file or a pipe
    into ``tee`` wants text, not escapes.

    Returns:
        True when it is safe to emit color escapes on stdout.
    """
    if os.environ.get("NO_COLOR"):
        return False
    isatty = getattr(sys.stdout, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (ValueError, OSError):
        # A closed or detached stream is not a terminal.
        return False


class SubagentPalette:
    """Assigns each concurrent subagent a stable color and short label.

    Several ``hive-worker`` subagents run at once and their output interleaves
    in one stream, so coloring by *agent type* would paint them all the same.
    The key is therefore the subagent's ``tool_use_id``, which is minted when
    the lead spawns it and is constant for that worker's whole life — so a
    worker's color and label never change mid-run, which is the one property
    that makes the color worth having at all.

    Slots are handed out in order of first appearance and cycle through the
    palette, so the workers alive at any moment (few, in practice) differ from
    each other. An instance is owned by one message processor and cleared
    between queries, so ordinals restart per session rather than growing
    forever.
    """

    def __init__(self, palette: Sequence[str] = SUBAGENT_PALETTE) -> None:
        """Initialize with a palette to cycle through.

        Args:
            palette: Non-empty sequence of ANSI color escapes.

        Raises:
            ValueError: If the palette is empty (nothing to cycle).
        """
        if not palette:
            raise ValueError("SubagentPalette requires at least one color")
        self._palette: tuple[str, ...] = tuple(palette)
        self._slots: dict[str, int] = {}

    def clear(self) -> None:
        """Forget every assignment (called between queries)."""
        self._slots = {}

    def slot(self, tool_use_id: str) -> int:
        """Return this worker's 0-based ordinal, assigning one on first sight.

        Args:
            tool_use_id: The subagent's spawning tool-use id.

        Returns:
            A stable ordinal for that id.
        """
        existing = self._slots.get(tool_use_id)
        if existing is not None:
            return existing
        assigned = len(self._slots)
        self._slots[tool_use_id] = assigned
        return assigned

    def color(self, tool_use_id: str) -> str:
        """Return the ANSI color escape assigned to this worker.

        Args:
            tool_use_id: The subagent's spawning tool-use id.

        Returns:
            One entry of the palette, stable for the id's lifetime.
        """
        return self._palette[self.slot(tool_use_id) % len(self._palette)]

    def label(self, tool_use_id: str, name: str) -> str:
        """Return a short human label: the agent name plus a discriminator.

        Args:
            tool_use_id: The subagent's spawning tool-use id.
            name: The agent type (e.g. ``hive-worker``).

        Returns:
            ``"<name>#<n>"`` — ``n`` being the 1-based ordinal, so two live
            ``hive-worker``s read as ``hive-worker#1`` / ``hive-worker#2``.
        """
        return f"{name}#{self.slot(tool_use_id) + 1}"

    def prefix(self, tool_use_id: str, name: str, *, color: bool | None = None) -> str:
        """Build the console marker that precedes a subagent's output line.

        Only the marker is colored; the message text after it is left alone so
        a worker's prose renders exactly as the lead's does.

        Args:
            tool_use_id: The subagent's spawning tool-use id.
            name: The agent type to display.
            color: Force color on/off. ``None`` (default) consults
                :func:`color_enabled`.

        Returns:
            ``"↳ [name#n] "``, wrapped in this worker's color when enabled.
        """
        marker = f"↳ [{self.label(tool_use_id, name)}] "
        if color is None:
            color = color_enabled()
        if not color:
            return marker
        return f"{self.color(tool_use_id)}{marker}{RESET}"


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
