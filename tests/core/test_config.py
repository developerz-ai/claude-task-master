"""Tests for the configuration model and loader.

Tests for:
- Default config generation
- Model serialization/deserialization
- Utility functions (get_model_name, get_tools_for_phase)
- Configuration file loading and saving
- Environment variable override behavior
- ConfigManager singleton pattern
"""

import json
import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from claude_task_master.core.config import (
    APIConfig,
    ClaudeTaskMasterConfig,
    GitConfig,
    ModelConfig,
    ToolsConfig,
    generate_default_config,
    generate_default_config_dict,
    generate_default_config_json,
    get_model_name,
    get_tools_for_phase,
)
from claude_task_master.core.config_loader import (
    CONFIG_FILE_NAME,
    STATE_DIR_NAME,
    ConfigManager,
    apply_env_overrides,
    config_file_exists,
    generate_default_config_file,
    get_config,
    get_config_file_path,
    get_env_overrides,
    get_state_dir,
    load_config_from_file,
    reload_config,
    reset_config,
    save_config_to_file,
)


class TestAPIConfig:
    """Tests for APIConfig model."""

    def test_default_values(self) -> None:
        """Test that APIConfig has correct default values."""
        config = APIConfig()
        assert config.anthropic_api_key is None
        assert config.anthropic_base_url == "https://api.anthropic.com"
        assert config.openrouter_api_key is None
        assert config.openrouter_base_url == "https://openrouter.ai/api/v1"

    def test_custom_values(self) -> None:
        """Test that APIConfig accepts custom values."""
        config = APIConfig(
            anthropic_api_key="sk-ant-test123",
            anthropic_base_url="https://custom.api.com",
            openrouter_api_key="sk-or-test456",
            openrouter_base_url="https://custom.openrouter.com",
        )
        assert config.anthropic_api_key == "sk-ant-test123"
        assert config.anthropic_base_url == "https://custom.api.com"
        assert config.openrouter_api_key == "sk-or-test456"
        assert config.openrouter_base_url == "https://custom.openrouter.com"


class TestModelConfig:
    """Tests for ModelConfig model."""

    def test_default_values(self) -> None:
        """Test that ModelConfig has correct default values."""
        config = ModelConfig()
        assert config.sonnet == "claude-sonnet-4-5-20250929"
        assert config.opus == "claude-opus-4-5-20251101"
        assert config.haiku == "claude-haiku-4-5-20251001"

    def test_custom_models(self) -> None:
        """Test that ModelConfig accepts custom model names."""
        config = ModelConfig(
            sonnet="anthropic/claude-sonnet-4-5-20250929",
            opus="anthropic/claude-opus-4-5-20251101",
            haiku="anthropic/claude-haiku-4-5-20251001",
        )
        assert config.sonnet == "anthropic/claude-sonnet-4-5-20250929"
        assert config.opus == "anthropic/claude-opus-4-5-20251101"
        assert config.haiku == "anthropic/claude-haiku-4-5-20251001"


class TestGitConfig:
    """Tests for GitConfig model."""

    def test_default_values(self) -> None:
        """Test that GitConfig has correct default values."""
        config = GitConfig()
        assert config.target_branch == "main"
        assert config.auto_push is True

    def test_custom_values(self) -> None:
        """Test that GitConfig accepts custom values."""
        config = GitConfig(target_branch="develop", auto_push=False)
        assert config.target_branch == "develop"
        assert config.auto_push is False


class TestToolsConfig:
    """Tests for ToolsConfig model."""

    def test_default_values(self) -> None:
        """Test that ToolsConfig has correct default values."""
        config = ToolsConfig()
        assert config.planning == ["Read", "Glob", "Grep", "Bash"]
        assert config.verification == ["Read", "Glob", "Grep", "Bash"]
        assert config.working == []

    def test_custom_tools(self) -> None:
        """Test that ToolsConfig accepts custom tool lists."""
        config = ToolsConfig(
            planning=["Read", "Glob"],
            verification=["Bash"],
            working=["Write", "Edit"],
        )
        assert config.planning == ["Read", "Glob"]
        assert config.verification == ["Bash"]
        assert config.working == ["Write", "Edit"]


