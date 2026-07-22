"""Path utilities, file I/O, and environment-variable override helpers for config_loader."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from claude_task_master.core.config import (
    ClaudeTaskMasterConfig,
    generate_default_config_json,
)
from claude_task_master.core.profiles import active_profile_env_safe

# =============================================================================
# Constants
# =============================================================================

# Default state directory name (relative to project root)
STATE_DIR_NAME = ".claude-task-master"
CONFIG_FILE_NAME = "config.json"

# Environment variable mappings
# Format: (env_var_name, config_path_parts)
ENV_VAR_MAPPINGS: list[tuple[str, tuple[str, ...]]] = [
    ("ANTHROPIC_API_KEY", ("api", "anthropic_api_key")),
    ("ANTHROPIC_BASE_URL", ("api", "anthropic_base_url")),
    ("OPENROUTER_API_KEY", ("api", "openrouter_api_key")),
    ("OPENROUTER_BASE_URL", ("api", "openrouter_base_url")),
    ("CLAUDETM_MODEL_SONNET", ("models", "sonnet")),
    ("CLAUDETM_MODEL_OPUS", ("models", "opus")),
    ("CLAUDETM_MODEL_FABLE", ("models", "fable")),
    ("CLAUDETM_MODEL_HAIKU", ("models", "haiku")),
    ("CLAUDETM_MODEL_SONNET_1M", ("models", "sonnet_1m")),
    ("CLAUDETM_CONTEXT_OPUS", ("context_windows", "opus")),
    ("CLAUDETM_CONTEXT_FABLE", ("context_windows", "fable")),
    ("CLAUDETM_CONTEXT_SONNET", ("context_windows", "sonnet")),
    ("CLAUDETM_CONTEXT_HAIKU", ("context_windows", "haiku")),
    ("CLAUDETM_CONTEXT_SONNET_1M", ("context_windows", "sonnet_1m")),
    ("CLAUDETM_TARGET_BRANCH", ("git", "target_branch")),
]


# =============================================================================
# Path Utilities
# =============================================================================


def get_state_dir(working_dir: Path | None = None) -> Path:
    """Get the state directory path.

    Args:
        working_dir: Optional working directory. If None, uses cwd.

    Returns:
        Path to the .claude-task-master directory.
    """
    if working_dir is None:
        working_dir = Path.cwd()
    return working_dir / STATE_DIR_NAME


def get_config_file_path(working_dir: Path | None = None) -> Path:
    """Get the configuration file path.

    Args:
        working_dir: Optional working directory. If None, uses cwd.

    Returns:
        Path to the config.json file.
    """
    return get_state_dir(working_dir) / CONFIG_FILE_NAME


def config_file_exists(working_dir: Path | None = None) -> bool:
    """Check if configuration file exists.

    Args:
        working_dir: Optional working directory. If None, uses cwd.

    Returns:
        True if config.json exists.
    """
    return get_config_file_path(working_dir).exists()


# =============================================================================
# File Operations
# =============================================================================


def load_config_from_file(config_path: Path) -> ClaudeTaskMasterConfig:
    """Load configuration from a JSON file.

    Args:
        config_path: Path to the config.json file.

    Returns:
        ClaudeTaskMasterConfig object.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        json.JSONDecodeError: If the file is not valid JSON.
        ValidationError: If the JSON doesn't match the schema.
    """
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)

    return ClaudeTaskMasterConfig.model_validate(data)


def save_config_to_file(
    config: ClaudeTaskMasterConfig,
    config_path: Path | None = None,
    create_dir: bool = True,
) -> Path:
    """Save configuration to a JSON file.

    Args:
        config: Configuration object to save.
        config_path: Path to save to. If None, uses default location.
        create_dir: Whether to create the parent directory if missing.

    Returns:
        Path where the config was saved.
    """
    if config_path is None:
        config_path = get_config_file_path()

    if create_dir:
        config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config.model_dump_json(indent=2))
        f.write("\n")  # Trailing newline for POSIX compliance

    return config_path


def generate_default_config_file(
    config_path: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Generate a default configuration file.

    Args:
        config_path: Path to save to. If None, uses default location.
        overwrite: Whether to overwrite existing file.

    Returns:
        Path where the config was saved.

    Raises:
        FileExistsError: If file exists and overwrite is False.
    """
    if config_path is None:
        config_path = get_config_file_path()

    if config_path.exists() and not overwrite:
        raise FileExistsError(f"Config file already exists: {config_path}")

    # Create parent directory
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write default config with formatted JSON
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(generate_default_config_json(indent=2))
        f.write("\n")  # Trailing newline

    return config_path


