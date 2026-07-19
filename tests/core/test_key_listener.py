"""Comprehensive tests for the key_listener module."""

import sys
import threading
from unittest.mock import MagicMock, patch

from claude_task_master.core.key_listener import (
    KeyListener,
    check_escape,
    get_listener,
    reset_escape,
    start_listening,
    stop_listening,
)

# =============================================================================
# KeyListener Class Tests
# =============================================================================


class TestKeyListenerInitialization:
    """Tests for KeyListener initialization."""

    def test_init_without_callback(self):
        """Test initialization without an on_escape callback."""
        listener = KeyListener()

        assert listener._escape_pressed is False
        assert listener._running is False
        assert listener._thread is None
        assert listener._on_escape is None
        assert listener._original_settings is None

    def test_init_with_callback(self):
        """Test initialization with an on_escape callback."""
        callback = MagicMock()
        listener = KeyListener(on_escape=callback)

        assert listener._on_escape is callback
        assert listener._escape_pressed is False
        assert listener._running is False

    def test_escape_key_constant(self):
        """Test ESCAPE_KEY constant is correct."""
        assert KeyListener.ESCAPE_KEY == "\x1b"


class TestKeyListenerProperties:
    """Tests for KeyListener properties."""

    def test_escape_pressed_property_false(self):
        """Test escape_pressed property when not pressed."""
        listener = KeyListener()

        assert listener.escape_pressed is False

    def test_escape_pressed_property_true(self):
        """Test escape_pressed property when pressed."""
        listener = KeyListener()
        listener._escape_pressed = True

        assert listener.escape_pressed is True


class TestKeyListenerReset:
    """Tests for KeyListener reset method."""

    def test_reset_clears_escape_flag(self):
        """Test reset clears the escape flag."""
        listener = KeyListener()
        listener._escape_pressed = True

        listener.reset()

        assert listener._escape_pressed is False

    def test_reset_when_already_false(self):
        """Test reset when flag is already false."""
        listener = KeyListener()

        listener.reset()

        assert listener._escape_pressed is False


class TestKeyListenerStart:
    """Tests for KeyListener start method."""

    def test_start_sets_running_flag(self):
        """Test start sets the running flag."""
        listener = KeyListener()

        with patch.object(listener, "_listen"):
            listener.start()

            assert listener._running is True
            listener.stop()

    def test_start_resets_escape_flag(self):
        """Test start resets the escape flag."""
        listener = KeyListener()
        listener._escape_pressed = True

        with patch.object(listener, "_listen"):
            listener.start()

            assert listener._escape_pressed is False
            listener.stop()

    def test_start_creates_thread(self):
        """Test start creates a background thread."""
        listener = KeyListener()

        with patch.object(listener, "_listen"):
            listener.start()

            assert listener._thread is not None
            assert isinstance(listener._thread, threading.Thread)
            assert listener._thread.daemon is True
            listener.stop()

    def test_start_does_nothing_if_already_running(self):
        """Test start does nothing if already running."""
        listener = KeyListener()
        listener._running = True
        original_thread = listener._thread

        listener.start()

        # Should not create a new thread
        assert listener._thread is original_thread


class TestKeyListenerStop:
    """Tests for KeyListener stop method."""

    def test_stop_clears_running_flag(self):
        """Test stop clears the running flag."""
        listener = KeyListener()
        listener._running = True

        with patch.object(listener, "_restore_terminal"):
            listener.stop()

        assert listener._running is False

    def test_stop_calls_restore_terminal(self):
        """Test stop calls _restore_terminal."""
        listener = KeyListener()
        listener._running = True

        with patch.object(listener, "_restore_terminal") as mock_restore:
            listener.stop()

        mock_restore.assert_called_once()

    def test_stop_joins_thread_if_alive(self):
        """Test stop joins thread if it's alive."""
        listener = KeyListener()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        listener._thread = mock_thread
        listener._running = True

        with patch.object(listener, "_restore_terminal"):
            listener.stop()

        mock_thread.join.assert_called_once_with(timeout=1.0)

    def test_stop_clears_thread_reference(self):
        """Test stop clears the thread reference."""
        listener = KeyListener()
        listener._thread = MagicMock()
        listener._running = True

        with patch.object(listener, "_restore_terminal"):
            listener.stop()

        assert listener._thread is None


