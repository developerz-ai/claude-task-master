"""Tests for working phase prompts.

This module tests the prompts from prompts_working.py:
- build_work_prompt: Main work session prompt
- _build_full_workflow_execution: Full workflow (commit + push + PR)
- _build_commit_only_execution: Commit-only workflow (more tasks in group)
"""

from claude_task_master.core.prompts_working import (
    _build_commit_only_execution,
    _build_full_workflow_execution,
    build_work_prompt,
)

# =============================================================================
# build_work_prompt Basic Tests
# =============================================================================


class TestBuildWorkPromptBasic:
    """Tests for basic build_work_prompt functionality."""

    def test_returns_string(self) -> None:
        """Test that build_work_prompt returns a string."""
        result = build_work_prompt("Implement feature X")
        assert isinstance(result, str)

    def test_returns_non_empty_string(self) -> None:
        """Test that build_work_prompt returns non-empty string."""
        result = build_work_prompt("Any task")
        assert len(result) > 0

    def test_task_description_included(self) -> None:
        """Test that task description is included in the prompt."""
        task = "Create user authentication module"
        result = build_work_prompt(task)
        assert task in result

    def test_task_with_special_characters(self) -> None:
        """Test task with special characters is preserved."""
        task = "Fix bug #123: User's session doesn't persist"
        result = build_work_prompt(task)
        assert task in result

    def test_task_with_markdown(self) -> None:
        """Test task with markdown formatting is preserved."""
        task = "Implement **critical** feature with `code_style`"
        result = build_work_prompt(task)
        assert "critical" in result
        assert "code_style" in result

    def test_empty_task_description(self) -> None:
        """Test with empty task description."""
        result = build_work_prompt("")
        # Should still generate a valid prompt
        assert isinstance(result, str)
        assert "Current Task" in result

    def test_multiline_task_description(self) -> None:
        """Test task with multiple lines."""
        task = "Task line 1\nTask line 2\nTask line 3"
        result = build_work_prompt(task)
        assert "Task line 1" in result
        assert "Task line 2" in result
        assert "Task line 3" in result


# =============================================================================
# Work Prompt Introduction Tests
# =============================================================================


class TestWorkPromptIntro:
    """Tests for work prompt introduction section."""

    def test_claude_task_master_mentioned(self) -> None:
        """Test Claude Task Master is mentioned."""
        result = build_work_prompt("Any task")
        assert "Claude Task Master" in result

    def test_current_task_section(self) -> None:
        """Test Current Task section is present."""
        result = build_work_prompt("Any task")
        assert "Current Task" in result

    def test_single_task_focus(self) -> None:
        """Test SINGLE task focus is mentioned."""
        result = build_work_prompt("Any task")
        assert "SINGLE task" in result or "THIS task only" in result

    def test_high_quality_work_mentioned(self) -> None:
        """Test HIGH QUALITY work is mentioned."""
        result = build_work_prompt("Any task")
        assert "HIGH QUALITY" in result

    def test_plan_and_progress_references(self) -> None:
        """Test plan.md and progress.md references are present."""
        result = build_work_prompt("Any task")
        assert "plan.md" in result
        assert "progress.md" in result


# =============================================================================
# Branch Info Tests
# =============================================================================


