"""Credential Manager - OAuth credential loading, validation, and refresh."""

import json
from datetime import datetime
from pathlib import Path

import httpx
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
    """Manages OAuth credentials from ~/.claude/.credentials.json."""

    CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
    OAUTH_TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
    DEFAULT_TIMEOUT = 30.0

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
        """Check if access token is expired.

        Args:
            credentials: The credentials to check.

        Returns:
            bool: True if the token is expired, False otherwise.
        """
        # expiresAt is in milliseconds, convert to seconds
        expires_at = datetime.fromtimestamp(credentials.expiresAt / 1000)
        return datetime.now() >= expires_at

    def refresh_access_token(self, credentials: Credentials) -> Credentials:
        """Refresh access token using refresh token.

        Args:
            credentials: The current credentials containing the refresh token.

        Returns:
            Credentials: New credentials with refreshed access token.

        Raises:
            NetworkTimeoutError: If the request times out.
            NetworkConnectionError: If there's a network connection error.
            TokenRefreshHTTPError: If the server returns an HTTP error.
            InvalidTokenResponseError: If the response is malformed.
            CredentialPermissionError: If credentials cannot be saved.
        """
        try:
            response = httpx.post(
                self.OAUTH_TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": credentials.refreshToken,
                },
                timeout=self.DEFAULT_TIMEOUT,
            )
        except httpx.TimeoutException as e:
            raise NetworkTimeoutError(self.OAUTH_TOKEN_URL, self.DEFAULT_TIMEOUT) from e
        except httpx.ConnectError as e:
            raise NetworkConnectionError(self.OAUTH_TOKEN_URL, e) from e
        except httpx.RequestError as e:
            # Catch any other request-related errors
            raise NetworkConnectionError(self.OAUTH_TOKEN_URL, e) from e

        # Handle HTTP errors with specific messages
        if response.status_code >= 400:
            try:
                response_body = response.text
            except Exception:
                response_body = None
            raise TokenRefreshHTTPError(response.status_code, response_body)

        # Parse response JSON
        try:
            token_data = response.json()
        except json.JSONDecodeError as e:
            raise InvalidTokenResponseError(
                "Token refresh response is not valid JSON",
                {"raw_response": response.text[:500] if response.text else None},
            ) from e

        # Validate required fields in response
        if not isinstance(token_data, dict):
            raise InvalidTokenResponseError(
                "Token refresh response is not a JSON object",
                {"received_type": type(token_data).__name__},
            )

        if "access_token" not in token_data:
            raise InvalidTokenResponseError(
                "Token refresh response missing 'access_token' field",
                token_data,
            )

        if "expires_at" not in token_data:
            raise InvalidTokenResponseError(
                "Token refresh response missing 'expires_at' field",
                token_data,
            )

        try:
            new_credentials = Credentials(
                accessToken=token_data["access_token"],
                refreshToken=token_data.get("refresh_token", credentials.refreshToken),
                expiresAt=token_data["expires_at"],
                tokenType=token_data.get("token_type", "Bearer"),
            )
        except ValidationError as e:
            raise InvalidTokenResponseError(
                "Token refresh response contains invalid data",
                token_data,
            ) from e

        self._save_credentials(new_credentials)
        return new_credentials

    def _save_credentials(self, credentials: Credentials) -> None:
        """Save updated credentials to file.

        Args:
            credentials: The credentials to save.

        Raises:
            CredentialPermissionError: If there are permission issues writing the file.
        """
        # Preserve nested structure
        data = {"claudeAiOauth": credentials.model_dump()}
        try:
            with open(self.CREDENTIALS_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except PermissionError as e:
            raise CredentialPermissionError(self.CREDENTIALS_PATH, "writing", e) from e

    def get_valid_token(self) -> str:
        """Get a valid access token, refreshing if necessary.

        Returns:
            str: A valid access token.

        Raises:
            CredentialNotFoundError: If the credentials file does not exist.
            InvalidCredentialsError: If the credentials are malformed.
            CredentialPermissionError: If there are permission issues.
            TokenRefreshError: If token refresh fails (and its subclasses).
        """
        credentials = self.load_credentials()

        if self.is_expired(credentials):
            credentials = self.refresh_access_token(credentials)

        return credentials.accessToken
