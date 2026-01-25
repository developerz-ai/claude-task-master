"""Tests for MCP coding style tools.

Tests delete_coding_style MCP tool implementation.
"""

import pytest

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestDeleteCodingStyleTool:
    """Test the delete_coding_style MCP tool."""

    def test_delete_coding_style_no_active_task(self, temp_dir):
        """Test delete_coding_style when no task exists."""
        from claude_task_master.mcp.tools import delete_coding_style

        result = delete_coding_style(temp_dir)
        assert result["success"] is False
        assert result["deleted"] is False
        assert "No active task found" in result["error"]
        assert "No task state found" in result["message"]

    def test_delete_coding_style_file_not_exists(self, initialized_state, state_dir):
        """Test delete_coding_style when coding-style.md doesn't exist."""
        from claude_task_master.mcp.tools import delete_coding_style

        result = delete_coding_style(state_dir.parent, str(state_dir))
        assert result["success"] is True
        assert result["deleted"] is False
        assert "did not exist" in result["message"]
        assert result["error"] is None

    def test_delete_coding_style_file_exists(self, initialized_state, state_dir):
        """Test delete_coding_style when coding-style.md exists."""
        from claude_task_master.mcp.tools import delete_coding_style

        # Create coding style file
        coding_style_file = state_dir / "coding-style.md"
        coding_style_file.write_text("# Coding Style\n\n- Use snake_case")

        assert coding_style_file.exists()

        result = delete_coding_style(state_dir.parent, str(state_dir))
        assert result["success"] is True
        assert result["deleted"] is True
        assert "deleted successfully" in result["message"]
        assert result["error"] is None
        assert not coding_style_file.exists()

    def test_delete_coding_style_with_state_manager_save(self, initialized_state, state_dir):
        """Test delete_coding_style with coding style saved via state manager."""
        from claude_task_master.mcp.tools import delete_coding_style

        state_manager, state = initialized_state

        # Save coding style using state manager method
        coding_style_content = """# Coding Style

## Workflow
- Run tests before committing
- Use ruff for formatting

## Code Style
- Max 100 chars per line
- Use double quotes
"""
        state_manager.save_coding_style(coding_style_content)

        # Verify file exists
        coding_style_file = state_dir / "coding-style.md"
        assert coding_style_file.exists()
        assert "Max 100 chars" in coding_style_file.read_text()

        # Delete it
        result = delete_coding_style(state_dir.parent, str(state_dir))
        assert result["success"] is True
        assert result["deleted"] is True
        assert "deleted successfully" in result["message"]

        # Verify file is gone
        assert not coding_style_file.exists()

    def test_delete_coding_style_twice(self, initialized_state, state_dir):
        """Test deleting coding style twice in a row."""
        from claude_task_master.mcp.tools import delete_coding_style

        # Create and delete first time
        coding_style_file = state_dir / "coding-style.md"
        coding_style_file.write_text("# Style Guide")

        result1 = delete_coding_style(state_dir.parent, str(state_dir))
        assert result1["success"] is True
        assert result1["deleted"] is True

        # Delete second time (file doesn't exist)
        result2 = delete_coding_style(state_dir.parent, str(state_dir))
        assert result2["success"] is True
        assert result2["deleted"] is False
        assert "did not exist" in result2["message"]
