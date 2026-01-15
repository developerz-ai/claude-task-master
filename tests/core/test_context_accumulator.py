"""Tests for context_accumulator.py - learning accumulation and session summaries."""

import pytest
from pathlib import Path

from claude_task_master.core.context_accumulator import ContextAccumulator
from claude_task_master.core.state import StateManager


class TestContextAccumulatorInit:
    """Tests for ContextAccumulator initialization."""

    def test_init_with_state_manager(self, state_manager):
        """Test ContextAccumulator initialization with StateManager."""
        accumulator = ContextAccumulator(state_manager)
        assert accumulator.state_manager is state_manager

    def test_init_stores_state_manager_reference(self, state_dir):
        """Test that StateManager is properly stored."""
        sm = StateManager(state_dir)
        accumulator = ContextAccumulator(sm)
        assert accumulator.state_manager is sm


class TestAddLearning:
    """Tests for add_learning method."""

    def test_add_learning_to_empty_context(self, context_accumulator):
        """Test adding a learning when no context exists."""
        context_accumulator.add_learning("Python uses indentation for blocks.")

        context = context_accumulator.state_manager.load_context()
        assert "# Accumulated Context" in context
        assert "## Learning" in context
        assert "Python uses indentation for blocks." in context

    def test_add_learning_to_existing_context(self, context_accumulator):
        """Test adding a learning when context already exists."""
        # First learning
        context_accumulator.add_learning("First learning point.")

        # Second learning
        context_accumulator.add_learning("Second learning point.")

        context = context_accumulator.state_manager.load_context()
        assert "First learning point." in context
        assert "## New Learning" in context
        assert "Second learning point." in context

    def test_add_multiple_learnings(self, context_accumulator):
        """Test adding multiple learnings in sequence."""
        learnings = [
            "Learning 1: Use fixtures for test setup.",
            "Learning 2: Mocking is useful for isolation.",
            "Learning 3: Parametrize tests for coverage.",
        ]

        for learning in learnings:
            context_accumulator.add_learning(learning)

        context = context_accumulator.state_manager.load_context()
        for learning in learnings:
            assert learning in context

    def test_add_empty_learning(self, context_accumulator):
        """Test adding an empty string as learning."""
        context_accumulator.add_learning("")

        context = context_accumulator.state_manager.load_context()
        # Should still create structure even with empty content
        assert "# Accumulated Context" in context

    def test_add_learning_with_special_characters(self, context_accumulator):
        """Test adding learning with markdown special characters."""
        special_learning = "Use `backticks` for code, **bold** for emphasis, and # for headers."
        context_accumulator.add_learning(special_learning)

        context = context_accumulator.state_manager.load_context()
        assert special_learning in context

    def test_add_learning_with_multiline_content(self, context_accumulator):
        """Test adding learning with multiple lines."""
        multiline_learning = """Key patterns identified:
1. Factory pattern for object creation
2. Strategy pattern for behavior variation
3. Observer pattern for event handling"""

        context_accumulator.add_learning(multiline_learning)

        context = context_accumulator.state_manager.load_context()
        assert "Key patterns identified:" in context
        assert "Factory pattern" in context
        assert "Observer pattern" in context

    def test_add_learning_preserves_existing_session_summaries(self, context_accumulator):
        """Test that adding learning doesn't overwrite session summaries."""
        # Add a session summary first
        context_accumulator.add_session_summary(1, "Completed initial setup.")

        # Then add a learning
        context_accumulator.add_learning("Found useful utility functions.")

        context = context_accumulator.state_manager.load_context()
        assert "Session 1" in context
        assert "Completed initial setup." in context
        assert "Found useful utility functions." in context


