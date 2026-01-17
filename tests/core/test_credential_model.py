"""Tests for the Credentials Pydantic model.

This module tests the Credentials model validation and serialization.
"""

import pytest

from claude_task_master.core.credentials import Credentials

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