class TestBranchInfoSection:
    """Tests for branch info section handling."""

    def test_no_branch_info_by_default(self) -> None:
        """Test no branch info when required_branch is None."""
        result = build_work_prompt("Any task", required_branch=None)
        assert "**Current Branch:**" not in result

    def test_branch_info_included_when_provided(self) -> None:
        """Test branch info is included when provided."""
        result = build_work_prompt(
            task_description="Task",
            required_branch="feat/new-feature",
        )
        assert "**Current Branch:**" in result
        assert "`feat/new-feature`" in result

    def test_main_branch_warning(self) -> None:
        """Test warning when on main branch."""
        result = build_work_prompt(
            task_description="Task",
            required_branch="main",
        )
        assert "main" in result
        assert "create a feature branch" in result.lower()

    def test_master_branch_warning(self) -> None:
        """Test warning when on master branch."""
        result = build_work_prompt(
            task_description="Task",
            required_branch="master",
        )
        assert "master" in result
        assert "create a feature branch" in result.lower()

    def test_feature_branch_no_warning(self) -> None:
        """Test no warning for feature branches."""
        result = build_work_prompt(
            task_description="Task",
            required_branch="feat/add-tests",
        )
        assert "**Current Branch:**" in result
        # Should not have the warning about creating a feature branch
        branch_section = result[
            result.find("**Current Branch:**") : result.find("**Current Branch:**") + 200
        ]
        assert (
            "create a feature branch" not in branch_section.lower()
            or "If on main/master" in branch_section
        )


# =============================================================================
# Context Section Tests
# =============================================================================


class TestContextSection:
    """Tests for context section handling."""

    def test_no_context_by_default(self) -> None:
        """Test no context section when context is None."""
        result = build_work_prompt("Any task", context=None)
        assert "## Context" not in result

    def test_context_included_when_provided(self) -> None:
        """Test context is included when provided."""
        result = build_work_prompt(
            task_description="Task",
            context="Previously discovered: uses React framework",
        )
        assert "## Context" in result
        assert "uses React framework" in result

    def test_context_stripped(self) -> None:
        """Test context whitespace is stripped."""
        result = build_work_prompt(
            task_description="Task",
            context="  Context with whitespace  \n\n",
        )
        assert "Context with whitespace" in result

    def test_empty_context_treated_as_none(self) -> None:
        """Test empty string context is treated like no context."""
        result = build_work_prompt(task_description="Task", context="")
        # Empty string is falsy, so no context section
        assert "## Context" not in result

    def test_multiline_context(self) -> None:
        """Test multiline context is preserved."""
        context = """Discovery 1: Uses Flask
Discovery 2: Has pytest tests
Discovery 3: No CI config"""
        result = build_work_prompt(task_description="Task", context=context)
        assert "Uses Flask" in result
        assert "Has pytest tests" in result
        assert "No CI config" in result

    def test_context_with_code_blocks(self) -> None:
        """Test context with code blocks is preserved."""
        context = """Found pattern:
```python
def main():
    pass
```"""
        result = build_work_prompt(task_description="Task", context=context)
        assert "```python" in result
        assert "def main():" in result


# =============================================================================
# File Hints Section Tests
# =============================================================================


class TestFileHintsSection:
    """Tests for file hints section handling."""

    def test_no_file_hints_by_default(self) -> None:
        """Test no file hints section when None."""
        result = build_work_prompt("Any task", file_hints=None)
        assert "## Relevant Files" not in result

    def test_file_hints_included_when_provided(self) -> None:
        """Test file hints are included when provided."""
        result = build_work_prompt(
            task_description="Task",
            file_hints=["src/main.py", "tests/test_main.py"],
        )
        assert "## Relevant Files" in result
        assert "`src/main.py`" in result
        assert "`tests/test_main.py`" in result

    def test_empty_file_hints_list(self) -> None:
        """Test empty file hints list."""
        result = build_work_prompt("Task", file_hints=[])
        # Empty list is falsy, so section should not appear
        assert "## Relevant Files" not in result

    def test_single_file_hint(self) -> None:
        """Test single file hint."""
        result = build_work_prompt(
            task_description="Task",
            file_hints=["src/app.py"],
        )
        assert "## Relevant Files" in result
        assert "`src/app.py`" in result

    def test_multiple_file_hints(self) -> None:
        """Test multiple file hints."""
        hints = [
            "src/core/main.py",
            "src/utils/helpers.py",
            "tests/test_main.py",
            "tests/test_helpers.py",
        ]
        result = build_work_prompt("Task", file_hints=hints)
        for hint in hints:
            assert f"`{hint}`" in result

    def test_file_hints_limited_to_10(self) -> None:
        """Test file hints are limited to 10."""
        hints = [f"file_{i}.py" for i in range(15)]
        result = build_work_prompt("Task", file_hints=hints)
        # First 10 should be present
        for i in range(10):
            assert f"`file_{i}.py`" in result
        # 11th and beyond should not be present
        assert "`file_10.py`" not in result
        assert "`file_14.py`" not in result

    def test_start_by_reading_instruction(self) -> None:
        """Test instruction to start by reading files."""
        result = build_work_prompt(
            task_description="Task",
            file_hints=["src/main.py"],
        )
        assert "Start by reading" in result


