"""Pytest fixtures for test data files.

This module exposes the test data from the fixtures package as pytest fixtures,
making them easily usable across all test modules.
"""

from datetime import datetime

import pytest

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
from tests.fixtures.pr_comments import (
    AUTOMATED_REVIEW_COMMENT,
    CODERABBIT_COMMENT,
    COMBINED_COMMENTS,
    EDGE_CASE_COMMENTS,
    HUMAN_REVIEWER_COMMENT,
    INLINE_CODE_COMMENT,
    get_pr_comment_for_type,
    get_sample_pr_comments,
)
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

# =============================================================================
# Mailbox Message Fixtures
# =============================================================================


@pytest.fixture
def sample_mailbox_messages():
    """Provide sample mailbox messages with various priorities."""
    return SAMPLE_MESSAGES.copy()


@pytest.fixture
def multi_instance_messages():
    """Provide messages for multi-instance coordination testing."""
    return MULTI_INSTANCE_MESSAGES.copy()


@pytest.fixture
def edge_case_mailbox_messages():
    """Provide edge case messages for testing special content."""
    return EDGE_CASE_MESSAGES.copy()


@pytest.fixture
def expected_merged_output():
    """Provide expected merged message output template."""
    return EXPECTED_MERGED_OUTPUT


@pytest.fixture
def empty_mailbox_state():
    """Provide an empty mailbox state dictionary."""
    return get_empty_mailbox_state()


@pytest.fixture
def sample_mailbox_state():
    """Provide a sample mailbox state with messages."""
    return get_sample_mailbox_state()


@pytest.fixture
def large_mailbox_state():
    """Provide a large mailbox state for performance testing."""
    return get_large_mailbox_state(100)


@pytest.fixture
def mailbox_messages_by_priority(sample_mailbox_messages):
    """Provide messages sorted by priority (highest first)."""
    return sorted(sample_mailbox_messages, key=lambda m: m["priority"], reverse=True)


# =============================================================================
# CI Failure Log Fixtures
# =============================================================================


@pytest.fixture
def github_actions_failure():
    """Provide GitHub Actions test failure log."""
    return GITHUB_ACTIONS_FAILURE


@pytest.fixture
def eslint_failure():
    """Provide ESLint failure log."""
    return ESLINT_FAILURE


@pytest.fixture
def typescript_failure():
    """Provide TypeScript compilation failure log."""
    return TYPESCRIPT_FAILURE


@pytest.fixture
def python_test_failure():
    """Provide pytest failure log."""
    return PYTHON_TEST_FAILURE


@pytest.fixture
def ruff_failure():
    """Provide ruff linting failure log."""
    return RUFF_FAILURE


@pytest.fixture
def build_failure():
    """Provide build failure log."""
    return BUILD_FAILURE


@pytest.fixture
def combined_ci_failures():
    """Provide combined CI failures (multiple jobs)."""
    return COMBINED_CI_FAILURES


@pytest.fixture
def all_ci_failure_types():
    """Provide dictionary of all CI failure types."""
    return get_sample_ci_failures()


@pytest.fixture(params=["github-actions", "eslint", "typescript", "pytest", "ruff", "build"])
def ci_failure_type(request):
    """Parametrized fixture for testing different CI failure types."""
    return request.param, get_ci_failure_for_type(request.param)


# =============================================================================
# PR Comment Fixtures
# =============================================================================


@pytest.fixture
def coderabbit_comment():
    """Provide CodeRabbit AI review comment."""
    return CODERABBIT_COMMENT


@pytest.fixture
def human_reviewer_comment():
    """Provide human reviewer comment."""
    return HUMAN_REVIEWER_COMMENT


@pytest.fixture
def automated_review_comment():
    """Provide automated review (SonarCloud) comment."""
    return AUTOMATED_REVIEW_COMMENT


@pytest.fixture
def inline_code_comment():
    """Provide inline code comment."""
    return INLINE_CODE_COMMENT


@pytest.fixture
def combined_pr_comments():
    """Provide combined PR comments from multiple sources."""
    return COMBINED_COMMENTS


@pytest.fixture
def all_pr_comment_types():
    """Provide dictionary of all PR comment types."""
    return get_sample_pr_comments()


@pytest.fixture
def edge_case_pr_comments():
    """Provide edge case PR comments for testing special content."""
    return EDGE_CASE_COMMENTS.copy()


@pytest.fixture(params=["coderabbit", "human", "automated", "inline"])
def pr_comment_type(request):
    """Parametrized fixture for testing different PR comment types."""
    return request.param, get_pr_comment_for_type(request.param)


# =============================================================================
# Sample Plan Fixtures
# =============================================================================


@pytest.fixture
def simple_plan():
    """Provide a simple plan with tasks."""
    return SIMPLE_PLAN


@pytest.fixture
def partially_complete_plan():
    """Provide a plan with some completed tasks."""
    return PARTIALLY_COMPLETE_PLAN


@pytest.fixture
def pr_grouped_plan():
    """Provide a plan with PR grouping structure."""
    return PR_GROUPED_PLAN


