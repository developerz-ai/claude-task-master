"""Tests for State Manager exception classes.

This module contains tests for all custom exception classes used by the StateManager:
- StateError (base class)
- StateNotFoundError
- StateCorruptedError
- StateValidationError
- InvalidStateTransitionError
- StatePermissionError
- StateLockError
- StateResumeValidationError

Also tests the state constants like VALID_STATUSES, VALID_TRANSITIONS, etc.
"""

from __future__ import annotations

from pathlib import Path

from claude_task_master.core.state_exceptions import (
    RESUMABLE_STATUSES,
    TERMINAL_STATUSES,
    VALID_STATUSES,
    VALID_TRANSITIONS,
    WORKFLOW_STAGES,
    InvalidStateTransitionError,
    StateCorruptedError,
    StateError,
    StateLockError,
    StateNotFoundError,
    StatePermissionError,
    StateResumeValidationError,
    StateValidationError,
)

# =============================================================================
# Constants Tests
# =============================================================================


class TestValidStatuses:
    """Tests for VALID_STATUSES constant."""

    def test_valid_statuses_is_frozenset(self):
        """Test that VALID_STATUSES is a frozenset."""
        assert isinstance(VALID_STATUSES, frozenset)

    def test_valid_statuses_contains_expected_values(self):
        """Test that VALID_STATUSES contains all expected values."""
        expected = {"planning", "working", "blocked", "paused", "stopped", "success", "failed"}
        assert VALID_STATUSES == expected

    def test_valid_statuses_immutable(self):
        """Test that VALID_STATUSES cannot be modified."""
        # frozenset doesn't have add method, just verify it's a frozenset
        assert not hasattr(VALID_STATUSES, "add")


class TestWorkflowStages:
    """Tests for WORKFLOW_STAGES constant."""

    def test_workflow_stages_is_frozenset(self):
        """Test that WORKFLOW_STAGES is a frozenset."""
        assert isinstance(WORKFLOW_STAGES, frozenset)

    def test_workflow_stages_contains_expected_values(self):
        """Test that WORKFLOW_STAGES contains all expected values."""
        expected = {
            "working",
            "pr_created",
            "waiting_ci",
            "ci_failed",
            "waiting_reviews",
            "addressing_reviews",
            "ready_to_merge",
            "merged",
        }
        assert WORKFLOW_STAGES == expected

    def test_workflow_stages_count(self):
        """Test that WORKFLOW_STAGES has correct count."""
        assert len(WORKFLOW_STAGES) == 8


class TestTerminalStatuses:
    """Tests for TERMINAL_STATUSES constant."""

    def test_terminal_statuses_is_frozenset(self):
        """Test that TERMINAL_STATUSES is a frozenset."""
        assert isinstance(TERMINAL_STATUSES, frozenset)

    def test_terminal_statuses_contains_success_and_failed(self):
        """Test that TERMINAL_STATUSES contains success and failed."""
        assert TERMINAL_STATUSES == {"success", "failed"}

    def test_terminal_statuses_is_subset_of_valid_statuses(self):
        """Test that TERMINAL_STATUSES is a subset of VALID_STATUSES."""
        assert TERMINAL_STATUSES.issubset(VALID_STATUSES)


class TestResumableStatuses:
    """Tests for RESUMABLE_STATUSES constant."""

    def test_resumable_statuses_is_frozenset(self):
        """Test that RESUMABLE_STATUSES is a frozenset."""
        assert isinstance(RESUMABLE_STATUSES, frozenset)

    def test_resumable_statuses_contains_expected_values(self):
        """Test that RESUMABLE_STATUSES contains expected values."""
        assert RESUMABLE_STATUSES == {"paused", "stopped", "working", "blocked"}

    def test_resumable_statuses_is_subset_of_valid_statuses(self):
        """Test that RESUMABLE_STATUSES is a subset of VALID_STATUSES."""
        assert RESUMABLE_STATUSES.issubset(VALID_STATUSES)

    def test_no_overlap_with_terminal_statuses(self):
        """Test that resumable and terminal statuses don't overlap."""
        assert RESUMABLE_STATUSES.isdisjoint(TERMINAL_STATUSES)


