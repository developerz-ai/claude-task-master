"""Tests for the injected agent GitHub credential (``github/gh_auth.py``).

The credential is injected per run through the environment. It has to reach
every ``gh`` subprocess as ``GH_TOKEN``, with ``GH_CONFIG_DIR`` pointing at a
claudetm-owned directory so the operator's ``~/.config/gh`` is never read — and
it must never be printed, logged or carried in an error message.

The token below is a stand-in for a real credential, not a secret. What these
tests pin is that *whatever* credential is injected stays out of the output.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.github.ci_infra import CIInfraDetector
from claude_task_master.github.ci_logs import CILogDownloader
from claude_task_master.github.ci_rerun import CIRerunner
from claude_task_master.github.client import GitHubAuthError, GitHubClient
from claude_task_master.github.gh_auth import (
    CREDENTIAL_HINT,
    GH_CONFIG_DIR_ENV_VAR,
    GH_TOKEN_ENV_VAR,
    TOKEN_ENV_VARS,
    build_gh_env,
    credential_source,
    gh_config_dir,
    gh_subprocess_env,
    redact_token,
    require_github_token,
    resolve_github_token,
)

# A stand-in credential. Nothing in this file may print it or assert on it.
TOKEN = "ghp_TESTtokenValue0123456789abcdef"


@pytest.fixture(autouse=True)
def _no_ambient_credential(monkeypatch):
    """No credential in the environment unless a test injects one."""
    for var in TOKEN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def injected_credential(monkeypatch):
    """Inject the agent credential the way the deployment does."""
    monkeypatch.setenv("CLAUDETM_GITHUB_TOKEN", TOKEN)
    return TOKEN


def _env_of(mock_run, command: list[str]) -> dict[str, str]:
    """Return the environment the subprocess call for ``command`` ran with."""
    for call in mock_run.call_args_list:
        if call.args and list(call.args[0]) == command:
            return dict(call.kwargs["env"])
    raise AssertionError(f"no subprocess call for {command}")


# =============================================================================
# Credential resolution
# =============================================================================


class TestCredentialResolution:
    """The credential comes from the environment, in a fixed order."""

    def test_claudetm_token_wins(self, monkeypatch):
        """CLAUDETM_GITHUB_TOKEN is claudetm's own name and takes priority."""
        monkeypatch.setenv("CLAUDETM_GITHUB_TOKEN", TOKEN)
        monkeypatch.setenv("GH_TOKEN", "other")
        monkeypatch.setenv("GITHUB_TOKEN", "other")
        assert resolve_github_token() == TOKEN
        assert credential_source() == "CLAUDETM_GITHUB_TOKEN"

    def test_gh_token_is_accepted(self, monkeypatch):
        """GH_TOKEN is gh's standard variable and is accepted as-is."""
        monkeypatch.setenv("GH_TOKEN", TOKEN)
        assert resolve_github_token() == TOKEN
        assert credential_source() == "GH_TOKEN"

    def test_github_token_is_accepted(self, monkeypatch):
        """GITHUB_TOKEN is what several CI systems inject."""
        monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
        assert resolve_github_token() == TOKEN
        assert credential_source() == "GITHUB_TOKEN"

    def test_no_credential_resolves_to_none(self):
        """Nothing injected means nothing resolved."""
        assert resolve_github_token() is None
        assert credential_source() is None

    def test_blank_value_is_not_a_credential(self, monkeypatch):
        """An empty variable is not a credential."""
        monkeypatch.setenv("GH_TOKEN", "   ")
        assert resolve_github_token() is None


# =============================================================================
# The environment overlay
# =============================================================================


class TestOverlay:
    """The overlay carries the token and isolates gh's config directory."""

    def test_overlay_carries_the_token(self, injected_credential):
        """The credential reaches the child as GH_TOKEN."""
        assert build_gh_env()[GH_TOKEN_ENV_VAR] == TOKEN

    def test_overlay_points_gh_at_the_claudetm_owned_directory(self, injected_credential):
        """GH_CONFIG_DIR points at claudetm's own directory."""
        overlay = build_gh_env()
        assert overlay[GH_CONFIG_DIR_ENV_VAR] == str(gh_config_dir())
        assert Path(overlay[GH_CONFIG_DIR_ENV_VAR]).name == "gh"

    def test_overlay_never_points_at_the_operator_gh_config(self, injected_credential):
        """The operator's ~/.config/gh is never handed to gh."""
        overlay = build_gh_env()
        operator_gh = Path.home() / ".config" / "gh"
        assert overlay[GH_CONFIG_DIR_ENV_VAR] != str(operator_gh)
        assert ".config/gh" not in overlay[GH_CONFIG_DIR_ENV_VAR]

    def test_config_dir_is_private_and_empty(self, injected_credential):
        """The directory is created owner-only and holds nothing."""
        build_gh_env()
        config_dir = gh_config_dir()
        assert config_dir.is_dir()
        assert oct(config_dir.stat().st_mode)[-3:] == "700"
        assert list(config_dir.iterdir()) == []

    def test_no_credential_leaves_the_environment_untouched(self):
        """Without a credential the ambient environment is used unchanged.

        That is what keeps a developer host's own ``gh`` login working; a
        container has no such login and fails closed instead.
        """
        assert build_gh_env() == {}

    def test_subprocess_env_keeps_the_rest_of_the_environment(self, injected_credential):
        """The overlay is merged into the environment, not substituted for it."""
        env = gh_subprocess_env()
        assert env[GH_TOKEN_ENV_VAR] == TOKEN
        assert env["PATH"] == os.environ["PATH"]


