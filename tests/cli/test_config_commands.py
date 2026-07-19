"""Tests for config CLI commands - init, show, and path."""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_task_master.cli import app
from claude_task_master.core.config_loader import (
    get_config_file_path,
    reset_config,
)
from tests.cli.conftest import strip_ansi


class TestConfigInit:
    """Tests for 'claudetm config init' command."""

    def test_config_init_creates_file(self, cli_runner, temp_dir, monkeypatch):
        """Test config init creates config.json with defaults."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        result = cli_runner.invoke(app, ["config", "init"])

        assert result.exit_code == 0
        assert "Config file created" in result.output

        # Verify file was created
        config_path = get_config_file_path(temp_dir)
        assert config_path.exists()

        # Verify file contains valid JSON with expected keys
        with open(config_path) as f:
            config_data = json.load(f)
        assert "api" in config_data
        assert "models" in config_data
        assert "git" in config_data
        assert "tools" in config_data

    def test_config_init_fails_if_exists(self, cli_runner, temp_dir, monkeypatch):
        """Test config init fails if config already exists without --force."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Create config first time
        cli_runner.invoke(app, ["config", "init"])

        # Try to create again without force
        result = cli_runner.invoke(app, ["config", "init"])

        assert result.exit_code == 1
        assert "already exists" in result.output
        assert "Use --force" in result.output

    def test_config_init_force_overwrites(self, cli_runner, temp_dir, monkeypatch):
        """Test config init --force overwrites existing config."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Create config first time
        cli_runner.invoke(app, ["config", "init"])

        # Modify the existing config
        config_path = get_config_file_path(temp_dir)
        with open(config_path, "w") as f:
            f.write('{"modified": "data"}')

        # Force overwrite
        result = cli_runner.invoke(app, ["config", "init", "--force"])

        assert result.exit_code == 0
        assert "Config file created" in result.output

        # Verify it was overwritten with defaults
        with open(config_path) as f:
            config_data = json.load(f)
        assert "modified" not in config_data
        assert "api" in config_data

    def test_config_init_force_short_flag(self, cli_runner, temp_dir, monkeypatch):
        """Test config init -f short flag works."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Create config first time
        cli_runner.invoke(app, ["config", "init"])

        # Force overwrite with short flag
        result = cli_runner.invoke(app, ["config", "init", "-f"])

        assert result.exit_code == 0
        assert "Config file created" in result.output

    def test_config_init_show_displays_config(self, cli_runner, temp_dir, monkeypatch):
        """Test config init --show displays config after creation."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        result = cli_runner.invoke(app, ["config", "init", "--show"])

        assert result.exit_code == 0
        assert "Config file created" in result.output
        # Should show configuration (JSON content)
        assert "api" in result.output or '"api"' in result.output

    def test_config_init_show_short_flag(self, cli_runner, temp_dir, monkeypatch):
        """Test config init -s short flag works."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        result = cli_runner.invoke(app, ["config", "init", "-s"])

        assert result.exit_code == 0
        assert "Config file created" in result.output

    def test_config_init_creates_parent_directory(self, cli_runner, temp_dir, monkeypatch):
        """Test config init creates .claude-task-master directory if missing."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Verify directory doesn't exist
        state_dir = temp_dir / ".claude-task-master"
        assert not state_dir.exists()

        result = cli_runner.invoke(app, ["config", "init"])

        assert result.exit_code == 0
        # Verify directory and file were created
        assert state_dir.exists()
        assert (state_dir / "config.json").exists()


class TestConfigShow:
    """Tests for 'claudetm config show' command."""

    def test_config_show_displays_config(self, cli_runner, temp_dir, monkeypatch):
        """Test config show displays current configuration."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Create config first
        cli_runner.invoke(app, ["config", "init"])

        result = cli_runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        # Should show formatted configuration
        assert "Configuration" in result.output
        # JSON content should be present
        assert "api" in result.output or '"api"' in result.output

    def test_config_show_without_file_shows_defaults(self, cli_runner, temp_dir, monkeypatch):
        """Test config show shows defaults when no config file exists."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        result = cli_runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        # Should indicate defaults are being used
        assert "defaults" in result.output.lower() or "api" in result.output

    def test_config_show_raw_outputs_json(self, cli_runner, temp_dir, monkeypatch):
        """Test config show --raw outputs raw JSON."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Create config first
        cli_runner.invoke(app, ["config", "init"])

        result = cli_runner.invoke(app, ["config", "show", "--raw"])

        assert result.exit_code == 0
        # Should be valid JSON without formatting
        cleaned_output = strip_ansi(result.output).strip()
        try:
            config_data = json.loads(cleaned_output)
            assert "api" in config_data
            assert "models" in config_data
        except json.JSONDecodeError:
            pytest.fail("--raw output is not valid JSON")

    def test_config_show_raw_short_flag(self, cli_runner, temp_dir, monkeypatch):
        """Test config show -r short flag works."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        cli_runner.invoke(app, ["config", "init"])

        result = cli_runner.invoke(app, ["config", "show", "-r"])

        assert result.exit_code == 0
        cleaned_output = strip_ansi(result.output).strip()
        # Should be valid JSON
        assert cleaned_output.startswith("{")
        assert cleaned_output.endswith("}")

    def test_config_show_env_shows_overrides(self, cli_runner, temp_dir, monkeypatch):
        """Test config show --env displays environment variable overrides."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Set some environment variables
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key-123456789")
        monkeypatch.setenv("CLAUDETM_TARGET_BRANCH", "develop")

        result = cli_runner.invoke(app, ["config", "show", "--env"])

        assert result.exit_code == 0
        assert "Environment Variable Overrides" in result.output
        # Should show the env vars that are set
        assert "ANTHROPIC_API_KEY" in result.output
        assert "CLAUDETM_TARGET_BRANCH" in result.output
        assert "develop" in result.output
        # API key should be masked
        assert "test-api-key-123456789" not in result.output
        assert "..." in result.output  # Masked indicator

    def test_config_show_env_short_flag(self, cli_runner, temp_dir, monkeypatch):
        """Test config show -e short flag works."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        monkeypatch.setenv("CLAUDETM_MODEL_SONNET", "custom-sonnet")

        result = cli_runner.invoke(app, ["config", "show", "-e"])

        assert result.exit_code == 0
        assert "Environment Variable Overrides" in result.output
        assert "CLAUDETM_MODEL_SONNET" in result.output

    def test_config_show_env_no_overrides(self, cli_runner, temp_dir, monkeypatch):
        """Test config show --env when no env vars are set."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Clear all relevant env vars
        for var in [
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "OPENROUTER_API_KEY",
            "OPENROUTER_BASE_URL",
            "CLAUDETM_MODEL_SONNET",
            "CLAUDETM_MODEL_OPUS",
            "CLAUDETM_MODEL_HAIKU",
            "CLAUDETM_TARGET_BRANCH",
        ]:
            monkeypatch.delenv(var, raising=False)

        result = cli_runner.invoke(app, ["config", "show", "--env"])

        assert result.exit_code == 0
        assert "No environment variable overrides" in result.output
        # Should show available env vars table
        assert "Available environment variables" in result.output
        assert "ANTHROPIC_API_KEY" in result.output

    def test_config_show_indicates_overrides_applied(self, cli_runner, temp_dir, monkeypatch):
        """Test config show indicates when env var overrides are applied."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Set an env var
        monkeypatch.setenv("CLAUDETM_TARGET_BRANCH", "main")

        result = cli_runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        # Should indicate overrides are applied
        assert "environment variable override" in result.output.lower()
        assert "claudetm config show --env" in result.output


class TestSecretMasking:
    """Unit tests for the secret-masking helpers."""

    def test_looks_secret_matches_key_names(self):
        """Field/env names containing key/secret/token/password are secret."""
        from claude_task_master.cli_commands.config import _looks_secret

        assert _looks_secret("anthropic_api_key")
        assert _looks_secret("OPENROUTER_API_KEY")
        assert _looks_secret("webhook_secret")
        assert _looks_secret("access_token")
        assert not _looks_secret("anthropic_base_url")
        assert not _looks_secret("target_branch")

    def test_mask_secret_keeps_short_prefix(self):
        """Long secrets keep an 8-char prefix hint; short ones fully collapse."""
        from claude_task_master.cli_commands.config import _mask_secret

        assert _mask_secret("sk-ant-supersecret-value") == "sk-ant-s..."
        assert _mask_secret("short") == "***"

    def test_redact_secrets_masks_only_secret_string_leaves(self):
        """Recursion masks secret string leaves but leaves None/non-secrets intact."""
        from claude_task_master.cli_commands.config import _redact_secrets

        data: dict[str, dict[str, Any]] = {
            "api": {
                "anthropic_api_key": "sk-ant-supersecret-1234",
                "openrouter_api_key": None,
                "anthropic_base_url": "https://api.anthropic.com",
            },
            "git": {"target_branch": "main"},
        }
        redacted = _redact_secrets(data)

        assert redacted["api"]["anthropic_api_key"] == "sk-ant-s..."
        assert redacted["api"]["openrouter_api_key"] is None  # unset stays visible
        assert redacted["api"]["anthropic_base_url"] == "https://api.anthropic.com"
        assert redacted["git"]["target_branch"] == "main"
        # Original is not mutated
        assert data["api"]["anthropic_api_key"] == "sk-ant-supersecret-1234"


class TestConfigShowSecrets:
    """Tests that 'claudetm config show' masks secrets by default."""

    def test_config_show_masks_api_key(self, cli_runner, temp_dir, monkeypatch):
        """A configured API key is masked in the default (formatted) output."""
        monkeypatch.chdir(temp_dir)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecret-abcdef123456")
        reset_config()

        result = cli_runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        assert "supersecret" not in result.output
        assert "Secrets masked" in result.output

    def test_config_show_raw_masks_secrets(self, cli_runner, temp_dir, monkeypatch):
        """--raw output masks secrets too (piped JSON must not leak keys)."""
        monkeypatch.chdir(temp_dir)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecret-abcdef123456")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-anothersecret-xyz789")
        reset_config()

        result = cli_runner.invoke(app, ["config", "show", "--raw"])

        assert result.exit_code == 0
        cleaned = strip_ansi(result.output).strip()
        config_data = json.loads(cleaned)  # still valid JSON
        assert "supersecret" not in cleaned
        assert "anothersecret" not in cleaned
        assert config_data["api"]["anthropic_api_key"].endswith("...")
        assert config_data["api"]["openrouter_api_key"].endswith("...")

    def test_config_show_secrets_reveals_values(self, cli_runner, temp_dir, monkeypatch):
        """--show-secrets reveals the full key values."""
        monkeypatch.chdir(temp_dir)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecret-abcdef123456")
        reset_config()

        result = cli_runner.invoke(app, ["config", "show", "--raw", "--show-secrets"])

        assert result.exit_code == 0
        assert "sk-ant-supersecret-abcdef123456" in result.output
        # No mask hint when nothing is masked
        assert "Secrets masked" not in result.output

    def test_config_show_no_secrets_no_hint(self, cli_runner, temp_dir, monkeypatch):
        """Without any configured secret, no masking hint is shown."""
        monkeypatch.chdir(temp_dir)
        for var in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        reset_config()

        result = cli_runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        assert "Secrets masked" not in result.output

    def test_config_show_env_show_secrets_reveals(self, cli_runner, temp_dir, monkeypatch):
        """--env --show-secrets reveals the masked override value."""
        monkeypatch.chdir(temp_dir)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecret-abcdef123456")
        reset_config()

        result = cli_runner.invoke(app, ["config", "show", "--env", "--show-secrets"])

        assert result.exit_code == 0
        assert "sk-ant-supersecret-abcdef123456" in result.output


class TestConfigPath:
    """Tests for 'claudetm config path' command."""

    def test_config_path_shows_path(self, cli_runner, temp_dir, monkeypatch):
        """Test config path displays the config file path."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        result = cli_runner.invoke(app, ["config", "path"])

        assert result.exit_code == 0
        # Should show the path
        output = strip_ansi(result.output).strip()
        assert ".claude-task-master" in output
        assert "config.json" in output

    def test_config_path_output_is_pipeable(self, cli_runner, temp_dir, monkeypatch):
        """Test config path output is plain text for piping."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        result = cli_runner.invoke(app, ["config", "path"])

        assert result.exit_code == 0
        # Output should be clean path without formatting
        output = strip_ansi(result.output).strip()
        # Should be a valid path
        path = Path(output)
        assert path.name == "config.json"
        assert ".claude-task-master" in str(path)

    def test_config_path_check_file_exists(self, cli_runner, temp_dir, monkeypatch):
        """Test config path --check when file exists."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Create config file
        cli_runner.invoke(app, ["config", "init"])

        result = cli_runner.invoke(app, ["config", "path", "--check"])

        assert result.exit_code == 0
        output = strip_ansi(result.output)
        # Should show path with success indicator
        assert ".claude-task-master" in output
        assert "config.json" in output

    def test_config_path_check_file_not_exists(self, cli_runner, temp_dir, monkeypatch):
        """Test config path --check when file does not exist."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        result = cli_runner.invoke(app, ["config", "path", "--check"])

        assert result.exit_code == 1
        output = strip_ansi(result.output)
        # Should show path with warning
        assert ".claude-task-master" in output
        assert "config.json" in output
        assert "not found" in output.lower()

    def test_config_path_check_short_flag(self, cli_runner, temp_dir, monkeypatch):
        """Test config path -c short flag works."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Create config file
        cli_runner.invoke(app, ["config", "init"])

        result = cli_runner.invoke(app, ["config", "path", "-c"])

        assert result.exit_code == 0
        assert "config.json" in result.output