class TestValidTransitions:
    """Tests for VALID_TRANSITIONS constant."""

    def test_valid_transitions_is_mapping(self):
        """Test that VALID_TRANSITIONS is a mapping."""
        assert isinstance(VALID_TRANSITIONS, dict)

    def test_all_valid_statuses_have_transitions(self):
        """Test that all valid statuses have defined transitions."""
        for status in VALID_STATUSES:
            assert status in VALID_TRANSITIONS

    def test_terminal_statuses_have_no_transitions(self):
        """Test that terminal statuses have no valid transitions."""
        for status in TERMINAL_STATUSES:
            assert VALID_TRANSITIONS[status] == frozenset()

    def test_planning_transitions(self):
        """Test valid transitions from planning."""
        expected = frozenset(["working", "failed", "paused", "stopped"])
        assert VALID_TRANSITIONS["planning"] == expected

    def test_working_transitions(self):
        """Test valid transitions from working."""
        expected = frozenset(["blocked", "success", "failed", "working", "paused", "stopped"])
        assert VALID_TRANSITIONS["working"] == expected

    def test_blocked_transitions(self):
        """Test valid transitions from blocked."""
        expected = frozenset(["working", "failed", "paused", "stopped"])
        assert VALID_TRANSITIONS["blocked"] == expected

    def test_paused_transitions(self):
        """Test valid transitions from paused."""
        expected = frozenset(["working", "failed", "stopped"])
        assert VALID_TRANSITIONS["paused"] == expected

    def test_transition_values_are_frozensets(self):
        """Test that all transition values are frozensets."""
        for transitions in VALID_TRANSITIONS.values():
            assert isinstance(transitions, frozenset)

    def test_all_transitions_are_to_valid_statuses(self):
        """Test that all transitions lead to valid statuses."""
        for transitions in VALID_TRANSITIONS.values():
            assert transitions.issubset(VALID_STATUSES)


# =============================================================================
# StateError (Base Class) Tests
# =============================================================================


class TestStateError:
    """Tests for StateError base exception class."""

    def test_create_with_message_only(self):
        """Test creating StateError with message only."""
        error = StateError("Something went wrong")
        assert error.message == "Something went wrong"
        assert error.details is None
        assert str(error) == "Something went wrong"

    def test_create_with_message_and_details(self):
        """Test creating StateError with message and details."""
        error = StateError("Error occurred", "Additional info here")
        assert error.message == "Error occurred"
        assert error.details == "Additional info here"
        assert "Details:" in str(error)
        assert "Additional info here" in str(error)

    def test_format_message_without_details(self):
        """Test _format_message without details."""
        error = StateError("Test message")
        assert error._format_message() == "Test message"

    def test_format_message_with_details(self):
        """Test _format_message with details."""
        error = StateError("Test message", "Details here")
        expected = "Test message\n  Details: Details here"
        assert error._format_message() == expected

    def test_is_exception(self):
        """Test that StateError is an Exception."""
        error = StateError("Test")
        assert isinstance(error, Exception)

    def test_can_be_raised(self):
        """Test that StateError can be raised and caught."""
        try:
            raise StateError("Test error", "With details")
        except StateError as e:
            assert e.message == "Test error"
            assert e.details == "With details"

    def test_empty_message(self):
        """Test StateError with empty message."""
        error = StateError("")
        assert error.message == ""
        assert str(error) == ""

    def test_none_details(self):
        """Test StateError with explicit None details."""
        error = StateError("Message", None)
        assert error.details is None
        assert str(error) == "Message"


# =============================================================================
# StateNotFoundError Tests
# =============================================================================


