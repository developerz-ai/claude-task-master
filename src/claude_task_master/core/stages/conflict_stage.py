"""_ConflictStage — AI resolution of merge conflicts on an open PR.

When ``ready_to_merge`` finds a PR whose mergeable state is ``CONFLICTING`` (the
base branch moved under it), the run used to block for manual resolution. This
stage hands the conflict to an agent session instead: merge the base branch into
the PR branch, resolve every hunk keeping both sides' intent, re-run the tests,
commit, push. The push re-triggers CI, so the PR re-enters the normal
``waiting_ci`` → reviews → merge path.

SRP: this module owns *the conflict-resolution session* — building its prompt and
running it. It does not decide mergeability (``_MergeStage`` does) and it does not
drive git itself; the agent owns the working tree, exactly as it does for a
CI-fix session.

Bounded on purpose: ``MAX_CONFLICT_FIX_ATTEMPTS`` passes per PR, after which the
run blocks with the same "manual resolution required" outcome as before. A merge
(not a rebase) is used deliberately — rebasing rewrites already-reviewed commits
and breaks the PR's review threads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import console
from ..agent import ModelType
from ..shutdown import interruptible_sleep
from .merge_stage import _MergeStage

if TYPE_CHECKING:
    from ..state import TaskState


class _ConflictStage(_MergeStage):
    """Mixin: resolve merge conflicts on an open PR with an agent session."""

    def handle_resolving_conflicts_stage(self, state: TaskState) -> int | None:
        """Run an agent session to resolve the current PR's merge conflicts.

        Args:
            state: Current task state. ``current_pr`` must be set; the attempt
                counter is incremented by the caller (``_MergeStage``) before the
                stage is entered.

        Returns:
            1 if the run is blocked (no PR, or the session failed), otherwise
            None to continue the loop with the PR back in ``waiting_ci``.
        """
        pr_number = state.current_pr
        if pr_number is None:
            # Nothing to resolve against — fall back to the normal path.
            state.workflow_stage = "ready_to_merge"
            self.state_manager.save_state(state)
            return None

        console.info(
            f"Resolving merge conflicts on PR #{pr_number} "
            f"(attempt {state.conflict_fix_attempts}/{self.MAX_CONFLICT_FIX_ATTEMPTS})..."
        )

        base_branch = self._get_pr_base_branch(pr_number)
        required_branch = self._get_pr_head_branch(state)

        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        task_description = self._build_conflict_resolution_task(
            pr_number, base_branch, state.conflict_fix_attempts
        )

        try:
            self.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=ModelType.OPUS,
                required_branch=required_branch,
                create_pr=False,
                push_only=True,
                target_branch=base_branch,
            )
        except Exception as e:
            console.error(f"Conflict-resolution session failed: {e}")
            console.detail(f"Resolve the conflicts on PR #{pr_number} manually, then resume")
            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1

        # The push re-triggers CI; GitHub also needs a moment to recompute
        # mergeability against the new head.
        console.info("Waiting 60s for CI to start...")
        if not interruptible_sleep(60):
            return None

        state.workflow_stage = "waiting_ci"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None

    def _get_pr_base_branch(self, pr_number: int) -> str:
        """Return the PR's base branch, falling back to ``main`` if unavailable."""
        try:
            return self.github_client.get_pr_status(pr_number).base_branch or "main"
        except Exception:
            return "main"

    def _build_conflict_resolution_task(
        self, pr_number: int, base_branch: str, attempt: int
    ) -> str:
        """Build the conflict-resolution task description for the agent.

        Args:
            pr_number: The PR whose branch conflicts with its base.
            base_branch: The PR's base branch (what to merge in).
            attempt: 1-based attempt number, surfaced so a retry knows the
                previous pass left the branch unresolved.

        Returns:
            Task description string for the agent session.
        """
        retry_note = (
            f"\n**This is attempt {attempt}** — a previous pass did not clear the conflict. "
            "Check `git status` first: the branch may still be mid-merge.\n"
            if attempt > 1
            else ""
        )

        return f"""PR #{pr_number} has merge conflicts with `{base_branch}` and cannot be merged.
{retry_note}
Resolve them so the PR can merge.

## Step 1: Bring in the base branch

```bash
git status                                  # confirm you are on the PR branch
git fetch origin {base_branch}
git merge origin/{base_branch}
```

Use `git merge`, NOT `git rebase` — rebasing rewrites already-reviewed commits and
breaks the PR's review threads.

## Step 2: Resolve every conflicted file

`git diff --name-only --diff-filter=U` lists the unmerged files. For each one:

- Read it and find every hunk: `<<<<<<<` … `=======` … `>>>>>>>`.
- Resolve by combining BOTH sides. Never blindly delete one side — the base side
  and the PR side each changed something on purpose; keep both intents coherent.
  Drop a side only when it is genuinely superseded, and only after reading enough
  of the surrounding code to be sure.
- Remove ALL conflict markers. A leftover `<<<<<<<`, `=======`, or `>>>>>>>` is a
  broken file.
- `git add` the file once it is clean.

Semantic conflicts count too: if the base renamed a function the PR calls, the
merged result must compile and pass tests, not merely be marker-free.

## Step 3: Verify

Run the repo's tests and lint. The merge can break code that neither side broke
alone — that is the point of running them here.

## Step 4: Commit and push

```bash
git commit --no-edit                        # completes the merge commit
git push origin HEAD
```

If `git status` shows the merge already committed, skip straight to the push.
Do NOT run `gh pr create` (the PR exists) and do NOT merge the PR yourself — the
orchestrator handles that once CI is green.

After the push succeeds, end with: TASK COMPLETE"""