def ensure_config_exists(working_dir: Path | None = None) -> tuple[Path, bool]:
    """Ensure configuration file exists, creating with defaults if missing.

    This is a safe, idempotent function that:
    - Creates the config file with defaults if it doesn't exist
    - Does nothing if the config file already exists
    - Never overwrites existing configuration

    Use this when you need to guarantee a config file exists before operations
    that depend on it, without loading the full configuration.

    Args:
        working_dir: Optional working directory. If None, uses cwd.

    Returns:
        Tuple of (config_path, was_created) where:
        - config_path: Path to the config file
        - was_created: True if the file was just created, False if it already existed

    Example:
        >>> path, created = ensure_config_exists()
        >>> if created:
        ...     print(f"Created new config at {path}")
        ... else:
        ...     print(f"Using existing config at {path}")
    """
    config_path = get_config_file_path(working_dir)

    if config_path.exists():
        return config_path, False

    # Create parent directory if needed
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write default config
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(generate_default_config_json(indent=2))
        f.write("\n")  # Trailing newline for POSIX compliance

    return config_path, True


# =============================================================================
# Environment Variable Override
# =============================================================================


def apply_env_overrides(config: ClaudeTaskMasterConfig) -> ClaudeTaskMasterConfig:
    """Apply environment variable overrides to configuration.

    Precedence (highest first): real environment variables, then the active
    profile's env, then the file-based config. Only non-empty values are
    applied.

    The active profile supplies the same keys for ``api-key``/``oauth`` profiles
    — auth (``ANTHROPIC_API_KEY``/``ANTHROPIC_BASE_URL``/``CLAUDE_CONFIG_DIR``),
    per-tier model ids (``CLAUDETM_MODEL_*``), and context windows
    (``CLAUDETM_CONTEXT_*``). Wiring it here is what makes a profile's model
    overrides actually take effect: without it the profile's ``CLAUDETM_MODEL_*``
    only reached the SDK subprocess env (which the bundled CLI ignores), never
    the config that drives ``get_model_name``.

    Args:
        config: Base configuration object.

    Returns:
        New configuration object with env var overrides applied.
    """
    # Convert to dict for modification
    config_dict = config.model_dump()

    # Active profile env ({} when no profile is active, or on profile error).
    # Real env vars win over the profile so an explicit export still overrides.
    profile_env = active_profile_env_safe()

    for env_var, path_parts in ENV_VAR_MAPPINGS:
        env_value = os.environ.get(env_var) or profile_env.get(env_var)
        if env_value:  # Only apply non-empty values
            _set_nested_value(config_dict, path_parts, env_value)

    # Create new config from modified dict
    return ClaudeTaskMasterConfig.model_validate(config_dict)


def _set_nested_value(
    d: dict[str, Any],
    path: tuple[str, ...],
    value: Any,
) -> None:
    """Set a nested value in a dictionary.

    Args:
        d: Dictionary to modify.
        path: Tuple of keys representing the path.
        value: Value to set.
    """
    for key in path[:-1]:
        d = d.setdefault(key, {})
    d[path[-1]] = value


def get_env_overrides() -> dict[str, str]:
    """Get all environment variable overrides that are currently set.

    Returns:
        Dictionary mapping env var names to their values.
    """
    overrides = {}
    for env_var, _path in ENV_VAR_MAPPINGS:
        value = os.environ.get(env_var)
        if value:
            overrides[env_var] = value
    return overrides


__all__ = [
    "STATE_DIR_NAME",
    "CONFIG_FILE_NAME",
    "ENV_VAR_MAPPINGS",
    "get_state_dir",
    "get_config_file_path",
    "config_file_exists",
    "load_config_from_file",
    "save_config_to_file",
    "generate_default_config_file",
    "ensure_config_exists",
    "apply_env_overrides",
    "_set_nested_value",
    "get_env_overrides",
]
