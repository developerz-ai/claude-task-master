"""Password hashing and verification utilities for Claude Task Master.

This module provides secure password hashing using bcrypt via passlib,
along with environment variable configuration and password comparison.

Environment Variables:
    CLAUDETM_PASSWORD: The password for authenticating API/MCP requests.
    CLAUDETM_PASSWORD_HASH: Pre-hashed password (bcrypt) for production use.

Security Notes:
    - Always use CLAUDETM_PASSWORD_HASH in production to avoid plaintext passwords in env
    - Passwords are compared using constant-time comparison to prevent timing attacks
    - bcrypt automatically handles salting and multiple rounds
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

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

# Try to import passlib for bcrypt hashing
try:
    from passlib.context import CryptContext

    # Create a bcrypt context for password hashing
    # Using bcrypt with default rounds (12) for security
    _pwd_context: CryptContext | None = CryptContext(
        schemes=["bcrypt"],
        deprecated="auto",
        bcrypt__rounds=12,
    )
    PASSLIB_AVAILABLE = True
except ImportError:
    _pwd_context = None
    PASSLIB_AVAILABLE = False


def _ensure_passlib() -> None:
    """Ensure passlib is available, raise ImportError if not.

    Raises:
        ImportError: If passlib[bcrypt] is not installed.
    """
    if not PASSLIB_AVAILABLE:
        raise ImportError(
            "passlib[bcrypt] not installed. Install with: "
            "pip install 'claude-task-master[api]' or pip install 'passlib[bcrypt]'"
        )


def _truncate_password_for_bcrypt(password: str) -> str:
    """Truncate password to bcrypt's 72-byte limit.

    bcrypt has a fundamental 72-byte password limit. Passwords longer than
    72 bytes (when UTF-8 encoded) must be truncated. This is done at a
    character boundary to avoid breaking multi-byte characters.

    Args:
        password: The password to potentially truncate.

    Returns:
        The password truncated to at most 72 bytes when UTF-8 encoded.
    """
    # Encode to bytes to check actual byte length
    encoded = password.encode("utf-8")
    if len(encoded) <= 72:
        return password

    # Truncate at byte boundary, then decode
    # We need to be careful not to break a multi-byte character
    truncated = encoded[:72]
    # Find the last complete character by decoding with error handling
    # If truncation breaks a multi-byte character, we need to go back
    while True:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
            if not truncated:
                # This shouldn't happen with valid UTF-8 input
                return password[:72]


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.

    Args:
        password: The plaintext password to hash.

    Returns:
        The bcrypt hash of the password.

    Raises:
        ImportError: If passlib[bcrypt] is not installed.
        ValueError: If password is empty.

    Note:
        bcrypt has a 72-byte password limit. Passwords longer than 72 bytes
        (when UTF-8 encoded) will be truncated. This is a bcrypt limitation,
        not a security concern for most use cases.

    Example:
        >>> hashed = hash_password("my_secret_password")
        >>> hashed.startswith("$2b$")  # bcrypt hash format
        True
    """
    _ensure_passlib()

    if not password:
        raise ValueError("Password cannot be empty")

    # Truncate to bcrypt's 72-byte limit
    password = _truncate_password_for_bcrypt(password)

    assert _pwd_context is not None  # ensured by _ensure_passlib
    result: str = _pwd_context.hash(password)
    return result


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a bcrypt hash.

    This function uses constant-time comparison to prevent timing attacks.

    Args:
        plain_password: The plaintext password to verify.
        hashed_password: The bcrypt hash to verify against.

    Returns:
        True if the password matches, False otherwise.

    Raises:
        ImportError: If passlib[bcrypt] is not installed.

    Note:
        bcrypt has a 72-byte password limit. Passwords are truncated to
        match the behavior during hashing.

    Example:
        >>> hashed = hash_password("my_password")
        >>> verify_password("my_password", hashed)
        True
        >>> verify_password("wrong_password", hashed)
        False
    """
    _ensure_passlib()

    if not plain_password or not hashed_password:
        return False

    try:
        # Truncate to bcrypt's 72-byte limit (must match hash_password behavior)
        plain_password = _truncate_password_for_bcrypt(plain_password)

        assert _pwd_context is not None  # ensured by _ensure_passlib
        result: bool = _pwd_context.verify(plain_password, hashed_password)
        return result
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

    return secrets.compare_digest(plain_password, expected_password)


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
