"""Tests for password hashing and verification utilities.

Tests cover:
- Password hashing with bcrypt
- Password verification (hashed and plaintext)
- Environment variable configuration
- Authentication flow
- Error handling and edge cases
- Security considerations
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from claude_task_master.auth.password import (
    ENV_PASSWORD,
    ENV_PASSWORD_HASH,
    PASSLIB_AVAILABLE,
    AuthenticationError,
    InvalidPasswordError,
    PasswordNotConfiguredError,
    authenticate,
    get_password_from_env,
    hash_password,
    is_auth_enabled,
    is_password_hash,
    require_password_from_env,
    verify_password,
    verify_password_plaintext,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# Test: hash_password
# =============================================================================


class TestHashPassword:
    """Tests for hash_password function."""

    def test_hash_password_creates_bcrypt_hash(self) -> None:
        """Test that hash_password creates a valid bcrypt hash."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "my_secure_password_123"
        hashed = hash_password(password)

        # bcrypt hashes start with $2a$, $2b$, or $2y$
        assert hashed.startswith(("$2a$", "$2b$", "$2y$"))
        # bcrypt hashes are 60 characters long
        assert len(hashed) == 60

    def test_hash_password_different_each_time(self) -> None:
        """Test that hashing the same password produces different hashes (salt)."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "same_password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        # Different salts mean different hashes
        assert hash1 != hash2

    def test_hash_password_empty_raises_value_error(self) -> None:
        """Test that empty password raises ValueError."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        with pytest.raises(ValueError, match="Password cannot be empty"):
            hash_password("")

    def test_hash_password_without_passlib(self) -> None:
        """Test that hash_password raises ImportError when passlib not installed."""
        with patch("claude_task_master.auth.password.PASSLIB_AVAILABLE", False):
            with pytest.raises(ImportError, match="passlib\\[bcrypt\\] not installed"):
                hash_password("password")

    def test_hash_password_unicode_characters(self) -> None:
        """Test hashing passwords with unicode characters."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "pàsswörd_with_émojis_🔐"
        hashed = hash_password(password)

        # Should successfully hash and verify
        assert hashed.startswith(("$2a$", "$2b$", "$2y$"))
        assert verify_password(password, hashed)

    def test_hash_password_very_long(self) -> None:
        """Test hashing very long passwords."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "a" * 1000  # Very long password
        hashed = hash_password(password)

        assert hashed.startswith(("$2a$", "$2b$", "$2y$"))
        assert verify_password(password, hashed)


# =============================================================================
# Test: verify_password
# =============================================================================