class TestClaudeTaskMasterConfig:
    """Tests for the main ClaudeTaskMasterConfig model."""

    def test_default_values(self) -> None:
        """Test that main config has correct default values."""
        config = ClaudeTaskMasterConfig()
        assert config.version == "1.0"
        assert isinstance(config.api, APIConfig)
        assert isinstance(config.models, ModelConfig)
        assert isinstance(config.git, GitConfig)
        assert isinstance(config.tools, ToolsConfig)

    def test_nested_defaults(self) -> None:
        """Test that nested configs have correct defaults."""
        config = ClaudeTaskMasterConfig()
        assert config.api.anthropic_api_key is None
        assert config.models.sonnet == "claude-sonnet-4-5-20250929"
        assert config.git.target_branch == "main"
        assert config.tools.planning == ["Read", "Glob", "Grep", "Bash"]

    def test_full_custom_config(self) -> None:
        """Test creating a fully custom configuration."""
        config = ClaudeTaskMasterConfig(
            version="1.1",
            api=APIConfig(anthropic_api_key="test-key"),
            models=ModelConfig(sonnet="custom-sonnet"),
            git=GitConfig(target_branch="develop"),
            tools=ToolsConfig(planning=["Read"]),
        )
        assert config.version == "1.1"
        assert config.api.anthropic_api_key == "test-key"
        assert config.models.sonnet == "custom-sonnet"
        assert config.git.target_branch == "develop"
        assert config.tools.planning == ["Read"]

    def test_serialization_to_dict(self) -> None:
        """Test that config serializes to dict correctly."""
        config = ClaudeTaskMasterConfig()
        data = config.model_dump()
        assert isinstance(data, dict)
        assert data["version"] == "1.0"
        assert "api" in data
        assert "models" in data
        assert "git" in data
        assert "tools" in data

    def test_serialization_to_json(self) -> None:
        """Test that config serializes to JSON correctly."""
        config = ClaudeTaskMasterConfig()
        json_str = config.model_dump_json()
        data = json.loads(json_str)
        assert isinstance(data, dict)
        assert data["version"] == "1.0"

    def test_deserialization_from_dict(self) -> None:
        """Test that config deserializes from dict correctly."""
        data = {
            "version": "1.0",
            "api": {"anthropic_api_key": "test-key"},
            "models": {"sonnet": "custom-sonnet"},
            "git": {"target_branch": "develop"},
            "tools": {"planning": ["Read"]},
        }
        config = ClaudeTaskMasterConfig.model_validate(data)
        assert config.api.anthropic_api_key == "test-key"
        assert config.models.sonnet == "custom-sonnet"
        assert config.git.target_branch == "develop"
        assert config.tools.planning == ["Read"]

    def test_partial_config_uses_defaults(self) -> None:
        """Test that partial config uses defaults for missing fields."""
        data = {"api": {"anthropic_api_key": "test-key"}}
        config = ClaudeTaskMasterConfig.model_validate(data)
        # Custom value
        assert config.api.anthropic_api_key == "test-key"
        # Default values for other fields
        assert config.api.anthropic_base_url == "https://api.anthropic.com"
        assert config.models.sonnet == "claude-sonnet-4-5-20250929"
        assert config.git.target_branch == "main"

    def test_empty_config_uses_all_defaults(self) -> None:
        """Test that empty config uses all defaults."""
        config = ClaudeTaskMasterConfig.model_validate({})
        assert config.version == "1.0"
        assert config.api.anthropic_api_key is None
        assert config.models.sonnet == "claude-sonnet-4-5-20250929"

    def test_invalid_field_raises_error(self) -> None:
        """Test that invalid field type raises validation error."""
        # Using an invalid type (dict instead of str) to trigger validation error
        with pytest.raises(ValidationError):
            ClaudeTaskMasterConfig(version={"invalid": "type"})  # type: ignore[arg-type]


