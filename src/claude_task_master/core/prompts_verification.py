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
        intro="""Verify all success criteria are met. Be concise — report results, not process."""
    )

    if tasks_summary:
        builder.add_section("Completed Tasks", tasks_summary)

    builder.add_section("Success Criteria", criteria)

    builder.add_section(
        "Verification",
        """Run tests, lint, type checks. Check PRs merged and CI green.

Report format:
- ✓ Criterion: evidence
- ✗ Criterion: reason

**First line of response MUST be:**
`VERIFICATION_RESULT: PASS` or `VERIFICATION_RESULT: FAIL`

Only PASS if ALL criteria met.""",
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
    return f"""Was this task completed?

## Task
{task_description}

## Session Output
{session_output}

Answer EXACTLY one of: COMPLETED, IN_PROGRESS, BLOCKED, FAILED
Then one sentence why."""


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
        intro="""Extract key learnings from this session. Be terse — bullet points only, under 300 words."""
    )

    if existing_context:
        builder.add_section("Existing Context", existing_context)

    builder.add_section("Session Output", session_output[:5000])  # Limit length

    builder.add_section(
        "Extract",
        """Bullet points only:
- **Patterns** found (conventions, architecture)
- **Decisions** made and why
- **Issues** hit and solutions
- **Feedback** received and response

Only include what helps future tasks. Skip obvious things.""",
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
        intro=f"""Error occurred. Fix it and resume.

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
        "Steps",
        """1. Root cause the error
2. Minimal fix
3. Verify (run tests)
4. Resume original task

If unrecoverable: explain what intervention is needed.""",
    )

    return builder.build()
