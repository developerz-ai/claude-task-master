"""Tests for CredentialManager token expiration checking.

This module tests the is_expired method for determining if credentials
have expired.
"""

from datetime import datetime, timedelta

from claude_task_master.core.credentials import CredentialManager, Credentials

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