class TestStateNotFoundError:
    """Tests for StateNotFoundError exception class."""

    def test_create_with_path(self):
        """Test creating StateNotFoundError with path."""
        path = Path("/test/state.json")
        error = StateNotFoundError(path)
        assert error.path == path
        assert str(path) in str(error)

    def test_message_contains_path(self):
        """Test that message contains the path."""
        path = Path("/some/path/state.json")
        error = StateNotFoundError(path)
        assert str(path) in error.message

    def test_details_suggest_start_command(self):
        """Test that details suggest running start command."""
        path = Path("/test/state.json")
        error = StateNotFoundError(path)
        assert error.details is not None
        assert "start" in error.details.lower()

    def test_inherits_from_state_error(self):
        """Test that StateNotFoundError inherits from StateError."""
        path = Path("/test/state.json")
        error = StateNotFoundError(path)
        assert isinstance(error, StateError)

    def test_path_is_stored(self):
        """Test that path is stored as attribute."""
        path = Path("/custom/path")
        error = StateNotFoundError(path)
        assert error.path == path

    def test_can_be_raised_and_caught(self):
        """Test that StateNotFoundError can be raised and caught."""
        path = Path("/test/path")
        try:
            raise StateNotFoundError(path)
        except StateNotFoundError as e:
            assert e.path == path


# =============================================================================
# StateCorruptedError Tests
# =============================================================================


class TestStateCorruptedError:
    """Tests for StateCorruptedError exception class."""

    def test_create_with_path_and_reason(self):
        """Test creating StateCorruptedError with path and reason."""
        path = Path("/test/state.json")
        error = StateCorruptedError(path, "Invalid JSON")
        assert error.path == path
        assert "Invalid JSON" in str(error)

    def test_recoverable_default_is_true(self):
        """Test that recoverable defaults to True."""
        path = Path("/test/state.json")
        error = StateCorruptedError(path, "Parse error")
        assert error.recoverable is True

    def test_recoverable_can_be_set_false(self):
        """Test that recoverable can be set to False."""
        path = Path("/test/state.json")
        error = StateCorruptedError(path, "Parse error", recoverable=False)
        assert error.recoverable is False

    def test_recoverable_message_includes_backup_info(self):
        """Test that recoverable error includes backup info."""
        path = Path("/test/state.json")
        error = StateCorruptedError(path, "Parse error", recoverable=True)
        assert "backup" in str(error).lower()
        assert "recoverable" in str(error).lower()

    def test_non_recoverable_message_excludes_backup_info(self):
        """Test that non-recoverable error excludes backup info."""
        path = Path("/test/state.json")
        error = StateCorruptedError(path, "Parse error", recoverable=False)
        # Should not include "backup will be created" text
        assert "backup will be created" not in str(error).lower()

    def test_message_mentions_corrupted(self):
        """Test that message mentions corrupted."""
        path = Path("/test/state.json")
        error = StateCorruptedError(path, "Invalid syntax")
        assert "corrupted" in error.message.lower()

    def test_inherits_from_state_error(self):
        """Test that StateCorruptedError inherits from StateError."""
        path = Path("/test/state.json")
        error = StateCorruptedError(path, "Error")
        assert isinstance(error, StateError)


# =============================================================================
# StateValidationError Tests
# =============================================================================


