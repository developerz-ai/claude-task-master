"""Tests for verification phase prompts.

This module tests the prompts from prompts_verification.py:
- build_verification_prompt: Verification phase prompt
- build_task_completion_check_prompt: Task completion checking
- build_context_extraction_prompt: Context/learnings extraction
- build_error_recovery_prompt: Error recovery prompt
"""

from claude_task_master.core.prompts_verification import (
    build_context_extraction_prompt,
    build_error_recovery_prompt,
    build_task_completion_check_prompt,
    build_verification_prompt,
)

# =============================================================================
# build_verification_prompt Tests
# =============================================================================


class TestBuildVerificationPromptBasic:
    """Tests for basic build_verification_prompt functionality."""

    def test_returns_string(self) -> None:
        """Test that build_verification_prompt returns a string."""
        result = build_verification_prompt("All tests pass")
        assert isinstance(result, str)

    def test_returns_non_empty_string(self) -> None:
        """Test that build_verification_prompt returns non-empty string."""
        result = build_verification_prompt("Any criteria")
        assert len(result) > 0

    def test_criteria_included_in_prompt(self) -> None:
        """Test that the criteria is included in the prompt."""
        criteria = "All unit tests pass with 100% coverage"
        result = build_verification_prompt(criteria)
        assert criteria in result

    def test_criteria_with_special_characters(self) -> None:
        """Test criteria with special characters is preserved."""
        criteria = "Tests pass: #123's assertion doesn't fail"
        result = build_verification_prompt(criteria)
        assert criteria in result

    def test_criteria_with_markdown(self) -> None:
        """Test criteria with markdown formatting is preserved."""
        criteria = "Run **critical** tests with `pytest`"
        result = build_verification_prompt(criteria)
        assert "critical" in result
        assert "pytest" in result

    def test_empty_criteria(self) -> None:
        """Test with empty criteria string."""
        result = build_verification_prompt("")
        # Should still generate a valid prompt
        assert isinstance(result, str)
        assert "Success Criteria" in result

    def test_multiline_criteria(self) -> None:
        """Test criteria with multiple lines."""
        criteria = "Tests pass\nLinting clean\nCI green"
        result = build_verification_prompt(criteria)
        assert "Tests pass" in result
        assert "Linting clean" in result
        assert "CI green" in result


class TestVerificationIntroduction:
    """Tests for verification prompt introduction section."""

    def test_claude_task_master_mentioned(self) -> None:
        """Test Claude Task Master is mentioned."""
        result = build_verification_prompt("Any criteria")
        assert "Claude Task Master" in result

    def test_verifying_keyword_present(self) -> None:
        """Test verifying/verification context is present."""
        result = build_verification_prompt("Any criteria")
        assert "verifying" in result.lower() or "verification" in result.lower()

    def test_work_complete_mentioned(self) -> None:
        """Test work complete is mentioned."""
        result = build_verification_prompt("Any criteria")
        assert "complete" in result.lower()

    def test_success_criteria_mentioned(self) -> None:
        """Test success criteria is mentioned."""
        result = build_verification_prompt("Any criteria")
        assert "success criteria" in result.lower()


class TestTasksSummarySectionVerification:
    """Tests for tasks summary section in verification prompt."""

    def test_no_tasks_summary_by_default(self) -> None:
        """Test no tasks summary section when None."""
        result = build_verification_prompt("Criteria", tasks_summary=None)
        assert "Completed Tasks" not in result

    def test_tasks_summary_included_when_provided(self) -> None:
        """Test tasks summary is included when provided."""
        result = build_verification_prompt(
            criteria="Tests pass",
            tasks_summary="Implemented login\nAdded tests",
        )
        assert "Completed Tasks" in result
        assert "Implemented login" in result
        assert "Added tests" in result

    def test_tasks_summary_multiline(self) -> None:
        """Test multiline tasks summary is preserved."""
        tasks = """Task 1: Done
Task 2: Done
Task 3: Done"""
        result = build_verification_prompt(criteria="Criteria", tasks_summary=tasks)
        assert "Task 1" in result
        assert "Task 2" in result
        assert "Task 3" in result

    def test_tasks_summary_with_checkboxes(self) -> None:
        """Test tasks summary with checkbox format."""
        tasks = """- [x] Implement feature
- [x] Add tests
- [x] Update docs"""
        result = build_verification_prompt(criteria="Criteria", tasks_summary=tasks)
        assert "Implement feature" in result
        assert "Add tests" in result
        assert "Update docs" in result


