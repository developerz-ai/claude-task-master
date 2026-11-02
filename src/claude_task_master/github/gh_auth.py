"""Resolve and isolate the GitHub credential every ``gh`` invocation uses.

The agent's GitHub credential is *injected per run* by the deployment. It is
never read from disk, never taken from a personal ``gh`` login, and never
persisted by claudetm. This module is the single place that resolves it and
builds the environment overlay every ``gh`` subprocess runs with:

``GH_TOKEN``
    The resolved credential, so ``gh`` authenticates as the bot account the
    token belongs to instead of as whatever login the host happens to have.
    ``GH_TOKEN`` is gh's own standard variable, so git's gh-backed credential
    helper and the agent's own ``gh`` calls authenticate the same way.

``GH_CONFIG_DIR``
    A claudetm-owned, empty, private directory (``<CLAUDETM_HOME or
    ~/.claudetm>/gh``). Pointing ``gh`` at it means the operator's
    ``~/.config/gh`` is never read and a personal login can never take over an
    agent run.

Both are set **only when a credential was injected**. With no credential the
environment is left exactly as it was, and that is deliberate:

- a developer host keeps working with its own personal ``gh`` login — the
  flow that works today, unchanged;
- a container has no personal login to fall back to (the image points
  ``GH_CONFIG_DIR`` at the same claudetm-owned directory), so ``gh`` fails and
  claudetm fails closed, naming the environment variable that carries the
  credential.

The credential is never logged, never written to disk and never placed in an
exception message: every message names the environment variable instead.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from .exceptions import GitHubAuthError

# Environment variables that may carry the injected credential, in priority
# order. ``CLAUDETM_GITHUB_TOKEN`` is claudetm's own name for it, ``GH_TOKEN``
# is gh's standard one (and the name the resolved value is passed on as), and
# ``GITHUB_TOKEN`` is accepted because that is what several CI systems inject.
TOKEN_ENV_VARS: tuple[str, ...] = ("CLAUDETM_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")

# The variable the resolved credential is handed to the child process as.
GH_TOKEN_ENV_VAR = "GH_TOKEN"

# The variable that redirects gh's config directory away from the operator's.
GH_CONFIG_DIR_ENV_VAR = "GH_CONFIG_DIR"

# Base directory for claudetm-owned state (same convention as the profile
# registry): ``CLAUDETM_HOME`` overrides ``~/.claudetm``.
HOME_ENV_VAR = "CLAUDETM_HOME"

# Directory name under the base directory used as gh's config directory.
GH_CONFIG_DIR_NAME = "gh"

# The operator-facing hint. It names the variables; it never carries a value.
CREDENTIAL_HINT = (
    "Set the GH_TOKEN (or CLAUDETM_GITHUB_TOKEN) environment variable to a "
    "repository-scoped token for the agent."
)


def _environ(env: Mapping[str, str] | None) -> Mapping[str, str]:
    """Return the environment to read from (the process env by default)."""
    return os.environ if env is None else env


def credential_source(env: Mapping[str, str] | None = None) -> str | None:
    """Return the name of the variable carrying the credential, if any.

    Args:
        env: Environment to read from. Defaults to the process environment.

    Returns:
        The variable name (``CLAUDETM_GITHUB_TOKEN``, ``GH_TOKEN`` or
        ``GITHUB_TOKEN``), or None when no credential was injected.
    """
    environ = _environ(env)
    for var in TOKEN_ENV_VARS:
        if (environ.get(var) or "").strip():
            return var
    return None


def resolve_github_token(env: Mapping[str, str] | None = None) -> str | None:
    """Return the injected GitHub credential, or None when none was injected.

    The credential is read from the environment at call time — it is never
    cached, never persisted and never logged.

    Args:
        env: Environment to read from. Defaults to the process environment.

    Returns:
        The credential, or None when no credential was injected.
    """
    environ = _environ(env)
    for var in TOKEN_ENV_VARS:
        value = (environ.get(var) or "").strip()
        if value:
            return value
    return None


def gh_config_dir(env: Mapping[str, str] | None = None) -> Path:
    """Return the claudetm-owned directory gh is pointed at.

    Args:
        env: Environment to read from. Defaults to the process environment.

    Returns:
        ``<CLAUDETM_HOME or ~/.claudetm>/gh`` — never the operator's
        ``~/.config/gh``.
    """
    environ = _environ(env)
    base = (environ.get(HOME_ENV_VAR) or "").strip()
    root = Path(base).expanduser() if base else Path.home() / ".claudetm"
    return root / GH_CONFIG_DIR_NAME


def build_gh_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the environment overlay every ``gh`` subprocess runs with.

    Args:
        env: Environment to read from. Defaults to the process environment.

    Returns:
        ``GH_TOKEN`` plus ``GH_CONFIG_DIR`` pointing at the claudetm-owned
        directory — empty when no credential was injected, so the ambient
        environment (a developer host's own ``gh`` login) keeps working.
    """
    token = resolve_github_token(env)
    if token is None:
        return {}

    config_dir = gh_config_dir(env)
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        config_dir.chmod(0o700)
    except OSError:
        # A directory we cannot create is a gh failure to report, never a
        # reason to fall back to the operator's ~/.config/gh.
        pass

    return {
        GH_TOKEN_ENV_VAR: token,
        GH_CONFIG_DIR_ENV_VAR: str(config_dir),
    }


