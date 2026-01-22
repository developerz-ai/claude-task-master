"""Test fixtures for claude-task-master tests.

This module provides sample test data and fixtures for:
- Mailbox messages (various priorities, multi-instance, edge cases)
- CI failure logs (GitHub Actions, ESLint, TypeScript, pytest, ruff, build)
- PR comments (CodeRabbit, human reviewers, automated tools)
- Sample plans (simple, complex, PR-grouped, with code)

Usage:
    # Import data directly
    from tests.fixtures.mailbox_messages import SAMPLE_MESSAGES
    from tests.fixtures.ci_failure_logs import GITHUB_ACTIONS_FAILURE

    # Use pytest fixtures (automatically available via conftest.py)
    def test_something(sample_mailbox_messages, combined_ci_failures):
        assert len(sample_mailbox_messages) > 0

    # Use parametrized fixtures for testing multiple types
    def test_all_ci_types(ci_failure_type):
        failure_type, failure_log = ci_failure_type
        assert len(failure_log) > 0
"""

# Mailbox message fixtures
# CI failure log fixtures
from tests.fixtures.ci_failure_logs import (
    BUILD_FAILURE,
    COMBINED_CI_FAILURES,
    ESLINT_FAILURE,
    GITHUB_ACTIONS_FAILURE,
    PYTHON_TEST_FAILURE,
    RUFF_FAILURE,
    TYPESCRIPT_FAILURE,
    get_ci_failure_for_type,
    get_sample_ci_failures,
)
from tests.fixtures.mailbox_messages import (
    EDGE_CASE_MESSAGES,
    EXPECTED_MERGED_OUTPUT,
    MULTI_INSTANCE_MESSAGES,
    SAMPLE_MESSAGES,
    get_empty_mailbox_state,
    get_large_mailbox_state,
    get_sample_mailbox_state,
)

# PR comment fixtures
from tests.fixtures.pr_comments import (
    AUTOMATED_REVIEW_COMMENT,
    CODERABBIT_COMMENT,
    COMBINED_COMMENTS,
    EDGE_CASE_COMMENTS,
    HUMAN_REVIEWER_COMMENT,
    INLINE_CODE_COMMENT,
    get_edge_case_comment,
    get_pr_comment_for_type,
    get_sample_pr_comments,
)

# Sample plan fixtures
from tests.fixtures.sample_plans import (
    COMPLETED_PLAN,
    COMPLEX_PLAN,
    EMPTY_PLAN,
    PARTIALLY_COMPLETE_PLAN,
    PLAN_AFTER_UPDATE,
    PLAN_BEFORE_UPDATE,
    PLAN_WITH_CODE,
    PR_GROUPED_PLAN,
    SIMPLE_PLAN,
    get_plan_for_type,
    get_plan_with_n_tasks,
    get_plan_with_pr_groups,
    get_sample_plans,
)

__all__ = [
    # Mailbox
    "SAMPLE_MESSAGES",
    "MULTI_INSTANCE_MESSAGES",
    "EDGE_CASE_MESSAGES",
    "EXPECTED_MERGED_OUTPUT",
    "get_sample_mailbox_state",
    "get_empty_mailbox_state",
    "get_large_mailbox_state",
    # CI Failures
    "GITHUB_ACTIONS_FAILURE",
    "ESLINT_FAILURE",
    "TYPESCRIPT_FAILURE",
    "PYTHON_TEST_FAILURE",
    "RUFF_FAILURE",
    "BUILD_FAILURE",
    "COMBINED_CI_FAILURES",
    "get_sample_ci_failures",
    "get_ci_failure_for_type",
    # PR Comments
    "CODERABBIT_COMMENT",
    "HUMAN_REVIEWER_COMMENT",
    "AUTOMATED_REVIEW_COMMENT",
    "INLINE_CODE_COMMENT",
    "COMBINED_COMMENTS",
    "EDGE_CASE_COMMENTS",
    "get_sample_pr_comments",
    "get_pr_comment_for_type",
    "get_edge_case_comment",
    # Plans
    "SIMPLE_PLAN",
    "PARTIALLY_COMPLETE_PLAN",
    "PR_GROUPED_PLAN",
    "COMPLEX_PLAN",
    "COMPLETED_PLAN",
    "EMPTY_PLAN",
    "PLAN_WITH_CODE",
    "PLAN_BEFORE_UPDATE",
    "PLAN_AFTER_UPDATE",
    "get_sample_plans",
    "get_plan_for_type",
    "get_plan_with_n_tasks",
    "get_plan_with_pr_groups",
]