class TestVerificationStepsSection:
    """Tests for verification steps section."""

    def test_verification_steps_present(self) -> None:
        """Test Verification Steps section exists."""
        result = build_verification_prompt("Any criteria")
        assert "Verification Steps" in result

    def test_run_tests_step(self) -> None:
        """Test run tests step is present."""
        result = build_verification_prompt("Any criteria")
        assert "Run tests" in result

    def test_check_lint_types_step(self) -> None:
        """Test check lint/types step is present."""
        result = build_verification_prompt("Any criteria")
        assert "lint" in result.lower() or "static analysis" in result.lower()

    def test_verify_prs_step(self) -> None:
        """Test verify PRs step is present."""
        result = build_verification_prompt("Any criteria")
        assert "PR" in result

    def test_functional_check_step(self) -> None:
        """Test functional check step is present."""
        result = build_verification_prompt("Any criteria")
        assert "Functional" in result or "requirements" in result.lower()


class TestVerificationReportFormat:
    """Tests for verification report format guidance."""

    def test_passed_format_present(self) -> None:
        """Test PASSED format is present."""
        result = build_verification_prompt("Any criteria")
        assert "PASSED" in result
        assert "✓" in result

    def test_failed_format_present(self) -> None:
        """Test FAILED format is present."""
        result = build_verification_prompt("Any criteria")
        assert "FAILED" in result
        assert "✗" in result

    def test_evidence_mentioned(self) -> None:
        """Test evidence requirement is mentioned."""
        result = build_verification_prompt("Any criteria")
        assert "evidence" in result.lower()

    def test_reason_mentioned(self) -> None:
        """Test reason requirement is mentioned."""
        result = build_verification_prompt("Any criteria")
        assert "reason" in result.lower()


class TestVerificationResultMarker:
    """Tests for verification result marker."""

    def test_verification_result_marker_present(self) -> None:
        """Test VERIFICATION_RESULT marker is present."""
        result = build_verification_prompt("Any criteria")
        assert "VERIFICATION_RESULT" in result

    def test_pass_option_present(self) -> None:
        """Test PASS option is present."""
        result = build_verification_prompt("Any criteria")
        assert "VERIFICATION_RESULT: PASS" in result

    def test_fail_option_present(self) -> None:
        """Test FAIL option is present."""
        result = build_verification_prompt("Any criteria")
        assert "VERIFICATION_RESULT: FAIL" in result

    def test_critical_marker_present(self) -> None:
        """Test CRITICAL marker is present."""
        result = build_verification_prompt("Any criteria")
        assert "CRITICAL" in result

    def test_strict_instruction_present(self) -> None:
        """Test strict instruction is present."""
        result = build_verification_prompt("Any criteria")
        assert "strict" in result.lower()


# =============================================================================
# build_task_completion_check_prompt Tests
# =============================================================================


class TestBuildTaskCompletionCheckPromptBasic:
    """Tests for basic build_task_completion_check_prompt functionality."""

    def test_returns_string(self) -> None:
        """Test that build_task_completion_check_prompt returns a string."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert isinstance(result, str)

    def test_returns_non_empty_string(self) -> None:
        """Test that build_task_completion_check_prompt returns non-empty string."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert len(result) > 0

    def test_task_description_included(self) -> None:
        """Test that task description is included."""
        task = "Implement user authentication"
        result = build_task_completion_check_prompt(task, "Output")
        assert task in result

    def test_session_output_included(self) -> None:
        """Test that session output is included."""
        output = "Authentication implemented successfully"
        result = build_task_completion_check_prompt("Task", output)
        assert output in result

    def test_task_section_header(self) -> None:
        """Test Task section header is present."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "## Task" in result

    def test_session_output_section_header(self) -> None:
        """Test Session Output section header is present."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "## Session Output" in result

    def test_determination_section_header(self) -> None:
        """Test Determination section header is present."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "## Determination" in result


class TestTaskCompletionStatusOptions:
    """Tests for task completion status options."""

    def test_completed_status_present(self) -> None:
        """Test COMPLETED status is present."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "COMPLETED" in result

    def test_in_progress_status_present(self) -> None:
        """Test IN_PROGRESS status is present."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "IN_PROGRESS" in result

    def test_blocked_status_present(self) -> None:
        """Test BLOCKED status is present."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "BLOCKED" in result

    def test_failed_status_present(self) -> None:
        """Test FAILED status is present."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "FAILED" in result

    def test_exactly_one_instruction(self) -> None:
        """Test instruction to answer with exactly one status."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "EXACTLY one" in result


