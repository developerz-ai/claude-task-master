"""Core module - exports key classes and exceptions."""

from claude_task_master.core import console
from claude_task_master.core.agent import AgentWrapper
from claude_task_master.core.agent_exceptions import (
    TRANSIENT_ERRORS,
    AgentError,
    APIAuthenticationError,
    APIConnectionError,
    APIRateLimitError,
    APIServerError,
    APITimeoutError,
    ContentFilterError,
    QueryExecutionError,
    SDKImportError,
    SDKInitializationError,
    WorkingDirectoryError,
)
from claude_task_master.core.agent_message import MessageProcessor
from claude_task_master.core.agent_models import (
    DEFAULT_COMPACT_THRESHOLD_PERCENT,
    MODEL_CONTEXT_WINDOWS,
    MODEL_CONTEXT_WINDOWS_STANDARD,
    ModelType,
    TaskComplexity,
    ToolConfig,
    get_tools_for_phase,
    parse_task_complexity,
)
from claude_task_master.core.agent_phases import AgentPhaseExecutor
from claude_task_master.core.agent_query import AgentQueryExecutor
from claude_task_master.core.checkpoint import (
    Checkpoint,
    CheckpointError,
    CheckpointingOptions,
    CheckpointManager,
    CheckpointNotFoundError,
    CheckpointRewindError,
    get_checkpointing_env,
)
from claude_task_master.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerMetrics,
    CircuitBreakerRegistry,
    CircuitState,
    get_circuit_breaker,
)
from claude_task_master.core.config import (
    APIConfig,
    ClaudeTaskMasterConfig,
    GitConfig,
    ModelConfig,
    ToolsConfig,
    generate_default_config,
    generate_default_config_dict,
    generate_default_config_json,
    get_model_name,
)
from claude_task_master.core.config_loader import (
    CONFIG,
    CONFIG_FILE_NAME,
    ENV_VAR_MAPPINGS,
    STATE_DIR_NAME,
    ConfigManager,
    apply_env_overrides,
    config_file_exists,
    generate_default_config_file,
    get_config,
    get_config_file_path,
    get_env_overrides,
    get_state_dir,
    initialize_config,
    load_config_from_file,
    reload_config,
    reset_config,
    save_config_to_file,
)
from claude_task_master.core.control import (
    ControlError,
    ControlManager,
    ControlOperationNotAllowedError,
    ControlResult,
    NoActiveTaskError,
)
from claude_task_master.core.credentials import (
    CredentialError,
    CredentialManager,
    CredentialNotFoundError,
    CredentialPermissionError,
    Credentials,
    InvalidCredentialsError,
    InvalidTokenResponseError,
    NetworkConnectionError,
    NetworkTimeoutError,
    TokenRefreshError,
    TokenRefreshHTTPError,
)
from claude_task_master.core.hooks import (
    AuditLogger,
    DangerousPattern,
    HookMatcher,
    HookResult,
    ProgressTracker,
    SafetyHooks,
    create_default_hooks,
)
from claude_task_master.core.orchestrator import (
    MaxSessionsReachedError,
    OrchestratorError,
    StateRecoveryError,
    WorkLoopOrchestrator,
)
from claude_task_master.core.parallel import (
    AsyncParallelExecutor,
    ParallelExecutor,
    ParallelExecutorConfig,
    ParallelTask,
    TaskResult,
    TaskStatus,
)
from claude_task_master.core.plan_updater import PlanUpdater
from claude_task_master.core.pr_context import PRContextManager
from claude_task_master.core.progress_tracker import (
    ExecutionTracker,
    ProgressState,
    SessionMetrics,
    TrackerConfig,
)
from claude_task_master.core.prompts import (
    PromptBuilder,
    PromptSection,
    build_context_extraction_prompt,
    build_error_recovery_prompt,
    build_plan_update_prompt,
    build_planning_prompt,
    build_task_completion_check_prompt,
    build_verification_prompt,
    build_work_prompt,
)
from claude_task_master.core.rate_limit import RateLimitConfig
from claude_task_master.core.shutdown import (
    ShutdownManager,
    add_shutdown_callback,
    get_shutdown_manager,
    get_shutdown_reason,
    interruptible_sleep,
    is_shutdown_requested,
    register_handlers,
    remove_shutdown_callback,
    request_shutdown,
    reset_shutdown,
    unregister_handlers,
)
from claude_task_master.core.state import (
    InvalidStateTransitionError,
    StateCorruptedError,
    StateError,
    StateLockError,
    StateManager,
    StateNotFoundError,
    StatePermissionError,
    StateResumeValidationError,
    StateValidationError,
    TaskOptions,
    TaskState,
)
from claude_task_master.core.task_runner import (
    NoPlanFoundError,
    NoTasksFoundError,
    TaskRunner,
    TaskRunnerError,
    WorkSessionError,
)
from claude_task_master.core.workflow_stages import WorkflowStageHandler

