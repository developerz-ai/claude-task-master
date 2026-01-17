"""Tests for circuit breaker pattern."""

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

    def test_lenient_config(self):
        """Test lenient configuration."""
        config = CircuitBreakerConfig.lenient()
        assert config.failure_threshold == 10
        assert config.timeout_seconds == 30.0


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
