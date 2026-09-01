"""Roster wiring for :class:`~.agent_message.MessageProcessor`.

Separate from the message processor for two reasons. It is a second reason to
change that file (how a fanned-out team is *summarised*, as against how a single
message is rendered), and the rules below are the load-bearing part of the
feature — they are what the live SDK stream actually says, as opposed to what it
looks like it should say. Keeping them here keeps both files inside the 500-LOC
house limit with room for the explanation.

:class:`HiveRoster` itself is deliberately tolerant: it adopts an unfamiliar
tool-use id on sight, because a worker can speak before the block that spawned
it has been processed. That tolerance moves the burden here — feeding it the
wrong ids is what invents workers that never existed.
"""

from __future__ import annotations

from typing import Any

from .hive_roster import HiveRoster

__all__ = ["_MessageRosterMixin"]


class _MessageRosterMixin:
    """Feeds and renders the hive roster from the SDK message stream.

    Attribute stubs satisfy mypy; concrete values come from MessageProcessor.
    """

    _roster: HiveRoster
    _subagent_names: dict[str, str]

    def _render_roster(self, *, force: bool = False) -> None:
        """Print the roster — implemented by MessageProcessor."""
        raise NotImplementedError  # pragma: no cover

    def _roster_note_dispatch(self, tool_use_id: str, name: str, ordinal: int) -> None:
        """Put a freshly dispatched worker on the roster and show it at once.

        Args:
            tool_use_id: The spawning tool-use id, this worker's identity.
            name: The ``subagent_type`` dispatched.
            ordinal: The palette slot, so ``#n`` matches the streamed prefixes.
        """
        self._roster.spawn(tool_use_id, name, ordinal)
        self._render_roster(force=True)

    def _roster_note_dispatch_result(self, block: Any) -> None:
        """Close out a worker whose *dispatch itself* failed. Nothing else.

        A dispatch's tool result is an **acknowledgement, not a completion**.
        Measured against a live session: the ``ToolResultBlock`` for an ``Agent``
        call arrives 0.1s after the dispatch, while that worker's own messages
        keep arriving for the next 40 seconds. Reading it as "the worker
        returned" marked every worker done on arrival — a roster that jumped
        straight to ``3 done`` at ``0s`` elapsed while all three were still
        working.

        So only a *failed* dispatch finishes a worker: an error here means the
        spawn was refused (the CLI's "Concurrent subagent limit reached") or
        crashed, so that worker never ran — the one completion this stream
        states outright. A successful worker simply stays live. Nothing in the
        block stream marks when it stopped, and inventing that signal is what
        produced the wrong roster to begin with.

        Args:
            block: A top-level ``ToolResultBlock``.
        """
        if not getattr(block, "is_error", False):
            return
        tool_use_id = getattr(block, "tool_use_id", None)
        # A known dispatch id only: every ordinary Read/Bash/Grep result reaches
        # here too, and the roster would adopt each one as a worker.
        if not isinstance(tool_use_id, str) or tool_use_id not in self._subagent_names:
            return
        self._roster.finish(tool_use_id, is_error=True)
        self._render_roster(force=True)

    def _roster_note_worker_message(self, subagent_id: str, message: Any) -> None:
        """Attribute a worker's tokens to it, then refresh the view if due.

        ``AssistantMessage.usage`` on a message carrying ``parent_tool_use_id``
        is the only per-subagent figure the stream offers: the terminal
        ``ResultMessage`` aggregates the lead and every worker into a single
        total, which is precisely the number that cannot answer *which* worker
        spent it. The SDK does not document the per-message field's meaning, so
        this is best-effort by construction — the roster ignores anything
        malformed rather than reporting a figure it cannot stand up.

        Args:
            subagent_id: The message's ``parent_tool_use_id``.
            message: The message from that worker.
        """
        usage = getattr(message, "usage", None)
        if usage is not None:
            self._roster.add_usage(subagent_id, usage)
        self._render_roster()
