"""Tests for CredentialManager get_valid_token functionality.

This module tests the get_valid_token method which combines loading,
expiration checking, and automatic refresh.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from claude_task_master.core.credentials import (
    CredentialManager,
    CredentialNotFoundError,
    NetworkConnectionError,
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

    def test_get_valid_token_refreshes_when_expired(self, temp_dir, mock_expired_credentials_data):
        """Test get_valid_token refreshes when token is expired."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_expired_credentials_data))

        new_token_data = {
            "access_token": "refreshed-token",
            "refresh_token": "new-refresh-token",
            "expires_at": int((datetime.now() + timedelta(hours=2)).timestamp() * 1000),
        }

        mock_response = MagicMock()
        mock_response.json.return_value = new_token_data
        mock_response.status_code = 200

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch.object(httpx, "post", return_value=mock_response):
                token = manager.get_valid_token()

        assert token == "refreshed-token"

    def test_get_valid_token_file_not_found(self, temp_dir):
        """Test get_valid_token raises CredentialNotFoundError when file not found."""
        non_existent_path = temp_dir / "non-existent" / ".credentials.json"

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", non_existent_path):
            with pytest.raises(CredentialNotFoundError):
                manager.get_valid_token()

    def test_get_valid_token_refresh_fails(self, temp_dir, mock_expired_credentials_data):
        """Test get_valid_token propagates refresh errors."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_expired_credentials_data))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch.object(httpx, "post", side_effect=httpx.ConnectError("Network error")):
                with pytest.raises(NetworkConnectionError):
                    manager.get_valid_token()
