"""Tests for the fixtures module.

This module tests that all fixture data is properly structured and usable.
"""

import json

import pytest


class TestMailboxMessageFixtures:
    """Tests for mailbox message fixtures."""

    def test_sample_messages_structure(self, sample_mailbox_messages):
        """Test sample messages have required fields."""
        assert len(sample_mailbox_messages) > 0
        for msg in sample_mailbox_messages:
            assert "content" in msg
            assert "sender" in msg
            assert "priority" in msg
            assert isinstance(msg["priority"], int)
            assert 0 <= msg["priority"] <= 3

    def test_multi_instance_messages(self, multi_instance_messages):
        """Test multi-instance messages have instance metadata."""
        assert len(multi_instance_messages) > 0
        for msg in multi_instance_messages:
            assert "sender" in msg
            assert msg["sender"].startswith("instance-")
            assert "metadata" in msg
            assert "instance_id" in msg["metadata"]

    def test_edge_case_messages(self, edge_case_mailbox_messages):
        """Test edge case messages for special content handling."""
        assert len(edge_case_mailbox_messages) > 0
        # Should include empty content, special chars, unicode, long content
        senders = [m["sender"] for m in edge_case_mailbox_messages]
        assert "empty-content" in senders
        assert "special-chars" in senders
        assert "unicode-test" in senders
        assert "long-content" in senders

    def test_empty_mailbox_state(self, empty_mailbox_state):
        """Test empty mailbox state structure."""
        assert empty_mailbox_state["messages"] == []
        assert empty_mailbox_state["last_checked"] is None
        assert empty_mailbox_state["total_messages_received"] == 0

    def test_sample_mailbox_state(self, sample_mailbox_state):
        """Test sample mailbox state has messages."""
        assert len(sample_mailbox_state["messages"]) > 0
        assert sample_mailbox_state["total_messages_received"] > 0

    def test_large_mailbox_state(self, large_mailbox_state):
        """Test large mailbox state for performance testing."""
        assert len(large_mailbox_state["messages"]) == 100
        assert large_mailbox_state["total_messages_received"] == 100

    def test_messages_sorted_by_priority(self, mailbox_messages_by_priority):
        """Test messages can be sorted by priority."""
        priorities = [m["priority"] for m in mailbox_messages_by_priority]
        assert priorities == sorted(priorities, reverse=True)


class TestCIFailureFixtures:
    """Tests for CI failure log fixtures."""

    def test_github_actions_failure(self, github_actions_failure):
        """Test GitHub Actions failure log content."""
        assert "npm test" in github_actions_failure or "FAIL" in github_actions_failure
        assert len(github_actions_failure) > 100

    def test_eslint_failure(self, eslint_failure):
        """Test ESLint failure log content."""
        assert "error" in eslint_failure.lower()
        assert "eslint" in eslint_failure.lower()

    def test_typescript_failure(self, typescript_failure):
        """Test TypeScript failure log content."""
        assert "error TS" in typescript_failure
        assert "Type" in typescript_failure

    def test_python_test_failure(self, python_test_failure):
        """Test pytest failure log content."""
        assert "FAIL" in python_test_failure
        assert "AssertionError" in python_test_failure

    def test_ruff_failure(self, ruff_failure):
        """Test ruff failure log content."""
        assert "ruff" in ruff_failure.lower()
        assert "error" in ruff_failure.lower() or "F401" in ruff_failure

    def test_build_failure(self, build_failure):
        """Test build failure log content."""
        assert "Error" in build_failure
        assert "Module not found" in build_failure or "build" in build_failure.lower()

    def test_combined_ci_failures(self, combined_ci_failures):
        """Test combined CI failures contain multiple job results."""
        assert "FAILED" in combined_ci_failures.upper()
        assert len(combined_ci_failures) > 500

    def test_all_ci_failure_types_dict(self, all_ci_failure_types):
        """Test all CI failure types dictionary."""
        expected_types = {
            "github-actions",
            "eslint",
            "typescript",
            "pytest",
            "ruff",
            "build",
            "combined",
        }
        assert expected_types.issubset(set(all_ci_failure_types.keys()))

    @pytest.mark.parametrize(
        "failure_type", ["github-actions", "eslint", "typescript", "pytest", "ruff", "build"]
    )
    def test_ci_failure_type_parametrized(self, failure_type, all_ci_failure_types):
        """Test each CI failure type is non-empty."""
        assert failure_type in all_ci_failure_types
        assert len(all_ci_failure_types[failure_type]) > 0


