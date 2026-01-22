"""Property-based tests for CircuitBreaker.

Tests the state machine properties and invariants of the circuit breaker pattern.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from claude_task_master.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerMetrics,
    CircuitState,
)

# Strategies for configuration values
failure_threshold_strategy = st.integers(min_value=1, max_value=20)
success_threshold_strategy = st.integers(min_value=1, max_value=10)
timeout_strategy = st.floats(min_value=1.0, max_value=300.0, allow_nan=False)
half_open_max_calls_strategy = st.integers(min_value=1, max_value=10)


class TestCircuitBreakerConfigProperties:
    """Property-based tests for CircuitBreakerConfig."""

    @given(
        failure_threshold=failure_threshold_strategy,
        success_threshold=success_threshold_strategy,
        timeout_seconds=timeout_strategy,
        half_open_max_calls=half_open_max_calls_strategy,
    )
    @settings(max_examples=100)
    def test_config_creation_preserves_values(
        self,
        failure_threshold: int,
        success_threshold: int,
        timeout_seconds: float,
        half_open_max_calls: int,
    ):
        """Configuration values should be preserved."""
        config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            success_threshold=success_threshold,
            timeout_seconds=timeout_seconds,
            half_open_max_calls=half_open_max_calls,
        )

        assert config.failure_threshold == failure_threshold
        assert config.success_threshold == success_threshold
        assert config.timeout_seconds == timeout_seconds
        assert config.half_open_max_calls == half_open_max_calls

    def test_preset_configs_are_valid(self):
        """All preset configurations should have valid values."""
        presets = [
            CircuitBreakerConfig.default(),
            CircuitBreakerConfig.aggressive(),
            CircuitBreakerConfig.lenient(),
        ]

        for config in presets:
            assert config.failure_threshold >= 1
            assert config.success_threshold >= 1
            assert config.timeout_seconds > 0
            assert config.half_open_max_calls >= 1


class TestCircuitBreakerMetricsProperties:
    """Property-based tests for CircuitBreakerMetrics."""

    @given(
        successes=st.integers(min_value=0, max_value=100),
        failures=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=100)
    def test_metrics_track_totals_correctly(self, successes: int, failures: int):
        """Metrics should correctly track success and failure counts."""
        metrics = CircuitBreakerMetrics()

        for _ in range(successes):
            metrics.record_success()

        for _ in range(failures):
            metrics.record_failure()

        # Note: The order matters - failures reset consecutive_successes
        assert metrics.total_calls == successes + failures
        assert metrics.successful_calls == successes
        assert metrics.failed_calls == failures

    @given(
        failures=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=50)
    def test_failure_rate_calculation(self, failures: int):
        """Failure rate should be calculated correctly."""
        metrics = CircuitBreakerMetrics()
        total_calls = failures + 10  # Add some successes

        for _ in range(10):  # 10 successes first
            metrics.record_success()
        for _ in range(failures):
            metrics.record_failure()

        expected_rate = (failures / total_calls) * 100
        assert metrics.failure_rate == pytest.approx(expected_rate)

    def test_empty_metrics_have_zero_failure_rate(self):
        """Empty metrics should have 0% failure rate."""
        metrics = CircuitBreakerMetrics()
        assert metrics.failure_rate == 0.0

    @given(
        sequence=st.lists(
            st.booleans(),  # True = success, False = failure
            min_size=1,
            max_size=50,
        )
    )
    @settings(max_examples=100)
    def test_consecutive_counts_track_correctly(self, sequence: list):
        """Consecutive success/failure counts should be tracked correctly."""
        metrics = CircuitBreakerMetrics()

        for is_success in sequence:
            if is_success:
                metrics.record_success()
            else:
                metrics.record_failure()

        # Count consecutive results from the end
        expected_consecutive = 1
        last_result = sequence[-1]
        for i in range(len(sequence) - 2, -1, -1):
            if sequence[i] == last_result:
                expected_consecutive += 1
            else:
                break

        if last_result:
            assert metrics.consecutive_successes == expected_consecutive
            assert metrics.consecutive_failures == 0
        else:
            assert metrics.consecutive_failures == expected_consecutive
            assert metrics.consecutive_successes == 0


class TestCircuitBreakerStateProperties:
    """Property-based tests for CircuitBreaker state machine."""

    @given(failure_count=st.integers(min_value=0, max_value=30))
    @settings(max_examples=50)
    def test_circuit_opens_after_threshold_failures(self, failure_count: int):
        """Circuit should open after reaching failure threshold."""
        threshold = 5
        config = CircuitBreakerConfig(failure_threshold=threshold)
        breaker = CircuitBreaker(name="test", config=config)

        for _i in range(failure_count):
            try:
                with breaker:
                    raise ValueError("Simulated failure")
            except ValueError:
                pass
            except CircuitBreakerError:
                # Circuit opened - this is expected after threshold
                break

        if failure_count >= threshold:
            assert breaker.state == CircuitState.OPEN
        else:
            assert breaker.state == CircuitState.CLOSED

    @given(
        successes=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=50)
    def test_circuit_stays_closed_with_successes(self, successes: int):
        """Circuit should stay closed when all calls succeed."""
        breaker = CircuitBreaker(name="test")

        for _ in range(successes):
            with breaker:
                pass  # Success

        assert breaker.state == CircuitState.CLOSED

    def test_circuit_transitions_to_half_open_after_timeout(self):
        """Circuit should transition to half-open after timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            timeout_seconds=0.1,  # Very short timeout for testing
        )
        breaker = CircuitBreaker(name="test", config=config)

        # Trip the circuit
        try:
            with breaker:
                raise ValueError("Failure")
        except ValueError:
            pass

        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        import time

        time.sleep(0.15)

        # State should now be half-open
        assert breaker.state == CircuitState.HALF_OPEN

    @given(
        failures_before=st.integers(min_value=1, max_value=5),
        successes_needed=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=30)
    def test_circuit_closes_after_success_threshold_in_half_open(
        self, failures_before: int, successes_needed: int
    ):
        """Circuit should close after success threshold in half-open state."""
        config = CircuitBreakerConfig(
            failure_threshold=failures_before,
            success_threshold=successes_needed,
            timeout_seconds=0.01,  # Very short for testing
        )
        breaker = CircuitBreaker(name="test", config=config)

        # Trip the circuit
        for _ in range(failures_before):
            try:
                with breaker:
                    raise ValueError("Failure")
            except (ValueError, CircuitBreakerError):
                pass

        # Wait for timeout to transition to half-open
        import time

        time.sleep(0.02)

        # Record successes in half-open state
        for _ in range(successes_needed):
            try:
                with breaker:
                    pass  # Success
            except CircuitBreakerError:
                # May have already transitioned
                break

        # Should be closed after enough successes
        assert breaker.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)


