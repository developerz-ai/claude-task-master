"""Tests for the TaskLogger class."""

import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest


class TestTaskLoggerInit:
    """Tests for TaskLogger initialization."""

    def test_init_with_path(self, log_file: Path):
        """Test TaskLogger initialization with a log file path."""
        from claude_task_master.core.logger import TaskLogger

        logger = TaskLogger(log_file)

        assert logger.log_file == log_file
        assert logger.current_session is None
        assert logger.session_start is None

    def test_init_with_custom_max_line_length(self, log_file: Path):
        """Test TaskLogger initialization with custom max line length."""
        from claude_task_master.core.logger import TaskLogger

        logger = TaskLogger(log_file, max_line_length=100)

        assert logger.max_line_length == 100

    def test_init_creates_logger_without_file(self, temp_dir: Path):
        """Test that TaskLogger can be created even if file doesn't exist yet."""
        from claude_task_master.core.logger import TaskLogger

        non_existent_file = temp_dir / "non_existent" / "log.txt"
        logger = TaskLogger(non_existent_file)

        assert logger.log_file == non_existent_file


class TestSessionLogging:
    """Tests for session logging functionality."""

    def test_start_session(self, task_logger, log_file: Path):
        """Test starting a new logging session."""
        task_logger.start_session(session_number=1, phase="planning")

        assert task_logger.current_session == 1
        assert task_logger.session_start is not None
        assert isinstance(task_logger.session_start, datetime)

        # Verify log file contents (compact format)
        content = log_file.read_text()
        assert "SESSION 1" in content
        assert "PLANNING" in content
        assert "===" in content

    def test_start_session_work_phase(self, task_logger, log_file: Path):
        """Test starting a session with work phase."""
        task_logger.start_session(session_number=5, phase="work")

        content = log_file.read_text()
        assert "SESSION 5" in content
        assert "WORK" in content

    def test_start_session_verification_phase(self, task_logger, log_file: Path):
        """Test starting a session with verification phase."""
        task_logger.start_session(session_number=10, phase="verification")

        content = log_file.read_text()
        assert "SESSION 10" in content
        assert "VERIFICATION" in content

    def test_start_multiple_sessions(self, task_logger, log_file: Path):
        """Test starting multiple sessions updates state correctly."""
        task_logger.start_session(session_number=1, phase="planning")
        first_start = task_logger.session_start

        # Small delay to ensure different timestamp
        time.sleep(0.01)

        task_logger.start_session(session_number=2, phase="work")

        assert task_logger.current_session == 2
        assert task_logger.session_start != first_start

        content = log_file.read_text()
        assert "SESSION 1" in content
        assert "PLANNING" in content
        assert "SESSION 2" in content
        assert "WORK" in content

    def test_end_session(self, task_logger, log_file: Path):
        """Test ending a session."""
        task_logger.start_session(session_number=1, phase="planning")

        # Small delay to have measurable duration
        time.sleep(0.05)

        task_logger.end_session(outcome="success")

        assert task_logger.current_session is None
        assert task_logger.session_start is None

        content = log_file.read_text()
        assert "END" in content
        assert "success" in content
        assert "s" in content  # seconds indicator

    def test_end_session_with_failure_outcome(self, task_logger, log_file: Path):
        """Test ending a session with failure outcome."""
        task_logger.start_session(session_number=1, phase="work")
        task_logger.end_session(outcome="failed - max retries exceeded")

        content = log_file.read_text()
        assert "failed - max retries exceeded" in content

    def test_end_session_without_start(self, task_logger, log_file: Path):
        """Test ending a session without starting one first."""
        # Should not crash, just not write duration
        task_logger.end_session(outcome="orphan_end")

        assert task_logger.current_session is None
        assert task_logger.session_start is None


class TestPromptAndResponseLogging:
    """Tests for prompt and response logging."""

    def test_log_prompt(self, task_logger, log_file: Path):
        """Test logging a prompt."""
        prompt = "Please analyze this code and suggest improvements."
        task_logger.log_prompt(prompt)

        content = log_file.read_text()
        assert "[PROMPT]" in content
        assert prompt in content

    def test_log_prompt_multiline(self, task_logger, log_file: Path):
        """Test logging a multiline prompt."""
        prompt = """You are a helpful assistant.

Please complete the following tasks:
1. Read the file
2. Make changes
3. Write tests"""
        task_logger.log_prompt(prompt)

        content = log_file.read_text()
        assert "[PROMPT]" in content
        assert "You are a helpful assistant." in content
        assert "1. Read the file" in content
        assert "3. Write tests" in content

    def test_log_response(self, task_logger, log_file: Path):
        """Test logging a response."""
        response = "I have analyzed the code and found 3 issues."
        task_logger.log_response(response)

        content = log_file.read_text()
        assert "[RESPONSE]" in content
        assert response in content

    def test_log_response_multiline(self, task_logger, log_file: Path):
        """Test logging a multiline response."""
        response = """Here are my findings:

1. Missing error handling in function foo()
2. Unused import on line 5
3. Potential race condition in async handler"""
        task_logger.log_response(response)

        content = log_file.read_text()
        assert "[RESPONSE]" in content
        assert "Missing error handling" in content
        assert "Potential race condition" in content


