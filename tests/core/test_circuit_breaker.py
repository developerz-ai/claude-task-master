"""Tests for circuit breaker pattern."""

import asyncio
import time

import pytest

from claude_task_master.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerMetrics,
    CircuitBreakerRegistry,
    CircuitState,
    get_circuit_breaker,
)


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CircuitBreakerConfig.default()
        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout_seconds == 60.0
        assert config.half_open_max_calls == 3

    def test_aggressive_config(self):
        """Test aggressive configuration."""
        config = CircuitBreakerConfig.aggressive()
        assert config.failure_threshold == 3
        assert config.timeout_seconds == 120.0

    def test_aggressive_config_satisfies_invariant(self):
        """aggressive() must satisfy success_threshold <= half_open_max_calls."""
        config = CircuitBreakerConfig.aggressive()
        assert config.success_threshold <= config.half_open_max_calls

    def test_all_presets_satisfy_invariant(self):
        """Every preset config satisfies the closing invariant."""
        for config in (
            CircuitBreakerConfig.default(),
            CircuitBreakerConfig.aggressive(),
            CircuitBreakerConfig.lenient(),
        ):
            assert config.success_threshold <= config.half_open_max_calls

    def test_lenient_config(self):
        """Test lenient configuration."""
        config = CircuitBreakerConfig.lenient()
        assert config.failure_threshold == 10
        assert config.timeout_seconds == 30.0

    def test_success_threshold_over_half_open_max_calls_rejected(self):
        """A config that could never close is rejected at construction."""
        with pytest.raises(ValueError, match="success_threshold"):
            CircuitBreakerConfig(success_threshold=3, half_open_max_calls=1)

    def test_zero_thresholds_rejected(self):
        """Thresholds below 1 are rejected."""
        with pytest.raises(ValueError, match="failure_threshold"):
            CircuitBreakerConfig(failure_threshold=0)
        with pytest.raises(ValueError, match="success_threshold"):
            CircuitBreakerConfig(success_threshold=0)
        with pytest.raises(ValueError, match="half_open_max_calls"):
            CircuitBreakerConfig(half_open_max_calls=0)


