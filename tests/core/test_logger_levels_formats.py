"""Tests for TaskLogger log levels and formats.

This module covers:
- Log level configuration (QUIET, NORMAL, VERBOSE)
- Log format configuration (TEXT, JSON)
- Combinations of levels and formats
"""

import json
from pathlib import Path


class TestLogLevels:
    """Tests for configurable log levels."""

    def test_default_log_level_is_normal(self, log_file: Path):
        """Test that default log level is NORMAL."""
        from claude_task_master.core.logger import LogLevel, TaskLogger

        logger = TaskLogger(log_file)
        assert logger.level == LogLevel.NORMAL

    def test_quiet_level_skips_prompt_and_response(self, log_file: Path):
        """Test that QUIET level only logs errors and sessions."""
        from claude_task_master.core.logger import LogLevel, TaskLogger

        logger = TaskLogger(log_file, level=LogLevel.QUIET)

        logger.start_session(1, "work")
        logger.log_prompt("This should not be logged")
        logger.log_response("This should not be logged either")
        logger.log_error("This error should be logged")
        logger.end_session("done")

        content = log_file.read_text()
        assert "SESSION 1" in content
        assert "This error should be logged" in content
        assert "This should not be logged" not in content

    def test_normal_level_logs_prompt_response_but_not_tools(self, log_file: Path):
        """Test that NORMAL level logs prompts and responses but not tool details."""
        from claude_task_master.core.logger import LogLevel, TaskLogger

        logger = TaskLogger(log_file, level=LogLevel.NORMAL)

        logger.start_session(1, "work")
        logger.log_prompt("Test prompt")
        logger.log_tool_use("Read", {"file_path": "/test.py"})
        logger.log_tool_result("Read", "file contents")
        logger.log_response("Test response")
        logger.end_session("done")

        content = log_file.read_text()
        assert "Test prompt" in content
        assert "Test response" in content
        assert "[TOOL]" not in content
        assert "[RESULT]" not in content

    def test_verbose_level_logs_everything(self, log_file: Path):
        """Test that VERBOSE level logs all details including tools."""
        from claude_task_master.core.logger import LogLevel, TaskLogger

        logger = TaskLogger(log_file, level=LogLevel.VERBOSE)

        logger.start_session(1, "work")
        logger.log_prompt("Test prompt")
        logger.log_tool_use("Read", {"file_path": "/test.py"})
        logger.log_tool_result("Read", "file contents")
        logger.log_response("Test response")
        logger.end_session("done")

        content = log_file.read_text()
        assert "Test prompt" in content
        assert "Test response" in content
        assert "[TOOL] Read:" in content
        assert "[RESULT] Read:" in content
        assert "/test.py" in content

    def test_errors_always_logged_regardless_of_level(self, temp_dir: Path):
        """Test that errors are always logged at any level."""
        from claude_task_master.core.logger import LogLevel, TaskLogger

        for level in [LogLevel.QUIET, LogLevel.NORMAL, LogLevel.VERBOSE]:
            log_file = temp_dir / f"log_{level.value}.txt"
            logger = TaskLogger(log_file, level=level)

            logger.log_error("Critical error occurred")

            content = log_file.read_text()
            assert "Critical error occurred" in content


