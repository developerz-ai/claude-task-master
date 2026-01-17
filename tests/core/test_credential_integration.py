"""Integration tests and edge cases for credentials module.

This module tests complete workflows and edge cases for credential
handling, including special characters, unicode, and exception hierarchy.
"""

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
    InvalidCredentialsError,
    InvalidTokenResponseError,
    NetworkConnectionError,
    NetworkTimeoutError,
    TokenRefreshError,
    TokenRefreshHTTPError,
)

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


# =============================================================================
# Exception Hierarchy Tests
# =============================================================================


class TestCredentialExceptionHierarchy:
    """Tests for exception class hierarchy."""

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
