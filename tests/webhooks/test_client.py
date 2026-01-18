"""Tests for webhook client module.

Tests cover:
- HMAC signature generation and verification
- WebhookClient initialization and configuration
- Payload preparation and headers
- Async and sync delivery methods
- Retry logic and error handling
- WebhookDeliveryResult and error classes
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from claude_task_master.webhooks.client import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    HEADER_EVENT_TYPE,
    HEADER_SIGNATURE,
    HEADER_SIGNATURE_256,
    HEADER_TIMESTAMP,
    WebhookClient,
    WebhookClientConfig,
    WebhookConnectionError,
    WebhookDeliveryError,
    WebhookDeliveryResult,
    WebhookTimeoutError,
    generate_signature,
    verify_signature,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# Test: Signature Generation and Verification
# =============================================================================


class TestSignatureGeneration:
    """Tests for HMAC signature generation."""

    def test_generate_signature_returns_sha256_prefixed_hex(self) -> None:
        """Test that signature has correct format."""
        payload = b'{"event": "test"}'
        secret = "test_secret"

        signature = generate_signature(payload, secret)

        assert signature.startswith("sha256=")
        # SHA256 produces 64 hex characters
        assert len(signature) == 7 + 64  # "sha256=" + 64 hex chars

    def test_generate_signature_deterministic(self) -> None:
        """Test that same payload and secret produce same signature."""
        payload = b'{"event": "test", "data": "value"}'
        secret = "my_secret_key"

        sig1 = generate_signature(payload, secret)
        sig2 = generate_signature(payload, secret)

        assert sig1 == sig2

    def test_generate_signature_different_secrets_different_results(self) -> None:
        """Test that different secrets produce different signatures."""
        payload = b'{"event": "test"}'

        sig1 = generate_signature(payload, "secret1")
        sig2 = generate_signature(payload, "secret2")

        assert sig1 != sig2

    def test_generate_signature_different_payloads_different_results(self) -> None:
        """Test that different payloads produce different signatures."""
        secret = "shared_secret"

        sig1 = generate_signature(b'{"event": "test1"}', secret)
        sig2 = generate_signature(b'{"event": "test2"}', secret)

        assert sig1 != sig2

    def test_generate_signature_empty_payload(self) -> None:
        """Test signature generation with empty payload."""
        signature = generate_signature(b"", "secret")

        assert signature.startswith("sha256=")
        assert len(signature) == 7 + 64

    def test_generate_signature_unicode_secret(self) -> None:
        """Test signature generation with unicode secret."""
        payload = b'{"test": true}'
        secret = "secret_with_unicode_"

        signature = generate_signature(payload, secret)

        assert signature.startswith("sha256=")


class TestSignatureVerification:
    """Tests for HMAC signature verification."""

    def test_verify_signature_valid(self) -> None:
        """Test that valid signature verifies successfully."""
        payload = b'{"event": "test"}'
        secret = "test_secret"

        signature = generate_signature(payload, secret)
        assert verify_signature(payload, secret, signature) is True

    def test_verify_signature_invalid_secret(self) -> None:
        """Test that wrong secret fails verification."""
        payload = b'{"event": "test"}'

        signature = generate_signature(payload, "correct_secret")
        assert verify_signature(payload, "wrong_secret", signature) is False

    def test_verify_signature_modified_payload(self) -> None:
        """Test that modified payload fails verification."""
        original_payload = b'{"event": "test"}'
        modified_payload = b'{"event": "modified"}'
        secret = "secret"

        signature = generate_signature(original_payload, secret)
        assert verify_signature(modified_payload, secret, signature) is False

    def test_verify_signature_without_prefix(self) -> None:
        """Test verification works with signature without prefix."""
        payload = b'{"test": true}'
        secret = "secret"

        full_signature = generate_signature(payload, secret)
        signature_only = full_signature[7:]  # Remove "sha256="

        assert verify_signature(payload, secret, signature_only) is True

    def test_verify_signature_empty_signature(self) -> None:
        """Test that empty signature fails verification."""
        assert verify_signature(b"payload", "secret", "") is False

    def test_verify_signature_none_signature(self) -> None:
        """Test that None signature fails verification."""
        # Type checker will complain but we test runtime behavior
        assert verify_signature(b"payload", "secret", None) is False  # type: ignore[arg-type]


# =============================================================================
# Test: WebhookClient Initialization
# =============================================================================


class TestWebhookClientInit:
    """Tests for WebhookClient initialization."""

    def test_init_with_url_only(self) -> None:
        """Test client initialization with just URL."""
        client = WebhookClient("https://example.com/webhook")

        assert client.url == "https://example.com/webhook"
        assert client.secret is None
        assert client.timeout == DEFAULT_TIMEOUT
        assert client.max_retries == DEFAULT_MAX_RETRIES

    def test_init_with_all_parameters(self) -> None:
        """Test client initialization with all parameters."""
        client = WebhookClient(
            url="https://example.com/webhook",
            secret="my_secret",
            timeout=10.0,
            max_retries=5,
            retry_delay=2.0,
            verify_ssl=False,
            headers={"X-Custom": "header"},
        )

        assert client.url == "https://example.com/webhook"
        assert client.secret == "my_secret"
        assert client.timeout == 10.0
        assert client.max_retries == 5
        assert client.retry_delay == 2.0
        assert client.verify_ssl is False
        assert client.headers == {"X-Custom": "header"}

    def test_init_empty_url_raises_value_error(self) -> None:
        """Test that empty URL raises ValueError."""
        with pytest.raises(ValueError, match="URL cannot be empty"):
            WebhookClient("")

    def test_init_invalid_url_scheme_raises_value_error(self) -> None:
        """Test that invalid URL scheme raises ValueError."""
        with pytest.raises(ValueError, match="Invalid webhook URL scheme"):
            WebhookClient("ftp://example.com/webhook")

    def test_init_accepts_http_url(self) -> None:
        """Test that HTTP URLs are accepted."""
        client = WebhookClient("http://localhost:8080/webhook")
        assert client.url == "http://localhost:8080/webhook"

    def test_init_accepts_https_url(self) -> None:
        """Test that HTTPS URLs are accepted."""
        client = WebhookClient("https://secure.example.com/webhook")
        assert client.url == "https://secure.example.com/webhook"

    def test_from_config(self) -> None:
        """Test creating client from configuration object."""
        config = WebhookClientConfig(
            url="https://example.com/webhook",
            secret="config_secret",
            timeout=15.0,
            max_retries=2,
        )

        client = WebhookClient.from_config(config)

        assert client.url == "https://example.com/webhook"
        assert client.secret == "config_secret"
        assert client.timeout == 15.0
        assert client.max_retries == 2

    def test_repr(self) -> None:
        """Test string representation of client."""
        client = WebhookClient("https://example.com/webhook", secret="secret", timeout=15.0)
        repr_str = repr(client)

        assert "https://example.com/webhook" in repr_str
        assert "has_secret=True" in repr_str
        assert "timeout=15.0" in repr_str


# =============================================================================
# Test: Payload Preparation
# =============================================================================


class TestPayloadPreparation:
    """Tests for payload preparation."""

    def test_prepare_payload_json_serialization(self) -> None:
        """Test that payload is serialized to JSON correctly."""
        client = WebhookClient("https://example.com/webhook")
        data = {"event": "test", "data": {"key": "value"}}

        payload, headers, signature = client._prepare_payload(data)

        # Verify JSON serialization (compact, sorted keys)
        parsed = json.loads(payload)
        assert parsed == data
        assert b'"data":{"key":"value"}' in payload  # Compact format

    def test_prepare_payload_includes_content_type(self) -> None:
        """Test that Content-Type header is set."""
        client = WebhookClient("https://example.com/webhook")

        _, headers, _ = client._prepare_payload({"test": True})

        assert headers["Content-Type"] == "application/json"

    def test_prepare_payload_includes_timestamp(self) -> None:
        """Test that timestamp header is included."""
        client = WebhookClient("https://example.com/webhook")

        _, headers, _ = client._prepare_payload({"test": True})

        assert HEADER_TIMESTAMP in headers
        # Should be a numeric string
        assert headers[HEADER_TIMESTAMP].isdigit()

    def test_prepare_payload_includes_event_type_when_provided(self) -> None:
        """Test that event type header is included when specified."""
        client = WebhookClient("https://example.com/webhook")

        _, headers, _ = client._prepare_payload({"test": True}, event_type="task.completed")

        assert headers[HEADER_EVENT_TYPE] == "task.completed"

    def test_prepare_payload_without_event_type(self) -> None:
        """Test that event type header is not included when not specified."""
        client = WebhookClient("https://example.com/webhook")

        _, headers, _ = client._prepare_payload({"test": True})

        assert HEADER_EVENT_TYPE not in headers

    def test_prepare_payload_with_secret_includes_signatures(self) -> None:
        """Test that signatures are included when secret is configured."""
        client = WebhookClient("https://example.com/webhook", secret="test_secret")

        _, headers, signature = client._prepare_payload({"test": True})

        assert HEADER_SIGNATURE in headers
        assert HEADER_SIGNATURE_256 in headers
        assert signature is not None
        assert signature.startswith("sha256=")

    def test_prepare_payload_without_secret_no_signatures(self) -> None:
        """Test that signatures are not included when no secret."""
        client = WebhookClient("https://example.com/webhook")

        _, headers, signature = client._prepare_payload({"test": True})

        assert HEADER_SIGNATURE not in headers
        assert HEADER_SIGNATURE_256 not in headers
        assert signature is None

    def test_prepare_payload_includes_custom_headers(self) -> None:
        """Test that custom headers are included."""
        client = WebhookClient(
            "https://example.com/webhook",
            headers={"X-Custom-Header": "custom_value"},
        )

        _, headers, _ = client._prepare_payload({"test": True})

        assert headers["X-Custom-Header"] == "custom_value"


# =============================================================================
# Test: Async Send
# =============================================================================


class TestAsyncSend:
    """Tests for async send method."""

    @pytest.mark.asyncio
    async def test_send_success_returns_result(self) -> None:
        """Test successful webhook delivery."""
        client = WebhookClient("https://example.com/webhook")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"received": true}'

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await client.send({"event": "test"})

        assert result.success is True
        assert result.status_code == 200
        assert result.attempt_count == 1

    @pytest.mark.asyncio
    async def test_send_with_event_type(self) -> None:
        """Test sending with event type header."""
        client = WebhookClient("https://example.com/webhook")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            await client.send({"event": "test"}, event_type="task.started")

        # Verify headers were passed
        call_kwargs = mock_post.call_args.kwargs
        assert HEADER_EVENT_TYPE in call_kwargs["headers"]
        assert call_kwargs["headers"][HEADER_EVENT_TYPE] == "task.started"

    @pytest.mark.asyncio
    async def test_send_with_delivery_id(self) -> None:
        """Test sending with delivery ID."""
        client = WebhookClient("https://example.com/webhook")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await client.send({"event": "test"}, delivery_id="delivery-123")

        assert result.delivery_id == "delivery-123"

    @pytest.mark.asyncio
    async def test_send_client_error_not_retried(self) -> None:
        """Test that 4xx errors (except 429) are not retried."""
        client = WebhookClient("https://example.com/webhook", max_retries=3)

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await client.send({"event": "test"})

        assert result.success is False
        assert result.status_code == 400
        assert result.attempt_count == 1  # Not retried
        assert mock_post.call_count == 1

    @pytest.mark.asyncio
    async def test_send_server_error_retried(self) -> None:
        """Test that 5xx errors are retried."""
        client = WebhookClient(
            "https://example.com/webhook",
            max_retries=2,
            retry_delay=0.01,  # Fast retries for testing
        )

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await client.send({"event": "test"})

        assert result.success is False
        assert result.attempt_count == 2  # Max retries reached
        assert mock_post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_timeout_retried(self) -> None:
        """Test that timeouts are retried."""
        client = WebhookClient(
            "https://example.com/webhook",
            max_retries=2,
            retry_delay=0.01,
        )

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.TimeoutException("timeout")

            result = await client.send({"event": "test"})

        assert result.success is False
        assert result.attempt_count == 2
        # Error message starts with capital "Webhook" so use lower() for comparison
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_send_connection_error_retried(self) -> None:
        """Test that connection errors are retried."""
        client = WebhookClient(
            "https://example.com/webhook",
            max_retries=2,
            retry_delay=0.01,
        )

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")

            result = await client.send({"event": "test"})

        assert result.success is False
        assert result.attempt_count == 2

    @pytest.mark.asyncio
    async def test_send_recovery_after_retry(self) -> None:
        """Test successful delivery after initial failure."""
        client = WebhookClient(
            "https://example.com/webhook",
            max_retries=3,
            retry_delay=0.01,
        )

        # First call fails, second succeeds
        fail_response = MagicMock()
        fail_response.status_code = 500
        fail_response.text = "Error"

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.text = "OK"

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [fail_response, success_response]

            result = await client.send({"event": "test"})

        assert result.success is True
        assert result.attempt_count == 2


# =============================================================================
# Test: Sync Send
# =============================================================================


class TestSyncSend:
    """Tests for synchronous send method."""

    def test_send_sync_success(self) -> None:
        """Test successful synchronous webhook delivery."""
        client = WebhookClient("https://example.com/webhook")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"received": true}'

        with patch.object(httpx.Client, "post") as mock_post:
            mock_post.return_value = mock_response

            result = client.send_sync({"event": "test"})

        assert result.success is True
        assert result.status_code == 200

    def test_send_sync_with_signature(self) -> None:
        """Test synchronous delivery includes signature."""
        client = WebhookClient("https://example.com/webhook", secret="test_secret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""

        with patch.object(httpx.Client, "post") as mock_post:
            mock_post.return_value = mock_response

            result = client.send_sync({"event": "test"})

        assert result.signature is not None
        assert result.signature.startswith("sha256=")

    def test_send_sync_retry_on_error(self) -> None:
        """Test synchronous retry on server error."""
        client = WebhookClient(
            "https://example.com/webhook",
            max_retries=2,
            retry_delay=0.01,
        )

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        with patch.object(httpx.Client, "post") as mock_post:
            mock_post.return_value = mock_response

            result = client.send_sync({"event": "test"})

        assert result.success is False
        assert result.attempt_count == 2


# =============================================================================
# Test: WebhookDeliveryResult
# =============================================================================


class TestWebhookDeliveryResult:
    """Tests for WebhookDeliveryResult dataclass."""

    def test_result_to_dict(self) -> None:
        """Test converting result to dictionary."""
        result = WebhookDeliveryResult(
            success=True,
            status_code=200,
            delivery_time_ms=123.45,
            attempt_count=1,
            delivery_id="test-123",
        )

        result_dict = result.to_dict()

        assert result_dict["success"] is True
        assert result_dict["status_code"] == 200
        assert result_dict["delivery_time_ms"] == 123.45
        assert result_dict["attempt_count"] == 1
        assert result_dict["delivery_id"] == "test-123"

    def test_result_to_dict_with_error(self) -> None:
        """Test converting failed result to dictionary."""
        result = WebhookDeliveryResult(
            success=False,
            error="Connection refused",
            attempt_count=3,
        )

        result_dict = result.to_dict()

        assert result_dict["success"] is False
        assert result_dict["error"] == "Connection refused"
        assert result_dict["attempt_count"] == 3


# =============================================================================
# Test: Exception Classes
# =============================================================================


class TestExceptionClasses:
    """Tests for webhook exception classes."""

    def test_webhook_delivery_error(self) -> None:
        """Test WebhookDeliveryError creation and attributes."""
        error = WebhookDeliveryError(
            message="Failed to deliver",
            url="https://example.com/webhook",
            status_code=500,
            response_body="Internal Error",
        )

        assert error.message == "Failed to deliver"
        assert error.url == "https://example.com/webhook"
        assert error.status_code == 500
        assert error.response_body == "Internal Error"
        assert "Failed to deliver" in str(error)
        assert "url=" in str(error)
        assert "status=" in str(error)

    def test_webhook_timeout_error(self) -> None:
        """Test WebhookTimeoutError creation and attributes."""
        error = WebhookTimeoutError("https://example.com/webhook", 30.0)

        assert error.url == "https://example.com/webhook"
        assert error.timeout == 30.0
        assert "timed out" in str(error).lower()
        assert "30" in str(error)

    def test_webhook_connection_error(self) -> None:
        """Test WebhookConnectionError creation and attributes."""
        original = Exception("Connection refused")
        error = WebhookConnectionError("https://example.com/webhook", original)

        assert error.url == "https://example.com/webhook"
        assert error.original_error is original
        assert "Failed to connect" in str(error)


# =============================================================================
# Test: WebhookClientConfig
# =============================================================================


class TestWebhookClientConfig:
    """Tests for WebhookClientConfig dataclass."""

    def test_config_defaults(self) -> None:
        """Test configuration default values."""
        config = WebhookClientConfig(url="https://example.com/webhook")

        assert config.url == "https://example.com/webhook"
        assert config.secret is None
        assert config.timeout == DEFAULT_TIMEOUT
        assert config.max_retries == DEFAULT_MAX_RETRIES
        assert config.verify_ssl is True
        assert config.headers == {}

    def test_config_custom_values(self) -> None:
        """Test configuration with custom values."""
        config = WebhookClientConfig(
            url="https://example.com/webhook",
            secret="my_secret",
            timeout=10.0,
            max_retries=5,
            retry_delay=2.0,
            verify_ssl=False,
            headers={"X-Custom": "value"},
        )

        assert config.secret == "my_secret"
        assert config.timeout == 10.0
        assert config.max_retries == 5
        assert config.retry_delay == 2.0
        assert config.verify_ssl is False
        assert config.headers == {"X-Custom": "value"}


# =============================================================================
# Test: Retry Backoff
# =============================================================================


class TestRetryBackoff:
    """Tests for retry backoff behavior."""

    @pytest.mark.asyncio
    async def test_exponential_backoff_calculation(self) -> None:
        """Test that backoff increases exponentially."""
        client = WebhookClient(
            "https://example.com/webhook",
            retry_delay=1.0,
        )

        # Test delay calculation (without actually sleeping)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await client._wait_before_retry(1)
            # First retry: 1.0 * 2^0 = 1.0
            mock_sleep.assert_called_with(1.0)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await client._wait_before_retry(2)
            # Second retry: 1.0 * 2^1 = 2.0
            mock_sleep.assert_called_with(2.0)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await client._wait_before_retry(3)
            # Third retry: 1.0 * 2^2 = 4.0
            mock_sleep.assert_called_with(4.0)

    def test_backoff_capped_at_30_seconds(self) -> None:
        """Test that backoff is capped at 30 seconds."""
        client = WebhookClient(
            "https://example.com/webhook",
            retry_delay=10.0,  # Large base delay
        )

        with patch("time.sleep") as mock_sleep:
            client._wait_before_retry_sync(5)  # Would be 10 * 2^4 = 160, but capped
            mock_sleep.assert_called_with(30.0)
