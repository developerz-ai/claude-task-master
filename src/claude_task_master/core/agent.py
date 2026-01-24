"""Agent Wrapper - Encapsulates all Claude Agent SDK interactions.

This module provides single-turn queries via `query()` for planning and
verification phases. For multi-turn conversations within task groups,
see the `conversation` module which uses `ClaudeSDKClient`.
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
    from .hooks import HookMatcher
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
        hooks: dict[str, list["HookMatcher"]] | None = None,
        enable_safety_hooks: bool = True,
        logger: "TaskLogger | None" = None,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
    ):
        """Initialize agent wrapper.

        Args:
            access_token: OAuth access token for Claude API.
            model: The Claude model to use.
            working_dir: Working directory for file operations.
            rate_limit_config: Rate limiting configuration. Uses defaults if None.
            hooks: Optional pre-configured hooks dictionary for ClaudeAgentOptions.
            enable_safety_hooks: If True and hooks is None, create default safety hooks.
            logger: Optional TaskLogger for capturing tool usage and responses.
            circuit_breaker_config: Optional circuit breaker config for fault tolerance.

        Raises:
            SDKImportError: If claude-agent-sdk is not installed.
            SDKInitializationError: If SDK components cannot be initialized.
        """
        self.access_token = access_token
        self.model = model
        self.working_dir = working_dir
        self.rate_limit_config = rate_limit_config or RateLimitConfig.default()
        self.hooks = hooks
        self.enable_safety_hooks = enable_safety_hooks
        self.logger = logger

        # Initialize circuit breaker for API fault tolerance
        self.circuit_breaker = CircuitBreaker(
            name="claude_api",
            config=circuit_breaker_config or CircuitBreakerConfig.default(),
        )

        # Import Claude Agent SDK with improved error handling
        self._import_sdk()

        # Initialize default hooks if not provided and safety enabled
        if self.hooks is None and self.enable_safety_hooks:
            self._init_default_hooks()

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
        )

        # Initialize phase executor (delegated for SRP)
        self._phase_executor = AgentPhaseExecutor(
            query_executor=self._query_executor,
            model=self.model,
            logger=self.logger,
            get_model_name_func=self._get_model_name,
            get_agents_func=get_agents_for_working_dir,
            process_message_func=self._message_processor.process_message,
        )

        # Note: The Claude Agent SDK will automatically use credentials from
        # ~/.claude/.credentials.json if no ANTHROPIC_API_KEY is set

    def _init_default_hooks(self) -> None:
        """Initialize default safety and audit hooks.

        This method is called when hooks are not explicitly provided and
        enable_safety_hooks is True. It sets up basic safety controls.
        """
        try:
            from .hooks import create_default_hooks

            self.hooks = create_default_hooks(
                enable_safety=True,
                enable_audit=False,  # Audit logging is handled by TaskLogger
                enable_progress=False,  # Progress tracking is handled by orchestrator
            )
        except ImportError:
            # If hooks module fails to import, continue without hooks
            self.hooks = None

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

    def run_planning_phase(self, goal: str, context: str = "") -> dict[str, Any]:
        """Run planning phase with read-only tools.

        Always uses Opus (smartest model) for planning to ensure
        high-quality task breakdown and complexity classification.

        Delegates to AgentPhaseExecutor for implementation.
        """
        return self._phase_executor.run_planning_phase(goal, context)

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

        Delegates to AgentPhaseExecutor for implementation.
        """
        return self._phase_executor.run_work_session(
            task_description=task_description,
            context=context,
            pr_comments=pr_comments,
            model_override=model_override,
            required_branch=required_branch,
            create_pr=create_pr,
            pr_group_info=pr_group_info,
            target_branch=target_branch,
        )

    def verify_success_criteria(self, criteria: str, context: str = "") -> dict[str, Any]:
        """Verify if success criteria are met.

        Uses verification tools (Read, Glob, Grep, Bash) to actually run tests
        and lint checks as specified in the verification prompt.

        Delegates to AgentPhaseExecutor for implementation.
        """
        return self._phase_executor.verify_success_criteria(criteria, context)

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
            ModelType.HAIKU: config.models.haiku,
        }
        return model_map.get(target_model, config.models.sonnet)
