"""Declarative registration of the MCP server's forwarding tools.

Most MCP task/mailbox tools do the same thing: inject the server's ``work_dir``
and forward every other argument to a matching function in
:mod:`claude_task_master.mcp.tools`. Hand-writing one ``@mcp.tool()`` wrapper per
tool meant the wrapper's parameter list could silently drift from the underlying
function -- e.g. the ``initialize_task`` wrapper omitted ``enable_verification``
so MCP clients could not set it even though the REST API and the tool itself
supported it.

:func:`register_forwarding_tool` removes that failure mode. It derives each MCP
tool's signature *from the underlying function* (dropping the injected
``work_dir``), so every parameter the tool accepts is exposed automatically and
the two can never fall out of sync. The registrations are driven by a plain
table of :class:`ForwardingSpec` values, one per tool.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP

# The injected parameter every forwarding tool supplies from server state rather
# than exposing to clients. It must be the underlying function's first parameter.
_INJECTED_PARAM = "work_dir"


@dataclass(frozen=True)
class ForwardingSpec:
    """One MCP tool that forwards to a synchronous ``tools`` function.

    Attributes:
        fn: The underlying :mod:`claude_task_master.mcp.tools` function. Its
            first parameter must be ``work_dir`` (injected by the server); every
            remaining parameter becomes an MCP tool parameter, derived
            automatically so the two signatures cannot drift.
        description: The description shown to MCP clients. Specified here rather
            than reused from ``fn.__doc__`` because the function's docstring
            documents the injected ``work_dir``, which clients never supply.
    """

    fn: Callable[..., dict[str, Any]]
    description: str


def register_forwarding_tool(mcp: FastMCP, spec: ForwardingSpec, *, work_dir: Path) -> None:
    """Register one forwarding tool on ``mcp``, injecting ``work_dir``.

    The generated wrapper's signature is the underlying function's signature with
    the leading ``work_dir`` parameter removed, so FastMCP builds the tool schema
    straight from the source of truth.

    Args:
        mcp: The FastMCP server to register the tool on.
        spec: The forwarding specification (underlying function + description).
        work_dir: The server working directory injected into every call.

    Raises:
        ValueError: If ``spec.fn``'s first parameter is not ``work_dir``.
    """
    fn = spec.fn
    # eval_str resolves the ``from __future__ import annotations`` string
    # annotations to real types using ``fn``'s module globals, so the generated
    # wrapper carries concrete types (not unresolved strings) for FastMCP.
    signature = inspect.signature(fn, eval_str=True)
    params = list(signature.parameters.values())
    if not params or params[0].name != _INJECTED_PARAM:
        raise ValueError(
            f"{fn.__name__} must take '{_INJECTED_PARAM}' as its first parameter "
            "to be registered as a forwarding tool"
        )

    exposed = params[1:]

    def wrapper(**kwargs: Any) -> dict[str, Any]:
        return fn(work_dir, **kwargs)

    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__name__
    wrapper.__doc__ = spec.description
    wrapper.__signature__ = signature.replace(parameters=exposed)  # type: ignore[attr-defined]
    annotations = {
        p.name: p.annotation for p in exposed if p.annotation is not inspect.Parameter.empty
    }
    if signature.return_annotation is not inspect.Signature.empty:
        annotations["return"] = signature.return_annotation
    wrapper.__annotations__ = annotations

    mcp.tool()(wrapper)


def register_forwarding_tools(
    mcp: FastMCP, specs: Iterable[ForwardingSpec], *, work_dir: Path
) -> None:
    """Register every :class:`ForwardingSpec` in ``specs`` on ``mcp``.

    Args:
        mcp: The FastMCP server to register the tools on.
        specs: The forwarding specifications to register.
        work_dir: The server working directory injected into every call.
    """
    for spec in specs:
        register_forwarding_tool(mcp, spec, work_dir=work_dir)
