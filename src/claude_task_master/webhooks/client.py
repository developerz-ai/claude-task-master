"""Webhook client for sending HTTP POST requests with HMAC signatures.

This module provides the WebhookClient class that handles secure webhook delivery
with:
- HMAC-SHA256 signature generation for payload verification
- Configurable timeouts and retry logic
- Both synchronous and asynchronous interfaces
- Detailed delivery result tracking

Security:
    Webhooks are signed using HMAC-SHA256 with a shared secret. The signature
    is included in the X-Webhook-Signature header and can be verified by the
    recipient to ensure payload integrity and authenticity.

Example:
    >>> client = WebhookClient(url="https://example.com/webhook", secret="mysecret")
    >>> result = await client.send({"event": "task.completed"})
    >>> print(result.success)
    True
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_TIMEOUT = 30.0  # 30 seconds
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0  # 1 second base delay

# Header names
HEADER_SIGNATURE = "X-Webhook-Signature"
HEADER_SIGNATURE_256 = "X-Webhook-Signature-256"
HEADER_TIMESTAMP = "X-Webhook-Timestamp"
HEADER_DELIVERY_ID = "X-Webhook-Delivery-Id"
HEADER_EVENT_TYPE = "X-Webhook-Event"


# =============================================================================
# Exceptions
# =============================================================================


class WebhookError(Exception):
    """Base exception for webhook-related errors."""

    pass


class WebhookDeliveryError(WebhookError):
    """Error during webhook delivery.

    Attributes:
        url: The webhook URL that failed.
        status_code: HTTP status code if available.
        message: Error description.
        response_body: Response body if available.
    """

    def __init__(
        self,
        message: str,
        url: str | None = None,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        """Initialize the delivery error.

        Args:
            message: Error description.
            url: The webhook URL that failed.
            status_code: HTTP status code if available.
            response_body: Response body if available.
        """
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.message = message
        self.response_body = response_body

    def __str__(self) -> str:
        """Return string representation of the error."""
        parts = [self.message]
        if self.url:
            parts.append(f"url={self.url}")
        if self.status_code:
            parts.append(f"status={self.status_code}")
        return " ".join(parts)


class WebhookTimeoutError(WebhookError):
    """Webhook delivery timed out.

    Attributes:
        url: The webhook URL that timed out.
        timeout: The timeout value that was exceeded.
    """

    def __init__(self, url: str, timeout: float) -> None:
        """Initialize the timeout error.

        Args:
            url: The webhook URL that timed out.
            timeout: The timeout value that was exceeded.
        """
        super().__init__(f"Webhook delivery timed out after {timeout}s: {url}")
        self.url = url
        self.timeout = timeout


class WebhookConnectionError(WebhookError):
    """Failed to connect to webhook endpoint.

    Attributes:
        url: The webhook URL that couldn't be reached.
        original_error: The underlying connection error.
    """

    def __init__(self, url: str, original_error: Exception) -> None:
        """Initialize the connection error.

        Args:
            url: The webhook URL that couldn't be reached.
            original_error: The underlying connection error.
        """
        super().__init__(f"Failed to connect to webhook: {url}")
        self.url = url
        self.original_error = original_error


# =============================================================================
# Result Types
# =============================================================================


@dataclass
class WebhookDeliveryResult:
    """Result of a webhook delivery attempt.

    Attributes:
        success: Whether the delivery was successful (2xx response).
        status_code: HTTP status code from the response.
        response_body: Response body content.
        delivery_time_ms: Time taken for delivery in milliseconds.
        attempt_count: Number of attempts made (including retries).
        signature: The HMAC signature that was sent.
        delivery_id: Unique identifier for this delivery.
    """

    success: bool
    status_code: int | None = None
    response_body: str | None = None
    delivery_time_ms: float = 0.0
    attempt_count: int = 1
    signature: str | None = None
    delivery_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for logging/serialization.

        Returns:
            Dictionary representation of the result.
        """
        return {
            "success": self.success,
            "status_code": self.status_code,
            "delivery_time_ms": self.delivery_time_ms,
            "attempt_count": self.attempt_count,
            "delivery_id": self.delivery_id,
            "error": self.error,
        }


@dataclass
class WebhookClientConfig:
    """Configuration for WebhookClient.

    Attributes:
        url: The webhook endpoint URL.
        secret: Shared secret for HMAC signature generation.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts.
        retry_delay: Base delay between retries in seconds.
        verify_ssl: Whether to verify SSL certificates.
        headers: Additional headers to include in requests.
    """

    url: str
    secret: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY
    verify_ssl: bool = True
    headers: dict[str, str] = field(default_factory=dict)


