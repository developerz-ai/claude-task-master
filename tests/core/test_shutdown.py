"""Tests for the shutdown module."""

import signal
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.core.shutdown import (
    ShutdownManager,
    add_shutdown_callback,
    get_shutdown_manager,
    get_shutdown_reason,
    interruptible_sleep,
    is_shutdown_requested,
    register_handlers,
    remove_shutdown_callback,
    request_shutdown,
    reset_shutdown,
    unregister_handlers,
)


class TestShutdownManager:
    """Tests for ShutdownManager class."""

    def test_init_default_state(self):
        """Test that ShutdownManager initializes with correct defaults."""
        manager = ShutdownManager()
        assert not manager.shutdown_requested
        assert manager.shutdown_reason is None

    def test_request_shutdown_sets_flag(self):
        """Test that request_shutdown sets the shutdown flag."""
        manager = ShutdownManager()
        manager.request_shutdown("test")
        assert manager.shutdown_requested
        assert manager.shutdown_reason == "test"

    def test_reset_clears_shutdown_state(self):
        """Test that reset clears shutdown state."""
        manager = ShutdownManager()
        manager.request_shutdown("test")
        manager.reset()
        assert not manager.shutdown_requested
        assert manager.shutdown_reason is None


class TestShutdownManagerSignalHandlers:
    """Tests for signal handler registration."""

    def test_register_handlers(self):
        """Test that signal handlers are registered."""
        manager = ShutdownManager()
        with patch("signal.signal") as mock_signal:
            mock_signal.return_value = signal.SIG_DFL
            manager.register()
            assert mock_signal.called
            manager.unregister()

    def test_register_idempotent(self):
        """Test that register is idempotent."""
        manager = ShutdownManager()
        with patch("signal.signal") as mock_signal:
            mock_signal.return_value = signal.SIG_DFL
            manager.register()
            call_count_1 = mock_signal.call_count
            manager.register()  # Second call should be no-op
            assert mock_signal.call_count == call_count_1
            manager.unregister()

    def test_unregister_restores_handlers(self):
        """Test that unregister restores original handlers."""
        manager = ShutdownManager()
        original_handler = MagicMock()
        with patch("signal.signal") as mock_signal:
            mock_signal.return_value = original_handler
            manager.register()
            manager.unregister()
            # Should have called signal.signal again with original handler
            assert mock_signal.call_count >= 2


class TestShutdownManagerCallbacks:
    """Tests for callback registration and execution."""

    def test_add_callback(self):
        """Test adding a callback."""
        manager = ShutdownManager()
        callback = MagicMock()
        manager.add_callback(callback)
        manager.run_callbacks()
        callback.assert_called_once()

    def test_remove_callback(self):
        """Test removing a callback."""
        manager = ShutdownManager()
        callback = MagicMock()
        manager.add_callback(callback)
        manager.remove_callback(callback)
        manager.run_callbacks()
        callback.assert_not_called()

    def test_callbacks_run_in_lifo_order(self):
        """Test that callbacks run in LIFO order."""
        manager = ShutdownManager()
        call_order = []
        manager.add_callback(lambda: call_order.append(1))
        manager.add_callback(lambda: call_order.append(2))
        manager.add_callback(lambda: call_order.append(3))
        manager.run_callbacks()
        assert call_order == [3, 2, 1]

    def test_callback_exception_does_not_stop_others(self):
        """Test that callback exceptions don't prevent other callbacks."""
        manager = ShutdownManager()
        callback1 = MagicMock()
        callback2 = MagicMock(side_effect=Exception("test"))
        callback3 = MagicMock()
        manager.add_callback(callback1)
        manager.add_callback(callback2)
        manager.add_callback(callback3)
        manager.run_callbacks()
        callback1.assert_called_once()
        callback3.assert_called_once()


class TestShutdownManagerInterruptibleSleep:
    """Tests for interruptible sleep."""

    def test_interruptible_sleep_completes_normally(self):
        """Test that interruptible_sleep completes when not interrupted."""
        manager = ShutdownManager()
        start = time.time()
        result = manager.interruptible_sleep(0.2, check_interval=0.05)
        elapsed = time.time() - start
        assert result is True
        assert elapsed >= 0.2

    def test_interruptible_sleep_interrupted(self):
        """Test that interruptible_sleep can be interrupted."""
        manager = ShutdownManager()

        def interrupt_after_delay():
            time.sleep(0.1)
            manager.request_shutdown("test")

        thread = threading.Thread(target=interrupt_after_delay)
        thread.start()

        start = time.time()
        result = manager.interruptible_sleep(1.0, check_interval=0.05)
        elapsed = time.time() - start

        thread.join()
        assert result is False
        assert elapsed < 0.5  # Should have stopped well before 1 second


