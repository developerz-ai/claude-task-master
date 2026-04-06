"""Planning Phase Prompts for Claude Task Master.

This module contains prompts for the planning phase where Claude
analyzes the codebase and creates a task list organized by PR.
"""

from __future__ import annotations

from .prompts_base import PromptBuilder


def build_planning_prompt(
    goal: str,
    context: str | None = None,
    coding_style: str | None = None,
    max_prs: int | None = None,
    release_guide: str | None = None,
) -> str:
    """Build the planning phase prompt.

    Args:
        goal: The user's goal to achieve.
        context: Optional accumulated context from previous sessions.
        coding_style: Optional coding style guide to inject.
        max_prs: Optional maximum number of PRs to create.
        release_guide: Optional release guide for post-merge verification.

    Returns:
        Complete planning prompt.
    """
    builder = PromptBuilder(
        intro=f"""You are Claude Task Master in PLANNING MODE.

Your mission: **{goal}**

Create master plan. big picture: architecture → dependencies → testing → integration.

All tools available. explore only — no code, no branches. OUTPUT plan as text (orchestrator saves it).

terse output. task descriptions = 1 line. sublists = file:line → what to change. no prose in tasks."""
    )

    # Context section if available
    if context:
        builder.add_section("Previous Context", context.strip())

    # Coding style section if available (generated from codebase analysis)
    if coding_style:
        builder.add_section(
            "Project Coding Style & Test Patterns",
            f"""The following guide was extracted from this codebase.
**Tasks you create MUST respect these conventions.**

⚠️ **CRITICAL for `[debugging-qa]` tasks:** The Testing section shows existing test patterns.
When creating debugging-qa tasks, reference these test locations and patterns so the worker
knows exactly where to write tests and what style to follow.

{coding_style.strip()}""",
        )

    # Exploration phase - READ ONLY
    builder.add_section(
        "Step 1: Explore Codebase",
        """Read `CLAUDE.md` first (coding requirements). Also check `.claude/instructions.md`, `CONTRIBUTING.md`, `.cursorrules`.

Then: Read key files, Glob for patterns, Grep for code, identify tests and CI config.
Include any coding requirements in task descriptions so workers follow project standards.""",
    )

    # Task creation phase - organized by PR
    builder.add_section(
        "Step 2: Create Task List (Organized by PR)",
        """Organize tasks into PRs. Tasks in same PR share a conversation (better context).

**Format:**
```markdown
### PR 1: Schema & Model Fixes

- [ ] `[coding]` Make `user_id` nullable in Shift model
  - `rails/db/migrate/` — new migration
  - `rails/app/models/shift.rb:15` — update `belongs_to :user`
  - `rails/spec/models/shift_spec.rb` — update specs
```

**Under each task:** add file paths, line numbers, and implementation hints (not subtasks).

**Complexity tags (model routing):**
- `[coding]` → Opus — new features, complex logic (default when uncertain)
- `[quick]` → Haiku — configs, small fixes
- `[general]` → Sonnet — tests, docs, refactoring
- `[debugging-qa]` → Sonnet 1M — debug + fix + write automated tests

**`[debugging-qa]` workflow:** Manual test → Fix bugs → Write integration tests → Verify.
Include: what to test, files to read, where to add tests (exact paths + run commands).

**PR grouping:** Dependencies first, related changes together, 3-6 tasks per PR.""",
    )

    # Release guide section - inject if available so planner adds per-PR release checks
    if release_guide and "no release verification available" not in release_guide.lower():
        builder.add_section(
            "Release Verification (Post-Merge Checks)",
            f"""The following release guide describes this project's deployment infrastructure.
After each PR is merged, the orchestrator runs release verification automatically.

**For each PR group, add a `**Release checks:**` section** listing what to verify after merge.
Only include checks that are possible given the accessible surface below.

Example:
```markdown
### PR 1: Add User Auth

- [ ] `[coding]` Implement JWT middleware
- [ ] `[coding]` Add login/register endpoints

**Release checks:**
- Verify: POST /api/auth/login returns 200
- Verify: GET /api/protected returns 401 without token
- DB: Migration adds users table
- Monitor: No new Sentry errors in auth module
```

If a PR has no meaningful release checks (e.g., pure refactor, test-only), skip the section.

{release_guide.strip()}""",
        )

    # PR strategy - minimal, main points only
    builder.add_section(
        "PR Strategy",
        """Each PR gets its own branch and CI check. Keep PRs small, focused, independently mergeable.""",
    )

    # PR limit constraint (if specified)
    if max_prs:
        builder.add_section(
            "PR Limit",
            f"""**Maximum {max_prs} PR(s). No exceptions.** Group everything to fit. Any plan exceeding this is invalid.""",
        )

    # Success criteria
    builder.add_section(
        "Step 3: Define Success Criteria",
        """Define 3-5 measurable criteria (tests pass, lint clean, CI green, PRs merged, specific requirements).""",
    )

    # STOP instruction
    builder.add_section(
        "STOP",
        """After task list and criteria, STOP. Do NOT write files or start implementing.
OUTPUT your plan as text. End with: `PLANNING COMPLETE`""",
    )

    return builder.build()