# =============================================================================
# Propagation into the gh subprocesses
# =============================================================================


class TestSubprocessPropagation:
    """Every gh subprocess runs with the overlay applied."""

    def test_token_reaches_the_gh_subprocess(self, injected_credential):
        """The client's gh calls carry the credential."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
            client = GitHubClient()
            client._run_gh_command(["gh", "api", "x"])

        env = _env_of(mock_run, ["gh", "api", "x"])
        assert env[GH_TOKEN_ENV_VAR] == TOKEN

    def test_gh_config_dir_reaches_the_gh_subprocess(self, injected_credential):
        """The client's gh calls carry the isolated config directory."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
            client = GitHubClient()
            client._run_gh_command(["gh", "api", "x"])

        env = _env_of(mock_run, ["gh", "api", "x"])
        assert env[GH_CONFIG_DIR_ENV_VAR] == str(gh_config_dir())

    def test_ci_infra_runs_with_the_overlay(self, injected_credential):
        """The CI-infra detector's gh calls carry the overlay."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
            CIInfraDetector("owner/repo")._jobs(123)

        env = _env_of(
            mock_run,
            [
                "gh",
                "api",
                "--paginate",
                "--jq",
                ".jobs[]",
                "repos/owner/repo/actions/runs/123/jobs",
            ],
        )
        assert env[GH_TOKEN_ENV_VAR] == TOKEN
        assert env[GH_CONFIG_DIR_ENV_VAR] == str(gh_config_dir())

    def test_ci_logs_runs_with_the_overlay(self, injected_credential):
        """The CI-log downloader's gh calls carry the overlay."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
            CILogDownloader("owner/repo").get_failed_jobs(123)

        env = _env_of(
            mock_run,
            [
                "gh",
                "api",
                "--paginate",
                "--jq",
                ".jobs[]",
                "repos/owner/repo/actions/runs/123/jobs",
            ],
        )
        assert env[GH_TOKEN_ENV_VAR] == TOKEN

    def test_ci_rerun_runs_with_the_overlay(self, injected_credential):
        """A CI re-run is authorised by the injected credential."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            assert CIRerunner("owner/repo").rerun_failed_jobs(123) is True

        env = _env_of(mock_run, ["gh", "run", "rerun", "123", "--failed", "--repo", "owner/repo"])
        assert env[GH_TOKEN_ENV_VAR] == TOKEN
        assert env[GH_CONFIG_DIR_ENV_VAR] == str(gh_config_dir())


# =============================================================================
# Failing closed
# =============================================================================


class TestFailClosed:
    """With no credential the run stops, naming the variable that carries one."""

    def test_missing_credential_fails_closed_naming_the_env_var(self):
        """A container with no credential cannot authenticate, and says why."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not logged in")
            with pytest.raises(GitHubAuthError) as exc_info:
                GitHubClient()

        message = str(exc_info.value)
        assert "not authenticated" in message
        assert "GH_TOKEN" in message
        assert "CLAUDETM_GITHUB_TOKEN" in message
        assert "gh auth login" not in message

    def test_the_message_never_carries_the_token(self, monkeypatch):
        """A rejected credential is reported without its value."""
        monkeypatch.setenv("GH_TOKEN", TOKEN)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not logged in")
            with pytest.raises(GitHubAuthError) as exc_info:
                GitHubClient()

        message = str(exc_info.value)
        assert TOKEN not in message
        assert TOKEN not in repr(exc_info.value.command)
        assert "GH_TOKEN" in message

    def test_require_github_token_raises_naming_the_env_var(self):
        """The fail-closed accessor names the variable, never a value."""
        with pytest.raises(GitHubAuthError) as exc_info:
            require_github_token()

        message = str(exc_info.value)
        assert "GH_TOKEN" in message
        assert CREDENTIAL_HINT in message

    def test_require_github_token_returns_the_injected_credential(self, injected_credential):
        """With a credential injected, the accessor hands it back."""
        assert require_github_token() == TOKEN

    def test_redact_token_removes_the_value(self, injected_credential):
        """Text that came back from gh is scrubbed before it is shown."""
        scrubbed = redact_token(f"auth failed with {TOKEN}")
        assert TOKEN not in scrubbed
        assert "***" in scrubbed

    def test_doctor_output_never_carries_the_token(self, monkeypatch, capsys):
        """The doctor reports the credential's presence, never its value."""
        from claude_task_master.utils.doctor import SystemDoctor

        monkeypatch.setenv("GH_TOKEN", TOKEN)
        doctor = SystemDoctor()
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            doctor._check_gh_cli()

        captured = capsys.readouterr()
        assert TOKEN not in captured.out
        assert TOKEN not in captured.err
        assert "GH_TOKEN" in captured.out
