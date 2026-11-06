"""Guard: the committed install artifact must pin the SDK the lock resolves.

CI installs the project with `uv pip install -e ".[all]"`, not from uv.lock,
so the installed SDK floats to the newest release in the declared range. This
guard therefore compares committed files only - pyproject.toml, uv.lock and
requirements.txt - and never the installed distribution.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

_ROOT = Path(__file__).resolve().parents[1]
_SDK = "claude-agent-sdk"


def _sdk_requirement(dependencies: list[str]) -> Requirement:
    """The single Agent SDK requirement among ``dependencies``."""
    requirements = [Requirement(dependency) for dependency in dependencies]
    matches = [requirement for requirement in requirements if requirement.name == _SDK]
    assert len(matches) == 1, "Declare the Agent SDK explicitly and exactly once"
    return matches[0]


def _compiled_requirements() -> list[Requirement]:
    """Requirement lines of the committed `uv pip compile` artifact."""
    requirements: list[Requirement] = []
    for line in (_ROOT / "requirements.txt").read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        requirements.append(Requirement(stripped))
    return requirements


def _locked_sdk_version() -> Version:
    """The version uv.lock resolves for the Agent SDK."""
    lock = tomllib.loads((_ROOT / "uv.lock").read_text())
    resolutions = [package for package in lock["package"] if package["name"] == _SDK]
    assert len(resolutions) == 1, "uv.lock must resolve the Agent SDK exactly once"
    return Version(resolutions[0]["version"])


def _declared_sdk_range() -> SpecifierSet:
    """The range pyproject declares for the Agent SDK."""
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]
    return _sdk_requirement(project["dependencies"]).specifier


def test_locked_sdk_satisfies_the_declared_range() -> None:
    """The authoritative resolution must stay inside the declared range."""
    declared = _declared_sdk_range()
    resolved = _locked_sdk_version()

    assert resolved in declared, f"lock resolves {resolved}, outside {declared}"


def test_lock_records_the_declared_sdk_range() -> None:
    """uv.lock must carry the range pyproject declares, not a stale one."""
    declared = _declared_sdk_range()
    lock = tomllib.loads((_ROOT / "uv.lock").read_text())
    root = next(pkg for pkg in lock["package"] if pkg["name"] == "claude-task-master")
    requires_dist = root["metadata"]["requires-dist"]
    locked = [dep for dep in requires_dist if dep["name"] == _SDK]

    assert len(locked) == 1
    assert SpecifierSet(locked[0]["specifier"]) == declared


def test_artifact_pins_the_locked_sdk_version() -> None:
    """The committed artifact must select the SDK uv.lock resolves."""
    declared = _declared_sdk_range()
    resolved = _locked_sdk_version()
    compiled = _compiled_requirements()
    pins = [requirement for requirement in compiled if requirement.name == _SDK]

    assert len(pins) == 1, "requirements.txt must pin the Agent SDK exactly once"
    specifiers = list(pins[0].specifier)
    assert len(specifiers) == 1, "requirements.txt must pin the Agent SDK to one version"
    assert specifiers[0].operator == "==", "requirements.txt must pin the Agent SDK with =="
    pinned = Version(specifiers[0].version)

    assert pinned == resolved, f"artifact {pinned}, lock {resolved}"
    assert pinned in declared, f"artifact {pinned} outside declared {declared}"