@pytest.fixture
def complex_plan():
    """Provide a complex plan with phases and notes."""
    return COMPLEX_PLAN


@pytest.fixture
def completed_plan():
    """Provide a plan with all tasks completed."""
    return COMPLETED_PLAN


@pytest.fixture
def empty_plan():
    """Provide an empty plan (no tasks)."""
    return EMPTY_PLAN


@pytest.fixture
def plan_with_code():
    """Provide a plan containing code examples."""
    return PLAN_WITH_CODE


@pytest.fixture
def plan_before_update():
    """Provide a plan before an update (for update testing)."""
    return PLAN_BEFORE_UPDATE


@pytest.fixture
def plan_after_update():
    """Provide a plan after an update (for update testing)."""
    return PLAN_AFTER_UPDATE


@pytest.fixture
def all_plan_types():
    """Provide dictionary of all plan types."""
    return get_sample_plans()


@pytest.fixture(params=["simple", "partial", "pr_grouped", "complex", "completed", "empty"])
def plan_type(request):
    """Parametrized fixture for testing different plan types."""
    return request.param, get_plan_for_type(request.param)


@pytest.fixture
def plan_generator():
    """Provide plan generator functions for dynamic test data."""
    return {
        "with_n_tasks": get_plan_with_n_tasks,
        "with_pr_groups": get_plan_with_pr_groups,
    }


# =============================================================================
# Combined Fixtures for Integration Testing
# =============================================================================


@pytest.fixture
def ci_failure_with_comments(combined_ci_failures, combined_pr_comments):
    """Provide combined CI failure and PR comments for testing combined handling."""
    return {
        "ci_failures": combined_ci_failures,
        "pr_comments": combined_pr_comments,
        "has_ci_failures": True,
        "has_pr_comments": True,
    }


@pytest.fixture
def mailbox_with_plan_update(sample_mailbox_messages, plan_before_update, plan_after_update):
    """Provide fixture for testing mailbox-triggered plan updates."""
    return {
        "messages": sample_mailbox_messages,
        "plan_before": plan_before_update,
        "plan_after": plan_after_update,
        "expected_tasks_added": 3,  # Feature C, Add logging, Add monitoring
    }


@pytest.fixture
def full_workflow_fixture(
    sample_mailbox_state,
    combined_ci_failures,
    combined_pr_comments,
    pr_grouped_plan,
):
    """Provide comprehensive fixture for full workflow integration tests."""
    return {
        "mailbox_state": sample_mailbox_state,
        "ci_failures": combined_ci_failures,
        "pr_comments": combined_pr_comments,
        "plan": pr_grouped_plan,
        "timestamp": datetime.now().isoformat(),
    }


# =============================================================================
# File-based Fixtures (write to temp directory)
# =============================================================================


@pytest.fixture
def ci_failure_file(tmp_path, combined_ci_failures):
    """Create a CI failure log file in temp directory."""
    ci_file = tmp_path / "ci_failures.txt"
    ci_file.write_text(combined_ci_failures)
    return ci_file


@pytest.fixture
def pr_comments_file(tmp_path, combined_pr_comments):
    """Create a PR comments file in temp directory."""
    comments_file = tmp_path / "pr_comments.md"
    comments_file.write_text(combined_pr_comments)
    return comments_file


@pytest.fixture
def plan_file(tmp_path, simple_plan):
    """Create a plan file in temp directory."""
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(simple_plan)
    return plan_file


@pytest.fixture
def mailbox_json_file(tmp_path, sample_mailbox_state):
    """Create a mailbox JSON file in temp directory."""
    import json

    mailbox_file = tmp_path / "mailbox.json"
    mailbox_file.write_text(json.dumps(sample_mailbox_state, default=str))
    return mailbox_file


@pytest.fixture
def full_state_directory(
    tmp_path,
    simple_plan,
    combined_ci_failures,
    combined_pr_comments,
    sample_mailbox_state,
):
    """Create a complete state directory structure with all fixture files."""
    import json

    state_dir = tmp_path / ".claude-task-master"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Create plan file
    (state_dir / "plan.md").write_text(simple_plan)

    # Create goal file
    (state_dir / "goal.txt").write_text("Complete the feature implementation with tests")

    # Create criteria file
    (state_dir / "criteria.txt").write_text(
        "1. All tests pass\n2. Code coverage > 80%\n3. Documentation complete"
    )

    # Create mailbox file
    (state_dir / "mailbox.json").write_text(json.dumps(sample_mailbox_state, default=str))

    # Create PR context directory
    pr_dir = state_dir / "pr-123"
    pr_dir.mkdir(parents=True, exist_ok=True)

    # Create CI failure log
    ci_dir = pr_dir / "ci"
    ci_dir.mkdir(parents=True, exist_ok=True)
    (ci_dir / "failures.txt").write_text(combined_ci_failures)

    # Create PR comments
    comments_dir = pr_dir / "comments"
    comments_dir.mkdir(parents=True, exist_ok=True)
    (comments_dir / "comments.md").write_text(combined_pr_comments)

    # Create logs directory
    logs_dir = state_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    return state_dir
