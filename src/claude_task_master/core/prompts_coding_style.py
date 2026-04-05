"""Coding Style Generation Prompt for Claude Task Master.

This module contains the prompt for generating a concise coding style guide
by analyzing CLAUDE.md and convention files. The generated guide captures:
- Coding workflow (TDD, development process)
- Code style conventions (naming, formatting)
- Project-specific requirements

The guide is saved to coding-style.md and injected into planning and work
prompts to save tokens while ensuring consistent code quality.
"""

from __future__ import annotations

from .prompts_base import PromptBuilder


def build_coding_style_prompt() -> str:
    """Build the prompt for generating a coding style guide.

    This prompt instructs Claude to analyze CLAUDE.md and convention files
    to create a concise coding style guide that captures the project's
    workflow (TDD, development process) and code conventions.

    Returns:
        Complete coding style generation prompt.
    """
    builder = PromptBuilder(
        intro="""Analyze codebase, create concise coding guide (under 600 words). This gets injected into every task, so keep it short and actionable.

All tools available for exploration. Do NOT write files — OUTPUT guide as text."""
    )

    builder.add_section(
        "What to Analyze",
        """1. Read `CLAUDE.md` (or `.claude/instructions.md`, `CONTRIBUTING.md`, `.cursorrules`) — extract workflow, requirements
2. Find test patterns: Glob for `**/e2e/**/*.spec.ts`, `**/*.test.ts`, etc. Note locations, naming, run commands, example files
3. Check configs: `pyproject.toml`, `.eslintrc`, `.prettierrc`, `biome.json` — line length, quotes, imports""",
    )

    builder.add_section(
        "Output Format",
        """Output markdown guide starting with `# Coding Style`. Sections (skip if N/A):
- **Workflow** — TDD? Required checks before commit?
- **Code Style** — Naming, formatting, imports (2-4 bullets)
- **Testing** — CRITICAL: exact paths, naming patterns, run commands, example files
- **Project-Specific** — unique requirements from CLAUDE.md

End with: `CODING_STYLE_COMPLETE`""",
    )

    return builder.build()


def extract_coding_style(result: str) -> str:
    """Extract the coding style guide from the generation result.

    Args:
        result: The raw output from the coding style generation.

    Returns:
        The extracted coding style guide content.
    """
    # Remove the completion marker if present
    content = result.replace("CODING_STYLE_COMPLETE", "").strip()

    # If it starts with markdown header, return as-is
    if content.startswith("# Coding Style") or content.startswith("# coding style"):
        return content

    # Try to find the coding style section
    if "# Coding Style" in content:
        idx = content.index("# Coding Style")
        return content[idx:].strip()

    # Fallback: wrap the content
    return f"# Coding Style\n\n{content}"
