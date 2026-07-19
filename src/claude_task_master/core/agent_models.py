"""Agent Models - Enums, constants, and utility functions for model configuration.

This module contains:
- ModelType: Available Claude models (Sonnet, Opus, Haiku, Sonnet 1M)
- TaskComplexity: Task complexity levels for dynamic model selection,
  including get_model_name_for_complexity for name-based model routing
- ToolConfig: Tool configurations for different execution phases (now config-backed)
- MODEL_CONTEXT_WINDOWS: Model context window sizes
- parse_task_complexity: Parse complexity tags from task descriptions
- get_tools_for_phase: Get tool list for a phase from global config
"""

from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claude_task_master.core.config import ClaudeTaskMasterConfig

# =============================================================================
# Enums
# =============================================================================


class ModelType(Enum):
    """Available Claude models."""

    SONNET = "sonnet"
    OPUS = "opus"
    FABLE = "fable"
    HAIKU = "haiku"
    SONNET_1M = "sonnet_1m"


class TaskComplexity(Enum):
    """Task complexity levels for model selection.

    - CODING: Complex implementation tasks → Opus (smartest)
    - QUICK: Simple fixes, config changes → Haiku (fastest/cheapest)
    - GENERAL: Moderate complexity → Sonnet (balanced)
    - DEBUGGING_QA: Debugging/QA tasks → Sonnet 1M (deep context)
    """

    CODING = "coding"
    QUICK = "quick"
    GENERAL = "general"
    DEBUGGING_QA = "debugging-qa"

    @classmethod
    def get_model_for_complexity(cls, complexity: TaskComplexity) -> ModelType:
        """Map task complexity to appropriate model."""
        mapping = {
            cls.CODING: ModelType.OPUS,
            cls.QUICK: ModelType.HAIKU,
            cls.GENERAL: ModelType.SONNET,
            cls.DEBUGGING_QA: ModelType.SONNET_1M,
        }
        return mapping.get(complexity, ModelType.SONNET)

    @classmethod
    def get_effort_for_complexity(cls, complexity: TaskComplexity) -> str:
        """Map task complexity to SDK effort level.

        Controls extended thinking depth:
        - CODING → "max" (deepest reasoning for complex implementation)
        - QUICK → "low" (minimal thinking for simple fixes)
        - GENERAL → "medium" (balanced thinking)
        - DEBUGGING_QA → "high" (thorough analysis for debugging)
        """
        mapping: dict[TaskComplexity, str] = {
            cls.CODING: "max",
            cls.QUICK: "low",
            cls.GENERAL: "medium",
            cls.DEBUGGING_QA: "high",
        }
        return mapping.get(complexity, "medium")

    @classmethod
    def get_model_name_for_complexity(cls, complexity: TaskComplexity) -> ModelType:
        """Map task complexity to the ModelType for name-based model routing.

        Mirrors the historical task_group string map ("coding"->opus,
        "quick"->haiku, "general"->sonnet, "debugging-qa"->sonnet_1m),
        returned as ModelType so callers no longer do ModelType(str).

        Args:
            complexity: The task complexity level.

        Returns:
            ModelType for the given complexity (SONNET as fallback).
        """
        mapping = {
            cls.CODING: ModelType.OPUS,
            cls.QUICK: ModelType.HAIKU,
            cls.GENERAL: ModelType.SONNET,
            cls.DEBUGGING_QA: ModelType.SONNET_1M,
        }
        return mapping.get(complexity, ModelType.SONNET)


# =============================================================================
# Constants
# =============================================================================

# Model context window sizes (tokens) for auto-compact threshold calculation.
# These are defaults; users can override via config.json "context_windows" section.
# Opus 4.8 and Sonnet 5 support 1M context (beta, tier 4+ users).
# Note: The Agent SDK handles the `context-1m-2025-08-07` beta header internally.
# These values are only used to calculate when to trigger context compaction.
# See: https://platform.claude.com/docs/en/build-with-claude/context-windows
MODEL_CONTEXT_WINDOWS = {
    ModelType.OPUS: 1_000_000,  # Claude Opus 4.8: 1M context (beta, tier 4+)
    ModelType.FABLE: 1_000_000,  # Claude Fable 5: 1M context (default, no beta gate)
    ModelType.SONNET: 1_000_000,  # Claude Sonnet 5: 1M context (beta, tier 4+)
    ModelType.HAIKU: 200_000,  # Claude Haiku 4.5: 200K context
    ModelType.SONNET_1M: 1_000_000,  # Sonnet with 1M context (always 1M)
}

