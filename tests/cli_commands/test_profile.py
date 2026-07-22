"""Tests for cli_commands/profile.py — profile add/list/use/show/remove/login.

Coverage goals:
- profile add: oauth and api-key creation, invalid --type rejection, env-key
  fallback, ProfileError forwarding.
- profile list: empty registry, table output, active marker.
- profile use: success, unknown-profile error forwarding.
- profile show: active default, named profile, api-key masking, unknown error.
- profile remove: confirmation flow, --force/-f, active-profile guard, unknown.
- profile login: oauth launch, api-key guard, unknown-profile error, claude
  binary not found.
- register_profile_commands: wires the sub-app under the Typer app.
- _mask helper: short/long secrets, None/empty inputs.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer

from claude_task_master.cli_commands.profile import (
    _mask,
    profile_app,
    register_profile_commands,
)
from claude_task_master.core.profiles import (
    Profile,
    ProfileError,
    ProfileExistsError,
    ProfileManager,
    ProfileNotFoundError,
    ProfileValidationError,
)

# Module path for patching
_MOD = "claude_task_master.cli_commands.profile"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def manager(tmp_path: Path) -> ProfileManager:
    """Isolated ProfileManager backed by a temp directory."""
    return ProfileManager(base_dir=tmp_path / ".claudetm")


@pytest.fixture
def oauth_profile(manager: ProfileManager) -> Profile:
    """A pre-created oauth profile named 'work'."""
    return manager.add("work", "oauth")


@pytest.fixture
def api_key_profile(manager: ProfileManager) -> Profile:
    """A pre-created api-key profile named 'zai'."""
    return manager.add(
        "zai", "api-key", api_key="sk-test-key-123456789", base_url="https://api.z.ai"
    )


@pytest.fixture
def runner():
    """Typer CLI test runner."""
    from typer.testing import CliRunner

    return CliRunner()


# =============================================================================
# _mask helper
# =============================================================================


class TestMaskHelper:
    """Unit tests for the _mask secret-masking helper."""

    def test_none_returns_dim_none(self):
        """None secret → rich dim placeholder."""
        assert _mask(None) == "[dim](none)[/dim]"

    def test_empty_string_returns_dim_none(self):
        """Empty string secret → rich dim placeholder (treated as absent)."""
        assert _mask("") == "[dim](none)[/dim]"

    def test_short_secret_collapses_to_stars(self):
        """Secrets ≤10 chars collapse to '***' (no useful prefix to show)."""
        assert _mask("abc") == "***"
        assert _mask("1234567890") == "***"

    def test_long_secret_shows_prefix_suffix(self):
        """Secrets >10 chars keep first 6 and last 4 with ellipsis in between."""
        result = _mask("sk-ant-supersecret-value-here")
        assert result.startswith("sk-ant")
        assert result.endswith("here")
        assert "…" in result

    def test_eleven_char_secret_has_prefix_suffix(self):
        """An 11-char secret (boundary) shows prefix and suffix."""
        result = _mask("abcdefghijk")
        assert result == "abcdef…hijk"


# =============================================================================
# profile add
# =============================================================================


class TestProfileAdd:
    """Tests for 'claudetm profile add <name>'."""

    def test_add_oauth_profile(self, runner, tmp_path):
        """Adding an oauth profile creates it and prints confirmation."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.type = "oauth"
            profile.name = "work"
            profile.config_dir = str(tmp_path / "work")
            mock_mgr.add.return_value = profile
            mock_mgr.active_name.return_value = "work"

            result = runner.invoke(profile_app, ["add", "work"])

        assert result.exit_code == 0
        assert "work" in result.output
        assert "oauth" in result.output or "Created" in result.output

    def test_add_api_key_profile_from_env(self, runner):
        """An api-key profile reads the key from CLAUDETM_API_KEY env var."""
        import os

        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.type = "api-key"
            profile.name = "zai"
            profile.config_dir = None
            mock_mgr.add.return_value = profile
            mock_mgr.active_name.return_value = "zai"

            with patch.dict(os.environ, {"CLAUDETM_API_KEY": "sk-test-12345"}):
                result = runner.invoke(
                    profile_app,
                    ["add", "zai", "--type", "api-key"],
                )

        assert result.exit_code == 0
        assert "zai" in result.output
        # Verify the key from env was used (not prompted)
        mock_mgr.add.assert_called_once()
        call_kwargs = mock_mgr.add.call_args[1]
        assert call_kwargs.get("api_key") == "sk-test-12345"

    def test_add_invalid_type_exits_with_error(self, runner):
        """--type 'bad' is rejected before reaching ProfileManager."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            result = runner.invoke(profile_app, ["add", "x", "--type", "bad"])
            MockMgr.assert_not_called()

        assert result.exit_code == 1
        assert "Invalid --type" in result.output
        assert "oauth" in result.output
        assert "api-key" in result.output

    def test_add_profile_error_propagated(self, runner):
        """ProfileError from manager.add prints the error and exits 1."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.add.side_effect = ProfileExistsError("work")

            result = runner.invoke(profile_app, ["add", "work"])

        assert result.exit_code == 1
        assert "work" in result.output

    def test_add_validation_error_propagated(self, runner):
        """ProfileValidationError from manager.add is shown as red error."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.add.side_effect = ProfileValidationError("bad/name")

            result = runner.invoke(profile_app, ["add", "bad/name"])

        assert result.exit_code == 1

    def test_add_shows_login_hint_for_oauth(self, runner):
        """After adding an oauth profile, the login hint is shown."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.type = "oauth"
            profile.name = "myprofile"
            profile.config_dir = "/some/dir"
            mock_mgr.add.return_value = profile
            mock_mgr.active_name.return_value = "other"

            result = runner.invoke(profile_app, ["add", "myprofile"])

        assert result.exit_code == 0
        assert "login" in result.output.lower()
        assert "myprofile" in result.output

    def test_add_shows_active_message_when_becomes_active(self, runner):
        """A profile that becomes active shows the 'now active' note."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.type = "oauth"
            profile.name = "first"
            profile.config_dir = "/dir"
            mock_mgr.add.return_value = profile
            mock_mgr.active_name.return_value = "first"

            result = runner.invoke(profile_app, ["add", "first"])

        assert result.exit_code == 0
        assert "first" in result.output
        assert "active" in result.output.lower()


# =============================================================================
# profile list
# =============================================================================


class TestProfileList:
    """Tests for 'claudetm profile list'."""

    def test_list_empty_registry(self, runner):
        """An empty profile registry shows the 'no profiles' hint."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.list.return_value = []

            result = runner.invoke(profile_app, ["list"])

        assert result.exit_code == 0
        assert "No profiles" in result.output

    def test_list_shows_profiles_table(self, runner):
        """Non-empty registry renders a table with profile names and types."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            work = MagicMock(spec=Profile)
            work.name = "work"
            work.type = "oauth"
            work.config_dir = "/dir/work"
            work.base_url = None
            zai = MagicMock(spec=Profile)
            zai.name = "zai"
            zai.type = "api-key"
            zai.config_dir = None
            zai.base_url = "https://api.z.ai"
            mock_mgr.list.return_value = [work, zai]
            mock_mgr.active_name.return_value = "work"

            result = runner.invoke(profile_app, ["list"])

        assert result.exit_code == 0
        assert "work" in result.output
        assert "zai" in result.output
        assert "oauth" in result.output
        assert "api-key" in result.output

    def test_list_marks_active_profile(self, runner):
        """The active profile is marked with the '→' arrow in the table."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            p = MagicMock(spec=Profile)
            p.name = "active-one"
            p.type = "oauth"
            p.config_dir = "/dir"
            p.base_url = None
            mock_mgr.list.return_value = [p]
            mock_mgr.active_name.return_value = "active-one"

            result = runner.invoke(profile_app, ["list"])

        assert result.exit_code == 0
        assert "→" in result.output