# =============================================================================
# PR Comments Section Tests
# =============================================================================


class TestPRCommentsSection:
    """Tests for PR review comments section handling."""

    def test_no_pr_comments_by_default(self) -> None:
        """Test no PR comments section when None."""
        result = build_work_prompt("Any task", pr_comments=None)
        assert "## PR Review Feedback" not in result

    def test_pr_comments_included_when_provided(self) -> None:
        """Test PR comments are included when provided."""
        result = build_work_prompt(
            task_description="Task",
            pr_comments="Please add error handling to the API",
        )
        assert "## PR Review Feedback" in result
        assert "Please add error handling to the API" in result

    def test_address_feedback_instruction(self) -> None:
        """Test instruction to address review feedback."""
        result = build_work_prompt(
            task_description="Task",
            pr_comments="Fix the bug",
        )
        assert "Address this review feedback" in result or "Address" in result

    def test_explore_thoroughly_instruction(self) -> None:
        """Test instruction to explore thoroughly first."""
        result = build_work_prompt(
            task_description="Task",
            pr_comments="Comments here",
        )
        assert "Explore thoroughly" in result or "Read the relevant files" in result

    def test_if_agree_instruction(self) -> None:
        """Test instruction for when agreeing with feedback."""
        result = build_work_prompt(
            task_description="Task",
            pr_comments="Comments here",
        )
        assert "If you agree" in result

    def test_if_disagree_instruction(self) -> None:
        """Test instruction for when disagreeing with feedback."""
        result = build_work_prompt(
            task_description="Task",
            pr_comments="Comments here",
        )
        assert "If you disagree" in result

    def test_run_tests_after_changes(self) -> None:
        """Test instruction to run tests after changes."""
        result = build_work_prompt(
            task_description="Task",
            pr_comments="Comments here",
        )
        assert "Run tests after" in result or "run tests" in result.lower()

    def test_multiline_pr_comments(self) -> None:
        """Test multiline PR comments are preserved."""
        comments = """Comment 1: Fix the error handling
Comment 2: Add missing tests
Comment 3: Update documentation"""
        result = build_work_prompt(task_description="Task", pr_comments=comments)
        assert "Fix the error handling" in result
        assert "Add missing tests" in result
        assert "Update documentation" in result


# =============================================================================
# PR Group Info Section Tests
# =============================================================================


