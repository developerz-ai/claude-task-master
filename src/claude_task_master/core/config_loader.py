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
- CLAUDETM_MODEL_FABLE -> config.models.fable
- CLAUDETM_MODEL_HAIKU -> config.models.haiku
- CLAUDETM_MODEL_SONNET_1M -> config.models.sonnet_1m
- CLAUDETM_TARGET_BRANCH -> config.git.target_branch

Path utilities, file I/O, and env-override helpers live in
:mod:`.config_loader_io`.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from claude_task_master.core.config import (
    ClaudeTaskMasterConfig,
    generate_default_config,
)

from .config_loader_io import (  # noqa: F401 — re-exported for backwards compat
    CONFIG_FILE_NAME,
    ENV_VAR_MAPPINGS,
    STATE_DIR_NAME,
    _set_nested_value,
    apply_env_overrides,
    config_file_exists,
    ensure_config_exists,
    generate_default_config_file,
    get_config_file_path,
    get_env_overrides,
    get_state_dir,
    load_config_from_file,
    save_config_to_file,
)

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
