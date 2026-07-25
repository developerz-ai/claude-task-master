"""_PRRecovery — deterministic recovery when a PR group ends without a PR.

Non-last tasks in a PR group run in commit-only mode ("do NOT push or create a
PR"), so all of the group's work sits on the local branch until the last task's
session opens the PR. When that last session legitimately ships nothing itself
(verification-only), agents sometimes report "no PR needed" — leaving the
group's earlier commits stranded and the run blocked in ``pr_created``.

The orchestrator has everything it needs to recover without an agent: push the
branch and open the PR itself, or — when the branch carries no commits over the
base — close the group out as done.

A *dirty* tree is the other common ending: a work session died mid-task (the SDK
terminating leftover background work, a turn that ended while the agent waited on
something) with real, uncommitted changes on disk. The orchestrator must not
commit those itself — it cannot tell finished work from a half-applied edit — but
it can hand them to a tightly-scoped agent session that verifies, commits, pushes
and opens the PR. That is bounded by ``MAX_PR_FINISH_ATTEMPTS``.

Blocking is reserved for what genuinely needs a human: sitting on the base
branch, git/API failures, or a tree still dirty after the finish sessions.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .. import console
from ..agent import ModelType
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
            return self._finish_unfinished_work(state, branch)

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

    def _finish_unfinished_work(self, state: TaskState, branch: str) -> int | None:
        """Hand a dirty tree to a bounded agent session that finishes the group.

        The previous work session ended with changes still on disk, so there is
        nothing to push and no PR to open. The orchestrator cannot judge whether
        those changes are complete — an agent can: verify, commit, push, open the
        PR. On the next cycle the normal path picks the PR up (or, if the session
        committed but did not push, the deterministic push+create path runs with a
        now-clean tree).

        Args:
            state: Current task state.
            branch: The branch the leftover work sits on.

        Returns:
            None to continue the loop with the stage still ``pr_created``, 1 when
            the attempt budget is spent or the session itself failed.
        """
        if state.pr_finish_attempts >= self.MAX_PR_FINISH_ATTEMPTS:
            return self._block_missing_pr(
                state,
                f"working tree still has uncommitted changes after "
                f"{state.pr_finish_attempts} finish attempt(s)",
            )

        state.pr_finish_attempts += 1
        console.warning(
            f"Working tree is dirty and {branch} has no PR — the last session left work "
            f"unfinished. Running a finish session "
            f"(attempt {state.pr_finish_attempts}/{self.MAX_PR_FINISH_ATTEMPTS})..."
        )
        self.state_manager.save_state(state)

        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        base = get_config().git.target_branch
        try:
            self.agent.run_work_session(
                task_description=self._build_finish_group_task(state, branch),
                context=context,
                model_override=ModelType.OPUS,
                required_branch=branch,
                create_pr=True,
                target_branch=base,
            )
        except Exception as e:
            return self._block_missing_pr(state, f"the finish session failed: {e}")

        state.session_count += 1
        # Stage stays pr_created: the next cycle detects the PR the session opened,
        # or re-enters recovery with a clean tree and pushes/opens it deterministically.
        self.state_manager.save_state(state)
        return None

    def _build_finish_group_task(self, state: TaskState, branch: str) -> str:
        """Build the finish-the-group task description for the agent session."""
        changes = self._uncommitted_summary()
        changes_block = f"\n```\n{changes}\n```\n" if changes else "\n"
        retry_note = (
            f"\n**This is attempt {state.pr_finish_attempts}** — a previous finish session did "
            "not leave the tree clean. Check `git status` first.\n"
            if state.pr_finish_attempts > 1
            else ""
        )
        group_name, completed = self._group_summary(state)
        group_line = f"PR group: {group_name}\n" if group_name else ""
        done_lines = "\n".join(f"- {desc}" for desc in completed)
        summary = f"{group_line}{done_lines}".strip() or "(plan unavailable — read the git log)"

        return f"""A work session on `{branch}` died before committing. Its changes are still
in the working tree; this PR group has no PR.
{retry_note}
Uncommitted:{changes_block}
Finish and ship exactly this. No new work.

1. `git diff` + read the changed files — understand what was in progress.
   Half-applied edits: finish them. Scratch/debug leftovers: delete them.
2. Run the repo's tests + lint. Foreground, wait for the result. Fix what breaks.
3. Commit, `git push -u origin HEAD`, `gh pr create`.

The PR ships every commit on `{branch}`, not just yours:

{summary}

Don't merge, don't wait for CI. Done = clean `git status` + PR URL."""

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

    def _group_summary(self, state: TaskState) -> tuple[str, list[str]]:
        """Return ``(group_name, completed_task_descriptions)`` for the current group.

        Degrades to ``("", [])`` on any parse failure — every caller only uses
        this to enrich text, so a missing plan must never break recovery.
        """
        try:
            plan = self.state_manager.load_plan()
            if not plan:
                return "", []
            tasks, _ = parse_tasks_with_groups(plan)
            if state.current_task_index >= len(tasks):
                return "", []
            current = tasks[state.current_task_index]
            completed = [
                t.cleaned_description
                for t in tasks
                if t.group_id == current.group_id and t.is_complete
            ]
            return current.group_name, completed
        except Exception as e:
            console.warning(f"Could not derive PR text from plan: {e}")
            return "", []

    def _build_group_pr_text(self, state: TaskState, branch: str) -> tuple[str, str]:
        """Build a PR title/body from the current task's PR group in the plan."""
        group_name, completed = self._group_summary(state)

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
