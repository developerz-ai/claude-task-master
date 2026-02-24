"""Integration tests for webhook CLI arguments and environment variables.

These tests verify that:
- --webhook-url and --webhook-secret CLI arguments work
- CLAUDETM_WEBHOOK_URL and CLAUDETM_WEBHOOK_SECRET environment variables are respected
- CLI arguments take precedence over environment variables
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from claude_task_master.cli import app
from claude_task_master.core.credentials import CredentialManager
from claude_task_master.core.state import StateManager


@pytest.fixture
def runner():
    """Provide a CLI test runner."""
    return CliRunner()


@pytest.fixture(autouse=True)
def mock_cleanup_on_success():
    """Prevent state cleanup so we can verify state was written.

    The orchestrator calls cleanup_on_success() after a successful run,
    which removes state files. We mock it to preserve state for assertion.
    """
    with patch("claude_task_master.core.state_backup.BackupRecoveryMixin.cleanup_on_success"):
        yield


@pytest.fixture(autouse=True)
def mock_webhook_http():
    """Prevent webhook client from making real HTTP calls."""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = "OK"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("claude_task_master.webhooks.client.httpx.AsyncClient", return_value=mock_client):
        yield


@pytest.mark.timeout(10)
class TestWebhookEnvironmentVariables:
    """Integration tests for webhook environment variable support."""

    def test_webhook_url_from_cli_argument(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that --webhook-url CLI argument is captured."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Configure mock SDK for simple planning response
        patched_sdk.set_planning_response("""## Task List

- [ ] Task 1: Test

## Success Criteria

1. Task completed
""")
        patched_sdk.set_work_response("Task completed successfully.")
        patched_sdk.set_verify_response("All success criteria met!")

        result = runner.invoke(
            app,
            [
                "start",
                "Test webhook",
                "--webhook-url",
                "https://example.com/webhooks",
            ],
        )

        # Check that the command ran
        assert result.exit_code in (0, 1)  # Success or paused due to task completion
        assert "Starting new task" in result.output
        assert "Webhook:" in result.output

        # Verify the state file contains the webhook URL
        state_file = integration_state_dir / "state.json"
        assert state_file.exists(), "State file should be written after start command"
        import json

        with open(state_file) as f:
            state_data = json.load(f)
            assert state_data["options"]["webhook_url"] == "https://example.com/webhooks"

    def test_webhook_url_from_environment_variable(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that CLAUDETM_WEBHOOK_URL environment variable is used."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)
        monkeypatch.setenv("CLAUDETM_WEBHOOK_URL", "https://example.com/webhooks-env")

        # Configure mock SDK for simple planning response
        patched_sdk.set_planning_response("""## Task List

- [ ] Task 1: Test

## Success Criteria

1. Task completed
""")
        patched_sdk.set_work_response("Task completed successfully.")
        patched_sdk.set_verify_response("All success criteria met!")

        result = runner.invoke(
            app,
            ["start", "Test webhook from env"],
        )

        # Check that the command ran
        assert result.exit_code in (0, 1)  # Success or paused
        assert "Starting new task" in result.output
        assert "Webhook:" in result.output

        # Verify the state file contains the webhook URL from environment variable
        state_file = integration_state_dir / "state.json"
        assert state_file.exists(), "State file should be written after start command"
        import json

        with open(state_file) as f:
            state_data = json.load(f)
            assert state_data["options"]["webhook_url"] == "https://example.com/webhooks-env"

    def test_webhook_url_cli_takes_precedence_over_env(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that CLI argument takes precedence over environment variable."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)
        monkeypatch.setenv("CLAUDETM_WEBHOOK_URL", "https://example.com/webhooks-env")

        # Configure mock SDK for simple planning response
        patched_sdk.set_planning_response("""## Task List

- [ ] Task 1: Test

## Success Criteria

1. Task completed
""")
        patched_sdk.set_work_response("Task completed successfully.")
        patched_sdk.set_verify_response("All success criteria met!")

        result = runner.invoke(
            app,
            [
                "start",
                "Test webhook precedence",
                "--webhook-url",
                "https://example.com/webhooks-cli",
            ],
        )

        # Check that the command ran
        assert result.exit_code in (0, 1)  # Success or paused
        assert "Starting new task" in result.output

        # Verify the state file contains the CLI argument, not the env variable
        state_file = integration_state_dir / "state.json"
        assert state_file.exists(), "State file should be written after start command"
        import json

        with open(state_file) as f:
            state_data = json.load(f)
            assert state_data["options"]["webhook_url"] == "https://example.com/webhooks-cli"

    def test_webhook_secret_from_cli_argument(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that --webhook-secret CLI argument is captured."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)

        # Configure mock SDK for simple planning response
        patched_sdk.set_planning_response("""## Task List

- [ ] Task 1: Test

## Success Criteria

