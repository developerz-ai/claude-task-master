"""Tests for the configuration model.

Tests for:
- Default config generation
- Model serialization/deserialization
- Utility functions (get_model_name, get_tools_for_phase)
"""

import json

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
        with pytest.raises(ValidationError):
            ClaudeTaskMasterConfig(version=123)  # type: ignore[arg-type]


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