# Standard context windows (for users below tier 4)
MODEL_CONTEXT_WINDOWS_STANDARD = {
    ModelType.OPUS: 200_000,
    ModelType.FABLE: 1_000_000,  # Fable 5's 1M window is the default, not tier-gated
    ModelType.SONNET: 200_000,
    ModelType.HAIKU: 200_000,
    ModelType.SONNET_1M: 1_000_000,  # Always 1M — that's the point
}

# Fallback model mapping: if primary model unavailable, try fallback
MODEL_FALLBACK_MAP = {
    ModelType.FABLE: ModelType.OPUS,  # Fable → Opus (Anthropic's recommended fallback)
    ModelType.OPUS: ModelType.SONNET,  # Opus → Sonnet
    ModelType.SONNET: ModelType.HAIKU,  # Sonnet → Haiku
    ModelType.HAIKU: ModelType.SONNET,  # Haiku → Sonnet
    ModelType.SONNET_1M: ModelType.HAIKU,  # Sonnet 1M → Haiku (not Sonnet — same model ID)
}

# Direct model → SDK effort-level map (extended-thinking depth).
#
# Mirrors the complexity→effort mapping (get_effort_for_complexity) but is keyed
# by the *resolved* model, so tiers that no complexity routes to still get an
# effort level. Without this, a reverse-lookup-by-complexity left FABLE (the
# premium 2x-priced tier) with no matching complexity → effort=None → it ran
# WITHOUT extended thinking while Opus got "max".
MODEL_EFFORT_MAP: dict[ModelType, str] = {
    ModelType.OPUS: "max",  # smartest tier → deepest reasoning (mirrors CODING)
    ModelType.FABLE: "max",  # premium tier → deepest reasoning
    ModelType.SONNET: "medium",  # balanced (mirrors GENERAL)
    ModelType.HAIKU: "low",  # fast/cheap (mirrors QUICK)
    ModelType.SONNET_1M: "high",  # deep-context debugging/QA (mirrors DEBUGGING_QA)
}


def get_fallback_chain(model: ModelType) -> list[ModelType]:
    """Build the ordered, cycle-guarded fallback chain for a model.

    Walks ``MODEL_FALLBACK_MAP`` hop-by-hop from ``model``, stopping when a model
    has no fallback or when a model would repeat. The cycle guard is essential:
    the map contains the HAIKU↔SONNET pair (HAIKU→SONNET, SONNET→HAIKU), so a
    naive walk would loop forever. The starting ``model`` is not included.

    Args:
        model: The primary model to build a fallback chain for.

    Returns:
        Ordered list of fallback models to try, most-preferred first.
        Empty only if the model has no fallback mapping at all.

    Example:
        >>> get_fallback_chain(ModelType.FABLE)
        [<ModelType.OPUS: 'opus'>, <ModelType.SONNET: 'sonnet'>, <ModelType.HAIKU: 'haiku'>]
        >>> get_fallback_chain(ModelType.SONNET)
        [<ModelType.HAIKU: 'haiku'>]
    """
    chain: list[ModelType] = []
    seen: set[ModelType] = {model}
    current = model
    while True:
        nxt = MODEL_FALLBACK_MAP.get(current)
        if nxt is None or nxt in seen:
            break
        chain.append(nxt)
        seen.add(nxt)
        current = nxt
    return chain


def get_context_window(
    model: ModelType,
    config: ClaudeTaskMasterConfig | None = None,
) -> int:
    """Get context window size for a model, reading from config if available.

    Args:
        model: The model type.
        config: Optional config object. If None, uses hardcoded defaults.

    Returns:
        Context window size in tokens.
    """
    if config is not None:
        context_map = {
            ModelType.OPUS: config.context_windows.opus,
            ModelType.FABLE: config.context_windows.fable,
            ModelType.SONNET: config.context_windows.sonnet,
            ModelType.HAIKU: config.context_windows.haiku,
            ModelType.SONNET_1M: config.context_windows.sonnet_1m,
        }
        return context_map.get(model, MODEL_CONTEXT_WINDOWS[model])
    return MODEL_CONTEXT_WINDOWS[model]


# Default compact threshold as percentage of context window
DEFAULT_COMPACT_THRESHOLD_PERCENT = 0.85  # Compact at 85% usage


# =============================================================================
# Utility Functions
# =============================================================================


