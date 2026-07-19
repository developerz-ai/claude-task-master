"""Tests for the profile manager and runtime env resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_task_master.core.profiles import (
    PROFILE_ENV_VAR,
    Profile,
    ProfileError,
    ProfileExistsError,
    ProfileManager,
    ProfileNotFoundError,
    ProfileValidationError,
    env_for_profile,
    resolve_runtime_env,
)


@pytest.fixture
def manager(tmp_path: Path) -> ProfileManager:
    """A ProfileManager rooted at an isolated temp directory."""
    return ProfileManager(base_dir=tmp_path / ".claudetm")


# =============================================================================
# add / list / get / use / remove
# =============================================================================


class TestProfileLifecycle:
    def test_empty_registry(self, manager: ProfileManager) -> None:
        assert manager.list() == []
        assert manager.active_name() is None

    def test_add_oauth_creates_config_dir(self, manager: ProfileManager) -> None:
        profile = manager.add("work", "oauth")
        assert profile.type == "oauth"
        assert profile.config_dir is not None
        assert Path(profile.config_dir).is_dir()

    def test_first_profile_becomes_active(self, manager: ProfileManager) -> None:
        manager.add("work", "oauth")
        assert manager.active_name() == "work"

    def test_second_profile_does_not_steal_active(self, manager: ProfileManager) -> None:
        manager.add("work", "oauth")
        manager.add("personal", "oauth")
        assert manager.active_name() == "work"

    def test_add_api_key_profile(self, manager: ProfileManager) -> None:
        profile = manager.add(
            "zai", "api-key", api_key="sk-test-123", base_url="https://api.z.ai/api/anthropic"
        )
        assert profile.config_dir is None
        assert profile.api_key == "sk-test-123"
        assert profile.base_url == "https://api.z.ai/api/anthropic"

    def test_add_duplicate_raises(self, manager: ProfileManager) -> None:
        manager.add("work", "oauth")
        with pytest.raises(ProfileExistsError):
            manager.add("work", "oauth")

    def test_add_api_key_without_key_raises(self, manager: ProfileManager) -> None:
        with pytest.raises(ProfileValidationError):
            manager.add("zai", "api-key")

    def test_list_sorted(self, manager: ProfileManager) -> None:
        manager.add("zebra", "oauth")
        manager.add("alpha", "oauth")
        assert [p.name for p in manager.list()] == ["alpha", "zebra"]

    def test_get_missing_raises(self, manager: ProfileManager) -> None:
        with pytest.raises(ProfileNotFoundError):
            manager.get("nope")

    def test_use_sets_active(self, manager: ProfileManager) -> None:
        manager.add("work", "oauth")
        manager.add("personal", "oauth")
        manager.use("personal")
        assert manager.active_name() == "personal"

    def test_use_missing_raises(self, manager: ProfileManager) -> None:
        with pytest.raises(ProfileNotFoundError):
            manager.use("nope")

    def test_remove_clears_active(self, manager: ProfileManager) -> None:
        manager.add("work", "oauth")
        manager.remove("work", force=True)
        assert manager.active_name() is None
        assert manager.list() == []

    def test_remove_active_profile_raises_without_force(self, manager: ProfileManager) -> None:
        manager.add("work", "oauth")
        assert manager.active_name() == "work"
        with pytest.raises(ProfileError, match="Cannot remove active profile"):
            manager.remove("work")

    def test_remove_keeps_other_active(self, manager: ProfileManager) -> None:
        manager.add("work", "oauth")
        manager.add("personal", "oauth")
        manager.use("personal")
        manager.remove("work")
        assert manager.active_name() == "personal"

    def test_remove_missing_raises(self, manager: ProfileManager) -> None:
        with pytest.raises(ProfileNotFoundError):
            manager.remove("nope")

    def test_persistence_across_managers(self, tmp_path: Path) -> None:
        base = tmp_path / ".claudetm"
        ProfileManager(base_dir=base).add("work", "oauth")
        # A fresh manager pointed at the same dir sees the saved profile.
        assert ProfileManager(base_dir=base).active_name() == "work"


# =============================================================================
# env resolution
# =============================================================================


class TestEnvForProfile:
    def test_oauth_emits_config_dir(self) -> None:
        p = Profile(name="work", type="oauth", config_dir="/tmp/work")
        assert env_for_profile(p) == {"CLAUDE_CONFIG_DIR": "/tmp/work"}

    def test_api_key_emits_anthropic_env(self) -> None:
        p = Profile(name="zai", type="api-key", api_key="sk-1", base_url="https://x")
        assert env_for_profile(p) == {
            "ANTHROPIC_API_KEY": "sk-1",
            "ANTHROPIC_BASE_URL": "https://x",
        }

    def test_api_key_without_base_url(self) -> None:
        p = Profile(name="zai", type="api-key", api_key="sk-1")
        assert env_for_profile(p) == {"ANTHROPIC_API_KEY": "sk-1"}

    def test_oauth_without_config_dir_is_empty(self) -> None:
        p = Profile(name="x", type="oauth")
        assert env_for_profile(p) == {}


class TestResolveRuntimeEnv:
    def test_no_registry_returns_empty(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("CLAUDETM_HOME", str(tmp_path / "missing"))
        monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
        assert resolve_runtime_env() == {}

    def test_active_profile_resolved(self, tmp_path: Path, monkeypatch) -> None:
        base = tmp_path / ".claudetm"
        ProfileManager(base_dir=base).add(
            "zai", "api-key", api_key="sk-active", base_url="https://api.z.ai"
        )
        monkeypatch.setenv("CLAUDETM_HOME", str(base))
        monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
        env = resolve_runtime_env()
        assert env["ANTHROPIC_API_KEY"] == "sk-active"
        assert env["ANTHROPIC_BASE_URL"] == "https://api.z.ai"

    def test_env_override_wins(self, tmp_path: Path, monkeypatch) -> None:
        base = tmp_path / ".claudetm"
        mgr = ProfileManager(base_dir=base)
        mgr.add("work", "oauth")  # active
        mgr.add("zai", "api-key", api_key="sk-override")
        monkeypatch.setenv("CLAUDETM_HOME", str(base))
        monkeypatch.setenv(PROFILE_ENV_VAR, "zai")
        env = resolve_runtime_env()
        assert env == {"ANTHROPIC_API_KEY": "sk-override"}

    def test_unknown_override_raises(self, tmp_path: Path, monkeypatch) -> None:
        # An explicitly-selected but missing profile must fail fast, not
        # silently fall back to ambient ~/.claude credentials.
        base = tmp_path / ".claudetm"
        ProfileManager(base_dir=base).add("work", "oauth")
        monkeypatch.setenv("CLAUDETM_HOME", str(base))
        monkeypatch.setenv(PROFILE_ENV_VAR, "ghost")
        with pytest.raises(ProfileNotFoundError):
            resolve_runtime_env()


# =============================================================================
# safety: name validation & permissions
# =============================================================================


class TestNameValidation:
    @pytest.mark.parametrize(
        "bad",
        ["../escape", "a/b", "..", ".", "", "/abs", "with space", ".hidden"],
    )
    def test_unsafe_names_rejected(self, manager: ProfileManager, bad: str) -> None:
        with pytest.raises(ProfileValidationError):
            manager.add(bad, "oauth")

    def test_traversal_name_does_not_create_dir_outside(self, manager: ProfileManager) -> None:
        with pytest.raises(ProfileValidationError):
            manager.add("../pwned", "oauth")
        assert not (manager.profiles_dir.parent / "pwned").exists()


class TestPermissions:
    def test_registry_is_owner_only(self, manager: ProfileManager) -> None:
        manager.add("zai", "api-key", api_key="sk-secret")
        mode = manager.registry_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_base_dir_is_owner_only(self, manager: ProfileManager) -> None:
        manager.add("work", "oauth")
        assert manager.base_dir.stat().st_mode & 0o777 == 0o700

    def test_oauth_profile_home_is_owner_only(self, manager: ProfileManager) -> None:
        profile = manager.add("work", "oauth")
        assert profile.config_dir is not None
        assert Path(profile.config_dir).stat().st_mode & 0o777 == 0o700
