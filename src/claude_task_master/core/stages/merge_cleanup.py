"""_MergeCleanup — recover a dirty working tree that is blocking the merge.

``gh pr merge`` checks branches out, so it dies on a raw git error when the tree
has uncommitted changes. ``ready_to_merge`` therefore refuses to call it on a
dirty tree — but refusing was *all* it did: ``status = "blocked"``, run over.

That block is undefeatable by the tool meant to defeat it. The condition is
purely local and deterministic, so ``claudetm resume --force`` clears the status,
re-enters ``ready_to_merge``, re-reads the same unchanged tree and blocks again
having run zero sessions. A run that spent hours getting a PR green then stops
overnight on two files an agent could have judged in a minute:

    D mobile/app/expo-env.d.ts
    M mobile/app/tsconfig.json

(both written by an `expo prebuild` a session ran, not by anyone's edit).

So the tree gets handed to a bounded agent session instead, exactly as
``_PRRecovery`` does for a dirty tree with no PR. The agent is the only thing
here that can tell the PR's own unfinished work (commit it, push it, let CI
re-verify) from tooling droppings (discard them). The orchestrator keeps the
parts that must not be guessed at:

- it never commits anything itself,
- a session that leaves new commits on the branch routes the PR back through
  ``waiting_ci`` rather than merging on CI that ran before those commits existed,
- and a tree still dirty after ``MAX_MERGE_CLEANUP_ATTEMPTS`` sessions blocks,
  which is the case where a human genuinely is required.

Leftovers sitting on the *base* branch still block on sight: nothing there
belongs to the PR, and a cleanup session must never commit to the base.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import console
from ..agent import ModelType
from .review_stage import _ReviewStage

if TYPE_CHECKING:
    from ..state import TaskState


class _MergeCleanup(_ReviewStage):
    """Mixin: bounded agent recovery for a dirty tree in ``ready_to_merge``."""

    def _handle_dirty_before_merge(
        self,
        state: TaskState,
        pr_number: int,
        pending: str,
        base_branch: str,
    ) -> int | None:
        """Clear a dirty working tree so the merge can proceed, or block.

        Args:
            state: Current task state.
            pr_number: The PR waiting to be merged.
            pending: ``git status --porcelain`` summary of the leftovers.
            base_branch: The PR's base branch — never a place to commit to.

        Returns:
            None to continue the loop (stage stays ``ready_to_merge``, or moves
            to ``waiting_ci`` when the cleanup pushed new commits), 1 when the
            run is blocked.
        """
        branch = self._get_current_branch()
        if branch is None or branch == base_branch:
            return self._block_dirty_merge(
                state,
                pr_number,
                pending,
                f"the changes are on {branch or 'an unknown branch'}, not on a PR branch",
            )

        if state.merge_cleanup_attempts >= self.MAX_MERGE_CLEANUP_ATTEMPTS:
            return self._block_dirty_merge(
                state,
                pr_number,
                pending,
                f"still dirty after {state.merge_cleanup_attempts} cleanup session(s)",
            )

        state.merge_cleanup_attempts += 1
        console.warning(
            f"PR #{pr_number} is ready but the working tree is dirty — running a cleanup "
            f"session (attempt {state.merge_cleanup_attempts}/{self.MAX_MERGE_CLEANUP_ATTEMPTS})"
        )
        for line in pending.splitlines():
            console.detail(f"  {line}")
        self.state_manager.save_state(state)

        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        before_sha = self._head_sha()
        try:
            self.agent.run_work_session(
                task_description=self._build_merge_cleanup_task(state, pr_number, branch, pending),
                context=context,
                model_override=ModelType.OPUS,
                required_branch=branch,
                create_pr=False,
                push_only=True,
                target_branch=base_branch,
            )
        except Exception as e:
            return self._block_dirty_merge(
                state, pr_number, pending, f"the cleanup session failed: {e}"
            )

        state.session_count += 1
        return self._after_merge_cleanup(state, pr_number, branch, before_sha)

    def _after_merge_cleanup(
        self,
        state: TaskState,
        pr_number: int,
        branch: str,
        before_sha: str | None,
    ) -> int | None:
        """Decide where the PR goes once the cleanup session has run.

        Three outcomes: still dirty (re-enter the stage, the attempt budget
        bounds it), cleaned with new commits on the branch (CI must run against
        the new head before the merge), or cleaned with the branch untouched
        (merge on the next cycle).
        """
        still_pending = self._uncommitted_summary(max_lines=20)
        if still_pending:
            console.warning(
                f"Cleanup session left the tree dirty "
                f"({state.merge_cleanup_attempts}/{self.MAX_MERGE_CLEANUP_ATTEMPTS} attempts used)"
            )
            # Stage untouched: the next cycle re-enters and either runs the last
            # attempt or blocks with the budget spent.
            self.state_manager.save_state(state)
            return None

        after_sha = self._head_sha()
        # Unknown counts as moved, not as unchanged. Reading "no new commits" off
        # a probe that failed is how a cleanup commit gets merged on the CI that
        # ran before it existed — and the cost of being wrong the other way is
        # one extra CI poll on an already-green PR.
        head_moved = before_sha is None or after_sha is None or before_sha != after_sha

        # A session that committed but never pushed is the dangerous case: the
        # tree reads clean, so nothing downstream would notice, and the merge
        # would land the PR *without* those commits and then delete the branch
        # carrying them. Pushing is deterministic, so the orchestrator does it.
        # A push with nothing to push is a no-op, so this runs whenever new
        # commits are possible rather than only when they are proven.
        unpushed = self._unpushed_commit_count(branch)
        if head_moved or unpushed:
            console.info(
                f"Pushing {unpushed} commit(s) the cleanup session left unpushed..."
                if unpushed
                else "Making sure the cleanup session's commits reached the PR..."
            )
            try:
                self._push_current_branch()
            except Exception as e:
                return self._block_dirty_merge(
                    state, pr_number, "", f"could not push the cleanup commits: {e}"
                )
            console.info(f"PR #{pr_number} goes back through CI before merging")
            state.workflow_stage = "waiting_ci"
            state.ci_poll_start_time = None
            self.state_manager.save_state(state)
            return None

        console.success("Working tree is clean — proceeding with the merge")
        self.state_manager.save_state(state)
        return None

    def _block_dirty_merge(
        self, state: TaskState, pr_number: int, pending: str, reason: str
    ) -> int:
        """Block the run on a dirty tree the orchestrator cannot clear itself."""
        console.error(
            f"Refusing to merge PR #{pr_number}: the working tree has uncommitted changes, "
            f"and merging checks branches out ({reason})"
        )
        if pending:
            console.detail("Pending changes:")
            for line in pending.splitlines():
                console.detail(f"  {line}")
        console.detail("Commit, stash or discard them, then: claudetm resume")
        state.status = "blocked"
        self.state_manager.save_state(state)
        return 1

    def _build_merge_cleanup_task(
        self, state: TaskState, pr_number: int, branch: str, pending: str
    ) -> str:
        """Build the clear-the-tree task description for the agent session."""
        retry_note = (
            f"\n**This is attempt {state.merge_cleanup_attempts}** — a previous cleanup session "
            "did not leave the tree clean. Run `git status` first.\n"
            if state.merge_cleanup_attempts > 1
            else ""
        )
        return f"""PR #{pr_number} is green and ready to merge, but `{branch}` has uncommitted
changes. `gh pr merge` checks the branch out, so it cannot merge until the tree
is clean.
{retry_note}
Uncommitted:
```
{pending}
```

Decide what these changes are — that judgement is the whole job. No new work.

1. `git status` and `git diff` (`git diff --staged` too) and read the files.
2. Sort every pending path into one of two buckets:
   - **The PR's own work**, finished or half-finished — a real edit that belongs
     in PR #{pr_number}. Finish it, run the repo's tests and lint, then commit and
     `git push origin HEAD`.
   - **Not the PR's work** — generated files, build/tooling droppings (an
     `expo prebuild`, a formatter run, a lockfile a test rewrote), scratch or
     debug leftovers. Restore or delete them: `git checkout --`, `git restore`,
     `git clean -fd` for untracked scratch.
   When you genuinely cannot tell, treat it as the PR's work and commit it —
   an extra reviewed commit is recoverable, a discarded edit is not.
3. Leave `git status` clean.

Do NOT merge the PR, do NOT run `gh pr create`, do NOT rebase, and do NOT touch
commits that are already pushed. If you push, the orchestrator sends the PR back
through CI before merging.

Done = clean `git status` (and a pushed commit, if you made one)."""
