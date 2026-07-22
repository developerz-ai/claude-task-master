"""Tests for config_loader module — env-precedence and ConfigManager behaviour.

Focuses on:
- Environment variable precedence over file-based config (all vars, including
  CLAUDETM_MODEL_FABLE and CLAUDETM_MODEL_SONNET_1M)
- ConfigManager singleton thread safety and reset/reload cycle
- CONFIG proxy object forwards attribute access
- Path helpers (get_state_dir, get_config_file_path, config_file_exists)
- ensure_config_exists idempotency
- initialize_config creates file on first run
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

from claude_task_master.core.config import (
    ClaudeTaskMasterConfig,
    ModelConfig,
    generate_default_config,
    get_model_name,
)
from claude_task_master.core.config_loader import (
    CONFIG,
    CONFIG_FILE_NAME,
    ENV_VAR_MAPPINGS,
    STATE_DIR_NAME,
    ConfigManager,
    apply_env_overrides,
    config_file_exists,
    ensure_config_exists,
    get_config,
    get_config_file_path,
    get_env_overrides,
    get_state_dir,
    initialize_config,
    load_config_from_file,
    reload_config,
    reset_config,
    save_config_to_file,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(path: Path, data: dict) -> None:
    """Write *data* to *path* as JSON, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# ENV_VAR_MAPPINGS coverage
# ---------------------------------------------------------------------------


class TestEnvVarMappingsCompleteness:
    """Ensure every model env var is present in ENV_VAR_MAPPINGS."""

    def test_fable_mapping_present(self) -> None:
        """CLAUDETM_MODEL_FABLE must be registered."""
        names = [e for e, _ in ENV_VAR_MAPPINGS]
        assert "CLAUDETM_MODEL_FABLE" in names

    def test_sonnet_1m_mapping_present(self) -> None:
        """CLAUDETM_MODEL_SONNET_1M must be registered."""
        names = [e for e, _ in ENV_VAR_MAPPINGS]
        assert "CLAUDETM_MODEL_SONNET_1M" in names

    def test_all_model_fields_have_env_mappings(self) -> None:
        """Every field in ModelConfig must have a corresponding env-var mapping."""
        model_fields = set(ModelConfig.model_fields.keys())
        mapped_fields = {path[-1] for _, path in ENV_VAR_MAPPINGS if path[0] == "models"}
        assert model_fields == mapped_fields, (
            f"Model fields without env mapping: {model_fields - mapped_fields}"
        )


# ---------------------------------------------------------------------------
# apply_env_overrides — precedence for FABLE and SONNET_1M
# ---------------------------------------------------------------------------


class TestFableEnvOverride:
    """CLAUDETM_MODEL_FABLE overrides config.models.fable."""

    def test_fable_override_replaces_default(self) -> None:
        """Env var takes precedence over the compiled-in default."""
        config = generate_default_config()
        assert config.models.fable == "claude-fable-5"

        with patch.dict(os.environ, {"CLAUDETM_MODEL_FABLE": "my-custom-fable"}):
            overridden = apply_env_overrides(config)

        assert overridden.models.fable == "my-custom-fable"

    def test_fable_override_does_not_affect_other_models(self) -> None:
        """Setting CLAUDETM_MODEL_FABLE does not change other model keys."""
        config = generate_default_config()
        original_opus = config.models.opus

        with patch.dict(os.environ, {"CLAUDETM_MODEL_FABLE": "custom-fable"}):
            overridden = apply_env_overrides(config)

        assert overridden.models.opus == original_opus

    def test_fable_empty_env_var_is_ignored(self) -> None:
        """Empty CLAUDETM_MODEL_FABLE must not overwrite an existing value."""
        from claude_task_master.core.config import ModelConfig

        config = ClaudeTaskMasterConfig(models=ModelConfig(fable="sentinel-fable"))

        with patch.dict(os.environ, {"CLAUDETM_MODEL_FABLE": ""}):
            overridden = apply_env_overrides(config)

        assert overridden.models.fable == "sentinel-fable"

    def test_fable_override_does_not_mutate_original(self) -> None:
        """apply_env_overrides must return a new object, not mutate in place."""
        config = generate_default_config()

        with patch.dict(os.environ, {"CLAUDETM_MODEL_FABLE": "mutant-fable"}):
            overridden = apply_env_overrides(config)

        assert config.models.fable == "claude-fable-5"
        assert overridden.models.fable == "mutant-fable"