class TestToolLogging:
    """Tests for tool use and result logging."""

    def test_log_tool_use(self, task_logger, log_file: Path):
        """Test logging tool use."""
        task_logger.log_tool_use(
            tool_name="Read",
            parameters={"file_path": "/path/to/file.py"},
        )

        content = log_file.read_text()
        assert "[TOOL] Read:" in content
        assert "file_path" in content
        assert "/path/to/file.py" in content

    def test_log_tool_use_complex_parameters(self, task_logger, log_file: Path):
        """Test logging tool use with complex parameters."""
        params = {
            "file_path": "/path/to/file.py",
            "offset": 100,
            "limit": 50,
            "options": {"encoding": "utf-8", "follow_symlinks": True},
        }
        task_logger.log_tool_use(tool_name="Read", parameters=params)

        content = log_file.read_text()
        assert "[TOOL] Read:" in content
        assert "offset" in content
        assert "100" in content
        assert "encoding" in content

    def test_log_tool_result(self, task_logger, log_file: Path):
        """Test logging tool result."""
        task_logger.log_tool_result(
            tool_name="Read",
            result="File contents here...",
        )

        content = log_file.read_text()
        assert "[RESULT] Read:" in content
        assert "File contents here..." in content

    def test_log_tool_result_dict(self, task_logger, log_file: Path):
        """Test logging tool result as dict."""
        result = {"success": True, "lines_read": 150, "file_size": 4096}
        task_logger.log_tool_result(tool_name="Read", result=result)

        content = log_file.read_text()
        assert "[RESULT] Read:" in content
        assert "success" in content
        assert "True" in content

    def test_log_tool_result_list(self, task_logger, log_file: Path):
        """Test logging tool result as list."""
        result = ["/path/to/file1.py", "/path/to/file2.py", "/path/to/file3.py"]
        task_logger.log_tool_result(tool_name="Glob", result=result)

        content = log_file.read_text()
        assert "[RESULT] Glob:" in content
        assert "file1.py" in content
        assert "file3.py" in content

    def test_log_multiple_tool_uses(self, task_logger, log_file: Path):
        """Test logging multiple tool uses in sequence."""
        task_logger.log_tool_use("Read", {"file_path": "/a.py"})
        task_logger.log_tool_result("Read", "content of a")

        task_logger.log_tool_use(
            "Edit", {"file_path": "/a.py", "old_string": "foo", "new_string": "bar"}
        )
        task_logger.log_tool_result("Edit", "Edit successful")

        content = log_file.read_text()
        assert "[TOOL] Read:" in content
        assert "[RESULT] Read:" in content
        assert "[TOOL] Edit:" in content
        assert "[RESULT] Edit:" in content
        assert "old_string" in content


class TestErrorLogging:
    """Tests for error logging."""

    def test_log_error(self, task_logger, log_file: Path):
        """Test logging an error."""
        error_msg = "Connection timeout after 30 seconds"
        task_logger.log_error(error_msg)

        content = log_file.read_text()
        assert "[ERROR]" in content
        assert error_msg in content

    def test_log_error_multiline(self, task_logger, log_file: Path):
        """Test logging a multiline error message."""
        error_msg = """FileNotFoundError: [Errno 2] No such file or directory: '/missing/file.py'

Traceback (most recent call last):
  File "main.py", line 42, in <module>
    open('/missing/file.py')"""
        task_logger.log_error(error_msg)

        content = log_file.read_text()
        assert "[ERROR]" in content
        assert "FileNotFoundError" in content

    def test_log_multiple_errors(self, task_logger, log_file: Path):
        """Test logging multiple errors."""
        task_logger.log_error("Error 1: First problem")
        task_logger.log_error("Error 2: Second problem")
        task_logger.log_error("Error 3: Third problem")

        content = log_file.read_text()
        assert content.count("[ERROR]") == 3
        assert "Error 1" in content
        assert "Error 2" in content
        assert "Error 3" in content