class TestShutdownManagerWaitForShutdown:
    """Tests for wait_for_shutdown."""

    def test_wait_for_shutdown_with_timeout(self):
        """Test wait_for_shutdown with timeout."""
        manager = ShutdownManager()
        result = manager.wait_for_shutdown(timeout=0.1)
        assert result is False

    def test_wait_for_shutdown_when_signaled(self):
        """Test wait_for_shutdown when shutdown is requested."""
        manager = ShutdownManager()

        def signal_shutdown():
            time.sleep(0.05)
            manager.request_shutdown("test")

        thread = threading.Thread(target=signal_shutdown)
        thread.start()
        result = manager.wait_for_shutdown(timeout=1.0)
        thread.join()
        assert result is True


class TestGlobalFunctions:
    """Tests for module-level convenience functions."""

    def test_get_shutdown_manager_returns_singleton(self):
        """Test that get_shutdown_manager returns singleton."""
        manager1 = get_shutdown_manager()
        manager2 = get_shutdown_manager()
        assert manager1 is manager2

    def test_register_handlers_global(self):
        """Test global register_handlers function."""
        with patch.object(get_shutdown_manager(), "register") as mock_register:
            register_handlers()
            mock_register.assert_called_once()

    def test_unregister_handlers_global(self):
        """Test global unregister_handlers function."""
        with patch.object(get_shutdown_manager(), "unregister") as mock_unregister:
            unregister_handlers()
            mock_unregister.assert_called_once()

    def test_is_shutdown_requested_global(self):
        """Test global is_shutdown_requested function."""
        manager = get_shutdown_manager()
        manager.reset()
        assert not is_shutdown_requested()
        manager.request_shutdown("test")
        assert is_shutdown_requested()
        manager.reset()

    def test_request_shutdown_global(self):
        """Test global request_shutdown function."""
        manager = get_shutdown_manager()
        manager.reset()
        request_shutdown("test_reason")
        assert manager.shutdown_requested
        assert manager.shutdown_reason == "test_reason"
        manager.reset()

    def test_get_shutdown_reason_global(self):
        """Test global get_shutdown_reason function."""
        manager = get_shutdown_manager()
        manager.reset()
        assert get_shutdown_reason() is None
        request_shutdown("my_reason")
        assert get_shutdown_reason() == "my_reason"
        manager.reset()

    def test_reset_shutdown_global(self):
        """Test global reset_shutdown function."""
        manager = get_shutdown_manager()
        request_shutdown("test")
        reset_shutdown()
        assert not manager.shutdown_requested
        assert manager.shutdown_reason is None

    def test_add_shutdown_callback_global(self):
        """Test global add_shutdown_callback function."""
        callback = MagicMock()
        add_shutdown_callback(callback)
        get_shutdown_manager().run_callbacks()
        callback.assert_called_once()
        remove_shutdown_callback(callback)

    def test_remove_shutdown_callback_global(self):
        """Test global remove_shutdown_callback function."""
        callback = MagicMock()
        add_shutdown_callback(callback)
        remove_shutdown_callback(callback)
        get_shutdown_manager().run_callbacks()
        callback.assert_not_called()

    def test_interruptible_sleep_global(self):
        """Test global interruptible_sleep function."""
        manager = get_shutdown_manager()
        manager.reset()
        start = time.time()
        result = interruptible_sleep(0.1, check_interval=0.02)
        elapsed = time.time() - start
        assert result is True
        assert elapsed >= 0.1


class TestShutdownManagerThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_request_shutdown(self):
        """Test that concurrent request_shutdown calls are safe."""
        manager = ShutdownManager()
        threads = []

        def request_from_thread(reason):
            manager.request_shutdown(reason)

        for i in range(10):
            t = threading.Thread(target=request_from_thread, args=(f"reason_{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert manager.shutdown_requested

    def test_concurrent_callbacks(self):
        """Test that concurrent callback operations are safe."""
        manager = ShutdownManager()
        call_count = 0
        lock = threading.Lock()

        def callback():
            nonlocal call_count
            with lock:
                call_count += 1

        threads = []
        for _ in range(10):
            t = threading.Thread(target=lambda: manager.add_callback(callback))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        manager.run_callbacks()
        assert call_count == 10


class TestSignalHandlerBehavior:
    """Tests for signal handler behavior."""

    def test_signal_handler_requests_shutdown(self):
        """Test that signal handler sets shutdown flag."""
        manager = ShutdownManager()
        # Manually call the signal handler
        manager._signal_handler(signal.SIGINT, None)
        assert manager.shutdown_requested
        assert manager.shutdown_reason == "SIGINT"

    def test_signal_handler_runs_callbacks(self):
        """Test that signal handler runs callbacks."""
        manager = ShutdownManager()
        callback = MagicMock()
        manager.add_callback(callback)
        manager._signal_handler(signal.SIGTERM, None)
        callback.assert_called_once()
