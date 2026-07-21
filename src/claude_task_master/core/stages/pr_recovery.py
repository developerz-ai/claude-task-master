"""_PRRecovery — deterministic recovery when a PR group ends without a PR.

Non-last tasks in a PR group run in commit-only mode ("do NOT push or create a
PR"), so all of the group's work sits on the local branch until the last task's
session opens the PR. When that last session legitimately ships nothing itself
(verification-only), agents sometimes report "no PR needed" — leaving the
group's earlier commits stranded and the run blocked in ``pr_created``.

The orchestrator has everything it needs to recover without an agent: push the
branch and open the PR itself, or — when the branch carries no commits over the
base — close the group out as done. Blocking is reserved for the cases that
genuinely need a human (dirty tree, sitting on the base branch, git/API
failures).
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .. import console
from ..config_loader import get_config
from ..task_group import parse_tasks_with_groups
from .git_ops import _GitOps

if TYPE_CHECKING:
    from ..state import TaskState

#: Cap for the generated PR title (repo convention: type + ≤70 chars).
_PR_TITLE_MAX = 70


class _PRRecovery(_GitOps):
    """Mixin: self-heal the ``pr_created`` stage when no PR exists yet."""

    def _recover_missing_pr(self, state: TaskState) -> int | None:
        """Recover from a finished PR group whose branch has no PR.

        Returns:
            None to continue the loop (PR opened, or nothing to ship and the
            stage advanced to ``merged``), 1 when blocked for manual
            intervention.
        """
        base = get_config().git.target_branch
        branch = self._get_current_branch()

        if not branch or branch == base:
            return self._block_missing_pr(
                state, f"current branch is the base branch ({base!r}) — nothing to open a PR from"
            )

        if self._has_uncommitted_changes():
            return self._block_missing_pr(
                state,
                "working tree has uncommitted changes — the last session left unfinished work",
            )

        ahead = self._commits_ahead_of_base(base)
        if ahead is None:
            return self._block_missing_pr(
                state, f"could not compare {branch} against origin/{base}"
            )

        if ahead == 0:
            console.info(
                f"Branch {branch} has no commits over {base} — nothing to ship for this PR group"
            )
            state.workflow_stage = "merged"
            self.state_manager.save_state(state)
            return None

        console.info(
            f"Branch {branch} is {ahead} commit(s) ahead of {base} — opening the PR myself"
        )
        try:
            self._push_current_branch()
            title, body = self._build_group_pr_text(state, branch)
            pr_number = self.github_client.create_pr(title, body, base=base)
        except Exception as e:
            return self._block_missing_pr(state, f"pushing/creating the PR failed: {e}")

        console.success(f"Opened PR #{pr_number} for branch {branch}")
        # Leave the stage as pr_created: the next cycle detects the PR through
        # the normal path (timing, body sanitizing, waiting_ci transition).
        self.state_manager.save_state(state)
        return None

    def _block_missing_pr(self, state: TaskState, reason: str) -> int:
        """Block the run for manual intervention (the pre-recovery behavior)."""
        console.error(f"No PR found for current branch and recovery is not possible: {reason}")
        console.detail("Manual intervention required:")
        console.detail("  1. Push the branch: git push -u origin HEAD")
        console.detail("  2. Create a PR: gh pr create --title 'feat: description'")
        console.detail("  3. Resume: claudetm resume")
        state.status = "blocked"
        self.state_manager.save_state(state)
        return 1

    def _build_group_pr_text(self, state: TaskState, branch: str) -> tuple[str, str]:
        """Build a PR title/body from the current task's PR group in the plan."""
        group_name = ""
        completed: list[str] = []
        try:
            plan = self.state_manager.load_plan()
            if plan:
                tasks, _ = parse_tasks_with_groups(plan)
                if state.current_task_index < len(tasks):
                    current = tasks[state.current_task_index]
                    group_name = current.group_name
                    completed = [
                        t.cleaned_description
                        for t in tasks
                        if t.group_id == current.group_id and t.is_complete
                    ]
        except Exception as e:
            console.warning(f"Could not derive PR text from plan: {e}")

        title = f"feat: {group_name or branch}"
        if len(title) > _PR_TITLE_MAX:
            title = title[: _PR_TITLE_MAX - 1] + "…"

        lines = ["Completed tasks in this PR group:"] if completed else []
        lines += [f"- {desc}" for desc in completed]
        lines += [
            "",
            "Opened by the claudetm orchestrator: the work sessions committed "
            "this group's changes but did not open the PR.",
        ]
        return title, "\n".join(lines).strip()

    @staticmethod
    def _has_uncommitted_changes() -> bool:
        """True when ``git status --porcelain`` reports anything (or fails)."""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return bool(result.stdout.strip())
        except Exception:
            return True

    @staticmethod
    def _commits_ahead_of_base(base: str) -> int | None:
        """Count commits on HEAD that are not on ``origin/<base>``.

        Returns None when the comparison cannot be made (fetch or rev-list
        failure) — the caller must treat that as "unknown", never as 0.
        """
        try:
            subprocess.run(
                ["git", "fetch", "origin", base],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            result = subprocess.run(
                ["git", "rev-list", "--count", f"origin/{base}..HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return int(result.stdout.strip())
        except Exception:
            return None

    @staticmethod
    def _push_current_branch() -> None:
        """Push the current branch, setting upstream. Raises on failure."""
        subprocess.run(
            ["git", "push", "-u", "origin", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