class TestVerifyPassword:
    """Tests for verify_password function."""

    def test_verify_password_correct(self) -> None:
        """Test that correct password verifies successfully."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "my_test_password"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self) -> None:
        """Test that incorrect password fails verification."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "correct_password"
        wrong_password = "wrong_password"
        hashed = hash_password(password)

        assert verify_password(wrong_password, hashed) is False

    def test_verify_password_empty_password(self) -> None:
        """Test that empty password returns False."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        hashed = hash_password("something")
        assert verify_password("", hashed) is False

    def test_verify_password_empty_hash(self) -> None:
        """Test that empty hash returns False."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        assert verify_password("password", "") is False

    def test_verify_password_malformed_hash(self) -> None:
        """Test that malformed hash returns False (not exception)."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        # Invalid hash format
        assert verify_password("password", "not_a_bcrypt_hash") is False
        assert verify_password("password", "$invalid$hash$format") is False

    def test_verify_password_without_passlib(self) -> None:
        """Test that verify_password raises ImportError when passlib not installed."""
        with patch("claude_task_master.auth.password.PASSLIB_AVAILABLE", False):
            with pytest.raises(ImportError, match="passlib\\[bcrypt\\] not installed"):
                verify_password("password", "$2b$12$hash")

    def test_verify_password_case_sensitive(self) -> None:
        """Test that password verification is case-sensitive."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "MyPassword"
        hashed = hash_password(password)

        assert verify_password("MyPassword", hashed) is True
        assert verify_password("mypassword", hashed) is False
        assert verify_password("MYPASSWORD", hashed) is False

    def test_verify_password_timing_safe(self) -> None:
        """Test that verification uses constant-time comparison (functional test)."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "correct_password"
        hashed = hash_password(password)

        # These should all take similar time (constant-time comparison)
        # This is more of a functional test than a timing test
        assert verify_password("wrong", hashed) is False
        assert verify_password("very_wrong_password_that_is_long", hashed) is False
        assert verify_password("c", hashed) is False


# =============================================================================
# Test: verify_password_plaintext
# =============================================================================


class TestVerifyPasswordPlaintext:
    """Tests for verify_password_plaintext function."""

    def test_verify_plaintext_correct(self) -> None:
        """Test that matching plaintext passwords verify."""
        assert verify_password_plaintext("password123", "password123") is True

    def test_verify_plaintext_incorrect(self) -> None:
        """Test that non-matching plaintext passwords fail."""
        assert verify_password_plaintext("password123", "different") is False

    def test_verify_plaintext_empty_password(self) -> None:
        """Test that empty provided password returns False."""
        assert verify_password_plaintext("", "expected") is False

    def test_verify_plaintext_empty_expected(self) -> None:
        """Test that empty expected password returns False."""
        assert verify_password_plaintext("password", "") is False

    def test_verify_plaintext_both_empty(self) -> None:
        """Test that both empty returns False."""
        assert verify_password_plaintext("", "") is False

    def test_verify_plaintext_case_sensitive(self) -> None:
        """Test that plaintext verification is case-sensitive."""
        assert verify_password_plaintext("Password", "Password") is True
        assert verify_password_plaintext("Password", "password") is False
        assert verify_password_plaintext("password", "Password") is False

    def test_verify_plaintext_timing_safe(self) -> None:
        """Test that verification uses secrets.compare_digest."""
        # Using secrets.compare_digest ensures timing-safe comparison
        # Functional test to verify it works correctly
        expected = "my_secret_password"
        assert verify_password_plaintext(expected, expected) is True
        assert verify_password_plaintext("wrong", expected) is False
        assert verify_password_plaintext("my_secret_password_extra", expected) is False


# =============================================================================
# Test: get_password_from_env
# =============================================================================


class TestGetPasswordFromEnv:
    """Tests for get_password_from_env function."""

    def test_returns_none_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that None is returned when no env vars are set."""
        monkeypatch.delenv(ENV_PASSWORD, raising=False)
        monkeypatch.delenv(ENV_PASSWORD_HASH, raising=False)

        assert get_password_from_env() is None

    def test_returns_plaintext_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that plaintext password is returned."""
        monkeypatch.setenv(ENV_PASSWORD, "my_password")
        monkeypatch.delenv(ENV_PASSWORD_HASH, raising=False)

        assert get_password_from_env() == "my_password"

    def test_returns_password_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that password hash is returned."""
        monkeypatch.delenv(ENV_PASSWORD, raising=False)
        monkeypatch.setenv(ENV_PASSWORD_HASH, "$2b$12$hash_value_here")

        assert get_password_from_env() == "$2b$12$hash_value_here"

    def test_prefers_hash_over_plaintext(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that hash is preferred when both are set."""
        monkeypatch.setenv(ENV_PASSWORD, "plaintext")
        monkeypatch.setenv(ENV_PASSWORD_HASH, "$2b$12$hash_value")

        # Hash should be returned (takes precedence)
        result = get_password_from_env()
        assert result == "$2b$12$hash_value"

    def test_empty_string_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test handling of empty string environment variables."""
        monkeypatch.setenv(ENV_PASSWORD_HASH, "")
        monkeypatch.setenv(ENV_PASSWORD, "actual_password")

        # Empty string is falsy, should fall through to PASSWORD
        assert get_password_from_env() == "actual_password"


# =============================================================================
# Test: is_password_hash
# =============================================================================


class TestIsPasswordHash:
    """Tests for is_password_hash function."""

    def test_recognizes_bcrypt_2b_hash(self) -> None:
        """Test that $2b$ prefix is recognized."""
        assert is_password_hash("$2b$12$abcdefghijklmnopqrstuvwxyz") is True

    def test_recognizes_bcrypt_2a_hash(self) -> None:
        """Test that $2a$ prefix is recognized."""
        assert is_password_hash("$2a$12$abcdefghijklmnopqrstuvwxyz") is True

    def test_recognizes_bcrypt_2y_hash(self) -> None:
        """Test that $2y$ prefix is recognized."""
        assert is_password_hash("$2y$12$abcdefghijklmnopqrstuvwxyz") is True

    def test_rejects_plaintext_password(self) -> None:
        """Test that plaintext password is not recognized as hash."""
        assert is_password_hash("my_plaintext_password") is False

    def test_rejects_empty_string(self) -> None:
        """Test that empty string is not a hash."""
        assert is_password_hash("") is False

    def test_rejects_other_hash_formats(self) -> None:
        """Test that other hash formats are rejected."""
        assert is_password_hash("$1$md5hash") is False  # MD5
        assert is_password_hash("$5$sha256") is False  # SHA-256
        assert is_password_hash("$6$sha512") is False  # SHA-512
        assert is_password_hash("sha256:abcdef") is False  # Django format

    def test_rejects_malformed_bcrypt(self) -> None:
        """Test that malformed bcrypt-like strings are handled."""
        # Note: is_password_hash only checks prefix, not full structure
        # This is intentional - full validation happens during verification
        assert is_password_hash("$2b$") is True  # Has valid prefix
        assert is_password_hash("$2c$12$hash") is False  # Invalid variant (not 2a/2b/2y)


# =============================================================================
# Test: require_password_from_env
# =============================================================================


class TestRequirePasswordFromEnv:
    """Tests for require_password_from_env function."""

    def test_returns_password_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that password is returned when configured."""
        monkeypatch.setenv(ENV_PASSWORD, "my_password")

        assert require_password_from_env() == "my_password"

    def test_raises_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that PasswordNotConfiguredError is raised when not configured."""
        monkeypatch.delenv(ENV_PASSWORD, raising=False)
        monkeypatch.delenv(ENV_PASSWORD_HASH, raising=False)

        with pytest.raises(PasswordNotConfiguredError) as exc_info:
            require_password_from_env()

        # Check error message contains env var names
        assert ENV_PASSWORD in str(exc_info.value)
        assert ENV_PASSWORD_HASH in str(exc_info.value)


# =============================================================================
# Test: authenticate
# =============================================================================


class TestAuthenticate:
    """Tests for authenticate function."""

    def test_authenticate_with_plaintext_password_correct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test authentication with correct plaintext password."""
        monkeypatch.setenv(ENV_PASSWORD, "my_password")
        monkeypatch.delenv(ENV_PASSWORD_HASH, raising=False)

        assert authenticate("my_password") is True

    def test_authenticate_with_plaintext_password_incorrect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test authentication with incorrect plaintext password."""
        monkeypatch.setenv(ENV_PASSWORD, "correct_password")
        monkeypatch.delenv(ENV_PASSWORD_HASH, raising=False)

        assert authenticate("wrong_password") is False

    def test_authenticate_with_hashed_password_correct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test authentication with correct password against hash."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "my_secure_password"
        hashed = hash_password(password)

        monkeypatch.delenv(ENV_PASSWORD, raising=False)
        monkeypatch.setenv(ENV_PASSWORD_HASH, hashed)

        assert authenticate(password) is True

    def test_authenticate_with_hashed_password_incorrect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test authentication with incorrect password against hash."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "correct_password"
        hashed = hash_password(password)

        monkeypatch.delenv(ENV_PASSWORD, raising=False)
        monkeypatch.setenv(ENV_PASSWORD_HASH, hashed)

        assert authenticate("wrong_password") is False

    def test_authenticate_not_configured_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that authenticate raises when password not configured."""
        monkeypatch.delenv(ENV_PASSWORD, raising=False)
        monkeypatch.delenv(ENV_PASSWORD_HASH, raising=False)

        with pytest.raises(PasswordNotConfiguredError):
            authenticate("any_password")

    def test_authenticate_prefers_hash_over_plaintext(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that hash is used when both hash and plaintext are configured."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "correct_password"
        hashed = hash_password(password)

        # Set both (hash should be preferred)
        monkeypatch.setenv(ENV_PASSWORD, "plaintext_password")
        monkeypatch.setenv(ENV_PASSWORD_HASH, hashed)

        # Should authenticate against the hash
        assert authenticate(password) is True
        assert authenticate("plaintext_password") is False


# =============================================================================
# Test: is_auth_enabled
# =============================================================================


class TestIsAuthEnabled:
    """Tests for is_auth_enabled function."""

    def test_returns_false_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that False is returned when no password is configured."""
        monkeypatch.delenv(ENV_PASSWORD, raising=False)
        monkeypatch.delenv(ENV_PASSWORD_HASH, raising=False)

        assert is_auth_enabled() is False

    def test_returns_true_when_plaintext_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that True is returned when plaintext password is configured."""
        monkeypatch.setenv(ENV_PASSWORD, "password")
        monkeypatch.delenv(ENV_PASSWORD_HASH, raising=False)

        assert is_auth_enabled() is True

    def test_returns_true_when_hash_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that True is returned when password hash is configured."""
        monkeypatch.delenv(ENV_PASSWORD, raising=False)
        monkeypatch.setenv(ENV_PASSWORD_HASH, "$2b$12$hash")

        assert is_auth_enabled() is True

    def test_returns_true_when_both_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that True is returned when both are configured."""
        monkeypatch.setenv(ENV_PASSWORD, "password")
        monkeypatch.setenv(ENV_PASSWORD_HASH, "$2b$12$hash")

        assert is_auth_enabled() is True


# =============================================================================
# Test: Exception Classes
# =============================================================================


class TestExceptionClasses:
    """Tests for custom exception classes."""

    def test_authentication_error_is_base(self) -> None:
        """Test that AuthenticationError is the base exception."""
        exc = AuthenticationError("test error")
        assert isinstance(exc, Exception)
        assert str(exc) == "test error"

    def test_password_not_configured_error_default_message(self) -> None:
        """Test PasswordNotConfiguredError default message."""
        exc = PasswordNotConfiguredError()
        message = str(exc)

        assert ENV_PASSWORD in message
        assert ENV_PASSWORD_HASH in message
        assert "not configured" in message.lower()

    def test_password_not_configured_error_custom_message(self) -> None:
        """Test PasswordNotConfiguredError with custom message."""
        custom_msg = "Custom error message"
        exc = PasswordNotConfiguredError(custom_msg)

        assert str(exc) == custom_msg

    def test_password_not_configured_error_inherits_from_auth_error(self) -> None:
        """Test that PasswordNotConfiguredError inherits from AuthenticationError."""
        exc = PasswordNotConfiguredError()
        assert isinstance(exc, AuthenticationError)
        assert isinstance(exc, Exception)

    def test_invalid_password_error_default_message(self) -> None:
        """Test InvalidPasswordError default message."""
        exc = InvalidPasswordError()
        assert str(exc) == "Invalid password"

    def test_invalid_password_error_custom_message(self) -> None:
        """Test InvalidPasswordError with custom message."""
        custom_msg = "Password verification failed"
        exc = InvalidPasswordError(custom_msg)
        assert str(exc) == custom_msg

    def test_invalid_password_error_inherits_from_auth_error(self) -> None:
        """Test that InvalidPasswordError inherits from AuthenticationError."""
        exc = InvalidPasswordError()
        assert isinstance(exc, AuthenticationError)
        assert isinstance(exc, Exception)


# =============================================================================
# Test: Integration Scenarios
# =============================================================================


class TestIntegrationScenarios:
    """Integration tests for realistic usage scenarios."""

    def test_full_bcrypt_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test complete workflow: hash -> store -> retrieve -> verify."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        # 1. User provides password
        original_password = "user_secure_password_123"

        # 2. System hashes it
        hashed = hash_password(original_password)

        # 3. Store hash in environment (simulating production setup)
        monkeypatch.setenv(ENV_PASSWORD_HASH, hashed)
        monkeypatch.delenv(ENV_PASSWORD, raising=False)

        # 4. Later, user provides password for authentication
        assert authenticate(original_password) is True
        assert authenticate("wrong_password") is False

    def test_development_plaintext_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test development workflow with plaintext password."""
        # Development setup - plaintext password
        dev_password = "dev_password_123"
        monkeypatch.setenv(ENV_PASSWORD, dev_password)
        monkeypatch.delenv(ENV_PASSWORD_HASH, raising=False)

        # Authentication should work
        assert is_auth_enabled() is True
        assert authenticate(dev_password) is True
        assert authenticate("wrong") is False

    def test_migration_from_plaintext_to_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test migrating from plaintext to hashed password."""
        if not PASSLIB_AVAILABLE:
            pytest.skip("passlib not available")

        password = "my_password"

        # Start with plaintext
        monkeypatch.setenv(ENV_PASSWORD, password)
        monkeypatch.delenv(ENV_PASSWORD_HASH, raising=False)
        assert authenticate(password) is True

        # Generate hash for production
        hashed = hash_password(password)

        # Switch to hash (both set, but hash takes precedence)
        monkeypatch.setenv(ENV_PASSWORD_HASH, hashed)
        assert authenticate(password) is True

        # Remove plaintext (production setup)
        monkeypatch.delenv(ENV_PASSWORD, raising=False)
        assert authenticate(password) is True

    def test_auth_disabled_scenario(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test scenario where auth is intentionally disabled."""
        monkeypatch.delenv(ENV_PASSWORD, raising=False)
        monkeypatch.delenv(ENV_PASSWORD_HASH, raising=False)

        # Auth is not enabled
        assert is_auth_enabled() is False

        # Attempting to authenticate raises error
        with pytest.raises(PasswordNotConfiguredError):
            authenticate("any_password")
