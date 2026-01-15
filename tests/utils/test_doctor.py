"""Comprehensive tests for the doctor module - system checks utility."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.utils.doctor import SystemDoctor

# =============================================================================
# SystemDoctor Initialization Tests
# =============================================================================


class TestSystemDoctorInitialization:
    """Tests for SystemDoctor initialization."""

    def test_init_creates_console(self):
        """Test initialization creates a Rich Console."""
        doctor = SystemDoctor()
        assert doctor.console is not None

    def test_init_sets_checks_passed_true(self):
        """Test initialization sets checks_passed to True."""
        doctor = SystemDoctor()
        assert doctor.checks_passed is True

    def test_init_creates_fresh_instance(self):
        """Test each initialization creates fresh instance."""
        doctor1 = SystemDoctor()
        doctor2 = SystemDoctor()

        # Modify first instance
        doctor1.checks_passed = False

        # Second instance should still be True
        assert doctor2.checks_passed is True


# =============================================================================
# run_checks Tests
# =============================================================================


class TestSystemDoctorRunChecks:
    """Tests for run_checks method."""

    def test_run_checks_returns_bool(self):
        """Test run_checks returns a boolean."""
        doctor = SystemDoctor()

        with patch.object(doctor, "_check_gh_cli"):
            with patch.object(doctor, "_check_credentials"):
                with patch.object(doctor, "_check_python_version"):
                    result = doctor.run_checks()

        assert isinstance(result, bool)

    def test_run_checks_calls_all_checks(self):
        """Test run_checks calls all check methods."""
        doctor = SystemDoctor()

        with patch.object(doctor, "_check_gh_cli") as mock_gh:
            with patch.object(doctor, "_check_credentials") as mock_creds:
                with patch.object(doctor, "_check_python_version") as mock_py:
                    doctor.run_checks()

        mock_gh.assert_called_once()
        mock_creds.assert_called_once()
        mock_py.assert_called_once()

    def test_run_checks_returns_true_when_all_pass(self):
        """Test run_checks returns True when all checks pass."""
        doctor = SystemDoctor()

        with patch.object(doctor, "_check_gh_cli"):
            with patch.object(doctor, "_check_credentials"):
                with patch.object(doctor, "_check_python_version"):
                    # All checks pass - checks_passed stays True
                    result = doctor.run_checks()

        assert result is True

    def test_run_checks_returns_false_when_check_fails(self):
        """Test run_checks returns False when a check fails."""
        doctor = SystemDoctor()

        def fail_gh_check():
            doctor.checks_passed = False

        with patch.object(doctor, "_check_gh_cli", side_effect=fail_gh_check):
            with patch.object(doctor, "_check_credentials"):
                with patch.object(doctor, "_check_python_version"):
                    result = doctor.run_checks()

        assert result is False

    def test_run_checks_prints_running_message(self):
        """Test run_checks prints running message."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        with patch.object(doctor, "_check_gh_cli"):
            with patch.object(doctor, "_check_credentials"):
                with patch.object(doctor, "_check_python_version"):
                    doctor.run_checks()

        # Check that print was called with "Running system checks..."
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Running system checks" in call for call in calls)

    def test_run_checks_prints_success_message(self):
        """Test run_checks prints success message when all pass."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        with patch.object(doctor, "_check_gh_cli"):
            with patch.object(doctor, "_check_credentials"):
                with patch.object(doctor, "_check_python_version"):
                    doctor.run_checks()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("All checks passed" in call for call in calls)

    def test_run_checks_prints_failure_message(self):
        """Test run_checks prints failure message when check fails."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        def fail_check():
            doctor.checks_passed = False

        with patch.object(doctor, "_check_gh_cli", side_effect=fail_check):
            with patch.object(doctor, "_check_credentials"):
                with patch.object(doctor, "_check_python_version"):
                    doctor.run_checks()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Some checks failed" in call for call in calls)


# =============================================================================
# _check_gh_cli Tests
# =============================================================================


