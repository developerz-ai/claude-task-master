"""Comprehensive tests for the credentials module."""

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
import httpx

from claude_task_master.core.credentials import Credentials, CredentialManager


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
            Credentials(
                refreshToken="test-refresh-token",
                expiresAt=1704067200000,
            )
        assert "accessToken" in str(exc_info.value)

    def test_credentials_validation_missing_refresh_token(self):
        """Test that missing refresh token raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            Credentials(
                accessToken="test-access-token",
                expiresAt=1704067200000,
            )
        assert "refreshToken" in str(exc_info.value)

    def test_credentials_validation_missing_expires_at(self):
        """Test that missing expiresAt raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            Credentials(
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
                expiresAt="not-a-number",
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
        """Test loading credentials when file doesn't exist."""
        non_existent_path = temp_dir / "non-existent" / ".credentials.json"

        manager = CredentialManager()
        with patch.object(CredentialManager, "CREDENTIALS_PATH", non_existent_path):
            with pytest.raises(FileNotFoundError) as exc_info:
                manager.load_credentials()

        assert "Credentials not found" in str(exc_info.value)
        assert "Please run 'claude' CLI first" in str(exc_info.value)

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
        """Test loading credentials from invalid JSON file."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text("{ invalid json }")

        manager = CredentialManager()
        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with pytest.raises(json.JSONDecodeError):
                manager.load_credentials()

    def test_load_credentials_missing_required_fields(self, temp_dir):
        """Test loading credentials with missing required fields."""
        from pydantic import ValidationError

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
            with pytest.raises(ValidationError):
                manager.load_credentials()

    def test_load_credentials_empty_file(self, temp_dir):
        """Test loading credentials from empty file."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text("")

        manager = CredentialManager()
        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with pytest.raises(json.JSONDecodeError):
                manager.load_credentials()

    def test_load_credentials_empty_json_object(self, temp_dir):
        """Test loading credentials from empty JSON object."""
        from pydantic import ValidationError

        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text("{}")

        manager = CredentialManager()
        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with pytest.raises(ValidationError):
                manager.load_credentials()


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
        mock_response.raise_for_status = MagicMock()

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

    def test_refresh_access_token_preserves_old_refresh_token(self, temp_dir, mock_credentials_data):
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
        mock_response.raise_for_status = MagicMock()

        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch.object(httpx, "post", return_value=mock_response):
                new_creds = manager.refresh_access_token(original_creds)

        # Old refresh token should be preserved
        assert new_creds.refreshToken == original_creds.refreshToken

    def test_refresh_access_token_network_error(self, mock_credentials_data):
        """Test token refresh handles network errors."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        with patch.object(httpx, "post", side_effect=httpx.ConnectError("Connection failed")):
            with pytest.raises(httpx.ConnectError):
                manager.refresh_access_token(original_creds)

    def test_refresh_access_token_timeout(self, mock_credentials_data):
        """Test token refresh handles timeout errors."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        with patch.object(httpx, "post", side_effect=httpx.TimeoutException("Timeout")):
            with pytest.raises(httpx.TimeoutException):
                manager.refresh_access_token(original_creds)

    def test_refresh_access_token_http_error(self, mock_credentials_data):
        """Test token refresh handles HTTP errors (401, 403, etc.)."""
        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )

        with patch.object(httpx, "post", return_value=mock_response):
            with pytest.raises(httpx.HTTPStatusError):
                manager.refresh_access_token(original_creds)

    def test_refresh_access_token_invalid_response_format(self, temp_dir, mock_credentials_data):
        """Test token refresh handles invalid response format."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_credentials_data))

        # Response missing required fields
        invalid_response_data = {"invalid": "data"}

        mock_response = MagicMock()
        mock_response.json.return_value = invalid_response_data
        mock_response.raise_for_status = MagicMock()

        manager = CredentialManager()
        original_creds = Credentials(**mock_credentials_data["claudeAiOauth"])

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch.object(httpx, "post", return_value=mock_response):
                with pytest.raises(KeyError):
                    manager.refresh_access_token(original_creds)


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
        mock_response.raise_for_status = MagicMock()

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch.object(httpx, "post", return_value=mock_response):
                token = manager.get_valid_token()

        assert token == "refreshed-token"

    def test_get_valid_token_file_not_found(self, temp_dir):
        """Test get_valid_token raises error when file not found."""
        non_existent_path = temp_dir / "non-existent" / ".credentials.json"

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", non_existent_path):
            with pytest.raises(FileNotFoundError):
                manager.get_valid_token()

    def test_get_valid_token_refresh_fails(self, temp_dir, mock_expired_credentials_data):
        """Test get_valid_token propagates refresh errors."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text(json.dumps(mock_expired_credentials_data))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch.object(httpx, "post", side_effect=httpx.ConnectError("Network error")):
                with pytest.raises(httpx.ConnectError):
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
        mock_response.raise_for_status = MagicMock()

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
        unicode_token = "token_with_unicode_🔐_emoji"
        data = {
            "claudeAiOauth": {
                "accessToken": unicode_token,
                "refreshToken": "refresh_tökén_ñ",
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

    def test_load_credentials_permission_error(self, temp_dir, mock_credentials_data):
        """Test handling of permission errors when loading credentials."""
        credentials_path = temp_dir / ".claude" / ".credentials.json"
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        # Create the file so it passes the exists() check
        credentials_path.write_text(json.dumps(mock_credentials_data))

        manager = CredentialManager()

        with patch.object(CredentialManager, "CREDENTIALS_PATH", credentials_path):
            with patch("builtins.open", side_effect=PermissionError("Access denied")):
                with pytest.raises(PermissionError):
                    manager.load_credentials()

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
                with pytest.raises(PermissionError):
                    manager._save_credentials(creds)