class TestKeyListenerListen:
    """Tests for KeyListener _listen method."""

    def test_listen_calls_setup_terminal(self):
        """Test _listen calls _setup_terminal."""
        listener = KeyListener()
        listener._running = False  # Will exit immediately

        with patch.object(listener, "_setup_terminal") as mock_setup:
            with patch.object(listener, "_check_key", return_value=False):
                with patch.object(listener, "_restore_terminal"):
                    listener._listen()

        mock_setup.assert_called_once()

    def test_listen_calls_restore_terminal_on_exit(self):
        """Test _listen calls _restore_terminal when exiting."""
        listener = KeyListener()
        listener._running = False

        with patch.object(listener, "_setup_terminal"):
            with patch.object(listener, "_check_key", return_value=False):
                with patch.object(listener, "_restore_terminal") as mock_restore:
                    listener._listen()

        mock_restore.assert_called_once()

    def test_listen_exits_when_check_key_returns_true(self):
        """Test _listen exits when _check_key returns True."""
        listener = KeyListener()
        listener._running = True
        check_count = 0

        def mock_check_key():
            nonlocal check_count
            check_count += 1
            if check_count >= 2:
                return True
            return False

        with patch.object(listener, "_setup_terminal"):
            with patch.object(listener, "_check_key", side_effect=mock_check_key):
                with patch.object(listener, "_restore_terminal"):
                    listener._listen()

        assert check_count == 2

    def test_listen_handles_exception_silently(self):
        """Test _listen handles exceptions silently."""
        listener = KeyListener()
        listener._running = True

        with patch.object(listener, "_setup_terminal", side_effect=Exception("Test error")):
            with patch.object(listener, "_restore_terminal") as mock_restore:
                # Should not raise
                listener._listen()

        # restore_terminal should still be called in finally
        mock_restore.assert_called_once()


class TestKeyListenerSetupTerminal:
    """Tests for KeyListener _setup_terminal method."""

    def test_setup_terminal_with_tty(self):
        """Test _setup_terminal with a TTY."""
        listener = KeyListener()

        mock_termios = MagicMock()
        mock_termios.tcgetattr.return_value = ["original", "settings"]
        mock_tty = MagicMock()

        with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}):
            with patch.object(sys.stdin, "isatty", return_value=True):
                with patch.object(sys.stdin, "fileno", return_value=0):
                    listener._setup_terminal()

        assert listener._original_settings == ["original", "settings"]
        mock_tty.setcbreak.assert_called_once_with(0)

    def test_setup_terminal_without_tty(self):
        """Test _setup_terminal without a TTY."""
        listener = KeyListener()

        mock_termios = MagicMock()
        mock_tty = MagicMock()

        with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}):
            with patch.object(sys.stdin, "isatty", return_value=False):
                listener._setup_terminal()

        # Should not call termios functions
        mock_termios.tcgetattr.assert_not_called()
        mock_tty.setcbreak.assert_not_called()
        assert listener._original_settings is None

    def test_setup_terminal_handles_exception(self):
        """Test _setup_terminal handles exceptions gracefully."""
        listener = KeyListener()

        # Test that the method handles exceptions from termios operations
        mock_termios = MagicMock()
        mock_termios.tcgetattr.side_effect = Exception("Terminal error")

        with patch.dict("sys.modules", {"termios": mock_termios, "tty": MagicMock()}):
            with patch.object(sys.stdin, "isatty", return_value=True):
                # Should not raise
                listener._setup_terminal()

        # Main assertion: method should not raise and settings should be None
        assert listener._original_settings is None

    def test_setup_terminal_handles_termios_error(self):
        """Test _setup_terminal handles termios.error gracefully."""
        listener = KeyListener()

        mock_termios = MagicMock()
        mock_termios.tcgetattr.side_effect = Exception("Terminal error")

        with patch.dict("sys.modules", {"termios": mock_termios}):
            with patch.object(sys.stdin, "isatty", return_value=True):
                # Should not raise
                listener._setup_terminal()


