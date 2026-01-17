"""Agent Models - Enums, constants, and utility functions for model configuration.

This module contains:
- ModelType: Available Claude models (Sonnet, Opus, Haiku)
- TaskComplexity: Task complexity levels for dynamic model selection
- ToolConfig: Tool configurations for different execution phases
- MODEL_CONTEXT_WINDOWS: Model context window sizes
- parse_task_complexity: Parse complexity tags from task descriptions
"""

import re
from enum import Enum

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
    def get_model_for_complexity(cls, complexity: "TaskComplexity") -> ModelType:
        """Map task complexity to appropriate model."""
        mapping = {
            cls.CODING: ModelType.OPUS,
            cls.QUICK: ModelType.HAIKU,
            cls.GENERAL: ModelType.SONNET,
        }
        return mapping.get(complexity, ModelType.SONNET)


class ToolConfig(Enum):
    """Tool configurations for different phases."""

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
    # Working phase has full tool access for implementation
    WORKING = [
        "Read",
        "Write",
        "Edit",
        "Bash",
        "Glob",
        "Grep",
        "Task",
        "TodoWrite",
        "WebSearch",
        "WebFetch",
        "Skill",  # Enable Skills from .claude/skills/
    ]


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