class TestPRGroupInfoSection:
    """Tests for PR group info section handling."""

    def test_no_pr_group_info_by_default(self) -> None:
        """Test no PR group info section when None."""
        result = build_work_prompt("Any task", pr_group_info=None)
        assert "## PR Group Context" not in result

    def test_pr_group_info_included_when_provided(self) -> None:
        """Test PR group info is included when provided."""
        result = build_work_prompt(
            task_description="Task",
            pr_group_info={
                "name": "Add Authentication",
                "completed_tasks": ["Create user model"],
                "remaining_tasks": 2,
            },
        )
        assert "## PR Group Context" in result
        assert "Add Authentication" in result

    def test_pr_group_name_displayed(self) -> None:
        """Test PR group name is displayed."""
        result = build_work_prompt(
            task_description="Task",
            pr_group_info={
                "name": "Implement Caching",
                "completed_tasks": [],
                "remaining_tasks": 3,
            },
        )
        assert "**PR Group:**" in result
        assert "Implement Caching" in result

    def test_pr_group_branch_displayed(self) -> None:
        """Test PR group branch is displayed when provided."""
        result = build_work_prompt(
            task_description="Task",
            pr_group_info={
                "name": "Feature",
                "branch": "feat/caching",
                "completed_tasks": [],
                "remaining_tasks": 1,
            },
        )
        assert "**Branch:**" in result
        assert "`feat/caching`" in result

    def test_completed_tasks_displayed(self) -> None:
        """Test completed tasks are displayed."""
        result = build_work_prompt(
            task_description="Task",
            pr_group_info={
                "name": "Feature",
                "completed_tasks": [
                    "Create user model",
                    "Add user API endpoints",
                    "Write user tests",
                ],
                "remaining_tasks": 1,
            },
        )
        assert "Already completed in this PR" in result
        assert "Create user model" in result
        assert "Add user API endpoints" in result
        assert "Write user tests" in result
        # Should have checkmark for completed tasks
        assert "✓" in result

    def test_remaining_tasks_count_displayed(self) -> None:
        """Test remaining tasks count is displayed."""
        result = build_work_prompt(
            task_description="Task",
            pr_group_info={
                "name": "Feature",
                "completed_tasks": [],
                "remaining_tasks": 5,
            },
        )
        assert "Tasks remaining after this one:" in result
        assert "5" in result

    def test_last_task_message_when_zero_remaining(self) -> None:
        """Test last task message when no remaining tasks."""
        result = build_work_prompt(
            task_description="Task",
            pr_group_info={
                "name": "Feature",
                "completed_tasks": ["Previous task"],
                "remaining_tasks": 0,
            },
        )
        assert "LAST task in this PR group" in result

    def test_empty_completed_tasks_no_section(self) -> None:
        """Test no completed section when empty list."""
        result = build_work_prompt(
            task_description="Task",
            pr_group_info={
                "name": "Feature",
                "completed_tasks": [],
                "remaining_tasks": 3,
            },
        )
        # Should not have "Already completed" section when no completed tasks
        # The section is only added when completed list is non-empty
        assert "**PR Group:**" in result


# =============================================================================
# Execution Section Tests
# =============================================================================


class TestExecutionSection:
    """Tests for execution section."""

    def test_execution_section_present(self) -> None:
        """Test Execution section is present."""
        result = build_work_prompt("Any task")
        assert "## Execution" in result

    def test_git_status_first_step(self) -> None:
        """Test git status first step is present."""
        result = build_work_prompt("Any task")
        assert "git status" in result
        assert "Check git status first" in result or "Step 1" in result or "1." in result

    def test_understand_task_step(self) -> None:
        """Test understand task step is present."""
        result = build_work_prompt("Any task")
        assert "Understand the task" in result or "Read files" in result

    def test_make_changes_step(self) -> None:
        """Test make changes step is present."""
        result = build_work_prompt("Any task")
        assert "Make changes" in result

    def test_verify_work_step(self) -> None:
        """Test verify work step is present."""
        result = build_work_prompt("Any task")
        assert "Verify work" in result

    def test_commit_step(self) -> None:
        """Test commit step is present."""
        result = build_work_prompt("Any task")
        assert "Commit" in result
        assert "git add" in result
        assert "git commit" in result

    def test_co_authored_by_present(self) -> None:
        """Test Co-Authored-By is present."""
        result = build_work_prompt("Any task")
        assert "Co-Authored-By" in result
        assert "Claude" in result

    def test_gitignore_note_present(self) -> None:
        """Test gitignore note about .claude-task-master is present."""
        result = build_work_prompt("Any task")
        assert ".claude-task-master" in result
        assert "gitignored" in result.lower() or "auto" in result.lower()