class TestSonnet1MEnvOverride:
    """CLAUDETM_MODEL_SONNET_1M overrides config.models.sonnet_1m."""

    def test_sonnet_1m_override_replaces_default(self) -> None:
        """Env var takes precedence over the compiled-in default."""
        config = generate_default_config()

        with patch.dict(os.environ, {"CLAUDETM_MODEL_SONNET_1M": "claude-custom-1m"}):
            overridden = apply_env_overrides(config)

        assert overridden.models.sonnet_1m == "claude-custom-1m"

    def test_sonnet_1m_empty_env_var_is_ignored(self) -> None:
        """Empty string must not overwrite the existing value."""
        from claude_task_master.core.config import ModelConfig

        config = ClaudeTaskMasterConfig(models=ModelConfig(sonnet_1m="my-1m-model"))

        with patch.dict(os.environ, {"CLAUDETM_MODEL_SONNET_1M": ""}):
            overridden = apply_env_overrides(config)

        assert overridden.models.sonnet_1m == "my-1m-model"

    def test_sonnet_1m_does_not_affect_sonnet(self) -> None:
        """Changing sonnet_1m must not alter the plain sonnet field."""
        config = generate_default_config()

        # Get the baseline sonnet value applying any existing env overrides,
        # then verify that adding SONNET_1M does not change it further.
        baseline_sonnet = apply_env_overrides(config).models.sonnet

        # Only add the sonnet_1m override — sonnet must stay identical.
        with patch.dict(os.environ, {"CLAUDETM_MODEL_SONNET_1M": "big-1m"}):
            overridden = apply_env_overrides(config)

        assert overridden.models.sonnet == baseline_sonnet

    def test_sonnet_1m_override_does_not_mutate_original(self) -> None:
        """Original config must remain unchanged after env override."""
        config = generate_default_config()
        original_1m = config.models.sonnet_1m

        with patch.dict(os.environ, {"CLAUDETM_MODEL_SONNET_1M": "overridden-1m"}):
            apply_env_overrides(config)

        assert config.models.sonnet_1m == original_1m


class TestEnvPrecedenceOverFileConfig:
    """Env vars beat values loaded from a config file."""

    def test_fable_env_beats_file_value(self, temp_dir: Path) -> None:
        """If config.json sets fable=X and env sets CLAUDETM_MODEL_FABLE=Y, Y wins."""
        config_path = temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME
        _write_config(config_path, {"models": {"fable": "file-fable"}})

        loaded = load_config_from_file(config_path)
        assert loaded.models.fable == "file-fable"

        with patch.dict(os.environ, {"CLAUDETM_MODEL_FABLE": "env-fable"}):
            overridden = apply_env_overrides(loaded)

        assert overridden.models.fable == "env-fable"

    def test_sonnet_1m_env_beats_file_value(self, temp_dir: Path) -> None:
        """If config.json sets sonnet_1m=X and env sets CLAUDETM_MODEL_SONNET_1M=Y, Y wins."""
        config_path = temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME
        _write_config(config_path, {"models": {"sonnet_1m": "file-1m"}})

        loaded = load_config_from_file(config_path)
        with patch.dict(os.environ, {"CLAUDETM_MODEL_SONNET_1M": "env-1m"}):
            overridden = apply_env_overrides(loaded)

        assert overridden.models.sonnet_1m == "env-1m"


# ---------------------------------------------------------------------------
# get_env_overrides
# ---------------------------------------------------------------------------


class TestGetEnvOverrides:
    """get_env_overrides returns only variables that are currently set."""

    def test_includes_fable_when_set(self) -> None:
        """CLAUDETM_MODEL_FABLE appears in result when set."""
        with patch.dict(os.environ, {"CLAUDETM_MODEL_FABLE": "fable-x"}):
            overrides = get_env_overrides()
        assert "CLAUDETM_MODEL_FABLE" in overrides
        assert overrides["CLAUDETM_MODEL_FABLE"] == "fable-x"

    def test_includes_sonnet_1m_when_set(self) -> None:
        """CLAUDETM_MODEL_SONNET_1M appears in result when set."""
        with patch.dict(os.environ, {"CLAUDETM_MODEL_SONNET_1M": "1m-x"}):
            overrides = get_env_overrides()
        assert "CLAUDETM_MODEL_SONNET_1M" in overrides

    def test_excludes_unset_vars(self) -> None:
        """Variables that are not set must not appear."""
        # Clear every var we know about so none bleed in from CI.
        env_names = [e for e, _ in ENV_VAR_MAPPINGS]
        clear = dict.fromkeys(env_names, "")
        with patch.dict(os.environ, clear):
            overrides = get_env_overrides()
        assert overrides == {}

    def test_excludes_empty_vars(self) -> None:
        """An empty string env var does not appear in overrides."""
        with patch.dict(os.environ, {"CLAUDETM_MODEL_FABLE": ""}):
            overrides = get_env_overrides()
        assert "CLAUDETM_MODEL_FABLE" not in overrides


