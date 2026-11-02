"""Password hashing and verification utilities for Claude Task Master.

This module provides secure password hashing using the bcrypt package,
along with environment variable configuration and password comparison.

Environment Variables:
    CLAUDETM_PASSWORD: The password for authenticating API/MCP requests.
    CLAUDETM_PASSWORD_HASH: Pre-hashed password (bcrypt) for production use.

Security Notes:
    - Always use CLAUDETM_PASSWORD_HASH in production to avoid plaintext passwords in env
    - Passwords are compared using constant-time comparison to prevent timing attacks
    - bcrypt automatically handles salting and multiple rounds
    - bcrypt cannot represent more than 72 bytes: a longer password is rejected
      rather than silently truncated
"""

from __future__ import annotations

import logging
import os
import secrets

logger = logging.getLogger(__name__)

# Environment variable names
ENV_PASSWORD = "CLAUDETM_PASSWORD"
ENV_PASSWORD_HASH = "CLAUDETM_PASSWORD_HASH"

# =============================================================================
# Exceptions
# =============================================================================


class AuthenticationError(Exception):
    """Base exception for authentication errors."""

    pass


class PasswordNotConfiguredError(AuthenticationError):
    """Raised when password authentication is required but not configured."""

    def __init__(self, message: str | None = None) -> None:
        """Initialize the exception.

        Args:
            message: Optional custom message. Defaults to standard message.
        """
        default_message = (
            f"Password not configured. Set {ENV_PASSWORD} or {ENV_PASSWORD_HASH} "
            "environment variable."
        )
        super().__init__(message or default_message)


class InvalidPasswordError(AuthenticationError):
    """Raised when password verification fails."""

    def __init__(self, message: str = "Invalid password") -> None:
        """Initialize the exception.

        Args:
            message: Custom error message.
        """
        super().__init__(message)


# =============================================================================
# Password Hashing
# =============================================================================

# bcrypt ships with the optional [api] extra, so the import stays guarded:
# the module must import cleanly without it and only hashing/verifying may
# raise ImportError. Nothing here probes a backend at import time.
try:
    import bcrypt

    BCRYPT_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the installed extras
    BCRYPT_AVAILABLE = False

# Cost factor for newly created hashes.
BCRYPT_ROUNDS = 12

# bcrypt cannot represent more than 72 bytes of input. Passwords over that
# limit are rejected instead of being silently truncated: truncation makes
# every password sharing its first 72 bytes interchangeable.
BCRYPT_MAX_PASSWORD_BYTES = 72


def _ensure_bcrypt() -> None:
    """Ensure bcrypt is available, raise ImportError if not.

    Raises:
        ImportError: If the bcrypt package is not installed.
    """
    if not BCRYPT_AVAILABLE:
        raise ImportError(
            "bcrypt not installed. Install with: "
            "pip install 'claude-task-master[api]' or pip install 'bcrypt'"
        )


def _encode_password(password: str) -> bytes:
    """Encode a password as UTF-8 bytes, enforcing bcrypt's 72-byte limit.

    Args:
        password: The plaintext password to encode.

    Returns:
        The UTF-8 encoded password.

    Raises:
        ValueError: If the encoded password exceeds bcrypt's 72-byte limit.
    """
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password cannot be longer than {BCRYPT_MAX_PASSWORD_BYTES} bytes "
            f"when UTF-8 encoded (got {len(encoded)} bytes)"
        )
    return encoded


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.

    Args:
        password: The plaintext password to hash.

    Returns:
        The bcrypt hash of the password ($2b$, cost 12, 60 characters).

    Raises:
        ImportError: If the bcrypt package is not installed.
        ValueError: If password is empty or longer than bcrypt's 72-byte limit.

    Note:
        bcrypt cannot represent more than 72 bytes of input. A password over
        that limit is rejected rather than truncated: truncation would make
        every password sharing the first 72 bytes authenticate.

    Example:
        >>> hashed = hash_password("my_secret_password")
        >>> hashed.startswith("$2b$")  # bcrypt hash format
        True
    """
    _ensure_bcrypt()

    if not password:
        raise ValueError("Password cannot be empty")

    encoded = _encode_password(password)

    hashed = bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a bcrypt hash.

    This function uses constant-time comparison to prevent timing attacks.

    Args:
        plain_password: The plaintext password to verify.
        hashed_password: The bcrypt hash to verify against.

    Returns:
        True if the password matches, False otherwise.

    Raises:
        ImportError: If the bcrypt package is not installed.

    Note:
        bcrypt compares in constant time by design, and the hash format
        ($2a$, $2b$, $2y$) is unchanged, so hashes stored by earlier
        versions keep verifying. A candidate longer than bcrypt's 72-byte
        limit can never match a stored hash and is refused.

    Example:
        >>> hashed = hash_password("my_password")
        >>> verify_password("my_password", hashed)
        True
        >>> verify_password("wrong_password", hashed)
        False
    """
    _ensure_bcrypt()

    if not plain_password or not hashed_password:
        return False

    try:
        encoded = _encode_password(plain_password)
    except ValueError:
        logger.warning(
            "Refusing to verify a password longer than %d bytes: bcrypt cannot "
            "represent it, so it can never match a stored hash.",
            BCRYPT_MAX_PASSWORD_BYTES,
        )
        return False

    try:
        return bcrypt.checkpw(encoded, hashed_password.encode("utf-8"))
    except Exception:
        # Any exception during verification means the password is invalid
        # This includes malformed hashes
        return False