class TestTaskCompletionStatusDescriptions:
    """Tests for task completion status descriptions."""

    def test_completed_description(self) -> None:
        """Test COMPLETED has description about fully done."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "fully done" in result.lower() or "no more work needed" in result.lower()

    def test_in_progress_description(self) -> None:
        """Test IN_PROGRESS has description about partial progress."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "partial progress" in result.lower() or "more work needed" in result.lower()

    def test_blocked_description(self) -> None:
        """Test BLOCKED has description about intervention."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "intervention" in result.lower()

    def test_failed_description(self) -> None:
        """Test FAILED has description about error."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "error" in result.lower()

    def test_explain_why_instruction(self) -> None:
        """Test instruction to explain why."""
        result = build_task_completion_check_prompt("Task", "Output")
        assert "explain why" in result.lower()


class TestTaskCompletionEdgeCases:
    """Edge case tests for build_task_completion_check_prompt."""

    def test_empty_task_description(self) -> None:
        """Test with empty task description."""
        result = build_task_completion_check_prompt("", "Output")
        assert isinstance(result, str)
        assert "## Task" in result

    def test_empty_session_output(self) -> None:
        """Test with empty session output."""
        result = build_task_completion_check_prompt("Task", "")
        assert isinstance(result, str)
        assert "## Session Output" in result

    def test_multiline_task(self) -> None:
        """Test with multiline task description."""
        task = "Task line 1\nTask line 2\nTask line 3"
        result = build_task_completion_check_prompt(task, "Output")
        assert "Task line 1" in result
        assert "Task line 2" in result
        assert "Task line 3" in result

    def test_multiline_output(self) -> None:
        """Test with multiline session output."""
        output = "Output line 1\nOutput line 2\nOutput line 3"
        result = build_task_completion_check_prompt("Task", output)
        assert "Output line 1" in result
        assert "Output line 2" in result
        assert "Output line 3" in result

    def test_special_characters_in_task(self) -> None:
        """Test special characters in task description."""
        task = "Fix bug #123: User's session doesn't persist"
        result = build_task_completion_check_prompt(task, "Output")
        assert task in result

    def test_code_blocks_in_output(self) -> None:
        """Test code blocks in session output."""
        output = """Fixed the issue:
```python
def main():
    pass
```"""
        result = build_task_completion_check_prompt("Task", output)
        assert "```python" in result
        assert "def main():" in result


# =============================================================================
# build_context_extraction_prompt Tests
# =============================================================================


class TestBuildContextExtractionPromptBasic:
    """Tests for basic build_context_extraction_prompt functionality."""

    def test_returns_string(self) -> None:
        """Test that build_context_extraction_prompt returns a string."""
        result = build_context_extraction_prompt("Session output")
        assert isinstance(result, str)

    def test_returns_non_empty_string(self) -> None:
        """Test that build_context_extraction_prompt returns non-empty string."""
        result = build_context_extraction_prompt("Session output")
        assert len(result) > 0

    def test_session_output_included(self) -> None:
        """Test that session output is included."""
        output = "Discovered the app uses React framework"
        result = build_context_extraction_prompt(output)
        assert output in result

    def test_intro_mentions_learnings(self) -> None:
        """Test intro mentions key learnings."""
        result = build_context_extraction_prompt("Output")
        assert "learnings" in result.lower()

    def test_intro_mentions_future_work(self) -> None:
        """Test intro mentions future work."""
        result = build_context_extraction_prompt("Output")
        assert "future" in result.lower()


