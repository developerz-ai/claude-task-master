"""Tests for TaskLogger workflow scenarios.

This module covers:
- Complete session workflows (planning, work, verification)
- Session with errors
- Multiple sequential sessions
"""

from pathlib import Path


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
