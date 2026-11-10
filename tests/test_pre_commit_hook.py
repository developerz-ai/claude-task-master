"""Guard: the pre-commit hook runs the gate and propagates its failure.

A hook that repairs the tree behind the committer's back, or that swallows a
red gate, lets a commit CI would reject reach the branch. This guard copies the
hook into a throwaway git repository whose `bin/check` is a stub, runs it, and
asserts that the stub ran and that its exit status reached the caller. It also
runs the hook outside any git repository, where the hook must refuse loudly
instead of guessing a root. It reads committed files only and never runs the
real gate.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_HOOK = _ROOT / "scripts" / "hooks" / "pre-commit"
_SETUP = _ROOT / "scripts" / "setup-hooks.sh"

# The hook must not repair the tree for the committer, and it must never report
# success when the gate failed.
_FORBIDDEN = ("--fix", "git add", "exit 0")

# The promise the old hook made; the new one runs the gate instead.
_OLD_PROMISE = "runs lint and fixes issues"

# Git exports these when it runs a hook, so the hook under test must find the
# repository by itself. The variants below cover the environments git uses.
_HOOK_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE")
_GIT_DIR_VARIANTS = (None, "absolute", "relative")

# A distinctive status, so a swallowed or rewritten exit code cannot pass.
_STUB_EXIT_CODE = 3

# What the hook must say when it cannot find a repository to gate.
_REFUSAL_MESSAGE = "pre-commit: cannot locate the repository root"

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def test_hook_source_carries_no_auto_fix_and_no_forced_success() -> None:
    """The hook source must run the gate and nothing that hides a failure."""
    text = _HOOK.read_text()
    for forbidden in _FORBIDDEN:
        assert forbidden not in text, f"the pre-commit hook must not contain {forbidden!r}"
    assert "bin/check" in text, "the pre-commit hook must run bin/check"


def test_setup_message_describes_the_gate() -> None:
    """The install script must tell contributors the hook runs the gate."""
    text = _SETUP.read_text()
    assert _OLD_PROMISE not in text, "setup-hooks.sh must not promise an auto-fix"
    assert "bin/check" in text, "setup-hooks.sh must name the gate the hook runs"


@requires_git
@pytest.mark.parametrize("git_dir", _GIT_DIR_VARIANTS)
def test_hook_runs_gate_and_propagates_failure(tmp_path: Path, git_dir: str | None) -> None:
    """The hook must run bin/check in the repository root and return its status."""
    repo = tmp_path / "repo"
    repo.mkdir()
    init = subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert init.returncode == 0, init.stderr

    marker = repo / "gate-ran"
    stub = repo / "bin" / "check"
    stub.parent.mkdir()
    stub.write_text(f"#!/usr/bin/env bash\ntouch {marker}\nexit {_STUB_EXIT_CODE}\n")
    stub.chmod(0o755)

    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(_HOOK.read_text())
    hook.chmod(0o755)

    env = {k: v for k, v in os.environ.items() if k not in _HOOK_ENV_DROP}
    if git_dir == "absolute":
        env["GIT_DIR"] = str(repo / ".git")
    elif git_dir == "relative":
        env["GIT_DIR"] = ".git"
    result = subprocess.run(
        [str(hook)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert marker.exists(), f"the hook did not run bin/check: {result.stderr}"
    detail = f"hook returned {result.returncode}, gate stderr: {result.stderr}"
    assert result.returncode == _STUB_EXIT_CODE, detail


@requires_git
def test_hook_refuses_to_run_outside_a_repository(tmp_path: Path) -> None:
    """Outside a repository the hook must fail loudly, not gate the wrong tree."""
    outside = tmp_path / "not-a-repo"
    outside.mkdir()

    hook = tmp_path / "pre-commit"
    hook.write_text(_HOOK.read_text())
    hook.chmod(0o755)

    env = {k: v for k, v in os.environ.items() if k not in _HOOK_ENV_DROP}
    # Keep discovery from walking above the temporary tree, so the case holds
    # even where the temporary directory happens to sit inside a checkout.
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path)

    probe = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=outside,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if probe.returncode == 0:
        pytest.skip(f"the temporary directory is inside a repository: {probe.stdout.strip()}")

    result = subprocess.run(
        [str(hook)],
        cwd=outside,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    detail = f"hook returned {result.returncode}, hook stderr: {result.stderr}"
    assert result.returncode == 1, detail
    assert _REFUSAL_MESSAGE in result.stderr, detail