class TestExistingContextSection:
    """Tests for existing context section handling."""

    def test_no_existing_context_by_default(self) -> None:
        """Test no existing context section when None."""
        result = build_context_extraction_prompt("Output", existing_context=None)
        assert "Existing Context" not in result

    def test_existing_context_included_when_provided(self) -> None:
        """Test existing context is included when provided."""
        result = build_context_extraction_prompt(
            session_output="New discovery",
            existing_context="Previously: uses Flask",
        )
        assert "Existing Context" in result
        assert "uses Flask" in result

    def test_multiline_existing_context(self) -> None:
        """Test multiline existing context is preserved."""
        context = """Discovery 1: Uses Flask
Discovery 2: Has pytest tests
Discovery 3: No CI config"""
        result = build_context_extraction_prompt("Output", existing_context=context)
        assert "Uses Flask" in result
        assert "Has pytest tests" in result
        assert "No CI config" in result


class TestSessionOutputHandling:
    """Tests for session output handling."""

    def test_session_output_section_present(self) -> None:
        """Test Session Output section is present."""
        result = build_context_extraction_prompt("Any output")
        assert "Session Output" in result

    def test_long_output_truncated(self) -> None:
        """Test that very long output is truncated to 5000 chars."""
        # Use a unique character pattern to avoid counting chars in other sections
        long_output = "UNIQUE_MARKER_" + "A" * 10000
        result = build_context_extraction_prompt(long_output)
        # The output should be truncated (5000 chars max from original)
        # The marker and A's together make up the truncated portion
        assert result.count("A") < 10000  # Should be truncated
        assert result.count("A") > 0  # But some should remain

    def test_output_at_limit_not_truncated(self) -> None:
        """Test output at exactly 5000 chars is not truncated."""
        output = "MARKER_" + "B" * 4993  # 7 + 4993 = 5000
        result = build_context_extraction_prompt(output)
        # All B's should be present since we're at the limit
        assert result.count("B") == 4993

    def test_output_under_limit_not_truncated(self) -> None:
        """Test output under 5000 chars is not truncated."""
        output = "MARKER_" + "Z" * 2993  # 7 + 2993 = 3000
        result = build_context_extraction_prompt(output)
        # All Z's should be present since we're under the limit
        assert result.count("Z") == 2993


class TestExtractionCategories:
    """Tests for extraction categories in context extraction prompt."""

    def test_patterns_category_present(self) -> None:
        """Test Patterns category is present."""
        result = build_context_extraction_prompt("Output")
        assert "Patterns" in result

    def test_decisions_category_present(self) -> None:
        """Test Decisions category is present."""
        result = build_context_extraction_prompt("Output")
        assert "Decisions" in result

    def test_issues_category_present(self) -> None:
        """Test Issues category is present."""
        result = build_context_extraction_prompt("Output")
        assert "Issues" in result

    def test_feedback_category_present(self) -> None:
        """Test Feedback category is present."""
        result = build_context_extraction_prompt("Output")
        assert "Feedback" in result

    def test_concise_instruction_present(self) -> None:
        """Test concise instruction is present."""
        result = build_context_extraction_prompt("Output")
        assert "concise" in result.lower() or "500 words" in result


class TestContextExtractionEdgeCases:
    """Edge case tests for build_context_extraction_prompt."""

    def test_empty_session_output(self) -> None:
        """Test with empty session output."""
        result = build_context_extraction_prompt("")
        assert isinstance(result, str)
        assert "Session Output" in result

    def test_unicode_in_output(self) -> None:
        """Test unicode characters in output."""
        output = "发现：使用 React 框架 🚀"
        result = build_context_extraction_prompt(output)
        assert output in result

    def test_code_blocks_in_output(self) -> None:
        """Test code blocks in session output are preserved."""
        output = """Found pattern:
```python
def main():
    pass
```"""
        result = build_context_extraction_prompt(output)
        assert "```python" in result
        assert "def main():" in result


# =============================================================================
# build_error_recovery_prompt Tests
# =============================================================================


