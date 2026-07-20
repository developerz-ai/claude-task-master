"""SSRF-protection and header-sanitisation helpers for webhook delivery.

Extracted from routes_webhooks.py so the security logic can be tested
independently and reused without pulling in FastAPI router machinery.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

__all__ = [
    "_HOP_BY_HOP_HEADERS",
    "_SENSITIVE_HEADER_MARKERS",
    "_MASKED_VALUE",
    "_mask_headers",
    "_strip_hop_headers",
    "_resolve_host",
    "_is_blocked_ip",
    "_url_ssrf_error",
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


def _resolve_host(host: str) -> list[str]:
    """Resolve a hostname to all of its IP addresses.

    Numeric IP literals are returned as-is (no network I/O). Extracted as a
    module-level function so tests can stub DNS resolution.

    Args:
        host: The hostname or IP literal to resolve.

    Returns:
        List of resolved IP address strings.

    Raises:
        OSError: If resolution fails (e.g. unknown host).
    """
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    # sockaddr[0] is the address string (typeshed widens it to str | int).
    return [str(info[4][0]) for info in infos]


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


def _url_ssrf_error(url: str) -> str | None:
    """Validate that a URL's host resolves only to public addresses.

    Resolves the host post-DNS and rejects the request if any resolved address
    falls in a private/loopback/link-local/reserved range. This blocks SSRF to
    cloud metadata endpoints (169.254.169.254), localhost, and internal networks
    even when the attacker hides behind a hostname.

    Note:
        This is a pre-connection screen, not a pinned resolution: it validates a
        fresh DNS lookup but does not bind the caller's later HTTP connection to
        the vetted address, so a rebinding host could resolve differently at
        connect time (a TOCTOU window). It gates the authenticated
        ``POST /webhooks/test`` endpoint as defense-in-depth. Fully closing the
        rebinding window requires pinning the connection to the vetted IP while
        preserving the original Host header and TLS SNI/cert hostname; that is
        tracked as separate hardening rather than bundled into this refactor.

    Args:
        url: The target URL.

    Returns:
        An error message if the target is not permitted, otherwise None.
    """
    host = urlparse(url).hostname
    if not host:
        return "URL has no host"
    try:
        addresses = _resolve_host(host)
    except OSError:
        return f"Could not resolve host: {host}"
    if not addresses:
        return f"Could not resolve host: {host}"
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return f"Invalid resolved address: {addr}"
        if _is_blocked_ip(ip):
            return (
                f"Target resolves to a non-public address ({addr}); "
                "private, loopback, link-local, and reserved ranges are blocked"
            )
    return None
