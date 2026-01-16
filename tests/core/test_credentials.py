"""Comprehensive tests for the credentials module."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from claude_task_master.core.credentials import (
    CredentialError,
    CredentialManager,
    CredentialNotFoundError,
    CredentialPermissionError,
    Credentials,
    InvalidCredentialsError,
    InvalidTokenResponseError,
    NetworkConnectionError,
    NetworkTimeoutError,
    TokenRefreshError,
    TokenRefreshHTTPError,
)

# =============================================================================
# Exception Classes Tests
# =============================================================================


class TestCredentialError:
    """Tests for the base CredentialError exception."""

    def test_credential_error_with_message_only(self):
        """Test CredentialError with just a message."""
        error = CredentialError("Test error message")
        assert error.message == "Test error message"
        assert error.details is None
        assert str(error) == "Test error message"

    def test_credential_error_with_message_and_details(self):
        """Test CredentialError with message and details."""
        error = CredentialError("Test error", "Additional details")
        assert error.message == "Test error"
        assert error.details == "Additional details"
        assert "Test error" in str(error)
        assert "Additional details" in str(error)


class TestCredentialNotFoundError:
    """Tests for CredentialNotFoundError exception."""

    def test_credential_not_found_error(self):
        """Test CredentialNotFoundError initialization."""
        path = Path("/test/path/.credentials.json")
        error = CredentialNotFoundError(path)
        assert error.path == path
        assert "Credentials not found" in str(error)
        assert str(path) in str(error)
        assert "claude" in str(error).lower()

    def test_credential_not_found_is_credential_error(self):
        """Test that CredentialNotFoundError inherits from CredentialError."""
        error = CredentialNotFoundError(Path("/test"))
        assert isinstance(error, CredentialError)


class TestInvalidCredentialsError:
    """Tests for InvalidCredentialsError exception."""

    def test_invalid_credentials_error(self):
        """Test InvalidCredentialsError initialization."""
        error = InvalidCredentialsError("Invalid format", "Missing field: token")
        assert error.message == "Invalid format"
        assert error.details == "Missing field: token"
        assert isinstance(error, CredentialError)


class TestCredentialPermissionError:
    """Tests for CredentialPermissionError exception."""

    def test_credential_permission_error(self):
        """Test CredentialPermissionError initialization."""
        path = Path("/test/.credentials.json")
        original = PermissionError("Permission denied")
        error = CredentialPermissionError(path, "reading", original)

        assert error.path == path
        assert error.operation == "reading"
        assert error.original_error == original
        assert "Permission denied" in str(error)
        assert "reading" in str(error)
        assert isinstance(error, CredentialError)


class TestTokenRefreshError:
    """Tests for TokenRefreshError exception."""

    def test_token_refresh_error_basic(self):
        """Test TokenRefreshError with basic message."""
        error = TokenRefreshError("Refresh failed")
        assert error.message == "Refresh failed"
        assert error.status_code is None
        assert isinstance(error, CredentialError)

    def test_token_refresh_error_with_status_code(self):
        """Test TokenRefreshError with status code."""
        error = TokenRefreshError("Unauthorized", "Invalid token", 401)
        assert error.status_code == 401


class TestNetworkTimeoutError:
    """Tests for NetworkTimeoutError exception."""

    def test_network_timeout_error(self):
        """Test NetworkTimeoutError initialization."""
        error = NetworkTimeoutError("https://api.example.com/token", 30.0)
        assert error.url == "https://api.example.com/token"
        assert error.timeout == 30.0
        assert "timeout" in str(error).lower()
        assert "30" in str(error)
        assert isinstance(error, TokenRefreshError)


class TestNetworkConnectionError:
    """Tests for NetworkConnectionError exception."""

    def test_network_connection_error(self):
        """Test NetworkConnectionError initialization."""
        original = ConnectionError("Connection refused")
        error = NetworkConnectionError("https://api.example.com/token", original)
        assert error.url == "https://api.example.com/token"
        assert error.original_error == original
        assert "connect" in str(error).lower()
        assert isinstance(error, TokenRefreshError)


class TestTokenRefreshHTTPError:
    """Tests for TokenRefreshHTTPError exception."""

    def test_token_refresh_http_error_401(self):
        """Test TokenRefreshHTTPError with 401 status."""
        error = TokenRefreshHTTPError(401)
        assert error.status_code == 401
        assert "Unauthorized" in str(error)
        assert isinstance(error, TokenRefreshError)

    def test_token_refresh_http_error_403(self):
        """Test TokenRefreshHTTPError with 403 status."""
        error = TokenRefreshHTTPError(403)
        assert error.status_code == 403
        assert "Forbidden" in str(error)

    def test_token_refresh_http_error_429(self):
        """Test TokenRefreshHTTPError with 429 rate limit status."""
        error = TokenRefreshHTTPError(429)
        assert error.status_code == 429
        assert "rate limit" in str(error).lower()

    def test_token_refresh_http_error_500(self):
        """Test TokenRefreshHTTPError with 500 server error."""
        error = TokenRefreshHTTPError(500)
        assert error.status_code == 500
        assert "server error" in str(error).lower()

    def test_token_refresh_http_error_with_response_body(self):
        """Test TokenRefreshHTTPError with response body."""
        error = TokenRefreshHTTPError(400, '{"error": "invalid_grant"}')
        assert error.response_body == '{"error": "invalid_grant"}'
        assert "invalid_grant" in str(error)

    def test_token_refresh_http_error_unknown_status(self):
        """Test TokenRefreshHTTPError with unknown status code."""
        error = TokenRefreshHTTPError(418)  # I'm a teapot
        assert error.status_code == 418
        assert "418" in str(error)


class TestInvalidTokenResponseError:
    """Tests for InvalidTokenResponseError exception."""

    def test_invalid_token_response_error(self):
        """Test InvalidTokenResponseError initialization."""
        error = InvalidTokenResponseError("Missing access_token", {"refresh_token": "xxx"})
        assert error.response_data == {"refresh_token": "xxx"}
        assert "access_token" in str(error).lower()
        assert isinstance(error, TokenRefreshError)


# =============================================================================
# Credentials Model Tests
# =============================================================================


class TestCredentialsModel:
    """Tests for the Credentials Pydantic model."""

    def test_credentials_creation_with_required_fields(self):
        """Test creating credentials with all required fields."""
        creds = Credentials(
            accessToken="test-access-token",
            refreshToken="test-refresh-token",
            expiresAt=1704067200000,  # Timestamp in milliseconds
        )
        assert creds.accessToken == "test-access-token"
        assert creds.refreshToken == "test-refresh-token"
        assert creds.expiresAt == 1704067200000
        assert creds.tokenType == "Bearer"  # Default value

    def test_credentials_creation_with_custom_token_type(self):
        """Test creating credentials with a custom token type."""
        creds = Credentials(
            accessToken="test-access-token",
            refreshToken="test-refresh-token",
            expiresAt=1704067200000,
            tokenType="CustomToken",
        )
        assert creds.tokenType == "CustomToken"

    def test_credentials_model_dump(self):
        """Test that model can be serialized to dict."""
        creds = Credentials(
            accessToken="test-access-token",
            refreshToken="test-refresh-token",
            expiresAt=1704067200000,
            tokenType="Bearer",
        )
        data = creds.model_dump()
        assert data == {
            "accessToken": "test-access-token",
            "refreshToken": "test-refresh-token",
            "expiresAt": 1704067200000,
            "tokenType": "Bearer",
        }

    def test_credentials_validation_missing_access_token(self):
        """Test that missing access token raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            Credentials(  # type: ignore[call-arg]
                refreshToken="test-refresh-token",
                expiresAt=1704067200000,
            )
        assert "accessToken" in str(exc_info.value)

    def test_credentials_validation_missing_refresh_token(self):
        """Test that missing refresh token raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            Credentials(  # type: ignore[call-arg]
                accessToken="test-access-token",
                expiresAt=1704067200000,
            )
        assert "refreshToken" in str(exc_info.value)

    def test_credentials_validation_missing_expires_at(self):
        """Test that missing expiresAt raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            Credentials(  # type: ignore[call-arg]
                accessToken="test-access-token",
                refreshToken="test-refresh-token",
            )
        assert "expiresAt" in str(exc_info.value)

    def test_credentials_validation_invalid_expires_at_type(self):
        """Test that invalid expiresAt type raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            Credentials(
                accessToken="test-access-token",
                refreshToken="test-refresh-token",
                expiresAt="not-a-number",  # type: ignore[arg-type]
            )
        assert "expiresAt" in str(exc_info.value)


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


# =============================================================================
# CredentialManager - Expiration Tests
# =============================================================================


class TestCredentialManagerExpiration:
    """Tests for token expiration checking."""

    def test_is_expired_with_future_timestamp(self):
        """Test that future timestamp is not expired."""
        manager = CredentialManager()
        # Set expiration to 1 hour from now
        future_ts = int((datetime.now() + timedelta(hours=1)).timestamp() * 1000)
        creds = Credentials(
            accessToken="test",
            refreshToken="test",
            expiresAt=future_ts,
        )
        assert manager.is_expired(creds) is False

    def test_is_expired_with_past_timestamp(self):
        """Test that past timestamp is expired."""
        manager = CredentialManager()
        # Set expiration to 1 hour ago
        past_ts = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)
        creds = Credentials(
            accessToken="test",
            refreshToken="test",
            expiresAt=past_ts,
        )
        assert manager.is_expired(creds) is True

    def test_is_expired_at_exact_expiration_time(self):
        """Test that exact expiration time is considered expired."""
        manager = CredentialManager()
        # Set expiration to right now
        now_ts = int(datetime.now().timestamp() * 1000)
        creds = Credentials(
            accessToken="test",
            refreshToken="test",
            expiresAt=now_ts,
        )
        # At exact time or later is expired
        assert manager.is_expired(creds) is True

    def test_is_expired_with_far_future_timestamp(self):
        """Test with timestamp far in the future."""
        manager = CredentialManager()
        # Set expiration to 1 year from now
        future_ts = int((datetime.now() + timedelta(days=365)).timestamp() * 1000)
        creds = Credentials(
            accessToken="test",
            refreshToken="test",
            expiresAt=future_ts,
        )
        assert manager.is_expired(creds) is False

    def test_is_expired_with_just_expired_timestamp(self):
        """Test with timestamp that just expired (1 second ago)."""
        manager = CredentialManager()
        # Set expiration to 1 second ago
        past_ts = int((datetime.now() - timedelta(seconds=1)).timestamp() * 1000)
        creds = Credentials(
            accessToken="test",
            refreshToken="test",
            expiresAt=past_ts,
        )
        assert manager.is_expired(creds) is True

    def test_is_expired_handles_millisecond_timestamp(self):
        """Test that millisecond timestamps are correctly handled."""
        manager = CredentialManager()
        # Create timestamp in milliseconds (as stored in credentials)
        future_ts = int((datetime.now() + timedelta(hours=1)).timestamp() * 1000)
        creds = Credentials(
            accessToken="test",
            refreshToken="test",
            expiresAt=future_ts,
        )
        # Should properly handle the conversion from milliseconds to seconds
        assert manager.is_expired(creds) is False


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


# =============================================================================
# Integration Tests
# =============================================================================


class TestCredentialManagerIntegration:
    """Integration tests for the complete workflow."""

    def test_full_workflow_load_refresh_save(self, temp_dir, mock_expired_credentials_data):
        """Test complete workflow: load expired credentials, refresh, save."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_expired_credentials_data))

        new_expires_at = int((datetime.now() + timedelta(hours=2)).timestamp() * 1000)
        new_token_data = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_at": new_expires_at,
            "token_type": "Bearer",
        }

        mock_response = MagicMock()
        mock_response.json.return_value = new_token_data
        mock_response.status_code = 200

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch.object(httpx, "post", return_value=mock_response):
                # Get valid token (should trigger refresh)
                token = manager.get_valid_token()

        assert token == "new-access-token"

        # Verify credentials were saved
        saved_data = json.loads(credentials_path.read_text())
        assert saved_data["claudeAiOauth"]["accessToken"] == "new-access-token"
        assert saved_data["claudeAiOauth"]["refreshToken"] == "new-refresh-token"
        assert saved_data["claudeAiOauth"]["expiresAt"] == new_expires_at

    def test_multiple_load_operations(self, temp_dir, mock_credentials_data):
        """Test that multiple load operations work correctly."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_credentials_data))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            creds1 = manager.load_credentials()
            creds2 = manager.load_credentials()
            creds3 = manager.load_credentials()

        # All should return the same data
        assert creds1.accessToken == creds2.accessToken == creds3.accessToken
        assert creds1.refreshToken == creds2.refreshToken == creds3.refreshToken

    def test_credentials_path_constant(self):
        """Test that default credentials path is correct."""
        manager = CredentialManager()
        expected_path = Path.home() / ".claude" / ".credentials.json"
        assert manager.CREDENTIALS_PATH == expected_path

    def test_oauth_url_constant(self):
        """Test that OAuth URL constant is correct."""
        manager = CredentialManager()
        assert manager.OAUTH_TOKEN_URL == "https://api.anthropic.com/v1/oauth/token"


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestCredentialManagerEdgeCases:
    """Tests for edge cases and error handling."""

    def test_credentials_with_empty_strings(self, temp_dir):
        """Test handling credentials with empty string values."""
        data = {
            "claudeAiOauth": {
                "accessToken": "",
                "refreshToken": "",
                "expiresAt": 1704067200000,
            }
        }
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(data))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            creds = manager.load_credentials()

        # Empty strings should be allowed (Pydantic doesn't validate content)
        assert creds.accessToken == ""
        assert creds.refreshToken == ""

    def test_credentials_with_extra_fields(self, temp_dir):
        """Test loading credentials with extra unrecognized fields."""
        data = {
            "claudeAiOauth": {
                "accessToken": "test-token",
                "refreshToken": "test-refresh",
                "expiresAt": 1704067200000,
                "tokenType": "Bearer",
                "extra_field": "should_be_ignored",
                "another_extra": 12345,
            }
        }
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(data))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            creds = manager.load_credentials()

        # Extra fields should be ignored
        assert creds.accessToken == "test-token"
        assert not hasattr(creds, "extra_field")

    def test_credentials_with_special_characters_in_token(self, temp_dir):
        """Test credentials with special characters in tokens."""
        special_token = "token+with/special=chars&more%stuff"
        data = {
            "claudeAiOauth": {
                "accessToken": special_token,
                "refreshToken": "refresh-with-special-!@#$%^&*()",
                "expiresAt": 1704067200000,
            }
        }
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(data))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            creds = manager.load_credentials()

        assert creds.accessToken == special_token

    def test_credentials_with_unicode_characters(self, temp_dir):
        """Test credentials with unicode characters."""
        unicode_token = "token_with_unicode_\U0001f510_emoji"
        data = {
            "claudeAiOauth": {
                "accessToken": unicode_token,
                "refreshToken": "refresh_token_n",
                "expiresAt": 1704067200000,
            }
        }
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(data, ensure_ascii=False))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            creds = manager.load_credentials()

        assert creds.accessToken == unicode_token

    def test_expires_at_zero_timestamp(self):
        """Test handling of zero timestamp (epoch)."""
        manager = CredentialManager()
        creds = Credentials(
            accessToken="test",
            refreshToken="test",
            expiresAt=0,  # Unix epoch
        )
        # Zero timestamp is definitely expired
        assert manager.is_expired(creds) is True

    def test_expires_at_negative_timestamp(self):
        """Test handling of negative timestamp."""
        manager = CredentialManager()
        creds = Credentials(
            accessToken="test",
            refreshToken="test",
            expiresAt=-1000,  # Negative timestamp
        )
        # Negative timestamp is definitely expired
        assert manager.is_expired(creds) is True

    def test_expires_at_very_large_timestamp(self):
        """Test handling of very large future timestamp."""
        manager = CredentialManager()
        # Year 3000 timestamp in milliseconds
        far_future_ts = int(datetime(3000, 1, 1).timestamp() * 1000)
        creds = Credentials(
            accessToken="test",
            refreshToken="test",
            expiresAt=far_future_ts,
        )
        assert manager.is_expired(creds) is False

    def test_exception_hierarchy(self):
        """Test that all custom exceptions inherit correctly."""
        # All should inherit from CredentialError
        assert issubclass(CredentialNotFoundError, CredentialError)
        assert issubclass(InvalidCredentialsError, CredentialError)
        assert issubclass(CredentialPermissionError, CredentialError)
        assert issubclass(TokenRefreshError, CredentialError)

        # Token refresh specific errors should inherit from TokenRefreshError
        assert issubclass(NetworkTimeoutError, TokenRefreshError)
        assert issubclass(NetworkConnectionError, TokenRefreshError)
        assert issubclass(TokenRefreshHTTPError, TokenRefreshError)
        assert issubclass(InvalidTokenResponseError, TokenRefreshError)

    def test_can_catch_all_credential_errors(self):
        """Test that all credential errors can be caught with base class."""
        errors = [
            CredentialNotFoundError(Path("/test")),
            InvalidCredentialsError("Invalid"),
            CredentialPermissionError(Path("/test"), "reading", Exception()),
            TokenRefreshError("Refresh failed"),
            NetworkTimeoutError("http://test", 30.0),
            NetworkConnectionError("http://test", Exception()),
            TokenRefreshHTTPError(401),
            InvalidTokenResponseError("Invalid response"),
        ]

        for error in errors:
            try:
                raise error
            except CredentialError:
                pass  # Expected - all should be caught
            except Exception as e:
                pytest.fail(f"Error {type(error).__name__} was not caught as CredentialError: {e}")
