"""Plan Update Prompts for Claude Task Master.

This module contains prompts for updating an existing plan when
a change request is received (via `claudetm resume "message"` or mailbox).
"""

from __future__ import annotations

from .prompts_base import PromptBuilder


def build_plan_update_prompt(
    current_plan: str,
    change_request: str,
    goal: str | None = None,
    context: str | None = None,
) -> str:
    """Build the plan update prompt.

    Args:
        current_plan: The current plan markdown content.
        change_request: The change request/message from the user.
        goal: Optional original goal for context.
        context: Optional accumulated context from previous sessions.

    Returns:
        Complete plan update prompt.
    """
    builder = PromptBuilder(
        intro=f"""You are Claude Task Master in PLAN UPDATE MODE.

A change request has been received that may require updating the existing plan.

**Change Request:** {change_request}

Your mission: **Analyze the change request and update the plan accordingly.**

## TOOL RESTRICTIONS (MANDATORY)

**ALLOWED TOOLS (use ONLY these):**
- `Read` - Read files to understand the codebase
- `Glob` - Find files by pattern
- `Grep` - Search for code patterns
- `Bash` - Run commands (git status, tests, lint checks, etc.)

**FORBIDDEN TOOLS (NEVER use during plan update):**
- `Write` - Do NOT write any files
- `Edit` - Do NOT edit any files
- `Task` - Do NOT launch any agents
- `TodoWrite` - Do NOT use todo tracking
- `WebFetch` - Do NOT fetch web pages
- `WebSearch` - Do NOT search the web

**WHY**: The orchestrator will save your updated plan to `plan.md` automatically.
You just need to OUTPUT the updated plan as TEXT in your response."""
    )

    # Original goal if available
    if goal:
        builder.add_section("Original Goal", goal)

    # Current plan section
    builder.add_section(
        "Current Plan",
        f"""Here is the current plan that may need updating:

```markdown
{current_plan}
```

**IMPORTANT:** Tasks marked with `[x]` are already completed and should NOT be removed or unchecked.
""",
    )

    # Context section if available
    if context:
        builder.add_section("Previous Context", context.strip())

    # Instructions for updating
    builder.add_section(
        "Update Instructions",
        """Analyze the change request and determine what updates are needed:

1. **Understand the Change**: What is being requested? Is it:
   - Adding new tasks/features?
   - Modifying existing tasks?
   - Removing/deprioritizing tasks?
   - Changing the approach/architecture?
   - Fixing a bug or issue?

2. **Preserve Completed Work**:
   - Keep all `[x]` (completed) tasks as-is
   - Do NOT uncheck completed tasks
   - Do NOT remove completed tasks unless explicitly requested

3. **Update Uncompleted Tasks**:
   - Modify `[ ]` tasks if the approach needs to change
   - Add new `[ ]` tasks if new requirements are introduced
   - Remove or mark as obsolete tasks that are no longer needed

4. **Maintain PR Structure**:
   - Keep the PR grouping structure (### PR N: Title)
   - Add new PRs if needed for new features
   - Reorder tasks within PRs if dependencies change

5. **Use Proper Format**:
   - Keep complexity tags: `[coding]`, `[quick]`, `[general]`
   - Include file paths and symbols in task descriptions
   - Maintain the success criteria section""",
    )

    # Output format
    builder.add_section(
        "Output Format",
        """After analyzing the change request, OUTPUT the complete updated plan.

**CRITICAL:**
- Start your updated plan with `## Task List`
- Include ALL tasks (both completed and uncompleted)
- Keep the same markdown checkbox format
- End with `## Success Criteria` section
- Do NOT use Write tool - just OUTPUT the plan as text

**Example structure:**
```markdown
## Task List

### PR 1: Infrastructure
- [x] `[quick]` Setup project structure (COMPLETED - keep as-is)
- [ ] `[coding]` Add new feature from change request

### PR 2: New Requirements (from change request)
- [ ] `[coding]` Implement new requirement A
- [ ] `[general]` Add tests for new requirements

## Success Criteria
1. All tasks completed
2. Tests pass
3. ...
```

End your response with:
```
PLAN UPDATE COMPLETE
```""",
    )

    return builder.build()
