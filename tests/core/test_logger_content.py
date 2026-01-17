"""Tests for TaskLogger content logging.

This module covers:
- Prompt and response logging
- Tool use and result logging
- Error logging
"""

from pathlib import Path


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
