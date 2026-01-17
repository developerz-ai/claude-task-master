"""Tests for credential exception classes.

This module tests all custom exception classes used in the credentials module.
"""

from pathlib import Path

from claude_task_master.core.credentials import (
    CredentialError,
    CredentialNotFoundError,
    CredentialPermissionError,
    InvalidCredentialsError,
    InvalidTokenResponseError,
    NetworkConnectionError,
    NetworkTimeoutError,
    TokenRefreshError,
    TokenRefreshHTTPError,
)

# =============================================================================
# Base CredentialError Tests
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


# =============================================================================
# Credential Not Found Error Tests
# =============================================================================


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


# =============================================================================
# Invalid Credentials Error Tests
# =============================================================================


class TestInvalidCredentialsError:
    """Tests for InvalidCredentialsError exception."""

    def test_invalid_credentials_error(self):
        """Test InvalidCredentialsError initialization."""
        error = InvalidCredentialsError("Invalid format", "Missing field: token")
        assert error.message == "Invalid format"
        assert error.details == "Missing field: token"
        assert isinstance(error, CredentialError)


# =============================================================================
# Credential Permission Error Tests
# =============================================================================


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


# =============================================================================
# Token Refresh Error Tests
# =============================================================================


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


# =============================================================================
# Network Timeout Error Tests
# =============================================================================


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


# =============================================================================
# Network Connection Error Tests
# =============================================================================


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


# =============================================================================
# Token Refresh HTTP Error Tests
# =============================================================================


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


# =============================================================================
# Invalid Token Response Error Tests
# =============================================================================


class TestInvalidTokenResponseError:
    """Tests for InvalidTokenResponseError exception."""

    def test_invalid_token_response_error(self):
        """Test InvalidTokenResponseError initialization."""
        error = InvalidTokenResponseError("Missing access_token", {"refresh_token": "xxx"})
        assert error.response_data == {"refresh_token": "xxx"}
        assert "access_token" in str(error).lower()
        assert isinstance(error, TokenRefreshError)