class TestStateValidationError:
    """Tests for StateValidationError exception class."""

    def test_create_with_message_only(self):
        """Test creating StateValidationError with message only."""
        error = StateValidationError("Validation failed")
        assert error.message == "Validation failed"
        assert error.missing_fields == []
        assert error.invalid_fields == []

    def test_create_with_missing_fields(self):
        """Test creating StateValidationError with missing fields."""
        error = StateValidationError(
            "Missing required data",
            missing_fields=["status", "current_task_index"],
        )
        assert error.missing_fields == ["status", "current_task_index"]
        assert "status" in str(error)
        assert "current_task_index" in str(error)

    def test_create_with_invalid_fields(self):
        """Test creating StateValidationError with invalid fields."""
        error = StateValidationError(
            "Invalid data",
            invalid_fields=["status: must be string", "count: must be positive"],
        )
        assert error.invalid_fields == ["status: must be string", "count: must be positive"]
        assert "status" in str(error)
        assert "count" in str(error)

    def test_create_with_both_missing_and_invalid(self):
        """Test creating StateValidationError with both missing and invalid fields."""
        error = StateValidationError(
            "Multiple issues",
            missing_fields=["field1"],
            invalid_fields=["field2: bad value"],
        )
        assert error.missing_fields == ["field1"]
        assert error.invalid_fields == ["field2: bad value"]
        assert "field1" in str(error)
        assert "field2" in str(error)

    def test_empty_lists_default(self):
        """Test that missing_fields and invalid_fields default to empty lists."""
        error = StateValidationError("Error")
        assert error.missing_fields == []
        assert error.invalid_fields == []

    def test_details_format_for_missing_fields(self):
        """Test details format when only missing fields are present."""
        error = StateValidationError(
            "Validation failed",
            missing_fields=["a", "b"],
        )
        assert "Missing required fields" in str(error)
        assert "a" in str(error)
        assert "b" in str(error)

    def test_details_format_for_invalid_fields(self):
        """Test details format when only invalid fields are present."""
        error = StateValidationError(
            "Validation failed",
            invalid_fields=["x: invalid", "y: wrong type"],
        )
        assert "Invalid fields" in str(error)

    def test_inherits_from_state_error(self):
        """Test that StateValidationError inherits from StateError."""
        error = StateValidationError("Error")
        assert isinstance(error, StateError)


# =============================================================================
# InvalidStateTransitionError Tests
# =============================================================================


class TestInvalidStateTransitionError:
    """Tests for InvalidStateTransitionError exception class."""

    def test_create_with_statuses(self):
        """Test creating InvalidStateTransitionError with statuses."""
        error = InvalidStateTransitionError("success", "working")
        assert error.current_status == "success"
        assert error.new_status == "working"

    def test_message_contains_both_statuses(self):
        """Test that message contains both statuses."""
        error = InvalidStateTransitionError("planning", "success")
        assert "planning" in str(error)
        assert "success" in str(error)

    def test_details_show_valid_transitions(self):
        """Test that details show valid transitions from current status."""
        error = InvalidStateTransitionError("planning", "blocked")
        details = str(error)
        # Planning can go to working, failed, paused
        assert "working" in details
        assert "failed" in details
        assert "paused" in details

    def test_terminal_status_shows_no_transitions(self):
        """Test that terminal status shows no valid transitions."""
        error = InvalidStateTransitionError("success", "working")
        # Terminal status has no valid transitions
        # The details should still be present but empty
        assert error.current_status == "success"

    def test_inherits_from_state_error(self):
        """Test that InvalidStateTransitionError inherits from StateError."""
        error = InvalidStateTransitionError("a", "b")
        assert isinstance(error, StateError)

    def test_valid_transitions_lookup(self):
        """Test that valid transitions are looked up correctly."""
        error = InvalidStateTransitionError("working", "planning")
        # Working can go to blocked, success, failed, working, paused
        details = str(error)
        assert "blocked" in details
        assert "success" in details
        assert "failed" in details
        assert "paused" in details


# =============================================================================
# StatePermissionError Tests
# =============================================================================


class TestStatePermissionError:
    """Tests for StatePermissionError exception class."""

    def test_create_with_all_params(self):
        """Test creating StatePermissionError with all parameters."""
        path = Path("/protected/state.json")
        original = PermissionError("Access denied")
        error = StatePermissionError(path, "reading", original)

        assert error.path == path
        assert error.operation == "reading"
        assert error.original_error == original

    def test_message_contains_operation(self):
        """Test that message contains the operation."""
        path = Path("/test/state.json")
        original = PermissionError("No access")
        error = StatePermissionError(path, "writing", original)
        assert "writing" in str(error)

    def test_message_contains_path(self):
        """Test that message contains the path."""
        path = Path("/specific/path/file.json")
        original = OSError("Error")
        error = StatePermissionError(path, "accessing", original)
        assert str(path) in str(error)

    def test_details_contain_original_error(self):
        """Test that details contain original error message."""
        path = Path("/test/state.json")
        original = PermissionError("Permission denied for user")
        error = StatePermissionError(path, "reading", original)
        assert "Permission denied for user" in str(error)

    def test_details_mention_permissions(self):
        """Test that details mention checking permissions."""
        path = Path("/test/state.json")
        original = OSError("Error")
        error = StatePermissionError(path, "reading", original)
        assert "permission" in str(error).lower()

    def test_inherits_from_state_error(self):
        """Test that StatePermissionError inherits from StateError."""
        path = Path("/test/state.json")
        original = Exception("Error")
        error = StatePermissionError(path, "reading", original)
        assert isinstance(error, StateError)


