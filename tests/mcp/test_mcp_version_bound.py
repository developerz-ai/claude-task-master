"""Packaging guards for the MCP 2 migration, independent of server imports."""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

_ROOT = Path(__file__).resolve().parents[2]


def _mcp_requirement(dependencies: list[str]) -> Requirement:
    requirements = [Requirement(dependency) for dependency in dependencies]
    matches = [requirement for requirement in requirements if requirement.name == "mcp"]
    assert len(matches) == 1, "Declare MCP explicitly and exactly once"
    assert matches[0].marker is None, "The MCP requirement must apply unconditionally"
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


def test_base_and_extra_require_supported_mcp_2() -> None:
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]
    base = _mcp_requirement(project["dependencies"])
    extra = _mcp_requirement(project["optional-dependencies"]["mcp"])

    assert base.specifier == extra.specifier
    for requirement in (base, extra):
        assert Version("2.1.1") in requirement.specifier
        assert Version("2.3.0") in requirement.specifier
        assert Version("1.28.1") not in requirement.specifier
        assert Version("3.0.0") not in requirement.specifier


def test_lock_requirements_match_base_and_extra() -> None:
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]
    lock = tomllib.loads((_ROOT / "uv.lock").read_text())
    root = next(package for package in lock["package"] if package["name"] == project["name"])
    locked_requirements = [
        dependency
        for dependency in root["metadata"]["requires-dist"]
        if dependency["name"] == "mcp"
    ]

    assert len(locked_requirements) == 2
    by_marker = {dependency.get("marker"): dependency for dependency in locked_requirements}
    assert set(by_marker) == {None, "extra == 'mcp'"}
    base = _mcp_requirement(project["dependencies"])
    extra = _mcp_requirement(project["optional-dependencies"]["mcp"])
    assert SpecifierSet(by_marker[None]["specifier"]) == base.specifier
    assert SpecifierSet(by_marker["extra == 'mcp'"]["specifier"]) == extra.specifier
    assert {"name": "mcp"} in root["dependencies"]
    assert {"name": "mcp"} in root["optional-dependencies"]["mcp"]


def test_installed_mcp_matches_supported_lock_resolution() -> None:
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]
    lock = tomllib.loads((_ROOT / "uv.lock").read_text())
    resolutions = [package for package in lock["package"] if package["name"] == "mcp"]
    assert len(resolutions) == 1
    resolved = Version(resolutions[0]["version"])
    installed = Version(version("mcp"))

    assert resolved.major == 2
    assert installed == resolved, "Provision the environment from the current lock before testing"
    assert resolved in _mcp_requirement(project["dependencies"]).specifier
    assert resolved in _mcp_requirement(project["optional-dependencies"]["mcp"]).specifier


def test_compiled_artifact_pins_supported_mcp_2() -> None:
    """The committed install artifact must not resolve an SDK the server cannot import."""
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]
    pins = [requirement for requirement in _compiled_requirements() if requirement.name == "mcp"]

    assert len(pins) == 1, "requirements.txt must pin MCP exactly once"
    specifiers = list(pins[0].specifier)
    assert len(specifiers) == 1, "requirements.txt must pin MCP to one exact version"
    assert specifiers[0].operator == "==", "requirements.txt must pin MCP with =="
    pinned = Version(specifiers[0].version)

    assert pinned.major == 2, f"requirements.txt pins MCP {pinned}; the server imports MCP 2"
    assert pinned in _mcp_requirement(project["dependencies"]).specifier