# =============================================================================
# HMAC Signature Generation
# =============================================================================


def generate_signature(payload: bytes, secret: str) -> str:
    """Generate HMAC-SHA256 signature for a payload.

    Creates a signature using the shared secret that can be verified by
    the webhook recipient to ensure payload integrity.

    Args:
        payload: The raw payload bytes to sign.
        secret: The shared secret key.

    Returns:
        Hex-encoded HMAC-SHA256 signature.

    Example:
        >>> signature = generate_signature(b'{"event": "test"}', "secret123")
        >>> signature.startswith("sha256=")
        True
    """
    # Encode secret if string
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret

    # Create HMAC-SHA256 signature
    mac = hmac.new(secret_bytes, payload, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_signature(payload: bytes, secret: str, signature: str) -> bool:
    """Verify an HMAC-SHA256 signature.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        payload: The raw payload bytes that were signed.
        secret: The shared secret key.
        signature: The signature to verify (with "sha256=" prefix).

    Returns:
        True if signature is valid, False otherwise.

    Example:
        >>> payload = b'{"event": "test"}'
        >>> signature = generate_signature(payload, "secret123")
        >>> verify_signature(payload, "secret123", signature)
        True
        >>> verify_signature(payload, "wrong_secret", signature)
        False
    """
    if not signature:
        return False

    # Handle signature with or without prefix
    if signature.startswith("sha256="):
        provided_sig = signature[7:]  # Remove "sha256=" prefix
    else:
        provided_sig = signature

    # Generate expected signature
    expected = generate_signature(payload, secret)
    expected_sig = expected[7:]  # Remove "sha256=" prefix

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(provided_sig, expected_sig)


# =============================================================================
# WebhookClient
# =============================================================================


class WebhookClient:
    """HTTP client for sending webhook notifications.

    Handles secure webhook delivery with HMAC signatures, configurable
    timeouts, and retry logic. Supports both sync and async interfaces.

    Attributes:
        url: The webhook endpoint URL.
        secret: Optional shared secret for HMAC signatures.
        timeout: Request timeout in seconds.
        max_retries: Maximum retry attempts for failed deliveries.

    Example:
        >>> # Basic usage
        >>> client = WebhookClient("https://example.com/webhook")
        >>> result = await client.send({"event": "test"})

        >>> # With authentication
        >>> client = WebhookClient(
        ...     url="https://example.com/webhook",
        ...     secret="shared_secret",
        ...     timeout=10.0
        ... )
        >>> result = await client.send({"event": "task.completed"})
    """

    def __init__(
        self,
        url: str,
        secret: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        verify_ssl: bool = True,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize the webhook client.

        Args:
            url: The webhook endpoint URL.
            secret: Optional shared secret for HMAC signature generation.
            timeout: Request timeout in seconds (default 30).
            max_retries: Maximum retry attempts (default 3).
            retry_delay: Base delay between retries in seconds (default 1).
            verify_ssl: Whether to verify SSL certificates (default True).
            headers: Additional headers to include in requests.

        Raises:
            ValueError: If URL is empty or invalid.
        """
        if not url:
            raise ValueError("Webhook URL cannot be empty")

        self.url = url
        self.secret = secret
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.verify_ssl = verify_ssl
        self.headers = headers or {}

        # Validate URL format
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid webhook URL scheme: {url}")

    @classmethod
    def from_config(cls, config: WebhookClientConfig) -> WebhookClient:
        """Create a WebhookClient from a configuration object.

        Args:
            config: Configuration for the webhook client.

        Returns:
            Configured WebhookClient instance.
        """
        return cls(
            url=config.url,
            secret=config.secret,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_delay=config.retry_delay,
            verify_ssl=config.verify_ssl,
            headers=config.headers,
        )

    def _prepare_payload(
        self,
        data: dict[str, Any],
        event_type: str | None = None,
        delivery_id: str | None = None,
    ) -> tuple[bytes, dict[str, str], str | None]:
        """Prepare the payload and headers for delivery.

        Args:
            data: The data to send.
            event_type: Optional event type for the X-Webhook-Event header.
            delivery_id: Optional delivery ID.

        Returns:
            Tuple of (payload_bytes, headers, signature).
        """
        # Serialize payload to JSON
        payload = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")

        # Build headers
        headers = {
            "Content-Type": "application/json",
            **self.headers,
        }

        # Add timestamp
        timestamp = str(int(time.time()))
        headers[HEADER_TIMESTAMP] = timestamp

        # Add event type if provided
        if event_type:
            headers[HEADER_EVENT_TYPE] = event_type

        # Add delivery ID if provided
        if delivery_id:
            headers[HEADER_DELIVERY_ID] = delivery_id

        # Generate signature if secret is configured
        signature = None
        if self.secret:
            # Sign timestamp + payload for replay protection
            signed_payload = f"{timestamp}.".encode() + payload
            signature = generate_signature(signed_payload, self.secret)
            headers[HEADER_SIGNATURE_256] = signature
            # Also include the simpler signature for backward compatibility
            headers[HEADER_SIGNATURE] = generate_signature(payload, self.secret)

        return payload, headers, signature

    async def send(
        self,
        data: dict[str, Any],
        event_type: str | None = None,
        delivery_id: str | None = None,
    ) -> WebhookDeliveryResult:
        """Send webhook payload asynchronously.

        Sends the data as JSON via HTTP POST with optional HMAC signature.
        Automatically retries on transient failures.

        Args:
            data: Dictionary to send as JSON payload.
            event_type: Optional event type (included in X-Webhook-Event header).
            delivery_id: Optional unique delivery identifier.

        Returns:
            WebhookDeliveryResult with delivery status and details.

        Raises:
            WebhookTimeoutError: If all retry attempts timed out.
            WebhookConnectionError: If connection failed.
            WebhookDeliveryError: If delivery failed with a non-retryable error.
        """
        payload, headers, signature = self._prepare_payload(data, event_type, delivery_id)

        start_time = time.time()
        last_error: Exception | None = None
        attempt = 0

        async with httpx.AsyncClient(verify=self.verify_ssl) as client:
            while attempt < self.max_retries:
                attempt += 1
                try:
                    response = await client.post(
                        self.url,
                        content=payload,
                        headers=headers,
                        timeout=self.timeout,
                    )

                    delivery_time_ms = (time.time() - start_time) * 1000

                    # Success on 2xx status codes
                    if 200 <= response.status_code < 300:
                        logger.debug(
                            "Webhook delivered successfully",
                            extra={
                                "url": self.url,
                                "status": response.status_code,
                                "delivery_time_ms": delivery_time_ms,
                            },
                        )
                        return WebhookDeliveryResult(
                            success=True,
                            status_code=response.status_code,
                            response_body=response.text,
                            delivery_time_ms=delivery_time_ms,
                            attempt_count=attempt,
                            signature=signature,
                            delivery_id=delivery_id,
                        )

                    # Retryable status codes: 429, 500, 502, 503, 504
                    if response.status_code in (429, 500, 502, 503, 504):
                        last_error = WebhookDeliveryError(
                            f"Webhook returned {response.status_code}",
                            url=self.url,
                            status_code=response.status_code,
                            response_body=response.text,
                        )
                        logger.warning(
                            "Webhook delivery failed, will retry",
                            extra={
                                "url": self.url,
                                "status": response.status_code,
                                "attempt": attempt,
                                "max_retries": self.max_retries,
                            },
                        )
                        await self._wait_before_retry(attempt)
                        continue

                    # Non-retryable error (4xx except 429)
                    delivery_time_ms = (time.time() - start_time) * 1000
                    return WebhookDeliveryResult(
                        success=False,
                        status_code=response.status_code,
                        response_body=response.text,
                        delivery_time_ms=delivery_time_ms,
                        attempt_count=attempt,
                        signature=signature,
                        delivery_id=delivery_id,
                        error=f"HTTP {response.status_code}: {response.text[:200] if response.text else ''}",
                    )

                except httpx.TimeoutException:
                    last_error = WebhookTimeoutError(self.url, self.timeout)
                    logger.warning(
                        "Webhook delivery timed out, will retry",
                        extra={
                            "url": self.url,
                            "timeout": self.timeout,
                            "attempt": attempt,
                        },
                    )
                    await self._wait_before_retry(attempt)

                except httpx.ConnectError as e:
                    last_error = WebhookConnectionError(self.url, e)
                    logger.warning(
                        "Webhook connection failed, will retry",
                        extra={
                            "url": self.url,
                            "error": str(e),
                            "attempt": attempt,
                        },
                    )
                    await self._wait_before_retry(attempt)

                except httpx.RequestError as e:
                    last_error = WebhookDeliveryError(
                        f"Request failed: {e}",
                        url=self.url,
                    )
                    logger.warning(
                        "Webhook request failed, will retry",
                        extra={
                            "url": self.url,
                            "error": str(e),
                            "attempt": attempt,
                        },
                    )
                    await self._wait_before_retry(attempt)

        # All retries exhausted
        delivery_time_ms = (time.time() - start_time) * 1000
        error_msg = str(last_error) if last_error else "All retry attempts exhausted"

        logger.error(
            "Webhook delivery failed after all retries",
            extra={
                "url": self.url,
                "attempts": attempt,
                "error": error_msg,
            },
        )

        return WebhookDeliveryResult(
            success=False,
            delivery_time_ms=delivery_time_ms,
            attempt_count=attempt,
            signature=signature,
            delivery_id=delivery_id,
            error=error_msg,
        )

    def send_sync(
        self,
        data: dict[str, Any],
        event_type: str | None = None,
        delivery_id: str | None = None,
    ) -> WebhookDeliveryResult:
        """Send webhook payload synchronously.

        Synchronous version of send() for use in non-async contexts.

        Args:
            data: Dictionary to send as JSON payload.
            event_type: Optional event type (included in X-Webhook-Event header).
            delivery_id: Optional unique delivery identifier.

        Returns:
            WebhookDeliveryResult with delivery status and details.
        """
        payload, headers, signature = self._prepare_payload(data, event_type, delivery_id)

        start_time = time.time()
        last_error: Exception | None = None
        attempt = 0

        with httpx.Client(verify=self.verify_ssl) as client:
            while attempt < self.max_retries:
                attempt += 1
                try:
                    response = client.post(
                        self.url,
                        content=payload,
                        headers=headers,
                        timeout=self.timeout,
                    )

                    delivery_time_ms = (time.time() - start_time) * 1000

                    # Success on 2xx status codes
                    if 200 <= response.status_code < 300:
                        return WebhookDeliveryResult(
                            success=True,
                            status_code=response.status_code,
                            response_body=response.text,
                            delivery_time_ms=delivery_time_ms,
                            attempt_count=attempt,
                            signature=signature,
                            delivery_id=delivery_id,
                        )

                    # Retryable status codes
                    if response.status_code in (429, 500, 502, 503, 504):
                        last_error = WebhookDeliveryError(
                            f"Webhook returned {response.status_code}",
                            url=self.url,
                            status_code=response.status_code,
                            response_body=response.text,
                        )
                        self._wait_before_retry_sync(attempt)
                        continue

                    # Non-retryable error
                    delivery_time_ms = (time.time() - start_time) * 1000
                    return WebhookDeliveryResult(
                        success=False,
                        status_code=response.status_code,
                        response_body=response.text,
                        delivery_time_ms=delivery_time_ms,
                        attempt_count=attempt,
                        signature=signature,
                        delivery_id=delivery_id,
                        error=f"HTTP {response.status_code}",
                    )

                except httpx.TimeoutException:
                    last_error = WebhookTimeoutError(self.url, self.timeout)
                    self._wait_before_retry_sync(attempt)

                except httpx.ConnectError as e:
                    last_error = WebhookConnectionError(self.url, e)
                    self._wait_before_retry_sync(attempt)

                except httpx.RequestError as e:
                    last_error = WebhookDeliveryError(f"Request failed: {e}", url=self.url)
                    self._wait_before_retry_sync(attempt)

        # All retries exhausted
        delivery_time_ms = (time.time() - start_time) * 1000
        error_msg = str(last_error) if last_error else "All retry attempts exhausted"

        return WebhookDeliveryResult(
            success=False,
            delivery_time_ms=delivery_time_ms,
            attempt_count=attempt,
            signature=signature,
            delivery_id=delivery_id,
            error=error_msg,
        )

    async def _wait_before_retry(self, attempt: int) -> None:
        """Wait before retrying with exponential backoff.

        Args:
            attempt: Current attempt number (1-indexed).
        """
        import asyncio

        # Exponential backoff: delay * 2^(attempt-1)
        delay = self.retry_delay * (2 ** (attempt - 1))
        # Cap at 30 seconds
        delay = min(delay, 30.0)
        await asyncio.sleep(delay)

    def _wait_before_retry_sync(self, attempt: int) -> None:
        """Wait before retrying with exponential backoff (sync version).

        Args:
            attempt: Current attempt number (1-indexed).
        """
        # Exponential backoff: delay * 2^(attempt-1)
        delay = self.retry_delay * (2 ** (attempt - 1))
        # Cap at 30 seconds
        delay = min(delay, 30.0)
        time.sleep(delay)

    def __repr__(self) -> str:
        """Return string representation of the client."""
        return (
            f"WebhookClient(url={self.url!r}, "
            f"has_secret={self.secret is not None}, "
            f"timeout={self.timeout})"
        )