# =============================================================================
# profile use
# =============================================================================


class TestProfileUse:
    """Tests for 'claudetm profile use <name>'."""

    def test_use_sets_active_profile(self, runner):
        """'profile use work' activates the profile and prints confirmation."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr

            result = runner.invoke(profile_app, ["use", "work"])

        assert result.exit_code == 0
        mock_mgr.use.assert_called_once_with("work")
        assert "work" in result.output

    def test_use_unknown_profile_exits_1(self, runner):
        """Using a non-existent profile forwards ProfileNotFoundError as exit 1."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.use.side_effect = ProfileNotFoundError("ghost")

            result = runner.invoke(profile_app, ["use", "ghost"])

        assert result.exit_code == 1
        assert "ghost" in result.output


# =============================================================================
# profile show
# =============================================================================


class TestProfileShow:
    """Tests for 'claudetm profile show [name]'."""

    def test_show_active_profile_by_default(self, runner):
        """Without a name argument, show displays the active profile."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.active_name.return_value = "work"
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.name = "work"
            profile.type = "oauth"
            profile.config_dir = "/dir/work"
            mock_mgr.get.return_value = profile

            result = runner.invoke(profile_app, ["show"])

        assert result.exit_code == 0
        mock_mgr.get.assert_called_once_with("work")
        assert "work" in result.output

    def test_show_named_profile(self, runner):
        """With a name argument, show displays that profile specifically."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.active_name.return_value = "work"
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.name = "zai"
            profile.type = "api-key"
            profile.base_url = "https://api.z.ai"
            profile.api_key = "sk-test-supersecret-value"
            mock_mgr.get.return_value = profile

            result = runner.invoke(profile_app, ["show", "zai"])

        assert result.exit_code == 0
        mock_mgr.get.assert_called_once_with("zai")

    def test_show_masks_api_key(self, runner):
        """API key is masked in show output (never shown in full)."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.active_name.return_value = "zai"
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.name = "zai"
            profile.type = "api-key"
            profile.base_url = "https://api.z.ai"
            profile.api_key = "sk-test-supersecret-value"
            mock_mgr.get.return_value = profile

            result = runner.invoke(profile_app, ["show", "zai"])

        assert result.exit_code == 0
        assert "supersecret" not in result.output
        assert "…" in result.output or "***" in result.output

    def test_show_no_active_no_name_exits_1(self, runner):
        """No name and no active profile → exit 1 with a helpful message."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.active_name.return_value = None

            result = runner.invoke(profile_app, ["show"])

        assert result.exit_code == 1
        assert "No profile" in result.output or "none active" in result.output.lower()

    def test_show_unknown_profile_exits_1(self, runner):
        """Requesting a non-existent profile propagates ProfileError as exit 1."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.active_name.return_value = "ghost"
            mock_mgr.get.side_effect = ProfileNotFoundError("ghost")

            result = runner.invoke(profile_app, ["show", "ghost"])

        assert result.exit_code == 1
        assert "ghost" in result.output

    def test_show_marks_active_profile(self, runner):
        """A profile that is the active one is labelled '(active)'."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.active_name.return_value = "work"
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.name = "work"
            profile.type = "oauth"
            profile.config_dir = "/dir"
            mock_mgr.get.return_value = profile

            result = runner.invoke(profile_app, ["show", "work"])

        assert result.exit_code == 0
        assert "active" in result.output.lower()

    def test_show_not_active_profile_no_active_label(self, runner):
        """A profile that is not the active one is not labelled '(active)'."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.active_name.return_value = "other"
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.name = "zai"
            profile.type = "api-key"
            profile.base_url = None
            profile.api_key = "sk-test-longenoughkey"
            mock_mgr.get.return_value = profile

            result = runner.invoke(profile_app, ["show", "zai"])

        assert result.exit_code == 0
        assert "(active)" not in result.output


# =============================================================================
# profile remove
# =============================================================================


class TestProfileRemove:
    """Tests for 'claudetm profile remove <name>'."""

    def test_remove_with_force_skips_confirmation(self, runner):
        """--force removes without confirmation prompt."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr

            result = runner.invoke(profile_app, ["remove", "work", "--force"])

        assert result.exit_code == 0
        mock_mgr.remove.assert_called_once_with("work", force=True)
        assert "Removed" in result.output

    def test_remove_short_force_flag(self, runner):
        """'-f' (short force) removes without confirmation."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr

            result = runner.invoke(profile_app, ["remove", "work", "-f"])

        assert result.exit_code == 0
        mock_mgr.remove.assert_called_once_with("work", force=True)

    def test_remove_confirmation_accepted(self, runner):
        """When user confirms, the profile is removed."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr

            result = runner.invoke(profile_app, ["remove", "work"], input="y\n")

        assert result.exit_code == 0
        mock_mgr.remove.assert_called_once_with("work", force=False)

    def test_remove_confirmation_declined_cancels(self, runner):
        """When user declines, the profile is NOT removed."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr

            result = runner.invoke(profile_app, ["remove", "work"], input="n\n")

        assert result.exit_code == 0
        mock_mgr.remove.assert_not_called()
        assert "Cancelled" in result.output

    def test_remove_active_profile_without_force_exits_1(self, runner):
        """Removing the active profile without --force propagates ProfileError."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.remove.side_effect = ProfileError(
                "Cannot remove active profile 'work'. Use --force..."
            )

            result = runner.invoke(profile_app, ["remove", "work", "--force"])

        assert result.exit_code == 1
        assert "work" in result.output

    def test_remove_unknown_profile_exits_1(self, runner):
        """Removing a non-existent profile propagates ProfileNotFoundError as exit 1."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.remove.side_effect = ProfileNotFoundError("ghost")

            result = runner.invoke(profile_app, ["remove", "ghost", "--force"])

        assert result.exit_code == 1
        assert "ghost" in result.output


# =============================================================================
# profile login
# =============================================================================


class TestProfileLogin:
    """Tests for 'claudetm profile login <name>'."""

    def test_login_launches_claude_cli(self, runner):
        """profile login runs subprocess.run(['claude']) with the profile's config dir."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.name = "work"
            profile.type = "oauth"
            profile.config_dir = "/profiles/work"
            mock_mgr.get.return_value = profile

            with patch(f"{_MOD}.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = runner.invoke(profile_app, ["login", "work"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        # CLAUDE_CONFIG_DIR must point to the profile's dir
        assert (
            kwargs.get("env", {}).get("CLAUDE_CONFIG_DIR") == "/profiles/work"
            or mock_run.call_args[1].get("env", {}).get("CLAUDE_CONFIG_DIR") == "/profiles/work"
            or "CLAUDE_CONFIG_DIR" in str(mock_run.call_args)
        )

    def test_login_api_key_profile_exits_1(self, runner):
        """login refuses api-key profiles (they have no OAuth config dir)."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.name = "zai"
            profile.type = "api-key"
            profile.config_dir = None
            mock_mgr.get.return_value = profile

            result = runner.invoke(profile_app, ["login", "zai"])

        assert result.exit_code == 1
        assert "oauth" in result.output.lower() or "not an oauth" in result.output.lower()

    def test_login_unknown_profile_exits_1(self, runner):
        """login with a non-existent profile forwards ProfileError as exit 1."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            mock_mgr.get.side_effect = ProfileNotFoundError("ghost")

            result = runner.invoke(profile_app, ["login", "ghost"])

        assert result.exit_code == 1
        assert "ghost" in result.output

    def test_login_claude_not_found_exits_1(self, runner):
        """When 'claude' binary is absent, login exits 1 with a helpful message."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.name = "work"
            profile.type = "oauth"
            profile.config_dir = "/profiles/work"
            mock_mgr.get.return_value = profile

            with patch(f"{_MOD}.subprocess.run", side_effect=FileNotFoundError):
                result = runner.invoke(profile_app, ["login", "work"])

        assert result.exit_code == 1
        assert "claude" in result.output.lower()

    def test_login_passes_returncode_as_exit(self, runner):
        """If the claude CLI exits non-zero, that code is propagated."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.name = "work"
            profile.type = "oauth"
            profile.config_dir = "/profiles/work"
            mock_mgr.get.return_value = profile

            with patch(f"{_MOD}.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=2)
                result = runner.invoke(profile_app, ["login", "work"])

        assert result.exit_code == 2

    def test_login_inherits_env_with_config_dir(self, runner):
        """The subprocess inherits the full env with CLAUDE_CONFIG_DIR added."""
        with patch(f"{_MOD}.ProfileManager") as MockMgr:
            mock_mgr = MagicMock()
            MockMgr.return_value = mock_mgr
            profile = MagicMock(spec=Profile)
            # Pydantic v2 hides fields from dir(), so a spec'd mock lacks the
            # override fields the CLI now reads; default to "no overrides".
            profile.models = None
            profile.context_windows = None
            profile.name = "work"
            profile.type = "oauth"
            profile.config_dir = "/isolated/work"
            mock_mgr.get.return_value = profile

            captured_env: dict = {}

            def capture(cmd: list[str], env: dict | None = None, **kw: object) -> MagicMock:
                if env:
                    captured_env.update(env)
                return MagicMock(returncode=0)

            with patch(f"{_MOD}.subprocess.run", side_effect=capture):
                runner.invoke(profile_app, ["login", "work"])

        assert captured_env.get("CLAUDE_CONFIG_DIR") == "/isolated/work"


# =============================================================================
# register_profile_commands
# =============================================================================


class TestRegisterProfileCommands:
    """register_profile_commands wires the profile sub-app into a Typer app."""

    def test_register_adds_profile_group(self):
        """After registration the parent app exposes a 'profile' command group."""
        app = typer.Typer()
        register_profile_commands(app)

        # The profile sub-app should be registered as a group
        group_names = [g.name for g in app.registered_groups]
        assert "profile" in group_names