class TestDefaultConfigGeneration:
    """Tests for default config generation functions."""

    def test_generate_default_config(self) -> None:
        """Test generate_default_config returns valid config."""
        config = generate_default_config()
        assert isinstance(config, ClaudeTaskMasterConfig)
        assert config.version == "1.0"

    def test_generate_default_config_dict(self) -> None:
        """Test generate_default_config_dict returns valid dict."""
        data = generate_default_config_dict()
        assert isinstance(data, dict)
        assert data["version"] == "1.0"
        assert isinstance(data["api"], dict)
        assert isinstance(data["models"], dict)

    def test_generate_default_config_json(self) -> None:
        """Test generate_default_config_json returns valid JSON."""
        json_str = generate_default_config_json()
        assert isinstance(json_str, str)
        data = json.loads(json_str)
        assert data["version"] == "1.0"

    def test_generate_default_config_json_custom_indent(self) -> None:
        """Test generate_default_config_json respects indent parameter."""
        json_str = generate_default_config_json(indent=4)
        # Check that it contains multiple lines (indented)
        assert "\n" in json_str
        # Should be parseable
        data = json.loads(json_str)
        assert data["version"] == "1.0"


class TestUtilityFunctions:
    """Tests for config utility functions."""

    def test_get_model_name_sonnet(self) -> None:
        """Test get_model_name returns correct model for sonnet."""
        config = ClaudeTaskMasterConfig()
        assert get_model_name(config, "sonnet") == "claude-sonnet-4-5-20250929"
        assert get_model_name(config, "SONNET") == "claude-sonnet-4-5-20250929"

    def test_get_model_name_opus(self) -> None:
        """Test get_model_name returns correct model for opus."""
        config = ClaudeTaskMasterConfig()
        assert get_model_name(config, "opus") == "claude-opus-4-5-20251101"
        assert get_model_name(config, "OPUS") == "claude-opus-4-5-20251101"

    def test_get_model_name_haiku(self) -> None:
        """Test get_model_name returns correct model for haiku."""
        config = ClaudeTaskMasterConfig()
        assert get_model_name(config, "haiku") == "claude-haiku-4-5-20251001"
        assert get_model_name(config, "HAIKU") == "claude-haiku-4-5-20251001"

    def test_get_model_name_custom_config(self) -> None:
        """Test get_model_name with custom model names."""
        config = ClaudeTaskMasterConfig(models=ModelConfig(sonnet="custom-sonnet-model"))
        assert get_model_name(config, "sonnet") == "custom-sonnet-model"

    def test_get_model_name_unknown_falls_back_to_sonnet(self) -> None:
        """Test get_model_name falls back to sonnet for unknown keys."""
        config = ClaudeTaskMasterConfig()
        assert get_model_name(config, "unknown") == "claude-sonnet-4-5-20250929"
        assert get_model_name(config, "invalid") == "claude-sonnet-4-5-20250929"

    def test_get_tools_for_phase_planning(self) -> None:
        """Test get_tools_for_phase returns correct tools for planning."""
        config = ClaudeTaskMasterConfig()
        tools = get_tools_for_phase(config, "planning")
        assert tools == ["Read", "Glob", "Grep", "Bash"]
        assert get_tools_for_phase(config, "PLANNING") == tools

    def test_get_tools_for_phase_verification(self) -> None:
        """Test get_tools_for_phase returns correct tools for verification."""
        config = ClaudeTaskMasterConfig()
        tools = get_tools_for_phase(config, "verification")
        assert tools == ["Read", "Glob", "Grep", "Bash"]

    def test_get_tools_for_phase_working(self) -> None:
        """Test get_tools_for_phase returns empty list for working."""
        config = ClaudeTaskMasterConfig()
        tools = get_tools_for_phase(config, "working")
        assert tools == []  # Empty means all tools allowed

    def test_get_tools_for_phase_custom_config(self) -> None:
        """Test get_tools_for_phase with custom tool configuration."""
        config = ClaudeTaskMasterConfig(
            tools=ToolsConfig(planning=["Read", "Glob"], working=["Write"])
        )
        assert get_tools_for_phase(config, "planning") == ["Read", "Glob"]
        assert get_tools_for_phase(config, "working") == ["Write"]

    def test_get_tools_for_phase_unknown_returns_empty(self) -> None:
        """Test get_tools_for_phase returns empty list for unknown phases."""
        config = ClaudeTaskMasterConfig()
        assert get_tools_for_phase(config, "unknown") == []
        assert get_tools_for_phase(config, "invalid") == []


