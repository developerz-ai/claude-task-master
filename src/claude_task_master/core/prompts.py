"""Prompt Templates - Centralized, maintainable prompt generation.

This module provides structured prompt templates for different agent phases:
- Planning: Initial codebase analysis and task creation
- Working: Task execution with verification
- PR Review: Addressing code review feedback
- Verification: Confirming success criteria

All prompts are designed to be concise, structured, and token-efficient.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# =============================================================================
# Template Components
# =============================================================================


@dataclass
class PromptSection:
    """A section of a prompt with a title and content.

    Attributes:
        title: Section header (will be formatted as ## title).
        content: The content of the section.
        include_if: Optional condition - if False, section is omitted.
    """

    title: str
    content: str
    include_if: bool = True

    def render(self) -> str:
        """Render the section as markdown."""
        if not self.include_if:
            return ""
        return f"## {self.title}\n\n{self.content}"


@dataclass
class PromptBuilder:
    """Builds prompts from sections.

    Attributes:
        intro: Opening text before sections.
        sections: List of prompt sections.
    """

    intro: str = ""
    sections: list[PromptSection] = field(default_factory=list)

    def add_section(
        self,
        title: str,
        content: str,
        include_if: bool = True,
    ) -> PromptBuilder:
        """Add a section to the prompt.

        Args:
            title: Section header.
            content: Section content.
            include_if: Whether to include this section.

        Returns:
            Self for chaining.
        """
        self.sections.append(PromptSection(title, content, include_if))
        return self

    def build(self) -> str:
        """Build the final prompt string.

        Returns:
            Complete prompt as string.
        """
        parts = []
        if self.intro:
            parts.append(self.intro)

        for section in self.sections:
            rendered = section.render()
            if rendered:
                parts.append(rendered)

        return "\n\n".join(parts)


# =============================================================================
# Planning Prompt
# =============================================================================


def build_planning_prompt(goal: str, context: str | None = None) -> str:
    """Build the planning phase prompt.

    Args:
        goal: The user's goal to achieve.
        context: Optional accumulated context from previous sessions.

    Returns:
        Complete planning prompt.
    """
    builder = PromptBuilder(
        intro=f"""You are Claude Task Master in PLANNING MODE.

Your mission: **{goal}**

🎯 **Create a HIGH QUALITY MASTER PLAN with BIG PICTURE thinking.**

Think strategically about the entire goal. Consider architecture, dependencies,
testing strategy, and how all pieces fit together. Plan for success.

## FIRST: Read Project Instructions

**Always read `CLAUDE.md` first** (if it exists) - it contains project-specific
instructions, coding standards, and important context you must follow.

## TOOL RESTRICTIONS (MANDATORY)

**ALLOWED TOOLS (use ONLY these):**
- `Read` - Read files to understand the codebase (start with CLAUDE.md!)
- `Glob` - Find files by pattern
- `Grep` - Search for code patterns

**FORBIDDEN TOOLS (NEVER use during planning):**
- ❌ `Write` - Do NOT write any files
- ❌ `Edit` - Do NOT edit any files
- ❌ `Bash` - Do NOT run any commands
- ❌ `Task` - Do NOT launch any agents
- ❌ `TodoWrite` - Do NOT use todo tracking
- ❌ `WebFetch` - Do NOT fetch web pages
- ❌ `WebSearch` - Do NOT search the web

**WHY**: The orchestrator will save your plan to `plan.md` automatically.
You just need to OUTPUT the plan as TEXT in your response.

## PLANNING RULES

- Do NOT write code
- Do NOT create git branches
- Do NOT run tests
- Do NOT create files
- ONLY explore and OUTPUT your plan as text"""
    )

    # Context section if available
    if context:
        builder.add_section("Previous Context", context.strip())

    # Exploration phase - READ ONLY
    builder.add_section(
        "Step 1: Explore Codebase (READ ONLY)",
        """Thoroughly analyze the codebase using READ-ONLY operations:
1. **Read** key files (README, configs, main modules)
2. **Glob** to find patterns (`**/*.py`, `src/**/*.ts`)
3. **Grep** for specific code (class definitions, imports)
4. **Identify** tests, CI config, and coding standards

Understand the architecture before creating tasks.""",
    )

    # Task creation phase
    builder.add_section(
        "Step 2: Create Task List",
        """Create an atomic, testable task list using this format:

```markdown
- [ ] `[coding]` Add `calculate_total()` method to `src/cart/service.py:CartService`
- [ ] `[quick]` Fix typo in `src/config.py` line 42
- [ ] `[general]` Add tests for `CartService` in `tests/test_cart.py`
```

**IMPORTANT: Include file paths and symbols in EVERY task:**
- File paths: `src/module/file.py`, `tests/test_file.py`
- Symbols: `ClassName`, `method_name()`, `CONSTANT_NAME`
- Line refs when relevant: `file.py:123`

**Complexity tags (for model routing):**
- `[coding]` → Opus (smartest) - new features, complex logic
- `[quick]` → Haiku (fastest) - configs, small fixes
- `[general]` → Sonnet (balanced) - tests, docs, refactoring

**When uncertain, use `[coding]`.**

**Task principles:**
- Atomic: One PR-able unit of work per task
- Ordered: Dependencies first
- Grouped: Related tasks for same PR
- Specific: Include exact file paths and symbol names

**Include git branch creation as first task:**
```markdown
- [ ] `[quick]` Create feature branch: claudetm/feat/your-feature-name
```""",
    )

    # PR strategy
    builder.add_section(
        "PR Strategy",
        """Group related tasks into focused PRs:

```markdown
- [ ] `[quick]` Create feature branch
- [ ] `[coding]` Implement feature X core logic
- [ ] `[general]` Add tests for feature X
- [ ] `[quick]` Update docs
- [ ] `[general]` Create PR, wait for CI, merge
```""",
    )

    # Success criteria
    builder.add_section(
        "Step 3: Define Success Criteria",
        """Define 3-5 measurable criteria:

1. Tests pass (`pytest`, `npm test`)
2. Linting clean (`ruff`, `eslint`, `mypy`)
3. CI pipeline green
4. PRs merged
5. Specific functional requirement

**Be specific and verifiable.**""",
    )

    # STOP instruction - critical
    builder.add_section(
        "STOP - Planning Complete",
        """**After creating the task list and success criteria, STOP.**

**IMPORTANT: Do NOT use Write tool. Just OUTPUT your plan as text.**

The orchestrator will automatically:
1. Extract your plan from your response
2. Save it to `plan.md`
3. Save criteria to `criteria.txt`
4. Start a NEW session for each task

**Do NOT:**
- Write any files (orchestrator handles this)
- Start implementing tasks
- Run any bash commands
- Launch any Task agents

**Just OUTPUT your plan as text and end with:**
```
PLANNING COMPLETE
```""",
    )

    return builder.build()


# =============================================================================
# Work Session Prompt
# =============================================================================


def build_work_prompt(
    task_description: str,
    context: str | None = None,
    pr_comments: str | None = None,
    file_hints: list[str] | None = None,
    required_branch: str | None = None,
) -> str:
    """Build the work session prompt.

    Args:
        task_description: The current task to execute.
        context: Optional accumulated context.
        pr_comments: Optional PR review comments to address.
        file_hints: Optional list of relevant files to check.
        required_branch: Optional branch name the agent should be on.

    Returns:
        Complete work session prompt.
    """
    branch_info = ""
    if required_branch:
        branch_info = f"\n\n**Current Branch:** `{required_branch}`"
        if required_branch in ("main", "master"):
            branch_info += "\n⚠️ You are on main/master - create a feature branch before making changes!"

    builder = PromptBuilder(
        intro=f"""You are Claude Task Master executing a SINGLE task.

## Current Task

{task_description}{branch_info}

**Focus on THIS task only. Do not work ahead to other tasks.**

🎯 **Deliver HIGH QUALITY work. Read and respect `CLAUDE.md` project instructions.**

📋 **Full plan:** `.claude-task-master/plan.md` | **Progress:** `.claude-task-master/progress.md`"""
    )

    # Context section
    if context:
        builder.add_section("Context", context.strip())

    # File hints
    if file_hints:
        files_list = "\n".join(f"- `{f}`" for f in file_hints[:10])  # Limit to 10
        builder.add_section(
            "Relevant Files",
            f"Start by reading these files:\n\n{files_list}",
        )

    # PR comments to address
    if pr_comments:
        builder.add_section(
            "PR Review Feedback",
            f"""Address this review feedback:

{pr_comments}

**For each comment:**
1. Make the requested change, or
2. Explain why it's not needed
3. Run tests after changes
4. Commit referencing the feedback""",
        )

    # Execution guidelines
    builder.add_section(
        "Execution",
        """**1. Check git status first**
```bash
git status
```
- Know where you are before making changes
- If on main/master, create a feature branch first
- If already on a feature branch, continue working there

**2. Read CLAUDE.md** (if exists)
- Contains project-specific instructions and coding standards
- Follow these rules strictly

**3. Understand the task**
- Read files before modifying
- Check existing patterns
- Identify tests to run

**4. Make changes**
- Edit existing files, Write new files
- Follow project coding style from CLAUDE.md
- Stay focused on current task

**5. Verify work**
```bash
# Common verification commands
pytest                    # Python tests
npm test                  # JS tests
ruff check . && mypy .   # Python lint/types
eslint . && tsc          # JS lint/types
```

**6. Commit properly**
```bash
git add -A && git commit -m "$(cat <<'EOF'
type: Brief description (50 chars)

- What changed
- Why needed

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

**7. Push and Create PR** (if task requires it)
```bash
git push -u origin HEAD
gh pr create --title "type: description" --body "..." --label "claudetm"
```

**STOP AFTER PR CREATION - DO NOT:**
- ❌ Wait for CI (`sleep`, `watch`, polling)
- ❌ Check CI status (`gh pr checks`, `gh pr view`)
- ❌ Monitor PR status
- ❌ Merge the PR

**The orchestrator handles CI/reviews/merge automatically.**""",
    )

    # Completion summary
    builder.add_section(
        "On Completion - STOP",
        """**After completing THIS task, STOP.**

Report:
1. What was completed
2. Tests run and results
3. Files modified
4. Git status (commits, push)
5. Any blockers

End your response with:
```
TASK COMPLETE
```

**The orchestrator will start a NEW session for the next task.**""",
    )

    return builder.build()


# =============================================================================
# Verification Prompt
# =============================================================================


def build_verification_prompt(
    criteria: str,
    tasks_summary: str | None = None,
) -> str:
    """Build the verification phase prompt.

    Args:
        criteria: The success criteria to verify.
        tasks_summary: Optional summary of completed tasks.

    Returns:
        Complete verification prompt.
    """
    builder = PromptBuilder(
        intro="""You are Claude Task Master verifying that all work is complete.

Verify that all success criteria have been met."""
    )

    if tasks_summary:
        builder.add_section("Completed Tasks", tasks_summary)

    builder.add_section("Success Criteria", criteria)

    builder.add_section(
        "Verification Steps",
        """1. **Run tests** - Execute the project's test suite
2. **Check lint/types** - Run all static analysis
3. **Verify PRs** - Check CI status and merge state
4. **Functional check** - Verify specific requirements work

**Report format:**
- ✓ Criterion: PASSED (evidence)
- ✗ Criterion: FAILED (reason)

**CRITICAL**: Your response MUST start with one of these two lines:
- `VERIFICATION_RESULT: PASS` - if ALL criteria are met
- `VERIFICATION_RESULT: FAIL` - if ANY criterion is not met

Be strict - only say PASS if ALL criteria are truly met.""",
    )

    return builder.build()


# =============================================================================
# Task Completion Prompt
# =============================================================================


def build_task_completion_check_prompt(
    task_description: str,
    session_output: str,
) -> str:
    """Build prompt to check if a task was completed.

    Args:
        task_description: The task that was being worked on.
        session_output: The output from the work session.

    Returns:
        Prompt for completion checking.
    """
    return f"""Determine if this task was completed successfully.

## Task
{task_description}

## Session Output
{session_output}

## Determination
Answer with EXACTLY one of:
- "COMPLETED" - Task is fully done, no more work needed
- "IN_PROGRESS" - Partial progress, more work needed
- "BLOCKED" - Cannot proceed, needs intervention
- "FAILED" - Encountered error that stops work

Then briefly explain why (1-2 sentences)."""


# =============================================================================
# Context Extraction Prompt
# =============================================================================


def build_context_extraction_prompt(
    session_output: str,
    existing_context: str | None = None,
) -> str:
    """Build prompt to extract learnings for context accumulation.

    Args:
        session_output: The output from the work session.
        existing_context: Optional existing context to append to.

    Returns:
        Prompt for context extraction.
    """
    builder = PromptBuilder(
        intro="""Extract key learnings from this session to help future work."""
    )

    if existing_context:
        builder.add_section("Existing Context", existing_context)

    builder.add_section("Session Output", session_output[:5000])  # Limit length

    builder.add_section(
        "Extract",
        """Identify and summarize:
1. **Patterns** - Coding conventions, architecture patterns
2. **Decisions** - Why certain approaches were chosen
3. **Issues** - Problems encountered and solutions
4. **Feedback** - Review comments and how addressed

Keep it concise (under 500 words). Focus on what helps future tasks.""",
    )

    return builder.build()


# =============================================================================
# Error Recovery Prompt
# =============================================================================


def build_error_recovery_prompt(
    error_message: str,
    task_context: str | None = None,
    attempted_actions: list[str] | None = None,
) -> str:
    """Build prompt for recovering from an error.

    Args:
        error_message: The error that occurred.
        task_context: Optional context about what was being attempted.
        attempted_actions: Optional list of actions already tried.

    Returns:
        Prompt for error recovery.
    """
    builder = PromptBuilder(
        intro=f"""An error occurred that needs to be resolved.

## Error
```
{error_message}
```"""
    )

    if task_context:
        builder.add_section("Task Context", task_context)

    if attempted_actions:
        actions = "\n".join(f"- {a}" for a in attempted_actions)
        builder.add_section("Already Tried", actions)

    builder.add_section(
        "Recovery Steps",
        """1. Analyze the error - understand root cause
2. Identify fix - what change will resolve it
3. Implement fix - make minimal changes
4. Verify - run tests/commands to confirm
5. Resume - continue with original task

**If unrecoverable**: Explain why and what intervention is needed.""",
    )

    return builder.build()
