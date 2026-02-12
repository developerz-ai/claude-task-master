"""Credential Manager - OAuth credential loading and validation.

Token refresh is handled automatically by the Claude Agent SDK.
This module only loads and validates credentials from disk.
"""

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

# =============================================================================
# Custom Exception Classes
# =============================================================================


class CredentialError(Exception):
    """Base exception for all credential-related errors."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class CredentialNotFoundError(CredentialError):
    """Raised when credentials file is not found."""

    def __init__(self, path: Path):
        super().__init__(
            f"Credentials not found at {path}",
            "Please run 'claude' CLI first to authenticate, then try again.",
        )
        self.path = path


class InvalidCredentialsError(CredentialError):
    """Raised when credentials are malformed or invalid."""

    def __init__(self, message: str, details: str | None = None):
        super().__init__(message, details)


class CredentialPermissionError(CredentialError):
    """Raised when there are permission issues accessing credentials."""

    def __init__(self, path: Path, operation: str, original_error: Exception):
        self.path = path
        self.operation = operation
        self.original_error = original_error
        super().__init__(
            f"Permission denied when {operation} credentials at {path}",
            f"Check file permissions. Original error: {original_error}",
        )


class TokenRefreshError(CredentialError):
    """Raised when token refresh fails."""

    def __init__(self, message: str, details: str | None = None, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message, details)


class NetworkTimeoutError(TokenRefreshError):
    """Raised when a network timeout occurs during token refresh."""

    def __init__(self, url: str, timeout: float):
        self.url = url
        self.timeout = timeout
        super().__init__(
            f"Network timeout while connecting to {url}",
            f"Request timed out after {timeout} seconds. Check your network connection.",
        )


class NetworkConnectionError(TokenRefreshError):
    """Raised when a network connection error occurs during token refresh."""

    def __init__(self, url: str, original_error: Exception):
        self.url = url
        self.original_error = original_error
        super().__init__(
            f"Failed to connect to {url}",
            f"Network error: {original_error}. Check your internet connection.",
        )


class TokenRefreshHTTPError(TokenRefreshError):
    """Raised when the token refresh endpoint returns an HTTP error."""

    def __init__(self, status_code: int, response_body: str | None = None):
        self.response_body = response_body
        error_messages = {
            400: "Bad request - the refresh token may be malformed",
            401: "Unauthorized - the refresh token may be invalid or expired",
            403: "Forbidden - you may not have permission to refresh this token",
            404: "Token endpoint not found - the API URL may have changed",
            429: "Rate limited - too many refresh attempts, please try again later",
            500: "Server error - the authentication server is experiencing issues",
            502: "Bad gateway - the authentication server may be temporarily unavailable",
            503: "Service unavailable - the authentication server is temporarily unavailable",
        }
        message = error_messages.get(status_code, f"HTTP error {status_code}")
        details = response_body if response_body else None
        super().__init__(f"Token refresh failed: {message}", details, status_code)


class InvalidTokenResponseError(TokenRefreshError):
    """Raised when the token refresh response is invalid or malformed."""

    def __init__(self, message: str, response_data: dict | None = None):
        self.response_data = response_data
        details = f"Received response: {response_data}" if response_data else None
        super().__init__(message, details)


# =============================================================================
# Credentials Model
# =============================================================================


class Credentials(BaseModel):
    """OAuth credentials model."""

    accessToken: str
    refreshToken: str
    expiresAt: int  # Timestamp in milliseconds
    tokenType: str = "Bearer"


# =============================================================================
# Credential Manager
# =============================================================================


class CredentialManager:
    """Manages OAuth credentials from ~/.claude/.credentials.json.

    Token refresh is handled automatically by the Claude Agent SDK.
    This class only loads and validates credentials from disk.
    """

    CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"

    def load_credentials(self) -> Credentials:
        """Load credentials from file.

        Returns:
            Credentials: The loaded OAuth credentials.

        Raises:
            CredentialNotFoundError: If the credentials file does not exist.
            InvalidCredentialsError: If the credentials file is malformed or invalid.
            CredentialPermissionError: If there are permission issues reading the file.
        """
        if not self.CREDENTIALS_PATH.exists():
            raise CredentialNotFoundError(self.CREDENTIALS_PATH)

        try:
            with open(self.CREDENTIALS_PATH) as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError as e:
                    raise InvalidCredentialsError(
                        "Credentials file contains invalid JSON",
                        f"JSON parse error at line {e.lineno}, column {e.colno}: {e.msg}",
                    ) from e
        except PermissionError as e:
            raise CredentialPermissionError(self.CREDENTIALS_PATH, "reading", e) from e

        # Handle empty JSON object
        if not data:
            raise InvalidCredentialsError(
                "Credentials file is empty or contains an empty JSON object",
                "Please re-authenticate using 'claude' CLI.",
            )

        # Handle nested structure - credentials are under 'claudeAiOauth' key
        if "claudeAiOauth" in data:
            data = data["claudeAiOauth"]

        try:
            return Credentials(**data)
        except ValidationError as e:
            # Extract meaningful error message from Pydantic validation error
            missing_fields = []
            invalid_fields = []
            for error in e.errors():
                field = ".".join(str(loc) for loc in error["loc"])
                if error["type"] == "missing":
                    missing_fields.append(field)
                else:
                    invalid_fields.append(f"{field}: {error['msg']}")

            details_parts = []
            if missing_fields:
                details_parts.append(f"Missing required fields: {', '.join(missing_fields)}")
            if invalid_fields:
                details_parts.append(f"Invalid fields: {'; '.join(invalid_fields)}")

            raise InvalidCredentialsError(
                "Credentials file has invalid structure",
                " | ".join(details_parts) if details_parts else str(e),
            ) from e

    def is_expired(self, credentials: Credentials) -> bool:
        """Check if access token is expired (for informational purposes only).

        NOTE: Token refresh is handled automatically by the Claude Agent SDK.
        This method is only useful for checking if the token appears expired.

        Args:
            credentials: The credentials to check.

        Returns:
            bool: True if the token is expired, False otherwise.
        """
        # expiresAt is in milliseconds, convert to seconds
        expires_at = datetime.fromtimestamp(credentials.expiresAt / 1000)
        return datetime.now() >= expires_at

    def get_valid_token(self) -> str:
        """Get access token from credentials file.

        NOTE: Token refresh is handled automatically by the Claude Agent SDK.
        This method only loads and returns the current token without refreshing.

        Returns:
            str: The current access token.

        Raises:
            CredentialNotFoundError: If the credentials file does not exist.
            InvalidCredentialsError: If the credentials are malformed.
            CredentialPermissionError: If there are permission issues.
        """
        credentials = self.load_credentials()
        return credentials.accessToken

    def verify_credentials(self) -> bool:
        """Verify that credentials exist and are loadable.

        NOTE: This does NOT validate tokens or check expiration.
        Token refresh is handled automatically by the Claude Agent SDK.

        Returns:
            bool: True if credentials can be loaded.

        Raises:
            CredentialNotFoundError: If the credentials file does not exist.
            InvalidCredentialsError: If the credentials are malformed.
            CredentialPermissionError: If there are permission issues.
        """
        self.load_credentials()
        return True