# =============================================================================
# Configuration File Operations Tests
# =============================================================================


class TestConfigPathUtilities:
    """Tests for configuration path utility functions."""

    def test_get_state_dir_default(self, temp_dir, monkeypatch) -> None:
        """Test get_state_dir returns correct path with default cwd."""
        monkeypatch.chdir(temp_dir)
        state_dir = get_state_dir()
        assert state_dir == temp_dir / STATE_DIR_NAME
        assert state_dir.parent == temp_dir

    def test_get_state_dir_custom_working_dir(self, temp_dir) -> None:
        """Test get_state_dir with custom working directory."""
        state_dir = get_state_dir(temp_dir)
        assert state_dir == temp_dir / STATE_DIR_NAME

    def test_get_config_file_path_default(self, temp_dir, monkeypatch) -> None:
        """Test get_config_file_path returns correct path."""
        monkeypatch.chdir(temp_dir)
        config_path = get_config_file_path()
        assert config_path == temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME

    def test_get_config_file_path_custom_working_dir(self, temp_dir) -> None:
        """Test get_config_file_path with custom working directory."""
        config_path = get_config_file_path(temp_dir)
        assert config_path == temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME

    def test_config_file_exists_false(self, temp_dir) -> None:
        """Test config_file_exists returns False when file doesn't exist."""
        assert config_file_exists(temp_dir) is False

    def test_config_file_exists_true(self, temp_dir) -> None:
        """Test config_file_exists returns True when file exists."""
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("{}")
        assert config_file_exists(temp_dir) is True


class TestLoadConfigFromFile:
    """Tests for loading configuration from file."""

    def test_load_config_from_file_success(self, temp_dir) -> None:
        """Test successful loading of config from file."""
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Create a config file
        test_config = ClaudeTaskMasterConfig(models=ModelConfig(sonnet="custom-sonnet"))
        config_path.write_text(test_config.model_dump_json())

        loaded_config = load_config_from_file(config_path)
        assert loaded_config.models.sonnet == "custom-sonnet"
        assert loaded_config.version == "1.0"

    def test_load_config_from_file_not_found(self, temp_dir) -> None:
        """Test loading from non-existent file raises FileNotFoundError."""
        config_path = temp_dir / "non-existent" / CONFIG_FILE_NAME
        with pytest.raises(FileNotFoundError):
            load_config_from_file(config_path)

    def test_load_config_from_file_invalid_json(self, temp_dir) -> None:
        """Test loading from invalid JSON file raises json.JSONDecodeError."""
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("{ invalid json }")

        with pytest.raises(json.JSONDecodeError):
            load_config_from_file(config_path)

    def test_load_config_from_file_validation_error(self, temp_dir) -> None:
        """Test loading file with invalid schema raises ValidationError."""
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({"version": 123}))  # Invalid type

        with pytest.raises(ValidationError):
            load_config_from_file(config_path)


class TestSaveConfigToFile:
    """Tests for saving configuration to file."""

    def test_save_config_to_file_creates_directory(self, temp_dir) -> None:
        """Test save_config_to_file creates parent directory."""
        config_path = temp_dir / "new" / "nested" / CONFIG_FILE_NAME
        config = generate_default_config()

        saved_path = save_config_to_file(config, config_path, create_dir=True)

        assert saved_path.exists()
        assert saved_path.parent.exists()
        assert saved_path == config_path

    def test_save_config_to_file_default_location(self, temp_dir, monkeypatch) -> None:
        """Test save_config_to_file uses default location."""
        monkeypatch.chdir(temp_dir)
        config = generate_default_config()

        saved_path = save_config_to_file(config)

        expected_path = get_config_file_path()
        assert saved_path == expected_path
        assert saved_path.exists()

    def test_save_config_to_file_overwrites_existing(self, temp_dir) -> None:
        """Test save_config_to_file overwrites existing file."""
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("old content")

        config = ClaudeTaskMasterConfig(models=ModelConfig(sonnet="new-sonnet"))
        saved_path = save_config_to_file(config, config_path)

        loaded = load_config_from_file(saved_path)
        assert loaded.models.sonnet == "new-sonnet"

    def test_save_config_to_file_adds_trailing_newline(self, temp_dir) -> None:
        """Test save_config_to_file adds POSIX trailing newline."""
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        config = generate_default_config()
        save_config_to_file(config, config_path)

        content = config_path.read_text()
        assert content.endswith("\n")


