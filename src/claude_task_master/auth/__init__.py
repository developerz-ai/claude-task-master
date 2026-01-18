"""Authentication module for Claude Task Master.

This module provides shared password-based authentication for REST API, MCP server,
and webhook authentication. It uses passlib with bcrypt for secure password hashing.

Key Components:
- Password hashing and verification using bcrypt
- Environment variable based password configuration
- FastAPI middleware for password-based authentication
- MCP transport authentication handlers

Usage:
    from claude_task_master.auth import verify_password, hash_password, get_password_from_env

    # Verify a password against a hash
    if verify_password(password, hashed):
        grant_access()

    # Get password from environment
    password = get_password_from_env()

    # Use middleware for FastAPI
    from claude_task_master.auth import PasswordAuthMiddleware
    app.add_middleware(PasswordAuthMiddleware)

Example:
    >>> from claude_task_master.auth import hash_password, verify_password
    >>> hashed = hash_password("my_secret")
    >>> verify_password("my_secret", hashed)
    True
    >>> verify_password("wrong_password", hashed)
    False
"""

from claude_task_master.auth.password import (
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

# Middleware imports - only available with [api] extra
try:
    from claude_task_master.auth.middleware import (
        PasswordAuthMiddleware,
        extract_bearer_token,
        get_password_auth_dependency,
        is_public_method,
        is_public_path,
    )

    _MIDDLEWARE_AVAILABLE = True
except ImportError:
    _MIDDLEWARE_AVAILABLE = False
    # Define placeholders for type hints
    PasswordAuthMiddleware = None  # type: ignore[assignment,misc]
    extract_bearer_token = None  # type: ignore[assignment]
    get_password_auth_dependency = None  # type: ignore[assignment]
    is_public_path = None  # type: ignore[assignment]
    is_public_method = None  # type: ignore[assignment]

__all__ = [
    # Password functions
    "hash_password",
    "verify_password",
    "verify_password_plaintext",
    "get_password_from_env",
    "require_password_from_env",
    "is_password_hash",
    "authenticate",
    "is_auth_enabled",
    # Exceptions
    "AuthenticationError",
    "InvalidPasswordError",
    "PasswordNotConfiguredError",
    # Middleware (requires [api] extra)
    "PasswordAuthMiddleware",
    "extract_bearer_token",
    "get_password_auth_dependency",
    "is_public_path",
    "is_public_method",
]
