"""Tests for MCP authentication module.

Tests cover:
- Authentication middleware application for MCP apps
- Transport-specific authentication requirements
- Authentication configuration checking
- Public path configuration for MCP
- Integration with password authentication
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from claude_task_master.mcp.auth import (
    MCP_PUBLIC_PATHS,
    add_auth_middleware,
    check_auth_config,
    is_auth_required_for_transport,
)

if TYPE_CHECKING:
    pass

# Skip all tests if Starlette is not available (required for middleware)
try:
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    STARLETTE_AVAILABLE = True
except ImportError:
    STARLETTE_AVAILABLE = False

pytestmark = pytest.mark.skipif(not STARLETTE_AVAILABLE, reason="Starlette not installed")


# =============================================================================
# Test: MCP_PUBLIC_PATHS constant
# =============================================================================


class TestMCPPublicPaths:
    """Tests for MCP_PUBLIC_PATHS constant."""

    def test_public_paths_contains_health_endpoints(self) -> None:
        """Test that public paths include standard health endpoints."""
        assert "/health" in MCP_PUBLIC_PATHS
        assert "/healthz" in MCP_PUBLIC_PATHS
        assert "/ready" in MCP_PUBLIC_PATHS
        assert "/livez" in MCP_PUBLIC_PATHS

    def test_public_paths_is_frozen(self) -> None:
        """Test that MCP_PUBLIC_PATHS is a frozenset."""
        assert isinstance(MCP_PUBLIC_PATHS, frozenset)


# =============================================================================
# Test: is_auth_required_for_transport
# =============================================================================


class TestIsAuthRequiredForTransport:
    """Tests for is_auth_required_for_transport function."""

    def test_stdio_does_not_require_auth(self) -> None:
        """Test that stdio transport doesn't require authentication."""
        assert is_auth_required_for_transport("stdio") is False
        assert is_auth_required_for_transport("STDIO") is False

    def test_sse_requires_auth(self) -> None:
        """Test that SSE transport requires authentication."""
        assert is_auth_required_for_transport("sse") is True
        assert is_auth_required_for_transport("SSE") is True

    def test_streamable_http_requires_auth(self) -> None:
        """Test that streamable-http transport requires authentication."""
        assert is_auth_required_for_transport("streamable-http") is True
        assert is_auth_required_for_transport("STREAMABLE-HTTP") is True

    def test_unknown_transport_does_not_require_auth(self) -> None:
        """Test that unknown transports don't require auth by default."""
        assert is_auth_required_for_transport("unknown") is False
        assert is_auth_required_for_transport("websocket") is False


# =============================================================================
# Test: check_auth_config
# =============================================================================


