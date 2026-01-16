"""Circuit Breaker Pattern for fault tolerance.

Implements the circuit breaker pattern to prevent cascading failures
and allow graceful degradation when services are unhealthy.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeVar

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests flow through
    OPEN = "open"  # Circuit tripped, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    failure_threshold: int = 5  # Failures before opening circuit
    success_threshold: int = 2  # Successes in half-open before closing
    timeout_seconds: float = 60.0  # Time before attempting recovery
    half_open_max_calls: int = 3  # Max concurrent calls in half-open state

    @classmethod
    def default(cls) -> CircuitBreakerConfig:
        """Default configuration for general use."""
        return cls()

    @classmethod
    def aggressive(cls) -> CircuitBreakerConfig:
        """Aggressive configuration - trips faster, recovers slower."""
        return cls(
            failure_threshold=3,
            success_threshold=3,
            timeout_seconds=120.0,
            half_open_max_calls=1,
        )

    @classmethod
    def lenient(cls) -> CircuitBreakerConfig:
        """Lenient configuration - more tolerant of failures."""
        return cls(
            failure_threshold=10,
            success_threshold=1,
            timeout_seconds=30.0,
            half_open_max_calls=5,
        )


class CircuitBreakerError(Exception):
    """Raised when circuit breaker prevents execution."""

    def __init__(self, message: str, state: CircuitState, time_until_retry: float = 0):
        self.message = message
        self.state = state
        self.time_until_retry = time_until_retry
        super().__init__(self.message)


@dataclass
class CircuitBreakerMetrics:
    """Metrics tracked by the circuit breaker."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0  # Calls rejected due to open circuit
    state_transitions: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0

    def record_success(self) -> None:
        """Record a successful call."""
        self.total_calls += 1
        self.successful_calls += 1
        self.last_success_time = time.time()
        self.consecutive_successes += 1
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self.total_calls += 1
        self.failed_calls += 1
        self.last_failure_time = time.time()
        self.consecutive_failures += 1
        self.consecutive_successes = 0

    def record_rejection(self) -> None:
        """Record a rejected call."""
        self.rejected_calls += 1

    def record_state_transition(self) -> None:
        """Record a state transition."""
        self.state_transitions += 1

    @property
    def failure_rate(self) -> float:
        """Calculate failure rate as a percentage."""
        if self.total_calls == 0:
            return 0.0
        return (self.failed_calls / self.total_calls) * 100

    def reset_consecutive_counts(self) -> None:
        """Reset consecutive counts (used on state transitions)."""
        self.consecutive_failures = 0
        self.consecutive_successes = 0


