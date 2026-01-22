"""Property-based tests for state transitions.

Tests the state machine properties of TaskState status transitions.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from claude_task_master.core.state_exceptions import (
    RESUMABLE_STATUSES,
    TERMINAL_STATUSES,
    VALID_STATUSES,
    VALID_TRANSITIONS,
    InvalidStateTransitionError,
)

# Define status strategy
status_strategy = st.sampled_from(list(VALID_STATUSES))


class TestStateTransitionProperties:
    """Property-based tests for state transitions."""

    @given(status=status_strategy)
    @settings(max_examples=50)
    def test_terminal_states_have_no_transitions(self, status: str):
        """Terminal states should have no valid transitions."""
        if status in TERMINAL_STATUSES:
            assert VALID_TRANSITIONS[status] == frozenset()

    @given(status=status_strategy)
    @settings(max_examples=50)
    def test_non_terminal_states_have_transitions(self, status: str):
        """Non-terminal states should have at least one valid transition."""
        if status not in TERMINAL_STATUSES:
            assert len(VALID_TRANSITIONS[status]) > 0

    @given(current=status_strategy, target=status_strategy)
    @settings(max_examples=200)
    def test_transition_consistency(self, current: str, target: str):
        """If a transition is valid, it should be in the transitions dict."""
        if target in VALID_TRANSITIONS.get(current, frozenset()):
            # Valid transition - no exception
            pass
        else:
            # Same status is always allowed (no actual transition)
            if current != target:
                # Different status not in valid transitions - should fail
                with pytest.raises(InvalidStateTransitionError):
                    _validate_transition(current, target)

    @given(status=status_strategy)
    @settings(max_examples=50)
    def test_all_states_can_transition_to_failed(self, status: str):
        """All non-terminal states should be able to transition to failed."""
        if status not in TERMINAL_STATUSES:
            assert "failed" in VALID_TRANSITIONS[status]

    @given(status=status_strategy)
    @settings(max_examples=50)
    def test_resumable_states_can_go_to_working(self, status: str):
        """All resumable states should be able to transition to working."""
        if status in RESUMABLE_STATUSES:
            assert "working" in VALID_TRANSITIONS[status]

    @given(
        path=st.lists(status_strategy, min_size=2, max_size=10),
    )
    @settings(max_examples=200)
    def test_random_state_paths(self, path: list):
        """Test random state transition paths for consistency."""
        for i in range(len(path) - 1):
            current = path[i]
            next_state = path[i + 1]

            # Check if transition is valid
            valid_next = VALID_TRANSITIONS.get(current, frozenset())
            is_valid = next_state in valid_next or current == next_state

            if current in TERMINAL_STATUSES:
                # Can't transition from terminal states
                assert not is_valid or current == next_state

    def test_planning_must_go_to_working_before_success(self):
        """Planning cannot directly go to success."""
        assert "success" not in VALID_TRANSITIONS["planning"]
        assert "working" in VALID_TRANSITIONS["planning"]

    def test_working_can_go_to_success(self):
        """Working can transition to success."""
        assert "success" in VALID_TRANSITIONS["working"]

    @given(status=status_strategy)
    @settings(max_examples=50)
    def test_valid_transitions_only_contain_valid_statuses(self, status: str):
        """All statuses in valid transitions should be valid statuses."""
        next_states = VALID_TRANSITIONS.get(status, frozenset())
        for next_state in next_states:
            assert next_state in VALID_STATUSES

    def test_all_statuses_have_transition_entry(self):
        """All valid statuses should have an entry in VALID_TRANSITIONS."""
        for status in VALID_STATUSES:
            assert status in VALID_TRANSITIONS


def _validate_transition(current_status: str, new_status: str) -> None:
    """Helper to validate state transitions (mirrors StateManager logic)."""
    if current_status == new_status:
        return

    valid_next_states = VALID_TRANSITIONS.get(current_status, frozenset())
    if new_status not in valid_next_states:
        raise InvalidStateTransitionError(current_status, new_status)
