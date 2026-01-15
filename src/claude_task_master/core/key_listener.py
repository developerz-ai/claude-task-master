"""Key listener for detecting pause requests during execution."""

import sys
import threading
from typing import Callable


class KeyListener:
    """Non-blocking key listener for detecting Escape key presses."""

    ESCAPE_KEY = "\x1b"  # Escape character

    def __init__(self, on_escape: Callable[[], None] | None = None):
        """Initialize key listener.

        Args:
            on_escape: Optional callback when Escape is pressed.
        """
        self._escape_pressed = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._on_escape = on_escape
        self._original_settings = None

    @property
    def escape_pressed(self) -> bool:
        """Check if Escape was pressed."""
        return self._escape_pressed

    def reset(self) -> None:
        """Reset the escape flag."""
        self._escape_pressed = False

    def start(self) -> None:
        """Start listening for key presses in background thread."""
        if self._running:
            return

        self._running = True
        self._escape_pressed = False
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop listening for key presses."""
        self._running = False
        self._restore_terminal()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.1)
        self._thread = None

    def _listen(self) -> None:
        """Listen for key presses (runs in background thread)."""
        try:
            self._setup_terminal()
            while self._running:
                if self._check_key():
                    break
        except Exception:
            # Silently handle any terminal errors
            pass
        finally:
            self._restore_terminal()

    def _setup_terminal(self) -> None:
        """Set up terminal for non-blocking input."""
        try:
            import termios
            import tty

            if sys.stdin.isatty():
                self._original_settings = termios.tcgetattr(sys.stdin)
                tty.setcbreak(sys.stdin.fileno())
        except (ImportError, termios.error):
            # Not a TTY or not on Unix
            pass

    def _restore_terminal(self) -> None:
        """Restore terminal to original settings."""
        try:
            import termios

            if self._original_settings and sys.stdin.isatty():
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._original_settings)
                self._original_settings = None
        except (ImportError, termios.error):
            pass

    def _check_key(self) -> bool:
        """Check for key press without blocking.

        Returns:
            True if Escape was pressed and we should stop listening.
        """
        try:
            import select

            # Check if input is available (timeout 0.1 seconds)
            if select.select([sys.stdin], [], [], 0.1)[0]:
                char = sys.stdin.read(1)
                if char == self.ESCAPE_KEY:
                    self._escape_pressed = True
                    if self._on_escape:
                        self._on_escape()
                    return True
        except Exception:
            pass
        return False


# Global instance for easy access
_listener: KeyListener | None = None


def get_listener() -> KeyListener:
    """Get or create the global key listener instance."""
    global _listener
    if _listener is None:
        _listener = KeyListener()
    return _listener


def start_listening() -> None:
    """Start the global key listener."""
    get_listener().start()


def stop_listening() -> None:
    """Stop the global key listener."""
    if _listener:
        _listener.stop()


def check_escape() -> bool:
    """Check if Escape was pressed.

    Returns:
        True if Escape was pressed since last reset.
    """
    if _listener:
        return _listener.escape_pressed
    return False


def reset_escape() -> None:
    """Reset the Escape pressed flag."""
    if _listener:
        _listener.reset()