__all__ = [
    # Config classes and functions
    "ClaudeTaskMasterConfig",
    "APIConfig",
    "ModelConfig",
    "GitConfig",
    "ToolsConfig",
    "generate_default_config",
    "generate_default_config_dict",
    "generate_default_config_json",
    "get_model_name",
    "get_tools_for_phase",
    # Config loader classes and functions
    "ConfigManager",
    "CONFIG",
    "get_config",
    "reload_config",
    "reset_config",
    "initialize_config",
    "load_config_from_file",
    "save_config_to_file",
    "generate_default_config_file",
    "get_state_dir",
    "get_config_file_path",
    "config_file_exists",
    "apply_env_overrides",
    "get_env_overrides",
    "STATE_DIR_NAME",
    "CONFIG_FILE_NAME",
    "ENV_VAR_MAPPINGS",
    # Console module
    "console",
    # Credential exceptions
    "CredentialError",
    "CredentialNotFoundError",
    "InvalidCredentialsError",
    "CredentialPermissionError",
    "TokenRefreshError",
    "NetworkTimeoutError",
    "NetworkConnectionError",
    "TokenRefreshHTTPError",
    "InvalidTokenResponseError",
    # Credential classes
    "Credentials",
    "CredentialManager",
    # Agent exceptions
    "AgentError",
    "SDKImportError",
    "SDKInitializationError",
    "QueryExecutionError",
    "APIRateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "APIAuthenticationError",
    "APIServerError",
    "ContentFilterError",
    "WorkingDirectoryError",
    "TRANSIENT_ERRORS",
    # Agent classes
    "ModelType",
    "TaskComplexity",
    "ToolConfig",
    "AgentWrapper",
    "AgentPhaseExecutor",
    "AgentQueryExecutor",
    "MessageProcessor",
    "parse_task_complexity",
    # Model context configuration
    "MODEL_CONTEXT_WINDOWS",
    "MODEL_CONTEXT_WINDOWS_STANDARD",
    "DEFAULT_COMPACT_THRESHOLD_PERCENT",
    # Rate limit classes
    "RateLimitConfig",
    # Checkpoint exceptions
    "CheckpointError",
    "CheckpointNotFoundError",
    "CheckpointRewindError",
    # Checkpoint classes
    "Checkpoint",
    "CheckpointManager",
    "CheckpointingOptions",
    "get_checkpointing_env",
    # State exceptions
    "StateError",
    "StateNotFoundError",
    "StateCorruptedError",
    "StateValidationError",
    "InvalidStateTransitionError",
    "StatePermissionError",
    "StateLockError",
    "StateResumeValidationError",
    # State classes
    "StateManager",
    "TaskState",
    "TaskOptions",
    # Orchestrator exceptions
    "OrchestratorError",
    "StateRecoveryError",
    "MaxSessionsReachedError",
    # Orchestrator classes
    "WorkLoopOrchestrator",
    # Plan updater classes
    "PlanUpdater",
    # Task runner exceptions
    "TaskRunnerError",
    "NoPlanFoundError",
    "NoTasksFoundError",
    "WorkSessionError",
    # Task runner classes
    "TaskRunner",
    # PR context classes
    "PRContextManager",
    # Workflow stage classes
    "WorkflowStageHandler",
    # Shutdown classes and functions
    "ShutdownManager",
    "get_shutdown_manager",
    "register_handlers",
    "unregister_handlers",
    "is_shutdown_requested",
    "request_shutdown",
    "get_shutdown_reason",
    "reset_shutdown",
    "add_shutdown_callback",
    "remove_shutdown_callback",
    "interruptible_sleep",
    # Hook classes
    "HookMatcher",
    "HookResult",
    "DangerousPattern",
    "SafetyHooks",
    "AuditLogger",
    "ProgressTracker",
    "create_default_hooks",
    # Prompt classes
    "PromptBuilder",
    "PromptSection",
    "build_planning_prompt",
    "build_plan_update_prompt",
    "build_work_prompt",
    "build_verification_prompt",
    "build_task_completion_check_prompt",
    "build_context_extraction_prompt",
    "build_error_recovery_prompt",
    # Control classes and exceptions
    "ControlManager",
    "ControlResult",
    "ControlError",
    "ControlOperationNotAllowedError",
    "NoActiveTaskError",
    # Circuit breaker classes
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerError",
    "CircuitBreakerMetrics",
    "CircuitBreakerRegistry",
    "CircuitState",
    "get_circuit_breaker",
    # Parallel executor classes
    "AsyncParallelExecutor",
    "ParallelExecutor",
    "ParallelExecutorConfig",
    "ParallelTask",
    "TaskResult",
    "TaskStatus",
    # Execution tracker classes
    "ExecutionTracker",
    "ProgressState",
    "SessionMetrics",
    "TrackerConfig",
]
