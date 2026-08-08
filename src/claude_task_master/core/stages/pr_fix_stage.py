"""PRFixStageMixin — CI-failure handling and combined CI+comments task builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import console
from ..agent import ModelType
from ..shutdown import interruptible_sleep
from .ci_stage import _CIStage

if TYPE_CHECKING:
    from ..state import TaskState


class _PRFixStage(_CIStage):
    """Mixin: handle CI failures and build CI+review combined task prompts."""

    def handle_ci_failed_stage(self, state: TaskState) -> int | None:
        """Handle CI failure - run agent to fix issues.

        This method now also fetches PR comments (from CodeRabbit, reviewers, etc.)
        when saving CI failures, so the agent can fix BOTH CI issues AND address
        review comments in a single step.
        """
        # A failure whose jobs never executed a step is the platform's, not the
        # branch's: no edit can fix it, and spending an agent session on it ends
        # with no commit, hence no new run, hence the next poll re-reading this
        # very failure. Re-run the jobs instead.
        infra_runs = self._infrastructural_runs(state)
        if infra_runs:
            return self._rerun_failed_ci(
                state,
                infra_runs,
                reason="no job in the failing run(s) executed a single step",
            )

        console.info("CI failed - running agent to fix...")

        # Cap consecutive CI-fix cycles to avoid an infinite fix loop
        state.ci_fix_attempts += 1
        if state.ci_fix_attempts > self.MAX_CI_FIX_ATTEMPTS:
            console.error(
                f"CI failed {state.ci_fix_attempts} times — blocking, manual intervention required"
            )
            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1
        self.state_manager.save_state(state)

        # Save CI failure logs (this also saves PR comments via _also_save_comments=True)
        self.pr_context.save_ci_failures(state.current_pr)

        # Check what feedback we have (CI failures and/or comments)
        has_ci, has_comments, pr_dir_path = self.pr_context.get_combined_feedback(state.current_pr)

        # Build combined task description
        task_description = self._build_combined_ci_comments_task(
            state.current_pr, has_ci, has_comments, pr_dir_path
        )

        # Run agent with Opus for complex debugging
        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        required_branch = self._get_pr_head_branch(state)
        head_before = self._head_sha()
        # Fix an EXISTING PR: push the fix to re-trigger CI, never open a new PR
        # or rebase (push_only routes through _build_push_only_execution, which
        # forbids rebasing already-reviewed commits).
        self.agent.run_work_session(
            task_description=task_description,
            context=context,
            model_override=ModelType.OPUS,
            required_branch=required_branch,
            create_pr=False,
            push_only=True,
        )

        # Did the session actually deliver? Advancing on an undelivered fix would
        # read the previous push's green CI as this fix's.
        unfinished = self._fix_session_unfinished_reason(required_branch)
        if unfinished:
            # This attempt fixed nothing, so it must not consume the CI-fix
            # budget — that counter bounds "the fix didn't work", not "no fix
            # was produced"; _handle_unfinished_fix has its own bound.
            state.ci_fix_attempts = max(0, state.ci_fix_attempts - 1)
            return self._handle_unfinished_fix(state, unfinished, "ci_failed")
        state.fix_finish_attempts = 0

        # A clean tree with nothing unpushed is also what "I read the logs and
        # concluded the diff is fine" looks like — the session ends reporting
        # success having committed nothing. Nothing was pushed, so GitHub starts
        # no new run, so waiting_ci would re-read the *same* red run as a fresh
        # failure and burn another fix attempt, every cycle, until the budget
        # blocks the task. Re-run the failed jobs instead: an agent that found
        # nothing to change is evidence the failure is not in the diff.
        if self._head_sha() == head_before:
            # This attempt produced no fix, so it must not consume the CI-fix
            # budget either — that counter bounds "the fix didn't work".
            state.ci_fix_attempts = max(0, state.ci_fix_attempts - 1)
            return self._rerun_failed_ci(
                state,
                self.pr_context.failing_run_ids(state.current_pr),
                reason="the fix session finished without committing anything",
            )

        # Wait for CI to start after push
        console.info("Waiting 60s for CI to start...")
        if not interruptible_sleep(60):
            return None

        state.workflow_stage = "waiting_ci"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None

    def _infrastructural_runs(self, state: TaskState) -> list[int]:
        """Return the PR's failing runs whose jobs never executed a step.

        Empty unless *every* failing run looks that way. A mixed red — one
        workflow genuinely broken, another killed in the queue — is still a
        real failure the fix agent has to see, and re-running would only delay
        it.

        Args:
            state: Current task state.

        Returns:
            The failing run IDs when all of them are infrastructural, else [].
        """
        from ...github.ci_infra import CIInfraDetector  # noqa: PLC0415

        try:
            reported = self.pr_context.failing_run_ids(state.current_pr)
            # None means GitHub could not be asked. Unknown is not "the platform
            # is at fault" — the ordinary fix path handles it, and the no-commit
            # branch below re-asks with a bounded retry.
            if not reported:
                return []
            run_ids = [int(run_id) for run_id in reported]
            detector = CIInfraDetector(repo=self.github_client._get_repo_info())
            all_infra = all(detector.never_ran(run_id) for run_id in run_ids)
        except Exception:
            # Cannot tell — fall through to the ordinary fix path rather than
            # re-running a failure that may well be the branch's own.
            return []

        return run_ids if all_infra else []

    def _rerun_failed_ci(
        self, state: TaskState, run_ids: list[int] | None, reason: str
    ) -> int | None:
        """Re-run the PR's failed jobs and go back to waiting on CI.

        The escape hatch for a red PR that no code change addresses. It is
        bounded because the two causes it serves diverge after a retry or two:
        a flake clears, an outage does not, and neither is improved by looping.

        Args:
            state: Current task state.
            run_ids: The failing workflow runs to re-run, or None when GitHub
                could not be asked which they are.
            reason: Why re-running is the right move, shown to the user.

        Returns:
            None to continue the loop, 1 once a budget is spent or GitHub
            refused outright.
        """
        if run_ids is None:
            # Not "nothing to re-run" — "we could not find out". Blocking on a
            # momentary API failure is the shape of bug this method exists to
            # remove, so it takes the bounded transient path instead.
            return self._retry_transient(
                state,
                "ci_rerun_lookup",
                f"Could not read the PR's failing checks to re-run them ({reason})",
            )
        self._clear_transient("ci_rerun_lookup")

        if not run_ids:
            console.error(
                f"CI is red but no workflow run could be identified to re-run ({reason}) — "
                f"blocking, manual intervention required"
            )
            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1

        if state.ci_rerun_attempts >= self.MAX_CI_RERUN_ATTEMPTS:
            console.error(
                f"CI still red after {self.MAX_CI_RERUN_ATTEMPTS} job re-runs ({reason}) — "
                f"blocking, manual intervention required"
            )
            console.detail(
                "Nothing in the diff is implicated, so this is the CI platform's to fix: "
                f"check the runner pool, then `gh run rerun {run_ids[0]} --failed`."
            )
            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1

        console.warning(
            f"Re-running failed CI jobs ({reason}) — "
            f"attempt {state.ci_rerun_attempts + 1}/{self.MAX_CI_RERUN_ATTEMPTS}"
        )

        from ...github.ci_rerun import CIRerunner  # noqa: PLC0415
        from ...github.exceptions import GitHubTimeoutError  # noqa: PLC0415

        try:
            rerunner = CIRerunner(repo=self.github_client._get_repo_info())
        except Exception as e:
            return self._retry_transient(
                state, "ci_rerun", f"Could not reach GitHub to re-run: {e}"
            )
        self._clear_transient("ci_rerun")

        restarted: list[int] = []
        unanswered: list[int] = []
        for run_id in run_ids:
            try:
                if rerunner.rerun_failed_jobs(run_id):
                    restarted.append(run_id)
            except GitHubTimeoutError:
                unanswered.append(run_id)

        if not restarted and not unanswered:
            console.error(
                "GitHub refused to re-run any of the failed jobs — "
                "blocking, manual intervention required"
            )
            console.detail(f"Runs: {run_ids}. A run older than its retention window cannot re-run.")
            state.status = "blocked"
            self.state_manager.save_state(state)
            return 1

        if unanswered:
            # A timed-out request may already have restarted the run. Asking
            # again would be refused ("already running") and read as a final
            # no; polling settles it either way — pending means it landed, red
            # again means it did not, and the budget is spent either way so a
            # permanently timing-out `gh` cannot loop.
            console.detail(f"Re-run request timed out for run(s) {unanswered} — CI will confirm")

        # Only now: the budget counts re-runs GitHub was actually asked to
        # perform, not attempts that never reached it.
        state.ci_rerun_attempts += 1

        if restarted:
            console.detail(
                f"Re-running {len(restarted)} of {len(run_ids)} failing run(s): {restarted}"
            )

        # The re-run starts the checks over, so the poll timer must too —
        # otherwise the previous wait counts against CI_POLL_TIMEOUT and the
        # fresh run is declared timed out before it can finish.
        self._clear_ci_poll_timer(state)
        state.workflow_stage = "waiting_ci"
        self.state_manager.save_state(state)

        console.info("Waiting 60s for CI to restart...")
        if not interruptible_sleep(60):
            return None
        return None

    def _build_combined_ci_comments_task(
        self,
        pr_number: int | None,
        has_ci: bool,
        has_comments: bool,
        pr_dir_path: str,
    ) -> str:
        """Build a combined task description for CI failures and review comments.

        This ensures that both CI failures AND review comments are addressed in
        a single agent session, avoiding the need for multiple fix cycles.

        Args:
            pr_number: The PR number.
            has_ci: Whether there are CI failure logs.
            has_comments: Whether there are review comments.
            pr_dir_path: Path to the PR directory.

        Returns:
            Task description string for the agent.
        """
        ci_path = f"{pr_dir_path}/ci/" if pr_dir_path else ".claude-task-master/debugging/"
        comments_path = (
            f"{pr_dir_path}/comments/" if pr_dir_path else ".claude-task-master/debugging/"
        )
        resolve_json_path = (
            f"{pr_dir_path}/resolve-comments.json"
            if pr_dir_path
            else ".claude-task-master/debugging/resolve-comments.json"
        )

        # Build the appropriate task description based on what feedback exists
        if has_ci and has_comments:
            # Both CI failures and comments - handle together!
            return f"""CI has failed for PR #{pr_number} AND there are review comments to address.

