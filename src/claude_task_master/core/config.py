"""Configuration Model - Pydantic models for claudetm configuration.

This module defines the configuration schema for Claude Task Master, including:
- API settings (Anthropic, OpenRouter)
- Model name mappings (sonnet, opus, haiku → full model strings)
- Git settings (target branch, auto-push)
- Tool configurations per phase (planning, verification, working)

Configuration is loaded from `.claude-task-master/config.json` in the project directory.
Environment variables can override specific settings.

Environment Variable Mapping:
| Config Key               | Environment Variable      |
|--------------------------|---------------------------|
| api.anthropic_api_key    | ANTHROPIC_API_KEY         |
| api.anthropic_base_url   | ANTHROPIC_BASE_URL        |
| api.openrouter_api_key   | OPENROUTER_API_KEY        |
| api.openrouter_base_url  | OPENROUTER_BASE_URL       |
| models.sonnet            | CLAUDETM_MODEL_SONNET     |
| models.opus              | CLAUDETM_MODEL_OPUS       |
| models.haiku             | CLAUDETM_MODEL_HAIKU      |
| git.target_branch        | CLAUDETM_TARGET_BRANCH    |
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# Configuration Sub-Models
# =============================================================================


class APIConfig(BaseModel):
    """API configuration settings.

    Supports both Anthropic direct API and OpenRouter proxy.
    API keys can be set via config file or environment variables.
    """

    anthropic_api_key: str | None = Field(
        default=None,
        description="Anthropic API key. Overridden by ANTHROPIC_API_KEY env var.",
    )
    anthropic_base_url: str = Field(
        default="https://api.anthropic.com",
        description="Anthropic API base URL. Overridden by ANTHROPIC_BASE_URL env var.",
    )
    openrouter_api_key: str | None = Field(
        default=None,
        description="OpenRouter API key. Overridden by OPENROUTER_API_KEY env var.",
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="OpenRouter API base URL. Overridden by OPENROUTER_BASE_URL env var.",
    )


class ModelConfig(BaseModel):
    """Model name mappings.

    Maps friendly names (sonnet, opus, haiku) to full API model strings.
    This allows users to customize which specific model version to use
    or use models from providers like OpenRouter.
    """

    sonnet: str = Field(
        default="claude-sonnet-4-5-20250929",
        description="Model name for 'sonnet' (balanced). Overridden by CLAUDETM_MODEL_SONNET.",
    )
    opus: str = Field(
        default="claude-opus-4-5-20251101",
        description="Model name for 'opus' (smartest). Overridden by CLAUDETM_MODEL_OPUS.",
    )
    haiku: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Model name for 'haiku' (fastest). Overridden by CLAUDETM_MODEL_HAIKU.",
    )


class GitConfig(BaseModel):
    """Git configuration settings.

    Controls how claudetm interacts with git for PRs and branches.
    """

    target_branch: str = Field(
        default="main",
        description="Target branch for PRs (e.g., main, master, develop). "
        "Overridden by CLAUDETM_TARGET_BRANCH.",
    )
    auto_push: bool = Field(
        default=True,
        description="Whether to automatically push branches after commits.",
    )


class ToolsConfig(BaseModel):
    """Tool configurations per execution phase.

    Each phase has a list of allowed tools:
    - planning: Read-only tools for codebase exploration
    - verification: Tools for running tests/lint
    - working: Full tool access for implementation (empty = all tools)

    Note: An empty list means ALL tools are allowed.
    """

    planning: list[str] = Field(
        default_factory=lambda: ["Read", "Glob", "Grep", "Bash", "WebFetch", "WebSearch"],
        description="Tools available during planning phase (read-only + bash for checks + web tools for research).",
    )
    verification: list[str] = Field(
        default_factory=lambda: ["Read", "Glob", "Grep", "Bash"],
        description="Tools available during verification phase (tests/lint).",
    )
    working: list[str] = Field(
        default_factory=list,
        description="Tools available during working phase (empty = all tools allowed).",
    )


# =============================================================================
# Main Configuration Model
# =============================================================================


class ClaudeTaskMasterConfig(BaseModel):
    """Main configuration model for Claude Task Master.

    This is the root configuration object that contains all settings.
    Configuration is loaded from `.claude-task-master/config.json` and
    can be overridden by environment variables.

    Example config.json:
    ```json
    {
      "version": "1.0",
      "api": {
        "anthropic_api_key": null,
        "anthropic_base_url": "https://api.anthropic.com"
      },
      "models": {
        "sonnet": "claude-sonnet-4-5-20250929",
        "opus": "claude-opus-4-5-20251101",
        "haiku": "claude-haiku-4-5-20251001"
      },
      "git": {
        "target_branch": "main",
        "auto_push": true
      },
      "tools": {
        "planning": ["Read", "Glob", "Grep", "Bash", "WebFetch", "WebSearch"],
        "verification": ["Read", "Glob", "Grep", "Bash"],
        "working": []
      }
    }
    ```
    """

    version: str = Field(
        default="1.0",
        description="Configuration schema version.",
    )
    api: APIConfig = Field(
        default_factory=APIConfig,
        description="API configuration (keys, URLs).",
    )
    models: ModelConfig = Field(
        default_factory=ModelConfig,
        description="Model name mappings.",
    )
    git: GitConfig = Field(
        default_factory=GitConfig,
        description="Git configuration (target branch, auto-push).",
    )
    tools: ToolsConfig = Field(
        default_factory=ToolsConfig,
        description="Tool configurations per phase.",
    )


# =============================================================================
# Default Configuration Generator
# =============================================================================


def generate_default_config() -> ClaudeTaskMasterConfig:
    """Generate a default configuration with all standard values.

    Returns:
        ClaudeTaskMasterConfig with all default values populated.
    """
    return ClaudeTaskMasterConfig()


def generate_default_config_dict() -> dict[str, Any]:
    """Generate default configuration as a dictionary.

    This is useful for writing to JSON files or for serialization.

    Returns:
        Dictionary representation of the default configuration.
    """
    config = generate_default_config()
    return config.model_dump()


def generate_default_config_json(indent: int = 2) -> str:
    """Generate default configuration as a formatted JSON string.

    Args:
        indent: Number of spaces for JSON indentation.

    Returns:
        JSON string representation of the default configuration.
    """
    config = generate_default_config()
    return config.model_dump_json(indent=indent)


# =============================================================================
# Utility Functions
# =============================================================================


def get_model_name(config: ClaudeTaskMasterConfig, model_key: str) -> str:
    """Get the full model name from a model key.

    Args:
        config: The configuration object.
        model_key: Short model name ("sonnet", "opus", "haiku").

    Returns:
        Full model name string from configuration.
        Falls back to sonnet if key is not found.
    """
    model_map = {
        "sonnet": config.models.sonnet,
        "opus": config.models.opus,
        "haiku": config.models.haiku,
    }
    return model_map.get(model_key.lower(), config.models.sonnet)


def get_tools_for_phase(config: ClaudeTaskMasterConfig, phase: str) -> list[str]:
    """Get the allowed tools for a specific execution phase.

    Args:
        config: The configuration object.
        phase: The phase name ("planning", "verification", "working").

    Returns:
        List of allowed tool names. Empty list means all tools allowed.
    """
    phase_map = {
        "planning": config.tools.planning,
        "verification": config.tools.verification,
        "working": config.tools.working,
    }
    return phase_map.get(phase.lower(), [])
