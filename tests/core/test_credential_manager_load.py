"""Tests for CredentialManager loading functionality.

This module tests loading credentials from file, including error handling
for various failure scenarios.
"""

import json
from unittest.mock import patch

import pytest

from claude_task_master.core.credentials import (
    CredentialManager,
    CredentialNotFoundError,
    CredentialPermissionError,
    InvalidCredentialsError,
)

# =============================================================================
# CredentialManager - Loading Tests
# =============================================================================


class TestCredentialManagerLoad:
    """Tests for loading credentials from file."""

    def test_load_credentials_success(self, temp_dir, mock_credentials_data):
        """Test successful loading of credentials."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_credentials_data))

        manager = CredentialManager()
        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            creds = manager.load_credentials()

        assert creds.accessToken == mock_credentials_data["claudeAiOauth"]["accessToken"]
        assert creds.refreshToken == mock_credentials_data["claudeAiOauth"]["refreshToken"]
        assert creds.expiresAt == mock_credentials_data["claudeAiOauth"]["expiresAt"]
        assert creds.tokenType == "Bearer"

    def test_load_credentials_file_not_found(self, temp_dir):
        """Test loading credentials when file doesn't exist raises CredentialNotFoundError."""
        non_existent_path = temp_dir / "non-existent" / ".credentials.json"

        manager = CredentialManager()
        with patch.object(CredentialManager, "CREDENTIALS_PATH", non_existent_path):
            with pytest.raises(CredentialNotFoundError) as exc_info:
                manager.load_credentials()

        assert exc_info.value.path == non_existent_path
        assert "Credentials not found" in str(exc_info.value)
        assert "claude" in str(exc_info.value).lower()

    def test_load_credentials_flat_structure(self, temp_dir):
        """Test loading credentials without nested claudeAiOauth wrapper."""
        flat_data = {
            "accessToken": "flat-access-token",
            "refreshToken": "flat-refresh-token",
            "expiresAt": 1704067200000,
            "tokenType": "Bearer",
        }
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(flat_data))

        manager = CredentialManager()
        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            creds = manager.load_credentials()

        assert creds.accessToken == "flat-access-token"
        assert creds.refreshToken == "flat-refresh-token"

    def test_load_credentials_invalid_json(self, temp_dir):
        """Test loading credentials from invalid JSON file raises InvalidCredentialsError."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text("{ invalid json }")

        manager = CredentialManager()
        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with pytest.raises(InvalidCredentialsError) as exc_info:
                manager.load_credentials()

        assert "invalid JSON" in str(exc_info.value)

    def test_load_credentials_missing_required_fields(self, temp_dir):
        """Test loading credentials with missing required fields raises InvalidCredentialsError."""
        incomplete_data = {
            "claudeAiOauth": {
                "accessToken": "test-token",
                # Missing refreshToken and expiresAt
            }
        }
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(incomplete_data))

        manager = CredentialManager()
        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with pytest.raises(InvalidCredentialsError) as exc_info:
                manager.load_credentials()

        error_str = str(exc_info.value)
        assert "invalid structure" in error_str.lower()
        assert "refreshToken" in error_str or "expiresAt" in error_str

    def test_load_credentials_empty_file(self, temp_dir):
        """Test loading credentials from empty file raises InvalidCredentialsError."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text("")

        manager = CredentialManager()
        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with pytest.raises(InvalidCredentialsError) as exc_info:
                manager.load_credentials()

        assert "invalid JSON" in str(exc_info.value)

    def test_load_credentials_empty_json_object(self, temp_dir):
        """Test loading credentials from empty JSON object raises InvalidCredentialsError."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text("{}")

        manager = CredentialManager()
        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with pytest.raises(InvalidCredentialsError) as exc_info:
                manager.load_credentials()

        assert "empty" in str(exc_info.value).lower()

    def test_load_credentials_permission_error(self, temp_dir, mock_credentials_data):
        """Test handling of permission errors when loading credentials."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_credentials_data))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch("builtins.open", side_effect=PermissionError("Access denied")):
                with pytest.raises(CredentialPermissionError) as exc_info:
                    manager.load_credentials()

        assert exc_info.value.operation == "reading"
        assert "Permission denied" in str(exc_info.value)
