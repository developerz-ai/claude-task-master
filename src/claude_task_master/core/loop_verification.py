"""Verification and fix-PR helpers for OrchestratorLoop.

Mixin providing ``_verify_success``, ``_run_verification_fix``,
``_wait_for_fix_pr_merge``, ``_poll_fix_pr_ci``, and ``_fix_pr_ci_failure``.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from typing import TYPE_CHECKING

from . import console
from .agent import ModelType
from .state import TaskState

if TYPE_CHECKING:
    from .orchestrator import WorkLoopOrchestrator


class _LoopVerificationMixin:
    """Mixin that provides verification and fix-PR helpers to OrchestratorLoop.

    Cross-mixin calls to ``_build_completed_tasks_summary``, ``_checkout_to_main``,
    and ``_get_current_branch`` are resolved at runtime via MRO on the concrete
    ``OrchestratorLoop`` class (which inherits from ``_LoopContextMixin``).
    """

    _orc: WorkLoopOrchestrator  # set by OrchestratorLoop.__init__

    # ------------------------------------------------------------------

    def _verify_success(self, state: TaskState) -> dict[str, object]:
        """Verify success criteria are met.

        Args:
            state: Current task state (used to summarise completed tasks/PRs).

        Returns:
            Dict with ``'success'`` (bool) and ``'details'`` (str) keys.
        """
        orc = self._orc
        criteria = orc.state_manager.load_criteria()
        if not criteria:
            return {"success": True, "details": "No criteria specified"}

        context = orc.state_manager.load_context()
        tasks_summary = self._build_completed_tasks_summary(state)  # type: ignore[attr-defined]
        result = orc.agent.verify_success_criteria(
            criteria=criteria, context=context, tasks_summary=tasks_summary
        )
        return {
            "success": bool(result.get("success", False)),
            "details": result.get("details", ""),
        }

    def _run_verification_fix(self, verification_details: str, state: TaskState) -> bool:
        """Run agent to fix verification failures and create a PR.

        Args:
            verification_details: Details of what failed during verification.
            state: Current task state.

        Returns:
            True if fix was attempted (PR created or at least committed).
        """
        orc = self._orc
        console.info("Running agent to fix verification failures...")
        criteria = orc.state_manager.load_criteria() or ""
        context = orc.state_manager.load_context()

        task_description = f"""Verification of success criteria has FAILED.

**Success Criteria:**
{criteria}

**Verification Result:**
{verification_details}

**Your Task:**
1. Read the verification details carefully to understand what failed
2. Fix all issues identified in the verification
3. Run tests/lint locally to verify the fixes work
4. Commit your changes with a descriptive message
5. Push to a new branch and create a PR

IMPORTANT: You must fix ALL verification failures, not just some of them.
After fixing everything, run the tests again to confirm they pass.

