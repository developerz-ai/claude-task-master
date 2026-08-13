"""Verification and Utility Prompts for Claude Task Master.

This module contains prompts for:
- Verification phase (checking success criteria)
- Task completion checking
- Context extraction
- Error recovery
"""

from __future__ import annotations

from .prompts_base import PromptBuilder

#: How much already-accumulated context the learnings extractor is shown. Enough
#: to recognise a repeat, far less than the full file — this prompt's output is
#: appended to that same file, so whatever it echoes here it pays for forever.
_EXTRACTION_CONTEXT_CHARS = 8_000

#: How much of the session's output the extractor reads (the tail — see below).
_EXTRACTION_OUTPUT_CHARS = 5_000


def build_verification_prompt(
    criteria: str,
    tasks_summary: str | None = None,
    context: str | None = None,
) -> str:
    """Build the verification phase prompt.

    Args:
        criteria: The success criteria to verify.
        tasks_summary: Optional summary of the tasks actually completed
            (checked-off plan tasks, merged PRs). Rendered under
            "Completed Tasks".
        context: Optional accumulated learnings from prior sessions. Rendered
            under its own "Previous Context" header — kept distinct from
            ``tasks_summary`` so accumulated context is never mislabelled as
            the list of completed tasks.

    Returns:
        Complete verification prompt.
    """
    builder = PromptBuilder(
        intro="""Verify all success criteria are met. Be concise — report results, not process."""
    )

    if tasks_summary:
        builder.add_section("Completed Tasks", tasks_summary)

    if context:
        builder.add_section("Previous Context", context)

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
        # Only the tail, and only enough of it to recognise a repeat. Handing
        # the model the whole accumulated file made it restate the backlog into
        # every new entry, which was then appended — so the file grew
        # superlinearly and each restatement was re-injected into every prompt
        # thereafter. One real file reached 157 KB with a single carried-forward
        # line present in 26 separate session entries.
        builder.add_section(
            "Already Captured (do NOT repeat any of this)",
            existing_context[-_EXTRACTION_CONTEXT_CHARS:],
        )

    # The TAIL of the session, not the head. This text is the whole accumulated
    # assistant output of the session, and the part worth learning from — what
    # changed, what broke, the completion report — is at the end. Slicing from
    # the front kept the opening exploration narration and discarded all of it.
    builder.add_section("Session Output", session_output[-_EXTRACTION_OUTPUT_CHARS:])

    builder.add_section(
        "Extract",
        """Bullet points only:
- **Patterns** found (conventions, architecture)
- **Decisions** made and why
- **Issues** hit and solutions
- **Feedback** received and response

Only include what helps future tasks. Skip obvious things, and skip anything already captured
above — a learning that is already in the accumulated context must NOT be restated.""",
    )

    return builder.build()
