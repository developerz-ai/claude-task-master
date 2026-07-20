"""Async event-loop utilities for AgentPhaseExecutor.

Contains:

- :data:`_TRAILING_PLANNING_COMPLETE_RE` — regex for stripping the stop-marker
- :func:`_strip_planning_complete` — strips the trailing ``PLANNING COMPLETE`` marker
- :func:`_drive_coroutine_on_new_loop` — drives a coroutine on a fresh event loop
- :func:`run_async_with_cleanup` — public wrapper for sync callers

All helpers are re-exported from :mod:`agent_phases` to preserve existing
import paths.
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Coroutine
from typing import Any

from .shutdown import get_shutdown_manager

# Trailing ``PLANNING COMPLETE`` stop-marker (optionally wrapped in backticks or
# bold) that the planning prompt instructs the model to end with. It is a
# control token for the parser, not plan content — anchored to end-of-string so
# only a trailing occurrence is stripped and marker-free output is untouched.
_TRAILING_PLANNING_COMPLETE_RE = re.compile(
    r"\s*[`*_]*\s*PLANNING\s+COMPLETE\s*[`*_]*\s*$",
    re.IGNORECASE,
)


def _strip_planning_complete(text: str) -> str:
    """Strip a trailing ``PLANNING COMPLETE`` marker from planner output.

    The planning prompt tells the model to end with ``PLANNING COMPLETE`` as a
    stop signal. Persisted verbatim it pollutes plan.md / criteria.txt and is
    re-injected into every later prompt. This removes a trailing occurrence
    (optionally wrapped in backticks/bold) while leaving marker-free output
    unchanged byte-for-byte.

    Args:
        text: Raw planner output.

    Returns:
        ``text`` with a trailing ``PLANNING COMPLETE`` marker removed, or the
        original string when no marker is present.
    """
    stripped = _TRAILING_PLANNING_COMPLETE_RE.sub("", text)
    if stripped == text:
        return text
    cleaned = stripped.rstrip()
    # Marker-only (or whitespace+marker) input collapses to empty, not a lone
    # newline. Otherwise normalise to a single trailing newline.
    return f"{cleaned}\n" if cleaned else ""


# How often the shutdown watcher re-checks for a cancellation request while a
# coroutine is in flight. Small enough that Ctrl+C (or a durable cross-process
# stop) interrupts a long streaming turn within a fraction of a second; the
# wait is on a local Event so a normally-completing turn exits instantly (no
# lingering thread).
_SHUTDOWN_POLL_SEC = 0.25


def _drive_coroutine_on_new_loop[T](coro: Coroutine[Any, Any, T]) -> T:
    """Drive a coroutine to completion on a fresh event loop in this thread.

    Assumes the calling thread has no running event loop. Creates a dedicated
    loop, runs the coroutine, and always tears the loop down — resetting the
    thread's current loop to ``None`` so a closed loop is never left behind for
    a later ``asyncio.get_event_loop()`` to pick up.

    A background watcher observes the shutdown manager and cancels the in-flight
    task the moment a shutdown is requested. This is what makes Ctrl+C
    interruptible mid-query: the signal handler only sets an Event (it must not
    touch the async loop), and while the task is blocked on a long streaming
    read nothing else would notice for up to the SDK idle ceiling (~30 min).
    The watcher cancels from a separate thread via
    ``loop.call_soon_threadsafe`` (the async-signal-safe way to poke a loop) and
    the resulting ``CancelledError`` is surfaced as ``KeyboardInterrupt`` so the
    orchestrator's interrupt path pauses and exits with code 2 promptly.

    Args:
        coro: The coroutine to run.

    Returns:
        The result of the coroutine.

    Raises:
        KeyboardInterrupt: On a shutdown request that cancels the task, or a
            direct Ctrl+C, re-raised after cancelling pending tasks.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    main_task = loop.create_task(coro)

    manager = get_shutdown_manager()
    watcher_done = threading.Event()

    def _cancel_main_task() -> None:
        # Runs in the loop thread (scheduled via call_soon_threadsafe).
        if not main_task.done():
            main_task.cancel()

    def _watch_for_shutdown() -> None:
        # Wait on the local done-Event so the common (no-interrupt) path exits
        # the instant the task finishes — no lingering thread. The short poll
        # bounds how quickly an in-process signal or a durable cross-process
        # stop is noticed, both surfaced by manager.shutdown_requested.
        while not watcher_done.wait(timeout=_SHUTDOWN_POLL_SEC):
            if manager.shutdown_requested:
                loop.call_soon_threadsafe(_cancel_main_task)
                return

    watcher = threading.Thread(target=_watch_for_shutdown, name="shutdown-watcher", daemon=True)
    watcher.start()

    try:
        return loop.run_until_complete(main_task)
    except asyncio.CancelledError as e:
        # The watcher cancelled the task on a shutdown request. Surface it as
        # KeyboardInterrupt so the orchestrator's interrupt handling (exit 2)
        # fires, rather than letting CancelledError escape as an unexpected
        # error. Guarded on shutdown_requested so an unrelated cancellation
        # (none exists today) would still propagate faithfully.
        if manager.shutdown_requested:
            raise KeyboardInterrupt from e
        raise
    except KeyboardInterrupt:
        # Direct Ctrl+C when no shutdown handler is installed (once registered,
        # our handler suppresses the default KeyboardInterrupt).
        main_task.cancel()
        try:
            # Give tasks a chance to clean up
            loop.run_until_complete(main_task)
        except asyncio.CancelledError:
            pass

        # Cancel all remaining tasks
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()

        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

        # Re-raise to let caller handle it
        raise
    finally:
        # Stop the watcher before tearing the loop down so it can never call
        # call_soon_threadsafe on a closed loop.
        watcher_done.set()
        watcher.join(timeout=_SHUTDOWN_POLL_SEC + 1.0)
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        # Never leave a closed loop as the thread-current loop.
        asyncio.set_event_loop(None)


def run_async_with_cleanup[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine synchronously with proper event-loop cleanup.

    Safe to call from either a plain synchronous context or from a thread that
    already has a running event loop (e.g. an async REST handler or MCP tool).
    When a loop is already running in this thread, driving another loop here
    would raise ``RuntimeError: Cannot run the event loop while another loop is
    running``; instead the coroutine is run to completion on its own loop in a
    dedicated worker thread. Otherwise it runs directly on a fresh loop in the
    current thread, cancelling pending tasks on ``KeyboardInterrupt``.

    Args:
        coro: The coroutine to run.

    Returns:
        The result of the coroutine.

    Raises:
        KeyboardInterrupt: Re-raised after cleanup to allow proper handling.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No event loop running in this thread: drive one here directly.
        return _drive_coroutine_on_new_loop(coro)

    # A loop is already running in this thread. We cannot nest another loop on
    # it, so run the coroutine on its own loop inside a dedicated worker thread
    # and block until it finishes, surfacing its result or exception here.
    result: list[T] = []
    error: list[BaseException] = []

    def _worker() -> None:
        try:
            result.append(_drive_coroutine_on_new_loop(coro))
        except BaseException as exc:  # noqa: B036 - re-raised in the caller thread
            error.append(exc)

    thread = threading.Thread(target=_worker, name="run-async-with-cleanup", daemon=True)
    thread.start()
    thread.join()

    if error:
        raise error[0]
    return result[0]


__all__ = [
    "_TRAILING_PLANNING_COMPLETE_RE",
    "_strip_planning_complete",
    "_SHUTDOWN_POLL_SEC",
    "_drive_coroutine_on_new_loop",
    "run_async_with_cleanup",
]
