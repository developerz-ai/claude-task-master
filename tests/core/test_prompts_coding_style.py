"""Tests for coding style prompt generation."""

from claude_task_master.core.prompts_coding_style import (
    build_coding_style_prompt,
    extract_coding_style,
)


class TestBuildCodingStylePrompt:
    """Tests for build_coding_style_prompt function."""

    def test_returns_non_empty_string(self) -> None:
        """Prompt should return a non-empty string."""
        prompt = build_coding_style_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_contains_mission_statement(self) -> None:
        """Prompt should explain the mission."""
        prompt = build_coding_style_prompt()
        assert "coding style" in prompt.lower() or "coding guide" in prompt.lower()
        assert "concise" in prompt.lower()

    def test_contains_tool_restrictions(self) -> None:
        """Prompt should specify tool restrictions."""
        prompt = build_coding_style_prompt()
        assert "Read" in prompt
        assert "Glob" in prompt
        assert "Grep" in prompt
        assert "Write" in prompt  # Should be forbidden
        assert "Edit" in prompt  # Should be forbidden

    def test_emphasizes_claude_md(self) -> None:
        """Prompt should emphasize reading CLAUDE.md first."""
        prompt = build_coding_style_prompt()
        assert "CLAUDE.md" in prompt

    def test_contains_workflow_guidance(self) -> None:
        """Prompt should mention extracting workflow/TDD patterns."""
        prompt = build_coding_style_prompt()
        prompt_lower = prompt.lower()
        assert "workflow" in prompt_lower or "tdd" in prompt_lower

    def test_specifies_output_format(self) -> None:
        """Prompt should specify output format."""
        prompt = build_coding_style_prompt()
        assert "CODING_STYLE_COMPLETE" in prompt

    def test_mentions_section_headers(self) -> None:
        """Prompt should mention expected section headers."""
        prompt = build_coding_style_prompt()
        # Check for common coding style sections
        assert "Naming" in prompt or "naming" in prompt
        assert "Formatting" in prompt or "formatting" in prompt


class TestExtractCodingStyle:
    """Tests for extract_coding_style function."""

    def test_extracts_content_with_header(self) -> None:
        """Should extract content that starts with Coding Style header."""
        result = """# Coding Style

## Naming
- Use snake_case for functions

CODING_STYLE_COMPLETE"""
        extracted = extract_coding_style(result)
        assert extracted.startswith("# Coding Style")
        assert "snake_case" in extracted
        assert "CODING_STYLE_COMPLETE" not in extracted

    def test_removes_completion_marker(self) -> None:
        """Should remove the CODING_STYLE_COMPLETE marker."""
        result = """# Coding Style

## Types
- Use type annotations

CODING_STYLE_COMPLETE"""
        extracted = extract_coding_style(result)
        assert "CODING_STYLE_COMPLETE" not in extracted

    def test_finds_header_in_middle_of_content(self) -> None:
        """Should find Coding Style header even if not at start."""
        result = """Some preamble text here.

# Coding Style

## Documentation
- Use docstrings

CODING_STYLE_COMPLETE"""
        extracted = extract_coding_style(result)
        assert extracted.startswith("# Coding Style")
        assert "docstrings" in extracted

    def test_wraps_content_without_header(self) -> None:
        """Should wrap content that lacks proper header."""
        result = """## Naming
- Use camelCase

CODING_STYLE_COMPLETE"""
        extracted = extract_coding_style(result)
        assert "# Coding Style" in extracted
        assert "camelCase" in extracted

    def test_handles_lowercase_header(self) -> None:
        """Should handle lowercase Coding Style header."""
        result = """# coding style

## Imports
- Sort alphabetically"""
        extracted = extract_coding_style(result)
        assert "Imports" in extracted

    def test_preserves_content_formatting(self) -> None:
        """Should preserve markdown formatting in content."""
        result = """# Coding Style

## Testing
- Use `pytest` for tests
- Run `ruff check .` before commit

CODING_STYLE_COMPLETE"""
        extracted = extract_coding_style(result)
        assert "`pytest`" in extracted
        assert "`ruff check .`" in extracted