class TestBuildErrorRecoveryPromptBasic:
    """Tests for basic build_error_recovery_prompt functionality."""

    def test_returns_string(self) -> None:
        """Test that build_error_recovery_prompt returns a string."""
        result = build_error_recovery_prompt("Error occurred")
        assert isinstance(result, str)

    def test_returns_non_empty_string(self) -> None:
        """Test that build_error_recovery_prompt returns non-empty string."""
        result = build_error_recovery_prompt("Error occurred")
        assert len(result) > 0

    def test_error_message_included(self) -> None:
        """Test that error message is included."""
        error = "ModuleNotFoundError: No module named 'flask'"
        result = build_error_recovery_prompt(error)
        assert error in result

    def test_error_section_present(self) -> None:
        """Test Error section is present."""
        result = build_error_recovery_prompt("Any error")
        assert "## Error" in result

    def test_error_in_code_block(self) -> None:
        """Test error message is in code block."""
        result = build_error_recovery_prompt("Test error")
        assert "```" in result
        assert "Test error" in result


class TestTaskContextSection:
    """Tests for task context section in error recovery prompt."""

    def test_no_task_context_by_default(self) -> None:
        """Test no task context section when None."""
        result = build_error_recovery_prompt("Error", task_context=None)
        assert "Task Context" not in result

    def test_task_context_included_when_provided(self) -> None:
        """Test task context is included when provided."""
        result = build_error_recovery_prompt(
            error_message="Test failed",
            task_context="Running unit tests for auth module",
        )
        assert "Task Context" in result
        assert "Running unit tests for auth module" in result

    def test_multiline_task_context(self) -> None:
        """Test multiline task context is preserved."""
        context = """Attempting to:
1. Run test suite
2. Check coverage
3. Generate report"""
        result = build_error_recovery_prompt("Error", task_context=context)
        assert "Run test suite" in result
        assert "Check coverage" in result
        assert "Generate report" in result


class TestAttemptedActionsSection:
    """Tests for attempted actions section in error recovery prompt."""

    def test_no_attempted_actions_by_default(self) -> None:
        """Test no attempted actions section when None."""
        result = build_error_recovery_prompt("Error", attempted_actions=None)
        assert "Already Tried" not in result

    def test_attempted_actions_included_when_provided(self) -> None:
        """Test attempted actions are included when provided."""
        result = build_error_recovery_prompt(
            error_message="Connection refused",
            attempted_actions=["Restarted server", "Checked port availability"],
        )
        assert "Already Tried" in result
        assert "Restarted server" in result
        assert "Checked port availability" in result

    def test_empty_attempted_actions_list(self) -> None:
        """Test empty attempted actions list."""
        result = build_error_recovery_prompt("Error", attempted_actions=[])
        # Empty list is falsy, so section should not appear
        assert "Already Tried" not in result

    def test_single_attempted_action(self) -> None:
        """Test single attempted action."""
        result = build_error_recovery_prompt(
            error_message="Error",
            attempted_actions=["Cleared cache"],
        )
        assert "Already Tried" in result
        assert "Cleared cache" in result

    def test_multiple_attempted_actions(self) -> None:
        """Test multiple attempted actions."""
        actions = [
            "Restarted service",
            "Cleared cache",
            "Updated dependencies",
            "Checked logs",
        ]
        result = build_error_recovery_prompt("Error", attempted_actions=actions)
        for action in actions:
            assert action in result

    def test_attempted_actions_formatted_as_list(self) -> None:
        """Test attempted actions are formatted as list items."""
        result = build_error_recovery_prompt(
            error_message="Error",
            attempted_actions=["Action 1", "Action 2"],
        )
        # Actions should be formatted with bullet points
        assert "- Action 1" in result or "Action 1" in result
        assert "- Action 2" in result or "Action 2" in result


class TestRecoveryStepsSection:
    """Tests for recovery steps section in error recovery prompt."""

    def test_recovery_steps_present(self) -> None:
        """Test Recovery Steps section is present."""
        result = build_error_recovery_prompt("Any error")
        assert "Recovery Steps" in result

    def test_analyze_error_step(self) -> None:
        """Test analyze error step is present."""
        result = build_error_recovery_prompt("Any error")
        assert "Analyze" in result and "error" in result.lower()

    def test_identify_fix_step(self) -> None:
        """Test identify fix step is present."""
        result = build_error_recovery_prompt("Any error")
        assert "Identify" in result or "fix" in result.lower()

    def test_implement_fix_step(self) -> None:
        """Test implement fix step is present."""
        result = build_error_recovery_prompt("Any error")
        assert "Implement" in result

    def test_verify_step(self) -> None:
        """Test verify step is present."""
        result = build_error_recovery_prompt("Any error")
        assert "Verify" in result

    def test_resume_step(self) -> None:
        """Test resume step is present."""
        result = build_error_recovery_prompt("Any error")
        assert "Resume" in result or "continue" in result.lower()

    def test_unrecoverable_guidance(self) -> None:
        """Test guidance for unrecoverable errors is present."""
        result = build_error_recovery_prompt("Any error")
        assert "unrecoverable" in result.lower() or "intervention" in result.lower()