class TestLogFormats:
    """Tests for configurable log formats."""

    def test_default_log_format_is_text(self, log_file: Path):
        """Test that default log format is TEXT."""
        from claude_task_master.core.logger import LogFormat, TaskLogger

        logger = TaskLogger(log_file)
        assert logger.log_format == LogFormat.TEXT

    def test_text_format_output(self, log_file: Path):
        """Test that TEXT format produces human-readable output."""
        from claude_task_master.core.logger import LogFormat, LogLevel, TaskLogger

        logger = TaskLogger(log_file, log_format=LogFormat.TEXT, level=LogLevel.VERBOSE)

        logger.start_session(1, "planning")
        logger.log_prompt("Analyze the code")
        logger.log_tool_use("Glob", {"pattern": "*.py"})
        logger.log_tool_result("Glob", ["a.py", "b.py"])
        logger.log_response("Found 2 files")
        logger.end_session("success")

        content = log_file.read_text()

        # Verify text format markers
        assert "=== SESSION 1 | PLANNING" in content
        assert "[PROMPT]" in content
        assert "[TOOL] Glob:" in content
        assert "[RESULT] Glob:" in content
        assert "[RESPONSE]" in content
        assert "=== END | success" in content

    def test_json_format_output(self, log_file: Path):
        """Test that JSON format produces valid JSON."""
        from claude_task_master.core.logger import LogFormat, LogLevel, TaskLogger

        json_log_file = log_file.with_suffix(".json")
        logger = TaskLogger(json_log_file, log_format=LogFormat.JSON, level=LogLevel.VERBOSE)

        logger.start_session(1, "planning")
        logger.log_prompt("Analyze the code")
        logger.log_tool_use("Glob", {"pattern": "*.py"})
        logger.log_tool_result("Glob", ["a.py", "b.py"])
        logger.log_response("Found 2 files")
        logger.end_session("success")

        # Parse the JSON output
        content = json_log_file.read_text()
        entries = json.loads(content)

        assert isinstance(entries, list)
        assert (
            len(entries) == 6
        )  # session_start, prompt, tool_use, tool_result, response, session_end

        # Verify entry types
        types = [e["type"] for e in entries]
        assert "session_start" in types
        assert "prompt" in types
        assert "tool_use" in types
        assert "tool_result" in types
        assert "response" in types
        assert "session_end" in types

        # Verify session_start entry
        session_start = next(e for e in entries if e["type"] == "session_start")
        assert session_start["phase"] == "PLANNING"

        # Verify tool_use entry has parameters
        tool_use = next(e for e in entries if e["type"] == "tool_use")
        assert tool_use["tool"] == "Glob"
        assert tool_use["parameters"] == {"pattern": "*.py"}

    def test_json_format_appends_to_existing(self, log_file: Path):
        """Test that JSON format correctly appends to existing entries."""
        from claude_task_master.core.logger import LogFormat, TaskLogger

        json_log_file = log_file.with_suffix(".json")
        logger = TaskLogger(json_log_file, log_format=LogFormat.JSON)

        # First session
        logger.start_session(1, "planning")
        logger.log_prompt("First prompt")
        logger.end_session("done")

        # Second session (new logger instance)
        logger2 = TaskLogger(json_log_file, log_format=LogFormat.JSON)
        logger2.start_session(2, "work")
        logger2.log_prompt("Second prompt")
        logger2.end_session("done")

        # Parse and verify all entries are present
        content = json_log_file.read_text()
        entries = json.loads(content)

        sessions = [e for e in entries if e["type"] == "session_start"]
        assert len(sessions) == 2
        assert sessions[0]["session"] == 1
        assert sessions[1]["session"] == 2

    def test_json_format_with_quiet_level(self, log_file: Path):
        """Test JSON format respects log level."""
        from claude_task_master.core.logger import LogFormat, LogLevel, TaskLogger

        json_log_file = log_file.with_suffix(".json")
        logger = TaskLogger(json_log_file, log_format=LogFormat.JSON, level=LogLevel.QUIET)

        logger.start_session(1, "work")
        logger.log_prompt("Should be skipped")
        logger.log_error("Should be logged")
        logger.end_session("done")

        content = json_log_file.read_text()
        entries = json.loads(content)

        types = [e["type"] for e in entries]
        assert "session_start" in types
        assert "session_end" in types
        assert "error" in types
        assert "prompt" not in types


class TestLogLevelAndFormatCombinations:
    """Tests for combinations of log levels and formats."""

    def test_verbose_json_full_output(self, log_file: Path):
        """Test verbose level with JSON format captures everything."""
        from claude_task_master.core.logger import LogFormat, LogLevel, TaskLogger

        json_log_file = log_file.with_suffix(".json")
        logger = TaskLogger(json_log_file, log_format=LogFormat.JSON, level=LogLevel.VERBOSE)

        logger.start_session(1, "work")
        logger.log_prompt("Prompt")
        logger.log_tool_use("Tool1", {"param": "value"})
        logger.log_tool_result("Tool1", "result")
        logger.log_response("Response")
        logger.log_error("Error")
        logger.end_session("done")

        content = json_log_file.read_text()
        entries = json.loads(content)

        types = [e["type"] for e in entries]
        assert len(types) == 7
        assert "prompt" in types
        assert "tool_use" in types
        assert "tool_result" in types
        assert "response" in types
        assert "error" in types

    def test_quiet_text_minimal_output(self, log_file: Path):
        """Test quiet level with text format produces minimal output."""
        from claude_task_master.core.logger import LogFormat, LogLevel, TaskLogger

        logger = TaskLogger(log_file, log_format=LogFormat.TEXT, level=LogLevel.QUIET)

        logger.start_session(1, "work")
        logger.log_prompt("Prompt - should be skipped")
        logger.log_tool_use("Tool1", {"param": "value"})
        logger.log_tool_result("Tool1", "result")
        logger.log_response("Response - should be skipped")
        logger.log_error("Error - should appear")
        logger.end_session("done")

        content = log_file.read_text()

        assert "SESSION 1" in content
        assert "Error - should appear" in content
        assert "END | done" in content
        assert "Prompt - should be skipped" not in content
        assert "Response - should be skipped" not in content
        assert "[TOOL]" not in content