# ---------------------------------------------------------------------------
# Path utilities
# ---------------------------------------------------------------------------


class TestPathUtilities:
    """Tests for get_state_dir, get_config_file_path, config_file_exists."""

    def test_get_state_dir_uses_cwd_when_no_arg(self, monkeypatch, temp_dir: Path) -> None:
        """Without working_dir get_state_dir resolves relative to cwd."""
        monkeypatch.chdir(temp_dir)
        assert get_state_dir() == temp_dir / STATE_DIR_NAME

    def test_get_state_dir_respects_working_dir(self, temp_dir: Path) -> None:
        """With working_dir get_state_dir returns working_dir / STATE_DIR_NAME."""
        assert get_state_dir(temp_dir) == temp_dir / STATE_DIR_NAME

    def test_get_config_file_path_returns_correct_path(self, temp_dir: Path) -> None:
        """get_config_file_path returns state_dir / config.json."""
        expected = temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME
        assert get_config_file_path(temp_dir) == expected

    def test_config_file_exists_false_when_missing(self, temp_dir: Path) -> None:
        """Returns False when config.json does not exist."""
        assert config_file_exists(temp_dir) is False

    def test_config_file_exists_true_after_creation(self, temp_dir: Path) -> None:
        """Returns True after the file is created."""
        config_path = temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME
        config_path.parent.mkdir(parents=True)
        config_path.write_text("{}")
        assert config_file_exists(temp_dir) is True


# ---------------------------------------------------------------------------
# ensure_config_exists
# ---------------------------------------------------------------------------


class TestEnsureConfigExists:
    """ensure_config_exists is idempotent and only creates the file once."""

    def test_creates_file_when_missing(self, temp_dir: Path) -> None:
        """File is created with defaults on first call."""
        path, created = ensure_config_exists(temp_dir)
        assert created is True
        assert path.exists()

    def test_returns_false_when_file_already_exists(self, temp_dir: Path) -> None:
        """Second call returns was_created=False."""
        ensure_config_exists(temp_dir)
        _, created = ensure_config_exists(temp_dir)
        assert created is False

    def test_created_file_is_valid_json(self, temp_dir: Path) -> None:
        """The generated file must be parseable as JSON."""
        path, _ = ensure_config_exists(temp_dir)
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    def test_does_not_overwrite_existing_file(self, temp_dir: Path) -> None:
        """Content written before the call must survive the second call."""
        config_path = temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME
        config_path.parent.mkdir(parents=True)
        config_path.write_text('{"marker": true}')

        ensure_config_exists(temp_dir)

        data = json.loads(config_path.read_text())
        assert data.get("marker") is True


# ---------------------------------------------------------------------------
# initialize_config
# ---------------------------------------------------------------------------


class TestInitializeConfig:
    """initialize_config creates a default file when none exists."""

    def test_creates_config_file_on_first_run(self, temp_dir: Path) -> None:
        """The file is created if absent."""
        reset_config()
        initialize_config(temp_dir)
        assert config_file_exists(temp_dir)

    def test_returns_config_object(self, temp_dir: Path) -> None:
        """Return value is a ClaudeTaskMasterConfig."""
        reset_config()
        cfg = initialize_config(temp_dir)
        assert isinstance(cfg, ClaudeTaskMasterConfig)

    def test_env_overrides_applied_after_init(self, temp_dir: Path) -> None:
        """Env vars still beat the newly generated file's values."""
        reset_config()
        with patch.dict(os.environ, {"CLAUDETM_MODEL_FABLE": "init-fable"}):
            cfg = initialize_config(temp_dir)
        assert cfg.models.fable == "init-fable"


# ---------------------------------------------------------------------------
# ConfigManager singleton
# ---------------------------------------------------------------------------


class TestConfigManagerSingleton:
    """ConfigManager must be a proper singleton."""

    def test_same_instance_returned(self) -> None:
        """Two calls to ConfigManager() must return the same object."""
        mgr1 = ConfigManager()
        mgr2 = ConfigManager()
        assert mgr1 is mgr2

    def test_reset_clears_cached_config(self, temp_dir: Path) -> None:
        """After reset(), the next .config access reloads from disk."""
        mgr = ConfigManager()
        mgr.reset()
        # Access loads from disk (uses default since no file present in cwd)
        cfg = mgr.config
        assert isinstance(cfg, ClaudeTaskMasterConfig)

    def test_reload_with_working_dir_picks_up_file(self, temp_dir: Path) -> None:
        """Reload from a directory that has a custom config file."""
        config_path = temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME
        _write_config(config_path, {"models": {"fable": "reloaded-fable"}})

        mgr = ConfigManager()
        cfg = mgr.reload(temp_dir)
        assert cfg.models.fable == "reloaded-fable"

    def test_thread_safe_singleton_creation(self) -> None:
        """Multiple threads racing to create ConfigManager get the same object."""
        instances: list[ConfigManager] = []
        errors: list[Exception] = []

        def create() -> None:
            try:
                instances.append(ConfigManager())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=create) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        first = instances[0]
        assert all(i is first for i in instances)


