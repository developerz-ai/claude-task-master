"""Tests for the doctor CLI command."""

from unittest.mock import patch

from claude_task_master.cli import app
from claude_task_master.utils.doctor import SystemDoctor


class TestDoctorCommand:
    """Tests for the doctor command."""

    def test_doctor_returns_success_when_all_pass(self, cli_runner, temp_dir):
        """Test doctor returns success when all checks pass."""
        with patch.object(SystemDoctor, "run_checks", return_value=True):
            result = cli_runner.invoke(app, ["doctor"])

        assert result.exit_code == 0

    def test_doctor_returns_failure_when_checks_fail(self, cli_runner, temp_dir):
        """Test doctor returns failure when checks fail."""
        with patch.object(SystemDoctor, "run_checks", return_value=False):
            result = cli_runner.invoke(app, ["doctor"])

        assert result.exit_code == 1
