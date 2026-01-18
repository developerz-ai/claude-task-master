"""Agent Models - Enums, constants, and utility functions for model configuration.

This module contains:
- ModelType: Available Claude models (Sonnet, Opus, Haiku)
- TaskComplexity: Task complexity levels for dynamic model selection
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
    HAIKU = "haiku"


class TaskComplexity(Enum):
    """Task complexity levels for model selection.

    - CODING: Complex implementation tasks → Opus (smartest)
    - QUICK: Simple fixes, config changes → Haiku (fastest/cheapest)
    - GENERAL: Moderate complexity → Sonnet (balanced)
    """

    CODING = "coding"
    QUICK = "quick"
    GENERAL = "general"

    @classmethod
    def get_model_for_complexity(cls, complexity: TaskComplexity) -> ModelType:
        """Map task complexity to appropriate model."""
        mapping = {
            cls.CODING: ModelType.OPUS,
            cls.QUICK: ModelType.HAIKU,
            cls.GENERAL: ModelType.SONNET,
        }
        return mapping.get(complexity, ModelType.SONNET)


class ToolConfig(Enum):
    """Tool configurations for different phases.

    Each phase specifies the tools available to Claude:
    - PLANNING: Read-only tools (Read, Glob, Grep, Bash) for exploring codebase
    - VERIFICATION: Same as planning (Read, Glob, Grep, Bash) for running tests/lint
    - WORKING: Empty list [] allows ALL tools for full implementation access

    Note: An empty list in allowed_tools means "all tools are allowed".

    DEPRECATED: Use `get_tools_for_phase()` function instead, which reads from
    the global config and supports user customization via config.json.
    These hardcoded values are kept for backwards compatibility only.
    """

    # Planning uses READ-ONLY tools + Bash for checks (git status, tests, etc.)
    PLANNING = [
        "Read",
        "Glob",
        "Grep",
        "Bash",
    ]
    # Verification uses read tools + Bash for running tests/lint (no write access)
    VERIFICATION = [
        "Read",
        "Glob",
        "Grep",
        "Bash",
    ]
    # Working phase has full tool access - empty list allows ALL tools
    WORKING = list[str]()


# =============================================================================
# Constants
# =============================================================================

# Model context window sizes (tokens) for auto-compact threshold calculation
# Sonnet 4/4.5 supports 1M context (available for tier 4+ users)
# See: https://www.claude.com/blog/1m-context
MODEL_CONTEXT_WINDOWS = {
    ModelType.OPUS: 200_000,  # Claude Opus 4.5: 200K context
    ModelType.SONNET: 1_000_000,  # Claude Sonnet 4/4.5: 1M context (tier 4+)
    ModelType.HAIKU: 200_000,  # Claude Haiku 4.5: 200K context
}

# Standard context windows (for users below tier 4)
MODEL_CONTEXT_WINDOWS_STANDARD = {
    ModelType.OPUS: 200_000,
    ModelType.SONNET: 200_000,
    ModelType.HAIKU: 200_000,
}

# Default compact threshold as percentage of context window
DEFAULT_COMPACT_THRESHOLD_PERCENT = 0.85  # Compact at 85% usage


# =============================================================================
# Utility Functions
# =============================================================================


def parse_task_complexity(task_description: str) -> tuple[TaskComplexity, str]:
    """Parse task complexity tag from task description.

    Looks for `[coding]`, `[quick]`, or `[general]` tags in the task.

    Args:
        task_description: The task description potentially containing a complexity tag.

    Returns:
        Tuple of (TaskComplexity, cleaned_task_description).
        Defaults to CODING if no tag found (prefer smarter model).
    """
    # Look for complexity tags in backticks: `[coding]`, `[quick]`, `[general]`
    pattern = r"`\[(coding|quick|general)\]`"
    match = re.search(pattern, task_description, re.IGNORECASE)

    if match:
        complexity_str = match.group(1).lower()
        # Remove the tag from the description
        cleaned = re.sub(pattern, "", task_description, flags=re.IGNORECASE).strip()

        complexity_map = {
            "coding": TaskComplexity.CODING,
            "quick": TaskComplexity.QUICK,
            "general": TaskComplexity.GENERAL,
        }
        return complexity_map.get(complexity_str, TaskComplexity.CODING), cleaned

    # Default to CODING (prefer smarter model when uncertain)
    return TaskComplexity.CODING, task_description


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
        ["Read", "Glob", "Grep", "Bash"]

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