# ---------------------------------------------------------------------------
# get_config / reload_config / reset_config public API
# ---------------------------------------------------------------------------


class TestPublicConfigAPI:
    """Top-level get_config / reload_config / reset_config helpers."""

    def test_get_config_returns_config_object(self) -> None:
        """get_config() always returns a ClaudeTaskMasterConfig."""
        reset_config()
        cfg = get_config()
        assert isinstance(cfg, ClaudeTaskMasterConfig)

    def test_reset_then_get_returns_fresh_config(self, temp_dir: Path) -> None:
        """After reset, get_config returns a config — potentially with different source.

        We write a haiku model name to the file and then clear the env var that
        would override it (CLAUDETM_MODEL_HAIKU may be set in the environment),
        so we can assert the file value is used.
        """
        config_path = temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME
        _write_config(config_path, {"models": {"haiku": "fresh-haiku"}})

        reset_config()
        # Ensure CLAUDETM_MODEL_HAIKU is absent so it doesn't shadow the file.
        env = {k: v for k, v in os.environ.items() if k != "CLAUDETM_MODEL_HAIKU"}
        with patch.dict(os.environ, env, clear=True):
            cfg = get_config(temp_dir)
        assert cfg.models.haiku == "fresh-haiku"

    def test_reload_config_reflects_env_overrides(self, temp_dir: Path) -> None:
        """reload_config applies env overrides on top of file values."""
        config_path = temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME
        _write_config(config_path, {"models": {"fable": "file-fable"}})

        with patch.dict(os.environ, {"CLAUDETM_MODEL_FABLE": "env-fable"}):
            cfg = reload_config(temp_dir)

        assert cfg.models.fable == "env-fable"


# ---------------------------------------------------------------------------
# CONFIG proxy object
# ---------------------------------------------------------------------------


class TestConfigProxy:
    """CONFIG proxy forwards attribute reads to the live config."""

    def test_proxy_exposes_models_attribute(self) -> None:
        """CONFIG.models is accessible and has the expected fields."""
        reset_config()
        models = CONFIG.models
        assert hasattr(models, "sonnet")
        assert hasattr(models, "opus")
        assert hasattr(models, "fable")
        assert hasattr(models, "haiku")
        assert hasattr(models, "sonnet_1m")

    def test_proxy_fable_reflects_env_override(self, temp_dir: Path) -> None:
        """CONFIG.models.fable mirrors an active env override."""
        reset_config()
        with patch.dict(os.environ, {"CLAUDETM_MODEL_FABLE": "proxy-fable"}):
            reload_config(temp_dir)
            # The proxy always delegates to the live manager config.
            # Force a fresh load so we capture the env-override value.
            mgr = ConfigManager()
            mgr.reload(temp_dir)
            cfg = mgr.config
        assert cfg.models.fable == "proxy-fable"

    def test_proxy_repr_is_non_empty(self) -> None:
        """repr(CONFIG) should return a non-empty string."""
        reset_config()
        assert repr(CONFIG)


# ---------------------------------------------------------------------------
# save_config_to_file round-trip
# ---------------------------------------------------------------------------


class TestSaveLoadRoundTrip:
    """Saving then loading must preserve all model fields."""

    def test_round_trip_preserves_fable(self, temp_dir: Path) -> None:
        """fable model name survives save → load."""
        from claude_task_master.core.config import ModelConfig

        cfg = ClaudeTaskMasterConfig(models=ModelConfig(fable="round-trip-fable"))
        config_path = temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME
        save_config_to_file(cfg, config_path)
        loaded = load_config_from_file(config_path)
        assert loaded.models.fable == "round-trip-fable"

    def test_round_trip_preserves_sonnet_1m(self, temp_dir: Path) -> None:
        """sonnet_1m model name survives save → load."""
        from claude_task_master.core.config import ModelConfig

        cfg = ClaudeTaskMasterConfig(models=ModelConfig(sonnet_1m="round-trip-1m"))
        config_path = temp_dir / STATE_DIR_NAME / CONFIG_FILE_NAME
        save_config_to_file(cfg, config_path)
        loaded = load_config_from_file(config_path)
        assert loaded.models.sonnet_1m == "round-trip-1m"


