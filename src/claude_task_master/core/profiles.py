"""Profile Manager - named credential profiles for multi-account isolation.

A *profile* lets claudetm run under an isolated authentication context so that
multiple Claude subscriptions (or a custom Anthropic-compatible endpoint) can be
used without colliding on the single global ``~/.claude/.credentials.json``.

Two profile types are supported:

- ``oauth``   - an isolated Claude Code config home. Each profile owns its own
  ``CLAUDE_CONFIG_DIR`` (under ``~/.claudetm/profiles/<name>/``) holding its own
  ``.credentials.json``. The bundled ``claude`` CLI reads/refreshes credentials
  inside that directory, so two oauth profiles never clobber each other -- this
  is what makes parallel runs under different subscriptions possible.
- ``api-key`` - a direct API key + base URL injected as ``ANTHROPIC_API_KEY`` /
  ``ANTHROPIC_BASE_URL`` (e.g. z.ai / GLM via an Anthropic-compatible endpoint).

The registry lives in ``~/.claudetm/profiles.json`` (override the base directory
with the ``CLAUDETM_HOME`` env var). The active profile is a single pointer,
overridable per-run via the ``CLAUDETM_PROFILE`` environment variable.

This module only manages profile *metadata* and resolves the environment a run
should launch with. The actual env injection happens at the SDK subprocess
boundary (see ``agent_query`` / ``conversation``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ProfileType = Literal["oauth", "api-key"]

# Environment variable that overrides the active profile for a single run.
PROFILE_ENV_VAR = "CLAUDETM_PROFILE"
# Environment variable that relocates the base directory (mainly for tests).
HOME_ENV_VAR = "CLAUDETM_HOME"


class ProfileError(Exception):
    """Base exception for profile management errors."""


class ProfileNotFoundError(ProfileError):
    """Raised when a named profile does not exist."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(
            f"Profile '{name}' not found. Run 'claudetm profile list' to see profiles."
        )


