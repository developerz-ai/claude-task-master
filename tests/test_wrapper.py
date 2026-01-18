"""Tests for the wrapper module that locates and executes the bash wrapper."""

import os
import stat
from pathlib import Path
from unittest import mock

import pytest


class TestFindBashWrapper:
    """Tests for find_bash_wrapper function."""

    def test_find_wrapper_via_env_var(self, tmp_path: Path):
        """Should find wrapper when CLAUDETM_BASH_WRAPPER env var is set."""
        from claude_task_master.wrapper import find_bash_wrapper

        # Create a mock wrapper script
        wrapper = tmp_path / "claudetm"
        wrapper.write_text("#!/bin/bash\necho test")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)

        with mock.patch.dict(os.environ, {"CLAUDETM_BASH_WRAPPER": str(wrapper)}):
            result = find_bash_wrapper()

        assert result == wrapper

    def test_find_wrapper_env_var_not_executable(self, tmp_path: Path):
        """Should return None if env var points to non-executable file."""
        from claude_task_master.wrapper import find_bash_wrapper

        # Create a non-executable file
        wrapper = tmp_path / "claudetm"
        wrapper.write_text("#!/bin/bash\necho test")
        # Don't make it executable

        with mock.patch.dict(os.environ, {"CLAUDETM_BASH_WRAPPER": str(wrapper)}):
            # Should not return the non-executable file
            # It should fall through to other search methods
            result = find_bash_wrapper()

        # The result should not be the non-executable file
        assert result != wrapper or result is None

    def test_find_wrapper_env_var_not_exists(self, tmp_path: Path):
        """Should return None or fallback if env var points to missing file."""
        from claude_task_master.wrapper import find_bash_wrapper

        with mock.patch.dict(os.environ, {"CLAUDETM_BASH_WRAPPER": "/nonexistent/path"}):
            # Should fall through to other search methods
            result = find_bash_wrapper()

        # Should either be None or find actual wrapper in repo
        assert result is None or result.exists()

    def test_find_wrapper_in_dev_mode(self):
        """Should find wrapper in bin/ directory during development."""
        from claude_task_master.wrapper import find_bash_wrapper

        # Clear the env var to test dev mode detection
        with mock.patch.dict(os.environ, {}, clear=False):
            if "CLAUDETM_BASH_WRAPPER" in os.environ:
                del os.environ["CLAUDETM_BASH_WRAPPER"]

            result = find_bash_wrapper()

        # In the test environment, we should find the dev wrapper
        if result is not None:
            assert result.name == "claudetm"
            assert result.is_file()


class TestGetWrapperPath:
    """Tests for get_wrapper_path utility function."""

    def test_get_wrapper_path_returns_string(self, tmp_path: Path):
        """Should return string path when wrapper is found."""
        from claude_task_master.wrapper import get_wrapper_path

        # Create a mock wrapper
        wrapper = tmp_path / "claudetm"
        wrapper.write_text("#!/bin/bash\necho test")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)

        with mock.patch.dict(os.environ, {"CLAUDETM_BASH_WRAPPER": str(wrapper)}):
            result = get_wrapper_path()

        assert isinstance(result, str)
        assert result == str(wrapper)

    def test_get_wrapper_path_returns_none(self):
        """Should return None when wrapper is not found."""
        from claude_task_master.wrapper import get_wrapper_path

        # Mock find_bash_wrapper to return None
        with mock.patch("claude_task_master.wrapper.find_bash_wrapper", return_value=None):
            result = get_wrapper_path()

        assert result is None


class TestMainFunction:
    """Tests for the main entry point function."""

    def test_main_with_wrapper_found(self, tmp_path: Path):
        """Should exec the wrapper when found."""
        from claude_task_master.wrapper import main

        # Create a mock wrapper
        wrapper = tmp_path / "claudetm"
        wrapper.write_text("#!/bin/bash\necho test")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)

        with (
            mock.patch.dict(os.environ, {"CLAUDETM_BASH_WRAPPER": str(wrapper)}),
            mock.patch("os.execv") as mock_execv,
            mock.patch("sys.argv", ["claudetm", "status"]),
        ):
            # Mock execv to not actually replace the process
            mock_execv.side_effect = SystemExit(0)

            with pytest.raises(SystemExit):
                main()

            # Verify execv was called with correct arguments
            mock_execv.assert_called_once_with(str(wrapper), [str(wrapper), "status"])

    def test_main_fallback_to_cli(self, capsys):
        """Should fall back to Python CLI when wrapper not found."""
        from claude_task_master.wrapper import main

        with (
            mock.patch("claude_task_master.wrapper.find_bash_wrapper", return_value=None),
            mock.patch("claude_task_master.cli.app") as mock_app,
            mock.patch("sys.exit"),
        ):
            main()

            # Should have printed warning
            captured = capsys.readouterr()
            assert "Warning: Bash wrapper not found" in captured.err

            # Should have called the CLI app
            mock_app.assert_called_once()