class TestCheckAuthConfig:
    """Tests for check_auth_config function."""

    def test_stdio_returns_no_auth_no_warning(self) -> None:
        """Test that stdio transport returns auth disabled without warning."""
        auth_enabled, warning = check_auth_config("stdio", "127.0.0.1")
        assert auth_enabled is False
        assert warning is None

    def test_sse_localhost_without_auth_returns_warning(self) -> None:
        """Test that SSE on localhost without auth returns acceptable warning."""
        with patch("claude_task_master.auth.is_auth_enabled", return_value=False):
            auth_enabled, warning = check_auth_config("sse", "127.0.0.1")
            assert auth_enabled is False
            assert warning is not None
            assert "acceptable for localhost" in warning.lower()
            assert "CLAUDETM_PASSWORD" in warning

    def test_sse_localhost_with_auth_returns_no_warning(self) -> None:
        """Test that SSE on localhost with auth returns no warning."""
        with patch("claude_task_master.auth.is_auth_enabled", return_value=True):
            auth_enabled, warning = check_auth_config("sse", "127.0.0.1")
            assert auth_enabled is True
            assert warning is None

    def test_sse_non_localhost_without_auth_returns_security_warning(self) -> None:
        """Test that SSE on non-localhost without auth returns security warning."""
        with patch("claude_task_master.auth.is_auth_enabled", return_value=False):
            auth_enabled, warning = check_auth_config("sse", "0.0.0.0")
            assert auth_enabled is False
            assert warning is not None
            assert "security risk" in warning.lower()
            assert "0.0.0.0" in warning

    def test_sse_non_localhost_with_auth_returns_no_warning(self) -> None:
        """Test that SSE on non-localhost with auth returns no warning."""
        with patch("claude_task_master.auth.is_auth_enabled", return_value=True):
            auth_enabled, warning = check_auth_config("sse", "0.0.0.0")
            assert auth_enabled is True
            assert warning is None

    def test_localhost_variations(self) -> None:
        """Test that different localhost representations are recognized."""
        localhost_addresses = ["127.0.0.1", "localhost", "::1"]
        with patch("claude_task_master.auth.is_auth_enabled", return_value=False):
            for host in localhost_addresses:
                auth_enabled, warning = check_auth_config("sse", host)
                assert auth_enabled is False
                assert warning is not None
                assert "acceptable for localhost" in warning.lower()

    def test_streamable_http_follows_same_rules(self) -> None:
        """Test that streamable-http follows same rules as SSE."""
        with patch("claude_task_master.auth.is_auth_enabled", return_value=False):
            # Localhost - acceptable warning
            auth_enabled, warning = check_auth_config("streamable-http", "127.0.0.1")
            assert auth_enabled is False
            assert warning is not None
            assert "acceptable for localhost" in warning.lower()

            # Non-localhost - security warning
            auth_enabled, warning = check_auth_config("streamable-http", "192.168.1.100")
            assert auth_enabled is False
            assert warning is not None
            assert "security risk" in warning.lower()


# =============================================================================
# Test: add_auth_middleware
# =============================================================================


class TestAddAuthMiddleware:
    """Tests for add_auth_middleware function."""

    @pytest.fixture
    def mock_app(self) -> MagicMock:
        """Create a mock Starlette app."""
        app = MagicMock(spec=Starlette)
        app.add_middleware = MagicMock()
        return app

    def test_adds_middleware_to_app(self, mock_app: MagicMock) -> None:
        """Test that middleware is added to the app."""
        result = add_auth_middleware(mock_app)

        # Should call add_middleware
        assert mock_app.add_middleware.called
        # Should return the same app
        assert result is mock_app

    def test_uses_default_public_paths(self, mock_app: MagicMock) -> None:
        """Test that default MCP public paths are used."""
        add_auth_middleware(mock_app)

        # Check that middleware was called with default paths
        mock_app.add_middleware.assert_called_once()
        call_kwargs = mock_app.add_middleware.call_args[1]
        assert "public_paths" in call_kwargs
        assert call_kwargs["public_paths"] == MCP_PUBLIC_PATHS

    def test_accepts_custom_public_paths(self, mock_app: MagicMock) -> None:
        """Test that custom public paths can be provided."""
        custom_paths = frozenset({"/custom", "/other"})
        add_auth_middleware(mock_app, public_paths=custom_paths)

        # Check that custom paths were used
        call_kwargs = mock_app.add_middleware.call_args[1]
        assert call_kwargs["public_paths"] == custom_paths

    def test_middleware_class_is_imported_correctly(self, mock_app: MagicMock) -> None:
        """Test that PasswordAuthMiddleware is properly imported and used."""
        # Verify that the middleware is added with the correct class
        add_auth_middleware(mock_app)

        # Get the middleware class that was added
        call_args = mock_app.add_middleware.call_args
        middleware_class = call_args[0][0]

        # Verify it's the PasswordAuthMiddleware
        from claude_task_master.auth.middleware import PasswordAuthMiddleware

        assert middleware_class is PasswordAuthMiddleware

    def test_empty_public_paths_accepted(self, mock_app: MagicMock) -> None:
        """Test that empty public paths frozenset is accepted."""
        empty_paths: frozenset[str] = frozenset()
        add_auth_middleware(mock_app, public_paths=empty_paths)

        call_kwargs = mock_app.add_middleware.call_args[1]
        assert call_kwargs["public_paths"] == empty_paths