class TestGenerateDefaultConfigFile:
    """Tests for generating default configuration file."""

    def test_generate_default_config_file_creates_file(self, temp_dir) -> None:
        """Test generate_default_config_file creates a new file."""
        config_path = get_config_file_path(temp_dir)

        returned_path = generate_default_config_file(config_path)

        assert config_path.exists()
        assert returned_path == config_path

    def test_generate_default_config_file_uses_defaults(self, temp_dir) -> None:
        """Test generated file contains default values."""
        config_path = get_config_file_path(temp_dir)

        generate_default_config_file(config_path)
        loaded = load_config_from_file(config_path)

        default = generate_default_config()
        assert loaded.version == default.version
        assert loaded.models.sonnet == default.models.sonnet

    def test_generate_default_config_file_exists_raises_error(self, temp_dir) -> None:
        """Test generate_default_config_file raises error if file exists."""
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("{}")

        with pytest.raises(FileExistsError):
            generate_default_config_file(config_path, overwrite=False)

    def test_generate_default_config_file_overwrites_if_flag_set(self, temp_dir) -> None:
        """Test generate_default_config_file overwrites with flag."""
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("old")

        generate_default_config_file(config_path, overwrite=True)

        content = config_path.read_text()
        assert content != "old"
        assert "version" in content


# =============================================================================
# Environment Variable Override Tests
# =============================================================================


