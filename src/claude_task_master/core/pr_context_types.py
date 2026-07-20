"""Shared types, constants, and utilities for the PR context sub-modules.

Extracted here to avoid circular imports between pr_context.py,
pr_context_ci.py, and pr_context_resolve.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

# Prefix marking PR conversation (issue-level) comments. These live on the
# issues endpoint and are NOT resolvable review threads, so they are tracked
# by a synthetic ``issue_comment_<id>`` key in the addressed-threads set.
_CONVERSATION_THREAD_PREFIX = "issue_comment_"

# Max resolveReviewThread mutations aliased into a single GraphQL request.
MUTATION_BATCH_SIZE = 20


@dataclass(frozen=True)
class _ThreadState:
    """Snapshot of a review thread's resolution status and latest author.

    Attributes:
        is_resolved: Whether the thread is resolved on GitHub.
        last_comment_author: Login of the most recent comment's author, or
            None when it cannot be determined.
    """

    is_resolved: bool
    last_comment_author: str | None


def _conversation_thread_key(comment_id: object) -> str:
    """Build the synthetic addressed-set key for a conversation comment."""
    return f"{_CONVERSATION_THREAD_PREFIX}{comment_id}"


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    """Yield successive ``size``-length chunks from ``items``."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


__all__ = [
    "_CONVERSATION_THREAD_PREFIX",
    "MUTATION_BATCH_SIZE",
    "_ThreadState",
    "_conversation_thread_key",
    "_chunks",
]
