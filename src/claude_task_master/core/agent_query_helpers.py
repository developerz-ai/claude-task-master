"""Default message-processing and error-classification helpers for AgentQueryExecutor.

Provides :class:`_AgentQueryHelpersMixin` with:

- :meth:`_default_get_model_name` — maps ModelType to API model name string
- :meth:`_default_process_message` — accumulates text from SDK stream messages
- :meth:`_classify_api_error` — thin delegator to :mod:`.agent_error_classify`
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .agent_exceptions import AgentError
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

        Delegates to :func:`~.agent_error_classify.classify_api_error`. The
        policy lives in its own module because the verdict decides whether an
        unattended run retries or dies, and because it now has two sources to
        reconcile — the SDK's structured ``ResultError`` payload and the message
        text — which is more than one reason for this mixin to change.

        Args:
            error: The original exception.

        Returns:
            A classified AgentError subclass.
        """
        from .agent_error_classify import classify_api_error  # noqa: PLC0415

        return classify_api_error(error)


__all__ = ["_AgentQueryHelpersMixin"]