After completing your fixes, end with: TASK COMPLETE"""

        try:
            coding_style = orc.state_manager.load_coding_style()
            orc.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=ModelType.OPUS,
                create_pr=True,
                coding_style=coding_style,
            )
            state.session_count += 1
            orc.state_manager.save_state_merged(state)
            return True
        except Exception as e:
            # Deferred import so tests can patch orchestrator_loop.console
            import claude_task_master.core.orchestrator_loop as _oloop  # noqa: PLC0415

            _oloop.console.error(f"Fix session failed: {e}")
            return False

    def _wait_for_fix_pr_merge(self, state: TaskState) -> bool:
        """Wait for fix PR to pass CI and merge it.

        Attempts to fix CI failures (up to 2 retries) before giving up.

        Args:
            state: Current task state.

        Returns:
            True if PR was merged successfully.
        """
        orc = self._orc
        try:
            pr_number = orc.github_client.get_pr_for_current_branch()
            if not pr_number:
                console.warning("No PR found for fix branch")
                return False
            console.success(f"Fix PR #{pr_number} detected")
            state.current_pr = pr_number
            if state.pr_start_time is None:
                state.pr_start_time = datetime.now()
            orc.state_manager.save_state_merged(state)
        except Exception as e:
            console.warning(f"Could not detect fix PR: {e}")
            return False

        max_ci_fix_attempts = 2
        ci_fix_attempt = 0

        while ci_fix_attempt <= max_ci_fix_attempts:
            # Route through orc.* so patch.object on orchestrator intercepts it.
            ci_result = orc._poll_fix_pr_ci(pr_number, state)

            if ci_result == "success":
                break
            elif ci_result == "failure":
                ci_fix_attempt += 1
                if ci_fix_attempt > max_ci_fix_attempts:
                    console.error(f"Fix PR CI failed after {ci_fix_attempt - 1} fix attempts")
                    return False
                console.info(
                    f"Attempting to fix CI failure ({ci_fix_attempt}/{max_ci_fix_attempts})..."
                )
                # Route through orc.* so patch.object on orchestrator intercepts it.
                if not orc._fix_pr_ci_failure(pr_number, state):
                    console.error("Failed to fix CI issues")
                    return False
                console.info("Waiting 60s for CI to restart...")
                import claude_task_master.core.orchestrator_loop as _oloop  # noqa: PLC0415

                if not _oloop.interruptible_sleep(60):
                    return False
            else:
                return False

        if state.options.auto_merge:
            try:
                console.info(f"Merging fix PR #{pr_number}...")
                orc.github_client.merge_pr(pr_number, admin=state.options.admin_merge)
                console.success(f"Fix PR #{pr_number} merged!")
                self._checkout_to_main()  # type: ignore[attr-defined]
                return True
            except Exception as e:
                console.error(f"Failed to merge fix PR: {e}")
                return False
        else:
            console.info(f"Fix PR #{pr_number} ready to merge (auto_merge disabled)")
            console.detail("Merge manually then run 'claudetm resume'")
            return False

    def _poll_fix_pr_ci(self, pr_number: int, state: TaskState) -> str:
        """Poll CI status for a fix PR.

        Args:
            pr_number: The PR number to check.
            state: Current task state.

        Returns:
            ``"success"``, ``"failure"``, or ``"interrupted"``.
        """
        orc = self._orc
        max_wait = 7200
        poll_interval = 10
        waited = 0

        while waited < max_wait:
            try:
                pr_status = orc.github_client.get_pr_status(pr_number)
                if pr_status.ci_state == "SUCCESS":
                    console.success("Fix PR CI passed!")
                    return "success"
                elif pr_status.ci_state in ("FAILURE", "ERROR"):
                    console.warning("Fix PR CI failed")
                    return "failure"
                else:
                    console.info(f"Waiting for fix PR CI... ({pr_status.checks_pending} pending)")
                    import claude_task_master.core.orchestrator_loop as _oloop  # noqa: PLC0415

                    if not _oloop.interruptible_sleep(poll_interval):
                        return "interrupted"
                    waited += poll_interval
            except Exception as e:
                console.warning(f"Error checking CI: {e}")
                import claude_task_master.core.orchestrator_loop as _oloop  # noqa: PLC0415

                if not _oloop.interruptible_sleep(poll_interval):
                    return "interrupted"
                waited += poll_interval

        console.warning("Timed out waiting for fix PR CI")
        return "interrupted"

    def _fix_pr_ci_failure(self, pr_number: int, state: TaskState) -> bool:
        """Fix CI failures on a fix PR.

        Args:
            pr_number: The PR number with failing CI.
            state: Current task state.

        Returns:
            True if fix session completed successfully.
        """
        orc = self._orc
        try:
            orc.pr_context.save_ci_failures(pr_number)
            has_ci, has_comments, pr_dir_path = orc.pr_context.get_combined_feedback(pr_number)

            if not has_ci and not has_comments:
                console.warning("No CI failures or comments found to fix")
                return False

            ci_path = f"{pr_dir_path}/ci/" if pr_dir_path else ".claude-task-master/debugging/"

            task_description = f"""
Fix PR CI Failure

The CI checks have failed for this fix PR. Your task is to:

1. Read the CI failure logs in `{ci_path}`
2. Understand what tests/lints are failing
3. Fix the issues in the codebase
4. Run tests locally to verify fixes (check package.json, Makefile, or pyproject.toml for test commands)
5. Commit and push the fixes

Important:
- Only fix issues identified in the CI logs
- Run tests locally before committing
- Push changes to trigger a new CI run
"""

            context = orc.state_manager.load_context()
            coding_style = orc.state_manager.load_coding_style()
            # Route through orc.* so patch.object on orchestrator intercepts it.
            current_branch = orc._get_current_branch()

            head_branch = None
            try:
                head_branch = orc.github_client.get_pr_status(pr_number).head_branch
            except Exception as e:
                console.warning(f"Could not fetch PR head branch: {e}")

            if head_branch and head_branch != current_branch:
                try:
                    subprocess.run(
                        ["git", "checkout", head_branch],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    console.info(f"Checked out PR branch {head_branch}")
                except Exception as e:
                    console.warning(f"Failed to checkout {head_branch}: {e}")

            orc.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=ModelType.OPUS,
                required_branch=head_branch or current_branch,
                coding_style=coding_style,
                create_pr=False,
                push_only=True,
            )

            state.session_count += 1
            orc.state_manager.save_state_merged(state)
            return True

        except Exception as e:
            console.error(f"Failed to fix CI issues: {e}")
            return False


__all__ = ["_LoopVerificationMixin"]
