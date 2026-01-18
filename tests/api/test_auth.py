"""Tests for API authentication integration.

Tests cover:
- Health endpoint accessibility without authentication
- Protected endpoints requiring authentication
- CORS preflight handling with auth
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from claude_task_master.api.routes import register_routes
from claude_task_master.api.server import lifespan

# Skip all tests if FastAPI is not installed
try:
    from claude_task_master.auth.middleware import PasswordAuthMiddleware

    MIDDLEWARE_AVAILABLE = True
except ImportError:
    MIDDLEWARE_AVAILABLE = False

pytestmark = pytest.mark.skipif(not MIDDLEWARE_AVAILABLE, reason="Auth middleware not available")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def auth_app(temp_dir: Path) -> FastAPI:
    """Create a FastAPI app with auth middleware enabled."""
    app = FastAPI(lifespan=lifespan)
    app.state.working_dir = temp_dir

    # Add auth middleware
    app.add_middleware(PasswordAuthMiddleware)

    # Register all routes
    register_routes(app)

    return app


@pytest.fixture
def auth_client(auth_app: FastAPI):
    """Create test client for app with auth enabled."""
    with TestClient(auth_app) as client:
        yield client


@pytest.fixture
def state_dir(temp_dir: Path) -> Path:
    """Create state directory with basic state."""
    state_dir = temp_dir / ".claude-task-master"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture
def state_file(state_dir: Path) -> Path:
    """Create a valid state file."""
    state_file = state_dir / "state.json"
    timestamp = datetime.now().isoformat()
    state_data = {
        "status": "working",
        "workflow_stage": None,
        "current_task_index": 0,
        "session_count": 1,
        "current_pr": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_id": "20250118-120000",
        "model": "sonnet",
        "options": {
            "auto_merge": True,
            "max_sessions": 10,
            "pause_on_pr": False,
            "enable_checkpointing": False,
            "log_level": "normal",
            "log_format": "text",
            "pr_per_task": False,
        },
    }
    state_file.write_text(json.dumps(state_data))
    return state_file


@pytest.fixture
def goal_file(state_dir: Path) -> Path:
    """Create a goal file."""
    goal_file = state_dir / "goal.txt"
    goal_file.write_text("Test goal for auth tests")
    return goal_file


# =============================================================================
# Test: Health Endpoint Without Auth
# =============================================================================


class TestHealthEndpointNoAuth:
    """Tests for health endpoint accessibility without authentication."""

    def test_health_endpoint_accessible_without_auth(self, auth_client: TestClient) -> None:
        """Test that /health endpoint works without Authorization header.

        This is critical for load balancers and monitoring systems that need
        to check health without providing credentials.
        """
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = auth_client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "version" in data
            assert "server_name" in data

    def test_health_endpoint_accessible_when_auth_not_configured(
        self, auth_client: TestClient
    ) -> None:
        """Test that /health works even when auth is not configured.

        When CLAUDETM_PASSWORD is not set, health should still work.
        """
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=False):
            response = auth_client.get("/health")

            # Should succeed even though auth is not configured
            # (health is public path, auth check is skipped before is_auth_enabled)
            assert response.status_code == 200

    def test_health_returns_degraded_for_blocked_task(
        self, auth_client: TestClient, state_file: Path, goal_file: Path
    ) -> None:
        """Test that /health returns degraded when task is blocked."""
        # Update state to blocked
        timestamp = datetime.now().isoformat()
        state_data = {
            "status": "blocked",
            "workflow_stage": None,
            "current_task_index": 0,
            "session_count": 1,
            "current_pr": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_id": "20250118-120000",
            "model": "sonnet",
            "options": {
                "auto_merge": True,
                "max_sessions": 10,
                "pause_on_pr": False,
                "enable_checkpointing": False,
                "log_level": "normal",
                "log_format": "text",
                "pr_per_task": False,
            },
        }
        state_file.write_text(json.dumps(state_data))

        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = auth_client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"


# =============================================================================
# Test: Protected Endpoints Require Auth
# =============================================================================


class TestProtectedEndpointsRequireAuth:
    """Tests for endpoints that require authentication."""

    def test_status_endpoint_requires_auth(
        self, auth_client: TestClient, state_file: Path, goal_file: Path
    ) -> None:
        """Test that /status endpoint returns 401 without auth."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = auth_client.get("/status")

            assert response.status_code == 401
            assert "WWW-Authenticate" in response.headers
            assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_plan_endpoint_requires_auth(
        self, auth_client: TestClient, state_file: Path, goal_file: Path
    ) -> None:
        """Test that /plan endpoint returns 401 without auth."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = auth_client.get("/plan")

            assert response.status_code == 401

    def test_control_stop_requires_auth(self, auth_client: TestClient) -> None:
        """Test that /control/stop endpoint returns 401 without auth."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = auth_client.post("/control/stop", json={})

            assert response.status_code == 401

    def test_task_init_requires_auth(self, auth_client: TestClient) -> None:
        """Test that /task/init endpoint returns 401 without auth."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = auth_client.post(
                "/task/init",
                json={"goal": "Test task", "model": "sonnet"},
            )

            assert response.status_code == 401


# =============================================================================
# Test: Authenticated Requests Succeed
# =============================================================================


class TestAuthenticatedRequests:
    """Tests for endpoints with valid authentication."""

    def test_status_with_valid_auth(
        self, auth_client: TestClient, state_file: Path, goal_file: Path
    ) -> None:
        """Test that /status works with valid auth."""
        with (
            patch("claude_task_master.auth.password.is_auth_enabled", return_value=True),
            patch("claude_task_master.auth.password.authenticate", return_value=True),
        ):
            response = auth_client.get(
                "/status",
                headers={"Authorization": "Bearer test_password"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    def test_invalid_password_returns_403(
        self, auth_client: TestClient, state_file: Path, goal_file: Path
    ) -> None:
        """Test that invalid password returns 403."""
        with (
            patch("claude_task_master.auth.password.is_auth_enabled", return_value=True),
            patch("claude_task_master.auth.password.authenticate", return_value=False),
        ):
            response = auth_client.get(
                "/status",
                headers={"Authorization": "Bearer wrong_password"},
            )

            assert response.status_code == 403


# =============================================================================
# Test: Public Paths
# =============================================================================


class TestPublicPaths:
    """Tests for paths that don't require authentication."""

    def test_root_endpoint_no_auth_required(self, auth_client: TestClient) -> None:
        """Test that root endpoint works without auth."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = auth_client.get("/")

            # Root is registered on the app directly, may return 404 if not
            # But should NOT return 401
            assert response.status_code != 401

    def test_docs_endpoint_no_auth_required(self, auth_client: TestClient) -> None:
        """Test that /docs endpoint works without auth."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = auth_client.get("/docs")

            # Docs might return redirect or 200, but not 401
            assert response.status_code != 401

    def test_openapi_json_no_auth_required(self, auth_client: TestClient) -> None:
        """Test that /openapi.json endpoint works without auth."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = auth_client.get("/openapi.json")

            # OpenAPI spec might return 404 if not configured, but not 401
            assert response.status_code != 401


# =============================================================================
# Test: OPTIONS Requests (CORS Preflight)
# =============================================================================


class TestOptionsRequests:
    """Tests for OPTIONS (CORS preflight) requests."""

    def test_options_request_no_auth_required(self, auth_client: TestClient) -> None:
        """Test that OPTIONS requests work without auth.

        CORS preflight must not require authentication per the CORS spec.
        """
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = auth_client.options("/status")

            # Should not be 401 - OPTIONS is always allowed
            assert response.status_code != 401

    def test_options_on_protected_endpoint(self, auth_client: TestClient) -> None:
        """Test OPTIONS on protected endpoint still works."""
        with patch("claude_task_master.auth.password.is_auth_enabled", return_value=True):
            response = auth_client.options("/control/stop")

            # OPTIONS should not require auth
            assert response.status_code != 401