# ---------------------------------------------------------------------------
# Active-profile model/context overrides (regression)
# ---------------------------------------------------------------------------


_PROFILE_MODEL_ENV = [
    "CLAUDETM_MODEL_OPUS",
    "CLAUDETM_MODEL_SONNET",
    "CLAUDETM_MODEL_FABLE",
    "CLAUDETM_MODEL_HAIKU",
    "CLAUDETM_MODEL_SONNET_1M",
    "CLAUDETM_CONTEXT_OPUS",
    "CLAUDETM_CONTEXT_SONNET",
]


def _clear_model_env(monkeypatch) -> None:
    """Strip ambient CLAUDETM_MODEL_*/CONTEXT_* so real-env can't shadow the profile."""
    for var in _PROFILE_MODEL_ENV:
        monkeypatch.delenv(var, raising=False)


class TestProfileModelOverrides:
    """Regression: an active profile's model/context overrides must reach config.

    Previously env_for_profile injected CLAUDETM_MODEL_* only into the SDK
    subprocess env (which the bundled CLI ignores), never into the os.environ
    that apply_env_overrides reads — so ModelConfig stayed at its claude-*
    default and the run printed/used e.g. claude-sonnet-5 instead of the
    profile's model. apply_env_overrides now consults the active profile too.
    """

    def test_active_profile_model_override_reaches_config(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The exact bug: an api-key profile must change what get_model_name returns."""
        _clear_model_env(monkeypatch)
        from claude_task_master.core.profiles import ProfileManager

        base = tmp_path / ".claudetm"
        ProfileManager(base_dir=base).add(
            "kimi",
            "api-key",
            api_key="sk-1",
            base_url="https://api.kimi.com/coding",
            models={"opus": "k3", "sonnet": "k3", "haiku": "kimi-for-coding-highspeed"},
        )
        monkeypatch.setenv("CLAUDETM_HOME", str(base))
        monkeypatch.delenv("CLAUDETM_PROFILE", raising=False)

        cfg = apply_env_overrides(generate_default_config())
        # Named tiers override...
        assert cfg.models.opus == "k3"
        assert cfg.models.sonnet == "k3"
        # ...and the omitted 1M/debugging tier inherits sonnet — the line that
        # used to print "Using model: sonnet_1m (claude-sonnet-5)".
        assert cfg.models.sonnet_1m == "k3"
        assert get_model_name(cfg, "sonnet_1m") == "k3"

    def test_active_profile_context_override_reaches_config(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Sibling bug: profile context_windows also never reached config before."""
        _clear_model_env(monkeypatch)
        from claude_task_master.core.profiles import ProfileManager

        base = tmp_path / ".claudetm"
        ProfileManager(base_dir=base).add(
            "zai",
            "api-key",
            api_key="sk-1",
            models={"opus": "glm-5.2"},
            context_windows={"opus": 128000},
        )
        monkeypatch.setenv("CLAUDETM_HOME", str(base))
        monkeypatch.delenv("CLAUDETM_PROFILE", raising=False)

        cfg = apply_env_overrides(generate_default_config())
        assert cfg.context_windows.opus == 128000

    def test_real_env_wins_over_profile(self, tmp_path: Path, monkeypatch) -> None:
        _clear_model_env(monkeypatch)
        from claude_task_master.core.profiles import ProfileManager

        base = tmp_path / ".claudetm"
        ProfileManager(base_dir=base).add(
            "kimi", "api-key", api_key="sk-1", models={"sonnet": "k3"}
        )
        monkeypatch.setenv("CLAUDETM_HOME", str(base))
        monkeypatch.delenv("CLAUDETM_PROFILE", raising=False)
        monkeypatch.setenv("CLAUDETM_MODEL_SONNET", "env-wins")

        cfg = apply_env_overrides(generate_default_config())
        assert cfg.models.sonnet == "env-wins"

    def test_no_profile_keeps_defaults(self, tmp_path: Path, monkeypatch) -> None:
        _clear_model_env(monkeypatch)
        monkeypatch.setenv("CLAUDETM_HOME", str(tmp_path / "empty"))
        monkeypatch.delenv("CLAUDETM_PROFILE", raising=False)

        cfg = apply_env_overrides(generate_default_config())
        assert cfg.models.sonnet_1m == "claude-sonnet-5"
        assert cfg.models.opus == "claude-opus-4-8"
