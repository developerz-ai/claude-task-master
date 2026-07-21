"""_ConflictStage — agent session that makes a PR mergeable against the live base.

``ready_to_merge`` routes here in two cases, both meaning "this PR is not ready to
merge into the base as it stands today":

- **CONFLICTING** — the base moved under the PR and git cannot merge it. Always
  routed here.
- **BEHIND** — the base moved but still merges cleanly. Green CI only proves the
  branch passed against the base *as it was when CI ran*; the merge result itself
  is untested. Only routed here under ``--sync-before-merge`` (off by default):
  paying an agent session plus a CI round on every PR main outpaces is not worth
  the rare semantic clash it catches.

Either way the fix is the agent's job, not a button: rebase the PR branch onto the
live base, resolve whatever that surfaces (textual hunks or semantic breakage),
re-run the tests, force-push with lease. The push re-triggers CI, so the PR
re-enters the normal ``waiting_ci`` → reviews → merge path and the *rebased*
tree is what gets verified before the merge.

SRP: this module owns *the make-it-mergeable session* — building its prompt and
running it. It does not decide mergeability (``_MergeStage`` does) and it does not
drive git itself; the agent owns the working tree, exactly as it does for a
CI-fix session.

Bounded on purpose: ``MAX_CONFLICT_FIX_ATTEMPTS`` conflict passes (then the run
blocks) and ``MAX_BRANCH_SYNC_ATTEMPTS`` sync passes (then a green-but-behind PR
merges as-is rather than chasing a fast-moving base forever).
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
    """Mixin: bring an open PR up to date with its base via an agent session."""

    def handle_resolving_conflicts_stage(self, state: TaskState) -> int | None:
        """Run an agent session to make the current PR mergeable against its base.

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

        base_branch, conflicted = self._get_pr_merge_context(pr_number)
        if conflicted:
            console.info(
                f"Resolving merge conflicts on PR #{pr_number} "
                f"(attempt {state.conflict_fix_attempts}/{self.MAX_CONFLICT_FIX_ATTEMPTS})..."
            )
            attempt = state.conflict_fix_attempts
        else:
            console.info(
                f"Syncing PR #{pr_number} with {base_branch} "
                f"(attempt {state.branch_sync_attempts}/{self.MAX_BRANCH_SYNC_ATTEMPTS})..."
            )
            attempt = state.branch_sync_attempts

        required_branch = self._get_pr_head_branch(state)

        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        task_description = self._build_conflict_resolution_task(
            pr_number, base_branch, attempt, conflicted=conflicted
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
                # Rebasing onto the base IS this session's job, so the push-only
                # boilerplate must not also tell the agent never to rebase.
                allow_rebase=True,
            )
        except Exception as e:
            console.error(f"Base-sync session failed: {e}")
            console.detail(
                f"Bring PR #{pr_number} up to date with {base_branch} manually, then resume"
            )
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
        return self._get_pr_merge_context(pr_number)[0]

    def _get_pr_merge_context(self, pr_number: int) -> tuple[str, bool]:
        """Return ``(base_branch, is_conflicted)`` for the PR.

        Degrades to ``("main", False)`` when the status cannot be fetched: a sync
        prompt is the safe default, since it works whether or not the merge turns
        out to conflict.
        """
        try:
            status = self.github_client.get_pr_status(pr_number)
        except Exception:
            return "main", False
        return status.base_branch or "main", status.mergeable == "CONFLICTING"

    def _build_conflict_resolution_task(
        self, pr_number: int, base_branch: str, attempt: int, conflicted: bool = True
    ) -> str:
        """Build the make-it-mergeable task description for the agent.

        Args:
            pr_number: The PR to bring up to date.
            base_branch: The PR's base branch (what to merge in).
            attempt: 1-based attempt number, surfaced so a retry knows the
                previous pass left the branch unresolved.
            conflicted: True when git reports actual conflicts, False when the
                branch is merely behind the base.

        Returns:
            Task description string for the agent session.
        """
        retry_note = (
            f"\n**This is attempt {attempt}** — a previous pass did not finish the job. "
            "Check `git status` first: the branch may still be mid-rebase.\n"
            if attempt > 1
            else ""
        )

        headline = (
            f"PR #{pr_number} has merge conflicts with `{base_branch}` and cannot be merged."
            if conflicted
            else (
                f"PR #{pr_number} is behind `{base_branch}`. CI passed against an older "
                f"{base_branch}, so the merged result is untested — bring the branch up to "
                "date and let CI verify the combination before it merges."
            )
        )

        return f"""{headline}
{retry_note}
Rebase the branch onto the live base so the PR can merge safely.

## Step 1: Start the rebase

```bash
git status                                  # confirm you are on the PR branch
git fetch origin {base_branch}
git rebase origin/{base_branch}
```

Rebase, not merge — the PR's history stays a clean series of commits on top of
`{base_branch}` instead of accumulating merge commits.

## Step 2: Resolve every conflicted file

If the rebase finished with no conflicts, skip to Step 3.

A rebase stops once per conflicting commit, so expect to repeat this step.
`git diff --name-only --diff-filter=U` lists the unmerged files. For each one:

- Read it and find every hunk: `<<<<<<<` … `=======` … `>>>>>>>`.
- Resolve by combining BOTH sides. Never blindly delete one side — the base side
  and the PR side each changed something on purpose; keep both intents coherent.
  Drop a side only when it is genuinely superseded, and only after reading enough
  of the surrounding code to be sure.
- Remove ALL conflict markers. A leftover `<<<<<<<`, `=======`, or `>>>>>>>` is a
  broken file.
- `git add` the file once it is clean.

Then `git rebase --continue` and repeat until the rebase reports it is done.
If a hunk is genuinely unresolvable, `git rebase --abort` and say so — never leave
the branch mid-rebase.

Semantic conflicts count too: if the base renamed a function the PR calls, the
rebased result must compile and pass tests, not merely be marker-free.

## Step 3: Verify

Run the repo's tests and lint. The rebase can break code that neither side broke
alone — a semantic clash between what landed on `{base_branch}` and what this PR
changed — and that is exactly what this step exists to catch. If it breaks, fix it
here and commit the fix on top.

## Step 4: Push

```bash
git push --force-with-lease origin HEAD
```

`--force-with-lease` is required: the rebase rewrote the branch, so a plain push is
rejected, and the lease still refuses to clobber commits someone else pushed.
If `git rebase` reported "up to date" and the tests needed no fix, there is nothing
to push — say so and stop.
Do NOT run `gh pr create` (the PR exists) and do NOT merge the PR yourself — the
orchestrator handles that once CI is green.

After the push succeeds, end with: TASK COMPLETE"""
