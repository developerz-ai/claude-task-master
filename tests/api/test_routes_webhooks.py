"""Tests for webhook management API routes.

Tests the CRUD endpoints for webhook configurations and the test endpoint.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Skip all tests if FastAPI is not installed
try:
    from fastapi.testclient import TestClient

    FASTAPI_AVAILABLE = True
except ImportError:
    TestClient = None  # type: ignore[assignment,misc]
    FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _enable_webhook_auth_and_stub_dns(monkeypatch):
    """Enable the /webhooks* auth gate and stub DNS for the happy-path suite.

    All webhook routes now refuse (403) when authentication is disabled, so the
    default posture for these tests is auth-enabled. DNS resolution is stubbed to
    a public IP so the SSRF guard never touches the network for example.com
    fixtures. Individual tests override either stub as needed.
    """
    import claude_task_master.api.routes_webhooks as rw

    monkeypatch.setattr(rw, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(rw, "_resolve_host", lambda host: ["93.184.216.34"])


@pytest.fixture
def webhooks_file(api_state_dir: Path) -> Path:
    """Create a webhooks.json file with sample data."""
    webhooks_data = {
        "webhooks": {
            "wh_abc12345_def67890": {
                "url": "https://example.com/webhook1",
                "secret": "secret123",
                "events": ["task.completed", "pr.created"],
                "enabled": True,
                "name": "Test Webhook 1",
                "description": "A test webhook",
                "timeout": 30.0,
                "max_retries": 3,
                "verify_ssl": True,
                "headers": {"X-Custom-Header": "value"},
                "created_at": "2025-01-18T12:00:00",
                "updated_at": "2025-01-18T12:00:00",
            },
            "wh_xyz98765_uvw43210": {
                "url": "https://example.com/webhook2",
                "secret": None,
                "events": None,
                "enabled": False,
                "name": "Test Webhook 2",
                "description": None,
                "timeout": 60.0,
                "max_retries": 5,
                "verify_ssl": False,
                "headers": {},
                "created_at": "2025-01-18T13:00:00",
                "updated_at": "2025-01-18T13:00:00",
            },
        },
        "updated_at": "2025-01-18T13:00:00",
    }
    webhooks_file = api_state_dir / "webhooks.json"
    webhooks_file.write_text(json.dumps(webhooks_data))
    return webhooks_file


@pytest.fixture
def empty_webhooks_file(api_state_dir: Path) -> Path:
    """Create an empty webhooks.json file."""
    webhooks_data = {"webhooks": {}, "updated_at": datetime.now().isoformat()}
    webhooks_file = api_state_dir / "webhooks.json"
    webhooks_file.write_text(json.dumps(webhooks_data))
    return webhooks_file


# =============================================================================
# List Webhooks Tests
# =============================================================================


class TestListWebhooks:
    """Tests for GET /webhooks endpoint."""

    def test_list_webhooks_success(self, api_client, webhooks_file):
        """Test listing all webhooks."""
        response = api_client.get("/webhooks")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["total"] == 2
        assert len(data["webhooks"]) == 2

        # Check first webhook
        webhook1 = next(w for w in data["webhooks"] if w["id"] == "wh_abc12345_def67890")
        assert webhook1["url"] == "https://example.com/webhook1"
        assert webhook1["has_secret"] is True
        assert webhook1["events"] == ["task.completed", "pr.created"]
        assert webhook1["enabled"] is True
        assert webhook1["name"] == "Test Webhook 1"

        # Check second webhook
        webhook2 = next(w for w in data["webhooks"] if w["id"] == "wh_xyz98765_uvw43210")
        assert webhook2["url"] == "https://example.com/webhook2"
        assert webhook2["has_secret"] is False
        assert webhook2["events"] is None
        assert webhook2["enabled"] is False

    def test_list_webhooks_empty(self, api_client, empty_webhooks_file):
        """Test listing webhooks when none exist."""
        response = api_client.get("/webhooks")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["total"] == 0
        assert data["webhooks"] == []

    def test_list_webhooks_no_file(self, api_client, api_state_dir):
        """Test listing webhooks when webhooks.json doesn't exist."""
        response = api_client.get("/webhooks")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["total"] == 0
        assert data["webhooks"] == []