def validate_model(model: str) -> ModelType:
    """Resolve a model identifier to its :class:`ModelType`, or raise.

    The single validation path shared by the REST API, the MCP server, and the
    repo-planning flow, so all three accept exactly the same identifiers -- every
    ``ModelType`` value (``opus``, ``sonnet``, ``fable``, ``haiku``,
    ``sonnet_1m``) -- and reject everything else identically. Before this
    existed each transport diverged: REST hard-coded an ``opus|sonnet|haiku``
    regex (silently rejecting ``fable``/``sonnet_1m``), MCP ``initialize_task``
    persisted any string unchecked, and ``plan_repo`` coerced unknown names to
    Opus.

    Args:
        model: The model identifier to validate.

    Returns:
        The corresponding :class:`ModelType`.

    Raises:
        ValueError: If ``model`` is not a recognised identifier. The message
            lists every valid option.
    """
    try:
        return ModelType(model)
    except ValueError:
        valid = ", ".join(m.value for m in ModelType)
        raise ValueError(f"Invalid model '{model}'. Must be one of: {valid}") from None


def parse_task_complexity(task_description: str) -> tuple[TaskComplexity, str]:
    """Parse the complexity routing tag from a task description.

    Looks for [coding], [quick], [general], or [debugging-qa] tags, with or
    without surrounding backticks.

    Tag selection is *anchored*: the routing tag is conventionally the leading
    or trailing marker on a task line (e.g. ```[coding]` Implement ...``
    or ``... update docs `[general]```). When several tags appear, a tag
    anchored to the start or end of the text wins over one buried in prose — so a
    quoted mention like "avoid `[quick]` hacks, do it right
    `[coding]`" routes to CODING, not QUICK. If no tag is anchored, the
    last occurrence wins (the trailing marker is the usual placement). Only the
    winning tag is stripped (``count=1`` semantics); other occurrences are left
    intact so prose is preserved.

    Args:
        task_description: The task description potentially containing a complexity tag.

    Returns:
        Tuple of (TaskComplexity, cleaned_task_description).
        Defaults to CODING if no tag found (prefer smarter model).
    """
    # Match complexity tags with or without backticks:
    # `[coding]` (backtick-wrapped) or [coding] (bare).
    pattern = r"`?\[(coding|quick|general|debugging-qa)\]`?"
    matches = list(re.finditer(pattern, task_description, re.IGNORECASE))

    if not matches:
        # Default to CODING (prefer smarter model when uncertain).
        return TaskComplexity.CODING, task_description

    def _is_anchored(m: re.Match[str]) -> bool:
        """True if the match sits at the start or end of the text (ignoring space)."""
        before = task_description[: m.start()].strip()
        after = task_description[m.end() :].strip()
        return before == "" or after == ""

    anchored = [m for m in matches if _is_anchored(m)]
    # Prefer the last anchored tag; otherwise fall back to the last tag overall.
    chosen = anchored[-1] if anchored else matches[-1]

    complexity_str = chosen.group(1).lower()
    # Strip only the winning tag's span (count=1); leave prose mentions intact.
    cleaned = (task_description[: chosen.start()] + task_description[chosen.end() :]).strip()

    complexity_map = {
        "coding": TaskComplexity.CODING,
        "quick": TaskComplexity.QUICK,
        "general": TaskComplexity.GENERAL,
        "debugging-qa": TaskComplexity.DEBUGGING_QA,
    }
    return complexity_map.get(complexity_str, TaskComplexity.CODING), cleaned


def get_tools_for_phase(
    phase: str,
    config: ClaudeTaskMasterConfig | None = None,
) -> list[str]:
    """Get the allowed tools for a specific execution phase from config.

    This function reads tool configurations from the global config, allowing
    users to customize which tools are available in each phase via config.json.

    Args:
        phase: The phase name ("planning", "verification", "working").
        config: Optional config object. If None, loads from global config.

    Returns:
        List of allowed tool names. Empty list means all tools allowed.

    Example:
        >>> tools = get_tools_for_phase("planning")
        >>> print(tools)
        ["Read", "Glob", "Grep", "WebFetch", "WebSearch"]

        >>> # With custom config
        >>> config = get_config()
        >>> tools = get_tools_for_phase("working", config)
        >>> print(tools)  # Empty = all tools
        []
    """
    # Import here to avoid circular imports
    from claude_task_master.core.config_loader import get_config

    if config is None:
        config = get_config()

    phase_lower = phase.lower()

    if phase_lower == "planning":
        return list(config.tools.planning)
    elif phase_lower == "verification":
        return list(config.tools.verification)
    elif phase_lower == "working":
        return list(config.tools.working)
    else:
        # Unknown phase - default to empty (all tools allowed)
        return []