class TestPRCommentFixtures:
    """Tests for PR comment fixtures."""

    def test_coderabbit_comment(self, coderabbit_comment):
        """Test CodeRabbit comment structure."""
        assert "CodeRabbit" in coderabbit_comment
        assert "File:" in coderabbit_comment or "**File:**" in coderabbit_comment

    def test_human_reviewer_comment(self, human_reviewer_comment):
        """Test human reviewer comment structure."""
        assert "Review" in human_reviewer_comment
        assert len(human_reviewer_comment) > 100

    def test_automated_review_comment(self, automated_review_comment):
        """Test automated review comment structure."""
        assert "Automated" in automated_review_comment or "SonarCloud" in automated_review_comment

    def test_inline_code_comment(self, inline_code_comment):
        """Test inline code comment structure."""
        assert "File:" in inline_code_comment or "**File:**" in inline_code_comment
        assert "Line:" in inline_code_comment or "**Line:**" in inline_code_comment

    def test_combined_pr_comments(self, combined_pr_comments):
        """Test combined PR comments contain multiple sources."""
        assert "CodeRabbit" in combined_pr_comments
        assert len(combined_pr_comments) > 1000

    def test_all_pr_comment_types_dict(self, all_pr_comment_types):
        """Test all PR comment types dictionary."""
        expected_types = {"coderabbit", "human", "automated", "inline", "combined"}
        assert expected_types.issubset(set(all_pr_comment_types.keys()))

    def test_edge_case_pr_comments(self, edge_case_pr_comments):
        """Test edge case PR comments dictionary."""
        assert "empty" in edge_case_pr_comments
        assert "unicode" in edge_case_pr_comments
        assert "special_chars" in edge_case_pr_comments
        assert edge_case_pr_comments["empty"] == ""


class TestSamplePlanFixtures:
    """Tests for sample plan fixtures."""

    def test_simple_plan(self, simple_plan):
        """Test simple plan structure."""
        assert "## Task List" in simple_plan
        assert "- [ ]" in simple_plan
        assert "## Success Criteria" in simple_plan

    def test_partially_complete_plan(self, partially_complete_plan):
        """Test partially complete plan has both checked and unchecked tasks."""
        assert "- [x]" in partially_complete_plan
        assert "- [ ]" in partially_complete_plan

    def test_pr_grouped_plan(self, pr_grouped_plan):
        """Test PR-grouped plan structure."""
        assert "### PR" in pr_grouped_plan
        assert "PR 1:" in pr_grouped_plan or "PR 2:" in pr_grouped_plan

    def test_complex_plan(self, complex_plan):
        """Test complex plan has phases and notes."""
        assert "Phase" in complex_plan
        assert "## Notes" in complex_plan or "Notes" in complex_plan

    def test_completed_plan(self, completed_plan):
        """Test completed plan has all tasks checked."""
        assert "- [x]" in completed_plan
        # Should not have any unchecked tasks
        lines = completed_plan.split("\n")
        task_lines = [line for line in lines if line.strip().startswith("- [")]
        for line in task_lines:
            assert "[x]" in line, f"Expected all tasks complete, found: {line}"

    def test_empty_plan(self, empty_plan):
        """Test empty plan has no task checkboxes."""
        assert "- [ ]" not in empty_plan
        assert "- [x]" not in empty_plan

    def test_plan_with_code(self, plan_with_code):
        """Test plan with code contains code blocks."""
        assert "```" in plan_with_code

    def test_plan_before_update(self, plan_before_update):
        """Test plan before update structure."""
        assert "Feature A" in plan_before_update
        assert "Feature B" in plan_before_update

    def test_plan_after_update(self, plan_after_update):
        """Test plan after update has new tasks."""
        assert "Feature C" in plan_after_update or "NEW" in plan_after_update

    def test_all_plan_types_dict(self, all_plan_types):
        """Test all plan types dictionary."""
        expected_types = {"simple", "partial", "pr_grouped", "complex", "completed", "empty"}
        assert expected_types.issubset(set(all_plan_types.keys()))

    def test_plan_generator_n_tasks(self, plan_generator):
        """Test plan generator creates correct number of tasks."""
        plan = plan_generator["with_n_tasks"](5, completed=2)
        assert plan.count("- [ ]") == 3
        assert plan.count("- [x]") == 2

    def test_plan_generator_pr_groups(self, plan_generator):
        """Test plan generator creates correct number of PR groups."""
        plan = plan_generator["with_pr_groups"](3, tasks_per_group=2)
        assert "### PR 1:" in plan
        assert "### PR 2:" in plan
        assert "### PR 3:" in plan