**IMPORTANT: Fix BOTH CI failures AND address review comments in this session.**
This is more efficient than fixing them separately.

## Step 1: Read ALL Feedback

**CI Failure logs:** `{ci_path}`
**Review comments:** `{comments_path}`

Use Glob to find all .txt files in both directories, then Read each one.

## Step 2: Fix CI Failures (Priority 1)

- Read ALL files in the ci/ directory
- Understand ALL error messages (lint, tests, types, etc.)
- Fix everything that's failing - don't skip anything
- Pre-existing issues, flaky tests, lint errors - fix them all

## Step 3: Address Review Comments (Priority 2)

- Read ALL comment files in the comments/ directory
- For each comment:
  - Make the requested change, OR
  - Explain why it's not needed

## Step 4: Verify, Commit, and Push

1. Run tests/lint locally to verify ALL passes
2. Commit all fixes together with a descriptive message
3. Push to update the existing PR: `git push origin HEAD` (CI re-runs on push). Do NOT rebase or force-push — it rewrites already-reviewed commits and breaks the PR's review threads. If push is rejected: `git pull --rebase origin HEAD`, resolve conflicts, re-test, then push.
4. Create a resolution summary file at: `{resolve_json_path}`

**Resolution file format:**
```json
{{
  "pr": {pr_number},
  "resolutions": [
    {{
      "thread_id": "THREAD_ID_FROM_COMMENT_FILE",
      "action": "fixed|explained|skipped",
      "message": "Brief explanation of what was done"
    }}
  ]
}}
```

