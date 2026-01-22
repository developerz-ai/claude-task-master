"""Tests for webhook events module.

Tests cover:
- EventType enum functionality
- Event class initialization and defaults
- Event serialization (to_dict)
- Event factory functions (create_event, get_event_class)
- Timestamp and ID generation
- Event type normalization
- All event classes: Task, PR, and Session events
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from claude_task_master.webhooks.events import (
    CIFailedEvent,
    CIPassedEvent,
    EventType,
    PlanUpdatedEvent,
    PRCreatedEvent,
    PRMergedEvent,
    RunCompletedEvent,
    RunStartedEvent,
    SessionCompletedEvent,
    SessionStartedEvent,
    StatusChangedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskStartedEvent,
    create_event,
    get_event_class,
)

# =============================================================================
# Test: EventType Enum
# =============================================================================


class TestEventTypeEnum:
    """Tests for EventType enum functionality."""

    def test_event_type_values(self) -> None:
        """Test that event types have correct string values."""
        # Task lifecycle events
        assert EventType.TASK_STARTED.value == "task.started"
        assert EventType.TASK_COMPLETED.value == "task.completed"
        assert EventType.TASK_FAILED.value == "task.failed"
        # PR events
        assert EventType.PR_CREATED.value == "pr.created"
        assert EventType.PR_MERGED.value == "pr.merged"
        # CI events
        assert EventType.CI_PASSED.value == "ci.passed"
        assert EventType.CI_FAILED.value == "ci.failed"
        # Session events
        assert EventType.SESSION_STARTED.value == "session.started"
        assert EventType.SESSION_COMPLETED.value == "session.completed"
        # Plan events
        assert EventType.PLAN_UPDATED.value == "plan.updated"
        # Orchestrator lifecycle events
        assert EventType.STATUS_CHANGED.value == "status.changed"
        assert EventType.RUN_STARTED.value == "run.started"
        assert EventType.RUN_COMPLETED.value == "run.completed"

    def test_event_type_from_string_valid(self) -> None:
        """Test converting valid strings to EventType."""
        assert EventType.from_string("task.started") == EventType.TASK_STARTED
        assert EventType.from_string("pr.created") == EventType.PR_CREATED
        assert EventType.from_string("session.completed") == EventType.SESSION_COMPLETED

    def test_event_type_from_string_invalid(self) -> None:
        """Test that invalid string raises ValueError."""
        with pytest.raises(ValueError, match="Unknown event type"):
            EventType.from_string("invalid.event")

    def test_event_type_str_returns_value(self) -> None:
        """Test that str() returns the event type value."""
        assert str(EventType.TASK_STARTED) == "task.started"
        assert str(EventType.PR_CREATED) == "pr.created"

    def test_all_event_types_exist(self) -> None:
        """Test that all expected event types are defined."""
        event_types = list(EventType)
        assert len(event_types) == 13
        # Task lifecycle events
        assert EventType.TASK_STARTED in event_types
        assert EventType.TASK_COMPLETED in event_types
        assert EventType.TASK_FAILED in event_types
        # PR events
        assert EventType.PR_CREATED in event_types
        assert EventType.PR_MERGED in event_types
        # CI events
        assert EventType.CI_PASSED in event_types
        assert EventType.CI_FAILED in event_types
        # Session events
        assert EventType.SESSION_STARTED in event_types
        assert EventType.SESSION_COMPLETED in event_types
        # Plan events
        assert EventType.PLAN_UPDATED in event_types
        # Orchestrator lifecycle events
        assert EventType.STATUS_CHANGED in event_types
        assert EventType.RUN_STARTED in event_types
        assert EventType.RUN_COMPLETED in event_types


# =============================================================================
# Test: WebhookEvent Base Class
# =============================================================================


class TestWebhookEventBase:
    """Tests for WebhookEvent base class."""

    def test_base_event_has_required_fields(self) -> None:
        """Test that base event has all required metadata fields."""
        event = TaskStartedEvent(task_index=0, task_description="Test")

        assert hasattr(event, "event_type")
        assert hasattr(event, "event_id")
        assert hasattr(event, "timestamp")
        assert hasattr(event, "run_id")

    def test_event_id_auto_generated(self) -> None:
        """Test that event_id is automatically generated."""
        event = TaskStartedEvent(task_index=0, task_description="Test")

        assert event.event_id is not None
        assert isinstance(event.event_id, str)
        # Should be a valid UUID
        uuid.UUID(event.event_id)

    def test_event_id_unique(self) -> None:
        """Test that each event gets a unique ID."""
        event1 = TaskStartedEvent(task_index=0, task_description="Test")
        event2 = TaskStartedEvent(task_index=0, task_description="Test")

        assert event1.event_id != event2.event_id

    def test_timestamp_auto_generated(self) -> None:
        """Test that timestamp is automatically generated."""
        event = TaskStartedEvent(task_index=0, task_description="Test")

        assert event.timestamp is not None
        assert isinstance(event.timestamp, str)
        # Should be valid ISO format
        datetime.fromisoformat(event.timestamp)

    def test_timestamp_has_timezone(self) -> None:
        """Test that timestamp includes timezone information."""
        event = TaskStartedEvent(task_index=0, task_description="Test")

        # ISO format should include timezone (ends with +00:00 or Z)
        assert "+" in event.timestamp or event.timestamp.endswith("Z")

    def test_run_id_optional(self) -> None:
        """Test that run_id is optional."""
        event = TaskStartedEvent(task_index=0, task_description="Test")
        assert event.run_id is None

        event_with_run_id = TaskStartedEvent(
            task_index=0, task_description="Test", run_id="run-123"
        )
        assert event_with_run_id.run_id == "run-123"

    def test_base_to_dict_includes_metadata(self) -> None:
        """Test that to_dict includes all base metadata."""
        event = TaskStartedEvent(
            task_index=1,
            task_description="Test",
            run_id="run-123",
        )

        data = event.to_dict()

        assert "event_type" in data
        assert "event_id" in data
        assert "timestamp" in data
        assert "run_id" in data
        assert data["event_type"] == "task.started"
        assert data["run_id"] == "run-123"

    def test_event_type_normalization_from_string(self) -> None:
        """Test that string event_type is normalized to EventType enum."""
        # This tests __post_init__ normalization
        event = TaskStartedEvent(task_index=0, task_description="Test")
        event.event_type = "task.started"  # type: ignore
        event.__post_init__()

        assert isinstance(event.event_type, EventType)
        assert event.event_type == EventType.TASK_STARTED


# =============================================================================
# Test: TaskStartedEvent
# =============================================================================


class TestTaskStartedEvent:
    """Tests for TaskStartedEvent serialization."""

    def test_task_started_event_initialization(self) -> None:
        """Test TaskStartedEvent initialization with required fields."""
        event = TaskStartedEvent(
            task_index=1,
            task_description="Implement feature X",
            total_tasks=10,
        )

        assert event.event_type == EventType.TASK_STARTED
        assert event.task_index == 1
        assert event.task_description == "Implement feature X"
        assert event.total_tasks == 10
        assert event.branch is None
        assert event.pr_group is None

    def test_task_started_event_with_optional_fields(self) -> None:
        """Test TaskStartedEvent with all fields."""
        event = TaskStartedEvent(
            task_index=2,
            task_description="Add tests",
            total_tasks=5,
            branch="feat/new-feature",
            pr_group="Feature Implementation",
            run_id="run-abc",
        )

        assert event.branch == "feat/new-feature"
        assert event.pr_group == "Feature Implementation"
        assert event.run_id == "run-abc"

    def test_task_started_event_to_dict(self) -> None:
        """Test TaskStartedEvent serialization."""
        event = TaskStartedEvent(
            task_index=3,
            task_description="Write documentation",
            total_tasks=8,
            branch="docs/update",
            pr_group="Documentation",
        )

        data = event.to_dict()

        assert data["event_type"] == "task.started"
        assert data["task_index"] == 3
        assert data["task_description"] == "Write documentation"
        assert data["total_tasks"] == 8
        assert data["branch"] == "docs/update"
        assert data["pr_group"] == "Documentation"
        assert "event_id" in data
        assert "timestamp" in data

    def test_task_started_event_defaults(self) -> None:
        """Test TaskStartedEvent with default values."""
        event = TaskStartedEvent()

        assert event.task_index == 0
        assert event.task_description == ""
        assert event.total_tasks == 0


# =============================================================================
# Test: TaskCompletedEvent
# =============================================================================


class TestTaskCompletedEvent:
    """Tests for TaskCompletedEvent serialization."""

    def test_task_completed_event_initialization(self) -> None:
        """Test TaskCompletedEvent initialization."""
        event = TaskCompletedEvent(
            task_index=1,
            task_description="Implement feature",
            total_tasks=10,
            completed_tasks=2,
        )

        assert event.event_type == EventType.TASK_COMPLETED
        assert event.task_index == 1
        assert event.task_description == "Implement feature"
        assert event.total_tasks == 10
        assert event.completed_tasks == 2

    def test_task_completed_event_with_all_fields(self) -> None:
        """Test TaskCompletedEvent with all optional fields."""
        event = TaskCompletedEvent(
            task_index=5,
            task_description="Add authentication",
            total_tasks=20,
            completed_tasks=6,
            duration_seconds=125.5,
            commit_hash="abc123def456",
            branch="feat/auth",
            pr_group="Auth Feature",
        )

        assert event.duration_seconds == 125.5
        assert event.commit_hash == "abc123def456"
        assert event.branch == "feat/auth"
        assert event.pr_group == "Auth Feature"

    def test_task_completed_event_to_dict(self) -> None:
        """Test TaskCompletedEvent serialization."""
        event = TaskCompletedEvent(
            task_index=3,
            task_description="Write tests",
            total_tasks=15,
            completed_tasks=4,
            duration_seconds=89.3,
            commit_hash="xyz789",
        )

        data = event.to_dict()

        assert data["event_type"] == "task.completed"
        assert data["task_index"] == 3
        assert data["task_description"] == "Write tests"
        assert data["total_tasks"] == 15
        assert data["completed_tasks"] == 4
        assert data["duration_seconds"] == 89.3
        assert data["commit_hash"] == "xyz789"

    def test_task_completed_event_defaults(self) -> None:
        """Test TaskCompletedEvent default values."""
        event = TaskCompletedEvent()

        assert event.task_index == 0
        assert event.completed_tasks == 0
        assert event.duration_seconds is None
        assert event.commit_hash is None


# =============================================================================
# Test: TaskFailedEvent
# =============================================================================


class TestTaskFailedEvent:
    """Tests for TaskFailedEvent serialization."""

    def test_task_failed_event_initialization(self) -> None:
        """Test TaskFailedEvent initialization."""
        event = TaskFailedEvent(
            task_index=2,
            task_description="Deploy to production",
            error_message="Connection timeout",
        )

        assert event.event_type == EventType.TASK_FAILED
        assert event.task_index == 2
        assert event.task_description == "Deploy to production"
        assert event.error_message == "Connection timeout"

    def test_task_failed_event_with_all_fields(self) -> None:
        """Test TaskFailedEvent with all fields."""
        event = TaskFailedEvent(
            task_index=7,
            task_description="Run tests",
            error_message="Tests failed: 3 failures",
            error_type="TestFailure",
            duration_seconds=45.2,
            branch="feat/broken",
            pr_group="Bug Fix",
            recoverable=True,
        )

        assert event.error_type == "TestFailure"
        assert event.duration_seconds == 45.2
        assert event.branch == "feat/broken"
        assert event.pr_group == "Bug Fix"
        assert event.recoverable is True

    def test_task_failed_event_to_dict(self) -> None:
        """Test TaskFailedEvent serialization."""
        event = TaskFailedEvent(
            task_index=1,
            task_description="Build project",
            error_message="Compilation error",
            error_type="BuildError",
            recoverable=False,
        )

        data = event.to_dict()

        assert data["event_type"] == "task.failed"
        assert data["task_index"] == 1
        assert data["task_description"] == "Build project"
        assert data["error_message"] == "Compilation error"
        assert data["error_type"] == "BuildError"
        assert data["recoverable"] is False

    def test_task_failed_event_defaults(self) -> None:
        """Test TaskFailedEvent default values."""
        event = TaskFailedEvent()

        assert event.task_index == 0
        assert event.error_message == ""
        assert event.error_type is None
        assert event.recoverable is True


# =============================================================================
# Test: PRCreatedEvent
# =============================================================================


class TestPRCreatedEvent:
    """Tests for PRCreatedEvent serialization."""

    def test_pr_created_event_initialization(self) -> None:
        """Test PRCreatedEvent initialization."""
        event = PRCreatedEvent(
            pr_number=123,
            pr_url="https://github.com/org/repo/pull/123",
            pr_title="feat: Add new feature",
            branch="feat/new-feature",
        )

        assert event.event_type == EventType.PR_CREATED
        assert event.pr_number == 123
        assert event.pr_url == "https://github.com/org/repo/pull/123"
        assert event.pr_title == "feat: Add new feature"
        assert event.branch == "feat/new-feature"

    def test_pr_created_event_with_all_fields(self) -> None:
        """Test PRCreatedEvent with all fields."""
        event = PRCreatedEvent(
            pr_number=456,
            pr_url="https://github.com/org/repo/pull/456",
            pr_title="fix: Fix critical bug",
            branch="fix/critical-bug",
            base_branch="develop",
            tasks_included=3,
            pr_group="Bug Fixes",
            repository="org/repo",
        )

        assert event.base_branch == "develop"
        assert event.tasks_included == 3
        assert event.pr_group == "Bug Fixes"
        assert event.repository == "org/repo"

    def test_pr_created_event_to_dict(self) -> None:
        """Test PRCreatedEvent serialization."""
        event = PRCreatedEvent(
            pr_number=789,
            pr_url="https://github.com/owner/project/pull/789",
            pr_title="docs: Update README",
            branch="docs/readme",
            tasks_included=1,
        )

        data = event.to_dict()

        assert data["event_type"] == "pr.created"
        assert data["pr_number"] == 789
        assert data["pr_url"] == "https://github.com/owner/project/pull/789"
        assert data["pr_title"] == "docs: Update README"
        assert data["branch"] == "docs/readme"
        assert data["tasks_included"] == 1

    def test_pr_created_event_defaults(self) -> None:
        """Test PRCreatedEvent default values."""
        event = PRCreatedEvent()

        assert event.pr_number == 0
        assert event.pr_url == ""
        assert event.base_branch == "main"
        assert event.tasks_included == 0


# =============================================================================
# Test: PRMergedEvent
# =============================================================================


class TestPRMergedEvent:
    """Tests for PRMergedEvent serialization."""

    def test_pr_merged_event_initialization(self) -> None:
        """Test PRMergedEvent initialization."""
        event = PRMergedEvent(
            pr_number=123,
            pr_url="https://github.com/org/repo/pull/123",
            pr_title="feat: Add feature",
            branch="feat/feature",
        )

        assert event.event_type == EventType.PR_MERGED
        assert event.pr_number == 123
        assert event.branch == "feat/feature"

    def test_pr_merged_event_with_all_fields(self) -> None:
        """Test PRMergedEvent with all fields."""
        event = PRMergedEvent(
            pr_number=456,
            pr_url="https://github.com/org/repo/pull/456",
            pr_title="fix: Critical fix",
            branch="fix/critical",
            base_branch="main",
            merge_commit_hash="abc123def456",
            merged_at="2024-01-15T10:30:00Z",
            pr_group="Hotfix",
            repository="org/repo",
            auto_merged=True,
        )

        assert event.base_branch == "main"
        assert event.merge_commit_hash == "abc123def456"
        assert event.merged_at == "2024-01-15T10:30:00Z"
        assert event.pr_group == "Hotfix"
        assert event.repository == "org/repo"
        assert event.auto_merged is True

    def test_pr_merged_event_to_dict(self) -> None:
        """Test PRMergedEvent serialization."""
        event = PRMergedEvent(
            pr_number=999,
            pr_url="https://github.com/test/project/pull/999",
            pr_title="chore: Update dependencies",
            branch="chore/deps",
            merge_commit_hash="xyz789",
            auto_merged=False,
        )

        data = event.to_dict()

        assert data["event_type"] == "pr.merged"
        assert data["pr_number"] == 999
        assert data["pr_url"] == "https://github.com/test/project/pull/999"
        assert data["merge_commit_hash"] == "xyz789"
        assert data["auto_merged"] is False

    def test_pr_merged_event_defaults(self) -> None:
        """Test PRMergedEvent default values."""
        event = PRMergedEvent()

        assert event.pr_number == 0
        assert event.merge_commit_hash is None
        assert event.auto_merged is False


# =============================================================================
# Test: SessionStartedEvent
# =============================================================================


class TestSessionStartedEvent:
    """Tests for SessionStartedEvent serialization."""

    def test_session_started_event_initialization(self) -> None:
        """Test SessionStartedEvent initialization."""
        event = SessionStartedEvent(
            session_number=1,
            task_index=0,
            task_description="Implement login",
        )

        assert event.event_type == EventType.SESSION_STARTED
        assert event.session_number == 1
        assert event.task_index == 0
        assert event.task_description == "Implement login"

    def test_session_started_event_with_all_fields(self) -> None:
        """Test SessionStartedEvent with all fields."""
        event = SessionStartedEvent(
            session_number=3,
            max_sessions=10,
            task_index=2,
            task_description="Write integration tests",
            phase="verification",
        )

        assert event.session_number == 3
        assert event.max_sessions == 10
        assert event.task_index == 2
        assert event.phase == "verification"

    def test_session_started_event_to_dict(self) -> None:
        """Test SessionStartedEvent serialization."""
        event = SessionStartedEvent(
            session_number=5,
            max_sessions=20,
            task_index=4,
            task_description="Deploy application",
            phase="working",
        )

        data = event.to_dict()

        assert data["event_type"] == "session.started"
        assert data["session_number"] == 5
        assert data["max_sessions"] == 20
        assert data["task_index"] == 4
        assert data["task_description"] == "Deploy application"
        assert data["phase"] == "working"

    def test_session_started_event_defaults(self) -> None:
        """Test SessionStartedEvent default values."""
        event = SessionStartedEvent()

        assert event.session_number == 1
        assert event.max_sessions is None
        assert event.phase == "working"


# =============================================================================
# Test: SessionCompletedEvent
# =============================================================================


class TestSessionCompletedEvent:
    """Tests for SessionCompletedEvent serialization."""

    def test_session_completed_event_initialization(self) -> None:
        """Test SessionCompletedEvent initialization."""
        event = SessionCompletedEvent(
            session_number=1,
            task_index=0,
            task_description="Setup project",
        )

        assert event.event_type == EventType.SESSION_COMPLETED
        assert event.session_number == 1
        assert event.task_index == 0

    def test_session_completed_event_with_all_fields(self) -> None:
        """Test SessionCompletedEvent with all fields."""
        event = SessionCompletedEvent(
            session_number=2,
            max_sessions=5,
            task_index=1,
            task_description="Implement API",
            phase="working",
            duration_seconds=234.5,
            result="success",
            tools_used=15,
            tokens_used=3500,
        )

        assert event.duration_seconds == 234.5
        assert event.result == "success"
        assert event.tools_used == 15
        assert event.tokens_used == 3500

    def test_session_completed_event_to_dict(self) -> None:
        """Test SessionCompletedEvent serialization."""
        event = SessionCompletedEvent(
            session_number=3,
            task_index=2,
            task_description="Run tests",
            phase="verification",
            duration_seconds=67.8,
            result="blocked",
            tools_used=8,
        )

        data = event.to_dict()

        assert data["event_type"] == "session.completed"
        assert data["session_number"] == 3
        assert data["task_index"] == 2
        assert data["phase"] == "verification"
        assert data["duration_seconds"] == 67.8
        assert data["result"] == "blocked"
        assert data["tools_used"] == 8

    def test_session_completed_event_defaults(self) -> None:
        """Test SessionCompletedEvent default values."""
        event = SessionCompletedEvent()

        assert event.session_number == 1
        assert event.result == "success"
        assert event.tools_used == 0
        assert event.tokens_used is None


# =============================================================================
# Test: CIPassedEvent
# =============================================================================


class TestCIPassedEvent:
    """Tests for CIPassedEvent serialization."""

    def test_ci_passed_event_initialization(self) -> None:
        """Test CIPassedEvent initialization."""
        event = CIPassedEvent(
            pr_number=123,
            pr_url="https://github.com/org/repo/pull/123",
            branch="feat/new-feature",
        )

        assert event.event_type == EventType.CI_PASSED
        assert event.pr_number == 123
        assert event.pr_url == "https://github.com/org/repo/pull/123"
        assert event.branch == "feat/new-feature"
        assert event.check_name is None
        assert event.check_url is None

    def test_ci_passed_event_with_all_fields(self) -> None:
        """Test CIPassedEvent with all fields."""
        event = CIPassedEvent(
            pr_number=456,
            pr_url="https://github.com/org/repo/pull/456",
            branch="fix/bug",
            check_name="pytest",
            check_url="https://github.com/org/repo/actions/runs/123",
            duration_seconds=45.3,
            repository="org/repo",
            run_id="run-xyz",
        )

        assert event.check_name == "pytest"
        assert event.check_url == "https://github.com/org/repo/actions/runs/123"
        assert event.duration_seconds == 45.3
        assert event.repository == "org/repo"
        assert event.run_id == "run-xyz"

    def test_ci_passed_event_to_dict(self) -> None:
        """Test CIPassedEvent serialization."""
        event = CIPassedEvent(
            pr_number=789,
            pr_url="https://github.com/test/project/pull/789",
            branch="feature/awesome",
            check_name="build",
            duration_seconds=120.5,
        )

        data = event.to_dict()

        assert data["event_type"] == "ci.passed"
        assert data["pr_number"] == 789
        assert data["pr_url"] == "https://github.com/test/project/pull/789"
        assert data["branch"] == "feature/awesome"
        assert data["check_name"] == "build"
        assert data["duration_seconds"] == 120.5
        assert "event_id" in data
        assert "timestamp" in data

    def test_ci_passed_event_defaults(self) -> None:
        """Test CIPassedEvent default values."""
        event = CIPassedEvent()

        assert event.pr_number == 0
        assert event.pr_url == ""
        assert event.branch == ""
        assert event.check_name is None
        assert event.duration_seconds is None


# =============================================================================
# Test: CIFailedEvent
# =============================================================================


class TestCIFailedEvent:
    """Tests for CIFailedEvent serialization."""

    def test_ci_failed_event_initialization(self) -> None:
        """Test CIFailedEvent initialization."""
        event = CIFailedEvent(
            pr_number=123,
            pr_url="https://github.com/org/repo/pull/123",
            branch="feat/broken",
        )

        assert event.event_type == EventType.CI_FAILED
        assert event.pr_number == 123
        assert event.pr_url == "https://github.com/org/repo/pull/123"
        assert event.branch == "feat/broken"
        assert event.check_name is None
        assert event.recoverable is True

    def test_ci_failed_event_with_all_fields(self) -> None:
        """Test CIFailedEvent with all fields."""
        event = CIFailedEvent(
            pr_number=456,
            pr_url="https://github.com/org/repo/pull/456",
            branch="fix/failing-test",
            check_name="lint",
            check_url="https://github.com/org/repo/actions/runs/456",
            failure_reason="Linting errors found",
            failure_log="Error: Line too long at line 42",
            duration_seconds=15.8,
            repository="org/repo",
            recoverable=False,
            run_id="run-abc",
        )

        assert event.check_name == "lint"
        assert event.check_url == "https://github.com/org/repo/actions/runs/456"
        assert event.failure_reason == "Linting errors found"
        assert event.failure_log == "Error: Line too long at line 42"
        assert event.duration_seconds == 15.8
        assert event.repository == "org/repo"
        assert event.recoverable is False
        assert event.run_id == "run-abc"

    def test_ci_failed_event_to_dict(self) -> None:
        """Test CIFailedEvent serialization."""
        event = CIFailedEvent(
            pr_number=999,
            pr_url="https://github.com/test/project/pull/999",
            branch="feature/test",
            check_name="pytest",
            failure_reason="3 tests failed",
            recoverable=True,
        )

        data = event.to_dict()

        assert data["event_type"] == "ci.failed"
        assert data["pr_number"] == 999
        assert data["pr_url"] == "https://github.com/test/project/pull/999"
        assert data["branch"] == "feature/test"
        assert data["check_name"] == "pytest"
        assert data["failure_reason"] == "3 tests failed"
        assert data["recoverable"] is True
        assert "event_id" in data
        assert "timestamp" in data

    def test_ci_failed_event_defaults(self) -> None:
        """Test CIFailedEvent default values."""
        event = CIFailedEvent()

        assert event.pr_number == 0
        assert event.pr_url == ""
        assert event.branch == ""
        assert event.check_name is None
        assert event.failure_reason is None
        assert event.failure_log is None
        assert event.recoverable is True


# =============================================================================
# Test: PlanUpdatedEvent
# =============================================================================


class TestPlanUpdatedEvent:
    """Tests for PlanUpdatedEvent serialization."""

    def test_plan_updated_event_initialization(self) -> None:
        """Test PlanUpdatedEvent initialization."""
        event = PlanUpdatedEvent(
            update_source="mailbox",
            tasks_added=2,
            total_tasks=10,
        )

        assert event.event_type == EventType.PLAN_UPDATED
        assert event.update_source == "mailbox"
        assert event.tasks_added == 2
        assert event.total_tasks == 10
        assert event.message is None

    def test_plan_updated_event_with_all_fields(self) -> None:
        """Test PlanUpdatedEvent with all fields."""
        event = PlanUpdatedEvent(
            update_source="resume",
            message="Add rate limiting to API",
            tasks_added=3,
            tasks_modified=1,
            tasks_removed=0,
            total_tasks=15,
            completed_tasks=7,
            run_id="run-123",
        )

        assert event.update_source == "resume"
        assert event.message == "Add rate limiting to API"
        assert event.tasks_added == 3
        assert event.tasks_modified == 1
        assert event.tasks_removed == 0
        assert event.total_tasks == 15
        assert event.completed_tasks == 7
        assert event.run_id == "run-123"

    def test_plan_updated_event_to_dict(self) -> None:
        """Test PlanUpdatedEvent serialization."""
        event = PlanUpdatedEvent(
            update_source="manual",
            message="Refactor authentication module",
            tasks_added=1,
            tasks_modified=2,
            tasks_removed=1,
            total_tasks=12,
            completed_tasks=5,
        )

        data = event.to_dict()

        assert data["event_type"] == "plan.updated"
        assert data["update_source"] == "manual"
        assert data["message"] == "Refactor authentication module"
        assert data["tasks_added"] == 1
        assert data["tasks_modified"] == 2
        assert data["tasks_removed"] == 1
        assert data["total_tasks"] == 12
        assert data["completed_tasks"] == 5
        assert "event_id" in data
        assert "timestamp" in data

    def test_plan_updated_event_defaults(self) -> None:
        """Test PlanUpdatedEvent default values."""
        event = PlanUpdatedEvent()

        assert event.update_source == "manual"
        assert event.message is None
        assert event.tasks_added == 0
        assert event.tasks_modified == 0
        assert event.tasks_removed == 0
        assert event.total_tasks == 0
        assert event.completed_tasks == 0


# =============================================================================
# Test: StatusChangedEvent
# =============================================================================


class TestStatusChangedEvent:
    """Tests for StatusChangedEvent serialization."""

    def test_status_changed_event_initialization(self) -> None:
        """Test StatusChangedEvent initialization."""
        event = StatusChangedEvent(
            previous_status="idle",
            new_status="planning",
        )

        assert event.event_type == EventType.STATUS_CHANGED
        assert event.previous_status == "idle"
        assert event.new_status == "planning"
        assert event.reason is None

    def test_status_changed_event_with_all_fields(self) -> None:
        """Test StatusChangedEvent with all fields."""
        event = StatusChangedEvent(
            previous_status="working",
            new_status="blocked",
            reason="Waiting for CI checks",
            task_index=3,
            session_number=5,
            run_id="run-xyz",
        )

        assert event.previous_status == "working"
        assert event.new_status == "blocked"
        assert event.reason == "Waiting for CI checks"
        assert event.task_index == 3
        assert event.session_number == 5
        assert event.run_id == "run-xyz"

    def test_status_changed_event_to_dict(self) -> None:
        """Test StatusChangedEvent serialization."""
        event = StatusChangedEvent(
            previous_status="planning",
            new_status="working",
            reason="Plan approved",
            task_index=0,
        )

        data = event.to_dict()

        assert data["event_type"] == "status.changed"
        assert data["previous_status"] == "planning"
        assert data["new_status"] == "working"
        assert data["reason"] == "Plan approved"
        assert data["task_index"] == 0
        assert "event_id" in data
        assert "timestamp" in data

    def test_status_changed_event_defaults(self) -> None:
        """Test StatusChangedEvent default values."""
        event = StatusChangedEvent()

        assert event.previous_status == ""
        assert event.new_status == ""
        assert event.reason is None
        assert event.task_index is None
        assert event.session_number is None


# =============================================================================
# Test: RunStartedEvent
# =============================================================================


class TestRunStartedEvent:
    """Tests for RunStartedEvent serialization."""

    def test_run_started_event_initialization(self) -> None:
        """Test RunStartedEvent initialization."""
        event = RunStartedEvent(
            goal="Implement user authentication",
            working_directory="/home/user/project",
        )

        assert event.event_type == EventType.RUN_STARTED
        assert event.goal == "Implement user authentication"
        assert event.working_directory == "/home/user/project"
        assert event.max_sessions is None
        assert event.auto_merge is False

    def test_run_started_event_with_all_fields(self) -> None:
        """Test RunStartedEvent with all fields."""
        event = RunStartedEvent(
            goal="Add API rate limiting",
            working_directory="/workspace/api-project",
            max_sessions=20,
            auto_merge=True,
            pr_mode="per-task",
            resumed=True,
            run_id="run-abc123",
        )

        assert event.goal == "Add API rate limiting"
        assert event.working_directory == "/workspace/api-project"
        assert event.max_sessions == 20
        assert event.auto_merge is True
        assert event.pr_mode == "per-task"
        assert event.resumed is True
        assert event.run_id == "run-abc123"

    def test_run_started_event_to_dict(self) -> None:
        """Test RunStartedEvent serialization."""
        event = RunStartedEvent(
            goal="Fix critical bug",
            working_directory="/code/bugfix",
            max_sessions=10,
            auto_merge=False,
            pr_mode="per-group",
            resumed=False,
        )

        data = event.to_dict()

        assert data["event_type"] == "run.started"
        assert data["goal"] == "Fix critical bug"
        assert data["working_directory"] == "/code/bugfix"
        assert data["max_sessions"] == 10
        assert data["auto_merge"] is False
        assert data["pr_mode"] == "per-group"
        assert data["resumed"] is False
        assert "event_id" in data
        assert "timestamp" in data

    def test_run_started_event_defaults(self) -> None:
        """Test RunStartedEvent default values."""
        event = RunStartedEvent()

        assert event.goal == ""
        assert event.working_directory == ""
        assert event.max_sessions is None
        assert event.auto_merge is False
        assert event.pr_mode == "per-group"
        assert event.resumed is False


# =============================================================================
# Test: RunCompletedEvent
# =============================================================================


class TestRunCompletedEvent:
    """Tests for RunCompletedEvent serialization."""

    def test_run_completed_event_initialization(self) -> None:
        """Test RunCompletedEvent initialization."""
        event = RunCompletedEvent(
            goal="Implement feature X",
            result="success",
            exit_code=0,
            total_tasks=10,
            completed_tasks=10,
        )

        assert event.event_type == EventType.RUN_COMPLETED
        assert event.goal == "Implement feature X"
        assert event.result == "success"
        assert event.exit_code == 0
        assert event.total_tasks == 10
        assert event.completed_tasks == 10

    def test_run_completed_event_with_all_fields(self) -> None:
        """Test RunCompletedEvent with all fields."""
        event = RunCompletedEvent(
            goal="Deploy application",
            result="blocked",
            exit_code=1,
            total_tasks=15,
            completed_tasks=12,
            total_sessions=25,
            duration_seconds=3600.5,
            prs_created=3,
            prs_merged=2,
            final_status="waiting_for_approval",
            error_message="Manual approval required",
            run_id="run-final",
        )

        assert event.goal == "Deploy application"
        assert event.result == "blocked"
        assert event.exit_code == 1
        assert event.total_tasks == 15
        assert event.completed_tasks == 12
        assert event.total_sessions == 25
        assert event.duration_seconds == 3600.5
        assert event.prs_created == 3
        assert event.prs_merged == 2
        assert event.final_status == "waiting_for_approval"
        assert event.error_message == "Manual approval required"
        assert event.run_id == "run-final"

    def test_run_completed_event_to_dict(self) -> None:
        """Test RunCompletedEvent serialization."""
        event = RunCompletedEvent(
            goal="Refactor codebase",
            result="failed",
            exit_code=2,
            total_tasks=8,
            completed_tasks=5,
            total_sessions=15,
            duration_seconds=1800.0,
            prs_created=2,
            prs_merged=1,
            final_status="failed",
            error_message="Unrecoverable error",
        )

        data = event.to_dict()

        assert data["event_type"] == "run.completed"
        assert data["goal"] == "Refactor codebase"
        assert data["result"] == "failed"
        assert data["exit_code"] == 2
        assert data["total_tasks"] == 8
        assert data["completed_tasks"] == 5
        assert data["total_sessions"] == 15
        assert data["duration_seconds"] == 1800.0
        assert data["prs_created"] == 2
        assert data["prs_merged"] == 1
        assert data["final_status"] == "failed"
        assert data["error_message"] == "Unrecoverable error"
        assert "event_id" in data
        assert "timestamp" in data

    def test_run_completed_event_defaults(self) -> None:
        """Test RunCompletedEvent default values."""
        event = RunCompletedEvent()

        assert event.goal == ""
        assert event.result == "success"
        assert event.exit_code == 0
        assert event.total_tasks == 0
        assert event.completed_tasks == 0
        assert event.total_sessions == 0
        assert event.duration_seconds is None
        assert event.prs_created == 0
        assert event.prs_merged == 0
        assert event.final_status == ""
        assert event.error_message is None


# =============================================================================
# Test: Event Factory - create_event()
# =============================================================================


class TestCreateEvent:
    """Tests for create_event factory function."""

    def test_create_event_with_enum(self) -> None:
        """Test creating event with EventType enum."""
        event = create_event(
            EventType.TASK_STARTED,
            task_index=1,
            task_description="Test task",
        )

        assert isinstance(event, TaskStartedEvent)
        assert event.event_type == EventType.TASK_STARTED
        assert event.task_index == 1

    def test_create_event_with_string(self) -> None:
        """Test creating event with string event type."""
        event = create_event(
            "task.completed",
            task_index=2,
            task_description="Completed task",
        )

        assert isinstance(event, TaskCompletedEvent)
        assert event.event_type == EventType.TASK_COMPLETED

    def test_create_event_all_types(self) -> None:
        """Test creating all event types via factory."""
        events = [
            (EventType.TASK_STARTED, TaskStartedEvent, {"task_index": 0}),
            (EventType.TASK_COMPLETED, TaskCompletedEvent, {"task_index": 0}),
            (EventType.TASK_FAILED, TaskFailedEvent, {"task_index": 0}),
            (EventType.PR_CREATED, PRCreatedEvent, {"pr_number": 1}),
            (EventType.PR_MERGED, PRMergedEvent, {"pr_number": 1}),
            (EventType.CI_PASSED, CIPassedEvent, {"pr_number": 1}),
            (EventType.CI_FAILED, CIFailedEvent, {"pr_number": 1}),
            (EventType.SESSION_STARTED, SessionStartedEvent, {}),
            (EventType.SESSION_COMPLETED, SessionCompletedEvent, {}),
            (EventType.PLAN_UPDATED, PlanUpdatedEvent, {}),
            (EventType.STATUS_CHANGED, StatusChangedEvent, {}),
            (EventType.RUN_STARTED, RunStartedEvent, {}),
            (EventType.RUN_COMPLETED, RunCompletedEvent, {}),
        ]

        for event_type, expected_class, kwargs in events:
            event = create_event(event_type, **kwargs)
            assert isinstance(event, expected_class)
            assert event.event_type == event_type

    def test_create_event_with_run_id(self) -> None:
        """Test creating event with run_id."""
        event = create_event(
            EventType.TASK_STARTED,
            task_index=0,
            run_id="test-run-123",
        )

        assert event.run_id == "test-run-123"

    def test_create_event_invalid_type_raises(self) -> None:
        """Test that invalid event type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown event type"):
            create_event("invalid.event")


