"""Guard: the gate documentation must state where the gate's tools come from.

CI installs the project with `uv pip install -e ".[all]"`, an install path that does
not read `uv.lock`, so CI resolves the newest ruff and mypy release inside
pyproject's dev-extra ranges while a local `uv sync`/`uv run` resolves the versions
`uv.lock` pins. A green local gate is therefore not evidence about CI, and the docs
have to say so. This guard reads committed files only and derives its expectations
from pyproject.toml and uv.lock, so a bumped range or a re-locked version fails the
test until the documentation is updated.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet

_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = ("ruff", "mypy")

_CLAUDE_MD = _ROOT / "CLAUDE.md"
_SKILL_MD = _ROOT / ".claude/skills/verify-change/SKILL.md"
_CONTRIBUTING_MD = _ROOT / "CONTRIBUTING.md"

_CI_INSTALL = 'uv pip install -e ".[all]"'

# A version specifier is built from these characters; the scan for the range a doc
# attaches to a tool name stops at the first character outside the set.
_SPECIFIER_CHARS = set("<>=!~,.*0123456789")

# Each doc and the caveat it keeps about a local pass, quoted verbatim from that doc.
_DOC_CAVEATS = [
    (_CLAUDE_MD, "not proof that CI is green"),
    (_SKILL_MD, "not a guarantee that CI will pass"),
]


def _squash(text: str) -> str:
    """Drop every whitespace character: a doc may wrap one phrase over lines."""
    return "".join(text.split())


def _declared(tool: str) -> Requirement:
    """The single requirement pyproject's dev extra declares for ``tool``."""
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]
    dev = project["optional-dependencies"]["dev"]
    matches = [r for r in map(Requirement, dev) if r.name == tool]
    assert len(matches) == 1, f"Declare {tool} in the dev extra exactly once"
    return matches[0]


def _locked_version(tool: str) -> str:
    """The version uv.lock resolves for ``tool``."""
    lock = tomllib.loads((_ROOT / "uv.lock").read_text())
    resolutions = [p for p in lock["package"] if p["name"] == tool]
    assert len(resolutions) == 1, f"uv.lock must resolve {tool} exactly once"
    return str(resolutions[0]["version"])


def _states_range(text: str, tool: str, expected: SpecifierSet) -> bool:
    """Whether ``text`` states ``tool`` with a specifier set equal to ``expected``."""
    squashed = _squash(text)
    for match in re.finditer(re.escape(tool), squashed):
        tail = squashed[match.end() :]
        end = 0
        while end < len(tail) and tail[end] in _SPECIFIER_CHARS:
            end += 1
        candidate = tail[:end]
        if not candidate:
            continue
        try:
            parsed = Requirement(f"{tool}{candidate}")
        except InvalidRequirement:
            continue
        if parsed.specifier == expected:
            return True
    return False


def _has_line_with(text: str, *needles: str) -> bool:
    """Whether one line of ``text`` holds every needle once whitespace is dropped."""
    for line in text.splitlines():
        squashed = _squash(line)
        if all(_squash(needle) in squashed for needle in needles):
            return True
    return False


@pytest.mark.parametrize("tool", _TOOLS)
@pytest.mark.parametrize("doc", [_CLAUDE_MD, _SKILL_MD], ids=lambda path: path.name)
def test_doc_names_the_declared_range(tool: str, doc: Path) -> None:
    """The doc must state the range pyproject declares, not a stale copy of it."""
    declared = _declared(tool)
    assert _states_range(doc.read_text(), tool, declared.specifier), (
        f"{doc.name} must state the {tool} range pyproject declares: {declared}"
    )


@pytest.mark.parametrize("tool", _TOOLS)
@pytest.mark.parametrize("doc", [_CLAUDE_MD, _SKILL_MD], ids=lambda path: path.name)
def test_doc_names_the_locked_version(tool: str, doc: Path) -> None:
    """The doc must state the version uv.lock pins, next to the tool name."""
    version = _locked_version(tool)
    assert f"{tool}{version}" in _squash(doc.read_text()), (
        f"{doc.name} must state that {tool} {version} is the version uv.lock pins"
    )


@pytest.mark.parametrize("doc", [_CLAUDE_MD, _SKILL_MD], ids=lambda path: path.name)
def test_doc_names_the_ci_install_source(doc: Path) -> None:
    """The doc must name CI's install command and the lock it bypasses."""
    text = doc.read_text()
    assert _squash(_CI_INSTALL) in _squash(text), (
        f"{doc.name} must name CI's install command {_CI_INSTALL}"
    )
    assert "uv.lock" in _squash(text), f"{doc.name} must name uv.lock"


@pytest.mark.parametrize("doc", [_CLAUDE_MD, _SKILL_MD], ids=lambda path: path.name)
def test_doc_says_requirements_txt_is_not_a_gate_input(doc: Path) -> None:
    """The compiled artifact must be declared out of the gate's way."""
    assert _has_line_with(doc.read_text(), "requirements.txt", "not a gate input"), (
        f"{doc.name} must have a line stating requirements.txt is not a gate input"
    )


@pytest.mark.parametrize(("doc", "caveat"), _DOC_CAVEATS, ids=["claude", "skill"])
def test_doc_keeps_the_local_pass_caveat(doc: Path, caveat: str) -> None:
    """A local pass is not evidence about CI; the doc has to say so."""
    assert _squash(caveat) in _squash(doc.read_text()), (
        f"{doc.name} must keep the caveat '{caveat}'"
    )


@pytest.mark.parametrize("doc", [_CLAUDE_MD, _SKILL_MD], ids=lambda path: path.name)
def test_doc_states_the_hook_runs_the_gate(doc: Path) -> None:
    """The installed pre-commit hook runs the gate; the doc must say so."""
    assert _has_line_with(doc.read_text(), "setup-hooks.sh", "bin/check"), (
        f"{doc.name} must state that the hook installed by scripts/setup-hooks.sh runs bin/check"
    )


def test_contributing_prescribes_the_gate_scope() -> None:
    """CONTRIBUTING.md must prescribe the checks the gate runs, not narrower ones."""
    squashed = _squash(_CONTRIBUTING_MD.read_text())
    assert _squash("uv run mypy .") in squashed, "CONTRIBUTING.md must prescribe `uv run mypy .`"
    assert _squash("mypy src/") not in squashed, "CONTRIBUTING.md must not narrow mypy to src/"
    assert _squash("uv run ruff format --check .") in squashed, (
        "CONTRIBUTING.md must prescribe `uv run ruff format --check .`"
    )
    assert _squash("uv run ruff format .") not in squashed, (
        "CONTRIBUTING.md must not prescribe the rewriting formatter"
    )


def test_contributing_test_commands_use_the_gate_timeout() -> None:
    """Every prescribed test command must carry the gate's pytest timeout."""
    lines = [line for line in _CONTRIBUTING_MD.read_text().splitlines() if "uv run pytest" in line]
    assert lines, "CONTRIBUTING.md must prescribe the test command"
    for line in lines:
        assert "--timeout=120" in line, (
            f"CONTRIBUTING.md test command lacks the gate's --timeout=120: {line.strip()}"
        )