class TestAddSessionSummary:
    """Tests for add_session_summary method."""

    def test_add_session_summary_to_empty_context(self, context_accumulator):
        """Test adding a session summary when no context exists."""
        context_accumulator.add_session_summary(1, "Explored the codebase and identified key components.")

        context = context_accumulator.state_manager.load_context()
        assert "# Accumulated Context" in context
        assert "## Session 1" in context
        assert "Explored the codebase and identified key components." in context

    def test_add_session_summary_to_existing_context(self, context_accumulator):
        """Test adding a session summary when context already exists."""
        # First session
        context_accumulator.add_session_summary(1, "First session work.")

        # Second session
        context_accumulator.add_session_summary(2, "Second session work.")

        context = context_accumulator.state_manager.load_context()
        assert "## Session 1" in context
        assert "First session work." in context
        assert "## Session 2" in context
        assert "Second session work." in context

    def test_add_multiple_session_summaries(self, context_accumulator):
        """Test adding many session summaries."""
        summaries = [
            (1, "Initial exploration of the codebase."),
            (2, "Implemented feature A."),
            (3, "Added tests for feature A."),
            (4, "Fixed bug in feature A."),
            (5, "Final cleanup and documentation."),
        ]

        for session_num, summary in summaries:
            context_accumulator.add_session_summary(session_num, summary)

        context = context_accumulator.state_manager.load_context()
        for session_num, summary in summaries:
            assert f"## Session {session_num}" in context
            assert summary in context

    def test_add_session_summary_with_large_session_number(self, context_accumulator):
        """Test adding session summary with a large session number."""
        context_accumulator.add_session_summary(999, "Long-running task session.")

        context = context_accumulator.state_manager.load_context()
        assert "## Session 999" in context

    def test_add_session_summary_with_zero_session(self, context_accumulator):
        """Test adding session summary with session number 0."""
        context_accumulator.add_session_summary(0, "Pre-session work.")

        context = context_accumulator.state_manager.load_context()
        assert "## Session 0" in context

    def test_add_session_summary_with_detailed_content(self, context_accumulator):
        """Test adding session summary with detailed markdown content."""
        detailed_summary = """### Completed Tasks
- Implemented user authentication
- Added input validation
- Created database migrations

### Challenges Encountered
- OAuth integration was complex
- Needed to handle edge cases

### Next Steps
- Add rate limiting
- Improve error messages"""

        context_accumulator.add_session_summary(1, detailed_summary)

        context = context_accumulator.state_manager.load_context()
        assert "### Completed Tasks" in context
        assert "### Challenges Encountered" in context
        assert "### Next Steps" in context

    def test_add_session_summary_preserves_learnings(self, context_accumulator):
        """Test that adding session summary doesn't overwrite learnings."""
        # Add a learning first
        context_accumulator.add_learning("Important architectural decision made.")

        # Then add a session summary
        context_accumulator.add_session_summary(1, "Completed architecture review.")

        context = context_accumulator.state_manager.load_context()
        assert "Important architectural decision made." in context
        assert "Session 1" in context
        assert "Completed architecture review." in context


class TestGetContextForPrompt:
    """Tests for get_context_for_prompt method."""

    def test_get_context_when_no_context_exists(self, context_accumulator):
        """Test getting context when none exists returns empty string."""
        result = context_accumulator.get_context_for_prompt()
        assert result == ""

    def test_get_context_with_learning(self, context_accumulator):
        """Test getting context after adding a learning."""
        context_accumulator.add_learning("Test learning content.")

        result = context_accumulator.get_context_for_prompt()
        assert "# Previous Context" in result
        assert "Test learning content." in result

    def test_get_context_with_session_summary(self, context_accumulator):
        """Test getting context after adding a session summary."""
        context_accumulator.add_session_summary(1, "Session summary content.")

        result = context_accumulator.get_context_for_prompt()
        assert "# Previous Context" in result
        assert "Session 1" in result
        assert "Session summary content." in result

    def test_get_context_format(self, context_accumulator):
        """Test that context is properly formatted with header."""
        context_accumulator.add_learning("Some learning.")

        result = context_accumulator.get_context_for_prompt()
        # Should start with newlines for proper markdown separation
        assert result.startswith("\n\n# Previous Context")

    def test_get_context_includes_all_accumulated_content(self, context_accumulator):
        """Test that all accumulated content is included."""
        context_accumulator.add_session_summary(1, "First session.")
        context_accumulator.add_learning("Important learning.")
        context_accumulator.add_session_summary(2, "Second session.")

        result = context_accumulator.get_context_for_prompt()
        assert "Session 1" in result
        assert "First session." in result
        assert "Important learning." in result
        assert "Session 2" in result
        assert "Second session." in result

    def test_get_context_is_idempotent(self, context_accumulator):
        """Test that getting context multiple times returns same result."""
        context_accumulator.add_learning("Test content.")

        result1 = context_accumulator.get_context_for_prompt()
        result2 = context_accumulator.get_context_for_prompt()
        result3 = context_accumulator.get_context_for_prompt()

        assert result1 == result2 == result3


class TestContextPersistence:
    """Tests for context persistence across accumulator instances."""

    def test_context_persists_to_file(self, state_manager):
        """Test that context is saved to file."""
        accumulator = ContextAccumulator(state_manager)
        accumulator.add_learning("Persisted learning.")

        context_file = state_manager.state_dir / "context.md"
        assert context_file.exists()
        assert "Persisted learning." in context_file.read_text()

    def test_context_persists_across_accumulator_instances(self, state_manager):
        """Test that context persists when creating new accumulator."""
        # Create first accumulator and add content
        acc1 = ContextAccumulator(state_manager)
        acc1.add_learning("Learning from first instance.")

        # Create second accumulator and verify content persists
        acc2 = ContextAccumulator(state_manager)
        context = acc2.get_context_for_prompt()

        assert "Learning from first instance." in context

    def test_context_accumulates_across_instances(self, state_manager):
        """Test that new content accumulates with existing content."""
        # First instance adds content
        acc1 = ContextAccumulator(state_manager)
        acc1.add_learning("First instance learning.")

        # Second instance adds more content
        acc2 = ContextAccumulator(state_manager)
        acc2.add_learning("Second instance learning.")

        # Verify both are present
        context = acc2.get_context_for_prompt()
        assert "First instance learning." in context
        assert "Second instance learning." in context


