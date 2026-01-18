"""FastAPI middleware for password authentication.

This module provides HTTP middleware that enforces password-based authentication
using the Authorization: Bearer <password> header format.

The middleware:
- Validates Authorization headers on protected endpoints
- Skips authentication for health/info endpoints and OPTIONS requests
- Supports both plaintext and bcrypt-hashed passwords via environment config
- Returns proper 401/403 responses for authentication failures

Usage:
    from fastapi import FastAPI
    from claude_task_master.auth.middleware import PasswordAuthMiddleware

    app = FastAPI()
    app.add_middleware(PasswordAuthMiddleware)

Environment Variables:
    CLAUDETM_PASSWORD: Plaintext password for authentication (development)
    CLAUDETM_PASSWORD_HASH: Bcrypt hash for authentication (production)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

# Try to import Starlette/FastAPI components
try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

    STARLETTE_AVAILABLE = True
except ImportError:
    STARLETTE_AVAILABLE = False
    # Define placeholders for type hints when Starlette isn't available
    BaseHTTPMiddleware = object  # type: ignore[assignment,misc]
    Request = object  # type: ignore[assignment,misc]
    Response = object  # type: ignore[assignment,misc]
    JSONResponse = object  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Paths that don't require authentication
# These are typically health checks, info endpoints, and CORS preflight
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/",  # API info
        "/health",  # Health check
        "/healthz",  # Alternative health check
        "/ready",  # Readiness probe
        "/livez",  # Liveness probe
        "/docs",  # OpenAPI docs
        "/redoc",  # ReDoc docs
        "/openapi.json",  # OpenAPI schema
    }
)

# HTTP methods that don't require authentication
PUBLIC_METHODS: frozenset[str] = frozenset(
    {
        "OPTIONS",  # CORS preflight
    }
)


# =============================================================================
# Helper Functions
# =============================================================================


def _ensure_starlette() -> None:
    """Ensure Starlette is available, raise ImportError if not.

    Raises:
        ImportError: If Starlette/FastAPI is not installed.
    """
    if not STARLETTE_AVAILABLE:
        raise ImportError(
            "Starlette/FastAPI not installed. Install with: pip install 'claude-task-master[api]'"
        )


def extract_bearer_token(authorization: str | None) -> str | None:
    """Extract Bearer token from Authorization header.

    Args:
        authorization: The Authorization header value.

    Returns:
        The token if present and valid format, None otherwise.

    Example:
        >>> extract_bearer_token("Bearer my_password")
        'my_password'
        >>> extract_bearer_token("Basic xyz")
        None
        >>> extract_bearer_token(None)
        None
    """
    if not authorization:
        return None

    parts = authorization.split(None, 1)  # Split on whitespace, max 2 parts
    if len(parts) != 2:
        return None

    scheme, token = parts
    if scheme.lower() != "bearer":
        return None

    return token


def is_public_path(path: str) -> bool:
    """Check if a path is public (no auth required).

    Args:
        path: The request path.

    Returns:
        True if the path is public, False otherwise.

    Example:
        >>> is_public_path("/health")
        True
        >>> is_public_path("/api/tasks")
        False
    """
    # Exact match
    if path in PUBLIC_PATHS:
        return True

    # Check path prefixes for docs
    if path.startswith("/docs") or path.startswith("/redoc"):
        return True

    return False


def is_public_method(method: str) -> bool:
    """Check if an HTTP method is public (no auth required).

    Args:
        method: The HTTP method (GET, POST, etc.).

    Returns:
        True if the method is public, False otherwise.

    Example:
        >>> is_public_method("OPTIONS")
        True
        >>> is_public_method("POST")
        False
    """
    return method.upper() in PUBLIC_METHODS


# =============================================================================
# Authentication Response Helpers
# =============================================================================


def _create_401_response() -> JSONResponse:
    """Create a 401 Unauthorized response.

    Returns:
        JSONResponse with 401 status and WWW-Authenticate header.
    """
    _ensure_starlette()
    return JSONResponse(
        status_code=401,
        content={
            "detail": "Not authenticated",
            "error": "missing_authorization",
            "message": "Authorization header required. Use: Authorization: Bearer <password>",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def _create_403_response() -> JSONResponse:
    """Create a 403 Forbidden response.

    Returns:
        JSONResponse with 403 status.
    """
    _ensure_starlette()
    return JSONResponse(
        status_code=403,
        content={
            "detail": "Invalid credentials",
            "error": "invalid_password",
            "message": "The provided password is incorrect",
        },
    )


def _create_500_response(message: str) -> JSONResponse:
    """Create a 500 Internal Server Error response.

    Args:
        message: Error message to include.

    Returns:
        JSONResponse with 500 status.
    """
    _ensure_starlette()
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Authentication configuration error",
            "error": "config_error",
            "message": message,
        },
    )


# =============================================================================
# Middleware Class
# =============================================================================


class PasswordAuthMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware for password-based authentication.

    This middleware enforces authentication using the Authorization: Bearer <password>
    header. It validates passwords against the configured environment variables
    (CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH).

    Attributes:
        public_paths: Set of paths that don't require authentication.
        public_methods: Set of HTTP methods that don't require authentication.
        require_auth: Whether to require authentication (can be disabled for testing).

    Example:
        from fastapi import FastAPI
        from claude_task_master.auth.middleware import PasswordAuthMiddleware

        app = FastAPI()
        app.add_middleware(PasswordAuthMiddleware)

        # Or with custom public paths:
        app.add_middleware(
            PasswordAuthMiddleware,
            public_paths={"/", "/health", "/custom-public"},
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        public_paths: set[str] | frozenset[str] | None = None,
        public_methods: set[str] | frozenset[str] | None = None,
        require_auth: bool = True,
    ) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application to wrap.
            public_paths: Set of paths that don't require auth. Defaults to PUBLIC_PATHS.
            public_methods: Set of methods that don't require auth. Defaults to PUBLIC_METHODS.
            require_auth: Whether to require authentication. Set to False to disable.
        """
        _ensure_starlette()
        super().__init__(app)

        self.public_paths = frozenset(public_paths) if public_paths else PUBLIC_PATHS
        self.public_methods = frozenset(public_methods) if public_methods else PUBLIC_METHODS
        self.require_auth = require_auth

        logger.debug(
            f"PasswordAuthMiddleware initialized: require_auth={require_auth}, "
            f"public_paths={len(self.public_paths)}"
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process the request and enforce authentication.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware/handler in the chain.

        Returns:
            The response from the next handler, or an error response if auth fails.
        """
        # Skip auth if disabled
        if not self.require_auth:
            return await call_next(request)

        # Skip auth for public methods (OPTIONS for CORS)
        if request.method.upper() in self.public_methods:
            return await call_next(request)

        # Skip auth for public paths
        path = request.url.path
        if path in self.public_paths or is_public_path(path):
            return await call_next(request)

        # Import auth functions here to avoid circular imports
        from claude_task_master.auth.password import (
            PasswordNotConfiguredError,
            authenticate,
            is_auth_enabled,
        )

        # Check if auth is configured
        if not is_auth_enabled():
            # No password configured - this is a configuration error
            # Log warning and reject the request
            logger.warning(
                "Authentication required but no password configured. "
                "Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH."
            )
            return _create_500_response(
                "Authentication required but not configured. "
                "Set CLAUDETM_PASSWORD or CLAUDETM_PASSWORD_HASH environment variable."
            )

        # Extract Bearer token from Authorization header
        auth_header = request.headers.get("Authorization")
        token = extract_bearer_token(auth_header)

        if not token:
            logger.debug(f"Missing or invalid Authorization header for {request.method} {path}")
            return _create_401_response()

        # Verify the password
        try:
            if not authenticate(token):
                logger.warning(f"Invalid password attempt for {request.method} {path}")
                return _create_403_response()
        except PasswordNotConfiguredError:
            # Should not happen since we checked is_auth_enabled(), but handle it
            logger.error("Password configuration error during authentication")
            return _create_500_response("Authentication configuration error")
        except Exception as e:
            # Unexpected error during authentication
            logger.exception(f"Unexpected error during authentication: {e}")
            return _create_500_response("Internal authentication error")

        # Authentication successful - proceed to next handler
        logger.debug(f"Authentication successful for {request.method} {path}")
        return await call_next(request)


# =============================================================================
# Dependency Injection Alternative
# =============================================================================


def get_password_auth_dependency(
    public_paths: set[str] | frozenset[str] | None = None,
) -> Callable[..., None]:
    """Create a FastAPI dependency for password authentication.

    This is an alternative to using middleware, useful when you want more
    granular control over which endpoints require authentication.

    Args:
        public_paths: Set of paths that don't require authentication.

    Returns:
        A FastAPI dependency function.

    Example:
        from fastapi import FastAPI, Depends
        from claude_task_master.auth.middleware import get_password_auth_dependency

        app = FastAPI()
        auth = get_password_auth_dependency()

        @app.get("/protected", dependencies=[Depends(auth)])
        def protected_endpoint():
            return {"message": "authenticated"}
    """
    _ensure_starlette()

    from fastapi import HTTPException

    from claude_task_master.auth.password import (
        PasswordNotConfiguredError,
        authenticate,
        is_auth_enabled,
    )

    paths = frozenset(public_paths) if public_paths else PUBLIC_PATHS

    def verify_auth(request: Request) -> None:
        """Verify authentication for the request.

        Args:
            request: The incoming HTTP request.

        Raises:
            HTTPException: If authentication fails.
        """
        # Skip auth for public paths
        if request.url.path in paths or is_public_path(request.url.path):
            return

        # Check if auth is configured
        if not is_auth_enabled():
            raise HTTPException(
                status_code=500,
                detail="Authentication required but not configured",
            )

        # Extract and verify token
        auth_header = request.headers.get("Authorization")
        token = extract_bearer_token(auth_header)

        if not token:
            raise HTTPException(
                status_code=401,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            if not authenticate(token):
                raise HTTPException(
                    status_code=403,
                    detail="Invalid credentials",
                )
        except PasswordNotConfiguredError as err:
            raise HTTPException(
                status_code=500,
                detail="Authentication configuration error",
            ) from err

    return verify_auth
