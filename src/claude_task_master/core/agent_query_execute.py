"""Single-attempt query execution mixin for AgentQueryExecutor.

Provides :class:`_AgentQueryExecuteMixin` with :meth:`_execute_query`, which
submits a single prompt to the Claude Agent SDK and streams the response.

``STREAM_IDLE_TIMEOUT_SEC`` and ``POST_COMPLETION_IDLE_TIMEOUT_SEC`` are
accessed via deferred import from :mod:`agent_query` so that tests can patch
``claude_task_master.core.agent_query.STREAM_IDLE_TIMEOUT_SEC`` etc. and
have the change reflected inside this method at runtime.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any

from . import console
from .agent_exceptions import (
    APITimeoutError,
    SDKInitializationError,
    StreamStallError,
    WorkingDirectoryError,
)

if TYPE_CHECKING:
    from .agent_models import ModelType
    from .logger import TaskLogger


class _AgentQueryExecuteMixin:
    """Mixin providing single-attempt query execution to AgentQueryExecutor.

    Concrete attribute stubs satisfy mypy; values are provided by AgentQueryExecutor.
    """

    query: Any
    options_class: Any
    working_dir: str
    model: ModelType
    hooks: dict[str, Any]
    logger: TaskLogger | None
    max_budget_usd: float | None

    async def _execute_query(
        self,
        prompt: str,
        tools: list[str],
        model_override: ModelType | None = None,
        get_model_name_func: Any = None,
        get_agents_func: Any = None,
        process_message_func: Any = None,
    ) -> str:
        """Execute a single query attempt.

        Args:
            prompt: The prompt to send to the model.
            tools: List of tools to enable.
            model_override: Optional model to use instead of default.
            get_model_name_func: Function to convert ModelType to API model name.
            get_agents_func: Function to get subagents for working directory.
            process_message_func: Function to process messages from query stream.

        Returns:
            The result text from the query.

        Raises:
            WorkingDirectoryError: If working directory cannot be accessed.
            APIRateLimitError: If rate limited.
            APIConnectionError: If connection fails.
            APITimeoutError: If request times out.
            APIAuthenticationError: If authentication fails.
            APIServerError: If server returns 5xx error.
            QueryExecutionError: For other query errors.
        """
        # Deferred import so tests can patch agent_query.STREAM_IDLE_TIMEOUT_SEC
        import claude_task_master.core.agent_query as _aq  # noqa: PLC0415

        STREAM_IDLE_TIMEOUT_SEC = _aq.STREAM_IDLE_TIMEOUT_SEC
        POST_COMPLETION_IDLE_TIMEOUT_SEC = _aq.POST_COMPLETION_IDLE_TIMEOUT_SEC

        result_text = ""

        # Determine which model to use
        effective_model = model_override or self.model

        # Get model name using provided function or default
        if get_model_name_func:
            model_name = get_model_name_func(effective_model)
        else:
            model_name = self._default_get_model_name(effective_model)  # type: ignore[attr-defined]

        # Log the model and tools being used
        tools_str = ", ".join(tools) if tools else "all"
        console.detail(
            f"Using model: {effective_model.value} ({model_name}) | Tools: {tools_str}",
            flush=True,
        )

        # Validate working directory exists before passing it to the SDK.
        # The SDK receives cwd= in options_kwargs; we don't chdir (which would
        # race concurrent queries in server mode) but we do want a clear error
        # if the directory is missing rather than a cryptic SDK failure.
        if not os.path.isdir(self.working_dir):
            raise WorkingDirectoryError(
                self.working_dir,
                "change to",
                FileNotFoundError(f"No such directory: {self.working_dir}"),
            )

        # Load subagents from .claude/agents/ directory
        if get_agents_func:
            agents = get_agents_func(self.working_dir)
        else:
            agents = None

        # Determine effort level and fallback model for the effective model.
        from .agent_models import MODEL_EFFORT_MAP, get_fallback_chain  # noqa: PLC0415

        # Effort is keyed directly off the resolved model so every tier —
        # including FABLE, which no complexity routes to — gets extended
        # thinking (fable → "max"). A None here means "SDK default".
        effort_level = MODEL_EFFORT_MAP.get(effective_model)

        # Hand the SDK the first hop of the cycle-guarded fallback chain for
        # automatic single-hop recovery. Deeper hops are driven by the
        # multi-hop retry in _run_query_with_retry on ModelUnavailableError.
        fallback_model_name = None
        fallback_chain = get_fallback_chain(effective_model)
        if fallback_chain:
            fallback_type = fallback_chain[0]
            if get_model_name_func:
                fallback_model_name = get_model_name_func(fallback_type)
            else:
                fallback_model_name = self._default_get_model_name(fallback_type)  # type: ignore[attr-defined]

        # Pass stall-timeout env vars to the underlying CLI subprocess.
        # The Python SDK ignores these, but the bundled CLI binary respects
        # them and will fail-fast on internal stalls before our watchdog
        # has to step in. Belt-and-suspenders for issue #30333.
        stall_timeout_ms = str(int(STREAM_IDLE_TIMEOUT_SEC * 1000))
        cli_env = {
            "CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS": stall_timeout_ms,
            "API_TIMEOUT_MS": stall_timeout_ms,
        }
        # Inject the active profile's auth context (isolated CLAUDE_CONFIG_DIR
        # for oauth profiles, or ANTHROPIC_API_KEY/BASE_URL for api-key
        # profiles). No-op when no profile is active.
        from .profiles import resolve_runtime_env  # noqa: PLC0415

        cli_env.update(resolve_runtime_env())

        # Create options with model specification and subagents
        try:
            options_kwargs: dict[str, Any] = {
                "allowed_tools": tools,
                "permission_mode": "bypassPermissions",
                "model": model_name,
                "cwd": str(self.working_dir),
                "setting_sources": ["user", "local", "project"],
                "hooks": self.hooks,
                "agents": agents if agents else None,
                "max_buffer_size": 5 * 1024 * 1024,
                "env": cli_env,
            }

            # Add effort level for extended thinking depth control
            if effort_level:
                options_kwargs["effort"] = effort_level

            # Add fallback model for auto-recovery on model unavailability
            if fallback_model_name:
                options_kwargs["fallback_model"] = fallback_model_name

            # Add per-session budget cap if configured
            if self.max_budget_usd is not None:
                options_kwargs["max_budget_usd"] = self.max_budget_usd

            options = self.options_class(**options_kwargs)
        except Exception as e:
            raise SDKInitializationError("ClaudeAgentOptions", e) from e

        # Execute query with per-message idle-timeout watchdog.
        # Two timeout regimes (see constants above):
        #   - STREAM_IDLE_TIMEOUT_SEC: the agent may be mid-tool, mid-think,
        #     etc. Long ceiling to accommodate real long-running tools.
        #   - POST_COMPLETION_IDLE_TIMEOUT_SEC: the agent just signaled
        #     end_turn with no pending tool_use. The only remaining message
        #     is ResultMessage; if it doesn't arrive shortly, the SDK lost
        #     it (#30333). Treat as success with accumulated text.
        stream = self.query(prompt=prompt, options=options)
        agent_completed = False
        try:
            while True:
                current_timeout = (
                    POST_COMPLETION_IDLE_TIMEOUT_SEC if agent_completed else STREAM_IDLE_TIMEOUT_SEC
                )
                try:
                    message = await asyncio.wait_for(
                        stream.__anext__(),
                        timeout=current_timeout,
                    )
                except StopAsyncIteration:
                    break
                except TimeoutError as e:
                    if agent_completed:
                        # Agent finished; SDK swallowed ResultMessage. Don't
                        # retry — the work succeeded, retrying would re-run
                        # a completed task.
                        console.newline()
                        console.warning(
                            f"ResultMessage missing after end_turn "
                            f"({current_timeout:.0f}s) - SDK bug #30333, "
                            "treating accumulated text as success",
                            flush=True,
                        )
                        break
                    console.newline()
                    console.warning(
                        f"Stream idle for {current_timeout:.0f}s - treating as upstream stall",
                        flush=True,
                    )
                    raise StreamStallError(current_timeout, e) from e
                except StreamStallError:
                    raise
                except APITimeoutError:
                    raise
                except Exception as e:
                    raise self._classify_api_error(e) from e  # type: ignore[attr-defined]

                # Detect "agent has nothing more to do" — used to switch to
                # the post-completion short timeout. We can't import the
                # SDK types directly without circular issues, so check by
                # class name. An AssistantMessage with stop_reason=end_turn
                # and no ToolUseBlock means: no more turns, ResultMessage
                # is the only thing left.
                if type(message).__name__ == "AssistantMessage":
                    # Only the top-level conversation drives end-of-turn
                    # detection. A Task-subagent's messages carry
                    # parent_tool_use_id != None; its end_turn does NOT mean
                    # the parent is done, so treating it as completion would
                    # arm the short post-completion idle timeout and truncate
                    # the still-working parent mid-task.
                    if getattr(message, "parent_tool_use_id", None) is None:
                        content = getattr(message, "content", None) or []
                        has_tool_use = any(type(b).__name__ == "ToolUseBlock" for b in content)
                        stop_reason = getattr(message, "stop_reason", None)
                        if has_tool_use:
                            agent_completed = False
                        elif stop_reason == "end_turn":
                            agent_completed = True

                if process_message_func:
                    result_text = process_message_func(message, result_text)
                else:
                    result_text = self._default_process_message(message, result_text)  # type: ignore[attr-defined]
        finally:
            # Release SDK transport resources (HTTP connection, subprocess).
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    pass

        return result_text


__all__ = ["_AgentQueryExecuteMixin"]