class TestConfigIntegration:
    """Integration tests for config commands."""

    def test_init_show_path_workflow(self, cli_runner, temp_dir, monkeypatch):
        """Test full workflow: init, show, and path commands."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # 1. Initialize config
        result = cli_runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0

        # 2. Show config
        result = cli_runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "api" in result.output

        # 3. Get path
        result = cli_runner.invoke(app, ["config", "path"])
        assert result.exit_code == 0
        assert "config.json" in result.output

        # 4. Check path exists
        result = cli_runner.invoke(app, ["config", "path", "--check"])
        assert result.exit_code == 0

    def test_config_respects_working_directory(self, cli_runner, temp_dir, monkeypatch):
        """Test config commands work in different directories."""
        # Create two different temp directories
        dir1 = temp_dir / "project1"
        dir2 = temp_dir / "project2"
        dir1.mkdir()
        dir2.mkdir()

        # Initialize in dir1
        monkeypatch.chdir(dir1)
        reset_config()
        result = cli_runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0

        # Verify it exists in dir1
        config1 = dir1 / ".claude-task-master" / "config.json"
        assert config1.exists()

        # Move to dir2, should not have config
        monkeypatch.chdir(dir2)
        reset_config()
        result = cli_runner.invoke(app, ["config", "path", "--check"])
        assert result.exit_code == 1  # Not found

        # Initialize in dir2
        result = cli_runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0

        # Verify both exist independently
        config2 = dir2 / ".claude-task-master" / "config.json"
        assert config1.exists()
        assert config2.exists()

    def test_env_vars_override_config_file(self, cli_runner, temp_dir, monkeypatch):
        """Test environment variables override config file values."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Create config
        cli_runner.invoke(app, ["config", "init"])

        # Set env var
        monkeypatch.setenv("CLAUDETM_TARGET_BRANCH", "feature-branch")

        # Show config in raw format to parse JSON
        result = cli_runner.invoke(app, ["config", "show", "--raw"])
        assert result.exit_code == 0

        # Parse the output
        cleaned_output = strip_ansi(result.output).strip()
        config_data = json.loads(cleaned_output)

        # Verify env var override is applied
        assert config_data["git"]["target_branch"] == "feature-branch"

    def test_multiple_env_overrides(self, cli_runner, temp_dir, monkeypatch):
        """Test multiple environment variable overrides work together."""
        monkeypatch.chdir(temp_dir)
        reset_config()

        # Set multiple env vars
        monkeypatch.setenv("CLAUDETM_MODEL_SONNET", "custom-sonnet-model")
        monkeypatch.setenv("CLAUDETM_MODEL_HAIKU", "custom-haiku-model")
        monkeypatch.setenv("CLAUDETM_TARGET_BRANCH", "develop")

        # Show config with env flag
        result = cli_runner.invoke(app, ["config", "show", "--env"])

        assert result.exit_code == 0
        assert "CLAUDETM_MODEL_SONNET" in result.output
        assert "CLAUDETM_MODEL_HAIKU" in result.output
        assert "CLAUDETM_TARGET_BRANCH" in result.output
        assert "custom-sonnet-model" in result.output
        assert "custom-haiku-model" in result.output
        assert "develop" in result.output
