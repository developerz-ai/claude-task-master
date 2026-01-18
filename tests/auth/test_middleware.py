"""Tests for the authentication middleware.

Tests cover:
- Bearer token extraction
- Public path detection
- Middleware authentication flow
- Error responses (401, 403, 500)
- Dependency injection alternative
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from claude_task_master.auth.middleware import (
    PasswordAuthMiddleware,
    extract_bearer_token,
    get_password_auth_dependency,
    is_public_method,
    is_public_path,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# Test: extract_bearer_token
# =============================================================================


class TestExtractBearerToken:
    """Tests for extract_bearer_token function."""

    def test_valid_bearer_token(self) -> None:
        """Test extracting a valid bearer token."""
        assert extract_bearer_token("Bearer my_password") == "my_password"

    def test_bearer_case_insensitive(self) -> None:
        """Test that bearer scheme is case-insensitive."""
        assert extract_bearer_token("bearer my_password") == "my_password"
        assert extract_bearer_token("BEARER my_password") == "my_password"
        assert extract_bearer_token("BeArEr my_password") == "my_password"

    def test_token_with_spaces(self) -> None:
        """Test that token after Bearer can contain spaces."""
        # Only first space is used as delimiter
        assert extract_bearer_token("Bearer token with spaces") == "token with spaces"

    def test_none_header(self) -> None:
        """Test with None header."""
        assert extract_bearer_token(None) is None

    def test_empty_header(self) -> None:
        """Test with empty header."""
        assert extract_bearer_token("") is None

    def test_basic_auth_header(self) -> None:
        """Test that Basic auth is rejected."""
        assert extract_bearer_token("Basic dXNlcjpwYXNz") is None

    def test_only_bearer_no_token(self) -> None:
        """Test with only Bearer scheme, no token."""
        assert extract_bearer_token("Bearer") is None
        assert extract_bearer_token("Bearer ") is None

    def test_malformed_header(self) -> None:
        """Test with malformed headers."""
        assert extract_bearer_token("NotBearer token") is None
        assert extract_bearer_token("just_a_token") is None


# =============================================================================
# Test: is_public_path
# =============================================================================


class TestIsPublicPath:
    """Tests for is_public_path function."""

    def test_root_is_public(self) -> None:
        """Test that root path is public."""
        assert is_public_path("/") is True

    def test_health_endpoints_are_public(self) -> None:
        """Test that health check endpoints are public."""
        assert is_public_path("/health") is True
        assert is_public_path("/healthz") is True
        assert is_public_path("/ready") is True
        assert is_public_path("/livez") is True

    def test_docs_endpoints_are_public(self) -> None:
        """Test that documentation endpoints are public."""
        assert is_public_path("/docs") is True
        assert is_public_path("/redoc") is True
        assert is_public_path("/openapi.json") is True
        # Also paths starting with docs/redoc
        assert is_public_path("/docs/oauth2-redirect") is True
        assert is_public_path("/redoc/") is True

    def test_api_paths_require_auth(self) -> None:
        """Test that API paths require authentication."""
        assert is_public_path("/api/tasks") is False
        assert is_public_path("/api/status") is False
        assert is_public_path("/tasks") is False
        assert is_public_path("/webhooks") is False


# =============================================================================
# Test: is_public_method
# =============================================================================


class TestIsPublicMethod:
    """Tests for is_public_method function."""

    def test_options_is_public(self) -> None:
        """Test that OPTIONS method is public (CORS preflight)."""
        assert is_public_method("OPTIONS") is True
        assert is_public_method("options") is True

    def test_other_methods_require_auth(self) -> None:
        """Test that other methods require authentication."""
        assert is_public_method("GET") is False
        assert is_public_method("POST") is False
        assert is_public_method("PUT") is False
        assert is_public_method("DELETE") is False
        assert is_public_method("PATCH") is False


# =============================================================================
# Test: PasswordAuthMiddleware
# =============================================================================


class TestPasswordAuthMiddleware:
    """Tests for PasswordAuthMiddleware class."""

    @pytest.fixture
    def app_with_auth(self) -> FastAPI:
        """Create a FastAPI app with auth middleware."""
        app = FastAPI()
        app.add_middleware(PasswordAuthMiddleware)

        @app.get("/")
        def root() -> dict[str, str]:
            return {"message": "root"}

        @app.get("/health")
        def health() -> dict[str, str]:
            return {"status": "healthy"}

        @app.get("/api/protected")
        def protected() -> dict[str, str]:
            return {"message": "protected"}

        @app.post("/api/data")
        def post_data() -> dict[str, str]:
            return {"message": "data posted"}

        return app

    @pytest.fixture
    def client(self, app_with_auth: FastAPI) -> TestClient:
        """Create test client for the app."""
        return TestClient(app_with_auth)

    def test_public_path_no_auth_required(self, client: TestClient) -> None:
        """Test that public paths don't require auth."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = client.get("/")
            assert response.status_code == 200

            response = client.get("/health")
            assert response.status_code == 200

    def test_options_request_no_auth_required(self, client: TestClient) -> None:
        """Test that OPTIONS requests don't require auth."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = client.options("/api/protected")
            # OPTIONS might return 405 if not explicitly handled, but shouldn't be 401
            assert response.status_code != 401

    def test_missing_auth_returns_401(self, client: TestClient) -> None:
        """Test that missing Authorization header returns 401."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = client.get("/api/protected")
            assert response.status_code == 401
            assert "WWW-Authenticate" in response.headers
            assert response.headers["WWW-Authenticate"] == "Bearer"
            data = response.json()
            assert data["error"] == "missing_authorization"

    def test_invalid_auth_scheme_returns_401(self, client: TestClient) -> None:
        """Test that non-Bearer auth returns 401."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = client.get("/api/protected", headers={"Authorization": "Basic dXNlcjpwYXNz"})
            assert response.status_code == 401

    def test_invalid_password_returns_403(self, client: TestClient) -> None:
        """Test that invalid password returns 403."""
        with (
            patch("claude_task_master.auth.password.is_auth_enabled", return_value=True),
            patch("claude_task_master.auth.password.authenticate", return_value=False),
        ):
            response = client.get(
                "/api/protected", headers={"Authorization": "Bearer wrong_password"}
            )
            assert response.status_code == 403
            data = response.json()
            assert data["error"] == "invalid_password"

    def test_valid_password_allows_access(self, client: TestClient) -> None:
        """Test that valid password allows access."""
        with (
            patch("claude_task_master.auth.password.is_auth_enabled", return_value=True),
            patch("claude_task_master.auth.password.authenticate", return_value=True),
        ):
            response = client.get(
                "/api/protected", headers={"Authorization": "Bearer correct_password"}
            )
            assert response.status_code == 200
            assert response.json() == {"message": "protected"}

    def test_auth_not_configured_returns_500(self, client: TestClient) -> None:
        """Test that missing auth config returns 500."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=False):
            response = client.get("/api/protected")
            assert response.status_code == 500
            data = response.json()
            assert data["error"] == "config_error"

    def test_auth_disabled_allows_all(self) -> None:
        """Test that auth can be disabled via require_auth=False."""
        app = FastAPI()
        app.add_middleware(PasswordAuthMiddleware, require_auth=False)

        @app.get("/api/protected")
        def protected() -> dict[str, str]:
            return {"message": "protected"}

        client = TestClient(app)
        response = client.get("/api/protected")
        assert response.status_code == 200

    def test_custom_public_paths(self) -> None:
        """Test that custom public paths can be configured."""
        app = FastAPI()
        app.add_middleware(PasswordAuthMiddleware, public_paths={"/", "/custom-public"})

        @app.get("/custom-public")
        def custom() -> dict[str, str]:
            return {"message": "custom"}

        @app.get("/health")
        def health() -> dict[str, str]:
            return {"message": "health"}

        client = TestClient(app)

        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            # Custom path is public
            response = client.get("/custom-public")
            assert response.status_code == 200

            # Default health is no longer public (not in custom set)
            # But is_public_path() still returns True for /health
            # because of the hardcoded check
            response = client.get("/health")
            assert response.status_code == 200  # Still public via is_public_path()


