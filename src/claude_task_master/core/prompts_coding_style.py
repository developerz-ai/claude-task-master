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
        intro="""You are analyzing a codebase to extract its coding workflow and style guide.

Your mission: **Create a CONCISE coding guide (under 800 words).**

Focus on extracting:
1. **Development workflow** (TDD, test-first, iteration patterns)
2. **Code conventions** (naming, formatting, imports)
3. **Test patterns** (E2E, integration, API tests - locations, commands, examples)
4. **Project-specific requirements** (from CLAUDE.md)

⚠️ **CRITICAL: Test patterns are ESSENTIAL for debugging-qa tasks.**
These tasks need to know where tests live and what patterns to follow.

This guide will be injected into every coding task, so keep it SHORT and ACTIONABLE.

## TOOL RESTRICTIONS (MANDATORY)

**ALLOWED TOOLS (use ONLY these):**
- `Read` - Read files to understand patterns
- `Glob` - Find files by pattern
- `Grep` - Search for code patterns
- `Bash` - Run commands (check configs, linters, etc.)

**FORBIDDEN TOOLS (NEVER use):**
- `Write` - Do NOT write any files
- `Edit` - Do NOT edit any files
- `Task` - Do NOT launch any agents"""
    )

    builder.add_section(
        "Step 1: Read CLAUDE.md (PRIORITY)",
        """**Start by reading `CLAUDE.md` at the repository root.**

This file contains the project's coding requirements and workflow instructions.
Extract:
- Development workflow (TDD, test-driven, iteration patterns)
- Code quality requirements
- Testing approach (test first? mock patterns?)
- Any specific coding rules or constraints

Also check these if CLAUDE.md doesn't exist:
- `.claude/instructions.md`
- `CONTRIBUTING.md`
- `.cursorrules`, `.github/copilot-instructions.md`""",
    )

    builder.add_section(
        "Step 2: Find Test Patterns (CRITICAL for debugging-qa tasks)",
        """**Look for existing integration/E2E tests - this is ESSENTIAL.**

Use Glob to find test directories and patterns:
- E2E tests: `**/e2e/**/*.spec.ts`, `**/tests/e2e/**`, `playwright.config.ts`
- Integration tests: `**/integration/**`, `**/*.integration.test.ts`, `**/*.test.ts`
- API tests: `**/*.request.test.ts`, `**/api/tests/**`

For each test type found, note:
- **Location**: Where test files live (e.g., `admin/e2e/`, `backend/src/**/*.test.ts`)
- **Naming pattern**: How tests are named (e.g., `*.spec.ts`, `*.test.ts`)
- **Run command**: How to run tests (check `package.json` scripts, `pyproject.toml`)
- **Example file**: A good test file to follow as a pattern

If no integration tests exist yet, note that and recommend where they should go.""",
    )

    builder.add_section(
        "Step 3: Check Configs",
        """Quickly scan linter/formatter configs for conventions:

- Python: `pyproject.toml` [tool.ruff], `ruff.toml`
- JS/TS: `.eslintrc`, `.prettierrc`, `biome.json`
- General: `.editorconfig`

Note line length, quote style, import ordering rules.""",
    )

    builder.add_section(
        "Step 4: Generate Coding Guide",
        """Create a CONCISE guide with these sections (skip if not applicable):

```markdown
# Coding Style

## Workflow
- [TDD approach? Test-first? Iteration pattern?]
- [Required checks before commit: tests, lint, types?]

## Code Style
- [Naming: snake_case, camelCase, etc.]
- [Formatting: line length, quotes, indentation]
- [Imports: ordering, grouping]

## Types
- [Type annotations required? Strictness level?]

## Testing
- [Unit tests: location, naming pattern, run command]
- [Integration/E2E tests: location, naming, run command, example file to follow]
- [API tests: location, naming, run command]
- [Assertion style, mock patterns]

## Error Handling
- [Exception patterns, logging approach]

## Project-Specific
- [Any unique requirements from CLAUDE.md]
```

**Rules:**
- Each section: 2-4 bullet points MAX
- Be SPECIFIC and ACTIONABLE: "Run `pnpm test:e2e` before commit" not "Test your code"
- **Testing section is CRITICAL**: Include exact paths, file patterns, and commands
- Capture the WORKFLOW, not just style
- Include actual commands where relevant
- Total guide: under 800 words (expanded for test patterns)""",
    )

    builder.add_section(
        "Output Format",
        """Output ONLY the coding guide in markdown format.

Start with `# Coding Style` and include only relevant sections.

Do NOT include explanations or meta-commentary - just the guide itself.

End with:
```
CODING_STYLE_COMPLETE
```""",
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