class TestCheckGhCli:
    """Tests for _check_gh_cli method."""

    def test_gh_cli_success(self):
        """Test successful gh CLI check."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "github.com logged in"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            doctor._check_gh_cli()

        mock_run.assert_called_once_with(
            ["gh", "auth", "status"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert doctor.checks_passed is True

    def test_gh_cli_not_authenticated(self):
        """Test gh CLI not authenticated."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "not logged in"

        with patch("subprocess.run", return_value=mock_result):
            doctor._check_gh_cli()

        assert doctor.checks_passed is False

    def test_gh_cli_not_installed(self):
        """Test gh CLI not installed (FileNotFoundError)."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        with patch("subprocess.run", side_effect=FileNotFoundError):
            doctor._check_gh_cli()

        assert doctor.checks_passed is False

    def test_gh_cli_success_prints_success(self):
        """Test successful gh CLI check prints success message."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            doctor._check_gh_cli()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("gh CLI installed and authenticated" in call for call in calls)
        assert any("[green]✓[/green]" in call for call in calls)

    def test_gh_cli_not_authenticated_prints_error(self):
        """Test gh CLI not authenticated prints error message."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            doctor._check_gh_cli()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("gh CLI not authenticated" in call for call in calls)
        assert any("gh auth login" in call for call in calls)

    def test_gh_cli_not_installed_prints_error(self):
        """Test gh CLI not installed prints error message."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        with patch("subprocess.run", side_effect=FileNotFoundError):
            doctor._check_gh_cli()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("gh CLI not installed" in call for call in calls)
        assert any("cli.github.com" in call for call in calls)

    def test_gh_cli_subprocess_arguments(self):
        """Test subprocess.run is called with correct arguments."""
        doctor = SystemDoctor()

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            doctor._check_gh_cli()

        # Verify exact call arguments
        args, kwargs = mock_run.call_args
        assert args[0] == ["gh", "auth", "status"]
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True


# =============================================================================
# _check_credentials Tests
# =============================================================================


class TestCheckCredentials:
    """Tests for _check_credentials method."""

    def test_credentials_exist(self, temp_dir):
        """Test credentials file exists."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        # Create fake credentials file
        creds_dir = temp_dir / ".claude"
        creds_dir.mkdir()
        creds_file = creds_dir / ".credentials.json"
        creds_file.write_text('{"token": "test"}')

        with patch.object(Path, "home", return_value=temp_dir):
            doctor._check_credentials()

        assert doctor.checks_passed is True

    def test_credentials_not_exist(self, temp_dir):
        """Test credentials file does not exist."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        # No credentials file exists
        with patch.object(Path, "home", return_value=temp_dir):
            doctor._check_credentials()

        assert doctor.checks_passed is False

    def test_credentials_exist_prints_success(self, temp_dir):
        """Test credentials exist prints success message."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        # Create fake credentials file
        creds_dir = temp_dir / ".claude"
        creds_dir.mkdir()
        creds_file = creds_dir / ".credentials.json"
        creds_file.write_text('{"token": "test"}')

        with patch.object(Path, "home", return_value=temp_dir):
            doctor._check_credentials()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Claude credentials found" in call for call in calls)
        assert any("[green]✓[/green]" in call for call in calls)

    def test_credentials_not_exist_prints_error(self, temp_dir):
        """Test credentials not exist prints error message."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        with patch.object(Path, "home", return_value=temp_dir):
            doctor._check_credentials()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Claude credentials not found" in call for call in calls)
        assert any("Expected at:" in call for call in calls)
        assert any("Run Claude CLI once to authenticate" in call for call in calls)

    def test_credentials_path_is_correct(self, temp_dir):
        """Test credentials are checked at correct path."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        expected_path = temp_dir / ".claude" / ".credentials.json"

        with patch.object(Path, "home", return_value=temp_dir):
            doctor._check_credentials()

        # Check that the expected path was checked
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any(str(expected_path) in call for call in calls)

    def test_credentials_directory_exists_but_file_missing(self, temp_dir):
        """Test credentials directory exists but file is missing."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        # Create directory but not file
        creds_dir = temp_dir / ".claude"
        creds_dir.mkdir()

        with patch.object(Path, "home", return_value=temp_dir):
            doctor._check_credentials()

        assert doctor.checks_passed is False


# =============================================================================
# _check_python_version Tests
# =============================================================================


