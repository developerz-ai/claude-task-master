"""Transport-neutral result type shared by the REST and MCP service layer.

The task-master exposes the same operations over two very different transports:
a FastAPI REST API (which must map outcomes to HTTP status codes and typed
response models) and an MCP server (which must map them to plain ``dict``
payloads). Historically each transport re-implemented the *business* logic --
existence checks, state loading, control transitions -- and then string-sniffed
the other's error messages to pick a status code.

:class:`ServiceResult` breaks that coupling: a service method returns a single
:class:`ServiceOutcome` plus a neutral ``data`` payload, and each transport
*translates* that outcome into its own shape. REST maps
:attr:`ServiceOutcome.NOT_FOUND` to ``404``; MCP maps it to
``{"success": False, ...}``. Neither transport re-derives the decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class ServiceOutcome(StrEnum):
    """Transport-neutral classification of a service operation's result.

    Each transport owns the mapping from an outcome to its wire representation
    (HTTP status code for REST, ``success`` flag + error code for MCP), so the
    service layer never needs to know which transport is calling it.

    Attributes:
        OK: The operation succeeded. REST -> ``200``.
        NOT_FOUND: The target (task, plan, log, directory) does not exist.
            REST -> ``404``.
        INVALID: The request was well-formed but not permitted in the current
            state, or carried invalid values. REST -> ``400``.
        CONFLICT: The operation conflicts with existing state (e.g. a task
            already exists). REST -> ``400`` (kept distinct from ``INVALID`` so
            transports can emit a specific error code such as ``task_exists``).
        FORBIDDEN: The operation is refused for authorization reasons (e.g. a
            repo operation while authentication is disabled). REST -> ``403``.
        ERROR: An unexpected internal failure occurred. REST -> ``500``.
    """

    OK = "ok"
    NOT_FOUND = "not_found"
    INVALID = "invalid"
    CONFLICT = "conflict"
    FORBIDDEN = "forbidden"
    ERROR = "error"


@dataclass
class ServiceResult:
    """Outcome of a service operation, plus a transport-neutral payload.

    Attributes:
        outcome: The :class:`ServiceOutcome` classifying the result.
        data: Success payload (loaded state, control-transition details, the raw
            tool dict for repo operations, ...). Empty for pure errors.
        message: A human-readable summary. For control operations this is the
            authoritative message from ``ControlManager``; both transports
            surface it verbatim.
        error: Error detail for non-``OK`` outcomes (typically ``str(exc)``).
    """

    outcome: ServiceOutcome
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    error: str | None = None

    @property
    def success(self) -> bool:
        """Whether the operation succeeded (:attr:`ServiceOutcome.OK`)."""
        return self.outcome is ServiceOutcome.OK

    # -------------------------------------------------------------------------
    # Constructors -- one per outcome, so call sites read as intent.
    # -------------------------------------------------------------------------

    @classmethod
    def ok(cls, data: dict[str, Any] | None = None, message: str = "") -> ServiceResult:
        """Build a successful result carrying ``data`` and an optional message."""
        return cls(ServiceOutcome.OK, data=data or {}, message=message)

    @classmethod
    def not_found(
        cls,
        message: str = "",
        *,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> ServiceResult:
        """Build a :attr:`ServiceOutcome.NOT_FOUND` result."""
        return cls(ServiceOutcome.NOT_FOUND, data=data or {}, message=message, error=error)

    @classmethod
    def invalid(
        cls,
        message: str = "",
        *,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> ServiceResult:
        """Build an :attr:`ServiceOutcome.INVALID` result."""
        return cls(ServiceOutcome.INVALID, data=data or {}, message=message, error=error)

    @classmethod
    def conflict(
        cls,
        message: str = "",
        *,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> ServiceResult:
        """Build a :attr:`ServiceOutcome.CONFLICT` result."""
        return cls(ServiceOutcome.CONFLICT, data=data or {}, message=message, error=error)

    @classmethod
    def forbidden(
        cls,
        message: str = "",
        *,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> ServiceResult:
        """Build a :attr:`ServiceOutcome.FORBIDDEN` result."""
        return cls(ServiceOutcome.FORBIDDEN, data=data or {}, message=message, error=error)

    @classmethod
    def failed(
        cls,
        message: str = "",
        *,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> ServiceResult:
        """Build an :attr:`ServiceOutcome.ERROR` (unexpected failure) result."""
        return cls(ServiceOutcome.ERROR, data=data or {}, message=message, error=error)