Copy the Thread ID from each comment file into the resolution JSON.

**IMPORTANT: DO NOT resolve threads directly using GitHub GraphQL mutations.**
The orchestrator will handle thread resolution automatically after you create the resolution file.

After fixing ALL CI issues AND addressing ALL comments, end with: TASK COMPLETE"""

        elif has_ci:
            # Only CI failures (no comments)
            return f"""CI has failed for PR #{pr_number}.

**Read the CI failure logs from:** `{ci_path}`

Use Glob to find all .txt files, then Read each one to understand the errors.

**IMPORTANT:** Fix ALL CI failures, even if they seem unrelated to your current work.
Your job is to keep CI green. Pre-existing issues, flaky tests, lint errors - fix them all.

Please:
1. Read ALL files in the ci/ directory
2. Understand ALL error messages (lint, tests, types, etc.)
3. Fix everything that's failing - don't skip anything
4. Run tests/lint locally to verify ALL passes
5. Commit fixes with a descriptive message
6. Push to update the existing PR: `git push origin HEAD` (CI re-runs on push). Do NOT rebase or force-push — it rewrites already-reviewed commits and breaks the PR's review threads. If push is rejected: `git pull --rebase origin HEAD`, resolve, re-test, then push.

After fixing, end with: TASK COMPLETE"""

        elif has_comments:
            # Only comments (rare case - CI passed but called with comments only)
            return f"""PR #{pr_number} has review comments to address.

**Read the review comments from:** `{comments_path}`

Use Glob to find all .txt files, then Read each one to understand the feedback.

Please:
1. Read ALL comment files in the comments/ directory
2. For each comment:
   - Make the requested change, OR
   - Explain why it's not needed
3. Run tests to verify
4. Commit fixes with a descriptive message
5. Push to update the existing PR: `git push origin HEAD` (CI re-runs on push). Do NOT rebase or force-push — it rewrites already-reviewed commits and breaks the PR's review threads. If push is rejected: `git pull --rebase origin HEAD`, resolve, re-test, then push.
6. Create a resolution summary file at: `{resolve_json_path}`

**Resolution file format:**
```json
{{
  "pr": {pr_number},
  "resolutions": [
    {{
      "thread_id": "THREAD_ID_FROM_COMMENT_FILE",
      "action": "fixed|explained|skipped",
      "message": "Brief explanation of what was done"
    }}
  ]
}}
```

Copy the Thread ID from each comment file into the resolution JSON.

**IMPORTANT: DO NOT resolve threads directly using GitHub GraphQL mutations.**
The orchestrator will handle thread resolution automatically after you create the resolution file.

After addressing ALL comments and creating the resolution file, end with: TASK COMPLETE"""

        else:
            # Neither CI failures nor comments (shouldn't happen in ci_failed stage)
            return f"""PR #{pr_number} needs attention.

Please check the PR status and ensure everything is working correctly.
Run tests/lint locally to verify.

After verifying, end with: TASK COMPLETE"""
