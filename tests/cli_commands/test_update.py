"""Unit tests for cli_commands/update.py module.

Tests the self-update command: PyPI version lookup, installer selection,
and the update/--check flows.
"""

from unittest.mock import MagicMock, patch

import pytest
import typer

from claude_task_master import __version__
from claude_task_master.cli_commands import update

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_console():
    """Mock the rich console."""
    with patch.object(update, "console") as mock:
        yield mock


# =============================================================================
# get_latest_version
# =============================================================================


class TestGetLatestVersion:
    def test_returns_version_from_pypi(self) -> None:
        response = MagicMock()
        response.json.return_value = {"info": {"version": "9.9.9"}}
        with patch.object(update.httpx, "get", return_value=response):
            assert update.get_latest_version() == "9.9.9"

    def test_returns_none_on_network_error(self) -> None:
        with patch.object(update.httpx, "get", side_effect=Exception("boom")):
            assert update.get_latest_version() is None

    def test_returns_none_on_malformed_response(self) -> None:
        response = MagicMock()
        response.json.return_value = {}
        with patch.object(update.httpx, "get", return_value=response):
            assert update.get_latest_version() is None


# =============================================================================
# build_update_command
# =============================================================================


class TestBuildUpdateCommand:
    def test_prefers_uv(self) -> None:
        with patch.object(update.shutil, "which", return_value="/usr/bin/uv"):
            command = update.build_update_command()
        assert command == [
            "uv",
            "tool",
            "install",
            "--force",
            "--reinstall",
            "claude-task-master",
        ]

    def test_falls_back_to_pipx(self) -> None:
        def which(name: str) -> str | None:
            return "/usr/bin/pipx" if name == "pipx" else None

        with patch.object(update.shutil, "which", side_effect=which):
            command = update.build_update_command()
        assert command == ["pipx", "install", "--force", "claude-task-master"]

    def test_none_when_no_installer(self) -> None:
        with patch.object(update.shutil, "which", return_value=None):
            assert update.build_update_command() is None


# =============================================================================
# update command
# =============================================================================


class TestUpdateCommand:
    def test_check_only_does_not_install(self, mock_console) -> None:
        with (
            patch.object(update, "get_latest_version", return_value="999.0.0"),
            patch.object(update.subprocess, "run") as mock_run,
            pytest.raises(typer.Exit) as exc_info,
        ):
            update.update(check=True)
        assert exc_info.value.exit_code == 0
        mock_run.assert_not_called()

    def test_up_to_date_skips_install(self, mock_console) -> None:
        with (
            patch.object(update, "get_latest_version", return_value=__version__),
            patch.object(update.subprocess, "run") as mock_run,
        ):
            update.update(check=False)
        mock_run.assert_not_called()

    def test_runs_installer_when_newer_version(self, mock_console) -> None:
        result = MagicMock(returncode=0)
        with (
            patch.object(update, "get_latest_version", return_value="999.0.0"),
            patch.object(update.subprocess, "run", return_value=result) as mock_run,
            patch.object(update.shutil, "which", return_value="/usr/bin/uv"),
        ):
            update.update(check=False)
        mock_run.assert_called_once()
        assert mock_run.call_args.args[0][:3] == ["uv", "tool", "install"]

    def test_installs_even_when_pypi_unreachable(self, mock_console) -> None:
        result = MagicMock(returncode=0)
        with (
            patch.object(update, "get_latest_version", return_value=None),
            patch.object(update.subprocess, "run", return_value=result) as mock_run,
            patch.object(update.shutil, "which", return_value="/usr/bin/uv"),
        ):
            update.update(check=False)
        mock_run.assert_called_once()

    def test_exits_when_no_installer_found(self, mock_console) -> None:
        with (
            patch.object(update, "get_latest_version", return_value="999.0.0"),
            patch.object(update.shutil, "which", return_value=None),
            pytest.raises(typer.Exit) as exc_info,
        ):
            update.update(check=False)
        assert exc_info.value.exit_code == 1

    def test_propagates_installer_failure(self, mock_console) -> None:
        result = MagicMock(returncode=3)
        with (
            patch.object(update, "get_latest_version", return_value="999.0.0"),
            patch.object(update.subprocess, "run", return_value=result),
            patch.object(update.shutil, "which", return_value="/usr/bin/uv"),
            pytest.raises(typer.Exit) as exc_info,
        ):
            update.update(check=False)
        assert exc_info.value.exit_code == 3


# =============================================================================
# register_update_command
# =============================================================================


class TestRegister:
    def test_registers_update(self) -> None:
        app = typer.Typer()
        update.register_update_command(app)
        names = [
            cmd.callback.__name__ for cmd in app.registered_commands if cmd.callback is not None
        ]
        assert "update" in names
