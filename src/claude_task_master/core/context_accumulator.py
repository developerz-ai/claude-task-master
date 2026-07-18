"""Context Accumulator - Builds up learnings across sessions."""

from __future__ import annotations

from .state import StateManager

# Maximum number of characters injected into a prompt from accumulated context.
# Context grows with every session; an unbounded injection eventually crowds out
# the plan, task instructions, and code that the agent actually needs to act on.
# ~32 k chars ≈ 8 k tokens at ~4 chars/token — large enough to hold dozens of
# session summaries while leaving ample headroom in the context window.
_MAX_CONTEXT_CHARS = 32_000


class ContextAccumulator:
    """Accumulates context and learnings across sessions."""

    def __init__(self, state_manager: StateManager):
        """Initialize context accumulator.

        Args:
            state_manager: The StateManager instance used to persist context.
        """
        self.state_manager = state_manager

    def add_learning(self, learning: str) -> None:
        """Add a new learning to the context.

        Args:
            learning: The learning text to add.
        """
        current_context = self.state_manager.load_context()

        if current_context:
            updated_context = f"{current_context}\n\n## New Learning\n\n{learning}"
        else:
            updated_context = f"# Accumulated Context\n\n## Learning\n\n{learning}"

        self.state_manager.save_context(updated_context)

    def add_session_summary(self, session_number: int, summary: str) -> None:
        """Add a session summary to the context.

        Args:
            session_number: The session number being summarised.
            summary: The summary text to add.
        """
        current_context = self.state_manager.load_context()

        session_entry = f"## Session {session_number}\n\n{summary}"

        if current_context:
            updated_context = f"{current_context}\n\n{session_entry}"
        else:
            updated_context = f"# Accumulated Context\n\n{session_entry}"

        self.state_manager.save_context(updated_context)

    def get_context_for_prompt(self, max_chars: int = _MAX_CONTEXT_CHARS) -> str:
        """Get formatted context for including in prompts.

        Returns the *most recent* portion of accumulated context so that the
        most relevant learnings are always present even when the file is very
        large.  Older entries are silently truncated from the front; a note is
        prepended so the agent knows the context was trimmed.

        Args:
            max_chars: Maximum number of characters to include from the raw
                context.  Defaults to :data:`_MAX_CONTEXT_CHARS`.

        Returns:
            A formatted string ready for prompt injection, or ``""`` when no
            context has been accumulated yet.
        """
        context = self.state_manager.load_context()

        if not context:
            return ""

        if len(context) > max_chars:
            # Keep the tail (most recent entries) and add a truncation note.
            truncated = context[-max_chars:]
            # Align to the next newline so we don't inject a partial line.
            newline_pos = truncated.find("\n")
            if newline_pos != -1:
                truncated = truncated[newline_pos + 1 :]
            context = (
                f"*[Earlier context truncated — showing last {max_chars:,} chars]*\n\n{truncated}"
            )

        return f"\n\n# Previous Context\n\n{context}"
