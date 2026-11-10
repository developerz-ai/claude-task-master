"""Guard: ruff and mypy must agree across pyproject.toml, uv.lock and requirements.txt.

CI installs the project with `uv pip install -e ".[all]"`, so the declared range
in pyproject.toml is what constrains the installed linter and type checker. A
range spanning several minor releases lets a new ruff or mypy minor change lint
or type findings with no commit. This guard compares committed files only and
pins the range to one minor line that the lock and the artifact both select.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = ("ruff", "mypy")


def _declared(tool: str) -> Requirement:
    """The single requirement pyproject's dev extra declares for ``tool``."""
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]
    dev = project["optional-dependencies"]["dev"]
    matches = [r for r in map(Requirement, dev) if r.name == tool]
    assert len(matches) == 1, f"Declare {tool} in the dev extra exactly once"
    return matches[0]


def _lock() -> dict[str, list[dict[str, object]]]:
    return tomllib.loads((_ROOT / "uv.lock").read_text())


def _locked_version(tool: str) -> Version:
    """The version uv.lock resolves for ``tool``."""
    resolutions = [p for p in _lock()["package"] if p["name"] == tool]
    assert len(resolutions) == 1, f"uv.lock must resolve {tool} exactly once"
    return Version(str(resolutions[0]["version"]))


def _compiled_requirements() -> list[Requirement]:
    """Requirement lines of the committed `uv pip compile` artifact."""
    requirements: list[Requirement] = []
    for line in (_ROOT / "requirements.txt").read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            continue
        requirements.append(Requirement(stripped))
    return requirements


@pytest.mark.parametrize("tool", _TOOLS)
def test_locked_tool_satisfies_the_declared_range(tool: str) -> None:
    declared = _declared(tool).specifier
    resolved = _locked_version(tool)

    assert resolved in declared, f"lock resolves {tool} {resolved}, outside {declared}"


@pytest.mark.parametrize("tool", _TOOLS)
def test_lock_records_the_declared_range(tool: str) -> None:
    declared = _declared(tool).specifier
    root = next(p for p in _lock()["package"] if p["name"] == "claude-task-master")
    requires_dist = root["metadata"]["requires-dist"]  # type: ignore[index]
    locked = [
        dep
        for dep in requires_dist
        if dep["name"] == tool and dep.get("marker") == "extra == 'dev'"
    ]

    assert len(locked) == 1, f"uv.lock must record the dev-extra {tool} requirement once"
    assert SpecifierSet(locked[0]["specifier"]) == declared


@pytest.mark.parametrize("tool", _TOOLS)
def test_artifact_pins_the_locked_version(tool: str) -> None:
    declared = _declared(tool).specifier
    resolved = _locked_version(tool)
    pins = [r for r in _compiled_requirements() if r.name == tool]

    assert len(pins) == 1, f"requirements.txt must pin {tool} exactly once"
    specifiers = list(pins[0].specifier)
    assert len(specifiers) == 1, f"requirements.txt must pin {tool} to one version"
    assert specifiers[0].operator == "==", f"requirements.txt must pin {tool} with =="
    pinned = Version(specifiers[0].version)

    assert pinned == resolved, f"artifact {pinned}, lock {resolved}"
    assert pinned in declared, f"artifact {pinned} outside declared {declared}"


@pytest.mark.parametrize("tool", _TOOLS)
def test_declared_range_spans_a_single_minor(tool: str) -> None:
    """``>=X.Y.Z,<X.(Y+1)``: a new minor must arrive through a reviewed commit."""
    specifiers = list(_declared(tool).specifier)
    lowers = [s for s in specifiers if s.operator == ">="]
    uppers = [s for s in specifiers if s.operator == "<"]

    assert len(specifiers) == 2 and len(lowers) == 1 and len(uppers) == 1, (
        f"{tool} must be declared as '>=X.Y.Z,<X.(Y+1)', got {_declared(tool).specifier}"
    )
    lower, upper = Version(lowers[0].version), Version(uppers[0].version)

    assert upper.release[:2] == (lower.release[0], lower.release[1] + 1), (
        f"{tool} range {lower}..{upper} spans more than one minor line"
    )
    assert all(part == 0 for part in upper.release[2:]), f"{tool} upper bound {upper} not X.Y"
