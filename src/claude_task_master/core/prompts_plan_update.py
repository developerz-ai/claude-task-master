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
        intro=f"""Plan update mode. Change request: **{change_request}**

All tools available for exploration. Do NOT write files — OUTPUT updated plan as text."""
    )

    if goal:
        builder.add_section("Original Goal", goal)

    builder.add_section(
        "Current Plan",
        f"""```markdown
{current_plan}
```

Tasks marked `[x]` are completed — do NOT remove or uncheck them.""",
    )

    if context:
        builder.add_section("Previous Context", context.strip())

    builder.add_section(
        "Rules",
        """- Preserve completed `[x]` tasks and PR structure
- Add/modify/remove only `[ ]` tasks as needed
- Keep complexity tags, file paths, and context sublists
- Start output with `## Task List`, end with `## Success Criteria`
- End response with: `PLAN UPDATE COMPLETE`""",
    )

    return builder.build()