class TestContextAccumulatorWithExistingContext:
    """Tests for behavior with pre-existing context."""

    def test_add_learning_with_existing_context_file(
        self, state_manager, sample_context_file
    ):
        """Test adding learning when context file already exists."""
        accumulator = ContextAccumulator(state_manager)
        accumulator.add_learning("New learning after existing context.")

        context = accumulator.get_context_for_prompt()
        # Should contain both existing and new content
        assert "Accumulated Context" in context
        assert "New learning after existing context." in context

    def test_add_session_summary_with_existing_context_file(
        self, state_manager, sample_context_file
    ):
        """Test adding session summary when context file already exists."""
        accumulator = ContextAccumulator(state_manager)
        accumulator.add_session_summary(3, "New session after existing context.")

        context = accumulator.get_context_for_prompt()
        # Should contain both existing and new content
        assert "Session 1" in context  # From sample_context
        assert "Session 3" in context  # New session


class TestContextAccumulatorEdgeCases:
    """Edge case tests for ContextAccumulator."""

    def test_add_learning_with_unicode_content(self, context_accumulator):
        """Test adding learning with unicode characters."""
        unicode_learning = "Learned about: \u2713 Success \u2717 Failure \u26a0 Warning"
        context_accumulator.add_learning(unicode_learning)

        context = context_accumulator.state_manager.load_context()
        assert unicode_learning in context

    def test_add_learning_with_very_long_content(self, context_accumulator):
        """Test adding very long learning content."""
        long_learning = "A" * 10000  # 10KB of content
        context_accumulator.add_learning(long_learning)

        context = context_accumulator.state_manager.load_context()
        assert long_learning in context

    def test_add_session_with_negative_number(self, context_accumulator):
        """Test adding session with negative session number."""
        context_accumulator.add_session_summary(-1, "Negative session test.")

        context = context_accumulator.state_manager.load_context()
        assert "## Session -1" in context
        assert "Negative session test." in context

    def test_context_with_only_whitespace(self, context_accumulator):
        """Test adding whitespace-only content."""
        context_accumulator.add_learning("   \n\t\n   ")

        # Should still create the structure
        context = context_accumulator.state_manager.load_context()
        assert "# Accumulated Context" in context

    def test_add_learning_with_markdown_code_blocks(self, context_accumulator):
        """Test adding learning with code blocks."""
        code_learning = """Found useful pattern:
```python
def helper():
    return "value"
```
Use this for utility functions."""

        context_accumulator.add_learning(code_learning)

        context = context_accumulator.state_manager.load_context()
        assert "```python" in context
        assert "def helper():" in context


class TestContextIntegration:
    """Integration tests for ContextAccumulator."""

    def test_full_workflow(self, context_accumulator):
        """Test a complete workflow of accumulating context."""
        # Session 1: Initial exploration
        context_accumulator.add_session_summary(
            1, "Explored codebase structure and identified main components."
        )
        context_accumulator.add_learning(
            "Project uses modular architecture with clear separation."
        )

        # Session 2: Implementation
        context_accumulator.add_session_summary(
            2, "Implemented core feature with tests."
        )
        context_accumulator.add_learning(
            "Found existing utilities that can be reused."
        )

        # Session 3: Refinement
        context_accumulator.add_session_summary(
            3, "Refactored and improved code quality."
        )

        # Get final context for prompt
        context = context_accumulator.get_context_for_prompt()

        # Verify structure
        assert "# Previous Context" in context
        assert "Session 1" in context
        assert "Session 2" in context
        assert "Session 3" in context
        assert "modular architecture" in context
        assert "existing utilities" in context

    def test_context_ordering(self, context_accumulator):
        """Test that context maintains chronological order."""
        context_accumulator.add_session_summary(1, "FIRST_SESSION")
        context_accumulator.add_learning("FIRST_LEARNING")
        context_accumulator.add_session_summary(2, "SECOND_SESSION")
        context_accumulator.add_learning("SECOND_LEARNING")

        context = context_accumulator.state_manager.load_context()

        # Verify order by position in string
        pos_session1 = context.index("FIRST_SESSION")
        pos_learning1 = context.index("FIRST_LEARNING")
        pos_session2 = context.index("SECOND_SESSION")
        pos_learning2 = context.index("SECOND_LEARNING")

        assert pos_session1 < pos_learning1 < pos_session2 < pos_learning2