# =============================================================================
# Test: get_password_auth_dependency
# =============================================================================


class TestGetPasswordAuthDependency:
    """Tests for get_password_auth_dependency function."""

    def _create_app_with_dependency(self) -> FastAPI:
        """Create a FastAPI app using dependency-based auth."""
        from fastapi import Depends

        app = FastAPI()
        auth = get_password_auth_dependency()

        @app.get("/")
        def root() -> dict[str, str]:
            return {"message": "root"}

        @app.get("/protected", dependencies=[Depends(auth)])
        def protected() -> dict[str, str]:
            return {"message": "protected"}

        return app

    def test_dependency_missing_auth_raises_401(self) -> None:
        """Test that missing auth raises 401."""
        # Create app inside the patch context so imports happen with mocked values
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            app = self._create_app_with_dependency()
            client = TestClient(app)
            response = client.get("/protected")
            assert response.status_code == 401

    def test_dependency_valid_auth_allows_access(self) -> None:
        """Test that valid auth allows access."""
        with (
            patch("claude_task_master.auth.password.is_auth_enabled", return_value=True),
            patch("claude_task_master.auth.password.authenticate", return_value=True),
        ):
            app = self._create_app_with_dependency()
            client = TestClient(app)
            response = client.get("/protected", headers={"Authorization": "Bearer correct"})
            assert response.status_code == 200

    def test_dependency_public_path_skips_auth(self) -> None:
        """Test that public paths skip auth even with dependency."""
        app = self._create_app_with_dependency()
        client = TestClient(app)
        # Root is a public path but dependency is only on /protected
        response = client.get("/")
        assert response.status_code == 200
