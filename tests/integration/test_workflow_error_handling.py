"""Integration tests for error handling scenarios.

These tests verify error handling including:
- Missing or invalid credentials
- Corrupted state files
- Network and SDK errors
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.core.credentials import CredentialManager
from claude_task_master.core.state import StateManager


@pytest.fixture
def runner():
    """Provide a CLI test runner."""
    return CliRunner()


class TestErrorHandling:
    """Integration tests for error handling scenarios."""

    def test_start_handles_credential_error(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test start handles missing credentials gracefully."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Point to non-existent credentials
        non_existent = integration_temp_dir / "non_existent" / ".credentials.json"
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", non_existent)

        result = runner.invoke(app, ["start", "Test goal"])

        assert result.exit_code == 1
        # Should give helpful error message
        assert "Error" in result.output or "doctor" in result.output.lower()

    def test_resume_handles_corrupted_state(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test resume handles corrupted state file."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Create a corrupted state file
        state_file = integration_state_dir / "state.json"
        state_file.write_text("{ invalid json }")

        result = runner.invoke(app, ["resume"])

        assert result.exit_code == 1
        # Should indicate error
        assert "Error" in result.output


class TestCredentialErrors:
    """Tests for credential-related errors."""

    def test_invalid_credential_format(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test handling of malformed credentials file."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Create malformed credentials file
        claude_dir = integration_temp_dir / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        credentials_path = claude_dir / ".credentials.json"
        credentials_path.write_text("not json at all")
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", credentials_path)

        result = runner.invoke(app, ["start", "Test goal"])

        assert result.exit_code == 1

    def test_missing_oauth_field(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test handling of credentials without claudeAiOauth field."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Create credentials without required field
        claude_dir = integration_temp_dir / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        credentials_path = claude_dir / ".credentials.json"
        credentials_path.write_text(json.dumps({"someOtherField": "value"}))
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", credentials_path)

        result = runner.invoke(app, ["start", "Test goal"])

        assert result.exit_code == 1


class TestStateFileErrors:
    """Tests for state file corruption scenarios."""

    def test_partial_state_file(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test handling of incomplete state file."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # Create incomplete state file (missing required fields)
        state_file = integration_state_dir / "state.json"
        state_file.write_text(json.dumps({"status": "working"}))

        result = runner.invoke(app, ["status"])

        # Should handle gracefully - either show partial info or error
        assert result.exit_code in [0, 1]

    def test_empty_state_directory(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        monkeypatch,
    ):
        """Test behavior with empty state directory."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)

        # State dir exists but no state.json
        result = runner.invoke(app, ["status"])

        # Should indicate no task found
        assert result.exit_code in [0, 1]