class TestKeyListenerRestoreTerminal:
    """Tests for KeyListener _restore_terminal method."""

    def test_restore_terminal_with_original_settings(self):
        """Test _restore_terminal restores settings when available."""
        listener = KeyListener()
        listener._original_settings = ["original", "settings"]

        mock_termios = MagicMock()

        with patch.dict("sys.modules", {"termios": mock_termios}):
            with patch.object(sys.stdin, "isatty", return_value=True):
                listener._restore_terminal()

        mock_termios.tcsetattr.assert_called_once()
        assert listener._original_settings is None

    def test_restore_terminal_without_original_settings(self):
        """Test _restore_terminal does nothing without settings."""
        listener = KeyListener()
        listener._original_settings = None

        mock_termios = MagicMock()

        with patch.dict("sys.modules", {"termios": mock_termios}):
            listener._restore_terminal()

        mock_termios.tcsetattr.assert_not_called()

    def test_restore_terminal_handles_import_error(self):
        """Test _restore_terminal handles ImportError gracefully."""
        listener = KeyListener()
        listener._original_settings = ["settings"]

        # Test by making the termios module operations fail
        # The method catches ImportError and Exception separately now
        try:
            import termios  # noqa: F401

            # termios available, test with exception case
            mock_termios = MagicMock()
            mock_termios.tcsetattr.side_effect = Exception("Terminal error")

            with patch.dict("sys.modules", {"termios": mock_termios}):
                with patch.object(sys.stdin, "isatty", return_value=True):
                    # Should not raise
                    listener._restore_terminal()
        except ImportError:
            # termios not available, which is fine
            listener._restore_terminal()  # Should not raise

    def test_restore_terminal_handles_termios_error(self):
        """Test _restore_terminal handles termios.error gracefully."""
        listener = KeyListener()
        listener._original_settings = ["settings"]

        mock_termios = MagicMock()
        mock_termios.tcsetattr.side_effect = Exception("Terminal error")

        with patch.dict("sys.modules", {"termios": mock_termios}):
            with patch.object(sys.stdin, "isatty", return_value=True):
                # Should not raise
                listener._restore_terminal()


class TestKeyListenerCheckKey:
    """Tests for KeyListener _check_key method."""

    def test_check_key_returns_true_on_escape(self):
        """Test _check_key returns True when Escape is pressed."""
        listener = KeyListener()

        mock_select = MagicMock()
        mock_select.select.return_value = ([sys.stdin], [], [])

        with patch.dict("sys.modules", {"select": mock_select}):
            with patch.object(sys.stdin, "read", return_value="\x1b"):
                result = listener._check_key()

        assert result is True
        assert listener._escape_pressed is True

    def test_check_key_returns_false_on_other_key(self):
        """Test _check_key returns False for non-Escape keys."""
        listener = KeyListener()

        mock_select = MagicMock()
        mock_select.select.return_value = ([sys.stdin], [], [])

        with patch.dict("sys.modules", {"select": mock_select}):
            with patch.object(sys.stdin, "read", return_value="a"):
                result = listener._check_key()

        assert result is False
        assert listener._escape_pressed is False

    def test_check_key_returns_false_when_no_input(self):
        """Test _check_key returns False when no input available."""
        listener = KeyListener()

        mock_select = MagicMock()
        mock_select.select.return_value = ([], [], [])

        with patch.dict("sys.modules", {"select": mock_select}):
            result = listener._check_key()

        assert result is False
        assert listener._escape_pressed is False

    def test_check_key_calls_callback_on_escape(self):
        """Test _check_key calls the on_escape callback."""
        callback = MagicMock()
        listener = KeyListener(on_escape=callback)

        mock_select = MagicMock()
        mock_select.select.return_value = ([sys.stdin], [], [])

        with patch.dict("sys.modules", {"select": mock_select}):
            with patch.object(sys.stdin, "read", return_value="\x1b"):
                listener._check_key()

        callback.assert_called_once()

    def test_check_key_handles_exception(self):
        """Test _check_key handles exceptions gracefully."""
        listener = KeyListener()

        mock_select = MagicMock()
        mock_select.select.side_effect = Exception("Select error")

        with patch.dict("sys.modules", {"select": mock_select}):
            # Should not raise
            result = listener._check_key()

        assert result is False


# =============================================================================
# Module-Level Function Tests
# =============================================================================


class TestGetListener:
    """Tests for get_listener function."""

    def test_get_listener_creates_instance(self):
        """Test get_listener creates a new instance if none exists."""
        import claude_task_master.core.key_listener as module

        # Reset the global listener
        module._listener = None

        listener = get_listener()

        assert listener is not None
        assert isinstance(listener, KeyListener)

    def test_get_listener_returns_same_instance(self):
        """Test get_listener returns the same instance on subsequent calls."""
        import claude_task_master.core.key_listener as module

        # Reset the global listener
        module._listener = None

        listener1 = get_listener()
        listener2 = get_listener()

        assert listener1 is listener2


class TestStartListening:
    """Tests for start_listening function."""

    def test_start_listening_starts_global_listener(self):
        """Test start_listening starts the global listener."""
        import claude_task_master.core.key_listener as module

        # Reset the global listener
        module._listener = None

        with patch.object(KeyListener, "start"):
            # Get the listener first to ensure it exists
            listener = get_listener()
            # Now patch its start method
            with patch.object(listener, "start") as mock_listener_start:
                start_listening()
                mock_listener_start.assert_called_once()