class TestTruncation:
    """Tests for line truncation."""

    def test_truncate_long_line(self, temp_dir: Path):
        """Test that long lines are truncated."""
        from claude_task_master.core.logger import TaskLogger

        log_file = temp_dir / "truncate_test.txt"
        logger = TaskLogger(log_file, max_line_length=50)

        long_line = "x" * 100
        result = logger._truncate(long_line)

        assert len(result) == 50
        assert result.endswith("...")

    def test_truncate_short_line_unchanged(self, temp_dir: Path):
        """Test that short lines are not truncated."""
        from claude_task_master.core.logger import TaskLogger

        log_file = temp_dir / "truncate_test.txt"
        logger = TaskLogger(log_file, max_line_length=50)

        short_line = "short"
        result = logger._truncate(short_line)

        assert result == short_line

    def test_truncate_multiline(self, temp_dir: Path):
        """Test that each line in multiline content is truncated."""
        from claude_task_master.core.logger import TaskLogger

        log_file = temp_dir / "truncate_test.txt"
        logger = TaskLogger(log_file, max_line_length=20)

        multiline = "short\n" + "x" * 50 + "\nshort again"
        result = logger._truncate(multiline)

        lines = result.split("\n")
        assert lines[0] == "short"
        assert len(lines[1]) == 20
        assert lines[1].endswith("...")
        assert lines[2] == "short again"


class TestInternalMethods:
    """Tests for internal helper methods."""

    def test_write_creates_file(self, temp_dir: Path):
        """Test that _write creates the file if it doesn't exist."""
        from claude_task_master.core.logger import TaskLogger

        log_file = temp_dir / "new_log.txt"
        logger = TaskLogger(log_file)

        logger._write("test message")

        assert log_file.exists()
        assert log_file.read_text() == "test message\n"

    def test_write_appends_to_file(self, task_logger, log_file: Path):
        """Test that _write appends to existing file."""
        task_logger._write("line 1")
        task_logger._write("line 2")
        task_logger._write("line 3")

        content = log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 3
        assert lines[0] == "line 1"
        assert lines[1] == "line 2"
        assert lines[2] == "line 3"

    def test_write_empty_string(self, task_logger, log_file: Path):
        """Test _write with empty string."""
        task_logger._write("")

        content = log_file.read_text()
        assert content == "\n"

    def test_format_params_json(self, task_logger):
        """Test that parameters are formatted as compact JSON."""
        params = {"key": "value", "num": 42}
        result = task_logger._format_params(params)

        assert '"key":"value"' in result
        assert '"num":42' in result


