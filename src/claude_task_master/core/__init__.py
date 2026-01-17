"""Core module - exports key classes and exceptions."""

from claude_task_master.core import console
from claude_task_master.core.agent import (
    DEFAULT_COMPACT_THRESHOLD_PERCENT,
    MODEL_CONTEXT_WINDOWS,
    MODEL_CONTEXT_WINDOWS_STANDARD,
    AgentError,
    AgentWrapper,
    APIAuthenticationError,
    APIConnectionError,
    APIRateLimitError,
    APIServerError,
    APITimeoutError,
    ModelType,
    QueryExecutionError,
    SDKImportError,
    SDKInitializationError,
    TaskComplexity,
    ToolConfig,
    WorkingDirectoryError,
    parse_task_complexity,
)
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
    "WorkingDirectoryError",
    # Agent classes
    "ModelType",
    "TaskComplexity",
    "ToolConfig",
    "AgentWrapper",
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
    "build_work_prompt",
    "build_verification_prompt",
    "build_task_completion_check_prompt",
    "build_context_extraction_prompt",
    "build_error_recovery_prompt",
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
