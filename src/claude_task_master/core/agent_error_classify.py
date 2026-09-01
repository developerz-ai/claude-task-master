"""Map a raw SDK exception onto a typed :class:`AgentError`.

The classification decides whether an unattended run **retries or dies**:
:data:`~.agent_exceptions.TRANSIENT_ERRORS` members are retried under the
failure budget, everything else propagates. Getting it wrong in either
direction is expensive, so this module prefers the structured payload the SDK
now hands us and falls back to prose only when there is none.

Two sources, in order:

1. **The result payload.** ``claude-agent-sdk`` >= 0.2.140 raises ``ResultError``
   (a ``ProcessError`` subclass) when the CLI exits after a terminal error
   result, carrying ``api_error_status``, ``subtype``, ``terminal_reason``,
   ``errors`` and ``result``. An HTTP status is a fact; a substring is a guess.
   The fields are read with ``getattr`` rather than by importing the SDK — this
   module must stay importable with ``claude_agent_sdk`` absent, which the
   suite exercises by patching it out of ``sys.modules``.

2. **The message text**, for every other exception shape. Note that
   ``str(ResultError)`` is only ``"Claude Code returned an error result:
   <subtype> (exit code: 1)"`` — the prose that names the actual failure
   ("Connection closed mid-response", "API Error: 529 overloaded_error") lives
   in ``errors``/``result``. So the payload is folded into the searched text
   too, which is what lets a text rule fire on a ``ResultError`` at all.

The text rules are matched on **token boundaries**, not raw substrings. Two
misclassifications lived in the loose version, both of them one-way:

- ``"500" in text`` also matched ``"request took 1500ms"``, turning a latency
  message into a retryable :class:`APIServerError`.
- ``"auth" in text`` also matched ``"Co-Authored-By"`` — which appears in every
  commit message this project writes — turning any error that echoed a git
  command into a *non*-retryable :class:`APIAuthenticationError` that ends the
  run.

A bare ``401``/``403`` is the same trap one step further in: because the payload
prose is searched, echoed command output such as ``"wrote 403 bytes"`` would
match. Status matching for auth therefore requires a status-like word nearby,
while the 5xx rule does not need to — a false 5xx is retried, a false auth kills
the run.
"""

from __future__ import annotations

import re
from typing import Any

from .agent_exceptions import (
    AgentError,
    APIAuthenticationError,
    APIConnectionError,
    APIRateLimitError,
    APIServerError,
    APITimeoutError,
    ContentFilterError,
    ModelUnavailableError,
    QueryExecutionError,
)

__all__ = ["classify_api_error", "result_error_fields", "searchable_error_text"]

#: A standalone HTTP 5xx status, not a digit inside a larger number.
_SERVER_STATUS_RE = re.compile(r"(?<!\d)(5\d\d)(?!\d)")

#: 401/403 preceded by a status-like word, never a bare number.
#:
#: Digit boundaries alone are not enough *here*, and the asymmetry with the 5xx
#: rule is deliberate. The searched text now includes the ``result``/``errors``
#: payload, which routinely carries tool and command output — so "wrote 403
#: bytes" or "exit 401" would match a bare-number rule. A false 5xx is merely
#: retried; a false auth error is **not** retryable and ends an unattended run,
#: so this side has to be the strict one.
_AUTH_STATUS_RE = re.compile(
    r"\b(?:http|https|status|code|error|response)\b[^0-9\n]{0,12}(?<!\d)(?:401|403)(?!\d)",
    re.IGNORECASE,
)

#: Auth phrasings, whole words only — never a bare ``auth`` substring.
_AUTH_RE = re.compile(
    r"\b(?:unauthorized|unauthenticated|authentication|authenticate|oauth"
    r"|forbidden|invalid[ _-]api[ _-]key|not logged in|credentials?)\b",
    re.IGNORECASE,
)

#: Statuses that describe a timeout rather than a generic server fault.
_TIMEOUT_STATUSES: frozenset[int] = frozenset({408, 504})

#: Default attributed to a text-derived timeout, matching the SDK's own.
_DEFAULT_TIMEOUT_SEC = 30.0


