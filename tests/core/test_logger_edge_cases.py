"""Tests for TaskLogger edge cases and truncation.

This module covers:
- Line truncation behavior
- Edge cases and error handling
- Special characters and unicode
- Nested parameters
"""

from pathlib import Path


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
