"""SSRF-protection and header-sanitisation helpers for webhook delivery.

Extracted from routes_webhooks.py so the security logic can be tested
independently and reused without pulling in FastAPI router machinery.

The SSRF URL check (``_url_ssrf_error``) and DNS resolution (``_resolve_host``)
live in routes_webhooks.py, not here: they must be defined in that module's
namespace so ``monkeypatch.setattr(rw, "_resolve_host", ...)`` intercepts the
calls made there. The IP classifier and header helpers are shared from this module.
"""

from __future__ import annotations

import ipaddress

__all__ = [
    "_HOP_BY_HOP_HEADERS",
    "_SENSITIVE_HEADER_MARKERS",
    "_MASKED_VALUE",
    "_mask_headers",
    "_strip_hop_headers",
    "_is_blocked_ip",
]

# Hop-by-hop headers (RFC 7230 §6.1) plus routing headers that must never be
# smuggled from a user-supplied webhook config into an outbound request.
_HOP_BY_HOP_HEADERS: frozenset[str] = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)

# Substrings that mark a header as carrying a credential; matched case-insensitively.
_SENSITIVE_HEADER_MARKERS: tuple[str, ...] = (
    "authorization",
    "auth",
    "token",
    "secret",
    "cookie",
    "password",
    "credential",
    "signature",
    "api-key",
    "apikey",
    "x-key",
)

# Placeholder shown instead of a sensitive header value.
_MASKED_VALUE = "***"


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redact credential-bearing header values for safe display.

    Header names are preserved so operators can see which headers are configured,
    but values of credential headers (e.g. ``Authorization: Bearer ...``) are
    replaced with a placeholder to avoid leaking bearer tokens/secrets.

    Args:
        headers: The stored header mapping.

    Returns:
        A new mapping with sensitive values masked.
    """
    masked: dict[str, str] = {}
    for name, value in headers.items():
        lowered = name.lower()
        if any(marker in lowered for marker in _SENSITIVE_HEADER_MARKERS):
            masked[name] = _MASKED_VALUE
        else:
            masked[name] = value
    return masked


def _strip_hop_headers(headers: dict[str, str]) -> dict[str, str]:
    """Drop hop-by-hop/routing headers before an outbound request.

    Prevents a stored webhook config from smuggling connection-control or
    ``Host`` headers into the request the server makes on its behalf.

    Args:
        headers: The stored header mapping.

    Returns:
        A new mapping without hop-by-hop headers.
    """
    return {
        name: value for name, value in headers.items() if name.lower() not in _HOP_BY_HOP_HEADERS
    }


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if an IP is private, loopback, link-local, or otherwise reserved.

    Args:
        ip: The parsed IP address to classify.

    Returns:
        True if the address must not be reachable via a server-side request.
    """
    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:169.254.169.254) before classifying.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )
