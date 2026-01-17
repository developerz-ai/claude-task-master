"""Tests for StateManager context accumulation.

This module contains tests for context-related functionality including:
- Context save/load operations
- Context accumulation across sessions
- Context persistence with multiple state managers
- Edge cases for context handling
"""

from claude_task_master.core.state import (
    StateManager,
    TaskOptions,
)

# =============================================================================
# Context Save/Load Basic Tests
# =============================================================================


class TestContextSaveLoad:
    """Tests for basic context save/load operations."""

    def test_save_load_context(self, state_manager):
        """Test save and load context."""
        state_manager.state_dir.mkdir(exist_ok=True)

        context = """# Accumulated Context

## Session 1
Initial exploration done.

## Session 2
Implementation started.
"""
        state_manager.save_context(context)

        loaded_context = state_manager.load_context()
        assert loaded_context == context

    def test_load_context_no_file_returns_empty(self, state_manager):
        """Test load_context returns empty string when file doesn't exist."""
        state_manager.state_dir.mkdir(exist_ok=True)

        result = state_manager.load_context()
        assert result == ""

    def test_context_file_path(self, state_manager):
        """Test context is saved to correct file path."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_context("Test context")

        context_file = state_manager.state_dir / "context.md"
        assert context_file.exists()

    def test_context_overwrite(self, state_manager):
        """Test that saving context overwrites previous content."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_context("First context")
        state_manager.save_context("Second context")

        assert state_manager.load_context() == "Second context"


# =============================================================================
# Context Content Tests
# =============================================================================


class TestContextContent:
    """Tests for various types of context content."""

    def test_context_large_content(self, state_manager):
        """Test context with large content."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Create large context
        context = "# Context\n\n" + "\n".join([f"Line {i}" for i in range(1000)])
        state_manager.save_context(context)

        loaded_context = state_manager.load_context()
        assert loaded_context == context

    def test_context_with_markdown(self, state_manager):
        """Test context with markdown formatting."""
        state_manager.state_dir.mkdir(exist_ok=True)

        context = """# Accumulated Context

## Session 1: Exploration

### Findings
- **Important**: The codebase uses modular architecture
- *Note*: Tests are in `tests/` directory

### Code Example
```python
def example():
    return "Hello"
```

## Session 2: Implementation

| Component | Status |
|-----------|--------|
| Core      | Done   |
| Tests     | WIP    |
"""
        state_manager.save_context(context)

        loaded_context = state_manager.load_context()
        assert loaded_context == context
        assert "# Accumulated Context" in loaded_context
        assert "```python" in loaded_context
        assert "| Component | Status |" in loaded_context

    def test_context_with_unicode(self, state_manager):
        """Test context with unicode characters."""
        state_manager.state_dir.mkdir(exist_ok=True)

        context = "Context with emoji 🚀 and unicode: 日本語, checkmarks ✓✗✔"
        state_manager.save_context(context)

        loaded_context = state_manager.load_context()
        assert loaded_context == context

    def test_context_with_special_characters(self, state_manager):
        """Test context with special characters."""
        state_manager.state_dir.mkdir(exist_ok=True)

        context = "Content with \"quotes\", <tags>, & ampersands, and 'apostrophes'"
        state_manager.save_context(context)

        loaded_context = state_manager.load_context()
        assert loaded_context == context

    def test_context_whitespace_only(self, state_manager):
        """Test context with only whitespace."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_context("   \n\t\n   ")
        assert state_manager.load_context() == "   \n\t\n   "

    def test_context_empty_string(self, state_manager):
        """Test context with empty string."""
        state_manager.state_dir.mkdir(exist_ok=True)

        state_manager.save_context("")
        assert state_manager.load_context() == ""


# =============================================================================
# Context Accumulation Pattern Tests
# =============================================================================


class TestContextAccumulationPatterns:
    """Tests for context accumulation patterns across sessions."""

    def test_append_session_context(self, state_manager):
        """Test appending session context manually."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Session 1 context
        session1_context = "## Session 1\nExplored the codebase."
        state_manager.save_context(session1_context)

        # Session 2 appends
        existing = state_manager.load_context()
        session2_context = existing + "\n\n## Session 2\nImplemented feature A."
        state_manager.save_context(session2_context)

        loaded = state_manager.load_context()
        assert "## Session 1" in loaded
        assert "## Session 2" in loaded
        assert "Explored the codebase" in loaded
        assert "Implemented feature A" in loaded

    def test_multi_session_accumulation(self, state_manager):
        """Test accumulating context over multiple sessions."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Simulate multiple sessions
        sessions = [
            ("Session 1", "Initial exploration and setup"),
            ("Session 2", "Core implementation completed"),
            ("Session 3", "Added unit tests"),
            ("Session 4", "Fixed bugs and refactored"),
            ("Session 5", "Documentation and cleanup"),
        ]

        accumulated = "# Accumulated Context\n"
        for session_name, summary in sessions:
            accumulated += f"\n## {session_name}\n{summary}\n"
            state_manager.save_context(accumulated)

        final_context = state_manager.load_context()
        for session_name, summary in sessions:
            assert session_name in final_context
            assert summary in final_context

    def test_context_preserves_order(self, state_manager):
        """Test that context preserves chronological order."""
        state_manager.state_dir.mkdir(exist_ok=True)

        context = """# Context
FIRST_ITEM
SECOND_ITEM
THIRD_ITEM
"""
        state_manager.save_context(context)

        loaded = state_manager.load_context()
        pos_first = loaded.index("FIRST_ITEM")
        pos_second = loaded.index("SECOND_ITEM")
        pos_third = loaded.index("THIRD_ITEM")

        assert pos_first < pos_second < pos_third


# =============================================================================
# Context Persistence Tests
# =============================================================================


class TestContextPersistence:
    """Tests for context persistence across manager instances."""

    def test_context_persists_across_manager_instances(self, temp_dir):
        """Test that context persists when creating new StateManager."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)

        # First manager writes context
        manager1 = StateManager(state_dir)
        manager1.save_context("Context from first manager instance")

        # New manager reads same context
        manager2 = StateManager(state_dir)
        loaded = manager2.load_context()

        assert loaded == "Context from first manager instance"

    def test_context_accumulates_across_manager_instances(self, temp_dir):
        """Test context accumulates across manager instances."""
        state_dir = temp_dir / ".claude-task-master"
        state_dir.mkdir(parents=True)

        # First manager
        manager1 = StateManager(state_dir)
        manager1.save_context("First instance content")

        # Second manager reads and appends
        manager2 = StateManager(state_dir)
        existing = manager2.load_context()
        manager2.save_context(existing + "\nSecond instance content")

        # Third manager reads accumulated
        manager3 = StateManager(state_dir)
        final = manager3.load_context()

        assert "First instance content" in final
        assert "Second instance content" in final


# =============================================================================
# Context with Full Workflow Tests
# =============================================================================


class TestContextInWorkflow:
    """Tests for context in full workflow scenarios."""

    def test_context_saved_during_work_session(self, temp_dir):
        """Test context can be saved during work session."""
        state_dir = temp_dir / ".claude-task-master"
        manager = StateManager(state_dir)

        # Initialize state
        options = TaskOptions(auto_merge=True, max_sessions=5)
        manager.initialize(goal="Complete task", model="sonnet", options=options)

        # Simulate work session saving context
        manager.save_context("Session 1: Explored codebase structure")

        # Verify context persists
        assert manager.load_context() == "Session 1: Explored codebase structure"

    def test_context_survives_state_updates(self, initialized_state_manager):
        """Test context survives state updates."""
        # Save context
        initialized_state_manager.save_context("Important context information")

        # Update state
        state = initialized_state_manager.load_state()
        state.status = "working"
        initialized_state_manager.save_state(state)

        state.session_count = 5
        initialized_state_manager.save_state(state)

        # Context should still be there
        assert initialized_state_manager.load_context() == "Important context information"

    def test_context_with_progress_and_plan(self, initialized_state_manager):
        """Test context coexists with progress and plan files."""
        # Save all types of content
        initialized_state_manager.save_plan("## Tasks\n- [ ] Task 1")
        initialized_state_manager.save_progress("Task 1 in progress")
        initialized_state_manager.save_context("Learned about architecture")

        # All should be independently loadable
        assert "Tasks" in initialized_state_manager.load_plan()
        assert "Task 1 in progress" == initialized_state_manager.load_progress()
        assert "Learned about architecture" == initialized_state_manager.load_context()


# =============================================================================
# Context Cleanup Tests
# =============================================================================


class TestContextCleanup:
    """Tests for context file cleanup behavior."""

    def test_context_removed_on_cleanup(self, initialized_state_manager):
        """Test context file is removed during cleanup on success."""
        # Save context
        initialized_state_manager.save_context("Session context")

        context_file = initialized_state_manager.state_dir / "context.md"
        assert context_file.exists()

        # Cleanup
        run_id = initialized_state_manager.load_state().run_id
        initialized_state_manager.cleanup_on_success(run_id)

        # Context file should be gone
        assert not context_file.exists()

    def test_context_remains_after_partial_cleanup(self, state_manager):
        """Test context remains when only specific files are removed."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Save context
        state_manager.save_context("Important learning")

        context_file = state_manager.state_dir / "context.md"
        assert context_file.exists()

        # Remove a different file (simulating partial operation)
        other_file = state_manager.state_dir / "other.txt"
        other_file.write_text("other content")
        other_file.unlink()

        # Context should remain
        assert context_file.exists()
        assert state_manager.load_context() == "Important learning"


# =============================================================================
# Context Edge Cases Tests
# =============================================================================


class TestContextEdgeCases:
    """Edge case tests for context handling."""

    def test_context_very_long_lines(self, state_manager):
        """Test context with very long lines."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Single line with 10000 characters
        long_line = "X" * 10000
        state_manager.save_context(long_line)

        assert state_manager.load_context() == long_line

    def test_context_many_newlines(self, state_manager):
        """Test context with many consecutive newlines."""
        state_manager.state_dir.mkdir(exist_ok=True)

        context = "Start\n\n\n\n\n\n\n\n\n\nEnd"
        state_manager.save_context(context)

        assert state_manager.load_context() == context

    def test_context_with_null_bytes(self, state_manager):
        """Test context handles content without null bytes gracefully."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Normal text content (null bytes would cause issues in text mode)
        context = "Normal context content"
        state_manager.save_context(context)

        assert state_manager.load_context() == context

    def test_context_mixed_line_endings(self, state_manager):
        """Test context with mixed line endings."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Mix of Unix (\n), Windows (\r\n), and old Mac (\r) line endings
        context = "Line 1\nLine 2\r\nLine 3\rLine 4"
        state_manager.save_context(context)

        # Python text mode may normalize, but content should be readable
        loaded = state_manager.load_context()
        assert "Line 1" in loaded
        assert "Line 2" in loaded
        assert "Line 3" in loaded
        assert "Line 4" in loaded

    def test_context_repeated_saves(self, state_manager):
        """Test context with many repeated saves."""
        state_manager.state_dir.mkdir(exist_ok=True)

        for i in range(100):
            state_manager.save_context(f"Version {i}")

        assert state_manager.load_context() == "Version 99"

    def test_context_binary_like_content(self, state_manager):
        """Test context with binary-like but valid text content."""
        state_manager.state_dir.mkdir(exist_ok=True)

        # Content that looks like binary but is valid UTF-8
        context = "\\x00\\x01\\x02 - escaped binary representation"
        state_manager.save_context(context)

        assert state_manager.load_context() == context


# =============================================================================
# Context Path Tests
# =============================================================================


class TestContextPaths:
    """Tests for context with various path scenarios."""

    def test_context_with_path_containing_spaces(self, temp_dir):
        """Test context with state directory path containing spaces."""
        parent_dir = temp_dir / "path with spaces"
        parent_dir.mkdir(parents=True)

        state_dir = parent_dir / ".claude-task-master"
        state_dir.mkdir()

        manager = StateManager(state_dir)
        manager.save_context("Context in spaced path")

        assert manager.load_context() == "Context in spaced path"

    def test_context_with_unicode_path(self, temp_dir):
        """Test context with unicode characters in path."""
        parent_dir = temp_dir / "日本語_path"
        parent_dir.mkdir(parents=True)

        state_dir = parent_dir / ".claude-task-master"
        state_dir.mkdir()

        manager = StateManager(state_dir)
        manager.save_context("Context in unicode path")

        assert manager.load_context() == "Context in unicode path"

    def test_context_file_correct_name(self, state_manager):
        """Test context is saved to context.md specifically."""
        state_manager.state_dir.mkdir(exist_ok=True)
        state_manager.save_context("Test content")

        # Should be context.md, not context.txt or other name
        assert (state_manager.state_dir / "context.md").exists()
        assert not (state_manager.state_dir / "context.txt").exists()
