"""Agent Phase Execution - Handles planning, work, and verification phases.

This module contains the phase execution logic extracted from AgentWrapper,
following the Single Responsibility Principle (SRP). It handles:
- Planning phase execution with Opus model
- Work session execution with dynamic model selection
- Success criteria verification with read/bash tools
"""

import asyncio
import threading
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, TypeVar

from . import console
from .agent_models import ModelType, get_tools_for_phase
from .prompts import (
    build_coding_style_prompt,
    build_context_extraction_prompt,
    build_planning_prompt,
    build_release_discovery_prompt,
    build_verification_prompt,
    build_work_prompt,
    extract_coding_style,
    extract_release_guide,
)
from .shutdown import get_shutdown_manager

if TYPE_CHECKING:
    from .agent_message import MessageProcessor
    from .agent_query import AgentQueryExecutor
    from .logger import TaskLogger

T = TypeVar("T")

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


class AgentPhaseExecutor:
    """Handles execution of different agent phases.

    This class is responsible for running planning, work, and verification
    phases with appropriate configurations and tool sets.
    """

    def __init__(
        self,
        query_executor: "AgentQueryExecutor",
        model: ModelType,
        logger: "TaskLogger | None" = None,
        get_model_name_func: Any = None,
        get_agents_func: Any = None,
        process_message_func: Any = None,
        message_processor: "MessageProcessor | None" = None,
    ):
        """Initialize the phase executor.

        Args:
            query_executor: The query executor to use for running queries.
            model: The default model to use for queries.
            logger: Optional TaskLogger for capturing tool usage.
            get_model_name_func: Function to convert ModelType to API model name.
            get_agents_func: Function to get subagents for working directory.
            process_message_func: Function to process messages from query stream.
            message_processor: The MessageProcessor whose ``process_message`` is
                passed as ``process_message_func``. Held so ``run_work_session``
                can derive session success from the captured terminal
                ResultMessage. Optional for backward compatibility.
        """
        self.query_executor = query_executor
        self.model = model
        self.logger = logger
        self.get_model_name_func = get_model_name_func
        self.get_agents_func = get_agents_func
        self.process_message_func = process_message_func
        self.message_processor = message_processor

    def run_planning_phase(
        self,
        goal: str,
        context: str = "",
        coding_style: str | None = None,
        max_prs: int | None = None,
        release_guide: str | None = None,
    ) -> dict[str, Any]:
        """Run planning phase with read-only tools.

        Always uses Opus (smartest model) for planning to ensure
        high-quality task breakdown and complexity classification.

        Args:
            goal: The goal to plan for.
            context: Additional context for planning.
            coding_style: Optional coding style guide to inject into prompt.
            max_prs: Optional maximum number of PRs to create.
            release_guide: Optional release guide for per-PR release checks.

        Returns:
            Dict with 'plan', 'criteria', and 'raw_output' keys.
        """
        # Build prompt for planning
        prompt = build_planning_prompt(
            goal=goal,
            context=context if context else None,
            coding_style=coding_style,
            max_prs=max_prs,
            release_guide=release_guide,
        )

        # Always use Opus for planning (smartest model)
        console.info("Planning with Opus (smartest model)...")

        # Run async query with Opus override
        result = run_async_with_cleanup(
            self.query_executor.run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("planning"),
                model_override=ModelType.OPUS,  # Always use Opus for planning
                get_model_name_func=self.get_model_name_func,
                get_agents_func=self.get_agents_func,
                process_message_func=self.process_message_func,
            )
        )

        # Parse result to extract plan and criteria
        return {
            "plan": self._extract_plan(result),
            "criteria": self._extract_criteria(result),
            "raw_output": result,
        }

    def run_work_session(
        self,
        task_description: str,
        context: str = "",
        pr_comments: str | None = None,
        model_override: ModelType | None = None,
        required_branch: str | None = None,
        create_pr: bool = True,
        push_only: bool = False,
        pr_group_info: dict | None = None,
        target_branch: str = "main",
        coding_style: str | None = None,
    ) -> dict[str, Any]:
        """Run a work session with full tools.

        Args:
            task_description: Description of the task to complete.
            context: Additional context for the task.
            pr_comments: PR review comments to address (if any).
            model_override: Optional model to use instead of default.
                           Used for dynamic model routing based on task complexity.
            required_branch: Optional branch name the agent should be on.
            create_pr: If True, instruct agent to create PR. If False, commit only.
            push_only: If True, push the commit but do NOT create a PR (for fixing
                an existing PR). Overrides create_pr.
            pr_group_info: Optional dict with PR group context (name, completed_tasks, etc).
            target_branch: The target branch for rebasing (default: "main").
            coding_style: Optional coding style guide to inject into prompt.

        Returns:
            Dict with 'output', 'success', and 'model_used' keys.
        """
        # Build prompt for work session
        prompt = build_work_prompt(
            task_description=task_description,
            context=context if context else None,
            pr_comments=pr_comments,
            required_branch=required_branch,
            create_pr=create_pr,
            push_only=push_only,
            pr_group_info=pr_group_info,
            target_branch=target_branch,
            coding_style=coding_style,
        )

        # Reset terminal-result capture so a prior session's outcome cannot
        # leak into this session's derived success.
        if self.message_processor is not None:
            self.message_processor.reset_result_state()

        # Run async query with optional model override
        result = run_async_with_cleanup(
            self.query_executor.run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("working"),
                model_override=model_override,
                get_model_name_func=self.get_model_name_func,
                get_agents_func=self.get_agents_func,
                process_message_func=self.process_message_func,
            )
        )

        # Derive success from the SDK's terminal ResultMessage instead of
        # assuming it. A budget/turn-capped or mid-execution error leaves
        # is_error=True; reporting such a half-done session as success would
        # let the orchestrator mark incomplete work [x]. When no processor is
        # wired, or the ResultMessage was lost (SDK bug #30333), fall back to
        # success from the accumulated text.
        success = True
        subtype: str | None = None
        if self.message_processor is not None:
            success = not self.message_processor.last_result_is_error
            subtype = self.message_processor.last_result_subtype

        return {
            "output": result,
            "success": success,
            "subtype": subtype,
            "model_used": (model_override or self.model).value,
        }

    def run_release_check(
        self,
        prompt: str,
        model_override: ModelType | None = None,
    ) -> dict[str, Any]:
        """Run a verify-only post-merge release check.

        Unlike ``run_work_session``, this does NOT wrap ``prompt`` in the
        create-PR contract. The release check is a read-only verification that
        must terminate with a ``RELEASE_CHECK: PASS/FAIL/SKIP`` marker. Routing
        it through ``run_work_session`` buries that instruction inside a work
        prompt whose outer contract demands "push + open a PR, don't finish
        without a PR URL" — a contradiction that makes the model drop the
        marker (``parse_release_check_result`` then defaults to SKIP, so the
        check can never FAIL) or open a junk PR. This runs the already-built
        prompt directly, and with verification-only tools (Read/Glob/Grep/Bash,
        no Edit/Write) so opening a PR is structurally impossible.

        Args:
            prompt: The fully-built release verification prompt (see
                ``build_release_check_prompt``).
            model_override: Optional model to use (callers pass Sonnet for
                speed); falls back to the executor's default model.

        Returns:
            Dict with 'output', 'success', 'subtype', and 'model_used' keys —
            the same shape as ``run_work_session``.
        """
        # Reset terminal-result capture so a prior session's outcome cannot
        # leak into this session's derived success.
        if self.message_processor is not None:
            self.message_processor.reset_result_state()

        # Run the prompt directly with verification tools (read + bash for
        # gh/curl/migration checks) — no create-PR wrapper, no write tools.
        result = run_async_with_cleanup(
            self.query_executor.run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("verification"),
                model_override=model_override,
                get_model_name_func=self.get_model_name_func,
                get_agents_func=self.get_agents_func,
                process_message_func=self.process_message_func,
            )
        )

        # Derive success from the SDK's terminal ResultMessage (see
        # run_work_session) rather than assuming it.
        success = True
        subtype: str | None = None
        if self.message_processor is not None:
            success = not self.message_processor.last_result_is_error
            subtype = self.message_processor.last_result_subtype

        return {
            "output": result,
            "success": success,
            "subtype": subtype,
            "model_used": (model_override or self.model).value,
        }

    def verify_success_criteria(
        self, criteria: str, context: str = "", tasks_summary: str = ""
    ) -> dict[str, Any]:
        """Verify if success criteria are met.

        Uses verification tools (Read, Glob, Grep, Bash) to actually run tests
        and lint checks as specified in the verification prompt.

        Args:
            criteria: The success criteria to verify.
            context: Accumulated learnings from prior sessions (context.md),
                injected under its own "Previous Context" header.
            tasks_summary: Summary of the tasks actually completed (checked-off
                plan tasks, merged PRs), injected under "Completed Tasks".

        Returns:
            Dict with 'success' and 'details' keys.
        """
        # Build prompt using centralized prompts module. Context and the
        # completed-tasks summary are passed separately so accumulated context
        # is never rendered under the "Completed Tasks" header.
        prompt = build_verification_prompt(
            criteria=criteria,
            tasks_summary=tasks_summary or None,
            context=context or None,
        )

        # Run async query with verification tools (read + bash for running tests)
        result = run_async_with_cleanup(
            self.query_executor.run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("verification"),
                get_model_name_func=self.get_model_name_func,
                get_agents_func=self.get_agents_func,
                process_message_func=self.process_message_func,
            )
        )

        # Parse the verification result
        success = self._parse_verification_result(result)

        return {
            "success": success,
            "details": result,
        }

    def extract_session_learnings(self, session_output: str, existing_context: str = "") -> str:
        """Extract terse, reusable learnings from a completed work session.

        Runs the (previously dead) context-extraction prompt over the session
        output so accumulated learnings can be persisted to context.md and
        injected into later planning/work/verification prompts. Uses read-only
        tools and Sonnet — this is a per-session summarization step, so it is
        kept cheap and fast rather than burning the work model on it.

        Args:
            session_output: The raw text output of the work session to summarize.
            existing_context: Already-accumulated context, passed so the model
                avoids repeating learnings it has captured before.

        Returns:
            The extracted learnings as terse markdown bullets, or ``""`` when
            ``session_output`` is empty.
        """
        if not session_output.strip():
            return ""

        prompt = build_context_extraction_prompt(
            session_output=session_output,
            existing_context=existing_context or None,
        )

        # Read-only tools (planning phase) — extraction only summarizes text
        # already in the prompt; it must never modify the repo or run commands.
        result = run_async_with_cleanup(
            self.query_executor.run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("planning"),
                model_override=ModelType.SONNET,  # Sonnet for speed/cost
                get_model_name_func=self.get_model_name_func,
                get_agents_func=self.get_agents_func,
                process_message_func=self.process_message_func,
            )
        )

        return result.strip()

    def _parse_verification_result(self, result: str) -> bool:
        """Parse the verification result to determine success.

        Args:
            result: The verification result text.

        Returns:
            True if verification passed, False otherwise.
        """
        result_lower = result.lower()

        # Look for our explicit marker first
        if "verification_result: pass" in result_lower:
            return True
        if "verification_result: fail" in result_lower:
            return False

        # Fallback: check for clear negative vs positive indicators
        # The key issue is catching "Overall Success: NO" while still
        # detecting genuine success
        negative_indicators = [
            "not met",
            "not all criteria",
            "criteria not met",
            "overall success: no",
            "criteria not satisfied",
            "verification failed",
            "cannot verify",
        ]
        positive_indicators = [
            "all criteria met",
            "all criteria verified",
            "overall success: yes",
            "verification successful",
            "success",  # Generic success indicator
        ]

        # Check for negative indicators first (these are disqualifying)
        has_negative = any(ind in result_lower for ind in negative_indicators)

        # Check for positive indicators
        has_positive = any(ind in result_lower for ind in positive_indicators)

        # Succeed if we have positive indicators without clear negatives
        # The key fix: "Overall Success: NO" will trigger has_negative
        return has_positive and not has_negative

    def get_tools_for_phase(self, phase: str) -> list[str]:
        """Get appropriate tools for the given phase from global config.

        Tool configurations can be customized via config.json:
        - Set in `.claude-task-master/config.json`
        - Under the `tools` section for each phase

        Args:
            phase: The phase name ('planning', 'verification', or 'working').

        Returns:
            List of tool names for the phase. Empty list means all tools allowed.
        """
        return get_tools_for_phase(phase)

    def _extract_plan(self, result: str) -> str:
        """Extract task list from planning result.

        Args:
            result: The raw planning result.

        Returns:
            The extracted or wrapped plan.
        """
        # For MVP, return the full result - we'll parse later
        if "## Task List" in result:
            return result

        # If no proper format, wrap it
        return f"## Task List\n\n{result}"

    def _extract_criteria(self, result: str) -> str:
        """Extract success criteria from planning result.

        Args:
            result: The raw planning result.

        Returns:
            The extracted success criteria.
        """
        # Look for success criteria section
        if "## Success Criteria" in result:
            parts = result.split("## Success Criteria")
            if len(parts) > 1:
                return parts[1].strip()

        # Default criteria if none specified
        return "All tasks in the task list are completed successfully."

    def generate_coding_style(self) -> dict[str, Any]:
        """Generate a coding style guide by analyzing the codebase.

        Analyzes CLAUDE.md, convention files, and sample source files
        to create a concise coding style guide.

        Returns:
            Dict with 'coding_style' and 'raw_output' keys.
        """
        # Build prompt for coding style generation
        prompt = build_coding_style_prompt()

        console.info("Generating coding style guide with Opus...")

        # Run with planning tools (read-only) and Opus for quality
        result = run_async_with_cleanup(
            self.query_executor.run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("planning"),
                model_override=ModelType.OPUS,  # Use Opus for quality
                get_model_name_func=self.get_model_name_func,
                get_agents_func=self.get_agents_func,
                process_message_func=self.process_message_func,
            )
        )

        # Extract the coding style content
        coding_style = extract_coding_style(result)

        return {
            "coding_style": coding_style,
            "raw_output": result,
        }

    def generate_release_guide(self) -> dict[str, Any]:
        """Generate a release guide by probing deploy infrastructure.

        Discovers deploy configs, monitoring, DB access, health endpoints,
        env vars, and cloud CLIs to map what release verification is possible.

        Uses all tools (including Bash) so the agent can probe env vars,
        run CLI commands, and check for credentials.

        Returns:
            Dict with 'release_guide' and 'raw_output' keys.
        """
        prompt = build_release_discovery_prompt()

        console.info("Discovering release infrastructure with Sonnet...")

        # Use working tools (all tools including Bash) so agent can probe env/CLIs
        result = run_async_with_cleanup(
            self.query_executor.run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("working"),  # All tools for probing
                model_override=ModelType.SONNET,  # Sonnet for speed
                get_model_name_func=self.get_model_name_func,
                get_agents_func=self.get_agents_func,
                process_message_func=self.process_message_func,
            )
        )

        release_guide = extract_release_guide(result)

        return {
            "release_guide": release_guide,
            "raw_output": result,
        }