class ProfileExistsError(ProfileError):
    """Raised when adding a profile whose name is already taken."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(
            f"Profile '{name}' already exists. Use a different name or remove it first."
        )


class ProfileValidationError(ProfileError):
    """Raised when a profile is missing fields required for its type."""


# =============================================================================
# Models
# =============================================================================


class Profile(BaseModel):
    """A single named authentication profile."""

    name: str
    type: ProfileType
    # oauth: absolute path to the isolated CLAUDE_CONFIG_DIR for this profile.
    config_dir: str | None = None
    # api-key: direct credentials for an Anthropic-compatible endpoint.
    api_key: str | None = None
    base_url: str | None = None

    def validate_for_type(self) -> None:
        """Ensure the fields required by this profile's type are present.

        Raises:
            ProfileValidationError: If a required field is missing.
        """
        if self.type == "oauth":
            if not self.config_dir:
                raise ProfileValidationError(
                    f"oauth profile '{self.name}' is missing its config_dir."
                )
        elif self.type == "api-key":
            if not self.api_key:
                raise ProfileValidationError(
                    f"api-key profile '{self.name}' is missing its api_key."
                )


class ProfileRegistry(BaseModel):
    """On-disk registry of all profiles plus the active pointer."""

    active: str | None = None
    profiles: dict[str, Profile] = Field(default_factory=dict)


# =============================================================================
# Environment resolution
# =============================================================================


def env_for_profile(profile: Profile) -> dict[str, str]:
    """Build the environment overrides a run should launch with for a profile.

    Args:
        profile: The profile to resolve.

    Returns:
        Mapping of environment variables to inject into the SDK subprocess.
        Empty when the profile carries no actionable credentials.
    """
    if profile.type == "oauth":
        if profile.config_dir:
            return {"CLAUDE_CONFIG_DIR": profile.config_dir}
        return {}

    # api-key
    env: dict[str, str] = {}
    if profile.api_key:
        env["ANTHROPIC_API_KEY"] = profile.api_key
    if profile.base_url:
        env["ANTHROPIC_BASE_URL"] = profile.base_url
    return env


def resolve_runtime_env() -> dict[str, str]:
    """Resolve env overrides for the currently active profile.

    Reads the ``CLAUDETM_PROFILE`` override or the persisted active profile.
    Deliberately defensive: any failure (missing/corrupt registry) returns an
    empty dict so the default ``~/.claude`` behavior is preserved.

    Returns:
        Environment overrides for the SDK subprocess, or empty dict.
    """
    try:
        manager = ProfileManager()
        profile = manager.resolve_active(os.environ.get(PROFILE_ENV_VAR))
        if profile is None:
            return {}
        return env_for_profile(profile)
    except Exception:
        return {}


# =============================================================================
# Manager
# =============================================================================


def _default_base_dir() -> Path:
    """Resolve the base directory for profile storage."""
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claudetm"


class ProfileManager:
    """Loads, persists, and resolves named authentication profiles."""

    def __init__(self, base_dir: Path | None = None):
        """Initialize the manager.

        Args:
            base_dir: Root directory for profile storage. Defaults to the
                ``CLAUDETM_HOME`` env var or ``~/.claudetm``.
        """
        self.base_dir = base_dir or _default_base_dir()
        self.registry_path = self.base_dir / "profiles.json"
        self.profiles_dir = self.base_dir / "profiles"

    # -- persistence -------------------------------------------------------

    def load(self) -> ProfileRegistry:
        """Load the registry from disk, returning an empty one if absent."""
        if not self.registry_path.exists():
            return ProfileRegistry()
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise ProfileError(
                f"Failed to read profile registry at {self.registry_path}: {e}"
            ) from e
        return ProfileRegistry.model_validate(data)

    def save(self, registry: ProfileRegistry) -> None:
        """Persist the registry atomically (temp file + rename)."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.registry_path.with_suffix(".json.tmp")
        tmp.write_text(registry.model_dump_json(indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.registry_path)

    # -- queries -----------------------------------------------------------

    def list(self) -> list[Profile]:
        """Return all profiles sorted by name."""
        registry = self.load()
        return [registry.profiles[name] for name in sorted(registry.profiles)]

    def get(self, name: str) -> Profile:
        """Return a single profile by name.

        Raises:
            ProfileNotFoundError: If no such profile exists.
        """
        registry = self.load()
        profile = registry.profiles.get(name)
        if profile is None:
            raise ProfileNotFoundError(name)
        return profile

    def active_name(self) -> str | None:
        """Return the name of the active profile, if any."""
        return self.load().active

    def resolve_active(self, override: str | None = None) -> Profile | None:
        """Resolve the profile in effect (override wins over persisted active).

        Args:
            override: Explicit profile name (e.g. from ``CLAUDETM_PROFILE``).

        Returns:
            The resolved Profile, or None when nothing is active / found. A
            missing override resolves to None so callers fall back to default
            credentials rather than erroring in the hot path.
        """
        registry = self.load()
        name = override or registry.active
        if not name:
            return None
        return registry.profiles.get(name)

    # -- mutations ---------------------------------------------------------

    def add(
        self,
        name: str,
        profile_type: ProfileType,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> Profile:
        """Create a new profile.

        For ``oauth`` profiles an isolated config directory is created under
        ``profiles_dir`` and the user must authenticate into it separately
        (``claudetm profile login <name>``).

        Args:
            name: Unique profile name.
            profile_type: ``oauth`` or ``api-key``.
            api_key: API key (required for ``api-key`` profiles).
            base_url: Anthropic-compatible base URL (``api-key`` profiles).

        Returns:
            The created profile.

        Raises:
            ProfileExistsError: If the name is already taken.
            ProfileValidationError: If required fields for the type are missing.
        """
        registry = self.load()
        if name in registry.profiles:
            raise ProfileExistsError(name)

        config_dir: str | None = None
        if profile_type == "oauth":
            profile_home = (self.profiles_dir / name).resolve()
            profile_home.mkdir(parents=True, exist_ok=True)
            config_dir = str(profile_home)

        profile = Profile(
            name=name,
            type=profile_type,
            config_dir=config_dir,
            api_key=api_key,
            base_url=base_url,
        )
        profile.validate_for_type()

        registry.profiles[name] = profile
        # First profile added becomes active automatically.
        if registry.active is None:
            registry.active = name
        self.save(registry)
        return profile

    def remove(self, name: str) -> None:
        """Remove a profile and clear the active pointer if it referenced it.

        Note: the profile's isolated config directory is left on disk so
        credentials are not destroyed by an accidental remove. Delete it
        manually if desired.

        Raises:
            ProfileNotFoundError: If no such profile exists.
        """
        registry = self.load()
        if name not in registry.profiles:
            raise ProfileNotFoundError(name)
        del registry.profiles[name]
        if registry.active == name:
            registry.active = None
        self.save(registry)

    def use(self, name: str) -> Profile:
        """Set the active profile.

        Raises:
            ProfileNotFoundError: If no such profile exists.
        """
        registry = self.load()
        profile = registry.profiles.get(name)
        if profile is None:
            raise ProfileNotFoundError(name)
        registry.active = name
        self.save(registry)
        return profile

    def clear_active(self) -> None:
        """Unset the active profile (revert to default ~/.claude credentials)."""
        registry = self.load()
        registry.active = None
        self.save(registry)
