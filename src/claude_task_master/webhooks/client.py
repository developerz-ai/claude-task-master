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

Exceptions, dataclasses, constants, and HMAC helpers live in
:mod:`.client_types`. Shared delivery helpers live in :mod:`.client_helpers`.

Example:
    >>> client = WebhookClient(url="https://example.com/webhook", secret="mysecret")
    >>> result = await client.send({"event": "task.completed"})
    >>> print(result.success)
    True
"""

from __future__ import annotations

from typing import Any

import httpx

from .client_helpers import _WebhookClientHelpersMixin
from .client_types import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    DEFAULT_TIMEOUT,
    HEADER_DELIVERY_ID,  # noqa: F401 — re-exported for test patching
    HEADER_EVENT_TYPE,  # noqa: F401 — re-exported for test patching
    HEADER_SIGNATURE,  # noqa: F401 — re-exported for test patching
    HEADER_SIGNATURE_256,  # noqa: F401 — re-exported for test patching
    HEADER_TIMESTAMP,  # noqa: F401 — re-exported for test patching
    MAX_RETRY_DELAY,  # noqa: F401 — re-exported
    RETRYABLE_STATUS_CODES,
    WebhookClientConfig,
    WebhookConnectionError,
    WebhookDeliveryError,
    WebhookDeliveryResult,
    WebhookError,  # noqa: F401 — re-exported
    WebhookTimeoutError,
    generate_signature,  # noqa: F401 — re-exported
    verify_signature,  # noqa: F401 — re-exported
)


class WebhookClient(_WebhookClientHelpersMixin):
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
        import time  # noqa: PLC0415

        payload, headers, signature = self._prepare_payload(data, event_type, delivery_id)

        start_time = time.time()
        last_error: Exception | None = None
        attempt = 0

        # Total attempts = 1 initial try + ``max_retries`` retries.
        async with httpx.AsyncClient(verify=self.verify_ssl) as client:
            while attempt <= self.max_retries:
                attempt += 1
                try:
                    response = await client.post(
                        self.url,
                        content=payload,
                        headers=headers,
                        timeout=self.timeout,
                    )

                    # Success on 2xx status codes
                    if 200 <= response.status_code < 300:
                        result = self._success_result(
                            response, start_time, attempt, signature, delivery_id
                        )
                        import logging  # noqa: PLC0415

                        logging.getLogger(__name__).debug(
                            "Webhook delivered successfully",
                            extra={
                                "url": self.url,
                                "status": response.status_code,
                                "delivery_time_ms": result.delivery_time_ms,
                            },
                        )
                        return result

                    # Non-retryable error (4xx except 429): fail immediately.
                    if response.status_code not in RETRYABLE_STATUS_CODES:
                        return self._http_error_result(
                            response, start_time, attempt, signature, delivery_id
                        )

                    # Retryable status codes: 429, 500, 502, 503, 504
                    last_error = self._retryable_status_error(response)
                    self._log_retry("Webhook delivery failed, will retry", attempt)

                except httpx.TimeoutException:
                    last_error = WebhookTimeoutError(self.url, self.timeout)
                    self._log_retry("Webhook delivery timed out, will retry", attempt)

                except httpx.ConnectError as e:
                    last_error = WebhookConnectionError(self.url, e)
                    self._log_retry("Webhook connection failed, will retry", attempt, error=e)

                except httpx.RequestError as e:
                    last_error = WebhookDeliveryError(f"Request failed: {e}", url=self.url)
                    self._log_retry("Webhook request failed, will retry", attempt, error=e)

                # Only back off when another attempt actually remains.
                if self._should_retry(attempt):
                    await self._wait_before_retry(attempt)

        return self._exhausted_result(last_error, start_time, attempt, signature, delivery_id)

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
        import time  # noqa: PLC0415

        payload, headers, signature = self._prepare_payload(data, event_type, delivery_id)

        start_time = time.time()
        last_error: Exception | None = None
        attempt = 0

        # Total attempts = 1 initial try + ``max_retries`` retries.
        with httpx.Client(verify=self.verify_ssl) as client:
            while attempt <= self.max_retries:
                attempt += 1
                try:
                    response = client.post(
                        self.url,
                        content=payload,
                        headers=headers,
                        timeout=self.timeout,
                    )

                    # Success on 2xx status codes
                    if 200 <= response.status_code < 300:
                        return self._success_result(
                            response, start_time, attempt, signature, delivery_id
                        )

                    # Non-retryable error (4xx except 429): fail immediately.
                    if response.status_code not in RETRYABLE_STATUS_CODES:
                        return self._http_error_result(
                            response, start_time, attempt, signature, delivery_id
                        )

                    # Retryable status codes
                    last_error = self._retryable_status_error(response)
                    self._log_retry("Webhook delivery failed, will retry", attempt)

                except httpx.TimeoutException:
                    last_error = WebhookTimeoutError(self.url, self.timeout)
                    self._log_retry("Webhook delivery timed out, will retry", attempt)

                except httpx.ConnectError as e:
                    last_error = WebhookConnectionError(self.url, e)
                    self._log_retry("Webhook connection failed, will retry", attempt, error=e)

                except httpx.RequestError as e:
                    last_error = WebhookDeliveryError(f"Request failed: {e}", url=self.url)
                    self._log_retry("Webhook request failed, will retry", attempt, error=e)

                # Only back off when another attempt actually remains.
                if self._should_retry(attempt):
                    self._wait_before_retry_sync(attempt)

        return self._exhausted_result(last_error, start_time, attempt, signature, delivery_id)
