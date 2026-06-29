"""Tests for profile-aware CredentialManager behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_task_master.core.credentials import CredentialManager
from claude_task_master.core.profiles import ProfileManager

VALID_OAUTH = {
    "claudeAiOauth": {
        "accessToken": "tok-abc",
        "refreshToken": "ref-abc",
        "expiresAt": 9999999999000,
        "tokenType": "Bearer",
    }
}


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch):
    """Point profile storage at an empty temp dir so no real profile leaks in."""
    monkeypatch.setenv("CLAUDETM_HOME", str(tmp_path / "empty-claudetm"))
    monkeypatch.delenv("CLAUDETM_PROFILE", raising=False)
    return tmp_path


class TestExplicitConfigDir:
    def test_reads_from_given_config_dir(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "profile-home"
        config_dir.mkdir()
        (config_dir / ".credentials.json").write_text(json.dumps(VALID_OAUTH))

        manager = CredentialManager(config_dir=config_dir)
        assert manager.credentials_path == config_dir / ".credentials.json"
        assert manager.get_valid_token() == "tok-abc"

    def test_default_uses_class_constant(self) -> None:
        # With no profile active and no config_dir, falls back to the patchable
        # class attribute (default ~/.claude/.credentials.json).
        manager = CredentialManager()
        assert manager.credentials_path == CredentialManager.CREDENTIALS_PATH


class TestActiveProfileResolution:
    def test_active_oauth_profile_redirects_path(self, tmp_path: Path, monkeypatch) -> None:
        base = tmp_path / "claudetm"
        mgr = ProfileManager(base_dir=base)
        profile = mgr.add("work", "oauth")
        monkeypatch.setenv("CLAUDETM_HOME", str(base))

        cred = CredentialManager()
        assert cred.credentials_path == Path(profile.config_dir) / ".credentials.json"

    def test_active_api_key_profile_short_circuits(self, tmp_path: Path, monkeypatch) -> None:
        base = tmp_path / "claudetm"
        ProfileManager(base_dir=base).add("zai", "api-key", api_key="sk-zai")
        monkeypatch.setenv("CLAUDETM_HOME", str(base))

        cred = CredentialManager()
        # No OAuth file exists, but api-key profiles authenticate via env.
        assert cred.get_valid_token() == "sk-zai"
        assert cred.verify_credentials() is True
