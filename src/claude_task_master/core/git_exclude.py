"""Keep the orchestrator state dir out of git via the repo-local exclude file.

The work prompts stage changes with ``git add -A -- ':!.claude-task-master'`` so
state never enters a commit through the agent, but that pathspec only guards the
one ``add`` step. Writing ``.claude-task-master/`` to the repo's
``.git/info/exclude`` at task init makes git ignore the directory for *every*
command (``status``, ``add``, ``stash``) — without committing a ``.gitignore``
change into the user's repository.

This is best-effort belt-and-suspenders: a missing ``git`` binary, a working
tree that is not a git repo, or an unwritable exclude file are all tolerated
silently. The ``add`` pathspec remains the hard guarantee.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Entry appended to ``.git/info/exclude``. The trailing slash matches the
# directory (and everything under it) the way a ``.gitignore`` line would.
_EXCLUDE_ENTRY = ".claude-task-master/"

# Bound the git call so a hung/paused git process can never stall task init.
_GIT_TIMEOUT_SEC = 10


def ensure_state_dir_git_excluded(state_dir: Path) -> bool:
    """Ensure the state dir is listed in the repo's local git exclude file.

    Resolves the working tree from ``state_dir``'s parent, asks git for the
    exclude file path via ``git rev-parse --git-path info/exclude`` (which is
    correct even for worktrees and submodules, where ``.git`` is a file rather
    than a directory), and appends the state-dir entry when it is not already
    present. Idempotent.

    Args:
        state_dir: The ``.claude-task-master`` directory being initialized.

    Returns:
        True if the entry is present afterwards (already listed or freshly
        appended); False if the exclude file could not be resolved or written
        — not a git repo, ``git`` unavailable, timed out, or a permission
        error. Never raises.
    """
    work_dir = state_dir.resolve().parent

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SEC,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        # git missing, not a repo, or timed out — the add-pathspec is the guard.
        return False

    exclude_path = Path(proc.stdout.strip())
    if not exclude_path.is_absolute():
        exclude_path = work_dir / exclude_path

    try:
        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
        if any(line.strip() == _EXCLUDE_ENTRY for line in existing.splitlines()):
            return True

        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        # Separate from any prior content that lacks a trailing newline so the
        # entry always lands on its own line.
        prefix = "" if existing == "" or existing.endswith("\n") else "\n"
        with exclude_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{prefix}{_EXCLUDE_ENTRY}\n")
    except OSError:
        return False

    return True