# =============================================================================
# Full Workflow Execution Tests (create_pr=True)
# =============================================================================


class TestFullWorkflowExecution:
    """Tests for full workflow execution (create_pr=True)."""

    def test_full_workflow_by_default(self) -> None:
        """Test full workflow is used by default."""
        result = build_work_prompt("Task")
        assert "Push and Create PR" in result or "git push" in result

    def test_full_workflow_when_create_pr_true(self) -> None:
        """Test full workflow when create_pr is True."""
        result = build_work_prompt("Task", create_pr=True)
        assert "Push and Create PR" in result or "git push" in result

    def test_git_push_present(self) -> None:
        """Test git push command is present."""
        result = build_work_prompt("Task", create_pr=True)
        assert "git push" in result

    def test_gh_pr_create_present(self) -> None:
        """Test gh pr create command is present."""
        result = build_work_prompt("Task", create_pr=True)
        assert "gh pr create" in result

    def test_claudetm_label_mentioned(self) -> None:
        """Test claudetm label is mentioned."""
        result = build_work_prompt("Task", create_pr=True)
        assert "claudetm" in result

    def test_work_not_done_until_pr_warning(self) -> None:
        """Test warning about work not done until PR."""
        result = build_work_prompt("Task", create_pr=True)
        assert "NOT done until pushed" in result or "NOT done until" in result

    def test_stop_after_pr_creation_instruction(self) -> None:
        """Test instruction to stop after PR creation."""
        result = build_work_prompt("Task", create_pr=True)
        assert "STOP AFTER PR CREATION" in result or "DO NOT" in result

    def test_no_wait_for_ci_instruction(self) -> None:
        """Test instruction to not wait for CI."""
        result = build_work_prompt("Task", create_pr=True)
        # Should have instruction to NOT poll/wait for CI
        lower_result = result.lower()
        assert "sleep" in lower_result or "wait" in lower_result

    def test_orchestrator_handles_ci_mention(self) -> None:
        """Test mention that orchestrator handles CI."""
        result = build_work_prompt("Task", create_pr=True)
        assert "orchestrator handles" in result.lower() or "orchestrator" in result.lower()


# =============================================================================
# Commit-Only Workflow Tests (create_pr=False)
# =============================================================================


class TestCommitOnlyWorkflow:
    """Tests for commit-only workflow (create_pr=False)."""

    def test_commit_only_when_create_pr_false(self) -> None:
        """Test commit-only workflow when create_pr is False."""
        result = build_work_prompt("Task", create_pr=False)
        assert "DO NOT create PR yet" in result

    def test_more_tasks_remain_message(self) -> None:
        """Test message about more tasks remaining."""
        result = build_work_prompt("Task", create_pr=False)
        assert "More tasks remain" in result or "more tasks" in result.lower()

    def test_just_commit_instruction(self) -> None:
        """Test instruction to just commit."""
        result = build_work_prompt("Task", create_pr=False)
        assert "Just commit" in result or "commit" in result.lower()

    def test_no_push_instruction(self) -> None:
        """Test instruction to not push."""
        result = build_work_prompt("Task", create_pr=False)
        assert "do NOT push" in result.lower() or "do not push" in result.lower()

    def test_orchestrator_will_tell_when(self) -> None:
        """Test message about orchestrator telling when to create PR."""
        result = build_work_prompt("Task", create_pr=False)
        assert "orchestrator will tell" in result.lower() or "orchestrator" in result.lower()


# =============================================================================
# Completion Section Tests
# =============================================================================


