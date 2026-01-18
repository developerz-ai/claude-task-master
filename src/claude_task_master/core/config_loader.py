"""Configuration Loader - Global config singleton with env var support.

This module provides a global configuration singleton that:
1. Loads configuration from `.claude-task-master/config.json`
2. Auto-generates default config if missing
3. Merges with environment variable overrides
4. Provides a global `CONFIG` singleton accessible everywhere

Usage:
    from claude_task_master.core.config_loader import get_config, CONFIG

    # Get the current config (loads from file if needed)
    config = get_config()

    # Use the global singleton directly
    model_name = CONFIG.models.sonnet

    # Reload from file (e.g., after user edits)
    config = reload_config()

Environment Variable Overrides:
- ANTHROPIC_API_KEY -> config.api.anthropic_api_key
- ANTHROPIC_BASE_URL -> config.api.anthropic_base_url
- OPENROUTER_API_KEY -> config.api.openrouter_api_key
- OPENROUTER_BASE_URL -> config.api.openrouter_base_url
- CLAUDETM_MODEL_SONNET -> config.models.sonnet
- CLAUDETM_MODEL_OPUS -> config.models.opus
- CLAUDETM_MODEL_HAIKU -> config.models.haiku
- CLAUDETM_TARGET_BRANCH -> config.git.target_branch
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from claude_task_master.core.config import (
    ClaudeTaskMasterConfig,
    generate_default_config,
    generate_default_config_json,
)

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
    ("CLAUDETM_MODEL_HAIKU", ("models", "haiku")),
    ("CLAUDETM_TARGET_BRANCH", ("git", "target_branch")),
]


# =============================================================================
# Config Singleton
# =============================================================================


class ConfigManager:
    """Thread-safe configuration manager singleton.

    Handles loading, caching, and reloading of configuration.
    Provides environment variable override support.
    """

    _instance: ConfigManager | None = None
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls) -> ConfigManager:
        """Ensure only one instance exists (singleton pattern)."""
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize the config manager (only runs once)."""
        if self._initialized:
            return

        self._config: ClaudeTaskMasterConfig | None = None
        self._config_path: Path | None = None
        self._config_lock = threading.RLock()
        self._initialized = True

    @property
    def config(self) -> ClaudeTaskMasterConfig:
        """Get the current configuration (loads if needed).

        Returns:
            The current configuration object.
        """
        with self._config_lock:
            if self._config is None:
                self._config = self._load_config()
            return self._config

    @property
    def config_path(self) -> Path:
        """Get the configuration file path.

        Returns:
            Path to the config.json file.
        """
        if self._config_path is None:
            self._config_path = get_config_file_path()
        return self._config_path

    def reload(self, working_dir: Path | None = None) -> ClaudeTaskMasterConfig:
        """Reload configuration from file.

        Args:
            working_dir: Optional working directory to search for config.
                        If None, uses current working directory.

        Returns:
            The reloaded configuration object.
        """
        with self._config_lock:
            if working_dir is not None:
                self._config_path = working_dir / STATE_DIR_NAME / CONFIG_FILE_NAME
            else:
                self._config_path = None  # Will be recalculated

            self._config = self._load_config()
            return self._config

    def reset(self) -> None:
        """Reset the configuration (useful for testing).

        After reset, the next access will reload from file.
        """
        with self._config_lock:
            self._config = None
            self._config_path = None

    def _load_config(self) -> ClaudeTaskMasterConfig:
        """Load configuration from file with env var overrides.

        Returns:
            Configuration object with all overrides applied.
        """
        config_path = self.config_path

        # Load from file if exists, otherwise generate default
        if config_path.exists():
            config = load_config_from_file(config_path)
        else:
            # Generate default config (but don't write to file automatically)
            config = generate_default_config()

        # Apply environment variable overrides
        config = apply_env_overrides(config)

        return config


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

    Environment variables take precedence over file-based configuration.
    Only non-empty environment variables are applied.

    Args:
        config: Base configuration object.

    Returns:
        New configuration object with env var overrides applied.
    """
    # Convert to dict for modification
    config_dict = config.model_dump()

    for env_var, path_parts in ENV_VAR_MAPPINGS:
        env_value = os.environ.get(env_var)
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


# =============================================================================
# Public API
# =============================================================================

# Global config manager instance
_config_manager = ConfigManager()


def get_config(working_dir: Path | None = None) -> ClaudeTaskMasterConfig:
    """Get the current configuration.

    If no configuration has been loaded, this will:
    1. Load from `.claude-task-master/config.json` if it exists
    2. Use default configuration if no file exists
    3. Apply environment variable overrides

    Args:
        working_dir: Optional working directory. If provided and different
                    from previously loaded config, triggers a reload.

    Returns:
        The current configuration object.
    """
    if working_dir is not None:
        # Reload with new working directory
        return _config_manager.reload(working_dir)
    return _config_manager.config


def reload_config(working_dir: Path | None = None) -> ClaudeTaskMasterConfig:
    """Force reload configuration from file.

    Use this after the config file has been modified externally.

    Args:
        working_dir: Optional working directory for the config file.

    Returns:
        The reloaded configuration object.
    """
    return _config_manager.reload(working_dir)


def reset_config() -> None:
    """Reset the configuration cache.

    After reset, the next access will reload from file.
    Useful for testing or when changing directories.
    """
    _config_manager.reset()


def initialize_config(working_dir: Path | None = None) -> ClaudeTaskMasterConfig:
    """Initialize configuration, creating default file if needed.

    This is the main entry point for the CLI. It will:
    1. Create `.claude-task-master/` directory if needed
    2. Create `config.json` with defaults if missing
    3. Load and return the configuration

    Args:
        working_dir: Optional working directory.

    Returns:
        The initialized configuration object.
    """
    config_path = get_config_file_path(working_dir)

    if not config_path.exists():
        generate_default_config_file(config_path)

    return reload_config(working_dir)


# =============================================================================
# Global CONFIG Singleton
# =============================================================================


class _ConfigProxy:
    """Proxy object that provides attribute access to the global config.

    This allows using `CONFIG.models.sonnet` syntax while ensuring
    the config is always loaded when accessed.
    """

    def __getattr__(self, name: str) -> Any:
        """Get an attribute from the underlying config."""
        return getattr(_config_manager.config, name)

    def __repr__(self) -> str:
        """Return string representation."""
        return f"<ConfigProxy: {_config_manager.config!r}>"


# Global CONFIG singleton for convenient access
# Usage: from claude_task_master.core.config_loader import CONFIG
CONFIG = _ConfigProxy()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Main functions
    "get_config",
    "reload_config",
    "reset_config",
    "initialize_config",
    # File operations
    "load_config_from_file",
    "save_config_to_file",
    "generate_default_config_file",
    "ensure_config_exists",
    # Path utilities
    "get_state_dir",
    "get_config_file_path",
    "config_file_exists",
    # Environment variable utilities
    "apply_env_overrides",
    "get_env_overrides",
    # Constants
    "STATE_DIR_NAME",
    "CONFIG_FILE_NAME",
    "ENV_VAR_MAPPINGS",
    # Manager class (for advanced use)
    "ConfigManager",
    # Global singleton
    "CONFIG",
]
