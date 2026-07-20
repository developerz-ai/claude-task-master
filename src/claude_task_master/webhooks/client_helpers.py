"""Delivery-helper methods mixin for WebhookClient.

Provides :class:`_WebhookClientHelpersMixin` with all the shared helper
methods used by both :meth:`WebhookClient.send` and
:meth:`WebhookClient.send_sync`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from .client_types import (
    HEADER_DELIVERY_ID,
    HEADER_EVENT_TYPE,
    HEADER_SIGNATURE,
    HEADER_SIGNATURE_256,
    HEADER_TIMESTAMP,
    MAX_RETRY_DELAY,
    WebhookDeliveryError,
    WebhookDeliveryResult,
    generate_signature,
)

logger = logging.getLogger(__name__)


class _WebhookClientHelpersMixin:
    """Mixin providing shared delivery helpers to WebhookClient.

    Concrete attribute stubs satisfy mypy; values are provided by WebhookClient.
    """

    url: str
    secret: str | None
    timeout: float
    max_retries: int
    retry_delay: float
    verify_ssl: bool
    headers: dict[str, str]

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
        headers: dict[str, str] = {
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

    def _should_retry(self, attempt: int) -> bool:
        """Return whether another attempt remains after the given one.

        Args:
            attempt: The attempt just completed (1-indexed). With the loop bound
                ``attempt <= max_retries``, another attempt runs iff this holds.

        Returns:
            True if a further retry will be made, False if attempts are exhausted.
        """
        return attempt <= self.max_retries

    def _success_result(
        self,
        response: httpx.Response,
        start_time: float,
        attempt: int,
        signature: str | None,
        delivery_id: str | None,
    ) -> WebhookDeliveryResult:
        """Build a successful delivery result from a 2xx response."""
        return WebhookDeliveryResult(
            success=True,
            status_code=response.status_code,
            response_body=response.text,
            delivery_time_ms=(time.time() - start_time) * 1000,
            attempt_count=attempt,
            signature=signature,
            delivery_id=delivery_id,
        )

    def _http_error_result(
        self,
        response: httpx.Response,
        start_time: float,
        attempt: int,
        signature: str | None,
        delivery_id: str | None,
    ) -> WebhookDeliveryResult:
        """Build a failed result for a non-retryable HTTP status (4xx except 429)."""
        body = response.text or ""
        return WebhookDeliveryResult(
            success=False,
            status_code=response.status_code,
            response_body=response.text,
            delivery_time_ms=(time.time() - start_time) * 1000,
            attempt_count=attempt,
            signature=signature,
            delivery_id=delivery_id,
            error=f"HTTP {response.status_code}: {body[:200]}",
        )

    def _exhausted_result(
        self,
        last_error: Exception | None,
        start_time: float,
        attempt: int,
        signature: str | None,
        delivery_id: str | None,
    ) -> WebhookDeliveryResult:
        """Build the terminal result after all retry attempts are exhausted."""
        error_msg = str(last_error) if last_error else "All retry attempts exhausted"
        logger.error(
            "Webhook delivery failed after all retries",
            extra={"url": self.url, "attempts": attempt, "error": error_msg},
        )
        return WebhookDeliveryResult(
            success=False,
            delivery_time_ms=(time.time() - start_time) * 1000,
            attempt_count=attempt,
            signature=signature,
            delivery_id=delivery_id,
            error=error_msg,
        )

    def _retryable_status_error(self, response: httpx.Response) -> WebhookDeliveryError:
        """Build the error recorded for a retryable HTTP status code."""
        return WebhookDeliveryError(
            f"Webhook returned {response.status_code}",
            url=self.url,
            status_code=response.status_code,
            response_body=response.text,
        )

    def _log_retry(self, message: str, attempt: int, error: Exception | None = None) -> None:
        """Log a transient delivery failure that will (or may) be retried."""
        extra: dict[str, Any] = {
            "url": self.url,
            "attempt": attempt,
            "max_retries": self.max_retries,
        }
        if error is not None:
            extra["error"] = str(error)
        logger.warning(message, extra=extra)

    def _backoff_delay(self, attempt: int) -> float:
        """Compute the exponential backoff delay for an attempt, capped.

        Args:
            attempt: Current attempt number (1-indexed).

        Returns:
            Delay in seconds: ``retry_delay * 2^(attempt-1)``, capped at
            :data:`MAX_RETRY_DELAY`.
        """
        return min(self.retry_delay * (2.0 ** (attempt - 1)), MAX_RETRY_DELAY)

    async def _wait_before_retry(self, attempt: int) -> None:
        """Wait before retrying with exponential backoff.

        Args:
            attempt: Current attempt number (1-indexed).
        """
        await asyncio.sleep(self._backoff_delay(attempt))

    def _wait_before_retry_sync(self, attempt: int) -> None:
        """Wait before retrying with exponential backoff (sync version).

        Args:
            attempt: Current attempt number (1-indexed).
        """
        time.sleep(self._backoff_delay(attempt))

    def __repr__(self) -> str:
        """Return string representation of the client."""
        return (
            f"WebhookClient(url={self.url!r}, "
            f"has_secret={self.secret is not None}, "
            f"timeout={self.timeout})"
        )


__all__ = ["_WebhookClientHelpersMixin"]
