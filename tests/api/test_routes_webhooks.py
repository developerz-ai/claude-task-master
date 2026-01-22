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