class TestCircuitBreakerMetrics:
    """Tests for CircuitBreakerMetrics."""

    def test_record_success(self):
        """Test recording successful calls."""
        metrics = CircuitBreakerMetrics()
        metrics.record_success()

        assert metrics.total_calls == 1
        assert metrics.successful_calls == 1
        assert metrics.consecutive_successes == 1
        assert metrics.consecutive_failures == 0

    def test_record_failure(self):
        """Test recording failed calls."""
        metrics = CircuitBreakerMetrics()
        metrics.record_failure()

        assert metrics.total_calls == 1
        assert metrics.failed_calls == 1
        assert metrics.consecutive_failures == 1
        assert metrics.consecutive_successes == 0

    def test_failure_rate(self):
        """Test failure rate calculation."""
        metrics = CircuitBreakerMetrics()
        metrics.record_success()
        metrics.record_failure()

        assert metrics.failure_rate == 50.0

    def test_failure_rate_zero_calls(self):
        """Test failure rate with zero calls."""
        metrics = CircuitBreakerMetrics()
        assert metrics.failure_rate == 0.0


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state_is_closed(self):
        """Test that initial state is closed."""
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.is_closed

    def test_successful_call(self):
        """Test successful call through circuit breaker."""
        cb = CircuitBreaker(name="test")

        result = cb.call(lambda: "success")

        assert result == "success"
        assert cb.metrics.successful_calls == 1

    def test_failed_call(self):
        """Test failed call through circuit breaker."""
        cb = CircuitBreaker(name="test")

        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))

    def test_circuit_opens_after_failures(self):
        """Test that circuit opens after threshold failures."""
        config = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker(name="test", config=config)

        # Cause failures
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError()))

        assert cb.state == CircuitState.OPEN

    def test_open_circuit_rejects_calls(self):
        """Test that open circuit rejects calls."""
        config = CircuitBreakerConfig(failure_threshold=1)
        cb = CircuitBreaker(name="test", config=config)

        # Open the circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError()))

        with pytest.raises(CircuitBreakerError):
            cb.call(lambda: "test")

    def test_context_manager_success(self):
        """Test context manager with successful execution."""
        cb = CircuitBreaker(name="test")

        with cb:
            result = "success"

        assert result == "success"
        assert cb.metrics.successful_calls == 1

    def test_context_manager_failure(self):
        """Test context manager with failed execution."""
        cb = CircuitBreaker(name="test")

        # Initial state check
        initial_failed = cb.metrics.failed_calls

        try:
            with cb:
                raise ValueError("test")
        except ValueError:
            pass  # Expected

        # Verify the failure was recorded
        assert cb.metrics.failed_calls == initial_failed + 1

    def test_reset(self):
        """Test resetting circuit breaker."""
        config = CircuitBreakerConfig(failure_threshold=1)
        cb = CircuitBreaker(name="test", config=config)

        # Open the circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError()))

        assert cb.state == CircuitState.OPEN

        cb.reset()

        # After reset, state should be CLOSED (intentional test of reset behavior)
        assert cb.state == CircuitState.CLOSED  # type: ignore[comparison-overlap]
        assert cb.metrics.total_calls == 0

    def test_force_open(self):
        """Test forcing circuit open."""
        cb = CircuitBreaker(name="test")
        cb.force_open()
        assert cb.state == CircuitState.OPEN

    def test_force_close(self):
        """Test forcing circuit closed."""
        cb = CircuitBreaker(name="test")
        cb.force_open()
        cb.force_close()
        assert cb.state == CircuitState.CLOSED

    def test_decorator(self):
        """Test protect decorator."""
        cb = CircuitBreaker(name="test")

        @cb.protect
        def my_func(x):
            return x * 2

        result = my_func(5)
        assert result == 10

    def test_time_until_retry(self):
        """Test time until retry calculation."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout_seconds=60.0)
        cb = CircuitBreaker(name="test", config=config)

        # Open the circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError()))

        # Should have time remaining
        assert cb.time_until_retry > 0
        assert cb.time_until_retry <= 60.0

    def test_half_open_times_out_back_to_open(self):
        """A wedged HALF_OPEN falls back to OPEN after timeout (recovery clock).

        With half_open_max_calls=1 and success_threshold=1, a single probe slot
        gets consumed without a success/failure resolution; without the HALF_OPEN
        timeout the circuit would be stuck failing fast forever.
        """
        config = CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=1,
            half_open_max_calls=1,
            timeout_seconds=0.1,
        )
        cb = CircuitBreaker(name="test", config=config)

        # Trip → OPEN, then wait past timeout → HALF_OPEN.
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError()))
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN  # type: ignore[comparison-overlap]

        # Consume the single probe slot without resolving (enter, no exit record).
        cb._can_execute()
        cb._half_open_calls = config.half_open_max_calls  # slots exhausted

        # After another timeout window, HALF_OPEN must fall back to OPEN.
        time.sleep(0.15)
        assert cb.state == CircuitState.OPEN

    def test_context_manager_ignores_cancelled_error(self):
        """asyncio.CancelledError must NOT be recorded as a breaker failure."""
        cb = CircuitBreaker(name="test")

        with pytest.raises(asyncio.CancelledError):
            with cb:
                raise asyncio.CancelledError()

        assert cb.metrics.failed_calls == 0
        assert cb.metrics.successful_calls == 0
        assert cb.state == CircuitState.CLOSED

    def test_context_manager_ignores_keyboard_interrupt(self):
        """KeyboardInterrupt must NOT be recorded as a breaker failure."""
        cb = CircuitBreaker(name="test")

        with pytest.raises(KeyboardInterrupt):
            with cb:
                raise KeyboardInterrupt()

        assert cb.metrics.failed_calls == 0
        assert cb.state == CircuitState.CLOSED

    def test_user_interrupts_do_not_trip_breaker(self):
        """Repeated interrupts never open the circuit (low failure_threshold)."""
        config = CircuitBreakerConfig(failure_threshold=1)
        cb = CircuitBreaker(name="test", config=config)

        for _ in range(5):
            with pytest.raises(asyncio.CancelledError):
                with cb:
                    raise asyncio.CancelledError()

        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry."""

    def test_singleton(self):
        """Test that registry is a singleton."""
        registry1 = CircuitBreakerRegistry()
        registry2 = CircuitBreakerRegistry()
        assert registry1 is registry2

    def test_get_or_create(self):
        """Test getting or creating circuit breakers."""
        registry = CircuitBreakerRegistry()
        registry.clear()

        cb1 = registry.get_or_create("test")
        cb2 = registry.get_or_create("test")

        assert cb1 is cb2

    def test_get_nonexistent(self):
        """Test getting nonexistent circuit breaker."""
        registry = CircuitBreakerRegistry()
        registry.clear()

        assert registry.get("nonexistent") is None

    def test_all_metrics(self):
        """Test getting all metrics."""
        registry = CircuitBreakerRegistry()
        registry.clear()

        registry.get_or_create("cb1")
        registry.get_or_create("cb2")

        metrics = registry.all_metrics()
        assert "cb1" in metrics
        assert "cb2" in metrics

    def test_reset_all(self):
        """Test resetting all circuit breakers."""
        registry = CircuitBreakerRegistry()
        registry.clear()

        cb = registry.get_or_create("test")
        cb.call(lambda: "success")

        registry.reset_all()

        assert cb.metrics.total_calls == 0


class TestGetCircuitBreaker:
    """Tests for get_circuit_breaker convenience function."""

    def test_get_circuit_breaker(self):
        """Test getting circuit breaker from global registry."""
        CircuitBreakerRegistry().clear()

        cb = get_circuit_breaker("test")
        assert cb.name == "test"
        assert cb.is_closed
