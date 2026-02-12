"""Tests for CredentialManager get_valid_token functionality.

This module tests the get_valid_token method which loads credentials
without automatic refresh (handled by Claude Agent SDK).
"""

import json
from unittest.mock import patch

import pytest

from claude_task_master.core.credentials import (
    CredentialManager,
    CredentialNotFoundError,
)

# =============================================================================
# CredentialManager - get_valid_token Tests
# =============================================================================


class TestCredentialManagerGetValidToken:
    """Tests for the get_valid_token method."""

    def test_get_valid_token_not_expired(self, temp_dir, mock_credentials_data):
        """Test get_valid_token returns token when not expired."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_credentials_data))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            token = manager.get_valid_token()

        assert token == mock_credentials_data["claudeAiOauth"]["accessToken"]

    def test_get_valid_token_returns_expired_token(self, temp_dir, mock_expired_credentials_data):
        """Test get_valid_token returns token even when expired (SDK handles refresh)."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_expired_credentials_data))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            token = manager.get_valid_token()

        # Should return the token even if expired - SDK handles refresh
        assert token == mock_expired_credentials_data["claudeAiOauth"]["accessToken"]

    def test_get_valid_token_file_not_found(self, temp_dir):
        """Test get_valid_token raises CredentialNotFoundError when file not found."""
        non_existent_path = temp_dir / "non-existent" / ".credentials.json"

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", non_existent_path):
            with pytest.raises(CredentialNotFoundError):
                manager.get_valid_token()

    def test_verify_credentials_success(self, temp_dir, mock_credentials_data):
        """Test verify_credentials returns True when credentials are valid."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_credentials_data))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            assert manager.verify_credentials() is True
