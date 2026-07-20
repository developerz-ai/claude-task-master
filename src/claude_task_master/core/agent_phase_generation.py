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

if TYPE_CHECKING:
    from .agent_query import AgentQueryExecutor


class _AgentPhaseGenerationMixin:
    """Mixin providing coding-style and release-guide generation to AgentPhaseExecutor.

    Attribute stubs satisfy mypy; concrete values are provided by AgentPhaseExecutor.
    """

    query_executor: AgentQueryExecutor
    get_model_name_func: Any
    get_agents_func: Any
    process_message_func: Any

    def get_tools_for_phase(self, phase: str) -> list[str]:
        """Return tool list for *phase* — overridden by AgentPhaseExecutor."""
        raise NotImplementedError  # pragma: no cover

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

        # Run with planning tools (read-only) and Opus for quality
        result = run_async_with_cleanup(
            self.query_executor.run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("planning"),
                model_override=ModelType.OPUS,  # Use Opus for quality
                get_model_name_func=self.get_model_name_func,
                get_agents_func=self.get_agents_func,
                process_message_func=self.process_message_func,
            )
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

        # Use working tools (all tools including Bash) so agent can probe env/CLIs
        result = run_async_with_cleanup(
            self.query_executor.run_query(
                prompt=prompt,
                tools=self.get_tools_for_phase("working"),  # All tools for probing
                model_override=ModelType.SONNET,  # Sonnet for speed
                get_model_name_func=self.get_model_name_func,
                get_agents_func=self.get_agents_func,
                process_message_func=self.process_message_func,
            )
        )

        release_guide = extract_release_guide(result)

        return {
            "release_guide": release_guide,
            "raw_output": result,
        }


__all__ = ["_AgentPhaseGenerationMixin"]