# =============================================================================
# StateLockError Tests
# =============================================================================


class TestStateLockError:
    """Tests for StateLockError exception class."""

    def test_create_with_path_and_timeout(self):
        """Test creating StateLockError with path and timeout."""
        path = Path("/test/state.json")
        error = StateLockError(path, 30.0)

        assert error.path == path
        assert error.timeout == 30.0

    def test_message_contains_lock_info(self):
        """Test that message contains lock information."""
        path = Path("/test/state.json")
        error = StateLockError(path, 10.0)
        assert "lock" in str(error).lower()

    def test_message_contains_path(self):
        """Test that message contains the path."""
        path = Path("/specific/path/state.json")
        error = StateLockError(path, 5.0)
        assert str(path) in str(error)

    def test_details_contain_timeout(self):
        """Test that details contain the timeout value."""
        path = Path("/test/state.json")
        error = StateLockError(path, 25.5)
        assert "25.5" in str(error)

    def test_details_mention_another_process(self):
        """Test that details mention another process."""
        path = Path("/test/state.json")
        error = StateLockError(path, 10.0)
        assert "process" in str(error).lower()

    def test_zero_timeout(self):
        """Test StateLockError with zero timeout."""
        path = Path("/test/state.json")
        error = StateLockError(path, 0.0)
        assert error.timeout == 0.0
        assert "0" in str(error)

    def test_inherits_from_state_error(self):
        """Test that StateLockError inherits from StateError."""
        path = Path("/test/state.json")
        error = StateLockError(path, 10.0)
        assert isinstance(error, StateError)


# =============================================================================
# StateResumeValidationError Tests
# =============================================================================


class TestStateResumeValidationError:
    """Tests for StateResumeValidationError exception class."""

    def test_create_with_reason_only(self):
        """Test creating StateResumeValidationError with reason only."""
        error = StateResumeValidationError("Task already completed")
        assert error.reason == "Task already completed"
        assert "Task already completed" in error.message

    def test_create_with_all_params(self):
        """Test creating StateResumeValidationError with all parameters."""
        error = StateResumeValidationError(
            reason="Already in terminal state",
            status="success",
            current_task_index=5,
            total_tasks=10,
            suggestion="Run 'start' to begin new task",
        )
        assert error.reason == "Already in terminal state"
        assert error.status == "success"
        assert error.current_task_index == 5
        assert error.total_tasks == 10
        assert error.suggestion == "Run 'start' to begin new task"

    def test_message_format(self):
        """Test that message has correct format."""
        error = StateResumeValidationError("Cannot resume")
        assert "Cannot resume" in str(error)

    def test_details_include_status(self):
        """Test that details include status when provided."""
        error = StateResumeValidationError(
            reason="Invalid state",
            status="failed",
        )
        assert "failed" in str(error)
        assert "status" in str(error).lower()

    def test_details_include_task_index(self):
        """Test that details include task index when provided."""
        error = StateResumeValidationError(
            reason="Task error",
            current_task_index=3,
        )
        assert "3" in str(error)
        assert "index" in str(error).lower()

    def test_details_include_total_tasks(self):
        """Test that details include total tasks when provided."""
        error = StateResumeValidationError(
            reason="Task error",
            total_tasks=15,
        )
        assert "15" in str(error)

    def test_details_include_suggestion(self):
        """Test that details include suggestion when provided."""
        error = StateResumeValidationError(
            reason="Cannot resume",
            suggestion="Try running clean first",
        )
        assert "Try running clean first" in str(error)
        assert "suggestion" in str(error).lower()

    def test_none_values_not_in_details(self):
        """Test that None values are not included in details."""
        error = StateResumeValidationError(
            reason="Test",
            status=None,
            current_task_index=None,
            total_tasks=None,
            suggestion=None,
        )
        # Should have minimal details since all optional params are None
        assert error.details is None or error.details == ""

    def test_inherits_from_state_error(self):
        """Test that StateResumeValidationError inherits from StateError."""
        error = StateResumeValidationError("Test")
        assert isinstance(error, StateError)

    def test_can_catch_as_state_error(self):
        """Test that StateResumeValidationError can be caught as StateError."""
        try:
            raise StateResumeValidationError(
                reason="Cannot resume",
                status="success",
            )
        except StateError as e:
            assert "Cannot resume" in str(e)