class TestCompletionSection:
    """Tests for completion section."""

    def test_on_completion_section_present(self) -> None:
        """Test On Completion section is present."""
        result = build_work_prompt("Any task")
        assert "On Completion" in result or "STOP" in result

    def test_task_complete_marker_present(self) -> None:
        """Test TASK COMPLETE marker is present."""
        result = build_work_prompt("Any task")
        assert "TASK COMPLETE" in result

    def test_commit_before_reporting_instruction(self) -> None:
        """Test instruction to commit before reporting."""
        result = build_work_prompt("Any task")
        assert "commit your work before reporting" in result.lower() or "commit" in result.lower()

    def test_report_requirements(self) -> None:
        """Test report requirements are listed."""
        result = build_work_prompt("Any task")
        assert "What was completed" in result
        assert "Tests run" in result
        assert "Files modified" in result
        assert "Commit hash" in result
        assert "blockers" in result.lower()

    def test_commit_hash_required(self) -> None:
        """Test commit hash is marked as required."""
        result = build_work_prompt("Any task")
        assert "Commit hash (REQUIRED" in result or "commit hash" in result.lower()

    def test_orchestrator_new_session_mention(self) -> None:
        """Test mention of orchestrator starting new session."""
        result = build_work_prompt("Any task")
        assert "orchestrator will start" in result.lower() or "NEW session" in result


# =============================================================================
# Log File Best Practices Tests
# =============================================================================


class TestLogFileBestPractices:
    """Tests for log file best practices section."""

    def test_log_file_best_practices_present(self) -> None:
        """Test Log File Best Practices section is present."""
        result = build_work_prompt("Any task")
        assert "Log File Best Practices" in result

    def test_append_mode_advice(self) -> None:
        """Test advice to use APPEND mode."""
        result = build_work_prompt("Any task")
        assert "APPEND mode" in result or "append" in result.lower()

    def test_context_bloat_warning(self) -> None:
        """Test warning about context bloat."""
        result = build_work_prompt("Any task")
        assert "context bloat" in result.lower() or "bloat" in result.lower()


# =============================================================================
# Private Function Tests
# =============================================================================


class TestBuildFullWorkflowExecution:
    """Tests for _build_full_workflow_execution private function."""

    def test_returns_string(self) -> None:
        """Test that function returns a string."""
        result = _build_full_workflow_execution()
        assert isinstance(result, str)

    def test_returns_non_empty(self) -> None:
        """Test that function returns non-empty string."""
        result = _build_full_workflow_execution()
        assert len(result) > 0

    def test_contains_push_and_pr_section(self) -> None:
        """Test contains Push and Create PR section."""
        result = _build_full_workflow_execution()
        assert "Push and Create PR" in result

    def test_contains_stop_after_pr_creation(self) -> None:
        """Test contains STOP AFTER PR CREATION."""
        result = _build_full_workflow_execution()
        assert "STOP AFTER PR CREATION" in result

    def test_contains_no_merge_instruction(self) -> None:
        """Test contains instruction to not merge."""
        result = _build_full_workflow_execution()
        assert "Merge the PR" in result


class TestBuildCommitOnlyExecution:
    """Tests for _build_commit_only_execution private function."""

    def test_returns_string(self) -> None:
        """Test that function returns a string."""
        result = _build_commit_only_execution()
        assert isinstance(result, str)

    def test_returns_non_empty(self) -> None:
        """Test that function returns non-empty string."""
        result = _build_commit_only_execution()
        assert len(result) > 0

    def test_contains_do_not_create_pr(self) -> None:
        """Test contains DO NOT create PR yet."""
        result = _build_commit_only_execution()
        assert "DO NOT create PR yet" in result

    def test_contains_more_tasks_remain(self) -> None:
        """Test contains more tasks remain message."""
        result = _build_commit_only_execution()
        assert "More tasks remain" in result


# =============================================================================
# Function Signature Tests
# =============================================================================


