"""Regression: the mcp<2 bound must apply to a base install, not just [mcp]."""

from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _pyproject() -> dict:
    return tomllib.loads(_PYPROJECT.read_text())


class TestMcpUpperBoundIsUnconditional:
    """mcp is not optional in practice, so its upper bound must not be either.

    `claude-agent-sdk` depends on mcp (allowing <3), so mcp lands in EVERY
    install, and the `claudetm-mcp` console script ships unconditionally. In
    v0.1.90 the `<2` bound sat only on the `[mcp]` extra, so a plain
    `uv tool install claude-task-master` resolved mcp 2.1.1 and `create_server()`
    failed — 2.x removed `mcp.server.fastmcp`.
    """

    def test_base_dependencies_bound_mcp_below_2(self) -> None:
        deps = _pyproject()["project"]["dependencies"]
        mcp = [d for d in deps if d.split(">")[0].split("<")[0].split("=")[0].strip() == "mcp"]
        assert mcp, "mcp must be a base dependency so its upper bound always applies"
        assert "<2" in mcp[0], f"base mcp requirement must cap below 2.x, got {mcp[0]!r}"

    def test_mcp_extra_also_bound(self) -> None:
        extra = _pyproject()["project"]["optional-dependencies"]["mcp"]
        assert any("<2" in d for d in extra), f"[mcp] extra must cap below 2.x, got {extra!r}"

    def test_sdk_alone_would_not_bound_it(self) -> None:
        """Documents why the base bound is required rather than inherited."""
        from importlib.metadata import requires

        sdk = [r for r in (requires("claude-agent-sdk") or []) if r.startswith("mcp")]
        assert sdk, "claude-agent-sdk is expected to depend on mcp"
        assert "<2" not in sdk[0], (
            "claude-agent-sdk no longer allows mcp 2.x; the base bound may be "
            f"revisitable, but do not remove it silently. SDK pin: {sdk[0]!r}"
        )


class TestUnavailableMessage:
    """A wrong-major-version mcp must not be reported as a missing package."""

    def test_message_names_the_installed_version(self) -> None:
        from claude_task_master.mcp.server import _mcp_unavailable_message

        msg = _mcp_unavailable_message()
        assert "mcp<2" in msg
        # mcp IS installed in this venv, so the message must not claim otherwise.
        assert "not installed" not in msg
        assert "incompatible" in msg