def result_error_fields(error: Exception) -> dict[str, Any]:
    """Structured fields off a ``ResultError``, empty for anything else.

    Duck-typed on purpose: importing ``claude_agent_sdk`` here would make error
    classification depend on the SDK being importable, which is exactly the
    situation some of these errors describe.

    Args:
        error: The raw exception from the SDK stream.

    Returns:
        A dict with any of ``api_error_status`` (int), ``subtype``,
        ``terminal_reason``, ``result`` (str) and ``errors`` (list[str]) that
        the exception actually carries, with wrong-typed values dropped.
    """
    fields: dict[str, Any] = {}

    status = getattr(error, "api_error_status", None)
    # bool is an int subclass; a True here would read as HTTP status 1.
    if isinstance(status, int) and not isinstance(status, bool):
        fields["api_error_status"] = status

    for name in ("subtype", "terminal_reason", "result"):
        value = getattr(error, name, None)
        if isinstance(value, str) and value:
            fields[name] = value

    errors = getattr(error, "errors", None)
    if isinstance(errors, list):
        strings = [e for e in errors if isinstance(e, str) and e]
        if strings:
            fields["errors"] = strings

    return fields


def searchable_error_text(error: Exception, fields: dict[str, Any]) -> str:
    """Lower-cased text to match rules against: the message plus its payload.

    ``str(ResultError)`` names only the subtype, so matching on it alone throws
    away the one string that says what went wrong.

    Args:
        error: The raw exception.
        fields: The result of :func:`result_error_fields`.

    Returns:
        A single lower-cased string safe to run substring and regex rules over.
    """
    parts = [str(error)]
    result = fields.get("result")
    if result:
        parts.append(result)
    parts.extend(fields.get("errors", ()))
    return "\n".join(parts).lower()


def _classify_status(status: int, text: str, error: Exception) -> AgentError | None:
    """Map an HTTP status from the result payload onto a typed error.

    Args:
        status: ``api_error_status`` as reported by the CLI.
        text: The searchable error text, for the one status that needs it.
        error: The raw exception, carried through as the typed error's cause so
            logs still show what the SDK actually said.

    Returns:
        The typed error, or None when the status carries no useful verdict and
        the text rules should have their turn.
    """
    if status == 429:
        return APIRateLimitError(getattr(error, "retry_after", None), error)
    if status in (401, 403):
        return APIAuthenticationError(error)
    if status == 404:
        # 404 is Anthropic's answer to an unknown model id. Only a model 404
        # routes to the fallback chain; any other 404 is not a model problem.
        if "model" in text:
            return ModelUnavailableError(error)
        return None
    if status in _TIMEOUT_STATUSES:
        # A gateway timeout is a timeout first and a 5xx second: the retry is
        # the same, but the message should say what actually happened.
        return APITimeoutError(_DEFAULT_TIMEOUT_SEC, error)
    if 500 <= status <= 599:
        # 529 (overloaded) lands here, which is the common real case and one
        # the text rules missed entirely — it is absent from str(ResultError).
        return APIServerError(status, error)
    return None


def _classify_text(error: Exception, text: str) -> AgentError:
    """Classify from the message text. Always returns something.

    Args:
        error: The raw exception, attached to the typed error as its cause.
        text: The searchable error text (already lower-cased).

    Returns:
        A typed :class:`AgentError`; :class:`QueryExecutionError` when no rule
        matches, which the retry layer treats as retryable-but-unclassified.
    """
    error_type = type(error).__name__

    if "content filtering" in text or "output blocked" in text:
        return ContentFilterError(error)

    # Require "model" *and* a not-found keyword, so "503 Service Unavailable"
    # and "Network unreachable" are not read as a bad model id.
    if "model" in text and any(
        kw in text
        for kw in ("not_found", "not found", "does not exist", "unavailable", "invalid model")
    ):
        return ModelUnavailableError(error)

    if "rate" in text and "limit" in text:
        return APIRateLimitError(getattr(error, "retry_after", None), error)

    if _AUTH_RE.search(text) or _AUTH_STATUS_RE.search(text):
        return APIAuthenticationError(error)

    if (
        "timeout" in text
        or "timed out" in text
        or error_type in ("TimeoutError", "AsyncioTimeoutError")
    ):
        return APITimeoutError(_DEFAULT_TIMEOUT_SEC, error)

    if any(kw in text for kw in ("connect", "connection", "network")):
        return APIConnectionError(error)

    match = _SERVER_STATUS_RE.search(text)
    if match:
        return APIServerError(int(match.group(1)), error)

    return QueryExecutionError(f"API error: {error}", error)


def classify_api_error(error: Exception) -> AgentError:
    """Classify a raw SDK exception into a typed :class:`AgentError`.

    Args:
        error: The exception raised out of the SDK query stream.

    Returns:
        A typed error. Membership in ``TRANSIENT_ERRORS`` is what decides
        whether the caller retries.
    """
    fields = result_error_fields(error)
    text = searchable_error_text(error, fields)

    status = fields.get("api_error_status")
    if isinstance(status, int):
        classified = _classify_status(status, text, error)
        if classified is not None:
            return classified

    return _classify_text(error, text)
