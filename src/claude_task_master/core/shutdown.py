"""Graceful shutdown handling for long-running operations.

This module provides coordinated shutdown handling across the application:
- Signal handlers for SIGTERM, SIGINT, SIGHUP
- Shutdown flag that can be checked by long-running operations
- Interruptible sleep for polling loops
- Integration with key listener for unified cancellation
"""

from __future__ import annotations

import signal
import sys
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import FrameType

# =============================================================================
# Shutdown Manager
# =============================================================================


class ShutdownManager:
    """Coordinates graceful shutdown across all long-running operations.

    This class provides:
    - Signal handling for SIGTERM, SIGINT, SIGHUP
    - A thread-safe shutdown flag
    - Callback registration for cleanup
    - Interruptible sleep for polling loops
    """

    # Signals to handle (platform-dependent)
    HANDLED_SIGNALS = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        HANDLED_SIGNALS.append(signal.SIGHUP)

    # Type alias for signal handlers
    _SignalHandler = Callable[[int, "FrameType | None"], None] | int | None

    def __init__(self) -> None:
        """Initialize shutdown manager."""
        self._shutdown_requested = threading.Event()
        self._original_handlers: dict[signal.Signals, ShutdownManager._SignalHandler] = {}
        self._callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._initialized = False
        self._shutdown_reason: str | None = None

    @property
    def shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested.is_set()

    @property
    def shutdown_reason(self) -> str | None:
        """Get the reason for shutdown (signal name or 'escape')."""
        return self._shutdown_reason

    def register(self) -> None:
        """Register signal handlers.

        This should be called once at application startup, ideally in the
        main thread before starting any long-running operations.

        Thread-safe: Can be called multiple times; subsequent calls are no-ops.
        """
        with self._lock:
            if self._initialized:
                return

            for sig in self.HANDLED_SIGNALS:
                try:
                    original = signal.signal(sig, self._signal_handler)
                    self._original_handlers[sig] = original
                except (ValueError, OSError):
                    # signal.signal() can fail if not called from main thread
                    # or if the signal is not valid on this platform
                    pass

            self._initialized = True

    def unregister(self) -> None:
        """Restore original signal handlers.

        Call this during cleanup to restore the original signal behavior.

        Thread-safe: Can be called multiple times; subsequent calls are no-ops.
        """
        with self._lock:
            if not self._initialized:
                return

            for sig, handler in self._original_handlers.items():
                try:
                    if handler is not None:
                        signal.signal(sig, handler)
                except (ValueError, OSError):
                    pass

            self._original_handlers.clear()
            self._initialized = False

    def request_shutdown(self, reason: str = "manual") -> None:
        """Request a graceful shutdown.

        Args:
            reason: Human-readable reason for shutdown (e.g., 'SIGTERM', 'escape').

        Thread-safe: Can be called from any thread.
        """
        self._shutdown_reason = reason
        self._shutdown_requested.set()

    def reset(self) -> None:
        """Reset the shutdown state.

        This should rarely be needed, but can be useful when reusing the
        manager for multiple sequential operations.

        Thread-safe: Can be called from any thread.
        """
        self._shutdown_requested.clear()
        self._shutdown_reason = None

    def add_callback(self, callback: Callable[[], None]) -> None:
        """Register a cleanup callback to run on shutdown.

        Callbacks are called in LIFO order (last registered = first called).

        Args:
            callback: Function to call during shutdown cleanup.

        Thread-safe: Can be called from any thread.
        """
        with self._lock:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove a previously registered cleanup callback.

        Args:
            callback: The callback function to remove.

        Thread-safe: Can be called from any thread.
        """
        with self._lock:
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass  # Callback not found

    def run_callbacks(self) -> None:
        """Run all registered cleanup callbacks.

        Callbacks are called in LIFO order. Exceptions are caught and
        logged to stderr to ensure all callbacks get a chance to run.

        Thread-safe: Can be called from any thread.
        """
        with self._lock:
            callbacks = list(reversed(self._callbacks))

        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                # Log to stderr to avoid import issues
                print(f"Shutdown callback error: {e}", file=sys.stderr)

    def interruptible_sleep(self, seconds: float, check_interval: float = 0.1) -> bool:
        """Sleep that can be interrupted by shutdown request.

        Args:
            seconds: Total time to sleep in seconds.
            check_interval: How often to check for shutdown (seconds).

        Returns:
            True if sleep completed normally, False if interrupted by shutdown.
        """
        remaining = seconds
        while remaining > 0:
            if self._shutdown_requested.is_set():
                return False
            sleep_time = min(check_interval, remaining)
            time.sleep(sleep_time)
            remaining -= sleep_time
        return True

    def wait_for_shutdown(self, timeout: float | None = None) -> bool:
        """Wait for a shutdown request.

        Args:
            timeout: Maximum time to wait in seconds, or None to wait forever.

        Returns:
            True if shutdown was requested, False if timeout expired.
        """
        return self._shutdown_requested.wait(timeout=timeout)

    def _signal_handler(self, signum: int, frame: FrameType | None) -> None:
        """Handle received signals by requesting shutdown.

        Args:
            signum: The signal number that was received.
            frame: The current stack frame (unused).
        """
        signal_name = signal.Signals(signum).name
        self.request_shutdown(reason=signal_name)

        # Run cleanup callbacks
        self.run_callbacks()


# =============================================================================
# Global Instance
# =============================================================================

# Singleton instance for application-wide shutdown coordination
_manager: ShutdownManager | None = None
_manager_lock = threading.Lock()


def get_shutdown_manager() -> ShutdownManager:
    """Get or create the global shutdown manager.

    Returns:
        The global ShutdownManager instance.

    Thread-safe: Can be called from any thread.
    """
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = ShutdownManager()
        return _manager


# =============================================================================
# Convenience Functions
# =============================================================================


def register_handlers() -> None:
    """Register signal handlers for graceful shutdown.

    Call this once at application startup, ideally in the main thread.
    """
    get_shutdown_manager().register()


def unregister_handlers() -> None:
    """Restore original signal handlers.

    Call this during application cleanup.
    """
    get_shutdown_manager().unregister()


def is_shutdown_requested() -> bool:
    """Check if shutdown has been requested.

    Returns:
        True if shutdown was requested via signal or programmatically.
    """
    return get_shutdown_manager().shutdown_requested


def request_shutdown(reason: str = "manual") -> None:
    """Request a graceful shutdown.

    Args:
        reason: Human-readable reason for shutdown.
    """
    get_shutdown_manager().request_shutdown(reason)


def get_shutdown_reason() -> str | None:
    """Get the reason for shutdown.

    Returns:
        The reason string or None if no shutdown requested.
    """
    return get_shutdown_manager().shutdown_reason


def reset_shutdown() -> None:
    """Reset the shutdown state."""
    get_shutdown_manager().reset()


def add_shutdown_callback(callback: Callable[[], None]) -> None:
    """Register a cleanup callback to run on shutdown.

    Args:
        callback: Function to call during shutdown cleanup.
    """
    get_shutdown_manager().add_callback(callback)


def remove_shutdown_callback(callback: Callable[[], None]) -> None:
    """Remove a previously registered cleanup callback.

    Args:
        callback: The callback function to remove.
    """
    get_shutdown_manager().remove_callback(callback)


def interruptible_sleep(seconds: float, check_interval: float = 0.1) -> bool:
    """Sleep that can be interrupted by shutdown request.

    Args:
        seconds: Total time to sleep in seconds.
        check_interval: How often to check for shutdown (seconds).

    Returns:
        True if sleep completed normally, False if interrupted by shutdown.
    """
    return get_shutdown_manager().interruptible_sleep(seconds, check_interval)