# =============================================================================
# Test: get_event_class()
# =============================================================================


class TestGetEventClass:
    """Tests for get_event_class helper function."""

    def test_get_event_class_with_enum(self) -> None:
        """Test getting event class with enum."""
        cls = get_event_class(EventType.TASK_STARTED)
        assert cls is TaskStartedEvent

    def test_get_event_class_with_string(self) -> None:
        """Test getting event class with string."""
        cls = get_event_class("pr.created")
        assert cls is PRCreatedEvent

    def test_get_event_class_all_types(self) -> None:
        """Test getting all event classes."""
        mappings = {
            EventType.TASK_STARTED: TaskStartedEvent,
            EventType.TASK_COMPLETED: TaskCompletedEvent,
            EventType.TASK_FAILED: TaskFailedEvent,
            EventType.PR_CREATED: PRCreatedEvent,
            EventType.PR_MERGED: PRMergedEvent,
            EventType.CI_PASSED: CIPassedEvent,
            EventType.CI_FAILED: CIFailedEvent,
            EventType.SESSION_STARTED: SessionStartedEvent,
            EventType.SESSION_COMPLETED: SessionCompletedEvent,
            EventType.PLAN_UPDATED: PlanUpdatedEvent,
            EventType.STATUS_CHANGED: StatusChangedEvent,
            EventType.RUN_STARTED: RunStartedEvent,
            EventType.RUN_COMPLETED: RunCompletedEvent,
        }

        for event_type, expected_class in mappings.items():
            cls = get_event_class(event_type)
            assert cls is expected_class

    def test_get_event_class_invalid_type_raises(self) -> None:
        """Test that invalid event type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown event type"):
            get_event_class("invalid.event")


# =============================================================================
# Test: Serialization Edge Cases
# =============================================================================


class TestSerializationEdgeCases:
    """Tests for edge cases in event serialization."""

    def test_event_with_none_optional_fields(self) -> None:
        """Test serialization with None values for optional fields."""
        event = TaskCompletedEvent(
            task_index=1,
            task_description="Test",
            duration_seconds=None,
            commit_hash=None,
        )

        data = event.to_dict()

        assert data["duration_seconds"] is None
        assert data["commit_hash"] is None

    def test_event_with_empty_strings(self) -> None:
        """Test serialization with empty string values."""
        event = TaskFailedEvent(
            task_index=0,
            task_description="",
            error_message="",
        )

        data = event.to_dict()

        assert data["task_description"] == ""
        assert data["error_message"] == ""

    def test_event_with_zero_values(self) -> None:
        """Test serialization with zero numeric values."""
        event = SessionCompletedEvent(
            session_number=1,
            task_index=0,
            duration_seconds=0.0,
            tools_used=0,
        )

        data = event.to_dict()

        assert data["duration_seconds"] == 0.0
        assert data["tools_used"] == 0

    def test_all_fields_present_in_dict(self) -> None:
        """Test that to_dict includes all event fields."""
        event = PRCreatedEvent(
            pr_number=123,
            pr_url="https://example.com/pr/123",
            pr_title="Test PR",
            branch="test",
            base_branch="main",
            tasks_included=5,
            pr_group="Group",
            repository="owner/repo",
        )

        data = event.to_dict()

        # Check all PR-specific fields are present
        assert "pr_number" in data
        assert "pr_url" in data
        assert "pr_title" in data
        assert "branch" in data
        assert "base_branch" in data
        assert "tasks_included" in data
        assert "pr_group" in data
        assert "repository" in data

        # Check base fields are also present
        assert "event_type" in data
        assert "event_id" in data
        assert "timestamp" in data
        assert "run_id" in data

    def test_boolean_fields_serialized_correctly(self) -> None:
        """Test that boolean fields are serialized correctly."""
        event_true = TaskFailedEvent(
            task_index=0,
            error_message="Error",
            recoverable=True,
        )
        event_false = TaskFailedEvent(
            task_index=0,
            error_message="Error",
            recoverable=False,
        )

        data_true = event_true.to_dict()
        data_false = event_false.to_dict()

        assert data_true["recoverable"] is True
        assert data_false["recoverable"] is False

    def test_float_fields_serialized_correctly(self) -> None:
        """Test that float fields maintain precision."""
        event = TaskCompletedEvent(
            task_index=0,
            duration_seconds=123.456789,
        )

        data = event.to_dict()

        assert data["duration_seconds"] == 123.456789
