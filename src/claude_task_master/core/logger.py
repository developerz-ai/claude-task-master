"""Logger - Single consolidated log file per run with compact output."""

import json
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
        self._json_entries: list[dict[str, Any]] = []  # Buffer for JSON format

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

    def _log_json_entry(self, entry_type: str, **kwargs: Any) -> None:
        """Add an entry to the JSON buffer."""
        entry: dict[str, Any] = {
            "type": entry_type,
            "timestamp": datetime.now().isoformat(),
            "session": self.current_session,
        }
        entry.update(kwargs)
        self._json_entries.append(entry)

    def _flush_json(self) -> None:
        """Flush JSON entries to file."""
        if not self._json_entries:
            return

        # Read existing entries if file exists
        existing: list[dict[str, Any]] = []
        if self.log_file.exists():
            try:
                with open(self.log_file) as f:
                    content = f.read().strip()
                    if content:
                        existing = json.loads(content)
            except (json.JSONDecodeError, OSError):
                pass  # Start fresh if file is corrupted

        # Combine and write all entries
        all_entries = existing + self._json_entries
        with open(self.log_file, "w") as f:
            json.dump(all_entries, f, indent=2, default=str)

        self._json_entries = []

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
