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
    PasswordNotConfiguredError,
    get_password_from_env,
    hash_password,
    verify_password,
)

__all__ = [
    # Password functions
    "hash_password",
    "verify_password",
    "get_password_from_env",
    # Exceptions
    "AuthenticationError",
    "PasswordNotConfiguredError",
]
