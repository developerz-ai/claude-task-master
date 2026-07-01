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

        assert profile.config_dir is not None
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


def _oauth_creds(access: str, refresh: str) -> str:
    return json.dumps(
        {
            "claudeAiOauth": {
                "accessToken": access,
                "refreshToken": refresh,
                "expiresAt": 9999999999000,
                "tokenType": "Bearer",
            }
        }
    )


def _write_account(creds_path: Path, uuid: str) -> None:
    """Write the account-identity metadata (.claude.json) next to a credentials file."""
    (creds_path.parent / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"accountUuid": uuid}})
    )


class TestResyncFromLive:
    def _oauth_manager(self, tmp_path: Path, monkeypatch):
        base = tmp_path / "claudetm"
        profile = ProfileManager(base_dir=base).add("work", "oauth")
        monkeypatch.setenv("CLAUDETM_HOME", str(base))
        live = tmp_path / "live" / ".credentials.json"
        live.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", live)
        assert profile.config_dir is not None
        return CredentialManager(), Path(profile.config_dir) / ".credentials.json", live

    def test_reseeds_same_account_when_refresh_token_differs(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        cred, profile_creds, live = self._oauth_manager(tmp_path, monkeypatch)
        live.write_text(_oauth_creds("new-access", "ref-NEW"))
        profile_creds.write_text(_oauth_creds("old-access", "ref-OLD"))
        _write_account(live, "acct-1")
        _write_account(profile_creds, "acct-1")  # same account → rotated token
        assert cred.resync_from_live() is True
        assert profile_creds.read_text() == live.read_text()

    def test_noop_when_accounts_differ(self, tmp_path: Path, monkeypatch) -> None:
        cred, profile_creds, live = self._oauth_manager(tmp_path, monkeypatch)
        live.write_text(_oauth_creds("new-access", "ref-NEW"))
        profile_creds.write_text(_oauth_creds("old-access", "ref-OLD"))
        _write_account(live, "acct-LIVE")
        _write_account(profile_creds, "acct-OTHER")  # different account → must NOT clobber
        before = profile_creds.read_text()
        assert cred.resync_from_live() is False
        assert profile_creds.read_text() == before

    def test_noop_when_account_identity_unknown(self, tmp_path: Path, monkeypatch) -> None:
        cred, profile_creds, live = self._oauth_manager(tmp_path, monkeypatch)
        live.write_text(_oauth_creds("new-access", "ref-NEW"))
        profile_creds.write_text(_oauth_creds("old-access", "ref-OLD"))
        # No .claude.json anywhere → identity can't be verified → refuse.
        assert cred.resync_from_live() is False

    def test_noop_when_refresh_tokens_match(self, tmp_path: Path, monkeypatch) -> None:
        cred, profile_creds, live = self._oauth_manager(tmp_path, monkeypatch)
        live.write_text(_oauth_creds("live-access", "ref-SAME"))
        profile_creds.write_text(_oauth_creds("profile-access", "ref-SAME"))
        _write_account(live, "acct-1")
        _write_account(profile_creds, "acct-1")
        before = profile_creds.read_text()
        assert cred.resync_from_live() is False  # same refresh token → not stale
        assert profile_creds.read_text() == before

    def test_noop_when_live_missing(self, tmp_path: Path, monkeypatch) -> None:
        cred, profile_creds, live = self._oauth_manager(tmp_path, monkeypatch)
        profile_creds.write_text(_oauth_creds("a", "ref-OLD"))
        assert not live.exists()
        assert cred.resync_from_live() is False

    def test_noop_without_active_profile(self, tmp_path: Path, monkeypatch) -> None:
        live = tmp_path / "live.json"
        live.write_text(_oauth_creds("a", "ref"))
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", live)
        # isolated_home clears CLAUDETM_PROFILE and points at an empty store → no active profile.
        assert CredentialManager().resync_from_live() is False

    def test_noop_for_api_key_profile(self, tmp_path: Path, monkeypatch) -> None:
        base = tmp_path / "claudetm"
        ProfileManager(base_dir=base).add("zai", "api-key", api_key="sk-zai")
        monkeypatch.setenv("CLAUDETM_HOME", str(base))
        live = tmp_path / "live.json"
        live.write_text(_oauth_creds("a", "ref"))
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", live)
        assert CredentialManager().resync_from_live() is False