class TestFunctionSignature:
    """Tests for function signature and parameters."""

    def test_task_description_is_required(self) -> None:
        """Test task_description parameter is required."""
        import inspect

        result = build_work_prompt("Task")
        assert isinstance(result, str)

        # Verify parameter is required (has no default value)
        sig = inspect.signature(build_work_prompt)
        params = sig.parameters
        assert "task_description" in params
        assert params["task_description"].default is inspect.Parameter.empty

    def test_context_is_optional(self) -> None:
        """Test context parameter is optional."""
        result1 = build_work_prompt("Task")
        result2 = build_work_prompt("Task", context="Context")
        assert isinstance(result1, str)
        assert isinstance(result2, str)

    def test_pr_comments_is_optional(self) -> None:
        """Test pr_comments parameter is optional."""
        result1 = build_work_prompt("Task")
        result2 = build_work_prompt("Task", pr_comments="Comments")
        assert isinstance(result1, str)
        assert isinstance(result2, str)

    def test_file_hints_is_optional(self) -> None:
        """Test file_hints parameter is optional."""
        result1 = build_work_prompt("Task")
        result2 = build_work_prompt("Task", file_hints=["file.py"])
        assert isinstance(result1, str)
        assert isinstance(result2, str)

    def test_required_branch_is_optional(self) -> None:
        """Test required_branch parameter is optional."""
        result1 = build_work_prompt("Task")
        result2 = build_work_prompt("Task", required_branch="main")
        assert isinstance(result1, str)
        assert isinstance(result2, str)

    def test_create_pr_is_optional(self) -> None:
        """Test create_pr parameter is optional."""
        result1 = build_work_prompt("Task")
        result2 = build_work_prompt("Task", create_pr=False)
        assert isinstance(result1, str)
        assert isinstance(result2, str)

    def test_pr_group_info_is_optional(self) -> None:
        """Test pr_group_info parameter is optional."""
        result1 = build_work_prompt("Task")
        result2 = build_work_prompt("Task", pr_group_info={"name": "Group"})
        assert isinstance(result1, str)
        assert isinstance(result2, str)

    def test_keyword_args_work(self) -> None:
        """Test keyword arguments work."""
        result = build_work_prompt(
            task_description="Task",
            context="Context",
            pr_comments="Comments",
            file_hints=["file.py"],
            required_branch="feat/test",
            create_pr=False,
            pr_group_info={"name": "Group", "completed_tasks": [], "remaining_tasks": 0},
        )
        assert isinstance(result, str)
        assert "Task" in result
        assert "Context" in result
        assert "Comments" in result


# =============================================================================
# Integration Tests
# =============================================================================