def gh_subprocess_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the full environment a ``gh`` subprocess runs with.

    Args:
        env: Environment to read from. Defaults to the process environment.

    Returns:
        The process environment with the agent-credential overlay applied.
    """
    environ = _environ(env)
    return {**environ, **build_gh_env(env)}


def missing_credential_error(
    command: list[str] | None = None, exit_code: int | None = None
) -> GitHubAuthError:
    """Build the fail-closed auth error: names the env var, never a value.

    Args:
        command: The command that failed, for the exception's context.
        exit_code: The command's exit code, for the exception's context.

    Returns:
        The exception to raise.
    """
    return GitHubAuthError(
        f"gh CLI is not authenticated: no GitHub credential was injected. {CREDENTIAL_HINT}",
        command=command,
        exit_code=exit_code,
    )


def require_github_token(
    env: Mapping[str, str] | None = None,
    *,
    command: list[str] | None = None,
    exit_code: int | None = None,
) -> str:
    """Return the injected credential, or fail closed naming the env var.

    Args:
        env: Environment to read from. Defaults to the process environment.
        command: The command that failed, for the exception's context.
        exit_code: The command's exit code, for the exception's context.

    Returns:
        The credential.

    Raises:
        GitHubAuthError: No credential was injected.
    """
    token = resolve_github_token(env)
    if token is None:
        raise missing_credential_error(command=command, exit_code=exit_code)
    return token


def redact_token(text: str, env: Mapping[str, str] | None = None) -> str:
    """Replace any injected credential value in ``text`` with a placeholder.

    Used on text that came back from ``gh`` before it reaches a log line or an
    exception message: the credential must never be printed, not even by
    accident.

    Args:
        text: The text to scrub.
        env: Environment to read from. Defaults to the process environment.

    Returns:
        The text with every credential value replaced by ``***``.
    """
    if not text:
        return text
    environ = _environ(env)
    for var in TOKEN_ENV_VARS:
        value = (environ.get(var) or "").strip()
        if value:
            text = text.replace(value, "***")
    return text


__all__ = [
    "CREDENTIAL_HINT",
    "GH_CONFIG_DIR_ENV_VAR",
    "GH_CONFIG_DIR_NAME",
    "GH_TOKEN_ENV_VAR",
    "HOME_ENV_VAR",
    "TOKEN_ENV_VARS",
    "build_gh_env",
    "credential_source",
    "gh_config_dir",
    "gh_subprocess_env",
    "missing_credential_error",
    "redact_token",
    "require_github_token",
    "resolve_github_token",
]