class TestCombinedFixtures:
    """Tests for combined/integration fixtures."""

    def test_ci_failure_with_comments(self, ci_failure_with_comments):
        """Test combined CI failure and comments fixture."""
        assert ci_failure_with_comments["has_ci_failures"] is True
        assert ci_failure_with_comments["has_pr_comments"] is True
        assert len(ci_failure_with_comments["ci_failures"]) > 0
        assert len(ci_failure_with_comments["pr_comments"]) > 0

    def test_mailbox_with_plan_update(self, mailbox_with_plan_update):
        """Test mailbox with plan update fixture."""
        assert len(mailbox_with_plan_update["messages"]) > 0
        assert "Feature A" in mailbox_with_plan_update["plan_before"]
        assert mailbox_with_plan_update["expected_tasks_added"] > 0

    def test_full_workflow_fixture(self, full_workflow_fixture):
        """Test full workflow fixture has all components."""
        assert "mailbox_state" in full_workflow_fixture
        assert "ci_failures" in full_workflow_fixture
        assert "pr_comments" in full_workflow_fixture
        assert "plan" in full_workflow_fixture
        assert "timestamp" in full_workflow_fixture


class TestFileBasedFixtures:
    """Tests for file-based fixtures."""

    def test_ci_failure_file(self, ci_failure_file):
        """Test CI failure file is created and readable."""
        assert ci_failure_file.exists()
        content = ci_failure_file.read_text()
        assert "FAIL" in content.upper() or "ERROR" in content.upper()

    def test_pr_comments_file(self, pr_comments_file):
        """Test PR comments file is created and readable."""
        assert pr_comments_file.exists()
        content = pr_comments_file.read_text()
        assert len(content) > 100

    def test_plan_file(self, plan_file):
        """Test plan file is created and readable."""
        assert plan_file.exists()
        content = plan_file.read_text()
        assert "## Task List" in content

    def test_mailbox_json_file(self, mailbox_json_file):
        """Test mailbox JSON file is valid JSON."""
        assert mailbox_json_file.exists()
        content = mailbox_json_file.read_text()
        data = json.loads(content)
        assert "messages" in data

    def test_full_state_directory(self, full_state_directory):
        """Test full state directory has all expected files."""
        assert full_state_directory.exists()
        assert (full_state_directory / "plan.md").exists()
        assert (full_state_directory / "goal.txt").exists()
        assert (full_state_directory / "criteria.txt").exists()
        assert (full_state_directory / "mailbox.json").exists()
        assert (full_state_directory / "pr-123" / "ci" / "failures.txt").exists()
        assert (full_state_directory / "pr-123" / "comments" / "comments.md").exists()
        assert (full_state_directory / "logs").exists()
