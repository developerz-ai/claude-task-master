"""ReleaseStageMixin — release verification and quick-fix PR after merge."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import console
from ..agent import ModelType
from ..shutdown import interruptible_sleep
from .merge_stage import _MergeStage

if TYPE_CHECKING:
    from ..state import TaskState


class _ReleaseStage(_MergeStage):
    """Mixin: post-merge release verification and quick-fix PR creation."""

    def handle_releasing_stage(self, state: TaskState) -> int | None:
        """Handle release verification — check deployment health after merge.

        This runs after a PR is merged when auto_merge is enabled.
        The agent verifies the deployment using whatever access is available
        (health checks, deploy status, error monitoring, migration status).

        If nothing is checkable, this is a no-op pass-through.
        If checks fail, transitions to release_fix for a quick-fix PR.
        Max 5 fix attempts before moving on (don't block the pipeline).
        """
        from ..prompts_release import (
            build_release_check_prompt,
            extract_pr_release_checks,
            parse_release_check_result,
        )

        release_guide = self.state_manager.load_release_guide()
        if not release_guide:
            console.info("No release guide — skipping release verification")
            self._advance_to_next_task(state)
            return None

        # Wait for deployments to start/finish before running release checks.
        # Without this, checks run before the deploy pipeline has picked up the
        # merge, so there's nothing meaningful to monitor.
        console.info("Waiting 90s for deployment to start before release checks...")
        if not interruptible_sleep(90):
            return None

        # Extract per-PR release checks from plan.md
        pr_release_checks = None
        plan = self.state_manager.load_plan()
        if plan and state.current_pr is not None:
            # Find the PR group number for the current task
            from ..task_group import parse_tasks_with_groups

            tasks, groups = parse_tasks_with_groups(plan)
            for group in groups:
                if state.current_task_index in group.task_indices:
                    # Extract numeric PR group number (e.g., "pr_1" → 1)
                    group_num_str = group.id.replace("pr_", "")
                    try:
                        pr_group_number = int(group_num_str)
                        pr_release_checks = extract_pr_release_checks(plan, pr_group_number)
                    except ValueError:
                        pass  # Non-numeric group ID (e.g., "default"), skip per-PR checks
                    break

        # Get PR title for context
        pr_title = None
        if state.current_pr is not None:
            try:
                pr_status = self.github_client.get_pr_status(state.current_pr)
                pr_title = pr_status.title
            except Exception:
                pass

        # Build and run release check prompt
        prompt = build_release_check_prompt(
            release_guide=release_guide,
            pr_release_checks=pr_release_checks,
            pr_number=state.current_pr,
            pr_title=pr_title,
        )

        console.info(f"Verifying release for PR #{state.current_pr or '?'}...")

        try:
            # Verify-only: run the release prompt directly, NOT via
            # run_work_session. The work session wraps it in the create-PR
            # contract ("push + open a PR, don't finish without a PR URL"),
            # which contradicts the verify-only RELEASE_CHECK marker — the
            # model then drops the marker and parse_release_check_result
            # defaults to SKIP, so a release check could never FAIL.
            result = self.agent.run_release_check(
                prompt,
                model_override=ModelType.SONNET,  # Sonnet for speed
            )
            output = result.get("output", "")
        except Exception as e:
            console.warning(f"Release verification error: {e}")
            console.detail("Skipping release verification and continuing")
            self._advance_to_next_task(state)
            return None

        # Parse the result
        check_result = parse_release_check_result(output)

        if check_result["status"] == "pass":
            console.success("Release verification passed!")
            self._advance_to_next_task(state)
            return None
        elif check_result["status"] == "skip":
            console.info("Release verification skipped (nothing to check)")
            self._advance_to_next_task(state)
            return None
        else:
            # Release check failed
            max_release_fixes = 5
            if state.release_fix_attempts >= max_release_fixes:
                console.warning(
                    f"Release verification failed after {max_release_fixes} fix attempts — "
                    "moving on to next task"
                )
                self._advance_to_next_task(state)
                return None

            console.warning("Release verification failed — attempting quick fix")
            # Persist the failure details so the fix session isn't blind — the
            # next handle_release_fix_stage injects them as "## Failed Checks".
            # Keep only the tail (FAIL marker + reasoning) to bound state size.
            state.release_fix_details = check_result["details"][
                -self.RELEASE_FAIL_DETAILS_MAX_CHARS :
            ]
            state.workflow_stage = "release_fix"
            self.state_manager.save_state(state)
            return None

    def handle_release_fix_stage(self, state: TaskState) -> int | None:
        """Handle release fix — create a small fix PR for deployment issues.

        This creates a quick-fix PR (capped scope) to address release
        verification failures. After the fix PR merges, re-runs release
        verification.

        Max 5 attempts before giving up and moving to next task.
        """
        state.release_fix_attempts += 1
        state.in_release_fix = True
        self.state_manager.save_state(state)
        console.info(
            f"Release fix attempt {state.release_fix_attempts} for PR #{state.current_pr or '?'}..."
        )

        release_guide = self.state_manager.load_release_guide()
        failed_checks = state.release_fix_details or "No failure details captured."

        task_description = f"""A release verification check FAILED after PR #{state.current_pr or "?"} was merged.

## Release Guide
{release_guide or "No release guide available."}

## Failed Checks
{failed_checks}

## Instructions

Create a SMALL fix to resolve the deployment issue. This must be:
- Under 50 lines changed
- A targeted fix, not a refactor
- Committed, pushed, and PR created

Common fixes:
- Missing env var → add to config
- Health check failing → fix the endpoint
- Migration not applied → run migration command
- New errors in Sentry → fix the bug

Steps:
1. Diagnose the issue (check deploy status, health endpoints, error logs)
2. Make a minimal fix
3. Commit with message: "fix: release fix for PR #{state.current_pr or "?"}"
4. Push and create PR

End with: TASK COMPLETE"""

        try:
            context = self.state_manager.load_context()
        except Exception:
            context = ""

        try:
            self.agent.run_work_session(
                task_description=task_description,
                context=context,
                model_override=ModelType.SONNET,  # Sonnet for speed
            )
        except Exception as e:
            console.warning(f"Release fix failed: {e}")
            console.detail("Moving on to next task")
            self._advance_to_next_task(state)
            return None

        # Wait for CI to start on the fix PR
        console.info("Waiting 60s for CI to start on release fix PR...")
        if not interruptible_sleep(60):
            return None

        # Reset current_pr so pr_created re-discovers the new fix PR from the current branch
        state.current_pr = None
        state.workflow_stage = "pr_created"
        state.session_count += 1
        self.state_manager.save_state(state)
        return None