class TestErrorRecoveryEdgeCases:
    """Edge case tests for build_error_recovery_prompt."""

    def test_empty_error_message(self) -> None:
        """Test with empty error message."""
        result = build_error_recovery_prompt("")
        assert isinstance(result, str)
        assert "## Error" in result

    def test_multiline_error_message(self) -> None:
        """Test multiline error message."""
        error = """Traceback (most recent call last):
  File "main.py", line 10, in <module>
    raise ValueError("Invalid input")
ValueError: Invalid input"""
        result = build_error_recovery_prompt(error)
        assert "Traceback" in result
        assert "ValueError" in result

    def test_error_with_special_characters(self) -> None:
        """Test error with special characters."""
        error = "Error: Can't open file 'test.txt' <FileNotFound>"
        result = build_error_recovery_prompt(error)
        assert error in result

    def test_unicode_error_message(self) -> None:
        """Test unicode characters in error message."""
        error = "错误：文件未找到 🚫"
        result = build_error_recovery_prompt(error)
        assert error in result

    def test_all_optional_params(self) -> None:
        """Test with all optional parameters provided."""
        result = build_error_recovery_prompt(
            error_message="Connection timeout",
            task_context="Connecting to API",
            attempted_actions=["Retried 3 times", "Checked network"],
        )
        assert "Connection timeout" in result
        assert "Task Context" in result
        assert "Connecting to API" in result
        assert "Already Tried" in result
        assert "Retried 3 times" in result
        assert "Checked network" in result


# =============================================================================
# Function Signature Tests
# =============================================================================


class TestVerificationPromptSignature:
    """Tests for build_verification_prompt function signature."""

    def test_criteria_is_required(self) -> None:
        """Test criteria parameter is required."""
        import inspect

        result = build_verification_prompt("Criteria")
        assert isinstance(result, str)

        # Verify parameter is required (has no default value)
        sig = inspect.signature(build_verification_prompt)
        params = sig.parameters
        assert "criteria" in params
        assert params["criteria"].default is inspect.Parameter.empty

    def test_tasks_summary_is_optional(self) -> None:
        """Test tasks_summary parameter is optional."""
        result1 = build_verification_prompt("Criteria")
        assert isinstance(result1, str)

        result2 = build_verification_prompt("Criteria", tasks_summary="Tasks")
        assert isinstance(result2, str)

    def test_tasks_summary_keyword_arg(self) -> None:
        """Test tasks_summary can be keyword argument."""
        result = build_verification_prompt(criteria="Criteria", tasks_summary="Tasks")
        assert "Tasks" in result


class TestTaskCompletionCheckPromptSignature:
    """Tests for build_task_completion_check_prompt function signature."""

    def test_both_params_required(self) -> None:
        """Test both parameters are required."""
        import inspect

        result = build_task_completion_check_prompt("Task", "Output")
        assert isinstance(result, str)

        # Verify both parameters are required (have no default values)
        sig = inspect.signature(build_task_completion_check_prompt)
        params = sig.parameters
        assert "task_description" in params
        assert params["task_description"].default is inspect.Parameter.empty
        assert "session_output" in params
        assert params["session_output"].default is inspect.Parameter.empty

    def test_keyword_args(self) -> None:
        """Test keyword arguments work."""
        result = build_task_completion_check_prompt(
            task_description="Task", session_output="Output"
        )
        assert "Task" in result
        assert "Output" in result