class TestFullSessionWorkflow:
    """Integration tests for complete logging workflows."""

    def test_complete_planning_session(self, task_logger, log_file: Path):
        """Test a complete planning session workflow."""
        # Start session
        task_logger.start_session(session_number=1, phase="planning")

        # Log prompt
        task_logger.log_prompt("Please analyze the codebase and create a plan.")

        # Log tool use
        task_logger.log_tool_use("Glob", {"pattern": "**/*.py"})
        task_logger.log_tool_result("Glob", ["main.py", "utils.py", "test_main.py"])

        task_logger.log_tool_use("Read", {"file_path": "/main.py"})
        task_logger.log_tool_result("Read", "def main():\n    pass")

        # Log response
        task_logger.log_response("I've analyzed the codebase. Here's my plan...")

        # End session
        task_logger.end_session(outcome="plan_created")

        # Verify complete log structure
        content = log_file.read_text()
        assert "SESSION 1" in content
        assert "PLANNING" in content
        assert "[PROMPT]" in content
        assert "[TOOL] Glob:" in content
        assert "[RESULT] Glob:" in content
        assert "[TOOL] Read:" in content
        assert "[RESULT] Read:" in content
        assert "[RESPONSE]" in content
        assert "plan_created" in content

    def test_session_with_error(self, task_logger, log_file: Path):
        """Test a session that encounters an error."""
        task_logger.start_session(session_number=3, phase="work")

        task_logger.log_prompt("Please modify the file.")

        task_logger.log_tool_use("Edit", {"file_path": "/missing.py"})
        task_logger.log_error("FileNotFoundError: File does not exist")

        task_logger.end_session(outcome="failed")

        content = log_file.read_text()
        assert "SESSION 3" in content
        assert "WORK" in content
        assert "[ERROR]" in content
        assert "FileNotFoundError" in content
        assert "failed" in content

    def test_multiple_sessions_in_sequence(self, task_logger, log_file: Path):
        """Test multiple sessions logged sequentially."""
        # Session 1: Planning
        task_logger.start_session(session_number=1, phase="planning")
        task_logger.log_prompt("Create a plan")
        task_logger.log_response("Here is the plan")
        task_logger.end_session(outcome="success")

        # Session 2: Work
        task_logger.start_session(session_number=2, phase="work")
        task_logger.log_prompt("Implement the plan")
        task_logger.log_tool_use("Write", {"file_path": "/new.py"})
        task_logger.log_tool_result("Write", "File written")
        task_logger.log_response("Implementation complete")
        task_logger.end_session(outcome="success")

        # Session 3: Verification
        task_logger.start_session(session_number=3, phase="verification")
        task_logger.log_prompt("Verify success criteria")
        task_logger.log_response("All criteria met")
        task_logger.end_session(outcome="verified")

        content = log_file.read_text()
        assert "SESSION 1" in content
        assert "PLANNING" in content
        assert "SESSION 2" in content
        assert "WORK" in content
        assert "SESSION 3" in content
        assert "VERIFICATION" in content


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_log_with_special_characters(self, task_logger, log_file: Path):
        """Test logging content with special characters."""
        special_content = "Special chars: \n\t\r\\ \"quotes\" 'apostrophe' `backtick`"
        task_logger.log_prompt(special_content)

        content = log_file.read_text()
        assert "quotes" in content
        assert "apostrophe" in content
        assert "backtick" in content

    def test_log_with_unicode(self, task_logger, log_file: Path):
        """Test logging content with unicode characters."""
        unicode_content = "Unicode: \u2713 \u2717 \u2022 \u2192 \u03b1 \u03b2 \u03b3"
        task_logger.log_prompt(unicode_content)

        content = log_file.read_text()
        assert "\u2713" in content  # checkmark
        assert "\u03b1" in content  # alpha

    def test_log_very_long_content(self, task_logger, log_file: Path):
        """Test logging very long content gets truncated."""
        long_content = "x" * 10000
        task_logger.log_prompt(long_content)

        content = log_file.read_text()
        # Content should be truncated but still logged
        assert "..." in content
        assert len(content) < 10000

    def test_log_empty_parameters(self, task_logger, log_file: Path):
        """Test logging tool use with empty parameters."""
        task_logger.log_tool_use("SomeCommand", {})

        content = log_file.read_text()
        assert "[TOOL] SomeCommand:" in content
        assert "{}" in content

    def test_log_none_result(self, task_logger, log_file: Path):
        """Test logging None as a tool result."""
        task_logger.log_tool_result("SomeCommand", None)

        content = log_file.read_text()
        assert "[RESULT] SomeCommand:" in content
        assert "None" in content

    def test_concurrent_sessions_state(self, temp_dir: Path):
        """Test that session state is properly maintained per logger instance."""
        from claude_task_master.core.logger import TaskLogger

        log1 = temp_dir / "log1.txt"
        log2 = temp_dir / "log2.txt"

        logger1 = TaskLogger(log1)
        logger2 = TaskLogger(log2)

        logger1.start_session(1, "planning")
        logger2.start_session(2, "work")

        # Each logger should have its own session
        assert logger1.current_session == 1
        assert logger2.current_session == 2

        logger1.end_session("done1")
        assert logger1.current_session is None
        assert logger2.current_session == 2  # logger2 unchanged

    def test_nested_dict_parameters(self, task_logger, log_file: Path):
        """Test logging deeply nested dict parameters."""
        params = {"level1": {"level2": {"level3": {"value": "deep_value"}}}}
        task_logger.log_tool_use("DeepTool", params)

        content = log_file.read_text()
        assert "deep_value" in content

    def test_list_parameters(self, task_logger, log_file: Path):
        """Test logging list in parameters."""
        params = {
            "files": ["/a.py", "/b.py", "/c.py"],
            "options": ["--verbose", "--debug"],
        }
        task_logger.log_tool_use("BatchTool", params)

        content = log_file.read_text()
        assert "/a.py" in content
        assert "--verbose" in content


class TestFileHandling:
    """Tests for file handling behavior."""

    def test_creates_parent_directory(self, temp_dir: Path):
        """Test that writing creates parent directories if needed."""
        from claude_task_master.core.logger import TaskLogger

        nested_path = temp_dir / "deep" / "nested" / "path" / "log.txt"
        nested_path.parent.mkdir(parents=True, exist_ok=True)

        logger = TaskLogger(nested_path)
        logger._write("test")

        assert nested_path.exists()

    def test_append_mode(self, task_logger, log_file: Path):
        """Test that logger always appends and never overwrites."""
        # Write some initial content
        task_logger._write("initial content")

        # Create a new logger instance pointing to the same file
        from claude_task_master.core.logger import TaskLogger

        new_logger = TaskLogger(log_file)
        new_logger._write("new content")

        content = log_file.read_text()
        assert "initial content" in content
        assert "new content" in content

    def test_handles_file_permission_error(self, temp_dir: Path, monkeypatch):
        """Test handling of permission errors gracefully."""
        from claude_task_master.core.logger import TaskLogger

        log_file = temp_dir / "readonly.txt"
        logger = TaskLogger(log_file)

        # Mock open to raise PermissionError
        def raise_permission_error(*args, **kwargs):
            raise PermissionError("Cannot write to file")

        with pytest.raises(PermissionError):
            with patch("builtins.open", side_effect=raise_permission_error):
                logger._write("test")


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
        import json

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
        import json

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
        import json

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
        import json

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