# =============================================================================
# Test: Integration with Starlette
# =============================================================================


class TestAuthMiddlewareIntegration:
    """Integration tests for auth middleware with Starlette apps."""

    @pytest.fixture
    def starlette_app(self) -> Starlette:
        """Create a real Starlette app for testing."""
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        async def health(request):
            return JSONResponse({"status": "healthy"})

        async def protected(request):
            return JSONResponse({"message": "protected"})

        routes = [
            Route("/health", health),
            Route("/protected", protected),
        ]

        return Starlette(routes=routes)

    def test_middleware_applied_to_real_app(self, starlette_app: Starlette) -> None:
        """Test that middleware can be applied to a real Starlette app."""
        # This should not raise
        app_with_auth = add_auth_middleware(starlette_app)
        assert app_with_auth is starlette_app

        # Check that middleware was added
        # Starlette stores middleware in app.middleware_stack
        assert len(starlette_app.user_middleware) > 0

    def test_public_path_accessible_without_auth(self, starlette_app: Starlette) -> None:
        """Test that public paths are accessible without authentication."""
        app_with_auth = add_auth_middleware(starlette_app)

        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            client = TestClient(app_with_auth)
            response = client.get("/health")
            # Health endpoint should be accessible (public path)
            assert response.status_code == 200

    def test_protected_path_requires_auth(self, starlette_app: Starlette) -> None:
        """Test that protected paths require authentication."""
        app_with_auth = add_auth_middleware(starlette_app)

        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            client = TestClient(app_with_auth)
            response = client.get("/protected")
            # Should return 401 without auth header
            assert response.status_code == 401

    def test_protected_path_with_valid_auth(self, starlette_app: Starlette) -> None:
        """Test that protected paths work with valid authentication."""
        app_with_auth = add_auth_middleware(starlette_app)

        with (
            patch("claude_task_master.auth.password.is_auth_enabled", return_value=True),
            patch("claude_task_master.auth.password.authenticate", return_value=True),
        ):
            client = TestClient(app_with_auth)
            response = client.get("/protected", headers={"Authorization": "Bearer valid_token"})
            # Should be accessible with valid auth
            assert response.status_code == 200
            assert response.json() == {"message": "protected"}

    def test_protected_path_with_invalid_auth(self, starlette_app: Starlette) -> None:
        """Test that protected paths reject invalid authentication."""
        app_with_auth = add_auth_middleware(starlette_app)

        with (
            patch("claude_task_master.auth.password.is_auth_enabled", return_value=True),
            patch("claude_task_master.auth.password.authenticate", return_value=False),
        ):
            client = TestClient(app_with_auth)
            response = client.get("/protected", headers={"Authorization": "Bearer invalid_token"})
            # Should return 403 with invalid auth
            assert response.status_code == 403


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestAuthEdgeCases:
    """Tests for edge cases in MCP auth module."""

    def test_none_public_paths_uses_default(self) -> None:
        """Test that None public_paths parameter uses default."""
        app = MagicMock(spec=Starlette)
        add_auth_middleware(app, public_paths=None)

        call_kwargs = app.add_middleware.call_args[1]
        assert call_kwargs["public_paths"] == MCP_PUBLIC_PATHS

    def test_check_auth_config_with_empty_host(self) -> None:
        """Test check_auth_config with empty host string."""
        with patch("claude_task_master.auth.is_auth_enabled", return_value=False):
            auth_enabled, warning = check_auth_config("sse", "")
            # Empty host is not localhost, should get security warning
            assert auth_enabled is False
            assert warning is not None
            assert "security risk" in warning.lower()

    def test_transport_case_insensitivity(self) -> None:
        """Test that transport checking is case-insensitive."""
        # Mixed case variants
        assert is_auth_required_for_transport("Sse") is True
        assert is_auth_required_for_transport("StDiO") is False
        assert is_auth_required_for_transport("Streamable-HTTP") is True