class TestStopListening:
    """Tests for stop_listening function."""

    def test_stop_listening_stops_global_listener(self):
        """Test stop_listening stops the global listener."""
        import claude_task_master.core.key_listener as module

        mock_listener = MagicMock()
        module._listener = mock_listener

        stop_listening()

        mock_listener.stop.assert_called_once()

    def test_stop_listening_does_nothing_if_no_listener(self):
        """Test stop_listening does nothing if no listener exists."""
        import claude_task_master.core.key_listener as module

        module._listener = None

        # Should not raise
        stop_listening()


class TestCheckEscape:
    """Tests for check_escape function."""

    def test_check_escape_returns_true_when_pressed(self):
        """Test check_escape returns True when escape is pressed."""
        import claude_task_master.core.key_listener as module

        mock_listener = MagicMock()
        mock_listener.escape_pressed = True
        module._listener = mock_listener

        assert check_escape() is True

    def test_check_escape_returns_false_when_not_pressed(self):
        """Test check_escape returns False when escape is not pressed."""
        import claude_task_master.core.key_listener as module

        mock_listener = MagicMock()
        mock_listener.escape_pressed = False
        module._listener = mock_listener

        assert check_escape() is False

    def test_check_escape_returns_false_when_no_listener(self):
        """Test check_escape returns False when no listener exists."""
        import claude_task_master.core.key_listener as module

        module._listener = None

        assert check_escape() is False


class TestResetEscape:
    """Tests for reset_escape function."""

    def test_reset_escape_resets_global_listener(self):
        """Test reset_escape resets the global listener."""
        import claude_task_master.core.key_listener as module

        mock_listener = MagicMock()
        module._listener = mock_listener

        reset_escape()

        mock_listener.reset.assert_called_once()

    def test_reset_escape_does_nothing_if_no_listener(self):
        """Test reset_escape does nothing if no listener exists."""
        import claude_task_master.core.key_listener as module

        module._listener = None

        # Should not raise
        reset_escape()


# =============================================================================
# Integration Tests
# =============================================================================


class TestKeyListenerIntegration:
    """Integration tests for KeyListener."""

    def test_full_lifecycle(self):
        """Test full lifecycle: create, start, stop."""
        listener = KeyListener()

        with patch.object(listener, "_listen"):
            listener.start()
            assert listener._running is True
            assert listener._thread is not None

            listener.stop()
            assert listener._running is False
            assert listener._thread is None

    def test_escape_detection_flow(self):
        """Test the escape detection flow."""
        callback_called = False

        def on_escape():
            nonlocal callback_called
            callback_called = True

        listener = KeyListener(on_escape=on_escape)

        mock_select = MagicMock()
        mock_select.select.return_value = ([sys.stdin], [], [])

        with patch.dict("sys.modules", {"select": mock_select}):
            with patch.object(sys.stdin, "read", return_value="\x1b"):
                result = listener._check_key()

        assert result is True
        assert listener.escape_pressed is True
        assert callback_called is True

        # Reset should clear the flag
        listener.reset()
        assert listener.escape_pressed is False

    def test_multiple_start_stop_cycles(self):
        """Test multiple start/stop cycles."""
        listener = KeyListener()

        for _ in range(3):
            with patch.object(listener, "_listen"):
                listener.start()
                assert listener._running is True

                listener.stop()
                assert listener._running is False


class TestKeyListenerEdgeCases:
    """Edge case tests for KeyListener."""

    def test_stop_without_start(self):
        """Test stopping without starting first."""
        listener = KeyListener()

        # Should not raise
        with patch.object(listener, "_restore_terminal"):
            listener.stop()

        assert listener._running is False

    def test_double_start(self):
        """Test starting twice."""
        listener = KeyListener()

        with patch.object(listener, "_listen"):
            listener.start()
            first_thread = listener._thread

            listener.start()
            # Thread should be the same (not restarted)
            assert listener._thread is first_thread

            listener.stop()

    def test_reset_during_running(self):
        """Test resetting while listener is running."""
        listener = KeyListener()
        listener._running = True
        listener._escape_pressed = True

        listener.reset()

        assert listener._escape_pressed is False
        assert listener._running is True  # Still running

    def test_callback_none_escape_pressed(self):
        """Test callback is not called when None."""
        listener = KeyListener(on_escape=None)

        mock_select = MagicMock()
        mock_select.select.return_value = ([sys.stdin], [], [])

        with patch.dict("sys.modules", {"select": mock_select}):
            with patch.object(sys.stdin, "read", return_value="\x1b"):
                # Should not raise even with no callback
                result = listener._check_key()

        assert result is True
        assert listener._escape_pressed is True