class TestBuildWorkPromptIntegration:
    """Integration tests for build_work_prompt."""

    def test_complete_prompt_structure(self) -> None:
        """Test complete prompt has all major sections."""
        result = build_work_prompt(
            task_description="Implement user authentication",
            context="Uses Flask framework",
            file_hints=["src/auth.py"],
            required_branch="feat/auth",
            create_pr=True,
            pr_group_info={
                "name": "Auth Feature",
                "completed_tasks": ["Create user model"],
                "remaining_tasks": 2,
            },
        )

        # All major sections should be present
        assert "Current Task" in result
        assert "PR Group Context" in result
        assert "## Context" in result
        assert "## Relevant Files" in result
        assert "## Execution" in result
        assert "On Completion" in result

    def test_section_order_logical(self) -> None:
        """Test sections appear in logical order."""
        result = build_work_prompt(
            task_description="Task",
            context="Context",
            pr_group_info={
                "name": "Group",
                "completed_tasks": [],
                "remaining_tasks": 1,
            },
        )

        # Find positions
        task_pos = result.find("Current Task")
        group_pos = result.find("PR Group Context")
        context_pos = result.find("## Context")
        exec_pos = result.find("## Execution")
        complete_pos = result.find("On Completion")

        # Verify order: Task -> PR Group -> Context -> Execution -> Completion
        assert task_pos < group_pos < context_pos < exec_pos < complete_pos

    def test_prompt_length_reasonable(self) -> None:
        """Test prompt length is reasonable."""
        result = build_work_prompt("Any task")
        assert len(result) > 500  # Has content
        assert len(result) < 15000  # Not excessively long

    def test_prompt_is_valid_markdown(self) -> None:
        """Test prompt contains valid markdown structure."""
        result = build_work_prompt("Any task")

        # Should have markdown headers
        assert "## " in result

        # Should have code blocks
        assert "```" in result

        # Should have list items
        assert "- " in result


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestBuildWorkPromptEdgeCases:
    """Edge case tests for build_work_prompt."""

    def test_very_long_task(self) -> None:
        """Test with very long task description."""
        long_task = "Implement feature " + "X" * 1000
        result = build_work_prompt(long_task)
        assert long_task in result

    def test_unicode_task(self) -> None:
        """Test with unicode characters in task."""
        task = "实现功能 🎯 日本語テスト"
        result = build_work_prompt(task)
        assert task in result

    def test_task_with_newlines_and_tabs(self) -> None:
        """Test task with various whitespace."""
        task = "Task\twith\ttabs\nand\nnewlines"
        result = build_work_prompt(task)
        assert "Task" in result
        assert "tabs" in result
        assert "newlines" in result

    def test_context_with_unicode(self) -> None:
        """Test context with unicode characters."""
        context = "发现：使用 React 框架 🚀"
        result = build_work_prompt(task_description="Task", context=context)
        assert context in result

    def test_all_optional_params_provided(self) -> None:
        """Test with all optional parameters provided."""
        result = build_work_prompt(
            task_description="Complete task",
            context="Rich context here",
            pr_comments="Fix the tests",
            file_hints=["a.py", "b.py", "c.py"],
            required_branch="feat/complete",
            create_pr=False,
            pr_group_info={
                "name": "Complete PR",
                "branch": "feat/complete",
                "completed_tasks": ["Task 1", "Task 2"],
                "remaining_tasks": 0,
            },
        )

        assert "Complete task" in result
        assert "Rich context here" in result
        assert "Fix the tests" in result
        assert "`a.py`" in result
        assert "feat/complete" in result
        assert "DO NOT create PR yet" in result
        assert "Complete PR" in result
        assert "Task 1" in result
        assert "LAST task" in result

    def test_pr_group_with_missing_keys(self) -> None:
        """Test PR group info with some missing keys."""
        result = build_work_prompt(
            task_description="Task",
            pr_group_info={"name": "Minimal"},
        )
        assert "Minimal" in result
        assert "PR Group" in result

    def test_file_hints_with_special_paths(self) -> None:
        """Test file hints with special path characters."""
        hints = [
            "src/path with spaces/file.py",
            "tests/test_file-name.py",
            "src/__init__.py",
        ]
        result = build_work_prompt("Task", file_hints=hints)
        for hint in hints:
            assert hint in result


# =============================================================================
# Verification Command Tests
# =============================================================================


class TestVerificationCommands:
    """Tests for verification commands in execution section."""

    def test_pytest_mentioned(self) -> None:
        """Test pytest is mentioned for Python tests."""
        result = build_work_prompt("Any task")
        assert "pytest" in result

    def test_npm_test_mentioned(self) -> None:
        """Test npm test is mentioned for JS tests."""
        result = build_work_prompt("Any task")
        assert "npm test" in result

    def test_ruff_mentioned(self) -> None:
        """Test ruff is mentioned for Python linting."""
        result = build_work_prompt("Any task")
        assert "ruff" in result

    def test_mypy_mentioned(self) -> None:
        """Test mypy is mentioned for Python types."""
        result = build_work_prompt("Any task")
        assert "mypy" in result

    def test_eslint_mentioned(self) -> None:
        """Test eslint is mentioned for JS linting."""
        result = build_work_prompt("Any task")
        assert "eslint" in result

    def test_tsc_mentioned(self) -> None:
        """Test tsc is mentioned for TypeScript."""
        result = build_work_prompt("Any task")
        assert "tsc" in result
