"""Agent Wrapper - Encapsulates all Claude Agent SDK interactions.

This module provides single-turn queries via `query()` for planning,
verification, and working phases.
"""

from typing import TYPE_CHECKING, Any

from .agent_exceptions import (
    SDKImportError,
    SDKInitializationError,
)
from .agent_message import MessageProcessor
from .agent_models import (
    ModelType,
    TaskComplexity,
    ToolConfig,
    get_tools_for_phase,
)
from .agent_phases import AgentPhaseExecutor
from .agent_query import AgentQueryExecutor
from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
)
from .config_loader import get_config
from .rate_limit import RateLimitConfig
from .subagents import get_agents_for_working_dir

if TYPE_CHECKING:
    from .logger import TaskLogger

# Re-export for backward compatibility
__all__ = [
    "AgentWrapper",
    "ModelType",
    "TaskComplexity",
    "ToolConfig",
]


class AgentWrapper:
    """Wraps Claude Agent SDK for task execution."""

    def __init__(
        self,
        access_token: str,
        model: ModelType,
        working_dir: str = ".",
        rate_limit_config: RateLimitConfig | None = None,
        logger: "TaskLogger | None" = None,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
        max_budget_usd: float | None = None,
    ):
        """Initialize agent wrapper.

        Args:
            access_token: OAuth access token for Claude API.
            model: The Claude model to use.
            working_dir: Working directory for file operations.
            rate_limit_config: Rate limiting configuration. Uses defaults if None.
            logger: Optional TaskLogger for capturing tool usage and responses.
            circuit_breaker_config: Optional circuit breaker config for fault tolerance.
            max_budget_usd: Optional per-session spending cap in USD.

        Raises:
            SDKImportError: If claude-agent-sdk is not installed.
            SDKInitializationError: If SDK components cannot be initialized.
        """
        self.access_token = access_token
        self.model = model
        self.working_dir = working_dir
        self.rate_limit_config = rate_limit_config or RateLimitConfig.default()
        self.logger = logger
        self.max_budget_usd = max_budget_usd

        # Initialize circuit breaker for API fault tolerance
        self.circuit_breaker = CircuitBreaker(
            name="claude_api",
            config=circuit_breaker_config or CircuitBreakerConfig.default(),
        )

        # Import Claude Agent SDK with improved error handling
        self._import_sdk()

        # Hooks are disabled globally to prevent "Stream closed" errors
        # (known bug in Claude Code). Safety is enforced via bypassPermissions
        # mode with allowed_tools restrictions per phase instead.
        # Pass empty dict (not None) to explicitly override defaults from settings.
        self.hooks: dict[str, Any] = {}

        # Initialize message processor (delegated for SRP)
        self._message_processor = MessageProcessor(logger=self.logger)

        # Initialize query executor (delegated for SRP)
        self._query_executor = AgentQueryExecutor(
            query_func=self.query,
            options_class=self.options_class,
            working_dir=self.working_dir,
            model=self.model,
            rate_limit_config=self.rate_limit_config,
            circuit_breaker=self.circuit_breaker,
            hooks=self.hooks,
            logger=self.logger,
            max_budget_usd=self.max_budget_usd,
        )

        # Initialize phase executor (delegated for SRP)
        self._phase_executor = AgentPhaseExecutor(
            query_executor=self._query_executor,
            model=self.model,
            logger=self.logger,
            get_model_name_func=self._get_model_name,
            get_agents_func=get_agents_for_working_dir,
            process_message_func=self._message_processor.process_message,
            message_processor=self._message_processor,
        )

        # Note: The Claude Agent SDK will automatically use credentials from
        # ~/.claude/.credentials.json if no ANTHROPIC_API_KEY is set

    def _import_sdk(self) -> None:
        """Import and initialize the Claude Agent SDK.

        Raises:
            SDKImportError: If the SDK cannot be imported.
            SDKInitializationError: If SDK components are missing or invalid.
        """
        try:
            import claude_agent_sdk
        except ImportError as e:
            raise SDKImportError(e) from e
        except Exception as e:
            raise SDKImportError(e) from e

        # Validate required components exist
        try:
            self.query = claude_agent_sdk.query
        except AttributeError as e:
            raise SDKInitializationError("query", e) from e

        try:
            self.options_class = claude_agent_sdk.ClaudeAgentOptions
        except AttributeError as e:
            raise SDKInitializationError("ClaudeAgentOptions", e) from e

        # Verify the query is callable
        if not callable(self.query):
            raise SDKInitializationError(
                "query",
                ValueError("query must be callable"),
            )

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

        Delegates to AgentPhaseExecutor for implementation.
        """
        return self._phase_executor.run_planning_phase(
            goal, context, coding_style, max_prs, release_guide
        )

    def generate_coding_style(self) -> dict[str, Any]:
        """Generate a coding style guide by analyzing the codebase.

        Analyzes CLAUDE.md, convention files, and codebase to create a
        concise coding style guide with workflow and conventions.

        Returns:
            Dict with 'coding_style' and 'raw_output' keys.

        Delegates to AgentPhaseExecutor for implementation.
        """
        return self._phase_executor.generate_coding_style()

    def generate_release_guide(self) -> dict[str, Any]:
        """Generate a release guide by probing deploy infrastructure.

        Discovers deploy configs, monitoring, DB access, health endpoints,
        env vars, and cloud CLIs to map what release verification is possible.

        Returns:
            Dict with 'release_guide' and 'raw_output' keys.

        Delegates to AgentPhaseExecutor for implementation.
        """
        return self._phase_executor.generate_release_guide()

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

        Delegates to AgentPhaseExecutor for implementation.
        """
        return self._phase_executor.run_work_session(
            task_description=task_description,
            context=context,
            pr_comments=pr_comments,
            model_override=model_override,
            required_branch=required_branch,
            create_pr=create_pr,
            push_only=push_only,
            pr_group_info=pr_group_info,
            target_branch=target_branch,
            coding_style=coding_style,
        )

    def run_release_check(
        self,
        prompt: str,
        model_override: ModelType | None = None,
    ) -> dict[str, Any]:
        """Run a verify-only post-merge release check (no create-PR contract).

        The release check must NOT go through ``run_work_session``: that wraps
        the prompt in the create-PR contract, which contradicts the verify-only
        ``RELEASE_CHECK: PASS/FAIL/SKIP`` marker and lets the check silently
        default to SKIP (never FAIL). See ``AgentPhaseExecutor.run_release_check``.

        Args:
            prompt: The fully-built release verification prompt.
            model_override: Optional model to use (Sonnet for speed).

        Returns:
            Dict with 'output', 'success', 'subtype', and 'model_used' keys.

        Delegates to AgentPhaseExecutor for implementation.
        """
        return self._phase_executor.run_release_check(
            prompt=prompt,
            model_override=model_override,
        )

    def verify_success_criteria(
        self, criteria: str, context: str = "", tasks_summary: str = ""
    ) -> dict[str, Any]:
        """Verify if success criteria are met.

        Uses verification tools (Read, Glob, Grep, Bash) to actually run tests
        and lint checks as specified in the verification prompt. ``context``
        (accumulated learnings) and ``tasks_summary`` (completed tasks/PRs) are
        injected under separate headers.

        Delegates to AgentPhaseExecutor for implementation.
        """
        return self._phase_executor.verify_success_criteria(criteria, context, tasks_summary)

    def extract_session_learnings(self, session_output: str, existing_context: str = "") -> str:
        """Extract terse, reusable learnings from a completed work session.

        Powers context.md accumulation: the returned bullets are persisted by
        the orchestrator so later sessions build on prior learnings.

        Delegates to AgentPhaseExecutor for implementation.
        """
        return self._phase_executor.extract_session_learnings(session_output, existing_context)

    async def _run_query(
        self, prompt: str, tools: list[str], model_override: ModelType | None = None
    ) -> str:
        """Run query with retry logic for transient errors.

        Delegates to AgentQueryExecutor for actual execution with retry logic,
        circuit breaker integration, and error classification.

        Args:
            prompt: The prompt to send to the model.
            tools: List of tools to enable.
            model_override: Optional model to use instead of default.

        Returns:
            The result text from the query.

        Raises:
            WorkingDirectoryError: If working directory cannot be accessed.
            QueryExecutionError: If the query fails after all retries.
            APIAuthenticationError: If authentication fails (not retried).
        """
        return await self._query_executor.run_query(
            prompt=prompt,
            tools=tools,
            model_override=model_override,
            get_model_name_func=self._get_model_name,
            get_agents_func=get_agents_for_working_dir,
            process_message_func=self._message_processor.process_message,
        )

    def get_tools_for_phase(self, phase: str) -> list[str]:
        """Get appropriate tools for the given phase from global config.

        Tool configurations can be customized via config.json:
        - Set in `.claude-task-master/config.json`
        - Under the `tools` section for each phase

        Args:
            phase: The phase name ("planning", "verification", "working").

        Returns:
            List of allowed tool names. Empty list means all tools allowed.
        """
        return get_tools_for_phase(phase)

    def _get_model_name(self, model: ModelType | None = None) -> str:
        """Convert ModelType to API model name using global config.

        Model names are loaded from configuration, which can be:
        - Set in `.claude-task-master/config.json`
        - Overridden via environment variables (CLAUDETM_MODEL_SONNET, etc.)

        Args:
            model: Optional model override. If None, uses self.model.

        Returns:
            The API model name string from configuration.
        """
        target_model = model or self.model
        config = get_config()
        model_map = {
            ModelType.SONNET: config.models.sonnet,
            ModelType.OPUS: config.models.opus,
            ModelType.FABLE: config.models.fable,
            ModelType.HAIKU: config.models.haiku,
            ModelType.SONNET_1M: config.models.sonnet_1m,
        }
        return model_map.get(target_model, config.models.sonnet)
