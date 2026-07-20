"""Exceptions, dataclasses, constants, and HMAC helpers for WebhookClient.

Re-exported from :mod:`client` so callers can import from either location.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any

# Default configuration
DEFAULT_TIMEOUT = 30.0  # 30 seconds
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0  # 1 second base delay
MAX_RETRY_DELAY = 30.0  # Cap exponential backoff at 30 seconds

# HTTP status codes that warrant a retry (transient / rate-limited responses).
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

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


# Expose build_timestamp as a testable helper so callers can mock time.time
def _build_timestamp() -> str:
    """Return the current Unix timestamp as a string."""
    return str(int(time.time()))


__all__ = [
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_DELAY",
    "MAX_RETRY_DELAY",
    "RETRYABLE_STATUS_CODES",
    "HEADER_SIGNATURE",
    "HEADER_SIGNATURE_256",
    "HEADER_TIMESTAMP",
    "HEADER_DELIVERY_ID",
    "HEADER_EVENT_TYPE",
    "WebhookError",
    "WebhookDeliveryError",
    "WebhookTimeoutError",
    "WebhookConnectionError",
    "WebhookDeliveryResult",
    "WebhookClientConfig",
    "generate_signature",
    "verify_signature",
]