def verify_password_plaintext(plain_password: str, expected_password: str) -> bool:
    """Verify a password against a plaintext expected password.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        plain_password: The password to verify.
        expected_password: The expected plaintext password.

    Returns:
        True if passwords match, False otherwise.
    """
    if not plain_password or not expected_password:
        return False

    # Compare UTF-8 bytes for consistent handling of non-ASCII characters
    return secrets.compare_digest(
        plain_password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )


# =============================================================================
# Environment Configuration
# =============================================================================


def get_password_from_env() -> str | None:
    """Get the configured password from environment variables.

    Checks for password configuration in order of preference:
    1. CLAUDETM_PASSWORD_HASH - pre-hashed bcrypt password (recommended for production)
    2. CLAUDETM_PASSWORD - plaintext password (for development/testing)

    Returns:
        The configured password (plaintext) or password hash, or None if not configured.

    Note:
        When CLAUDETM_PASSWORD is set, it returns the plaintext password.
        When CLAUDETM_PASSWORD_HASH is set, it returns the hash.
        The caller should use is_password_hash() to determine which type was returned.
    """
    # First check for pre-hashed password (production)
    password_hash = os.getenv(ENV_PASSWORD_HASH)
    if password_hash:
        return password_hash

    # Fall back to plaintext password (development)
    password = os.getenv(ENV_PASSWORD)
    if password:
        return password

    return None


def is_password_hash(value: str) -> bool:
    """Check if a value appears to be a bcrypt hash.

    Args:
        value: The value to check.

    Returns:
        True if the value looks like a bcrypt hash, False otherwise.
    """
    if not value:
        return False

    # bcrypt hashes start with $2a$, $2b$, or $2y$ followed by cost factor
    return value.startswith(("$2a$", "$2b$", "$2y$"))


def require_password_from_env() -> str:
    """Get the configured password, raising an error if not configured.

    Returns:
        The configured password or password hash.

    Raises:
        PasswordNotConfiguredError: If no password is configured.
    """
    password = get_password_from_env()
    if password is None:
        raise PasswordNotConfiguredError()
    return password


def authenticate(provided_password: str) -> bool:
    """Authenticate a provided password against the configured password.

    This function handles both plaintext and hashed password configurations:
    - If CLAUDETM_PASSWORD_HASH is set, verifies against the hash
    - If CLAUDETM_PASSWORD is set, compares plaintext (constant-time)

    Args:
        provided_password: The password to authenticate.

    Returns:
        True if authentication succeeds, False otherwise.

    Raises:
        PasswordNotConfiguredError: If no password is configured.
    """
    configured = require_password_from_env()

    if is_password_hash(configured):
        # Verify against bcrypt hash
        return verify_password(provided_password, configured)
    else:
        # Compare plaintext (constant-time)
        return verify_password_plaintext(provided_password, configured)


def is_auth_enabled() -> bool:
    """Check if password authentication is enabled.

    Returns:
        True if a password is configured, False otherwise.
    """
    return get_password_from_env() is not None
