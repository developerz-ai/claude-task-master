"""Tests for CredentialManager save functionality.

This module tests saving credentials to file, including error handling
for permission issues.
"""

import json
from unittest.mock import patch

import pytest

from claude_task_master.core.credentials import (
    CredentialManager,
    CredentialPermissionError,
    Credentials,
)

# =============================================================================
# CredentialManager - Save Tests
# =============================================================================


class TestCredentialManagerSave:
    """Tests for saving credentials."""

    def test_save_credentials_creates_file(self, temp_dir):
        """Test that saving credentials creates the file."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)

        manager = CredentialManager()
        creds = Credentials(
            accessToken="new-token",
            refreshToken="new-refresh",
            expiresAt=1704067200000,
            tokenType="Bearer",
        )

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            manager._save_credentials(creds)

        assert credentials_path.exists()

        # Verify content
        saved_data = json.loads(credentials_path.read_text())
        assert "claudeAiOauth" in saved_data
        assert saved_data["claudeAiOauth"]["accessToken"] == "new-token"
        assert saved_data["claudeAiOauth"]["refreshToken"] == "new-refresh"

    def test_save_credentials_overwrites_existing(self, temp_dir, mock_credentials_data):
        """Test that saving credentials overwrites existing file."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_credentials_data))

        manager = CredentialManager()
        new_creds = Credentials(
            accessToken="updated-token",
            refreshToken="updated-refresh",
            expiresAt=9999999999999,
            tokenType="Bearer",
        )

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            manager._save_credentials(new_creds)

        saved_data = json.loads(credentials_path.read_text())
        assert saved_data["claudeAiOauth"]["accessToken"] == "updated-token"

    def test_save_credentials_preserves_nested_structure(self, temp_dir):
        """Test that saved credentials maintain the nested structure."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)

        manager = CredentialManager()
        creds = Credentials(
            accessToken="test-token",
            refreshToken="test-refresh",
            expiresAt=1704067200000,
            tokenType="Bearer",
        )

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            manager._save_credentials(creds)

        saved_data = json.loads(credentials_path.read_text())
        # Verify nested structure
        assert "claudeAiOauth" in saved_data
        assert isinstance(saved_data["claudeAiOauth"], dict)
        # Verify no extra top-level keys
        assert len(saved_data) == 1

    def test_save_credentials_formats_json_with_indent(self, temp_dir):
        """Test that saved JSON is formatted with indentation."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)

        manager = CredentialManager()
        creds = Credentials(
            accessToken="test-token",
            refreshToken="test-refresh",
            expiresAt=1704067200000,
        )

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            manager._save_credentials(creds)

        # Read raw content to check formatting
        content = credentials_path.read_text()
        # Indented JSON should have newlines
        assert "\n" in content
        # Should have indentation (2 spaces as per json.dump indent=2)
        assert "  " in content

    def test_save_credentials_permission_error(self, temp_dir):
        """Test handling of permission errors when saving credentials."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)

        manager = CredentialManager()
        creds = Credentials(
            accessToken="test",
            refreshToken="test",
            expiresAt=1704067200000,
        )

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch("builtins.open", side_effect=PermissionError("Access denied")):
                with pytest.raises(CredentialPermissionError) as exc_info:
                    manager._save_credentials(creds)

        assert exc_info.value.operation == "writing"
