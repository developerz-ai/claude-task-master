"""Tests for the debug-md CLI command."""

from unittest.mock import AsyncMock, patch

import pytest

from claude_task_master.cli import app


class TestDebugCommand:
    """Tests for the debug-md command."""

    def test_debug_md_keyboard_interrupt(self, cli_runner, temp_dir):
        """Test debug-md handles keyboard interrupt gracefully."""
        with patch(
            "claude_task_master.cli.debug_claude_md_detection",
            new_callable=AsyncMock,
            side_effect=KeyboardInterrupt(),
        ):
            result = cli_runner.invoke(app, ["debug-md"])

        assert result.exit_code == 2
        assert "Interrupted" in result.stdout

    def test_debug_md_exception_handling(self, cli_runner, temp_dir):
        """Test debug-md handles exceptions gracefully."""
        with patch(
            "claude_task_master.cli.debug_claude_md_detection",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Test error"),
        ):
            result = cli_runner.invoke(app, ["debug-md"])

        assert result.exit_code == 1
        assert "Error running debug" in result.stdout
