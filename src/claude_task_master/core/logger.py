"""Logger - Single consolidated log file per run with compact output."""

import json
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

# Default max line length for truncation
DEFAULT_MAX_LINE_LENGTH = 200


class LogLevel(Enum):
    """Logging verbosity levels.

    - QUIET: Only log errors and session markers
    - NORMAL: Default - log prompts, responses, and errors (skip tool details)
    - VERBOSE: Log everything including full tool uses and results
    """

    QUIET = "quiet"
    NORMAL = "normal"
    VERBOSE = "verbose"


class LogFormat(Enum):
    """Output format for log files.

    - TEXT: Human-readable text format (default)
    - JSON: Structured JSON format for machine processing
    """

    TEXT = "text"
    JSON = "json"


class TaskLogger:
    """Manages logging for task execution with compact, truncated output."""

    def __init__(
        self,
        log_file: Path,
        max_line_length: int = DEFAULT_MAX_LINE_LENGTH,
        level: LogLevel = LogLevel.NORMAL,
        log_format: LogFormat = LogFormat.TEXT,
    ):
        """Initialize logger.

        Args:
            log_file: Path to the log file.
            max_line_length: Maximum line length before truncation (default 200).
            level: Logging verbosity level (default NORMAL).
            log_format: Output format (default TEXT).
        """
        self.log_file = log_file
        self.max_line_length = max_line_length
        self.level = level
        self.log_format = log_format
        self.current_session: int | None = None
        self.session_start: datetime | None = None

    def _truncate(self, text: str) -> str:
        """Truncate text to max line length per line."""
        lines = text.split("\n")
        truncated_lines = []
        for line in lines:
            if len(line) > self.max_line_length:
                truncated_lines.append(line[: self.max_line_length - 3] + "...")
            else:
                truncated_lines.append(line)
        return "\n".join(truncated_lines)

    def _format_params(self, params: dict[str, Any]) -> str:
        """Format parameters compactly."""
        try:
            # Try to format as compact JSON
            return json.dumps(params, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            return str(params)

    def start_session(self, session_number: int, phase: str) -> None:
        """Start logging a new session.

        Session markers are always logged regardless of level.
        """
        self.current_session = session_number
        self.session_start = datetime.now()

        if self.log_format == LogFormat.JSON:
            self._log_json_entry(
                "session_start",
                session=session_number,
                phase=phase.upper(),
                timestamp=self.session_start.isoformat(),
            )
        else:
            self._write_raw(
                f"=== SESSION {session_number} | {phase.upper()} | {self.session_start.strftime('%H:%M:%S')} ==="
            )

    def log_prompt(self, prompt: str) -> None:
        """Log the prompt sent to Claude.

        Logged at NORMAL and VERBOSE levels (not QUIET).
        """
        if self.level == LogLevel.QUIET:
            return

        if self.log_format == LogFormat.JSON:
            self._log_json_entry("prompt", content=prompt)
        else:
            self._write_raw("[PROMPT]")
            self._write_raw(self._truncate(prompt))

    def log_response(self, response: str) -> None:
        """Log Claude's response.

        Logged at NORMAL and VERBOSE levels (not QUIET).
        """
        if self.level == LogLevel.QUIET:
            return

        if self.log_format == LogFormat.JSON:
            self._log_json_entry("response", content=response)
        else:
            self._write_raw("[RESPONSE]")
            self._write_raw(self._truncate(response))

    def log_tool_use(self, tool_name: str, parameters: dict[str, Any]) -> None:
        """Log tool usage compactly.

        Only logged at VERBOSE level.
        """
        if self.level != LogLevel.VERBOSE:
            return

        if self.log_format == LogFormat.JSON:
            self._log_json_entry("tool_use", tool=tool_name, parameters=parameters)
        else:
            params_str = self._truncate(self._format_params(parameters))
            self._write_raw(f"[TOOL] {tool_name}: {params_str}")

    def log_tool_result(self, tool_name: str, result: Any) -> None:
        """Log tool result compactly.

        Only logged at VERBOSE level.
        """
        if self.level != LogLevel.VERBOSE:
            return

        if self.log_format == LogFormat.JSON:
            self._log_json_entry("tool_result", tool=tool_name, result=str(result))
        else:
            result_str = self._truncate(str(result))
            self._write_raw(f"[RESULT] {tool_name}: {result_str}")

    def end_session(self, outcome: str) -> None:
        """End the current session.

        Session markers are always logged regardless of level.
        """
        duration_seconds: float | None = None
        if self.session_start:
            duration = datetime.now() - self.session_start
            duration_seconds = duration.total_seconds()

        if self.log_format == LogFormat.JSON:
            self._log_json_entry(
                "session_end",
                outcome=outcome,
                duration_seconds=duration_seconds,
            )
            # Flush JSON entries to file
            self._flush_json()
        else:
            if duration_seconds is not None:
                self._write_raw(f"=== END | {outcome} | {duration_seconds:.1f}s ===")

        self.current_session = None
        self.session_start = None

    def log_error(self, error: str) -> None:
        """Log an error.

        Errors are always logged regardless of level.
        """
        if self.log_format == LogFormat.JSON:
            self._log_json_entry("error", message=error)
        else:
            self._write_raw(f"[ERROR] {self._truncate(error)}")

    def log_task_timing(self, task_index: int, duration_seconds: float) -> None:
        """Log task completion timing.

        Task timing is always logged regardless of level.
        """
        if self.log_format == LogFormat.JSON:
            self._log_json_entry(
                "task_timing",
                task_index=task_index,
                duration_seconds=duration_seconds,
            )
        else:
            minutes = int(duration_seconds // 60)
            seconds = duration_seconds % 60
            if minutes > 0:
                time_str = f"{minutes}m {seconds:.1f}s"
            else:
                time_str = f"{seconds:.1f}s"
            self._write_raw(f"[TIMING] Task #{task_index + 1} completed in {time_str}")

    def log_pr_timing(
        self,
        pr_number: int,
        total_seconds: float,
        active_work_seconds: float,
        ci_wait_seconds: float | None = None,
    ) -> None:
        """Log PR merge timing with breakdown.

        PR timing is always logged regardless of level.
        """
        if ci_wait_seconds is None:
            ci_wait_seconds = total_seconds - active_work_seconds

        if self.log_format == LogFormat.JSON:
            self._log_json_entry(
                "pr_timing",
                pr_number=pr_number,
                total_seconds=total_seconds,
                active_work_seconds=active_work_seconds,
                ci_wait_seconds=ci_wait_seconds,
            )
        else:

            def format_duration(seconds: float) -> str:
                minutes = int(seconds // 60)
                secs = seconds % 60
                if minutes > 0:
                    return f"{minutes}m {secs:.1f}s"
                return f"{secs:.1f}s"

            self._write_raw(
                f"[TIMING] PR #{pr_number} merged - "
                f"Total: {format_duration(total_seconds)}, "
                f"Active work: {format_duration(active_work_seconds)}, "
                f"CI wait: {format_duration(ci_wait_seconds)}"
            )

    def _log_json_entry(self, entry_type: str, **kwargs: Any) -> None:
        """Append a single entry to the JSON Lines log file.

        The entry is serialized to one line and appended immediately (JSON Lines
        format). Writing on the fly — rather than buffering until ``end_session``
        — means a crash loses at most the final in-flight line and never rewrites
        or discards existing history. Append is O(1) per entry, avoiding the
        previous O(n²) whole-file read-modify-rewrite.

        Args:
            entry_type: The entry category (e.g. "prompt", "error", "session_end").
            **kwargs: Additional fields merged into the entry.
        """
        entry: dict[str, Any] = {
            "type": entry_type,
            "timestamp": datetime.now().isoformat(),
            "session": self.current_session,
        }
        entry.update(kwargs)
        line = json.dumps(entry, default=str)
        # If a prior crash left the final record unterminated (bytes written but
        # the trailing newline never reached disk), appending directly would fuse
        # this entry onto the fragment so the parser discards *both* lines. Heal
        # the boundary with a leading newline before writing the new record.
        separator = "\n" if self._jsonl_needs_record_separator() else ""
        with open(self.log_file, "a") as f:
            f.write(separator + line + "\n")

    def _jsonl_needs_record_separator(self) -> bool:
        """Whether the JSONL log ends mid-record (non-empty, no trailing newline).

        Returns:
            True if the log file exists, is non-empty, and its last byte is not a
            newline — meaning the previous record was torn and the next append
            must start on a fresh line. False for a missing, empty, or
            properly-terminated file.
        """
        try:
            if self.log_file.stat().st_size == 0:
                return False
            with open(self.log_file, "rb") as f:
                f.seek(-1, os.SEEK_END)
                return f.read(1) != b"\n"
        except OSError:
            return False

    def _flush_json(self) -> None:
        """No-op retained for backward compatibility.

        JSON entries are appended immediately by :meth:`_log_json_entry`, so
        there is nothing to flush. Kept so existing callers (``end_session``)
        keep working without change.
        """

    def _write_raw(self, message: str) -> None:
        """Write message to log file (text format only)."""
        with open(self.log_file, "a") as f:
            f.write(message + "\n")

    # Backwards compatibility alias
    def _write(self, message: str) -> None:
        """Write message to log file.

        Deprecated: Use _write_raw for text format or _log_json_entry for JSON.
        This method is kept for backwards compatibility.
        """
        if self.log_format == LogFormat.JSON:
            # For backwards compatibility, treat raw writes as generic entries
            self._log_json_entry("raw", content=message)
        else:
            self._write_raw(message)


def read_json_log(log_file: Path) -> list[dict[str, Any]]:
    """Read all entries from a JSON Lines (JSONL) log file.

    Each line is an independent JSON object. Blank lines and lines that fail to
    parse (for example a partially-written final line left by a crash) are
    skipped, so a single corrupt line never discards the surrounding history —
    the property the previous whole-file rewrite lacked.

    Args:
        log_file: Path to the JSONL log file.

    Returns:
        Parsed log entries in write order. Empty list if the file is absent.
    """
    if not log_file.exists():
        return []

    entries: list[dict[str, Any]] = []
    with open(log_file) as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                continue  # Skip a torn or corrupt line; keep the rest.
            if isinstance(parsed, dict):
                entries.append(parsed)
    return entries