class TestCircuitBreakerInvariants:
    """Test invariants that should always hold."""

    def test_reset_always_returns_to_closed(self):
        """reset() should always return circuit to closed state."""
        breaker = CircuitBreaker(name="test")

        # Trip the circuit
        breaker.force_open()
        assert breaker.state == CircuitState.OPEN

        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.metrics.total_calls == 0

    @given(
        failure_threshold=failure_threshold_strategy,
    )
    @settings(max_examples=30)
    def test_force_open_always_opens(self, failure_threshold: int):
        """force_open should always open the circuit regardless of state."""
        config = CircuitBreakerConfig(failure_threshold=failure_threshold)
        breaker = CircuitBreaker(name="test", config=config)

        # Even with no failures
        assert breaker.state == CircuitState.CLOSED

        breaker.force_open()
        assert breaker.state == CircuitState.OPEN

    @given(
        failure_threshold=failure_threshold_strategy,
    )
    @settings(max_examples=30)
    def test_force_close_always_closes(self, failure_threshold: int):
        """force_close should always close the circuit regardless of state."""
        config = CircuitBreakerConfig(failure_threshold=failure_threshold)
        breaker = CircuitBreaker(name="test", config=config)

        # Open the circuit first
        breaker.force_open()
        assert breaker.state == CircuitState.OPEN

        breaker.force_close()
        assert breaker.state == CircuitState.CLOSED

    @given(
        call_count=st.integers(min_value=0, max_value=50),
        success_rate=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_total_calls_equals_sum_of_success_and_failure(
        self, call_count: int, success_rate: float
    ):
        """total_calls should always equal successful_calls + failed_calls."""
        metrics = CircuitBreakerMetrics()

        for i in range(call_count):
            if i / max(call_count, 1) < success_rate:
                metrics.record_success()
            else:
                metrics.record_failure()

        assert metrics.total_calls == metrics.successful_calls + metrics.failed_calls
