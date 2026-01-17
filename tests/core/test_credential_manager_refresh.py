"""Tests for CredentialManager token refresh functionality.

This module tests the refresh_access_token method and related error handling
for network errors, HTTP errors, and invalid responses.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from claude_task_master.core.credentials import (
    CredentialManager,
    Credentials,
    InvalidTokenResponseError,
    NetworkConnectionError,
    NetworkTimeoutError,
    TokenRefreshHTTPError,
)

# =============================================================================
# CredentialManager - Token Refresh Tests
# =============================================================================


class TestCredentialManagerRefresh:
    """Tests for token refresh functionality."""

    def test_refresh_access_token_success(self, temp_dir, mock_credentials_data):
        """Test successful token refresh."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_credentials_data))

        new_token_data = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_at": int((datetime.now() + timedelta(hours=2)).timestamp() * 1000),
            "token_type": "Bearer",
        }

        mock_response = MagicMock()
        mock_response.json.return_value = new_token_data
        mock_response.status_code = 200

        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch.object(httpx, "post", return_value=mock_response) as mock_post:
                new_creds = manager.refresh_access_token(original_creds)

        # Verify the API call
        mock_post.assert_called_once_with(
            CredentialManager.OAUTH_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "refresh_token": original_creds.refreshToken,
            },
            timeout=30.0,
        )

        # Verify new credentials
        assert new_creds.accessToken == "new-access-token"
        assert new_creds.refreshToken == "new-refresh-token"
        assert new_creds.expiresAt == new_token_data["expires_at"]

    def test_refresh_access_token_preserves_old_refresh_token(
        self, temp_dir, mock_credentials_data
    ):
        """Test that old refresh token is preserved if new one not provided."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_credentials_data))

        # Response without new refresh token
        new_token_data = {
            "access_token": "new-access-token",
            "expires_at": int((datetime.now() + timedelta(hours=2)).timestamp() * 1000),
        }

        mock_response = MagicMock()
        mock_response.json.return_value = new_token_data
        mock_response.status_code = 200

        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch.object(httpx, "post", return_value=mock_response):
                new_creds = manager.refresh_access_token(original_creds)

        # Old refresh token should be preserved
        assert new_creds.refreshToken == original_creds.refreshToken


class TestCredentialManagerRefreshNetworkErrors:
    """Tests for network error handling during token refresh."""

    def test_refresh_access_token_network_timeout(self, mock_credentials_data):
        """Test token refresh handles timeout errors with NetworkTimeoutError."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        with patch.object(httpx, "post", side_effect=httpx.TimeoutException("Timeout")):
            with pytest.raises(NetworkTimeoutError) as exc_info:
                manager.refresh_access_token(original_creds)

        assert exc_info.value.url == CredentialManager.OAUTH_TOKEN_URL
        assert exc_info.value.timeout == 30.0
        assert "timeout" in str(exc_info.value).lower()

    def test_refresh_access_token_connection_error(self, mock_credentials_data):
        """Test token refresh handles connection errors with NetworkConnectionError."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        with patch.object(httpx, "post", side_effect=httpx.ConnectError("Connection failed")):
            with pytest.raises(NetworkConnectionError) as exc_info:
                manager.refresh_access_token(original_creds)

        assert exc_info.value.url == CredentialManager.OAUTH_TOKEN_URL
        assert "connect" in str(exc_info.value).lower()

    def test_refresh_access_token_request_error(self, mock_credentials_data):
        """Test token refresh handles general request errors."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        # Create a mock request object for the error
        mock_request = MagicMock()
        with patch.object(
            httpx, "post", side_effect=httpx.RequestError("Request failed", request=mock_request)
        ):
            with pytest.raises(NetworkConnectionError) as exc_info:
                manager.refresh_access_token(original_creds)

        assert "connect" in str(exc_info.value).lower() or "network" in str(exc_info.value).lower()


class TestCredentialManagerRefreshHTTPErrors:
    """Tests for HTTP error handling during token refresh."""

    def test_refresh_access_token_http_401(self, mock_credentials_data):
        """Test token refresh handles 401 unauthorized."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = '{"error": "invalid_token"}'

        with patch.object(httpx, "post", return_value=mock_response):
            with pytest.raises(TokenRefreshHTTPError) as exc_info:
                manager.refresh_access_token(original_creds)

        assert exc_info.value.status_code == 401
        assert "Unauthorized" in str(exc_info.value)

    def test_refresh_access_token_http_403(self, mock_credentials_data):
        """Test token refresh handles 403 forbidden."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = '{"error": "forbidden"}'

        with patch.object(httpx, "post", return_value=mock_response):
            with pytest.raises(TokenRefreshHTTPError) as exc_info:
                manager.refresh_access_token(original_creds)

        assert exc_info.value.status_code == 403
        assert "Forbidden" in str(exc_info.value)

    def test_refresh_access_token_http_429_rate_limit(self, mock_credentials_data):
        """Test token refresh handles 429 rate limit."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = '{"error": "rate_limited"}'

        with patch.object(httpx, "post", return_value=mock_response):
            with pytest.raises(TokenRefreshHTTPError) as exc_info:
                manager.refresh_access_token(original_creds)

        assert exc_info.value.status_code == 429
        assert "rate limit" in str(exc_info.value).lower()

    def test_refresh_access_token_http_500(self, mock_credentials_data):
        """Test token refresh handles 500 server error."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = '{"error": "internal_error"}'

        with patch.object(httpx, "post", return_value=mock_response):
            with pytest.raises(TokenRefreshHTTPError) as exc_info:
                manager.refresh_access_token(original_creds)

        assert exc_info.value.status_code == 500
        assert "server error" in str(exc_info.value).lower()


class TestCredentialManagerRefreshInvalidResponse:
    """Tests for invalid response handling during token refresh."""

    def test_refresh_access_token_invalid_json_response(self, mock_credentials_data):
        """Test token refresh handles invalid JSON response."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid", "", 0)
        mock_response.text = "not valid json"

        with patch.object(httpx, "post", return_value=mock_response):
            with pytest.raises(InvalidTokenResponseError) as exc_info:
                manager.refresh_access_token(original_creds)

        assert "not valid JSON" in str(exc_info.value)

    def test_refresh_access_token_missing_access_token_field(self, mock_credentials_data):
        """Test token refresh handles missing access_token field."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"expires_at": 12345}

        with patch.object(httpx, "post", return_value=mock_response):
            with pytest.raises(InvalidTokenResponseError) as exc_info:
                manager.refresh_access_token(original_creds)

        assert "access_token" in str(exc_info.value)

    def test_refresh_access_token_missing_expires_at_field(self, mock_credentials_data):
        """Test token refresh handles missing expires_at field."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "new-token"}

        with patch.object(httpx, "post", return_value=mock_response):
            with pytest.raises(InvalidTokenResponseError) as exc_info:
                manager.refresh_access_token(original_creds)

        assert "expires_at" in str(exc_info.value)

    def test_refresh_access_token_non_dict_response(self, mock_credentials_data):
        """Test token refresh handles non-dict response."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["not", "a", "dict"]

        with patch.object(httpx, "post", return_value=mock_response):
            with pytest.raises(InvalidTokenResponseError) as exc_info:
                manager.refresh_access_token(original_creds)

        assert "not a JSON object" in str(exc_info.value)