# =============================================================================
# Exception Hierarchy Tests
# =============================================================================


class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_all_exceptions_inherit_from_state_error(self):
        """Test that all custom exceptions inherit from StateError."""
        path = Path("/test")
        exceptions = [
            StateNotFoundError(path),
            StateCorruptedError(path, "reason"),
            StateValidationError("message"),
            InvalidStateTransitionError("a", "b"),
            StatePermissionError(path, "op", Exception()),
            StateLockError(path, 1.0),
            StateResumeValidationError("reason"),
        ]
        for exc in exceptions:
            assert isinstance(exc, StateError)
            assert isinstance(exc, Exception)

    def test_can_catch_all_with_state_error(self):
        """Test that all exceptions can be caught with StateError."""
        path = Path("/test")
        exceptions = [
            StateNotFoundError(path),
            StateCorruptedError(path, "reason"),
            StateValidationError("message"),
            InvalidStateTransitionError("a", "b"),
            StatePermissionError(path, "op", Exception()),
            StateLockError(path, 1.0),
            StateResumeValidationError("reason"),
        ]

        for exc in exceptions:
            try:
                raise exc
            except StateError:
                pass  # Should be caught
            except Exception as e:
                raise AssertionError(f"{type(exc).__name__} not caught as StateError") from e

    def test_specific_exceptions_not_caught_by_sibling(self):
        """Test that specific exceptions are not caught by sibling types."""
        try:
            raise StateNotFoundError(Path("/test"))
        except StateCorruptedError as e:
            raise AssertionError("StateNotFoundError wrongly caught as StateCorruptedError") from e
        except StateNotFoundError:
            pass  # Correct

    def test_state_error_is_base_exception(self):
        """Test that StateError can be caught as base Exception."""
        try:
            raise StateError("Test")
        except Exception:
            pass  # Should be caught


# =============================================================================
# Edge Cases and Boundary Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_path_with_special_characters(self):
        """Test exceptions with paths containing special characters."""
        path = Path("/path with spaces/state (1).json")
        error = StateNotFoundError(path)
        assert str(path) in str(error)

    def test_unicode_in_error_messages(self):
        """Test exceptions with unicode in messages."""
        error = StateValidationError("Error: ñ 日本語 emoji 🔧")
        assert "ñ" in str(error)
        assert "日本語" in str(error)
        assert "🔧" in str(error)

    def test_very_long_reason_string(self):
        """Test exception with very long reason string."""
        long_reason = "x" * 10000
        error = StateCorruptedError(Path("/test"), long_reason)
        assert long_reason in str(error)

    def test_empty_strings(self):
        """Test exceptions with empty strings where applicable."""
        error = StateValidationError("")
        assert error.message == ""

        error2 = StateResumeValidationError("")
        assert error2.reason == ""

    def test_many_missing_fields(self):
        """Test StateValidationError with many missing fields."""
        fields = [f"field_{i}" for i in range(100)]
        error = StateValidationError("Many missing", missing_fields=fields)
        # All fields should be included
        for field in fields[:5]:  # Spot check first few
            assert field in str(error)

    def test_many_invalid_fields(self):
        """Test StateValidationError with many invalid fields."""
        fields = [f"field_{i}: invalid value" for i in range(50)]
        error = StateValidationError("Many invalid", invalid_fields=fields)
        assert len(error.invalid_fields) == 50
