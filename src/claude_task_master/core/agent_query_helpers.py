"""Default message-processing and error-classification helpers for AgentQueryExecutor.

Provides :class:`_AgentQueryHelpersMixin` with:

- :meth:`_default_get_model_name` — maps ModelType to API model name string
- :meth:`_default_process_message` — accumulates text from SDK stream messages
- :meth:`_classify_api_error` — maps raw exceptions to typed AgentError subclasses
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .agent_exceptions import (
    AgentError,
    APIAuthenticationError,
    APIConnectionError,
    APIRateLimitError,
    APIServerError,
    APITimeoutError,
    ContentFilterError,
    ModelUnavailableError,
    QueryExecutionError,
)
from .config_loader import get_config

if TYPE_CHECKING:
    from .agent_models import ModelType


class _AgentQueryHelpersMixin:
    """Mixin providing default message processing and error classification.

    Concrete attribute stubs satisfy mypy; values are provided by AgentQueryExecutor.
    """

    model: ModelType

    def _default_get_model_name(self, model: ModelType) -> str:
        """Default model name mapping using global config.

        Model names are loaded from configuration, which can be:
        - Set in `.claude-task-master/config.json`
        - Overridden via environment variables (CLAUDETM_MODEL_SONNET, etc.)

        Args:
            model: The ModelType to convert.

        Returns:
            The API model name string from configuration.
        """
        from .agent_models import ModelType  # noqa: PLC0415

        config = get_config()
        model_map = {
            ModelType.SONNET: config.models.sonnet,
            ModelType.OPUS: config.models.opus,
            ModelType.FABLE: config.models.fable,
            ModelType.HAIKU: config.models.haiku,
            ModelType.SONNET_1M: config.models.sonnet_1m,
        }
        return model_map.get(model, config.models.sonnet)

    def _default_process_message(self, message: Any, result_text: str) -> str:
        """Default message processing - just accumulates text.

        Args:
            message: The message to process.
            result_text: The accumulated result text.

        Returns:
            Updated result text.
        """
        message_type = type(message).__name__

        if hasattr(message, "content") and message.content:
            for block in message.content:
                block_type = type(block).__name__
                if block_type == "TextBlock":
                    result_text += block.text

        if message_type == "ResultMessage":
            # Guard against None: error ResultMessages (max_turns, budget cap,
            # error_during_execution) carry result=None; overwriting the
            # accumulated text with None would drop real work and break the
            # str return contract.
            if hasattr(message, "result") and message.result:
                result_text = message.result

        return result_text

    def _classify_api_error(self, error: Exception) -> AgentError:
        """Classify an API error into a specific error type.

        Args:
            error: The original exception.

        Returns:
            A classified AgentError subclass.
        """
        error_str = str(error).lower()
        error_type = type(error).__name__

        # Check for content filtering errors (not retryable)
        if "content filtering" in error_str or "output blocked" in error_str:
            return ContentFilterError(error)

        # Check for model-availability errors (recover via fallback chain, not by
        # retrying the same model). Anthropic returns not_found_error for an
        # unknown/unavailable model id. Require both "model" and a not-found
        # keyword so generic messages like "503 Service Unavailable" or
        # "Network unreachable" are not misclassified.
        if "model" in error_str and any(
            kw in error_str
            for kw in ("not_found", "not found", "does not exist", "unavailable", "invalid model")
        ):
            return ModelUnavailableError(error)

        # Check for rate limiting
        if "rate" in error_str and "limit" in error_str:
            # Try to extract retry-after if present
            retry_after = None
            if hasattr(error, "retry_after"):
                retry_after = error.retry_after
            return APIRateLimitError(retry_after, error)

        # Check for authentication errors
        if any(kw in error_str for kw in ["auth", "unauthorized", "403", "401"]):
            return APIAuthenticationError(error)

        # Check for timeout errors
        if "timeout" in error_str or error_type in ("TimeoutError", "AsyncioTimeoutError"):
            return APITimeoutError(30.0, error)

        # Check for connection errors
        if any(kw in error_str for kw in ["connect", "connection", "network"]):
            return APIConnectionError(error)

        # Check for server errors (5xx)
        if "500" in error_str or "502" in error_str or "503" in error_str or "504" in error_str:
            # Try to extract status code
            for code in [500, 502, 503, 504]:
                if str(code) in error_str:
                    return APIServerError(code, error)
            return APIServerError(500, error)

        # Default to generic query execution error
        return QueryExecutionError(f"API error: {error}", error)


__all__ = ["_AgentQueryHelpersMixin"]
