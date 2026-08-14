"""Code-style and release-guide generation mixin for AgentPhaseExecutor.

Provides :class:`_AgentPhaseGenerationMixin` with:

- :meth:`generate_coding_style` — analyzes codebase conventions
- :meth:`generate_release_guide` — probes deploy infrastructure
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import console
from .agent_async_utils import run_async_with_cleanup
from .agent_models import ModelType
from .prompts import (
    build_coding_style_prompt,
    build_release_discovery_prompt,
    extract_coding_style,
    extract_release_guide,
)
from .usage_limit import run_query_riding_out_usage_limits

if TYPE_CHECKING:
    from .agent_message import MessageProcessor
    from .agent_query import AgentQueryExecutor


class _AgentPhaseGenerationMixin:
    """Mixin providing coding-style and release-guide generation to AgentPhaseExecutor.

    Attribute stubs satisfy mypy; concrete values are provided by AgentPhaseExecutor.
    """

    query_executor: AgentQueryExecutor
    get_model_name_func: Any
    get_agents_func: Any
    process_message_func: Any
    message_processor: MessageProcessor | None

    def get_tools_for_phase(self, phase: str) -> list[str]:
        """Return tool list for *phase* — overridden by AgentPhaseExecutor."""
        raise NotImplementedError  # pragma: no cover

    def agents_for(self, fan_out: bool) -> Any:
        """The agent loader to hand this query, or None to register no agents.

        Subagent definitions are not free. Each one ships its full prompt in the
        query's system prompt (``hive-worker`` alone is ~1.4k tokens, re-read
        from cache on every turn of the session).

        What they are *not* is the switch that makes fan-out possible. That was
        believed here and is false: the CLI registers built-in dispatch types
        (``general-purpose``, ``Explore``, ``Plan``) on every query, so
        withholding definitions removes ``hive-worker`` and leaves the Agent tool
        working. The capability is denied where fan-out is not permitted by
        ``_execute_query``, which disallows the dispatch tools outright whenever
        this returns None — so returning None really does mean "cannot fan out".

        They used to be attached to every query unconditionally, which had two
        consequences neither documented nor intended: ``--no-parallel`` removed
        the fan-out brief but left the machinery in place, and phases that must
        never fan out — planning, verification, release checks, learnings
        extraction, and every push-only fix session — carried the worker
        contract and could act on it. A review-fix session was observed
        dispatching ``hive-worker`` subagents this way.

        So the rule is now the obvious one: agents are registered exactly where
        fan-out is permitted, and nowhere else.

        Args:
            fan_out: Whether this query may dispatch workers — see
                :func:`~.hive.fan_out_enabled`.

        Returns:
            ``self.get_agents_func`` when fan-out is permitted, else None.
        """
        return self.get_agents_func if fan_out else None

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

        # Run with planning tools (read-only) and Opus for quality. The guide
        # is persisted across runs, so a usage-limit refusal must be waited
        # out rather than extracted into coding-style.md as if it were a guide.
        result = run_query_riding_out_usage_limits(
            lambda: self.query_executor.run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("planning"),
                model_override=ModelType.OPUS,  # Use Opus for quality
                get_model_name_func=self.get_model_name_func,
                get_agents_func=self.agents_for(False),
                process_message_func=self.process_message_func,
            ),
            self.message_processor,
            runner=run_async_with_cleanup,
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

        # Use working tools (all tools including Bash) so agent can probe
        # env/CLIs. Like the coding-style guide, release.md is persisted
        # across runs — wait a usage-limit refusal out instead of saving it.
        result = run_query_riding_out_usage_limits(
            lambda: self.query_executor.run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("working"),  # All tools for probing
                model_override=ModelType.SONNET,  # Sonnet for speed
                get_model_name_func=self.get_model_name_func,
                get_agents_func=self.agents_for(False),
                process_message_func=self.process_message_func,
            ),
            self.message_processor,
            runner=run_async_with_cleanup,
        )

        release_guide = extract_release_guide(result)

        return {
            "release_guide": release_guide,
            "raw_output": result,
        }


__all__ = ["_AgentPhaseGenerationMixin"]