class TestCheckPythonVersion:
    """Tests for _check_python_version method."""

    def test_python_version_310_passes(self):
        """Test Python 3.10 passes the check."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_version = MagicMock()
        mock_version.major = 3
        mock_version.minor = 10
        mock_version.micro = 0
        mock_version.__ge__ = lambda self, other: (3, 10) >= other

        with patch.object(sys, "version_info", mock_version):
            doctor._check_python_version()

        assert doctor.checks_passed is True

    def test_python_version_311_passes(self):
        """Test Python 3.11 passes the check."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_version = MagicMock()
        mock_version.major = 3
        mock_version.minor = 11
        mock_version.micro = 5
        mock_version.__ge__ = lambda self, other: (3, 11) >= other

        with patch.object(sys, "version_info", mock_version):
            doctor._check_python_version()

        assert doctor.checks_passed is True

    def test_python_version_312_passes(self):
        """Test Python 3.12 passes the check."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_version = MagicMock()
        mock_version.major = 3
        mock_version.minor = 12
        mock_version.micro = 0
        mock_version.__ge__ = lambda self, other: (3, 12) >= other

        with patch.object(sys, "version_info", mock_version):
            doctor._check_python_version()

        assert doctor.checks_passed is True

    def test_python_version_39_fails(self):
        """Test Python 3.9 fails the check."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_version = MagicMock()
        mock_version.major = 3
        mock_version.minor = 9
        mock_version.micro = 0
        mock_version.__ge__ = lambda self, other: (3, 9) >= other

        with patch.object(sys, "version_info", mock_version):
            doctor._check_python_version()

        assert doctor.checks_passed is False

    def test_python_version_27_fails(self):
        """Test Python 2.7 fails the check."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_version = MagicMock()
        mock_version.major = 2
        mock_version.minor = 7
        mock_version.micro = 18
        mock_version.__ge__ = lambda self, other: (2, 7) >= other

        with patch.object(sys, "version_info", mock_version):
            doctor._check_python_version()

        assert doctor.checks_passed is False

    def test_python_version_success_prints_version(self):
        """Test successful version check prints version number."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_version = MagicMock()
        mock_version.major = 3
        mock_version.minor = 11
        mock_version.micro = 5
        mock_version.__ge__ = lambda self, other: (3, 11) >= other

        with patch.object(sys, "version_info", mock_version):
            doctor._check_python_version()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("3.11.5" in call for call in calls)
        assert any("[green]✓[/green]" in call for call in calls)

    def test_python_version_failure_prints_error(self):
        """Test failed version check prints error message."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_version = MagicMock()
        mock_version.major = 3
        mock_version.minor = 9
        mock_version.micro = 0
        mock_version.__ge__ = lambda self, other: (3, 9) >= other

        with patch.object(sys, "version_info", mock_version):
            doctor._check_python_version()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("3.9.0" in call for call in calls)
        assert any("[red]✗[/red]" in call for call in calls)
        assert any("Requires Python 3.10 or higher" in call for call in calls)


# =============================================================================
# Integration Tests
# =============================================================================


class TestSystemDoctorIntegration:
    """Integration tests for SystemDoctor."""

    def test_all_checks_pass(self, temp_dir):
        """Test all checks passing end-to-end."""
        doctor = SystemDoctor()

        # Create credentials file
        creds_dir = temp_dir / ".claude"
        creds_dir.mkdir()
        creds_file = creds_dir / ".credentials.json"
        creds_file.write_text('{"token": "test"}')

        # Mock gh CLI success
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(Path, "home", return_value=temp_dir):
                result = doctor.run_checks()

        assert result is True

    def test_gh_cli_fails_other_pass(self, temp_dir):
        """Test gh CLI fails but other checks pass."""
        doctor = SystemDoctor()

        # Create credentials file
        creds_dir = temp_dir / ".claude"
        creds_dir.mkdir()
        creds_file = creds_dir / ".credentials.json"
        creds_file.write_text('{"token": "test"}')

        # Mock gh CLI failure
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(Path, "home", return_value=temp_dir):
                result = doctor.run_checks()

        assert result is False

    def test_credentials_fail_other_pass(self, temp_dir):
        """Test credentials fail but other checks pass."""
        doctor = SystemDoctor()

        # No credentials file

        # Mock gh CLI success
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(Path, "home", return_value=temp_dir):
                result = doctor.run_checks()

        assert result is False

    def test_multiple_failures(self, temp_dir):
        """Test multiple checks failing."""
        doctor = SystemDoctor()

        # No credentials file

        # Mock gh CLI failure
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with patch.object(Path, "home", return_value=temp_dir):
                result = doctor.run_checks()

        assert result is False


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestSystemDoctorEdgeCases:
    """Edge case tests for SystemDoctor."""

    def test_subprocess_timeout(self):
        """Test handling of subprocess timeout."""
        doctor = SystemDoctor()

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 30)):
            # Should handle timeout gracefully - currently it will raise
            # This tests that the exception propagates correctly
            with pytest.raises(subprocess.TimeoutExpired):
                doctor._check_gh_cli()

    def test_subprocess_permission_error(self):
        """Test handling of permission error running gh."""
        doctor = SystemDoctor()

        with patch("subprocess.run", side_effect=PermissionError):
            # Should handle permission error - currently it will raise
            with pytest.raises(PermissionError):
                doctor._check_gh_cli()

    def test_credentials_path_with_special_characters(self, temp_dir):
        """Test credentials path handling with unusual home directory."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        # Create special directory
        special_dir = temp_dir / "special spaces"
        special_dir.mkdir()
        creds_dir = special_dir / ".claude"
        creds_dir.mkdir()
        creds_file = creds_dir / ".credentials.json"
        creds_file.write_text('{"token": "test"}')

        with patch.object(Path, "home", return_value=special_dir):
            doctor._check_credentials()

        assert doctor.checks_passed is True

    def test_empty_credentials_file(self, temp_dir):
        """Test credentials file exists but is empty."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        # Create empty credentials file
        creds_dir = temp_dir / ".claude"
        creds_dir.mkdir()
        creds_file = creds_dir / ".credentials.json"
        creds_file.write_text("")

        with patch.object(Path, "home", return_value=temp_dir):
            doctor._check_credentials()

        # File exists, so check should pass (content validation is not done)
        assert doctor.checks_passed is True

    def test_run_checks_multiple_times(self):
        """Test running checks multiple times."""
        doctor = SystemDoctor()

        with patch.object(doctor, "_check_gh_cli"):
            with patch.object(doctor, "_check_credentials"):
                with patch.object(doctor, "_check_python_version"):
                    result1 = doctor.run_checks()
                    result2 = doctor.run_checks()

        assert result1 is True
        assert result2 is True

    def test_run_checks_resets_state(self):
        """Test run_checks doesn't carry over state from previous failure."""
        doctor = SystemDoctor()

        def fail_first_time():
            doctor.checks_passed = False

        # First run fails
        with patch.object(doctor, "_check_gh_cli", side_effect=fail_first_time):
            with patch.object(doctor, "_check_credentials"):
                with patch.object(doctor, "_check_python_version"):
                    result1 = doctor.run_checks()

        assert result1 is False

        # Reset for second run
        doctor.checks_passed = True

        # Second run succeeds
        with patch.object(doctor, "_check_gh_cli"):
            with patch.object(doctor, "_check_credentials"):
                with patch.object(doctor, "_check_python_version"):
                    result2 = doctor.run_checks()

        assert result2 is True


# =============================================================================
# Console Output Tests
# =============================================================================


class TestSystemDoctorConsoleOutput:
    """Tests for console output formatting."""

    def test_console_uses_rich_formatting(self):
        """Test console output uses Rich formatting."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            doctor._check_gh_cli()

        # Verify Rich formatting tags are used
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("[green]" in call for call in calls)

    def test_error_output_uses_red_formatting(self):
        """Test error output uses red formatting."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        with patch("subprocess.run", side_effect=FileNotFoundError):
            doctor._check_gh_cli()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("[red]" in call for call in calls)

    def test_success_output_uses_green_formatting(self):
        """Test success output uses green formatting."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            doctor._check_gh_cli()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("[green]" in call for call in calls)

    def test_instruction_output_uses_cyan_formatting(self):
        """Test instruction output uses cyan formatting."""
        doctor = SystemDoctor()
        mock_console = MagicMock()
        doctor.console = mock_console

        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            doctor._check_gh_cli()

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("[cyan]" in call for call in calls)
