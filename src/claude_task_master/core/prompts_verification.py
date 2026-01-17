"""Verification and Utility Prompts for Claude Task Master.

This module contains prompts for:
- Verification phase (checking success criteria)
- Task completion checking
- Context extraction
- Error recovery
"""

from __future__ import annotations

from .prompts_base import PromptBuilder


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
