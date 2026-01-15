"""Core module - exports key classes and exceptions."""

from claude_task_master.core import console
from claude_task_master.core.agent import (
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
    NoPlanFoundError,
    NoTasksFoundError,
    OrchestratorError,
    PlanParsingError,
    StateRecoveryError,
    TaskIndexOutOfBoundsError,
    VerificationFailedError,
    WorkLoopOrchestrator,
    WorkSessionError,
)
from claude_task_master.core.state import (
    InvalidStateTransitionError,
    StateCorruptedError,
    StateError,
    StateLockError,
    StateManager,
    StateNotFoundError,
    StatePermissionError,
    StateValidationError,
    TaskOptions,
    TaskState,
)

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
    # State exceptions
    "StateError",
    "StateNotFoundError",
    "StateCorruptedError",
    "StateValidationError",
    "InvalidStateTransitionError",
    "StatePermissionError",
    "StateLockError",
    # State classes
    "StateManager",
    "TaskState",
    "TaskOptions",
    # Orchestrator exceptions
    "OrchestratorError",
    "PlanParsingError",
    "NoPlanFoundError",
    "NoTasksFoundError",
    "TaskIndexOutOfBoundsError",
    "WorkSessionError",
    "StateRecoveryError",
    "MaxSessionsReachedError",
    "VerificationFailedError",
    # Orchestrator classes
    "WorkLoopOrchestrator",
    # Hook classes
    "HookMatcher",
    "HookResult",
    "DangerousPattern",
    "SafetyHooks",
    "AuditLogger",
    "ProgressTracker",
    "create_default_hooks",
]
