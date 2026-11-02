"""Unit tests for git branch-name validation and the git command environment."""

import os
import secrets
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_task_master.core.git_branch import is_valid_branch_name, run_git
from claude_task_master.github.gh_auth import gh_config_dir

# A stand-in for the injected agent credential — not a secret. The assertions
# below compare against it without ever echoing it, so a failing test cannot
# print a credential into the CI log.
CREDENTIAL = "ghp_TESTagentCredentialValue0000"


@pytest.mark.parametrize(
    "name",
    [
        "feature/login",
        "release/v2",
        "fix-123",
        "user/task/subtask",
        "a",
        "WIP_snake_case",
    ],
)
def test_valid_names(name: str) -> None:
    assert is_valid_branch_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "",  # empty
        "@",  # bare @
        "-leading-dash",
        "/leading-slash",
        "trailing-slash/",
        "trailing-dot.",
        "feature.lock",
        "foo.lock/bar",  # nested component ending in .lock
        "a/b.lock",
        "has..dotdot",
        "has space",
        "has\ttab",
        "ctrl\x01char",
        "tilde~",
        "caret^",
        "colon:",
        "question?",
        "star*",
        "bracket[",
        "back\\slash",
        "at@{brace",
        "double//slash",
        "foo/.hidden",  # component starting with dot
        ".hidden",
    ],
)
def test_invalid_names(name: str) -> None:
    assert is_valid_branch_name(name) is False


class TestRunGitEnvironment:
    """run_git must authenticate as the injected agent credential.

    The container image's credential helper is gh-backed and gh reads
    ``GH_TOKEN``; a credential injected under the ``CLAUDETM_GITHUB_TOKEN``
    alias only reaches git when git runs with the credential overlay applied.
    """

    @pytest.fixture(autouse=True)
    def _no_ambient_credential(self, monkeypatch):
        """No credential in the environment unless a test injects one."""
        for var in ("CLAUDETM_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
            monkeypatch.delenv(var, raising=False)

    @staticmethod
    def _env_of_git_call(*args: str) -> dict[str, str]:
        """Run a git command with the subprocess layer mocked; return its env."""
        with patch("claude_task_master.core.git_branch.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["git"], 0, "", "")
            run_git(*args)
        return dict(mock_run.call_args.kwargs["env"])

    def test_injected_credential_reaches_git_as_gh_token(self, monkeypatch):
        """The credential arrives as GH_TOKEN, under whichever name it was injected."""
        monkeypatch.setenv("CLAUDETM_GITHUB_TOKEN", CREDENTIAL)

        env = self._env_of_git_call("push", "-u", "origin", "HEAD")

        # compare_digest, not ==: a failed assertion must not echo the value.
        assert secrets.compare_digest(env.get("GH_TOKEN", ""), CREDENTIAL)

    def test_gh_config_dir_is_the_claudetm_owned_one(self, monkeypatch):
        """gh is pointed at claudetm's own directory, never the operator's."""
        monkeypatch.setenv("CLAUDETM_GITHUB_TOKEN", CREDENTIAL)

        env = self._env_of_git_call("push", "-u", "origin", "HEAD")

        config_dir = env["GH_CONFIG_DIR"]
        assert config_dir == str(gh_config_dir())
        assert config_dir != str(Path.home() / ".config" / "gh")
        assert ".config/gh" not in config_dir

    def test_without_a_credential_the_environment_is_the_ambient_one(self):
        """A developer host keeps working with its own gh login."""
        env = self._env_of_git_call("status")

        assert env == dict(os.environ)
        assert "GH_TOKEN" not in env