class TestContextExtractionPromptSignature:
    """Tests for build_context_extraction_prompt function signature."""

    def test_session_output_required(self) -> None:
        """Test session_output parameter is required."""
        import inspect

        result = build_context_extraction_prompt("Output")
        assert isinstance(result, str)

        # Verify parameter is required (has no default value)
        sig = inspect.signature(build_context_extraction_prompt)
        params = sig.parameters
        assert "session_output" in params
        assert params["session_output"].default is inspect.Parameter.empty

    def test_existing_context_optional(self) -> None:
        """Test existing_context parameter is optional."""
        result1 = build_context_extraction_prompt("Output")
        assert isinstance(result1, str)

        result2 = build_context_extraction_prompt("Output", existing_context="Context")
        assert isinstance(result2, str)

    def test_keyword_args(self) -> None:
        """Test keyword arguments work."""
        result = build_context_extraction_prompt(
            session_output="Output", existing_context="Context"
        )
        assert "Output" in result
        assert "Context" in result


class TestErrorRecoveryPromptSignature:
    """Tests for build_error_recovery_prompt function signature."""

    def test_error_message_required(self) -> None:
        """Test error_message parameter is required."""
        import inspect

        result = build_error_recovery_prompt("Error")
        assert isinstance(result, str)

        # Verify parameter is required (has no default value)
        sig = inspect.signature(build_error_recovery_prompt)
        params = sig.parameters
        assert "error_message" in params
        assert params["error_message"].default is inspect.Parameter.empty

    def test_task_context_optional(self) -> None:
        """Test task_context parameter is optional."""
        result1 = build_error_recovery_prompt("Error")
        result2 = build_error_recovery_prompt("Error", task_context="Context")
        assert isinstance(result1, str)
        assert isinstance(result2, str)

    def test_attempted_actions_optional(self) -> None:
        """Test attempted_actions parameter is optional."""
        result1 = build_error_recovery_prompt("Error")
        result2 = build_error_recovery_prompt("Error", attempted_actions=["Action"])
        assert isinstance(result1, str)
        assert isinstance(result2, str)

    def test_keyword_args(self) -> None:
        """Test keyword arguments work."""
        result = build_error_recovery_prompt(
            error_message="Error",
            task_context="Context",
            attempted_actions=["Action"],
        )
        assert "Error" in result
        assert "Context" in result
        assert "Action" in result


# =============================================================================
# Integration Tests
# =============================================================================


class TestVerificationPromptIntegration:
    """Integration tests for build_verification_prompt."""

    def test_complete_prompt_structure(self) -> None:
        """Test complete prompt has all sections."""
        result = build_verification_prompt(
            criteria="Tests pass\nCI green",
            tasks_summary="Implemented feature",
        )
        assert "Claude Task Master" in result
        assert "Completed Tasks" in result
        assert "Success Criteria" in result
        assert "Verification Steps" in result
        assert "VERIFICATION_RESULT" in result

    def test_prompt_length_reasonable(self) -> None:
        """Test prompt length is reasonable."""
        result = build_verification_prompt("Any criteria")
        assert len(result) > 200  # Has content
        assert len(result) < 5000  # Not too long


class TestContextExtractionIntegration:
    """Integration tests for build_context_extraction_prompt."""

    def test_complete_prompt_structure(self) -> None:
        """Test complete prompt has all sections."""
        result = build_context_extraction_prompt(
            session_output="Found React patterns",
            existing_context="Previously: uses Flask",
        )
        assert "learnings" in result.lower()
        assert "Existing Context" in result
        assert "Session Output" in result
        assert "Extract" in result
        assert "Patterns" in result


class TestErrorRecoveryIntegration:
    """Integration tests for build_error_recovery_prompt."""

    def test_complete_prompt_structure(self) -> None:
        """Test complete prompt has all sections."""
        result = build_error_recovery_prompt(
            error_message="Test failed",
            task_context="Running tests",
            attempted_actions=["Retried", "Checked logs"],
        )
        assert "## Error" in result
        assert "Task Context" in result
        assert "Already Tried" in result
        assert "Recovery Steps" in result

    def test_section_order(self) -> None:
        """Test sections appear in logical order."""
        result = build_error_recovery_prompt(
            error_message="Error",
            task_context="Context",
            attempted_actions=["Action"],
        )
        error_pos = result.find("## Error")
        context_pos = result.find("Task Context")
        tried_pos = result.find("Already Tried")
        steps_pos = result.find("Recovery Steps")

        # Verify order: Error -> Task Context -> Already Tried -> Recovery Steps
        assert error_pos < context_pos < tried_pos < steps_pos