1. Task completed
""")
        patched_sdk.set_work_response("Task completed successfully.")
        patched_sdk.set_verify_response("All success criteria met!")

        result = runner.invoke(
            app,
            [
                "start",
                "Test webhook secret",
                "--webhook-url",
                "https://example.com/webhooks",
                "--webhook-secret",
                "my-secret-key",
            ],
        )

        # Check that the command ran
        assert result.exit_code in (0, 1)  # Success or paused
        assert "Starting new task" in result.output
        assert "secret: configured" in result.output

        # Verify the state file contains the webhook secret
        state_file = integration_state_dir / "state.json"
        assert state_file.exists(), "State file should be written after start command"
        import json

        with open(state_file) as f:
            state_data = json.load(f)
            assert state_data["options"]["webhook_secret"] == "my-secret-key"

    def test_webhook_secret_from_environment_variable(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that CLAUDETM_WEBHOOK_SECRET environment variable is used."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)
        monkeypatch.setenv("CLAUDETM_WEBHOOK_URL", "https://example.com/webhooks")
        monkeypatch.setenv("CLAUDETM_WEBHOOK_SECRET", "env-secret-key")

        # Configure mock SDK for simple planning response
        patched_sdk.set_planning_response("""## Task List

- [ ] Task 1: Test

## Success Criteria

1. Task completed
""")
        patched_sdk.set_work_response("Task completed successfully.")
        patched_sdk.set_verify_response("All success criteria met!")

        result = runner.invoke(
            app,
            ["start", "Test webhook secret from env"],
        )

        # Check that the command ran
        assert result.exit_code in (0, 1)  # Success or paused
        assert "Starting new task" in result.output
        assert "secret: configured" in result.output

        # Verify the state file contains the webhook secret from environment variable
        state_file = integration_state_dir / "state.json"
        assert state_file.exists(), "State file should be written after start command"
        import json

        with open(state_file) as f:
            state_data = json.load(f)
            assert state_data["options"]["webhook_secret"] == "env-secret-key"

    def test_webhook_secret_cli_takes_precedence_over_env(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that CLI argument takes precedence over environment variable for secret."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)
        monkeypatch.setenv("CLAUDETM_WEBHOOK_URL", "https://example.com/webhooks")
        monkeypatch.setenv("CLAUDETM_WEBHOOK_SECRET", "env-secret")

        # Configure mock SDK for simple planning response
        patched_sdk.set_planning_response("""## Task List

- [ ] Task 1: Test

## Success Criteria

1. Task completed
""")
        patched_sdk.set_work_response("Task completed successfully.")
        patched_sdk.set_verify_response("All success criteria met!")

        result = runner.invoke(
            app,
            [
                "start",
                "Test webhook secret precedence",
                "--webhook-secret",
                "cli-secret",
            ],
        )

        # Check that the command ran
        assert result.exit_code in (0, 1)  # Success or paused
        assert "Starting new task" in result.output

        # Verify the state file contains the CLI argument, not the env variable
        state_file = integration_state_dir / "state.json"
        assert state_file.exists(), "State file should be written after start command"
        import json

        with open(state_file) as f:
            state_data = json.load(f)
            assert state_data["options"]["webhook_secret"] == "cli-secret"

    def test_no_webhook_when_neither_cli_nor_env_set(
        self,
        runner,
        integration_temp_dir: Path,
        integration_state_dir: Path,
        mock_credentials_file: Path,
        patched_sdk,
        monkeypatch,
    ):
        """Test that no webhook is configured when neither CLI nor env variables are set."""
        monkeypatch.chdir(integration_temp_dir)
        monkeypatch.setattr(StateManager, "STATE_DIR", integration_state_dir)
        monkeypatch.setattr(CredentialManager, "CREDENTIALS_PATH", mock_credentials_file)
        # Ensure no environment variables are set
        monkeypatch.delenv("CLAUDETM_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("CLAUDETM_WEBHOOK_SECRET", raising=False)

        # Configure mock SDK for simple planning response
        patched_sdk.set_planning_response("""## Task List

- [ ] Task 1: Test

## Success Criteria

1. Task completed
""")
        patched_sdk.set_work_response("Task completed successfully.")
        patched_sdk.set_verify_response("All success criteria met!")

        result = runner.invoke(
            app,
            ["start", "Test no webhook"],
        )

        # Check that the command ran
        assert result.exit_code in (0, 1)  # Success or paused
        assert "Starting new task" in result.output
        assert "Webhook:" not in result.output

        # Verify the state file has no webhook URL
        state_file = integration_state_dir / "state.json"
        assert state_file.exists(), "State file should be written after start command"
        import json

        with open(state_file) as f:
            state_data = json.load(f)
            assert state_data["options"]["webhook_url"] is None
            assert state_data["options"]["webhook_secret"] is None