# =============================================================================
# Create Webhook Tests
# =============================================================================


class TestCreateWebhook:
    """Tests for POST /webhooks endpoint."""

    def test_create_webhook_success(self, api_client, api_state_dir):
        """Test creating a new webhook."""
        request_data = {
            "url": "https://newwebhook.example.com/hook",
            "secret": "newsecret",
            "events": ["task.started", "task.completed"],
            "enabled": True,
            "name": "New Webhook",
            "description": "A brand new webhook",
            "timeout": 15.0,
            "max_retries": 2,
            "verify_ssl": True,
            "headers": {"Authorization": "Bearer token"},
        }

        response = api_client.post("/webhooks", json=request_data)
        assert response.status_code == 201

        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Webhook created successfully"
        assert data["webhook"]["url"] == request_data["url"]
        assert data["webhook"]["has_secret"] is True
        assert data["webhook"]["events"] == request_data["events"]
        assert data["webhook"]["name"] == request_data["name"]
        assert data["webhook"]["id"].startswith("wh_")

    def test_create_webhook_minimal(self, api_client, api_state_dir):
        """Test creating a webhook with minimal fields."""
        request_data = {"url": "https://minimal.example.com/hook"}

        response = api_client.post("/webhooks", json=request_data)
        assert response.status_code == 201

        data = response.json()
        assert data["success"] is True
        assert data["webhook"]["url"] == request_data["url"]
        assert data["webhook"]["has_secret"] is False
        assert data["webhook"]["enabled"] is True
        assert data["webhook"]["timeout"] == 30.0
        assert data["webhook"]["max_retries"] == 3

    def test_create_webhook_duplicate_url(self, api_client, webhooks_file):
        """Test creating a webhook with duplicate URL."""
        request_data = {"url": "https://example.com/webhook1"}  # Already exists

        response = api_client.post("/webhooks", json=request_data)
        assert response.status_code == 409

        data = response.json()
        assert data["success"] is False
        assert data["error"] == "duplicate_webhook"
        assert "already exists" in data["message"]

    def test_create_webhook_invalid_url(self, api_client, api_state_dir):
        """Test creating a webhook with invalid URL."""
        request_data = {"url": "not-a-valid-url"}

        response = api_client.post("/webhooks", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_create_webhook_invalid_events(self, api_client, api_state_dir):
        """Test creating a webhook with invalid event types."""
        request_data = {
            "url": "https://example.com/hook",
            "events": ["invalid.event.type"],
        }

        response = api_client.post("/webhooks", json=request_data)
        assert response.status_code == 422  # Validation error


# =============================================================================
# Get Webhook Tests
# =============================================================================


class TestGetWebhook:
    """Tests for GET /webhooks/{webhook_id} endpoint."""

    def test_get_webhook_success(self, api_client, webhooks_file):
        """Test getting a specific webhook."""
        response = api_client.get("/webhooks/wh_abc12345_def67890")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == "wh_abc12345_def67890"
        assert data["url"] == "https://example.com/webhook1"
        assert data["has_secret"] is True
        assert data["name"] == "Test Webhook 1"

    def test_get_webhook_not_found(self, api_client, webhooks_file):
        """Test getting a non-existent webhook."""
        response = api_client.get("/webhooks/wh_nonexistent_12345")
        assert response.status_code == 404

        data = response.json()
        assert data["success"] is False
        assert data["error"] == "not_found"


# =============================================================================
# Update Webhook Tests
# =============================================================================


class TestUpdateWebhook:
    """Tests for PUT /webhooks/{webhook_id} endpoint."""

    def test_update_webhook_success(self, api_client, webhooks_file):
        """Test updating a webhook."""
        update_data = {
            "name": "Updated Name",
            "enabled": False,
            "timeout": 45.0,
        }

        response = api_client.put("/webhooks/wh_abc12345_def67890", json=update_data)
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == "wh_abc12345_def67890"
        assert data["name"] == "Updated Name"
        assert data["enabled"] is False
        assert data["timeout"] == 45.0
        # Unchanged fields should remain the same
        assert data["url"] == "https://example.com/webhook1"

    def test_update_webhook_url(self, api_client, webhooks_file):
        """Test updating a webhook's URL."""
        update_data = {"url": "https://newurl.example.com/hook"}

        response = api_client.put("/webhooks/wh_abc12345_def67890", json=update_data)
        assert response.status_code == 200

        data = response.json()
        assert data["url"] == "https://newurl.example.com/hook"

    def test_update_webhook_url_conflict(self, api_client, webhooks_file):
        """Test updating a webhook to a URL that's already used."""
        update_data = {"url": "https://example.com/webhook2"}  # Already used by other webhook

        response = api_client.put("/webhooks/wh_abc12345_def67890", json=update_data)
        assert response.status_code == 409

        data = response.json()
        assert data["error"] == "duplicate_webhook"

    def test_update_webhook_not_found(self, api_client, webhooks_file):
        """Test updating a non-existent webhook."""
        update_data = {"name": "New Name"}

        response = api_client.put("/webhooks/wh_nonexistent_12345", json=update_data)
        assert response.status_code == 404

    def test_update_webhook_clear_secret(self, api_client, webhooks_file):
        """Test clearing a webhook's secret."""
        update_data = {"secret": ""}

        response = api_client.put("/webhooks/wh_abc12345_def67890", json=update_data)
        assert response.status_code == 200

        data = response.json()
        assert data["has_secret"] is False

    def test_update_webhook_no_updates(self, api_client, webhooks_file):
        """Test updating a webhook with no fields provided returns 400."""
        update_data = {}

        response = api_client.put("/webhooks/wh_abc12345_def67890", json=update_data)
        assert response.status_code == 400

        data = response.json()
        assert data["error"] == "validation_error"
        assert "At least one field" in data["message"]


# =============================================================================
# Delete Webhook Tests
# =============================================================================


class TestDeleteWebhook:
    """Tests for DELETE /webhooks/{webhook_id} endpoint."""

    def test_delete_webhook_success(self, api_client, webhooks_file):
        """Test deleting a webhook."""
        response = api_client.delete("/webhooks/wh_abc12345_def67890")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Webhook deleted successfully"
        assert data["id"] == "wh_abc12345_def67890"

        # Verify it's actually deleted
        response = api_client.get("/webhooks/wh_abc12345_def67890")
        assert response.status_code == 404

    def test_delete_webhook_not_found(self, api_client, webhooks_file):
        """Test deleting a non-existent webhook."""
        response = api_client.delete("/webhooks/wh_nonexistent_12345")
        assert response.status_code == 404

        data = response.json()
        assert data["success"] is False
        assert data["error"] == "not_found"


# =============================================================================
# Test Webhook Tests
# =============================================================================


class TestTestWebhook:
    """Tests for POST /webhooks/test endpoint."""

    def test_test_webhook_by_id_success(self, api_client, webhooks_file):
        """Test sending a test webhook by ID."""
        with patch("claude_task_master.api.routes_webhooks.WebhookClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.send.return_value = AsyncMock(
                success=True,
                status_code=200,
                delivery_time_ms=150.5,
                attempt_count=1,
                error=None,
            )
            mock_client_class.return_value = mock_client

            request_data = {"webhook_id": "wh_abc12345_def67890"}
            response = api_client.post("/webhooks/test", json=request_data)

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["message"] == "Test webhook delivered successfully"
            assert data["status_code"] == 200
            assert data["delivery_time_ms"] == 150.5
            assert data["attempt_count"] == 1

            # Verify client was created with correct params
            mock_client_class.assert_called_once()
            call_kwargs = mock_client_class.call_args[1]
            assert call_kwargs["url"] == "https://example.com/webhook1"
            assert call_kwargs["secret"] == "secret123"
            assert call_kwargs["timeout"] == 30.0
            assert call_kwargs["max_retries"] == 1  # Tests use 1 retry
            assert call_kwargs["verify_ssl"] is True

    def test_test_webhook_by_url_success(self, api_client, api_state_dir):
        """Test sending a test webhook by URL."""
        with patch("claude_task_master.api.routes_webhooks.WebhookClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.send.return_value = AsyncMock(
                success=True,
                status_code=200,
                delivery_time_ms=100.0,
                attempt_count=1,
                error=None,
            )
            mock_client_class.return_value = mock_client

            request_data = {
                "url": "https://test.example.com/webhook",
                "secret": "test_secret",
            }
            response = api_client.post("/webhooks/test", json=request_data)

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

            # Verify client was created with direct URL params
            mock_client_class.assert_called_once()
            call_kwargs = mock_client_class.call_args[1]
            assert call_kwargs["url"] == "https://test.example.com/webhook"
            assert call_kwargs["secret"] == "test_secret"

    def test_test_webhook_by_id_not_found(self, api_client, webhooks_file):
        """Test sending a test webhook with non-existent ID."""
        request_data = {"webhook_id": "wh_nonexistent_12345"}
        response = api_client.post("/webhooks/test", json=request_data)

        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "not_found"

    def test_test_webhook_missing_params(self, api_client, api_state_dir):
        """Test sending a test webhook without ID or URL."""
        request_data: dict[str, str] = {}
        response = api_client.post("/webhooks/test", json=request_data)

        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "invalid_request"
        assert "webhook_id or url" in data["message"]

    def test_test_webhook_delivery_failure(self, api_client, webhooks_file):
        """Test handling of webhook delivery failure."""
        with patch("claude_task_master.api.routes_webhooks.WebhookClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.send.return_value = AsyncMock(
                success=False,
                status_code=500,
                delivery_time_ms=250.0,
                attempt_count=1,
                error="Internal Server Error",
            )
            mock_client_class.return_value = mock_client

            request_data = {"webhook_id": "wh_abc12345_def67890"}
            response = api_client.post("/webhooks/test", json=request_data)

            assert response.status_code == 200  # Request succeeded, delivery failed
            data = response.json()
            assert data["success"] is False
            assert data["message"] == "Test webhook delivery failed"
            assert data["status_code"] == 500
            assert data["error"] == "Internal Server Error"

    def test_test_webhook_connection_error(self, api_client, webhooks_file):
        """Test handling of connection error during webhook test."""
        with patch("claude_task_master.api.routes_webhooks.WebhookClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.send.return_value = AsyncMock(
                success=False,
                status_code=None,
                delivery_time_ms=5000.0,
                attempt_count=1,
                error="Connection refused",
            )
            mock_client_class.return_value = mock_client

            request_data = {"webhook_id": "wh_abc12345_def67890"}
            response = api_client.post("/webhooks/test", json=request_data)

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert data["error"] == "Connection refused"

    def test_test_webhook_invalid_url(self, api_client, api_state_dir):
        """Test sending a test webhook with invalid URL."""
        request_data = {"url": "not-a-valid-url"}
        response = api_client.post("/webhooks/test", json=request_data)

        assert response.status_code == 422  # Validation error

    def test_test_webhook_verifies_ssl_setting(self, api_client, webhooks_file):
        """Test that SSL verification setting is respected."""
        with patch("claude_task_master.api.routes_webhooks.WebhookClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.send.return_value = AsyncMock(
                success=True,
                status_code=200,
                delivery_time_ms=100.0,
                attempt_count=1,
                error=None,
            )
            mock_client_class.return_value = mock_client

            # Use the webhook with verify_ssl=False
            request_data = {"webhook_id": "wh_xyz98765_uvw43210"}
            response = api_client.post("/webhooks/test", json=request_data)

            assert response.status_code == 200
            # Verify SSL verification was disabled
            call_kwargs = mock_client_class.call_args[1]
            assert call_kwargs["verify_ssl"] is False

    def test_test_webhook_uses_custom_headers(self, api_client, webhooks_file):
        """Test that custom headers are passed to the client."""
        with patch("claude_task_master.api.routes_webhooks.WebhookClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.send.return_value = AsyncMock(
                success=True,
                status_code=200,
                delivery_time_ms=100.0,
                attempt_count=1,
                error=None,
            )
            mock_client_class.return_value = mock_client

            # Use the webhook with custom headers
            request_data = {"webhook_id": "wh_abc12345_def67890"}
            response = api_client.post("/webhooks/test", json=request_data)

            assert response.status_code == 200
            # Verify custom headers were passed
            call_kwargs = mock_client_class.call_args[1]
            assert call_kwargs["headers"] == {"X-Custom-Header": "value"}


# =============================================================================
# Auth-gate Tests (/webhooks* require auth)
# =============================================================================


def _disable_auth(monkeypatch) -> None:
    """Report webhook authentication as disabled at the route boundary."""
    import claude_task_master.api.routes_webhooks as rw

    monkeypatch.setattr(rw, "is_auth_enabled", lambda: False)


class TestWebhooksRequireAuth:
    """Every /webhooks* route refuses with 403 when auth is disabled."""

    def test_list_requires_auth(self, api_client, webhooks_file, monkeypatch):
        """GET /webhooks returns 403 when auth is disabled."""
        _disable_auth(monkeypatch)
        response = api_client.get("/webhooks")
        assert response.status_code == 403
        assert response.json()["error"] == "authentication_required"

    def test_create_requires_auth(self, api_client, api_state_dir, monkeypatch):
        """POST /webhooks returns 403 when auth is disabled."""
        _disable_auth(monkeypatch)
        response = api_client.post("/webhooks", json={"url": "https://example.com/hook"})
        assert response.status_code == 403
        assert response.json()["error"] == "authentication_required"

    def test_get_requires_auth(self, api_client, webhooks_file, monkeypatch):
        """GET /webhooks/{id} returns 403 when auth is disabled."""
        _disable_auth(monkeypatch)
        response = api_client.get("/webhooks/wh_abc12345_def67890")
        assert response.status_code == 403

    def test_update_requires_auth(self, api_client, webhooks_file, monkeypatch):
        """PUT /webhooks/{id} returns 403 when auth is disabled."""
        _disable_auth(monkeypatch)
        response = api_client.put("/webhooks/wh_abc12345_def67890", json={"enabled": False})
        assert response.status_code == 403

    def test_delete_requires_auth(self, api_client, webhooks_file, monkeypatch):
        """DELETE /webhooks/{id} returns 403 when auth is disabled."""
        _disable_auth(monkeypatch)
        response = api_client.delete("/webhooks/wh_abc12345_def67890")
        assert response.status_code == 403

    def test_test_requires_auth(self, api_client, webhooks_file, monkeypatch):
        """POST /webhooks/test returns 403 when auth is disabled (before any egress)."""
        _disable_auth(monkeypatch)
        with patch("claude_task_master.api.routes_webhooks.WebhookClient") as mock_client_class:
            response = api_client.post("/webhooks/test", json={"url": "https://example.com/hook"})
            assert response.status_code == 403
            mock_client_class.assert_not_called()


# =============================================================================
# SSRF Guard Tests (POST /webhooks/test)
# =============================================================================


class TestWebhookSSRFGuard:
    """POST /webhooks/test refuses targets resolving to internal addresses."""

    def _stub_resolver(self, monkeypatch, addresses):
        """Force _resolve_host to return the given addresses."""
        import claude_task_master.api.routes_webhooks as rw

        monkeypatch.setattr(rw, "_resolve_host", lambda host: addresses)

    def test_rejects_loopback(self, api_client, api_state_dir, monkeypatch):
        """A host resolving to loopback is rejected with 400 and no egress."""
        self._stub_resolver(monkeypatch, ["127.0.0.1"])
        with patch("claude_task_master.api.routes_webhooks.WebhookClient") as mock_client_class:
            response = api_client.post(
                "/webhooks/test", json={"url": "http://sneaky.internal.test/hook"}
            )
            assert response.status_code == 400
            assert response.json()["error"] == "url_not_allowed"
            mock_client_class.assert_not_called()

    def test_rejects_cloud_metadata(self, api_client, api_state_dir, monkeypatch):
        """The cloud metadata IP (169.254.169.254) is rejected with 400."""
        self._stub_resolver(monkeypatch, ["169.254.169.254"])
        with patch("claude_task_master.api.routes_webhooks.WebhookClient") as mock_client_class:
            response = api_client.post(
                "/webhooks/test", json={"url": "http://metadata.test/latest/meta-data/"}
            )
            assert response.status_code == 400
            assert response.json()["error"] == "url_not_allowed"
            mock_client_class.assert_not_called()

    def test_rejects_private_range(self, api_client, api_state_dir, monkeypatch):
        """A private RFC1918 address (10.x) is rejected with 400."""
        self._stub_resolver(monkeypatch, ["10.1.2.3"])
        response = api_client.post("/webhooks/test", json={"url": "http://intranet.test/hook"})
        assert response.status_code == 400
        assert response.json()["error"] == "url_not_allowed"

    def test_rejects_ipv4_mapped_ipv6_loopback(self, api_client, api_state_dir, monkeypatch):
        """An IPv4-mapped IPv6 loopback (::ffff:127.0.0.1) is unwrapped and rejected."""
        self._stub_resolver(monkeypatch, ["::ffff:127.0.0.1"])
        response = api_client.post("/webhooks/test", json={"url": "http://mapped.test/hook"})
        assert response.status_code == 400

    def test_rejects_unresolvable_host(self, api_client, api_state_dir, monkeypatch):
        """A host that fails DNS resolution is rejected with 400."""
        import socket

        import claude_task_master.api.routes_webhooks as rw

        def _boom(host):
            raise socket.gaierror("name resolution failed")

        monkeypatch.setattr(rw, "_resolve_host", _boom)
        response = api_client.post("/webhooks/test", json={"url": "http://nope.invalid/hook"})
        assert response.status_code == 400
        assert response.json()["error"] == "url_not_allowed"

    def test_allows_public_address(self, api_client, api_state_dir, monkeypatch):
        """A public address passes the guard and the client is invoked."""
        self._stub_resolver(monkeypatch, ["93.184.216.34"])
        with patch("claude_task_master.api.routes_webhooks.WebhookClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.send.return_value = AsyncMock(
                success=True,
                status_code=200,
                delivery_time_ms=10.0,
                attempt_count=1,
                error=None,
            )
            mock_client_class.return_value = mock_client
            response = api_client.post(
                "/webhooks/test", json={"url": "https://public.example.com/hook"}
            )
            assert response.status_code == 200
            mock_client_class.assert_called_once()


# =============================================================================
# Header Masking Tests (no bearer/secret leak)
# =============================================================================


def _write_single_webhook(api_state_dir: Path, webhook_id: str, headers: dict) -> None:
    """Write a webhooks.json containing one webhook with the given headers."""
    data = {
        "webhooks": {
            webhook_id: {
                "url": "https://example.com/masked",
                "secret": "s3cr3t",
                "events": None,
                "enabled": True,
                "name": "Masked",
                "description": None,
                "timeout": 30.0,
                "max_retries": 3,
                "verify_ssl": True,
                "headers": headers,
                "created_at": "2025-01-18T12:00:00",
                "updated_at": "2025-01-18T12:00:00",
            }
        },
        "updated_at": "2025-01-18T12:00:00",
    }
    (api_state_dir / "webhooks.json").write_text(json.dumps(data))


class TestWebhookHeaderMasking:
    """Credential-bearing header values are masked in responses."""

    def test_list_masks_authorization_header(self, api_client, api_state_dir):
        """GET /webhooks masks an Authorization bearer value but keeps benign headers."""
        _write_single_webhook(
            api_state_dir,
            "wh_mask_0001",
            {"Authorization": "Bearer super-secret-token", "Content-Type": "application/json"},
        )
        response = api_client.get("/webhooks")
        assert response.status_code == 200
        headers = response.json()["webhooks"][0]["headers"]
        assert headers["Authorization"] == "***"
        assert headers["Content-Type"] == "application/json"

    def test_get_masks_sensitive_headers(self, api_client, api_state_dir):
        """GET /webhooks/{id} masks X-Api-Key and Cookie, preserves Accept."""
        _write_single_webhook(
            api_state_dir,
            "wh_mask_0002",
            {"X-Api-Key": "abc123", "Cookie": "session=xyz", "Accept": "application/json"},
        )
        response = api_client.get("/webhooks/wh_mask_0002")
        assert response.status_code == 200
        headers = response.json()["headers"]
        assert headers["X-Api-Key"] == "***"
        assert headers["Cookie"] == "***"
        assert headers["Accept"] == "application/json"

    def test_create_response_masks_headers(self, api_client, api_state_dir):
        """POST /webhooks masks Authorization in the creation response."""
        response = api_client.post(
            "/webhooks",
            json={
                "url": "https://example.com/newhook",
                "headers": {"Authorization": "Bearer leak-me"},
            },
        )
        assert response.status_code == 201
        assert response.json()["webhook"]["headers"]["Authorization"] == "***"


# =============================================================================
# Hop-by-hop Header Stripping Tests (POST /webhooks/test)
# =============================================================================


class TestWebhookHopHeaderStripping:
    """Hop-by-hop/routing headers are removed before the outbound test request."""

    def test_strips_hop_headers_before_send(self, api_client, api_state_dir, monkeypatch):
        """Connection/Host headers are dropped while custom headers survive."""
        import claude_task_master.api.routes_webhooks as rw

        monkeypatch.setattr(rw, "_resolve_host", lambda host: ["93.184.216.34"])
        _write_single_webhook(
            api_state_dir,
            "wh_hop_0001",
            {"Connection": "keep-alive", "Host": "evil.example.com", "X-Custom": "keep-me"},
        )
        with patch("claude_task_master.api.routes_webhooks.WebhookClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.send.return_value = AsyncMock(
                success=True,
                status_code=200,
                delivery_time_ms=10.0,
                attempt_count=1,
                error=None,
            )
            mock_client_class.return_value = mock_client
            response = api_client.post("/webhooks/test", json={"webhook_id": "wh_hop_0001"})
            assert response.status_code == 200
            sent_headers = mock_client_class.call_args[1]["headers"]
            assert sent_headers == {"X-Custom": "keep-me"}


# =============================================================================
# Security Helper Unit Tests
# =============================================================================


class TestSecurityHelpers:
    """Unit tests for the webhook security helper functions."""

    def test_mask_headers_redacts_credentials(self):
        """_mask_headers redacts credential headers and preserves benign ones."""
        from claude_task_master.api.routes_webhooks import _mask_headers

        masked = _mask_headers({"Authorization": "Bearer x", "Accept": "application/json"})
        assert masked == {"Authorization": "***", "Accept": "application/json"}

    def test_mask_headers_is_case_insensitive(self):
        """_mask_headers matches credential markers case-insensitively."""
        from claude_task_master.api.routes_webhooks import _mask_headers

        assert _mask_headers({"x-api-key": "k", "X-SECRET-TOKEN": "t"}) == {
            "x-api-key": "***",
            "X-SECRET-TOKEN": "***",
        }

    def test_strip_hop_headers_removes_hop_by_hop(self):
        """_strip_hop_headers drops hop-by-hop/routing headers only."""
        from claude_task_master.api.routes_webhooks import _strip_hop_headers

        result = _strip_hop_headers(
            {"Connection": "keep-alive", "X-Ok": "1", "Host": "h", "Transfer-Encoding": "chunked"}
        )
        assert result == {"X-Ok": "1"}

    @pytest.mark.parametrize(
        "addr",
        ["127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.1", "169.254.169.254", "::1", "0.0.0.0"],
    )
    def test_is_blocked_ip_blocks_internal(self, addr):
        """_is_blocked_ip flags loopback/private/link-local/reserved addresses."""
        import ipaddress

        from claude_task_master.api.routes_webhooks import _is_blocked_ip

        assert _is_blocked_ip(ipaddress.ip_address(addr)) is True

    @pytest.mark.parametrize("addr", ["93.184.216.34", "8.8.8.8", "1.1.1.1"])
    def test_is_blocked_ip_allows_public(self, addr):
        """_is_blocked_ip permits public addresses."""
        import ipaddress

        from claude_task_master.api.routes_webhooks import _is_blocked_ip

        assert _is_blocked_ip(ipaddress.ip_address(addr)) is False

    def test_url_ssrf_error_none_for_public(self, monkeypatch):
        """_url_ssrf_error returns None when the host resolves to a public address."""
        import claude_task_master.api.routes_webhooks as rw

        monkeypatch.setattr(rw, "_resolve_host", lambda host: ["93.184.216.34"])
        assert rw._url_ssrf_error("https://example.com/hook") is None

    def test_url_ssrf_error_blocks_private(self, monkeypatch):
        """_url_ssrf_error returns a message when the host resolves internally."""
        import claude_task_master.api.routes_webhooks as rw

        monkeypatch.setattr(rw, "_resolve_host", lambda host: ["10.0.0.5"])
        assert rw._url_ssrf_error("http://intranet.test/") is not None