class TestEnvironmentVariableOverrides:
    """Tests for environment variable override behavior."""

    def test_apply_env_overrides_anthropic_api_key(self) -> None:
        """Test env var overrides anthropic_api_key."""
        config = generate_default_config()
        assert config.api.anthropic_api_key is None

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            overridden = apply_env_overrides(config)

        assert overridden.api.anthropic_api_key == "test-key"

    def test_apply_env_overrides_anthropic_base_url(self) -> None:
        """Test env var overrides anthropic_base_url."""
        config = generate_default_config()
        original_url = config.api.anthropic_base_url

        with patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "https://custom.api.com"}):
            overridden = apply_env_overrides(config)

        assert overridden.api.anthropic_base_url == "https://custom.api.com"
        assert overridden.api.anthropic_base_url != original_url

    def test_apply_env_overrides_openrouter_api_key(self) -> None:
        """Test env var overrides openrouter_api_key."""
        config = generate_default_config()
        assert config.api.openrouter_api_key is None

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-or-key"}):
            overridden = apply_env_overrides(config)

        assert overridden.api.openrouter_api_key == "test-or-key"

    def test_apply_env_overrides_model_names(self) -> None:
        """Test env vars override model names."""
        config = generate_default_config()

        env_vars = {
            "CLAUDETM_MODEL_SONNET": "custom-sonnet",
            "CLAUDETM_MODEL_OPUS": "custom-opus",
            "CLAUDETM_MODEL_HAIKU": "custom-haiku",
        }

        with patch.dict(os.environ, env_vars):
            overridden = apply_env_overrides(config)

        assert overridden.models.sonnet == "custom-sonnet"
        assert overridden.models.opus == "custom-opus"
        assert overridden.models.haiku == "custom-haiku"

    def test_apply_env_overrides_target_branch(self) -> None:
        """Test env var overrides target_branch."""
        config = generate_default_config()
        assert config.git.target_branch == "main"

        with patch.dict(os.environ, {"CLAUDETM_TARGET_BRANCH": "develop"}):
            overridden = apply_env_overrides(config)

        assert overridden.git.target_branch == "develop"

    def test_apply_env_overrides_ignores_empty_values(self) -> None:
        """Test env var overrides ignores empty string values."""
        config = ClaudeTaskMasterConfig(api=APIConfig(anthropic_api_key="original-key"))

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            overridden = apply_env_overrides(config)

        # Empty string should not override
        assert overridden.api.anthropic_api_key == "original-key"

    def test_apply_env_overrides_multiple_vars(self) -> None:
        """Test multiple environment variable overrides."""
        config = generate_default_config()

        env_vars = {
            "ANTHROPIC_API_KEY": "test-key",
            "CLAUDETM_TARGET_BRANCH": "develop",
            "CLAUDETM_MODEL_SONNET": "custom-sonnet",
        }

        with patch.dict(os.environ, env_vars):
            overridden = apply_env_overrides(config)

        assert overridden.api.anthropic_api_key == "test-key"
        assert overridden.git.target_branch == "develop"
        assert overridden.models.sonnet == "custom-sonnet"

    def test_apply_env_overrides_does_not_mutate_original(self) -> None:
        """Test apply_env_overrides doesn't mutate the original config."""
        config = generate_default_config()

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            overridden = apply_env_overrides(config)

        # Original should be unchanged
        assert config.api.anthropic_api_key is None
        assert overridden.api.anthropic_api_key == "test-key"

    def test_get_env_overrides_returns_set_vars(self) -> None:
        """Test get_env_overrides returns only set environment variables."""
        env_vars = {
            "ANTHROPIC_API_KEY": "test-key",
            "CLAUDETM_TARGET_BRANCH": "develop",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            overrides = get_env_overrides()

        assert "ANTHROPIC_API_KEY" in overrides
        assert overrides["ANTHROPIC_API_KEY"] == "test-key"
        assert "CLAUDETM_TARGET_BRANCH" in overrides

    def test_get_env_overrides_ignores_unset_vars(self) -> None:
        """Test get_env_overrides ignores unset environment variables."""
        # Clear all our env vars
        with patch.dict(os.environ, {}, clear=True):
            overrides = get_env_overrides()

        # Should be empty or only have our vars if they're in the env
        assert "ANTHROPIC_API_KEY" not in overrides or overrides["ANTHROPIC_API_KEY"]


# =============================================================================
# ConfigManager Singleton Tests
# =============================================================================


class TestConfigManager:
    """Tests for ConfigManager singleton."""

    def test_config_manager_singleton_pattern(self) -> None:
        """Test ConfigManager implements singleton pattern."""
        reset_config()
        manager1 = ConfigManager()
        manager2 = ConfigManager()

        assert manager1 is manager2

    def test_config_manager_lazy_loads_config(self, temp_dir, monkeypatch) -> None:
        """Test ConfigManager lazy loads configuration."""
        # Clear env vars that would override file values
        monkeypatch.delenv("CLAUDETM_MODEL_SONNET", raising=False)

        reset_config()
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        test_config = ClaudeTaskMasterConfig(models=ModelConfig(sonnet="custom-sonnet"))
        config_path.write_text(test_config.model_dump_json())

        with patch("claude_task_master.core.config_loader.get_config_file_path") as mock_get_path:
            mock_get_path.return_value = config_path

            manager = ConfigManager()
            # First access should load
            config1 = manager.config
            # Second access should use cached
            config2 = manager.config

        assert config1 is config2
        assert config1.models.sonnet == "custom-sonnet"

    def test_config_manager_reset(self, temp_dir) -> None:
        """Test ConfigManager reset clears cache."""
        reset_config()
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(generate_default_config().model_dump_json())

        with patch("claude_task_master.core.config_loader.get_config_file_path") as mock_get_path:
            mock_get_path.return_value = config_path

            manager = ConfigManager()
            config1 = manager.config

            manager.reset()
            config2 = manager.config

        # Should be different instances after reset
        assert config1 is not config2

    def test_config_manager_thread_safe(self, temp_dir) -> None:
        """Test ConfigManager is thread-safe."""
        import threading

        reset_config()
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(generate_default_config().model_dump_json())

        instances = []

        def get_manager():
            instances.append(ConfigManager())

        with patch("claude_task_master.core.config_loader.get_config_file_path") as mock_get_path:
            mock_get_path.return_value = config_path

            threads = [threading.Thread(target=get_manager) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # All instances should be the same
        for instance in instances[1:]:
            assert instance is instances[0]


# =============================================================================
# Integration Tests for Config Loading and Env Overrides
# =============================================================================


class TestConfigLoaderIntegration:
    """Integration tests for config loading with env var overrides."""

    def test_get_config_loads_from_file(self, temp_dir, monkeypatch) -> None:
        """Test get_config loads from file."""
        # Clear env vars that would override file values
        monkeypatch.delenv("CLAUDETM_MODEL_SONNET", raising=False)

        monkeypatch.chdir(temp_dir)
        reset_config()

        # Create config file
        config_path = get_config_file_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        test_config = ClaudeTaskMasterConfig(models=ModelConfig(sonnet="file-sonnet"))
        config_path.write_text(test_config.model_dump_json())

        config = get_config(temp_dir)

        assert config.models.sonnet == "file-sonnet"

    def test_get_config_generates_defaults_if_missing(self, temp_dir, monkeypatch) -> None:
        """Test get_config returns defaults if file doesn't exist."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # No config file created
        config = get_config(temp_dir)

        default = generate_default_config()
        assert config.version == default.version
        assert config.models.sonnet == default.models.sonnet

    def test_get_config_applies_env_overrides(self, temp_dir, monkeypatch) -> None:
        """Test get_config applies env var overrides."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Create config file
        config_path = get_config_file_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        test_config = ClaudeTaskMasterConfig(models=ModelConfig(sonnet="file-sonnet"))
        config_path.write_text(test_config.model_dump_json())

        with patch.dict(os.environ, {"CLAUDETM_MODEL_SONNET": "env-sonnet"}):
            config = get_config(temp_dir)

        assert config.models.sonnet == "env-sonnet"

    def test_reload_config_updates_cache(self, temp_dir, monkeypatch) -> None:
        """Test reload_config updates the cached config."""
        # Clear env vars that would override file values
        monkeypatch.delenv("CLAUDETM_MODEL_SONNET", raising=False)

        reset_config()
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Create initial config
        config1 = ClaudeTaskMasterConfig(models=ModelConfig(sonnet="sonnet-v1"))
        config_path.write_text(config1.model_dump_json())

        with patch("claude_task_master.core.config_loader.get_config_file_path") as mock_get_path:
            mock_get_path.return_value = config_path

            # Load initial config
            config = get_config()
            assert config.models.sonnet == "sonnet-v1"

            # Modify file
            config2 = ClaudeTaskMasterConfig(models=ModelConfig(sonnet="sonnet-v2"))
            config_path.write_text(config2.model_dump_json())

            # Reload
            reloaded = reload_config()

        assert reloaded.models.sonnet == "sonnet-v2"

    def test_config_file_and_env_vars_together(self, temp_dir, monkeypatch) -> None:
        """Test config file and env vars work together correctly."""
        # Clear ALL env vars that could interfere, then set only the ones we want to test
        monkeypatch.delenv("CLAUDETM_MODEL_SONNET", raising=False)
        monkeypatch.delenv("CLAUDETM_TARGET_BRANCH", raising=False)
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

        reset_config()
        config_path = get_config_file_path(temp_dir)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Create config with some values
        test_config = ClaudeTaskMasterConfig(
            api=APIConfig(anthropic_base_url="https://file.api.com"),
            models=ModelConfig(sonnet="file-sonnet"),
            git=GitConfig(target_branch="file-branch"),
        )
        config_path.write_text(test_config.model_dump_json())

        # Override only some with env vars
        env_vars = {
            "CLAUDETM_MODEL_SONNET": "env-sonnet",
            "CLAUDETM_TARGET_BRANCH": "env-branch",
        }

        with patch("claude_task_master.core.config_loader.get_config_file_path") as mock_get_path:
            mock_get_path.return_value = config_path
            with patch.dict(os.environ, env_vars, clear=False):
                config = get_config()

        # Env vars should override
        assert config.models.sonnet == "env-sonnet"
        assert config.git.target_branch == "env-branch"
        # File values should remain where not overridden
        assert config.api.anthropic_base_url == "https://file.api.com"
