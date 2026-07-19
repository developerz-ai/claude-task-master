"""Tests for the declarative MCP forwarding-tool table.

These are contract tests: they assert every generated MCP tool exposes exactly
the parameters of its underlying ``tools`` function (minus the injected
``work_dir``), so a wrapper can never silently drift from the function it
forwards to -- the class of bug that hid ``enable_verification`` from
``initialize_task`` and ``update_config``.

The pure generator tests (``TestRegisterForwardingTool``) exercise
``register_forwarding_tool`` without the MCP SDK; the schema tests build a real
server and are skipped when the SDK is unavailable.
"""

import asyncio
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from claude_task_master.mcp.tool_forwarding import (
    ForwardingSpec,
    register_forwarding_tool,
)

from .conftest import MCP_AVAILABLE


def _tools_by_name(temp_dir):
    """Build a server and return its tools keyed by name."""
    from claude_task_master.mcp.server import create_server

    server = create_server(working_dir=str(temp_dir))
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


class TestRegisterForwardingTool:
    """Unit tests for the wrapper generator (no MCP SDK required)."""

    def test_wrapper_injects_work_dir_and_forwards(self):
        """The wrapper hides work_dir, injects it, and forwards the rest."""
        captured = {}

        def fake_fn(work_dir, goal, model="opus"):
            return {"work_dir": work_dir, "goal": goal, "model": model}

        class FakeMCP:
            def tool(self):
                def decorator(fn):
                    captured["fn"] = fn
                    return fn

                return decorator

        register_forwarding_tool(
            FakeMCP(),  # type: ignore[arg-type]
            ForwardingSpec(fake_fn, "the description"),
            work_dir=Path("/wd"),
        )
        wrapper = captured["fn"]

        # work_dir is injected, never exposed to callers.
        assert set(inspect.signature(wrapper).parameters) == {"goal", "model"}
        assert wrapper(goal="g") == {"work_dir": Path("/wd"), "goal": "g", "model": "opus"}
        assert wrapper.__name__ == "fake_fn"
        assert wrapper.__doc__ == "the description"

    def test_rejects_function_without_leading_work_dir(self):
        """A function whose first parameter isn't work_dir is rejected."""

        def bad(goal: str) -> dict:
            return {}

        with pytest.raises(ValueError, match="work_dir"):
            register_forwarding_tool(MagicMock(), ForwardingSpec(bad, "d"), work_dir=Path("."))


@pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")
class TestForwardingTableSchemas:
    """Every forwarding tool's schema matches its underlying function exactly."""

    def test_each_tool_exposes_underlying_params(self, temp_dir):
        """Generated schema properties equal the underlying params minus work_dir."""
        from claude_task_master.mcp.server import _FORWARDING_SPECS

        tools_by_name = _tools_by_name(temp_dir)
        for spec in _FORWARDING_SPECS:
            expected = {
                name for name in inspect.signature(spec.fn).parameters if name != "work_dir"
            }
            tool = tools_by_name[spec.fn.__name__]
            actual = set(tool.inputSchema.get("properties", {}))
            assert actual == expected, f"{spec.fn.__name__} drifted: {actual} != {expected}"

    def test_initialize_task_exposes_enable_verification(self, temp_dir):
        """The drift that motivated the table: enable_verification is exposed."""
        props = _tools_by_name(temp_dir)["initialize_task"].inputSchema.get("properties", {})
        assert "enable_verification" in props
        assert "enable_release" in props

    def test_update_config_exposes_enable_verification(self, temp_dir):
        """update_config also exposes its full option set (same latent drift)."""
        props = _tools_by_name(temp_dir)["update_config"].inputSchema.get("properties", {})
        assert "enable_verification" in props

    def test_model_param_has_no_restrictive_pattern(self, temp_dir):
        """The model param is a plain string; validation is centralised, not a regex."""
        model = _tools_by_name(temp_dir)["initialize_task"].inputSchema["properties"]["model"]
        assert "pattern" not in model


@pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")
class TestRepoToolNaming:
    """Repo tools use work_dir, matching REST and the tools layer."""

    def test_setup_and_plan_use_work_dir(self, temp_dir):
        """setup_repo/plan_repo expose work_dir, not the drifted repo_dir."""
        tools_by_name = _tools_by_name(temp_dir)
        for name in ("setup_repo", "plan_repo"):
            props = tools_by_name[name].inputSchema.get("properties", {})
            assert "work_dir" in props, f"{name} missing work_dir"
            assert "repo_dir" not in props, f"{name} still exposes repo_dir"