@dataclass
class CircuitBreaker:
    """Circuit breaker implementation for fault tolerance.

    States:
    - CLOSED: Normal operation, all requests pass through
    - OPEN: Circuit tripped, requests fail fast without executing
    - HALF_OPEN: Testing recovery, limited requests allowed through

    Usage:
        breaker = CircuitBreaker(name="api")

        # Option 1: Context manager
        with breaker:
            result = make_api_call()

        # Option 2: Decorator
        @breaker.protect
        def make_api_call():
            ...

        # Option 3: Direct call
        result = breaker.call(make_api_call)
    """

    name: str
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig.default)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _metrics: CircuitBreakerMetrics = field(default_factory=CircuitBreakerMetrics, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _last_state_change: float = field(default_factory=time.time, init=False)
    _half_open_calls: int = field(default=0, init=False)

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            self._check_state_timeout()
            return self._state

    @property
    def metrics(self) -> CircuitBreakerMetrics:
        """Get circuit breaker metrics."""
        return self._metrics

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing fast)."""
        return self.state == CircuitState.OPEN

    @property
    def time_until_retry(self) -> float:
        """Time in seconds until circuit will attempt recovery."""
        if self._state != CircuitState.OPEN:
            return 0.0
        elapsed = time.time() - self._last_state_change
        remaining = self.config.timeout_seconds - elapsed
        return max(0.0, remaining)

    def _check_state_timeout(self) -> None:
        """Check if timeout has elapsed and transition state."""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_state_change
            if elapsed >= self.config.timeout_seconds:
                self._transition_to(CircuitState.HALF_OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        if self._state != new_state:
            self._state = new_state
            self._last_state_change = time.time()
            self._metrics.record_state_transition()
            self._metrics.reset_consecutive_counts()
            if new_state == CircuitState.HALF_OPEN:
                self._half_open_calls = 0

    def _can_execute(self) -> bool:
        """Check if a call can be executed in current state."""
        self._check_state_timeout()

        if self._state == CircuitState.CLOSED:
            return True
        elif self._state == CircuitState.OPEN:
            return False
        else:  # HALF_OPEN
            return self._half_open_calls < self.config.half_open_max_calls

    def _record_success(self) -> None:
        """Record a successful execution."""
        self._metrics.record_success()

        if self._state == CircuitState.HALF_OPEN:
            if self._metrics.consecutive_successes >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)

    def _record_failure(self) -> None:
        """Record a failed execution."""
        self._metrics.record_failure()

        if self._state == CircuitState.CLOSED:
            if self._metrics.consecutive_failures >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.HALF_OPEN:
            # Single failure in half-open triggers immediate open
            self._transition_to(CircuitState.OPEN)

    def call(self, func: Callable[[], T]) -> T:
        """Execute a function through the circuit breaker.

        Args:
            func: The function to execute.

        Returns:
            The function's return value.

        Raises:
            CircuitBreakerError: If circuit is open.
            Exception: Any exception from the function.
        """
        with self._lock:
            if not self._can_execute():
                self._metrics.record_rejection()
                raise CircuitBreakerError(
                    f"Circuit '{self.name}' is {self._state.value}",
                    self._state,
                    self.time_until_retry,
                )

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1

        try:
            result = func()
            with self._lock:
                self._record_success()
            return result
        except Exception:
            with self._lock:
                self._record_failure()
            raise

    def protect(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator to protect a function with this circuit breaker.

        Usage:
            breaker = CircuitBreaker(name="api")

            @breaker.protect
            def make_api_call(url):
                ...
        """

        def wrapper(*args: object, **kwargs: object) -> T:
            return self.call(lambda: func(*args, **kwargs))

        return wrapper

    def __enter__(self) -> CircuitBreaker:
        """Context manager entry - check if call is allowed."""
        with self._lock:
            if not self._can_execute():
                self._metrics.record_rejection()
                raise CircuitBreakerError(
                    f"Circuit '{self.name}' is {self._state.value}",
                    self._state,
                    self.time_until_retry,
                )
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Context manager exit - record success or failure."""
        with self._lock:
            if exc_type is None:
                self._record_success()
            else:
                self._record_failure()

    def reset(self) -> None:
        """Reset the circuit breaker to initial state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._last_state_change = time.time()
            self._half_open_calls = 0
            self._metrics = CircuitBreakerMetrics()

    def force_open(self) -> None:
        """Force the circuit to open state (for testing or manual intervention)."""
        with self._lock:
            self._transition_to(CircuitState.OPEN)

    def force_close(self) -> None:
        """Force the circuit to closed state (for testing or manual intervention)."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    _instance: CircuitBreakerRegistry | None = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize registry (called only once due to singleton)."""
        # Only initialize if not already done
        if not hasattr(self, "_initialized"):
            self._breakers: dict[str, CircuitBreaker] = {}
            self._registry_lock: threading.RLock = threading.RLock()
            self._initialized = True

    def __new__(cls) -> CircuitBreakerRegistry:
        """Singleton pattern for global registry."""
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def get_or_create(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> CircuitBreaker:
        """Get an existing circuit breaker or create a new one.

        Args:
            name: Unique name for the circuit breaker.
            config: Configuration (only used if creating new).

        Returns:
            The circuit breaker instance.
        """
        with self._registry_lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name,
                    config=config or CircuitBreakerConfig.default(),
                )
            return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker | None:
        """Get a circuit breaker by name."""
        with self._registry_lock:
            return self._breakers.get(name)

    def all_metrics(self) -> dict[str, CircuitBreakerMetrics]:
        """Get metrics for all circuit breakers."""
        with self._registry_lock:
            return {name: cb.metrics for name, cb in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        with self._registry_lock:
            for cb in self._breakers.values():
                cb.reset()

    def clear(self) -> None:
        """Clear all circuit breakers from registry."""
        with self._registry_lock:
            self._breakers.clear()


# Convenience function
def get_circuit_breaker(
    name: str,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreaker:
    """Get or create a circuit breaker from the global registry.

    Args:
        name: Unique name for the circuit breaker.
        config: Configuration (only used if creating new).

    Returns:
        The circuit breaker instance.
    """
    return CircuitBreakerRegistry().get_or_create(name, config)
