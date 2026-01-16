"""Logger - Single consolidated log file per run with compact output."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# Default max line length for truncation
DEFAULT_MAX_LINE_LENGTH = 200


class TaskLogger:
    """Manages logging for task execution with compact, truncated output."""

    def __init__(self, log_file: Path, max_line_length: int = DEFAULT_MAX_LINE_LENGTH):
        """Initialize logger.

        Args:
            log_file: Path to the log file.
            max_line_length: Maximum line length before truncation (default 200).
        """
        self.log_file = log_file
        self.max_line_length = max_line_length
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
        """Start logging a new session."""
        self.current_session = session_number
        self.session_start = datetime.now()
        self._write(f"=== SESSION {session_number} | {phase.upper()} | {self.session_start.strftime('%H:%M:%S')} ===")

    def log_prompt(self, prompt: str) -> None:
        """Log the prompt sent to Claude."""
        self._write("[PROMPT]")
        self._write(self._truncate(prompt))

    def log_response(self, response: str) -> None:
        """Log Claude's response."""
        self._write("[RESPONSE]")
        self._write(self._truncate(response))

    def log_tool_use(self, tool_name: str, parameters: dict[str, Any]) -> None:
        """Log tool usage compactly."""
        params_str = self._truncate(self._format_params(parameters))
        self._write(f"[TOOL] {tool_name}: {params_str}")

    def log_tool_result(self, tool_name: str, result: Any) -> None:
        """Log tool result compactly."""
        result_str = self._truncate(str(result))
        self._write(f"[RESULT] {tool_name}: {result_str}")

    def end_session(self, outcome: str) -> None:
        """End the current session."""
        if self.session_start:
            duration = datetime.now() - self.session_start
            self._write(f"=== END | {outcome} | {duration.total_seconds():.1f}s ===")
        self.current_session = None
        self.session_start = None

    def log_error(self, error: str) -> None:
        """Log an error."""
        self._write(f"[ERROR] {self._truncate(error)}")

    def _write(self, message: str) -> None:
        """Write message to log file."""
        with open(self.log_file, "a") as f:
            f.write(message + "\n")
