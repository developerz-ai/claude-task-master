"""Agent Phase Execution - Handles planning, work, and verification phases.

This module contains the phase execution logic extracted from AgentWrapper,
following the Single Responsibility Principle (SRP). It handles:
- Planning phase execution with Opus model
- Work session execution with dynamic model selection
- Success criteria verification with read/bash tools
"""

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, TypeVar

from . import console
from .agent_models import ModelType, get_tools_for_phase
from .prompts import build_planning_prompt, build_verification_prompt, build_work_prompt

if TYPE_CHECKING:
    from .agent_query import AgentQueryExecutor
    from .logger import TaskLogger

T = TypeVar("T")


def run_async_with_cleanup[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run async coroutine with proper cleanup on KeyboardInterrupt.

    This ensures that when Ctrl+C is pressed, all pending tasks are cancelled
    and the event loop is properly closed.

    Args:
        coro: The coroutine to run.

    Returns:
        The result of the coroutine.

    Raises:
        KeyboardInterrupt: Re-raised after cleanup to allow proper handling.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    main_task = loop.create_task(coro)

    try:
        return loop.run_until_complete(main_task)
    except KeyboardInterrupt:
        # Cancel the main task and any pending tasks
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
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()


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
    ):
        """Initialize the phase executor.

        Args:
            query_executor: The query executor to use for running queries.
            model: The default model to use for queries.
            logger: Optional TaskLogger for capturing tool usage.
            get_model_name_func: Function to convert ModelType to API model name.
            get_agents_func: Function to get subagents for working directory.
            process_message_func: Function to process messages from query stream.
        """
        self.query_executor = query_executor
        self.model = model
        self.logger = logger
        self.get_model_name_func = get_model_name_func
        self.get_agents_func = get_agents_func
        self.process_message_func = process_message_func

    def run_planning_phase(self, goal: str, context: str = "") -> dict[str, Any]:
        """Run planning phase with read-only tools.

        Always uses Opus (smartest model) for planning to ensure
        high-quality task breakdown and complexity classification.

        Args:
            goal: The goal to plan for.
            context: Additional context for planning.

        Returns:
            Dict with 'plan', 'criteria', and 'raw_output' keys.
        """
        # Build prompt for planning
        prompt = build_planning_prompt(goal=goal, context=context if context else None)

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
        pr_group_info: dict | None = None,
        target_branch: str = "main",
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
            pr_group_info: Optional dict with PR group context (name, completed_tasks, etc).
            target_branch: The target branch for rebasing (default: "main").

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
            pr_group_info=pr_group_info,
            target_branch=target_branch,
        )

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

        return {
            "output": result,
            "success": True,  # For MVP, assume success
            "model_used": (model_override or self.model).value,
        }

    def verify_success_criteria(self, criteria: str, context: str = "") -> dict[str, Any]:
        """Verify if success criteria are met.

        Uses verification tools (Read, Glob, Grep, Bash) to actually run tests
        and lint checks as specified in the verification prompt.

        Args:
            criteria: The success criteria to verify.
            context: Additional context (e.g., tasks summary).

        Returns:
            Dict with 'success' and 'details' keys.
        """
        # Build prompt using centralized prompts module
        prompt = build_verification_prompt(criteria=criteria, tasks_summary=context)

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
