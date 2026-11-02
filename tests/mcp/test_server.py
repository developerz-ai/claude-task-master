"""Real-SDK regressions for MCP creation, transports, and network security."""

from collections.abc import Sequence
from unittest.mock import AsyncMock, patch

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.testclient import TestClient

from claude_task_master.auth.middleware import PasswordAuthMiddleware
from claude_task_master.mcp.server import create_server, run_server
from claude_task_master.mcp.server_runner import (
    _get_authenticated_app,
    _run_network_transport_async,
)

from .conftest import MCP_AVAILABLE

if MCP_AVAILABLE:
    # The conftest gate already proved the SDK is importable, so importing
    # the class under that guard keeps a genuinely missing SDK a skip, while
    # an installed-but-incompatible one still fails collection in the conftest.
    from mcp.server.mcpserver import MCPServer


def _route_paths(app: Starlette) -> set[str]:
    """Return the paths of the routes on *app* that carry one.

    ``Starlette.routes`` is a list of ``BaseRoute``; only the path-bearing
    subclasses (``Route``, ``WebSocketRoute``, ``Mount``) expose ``.path``.
    """
    return {route.path for route in app.routes if isinstance(route, (Route, WebSocketRoute, Mount))}


def _middleware_classes(app: Starlette) -> Sequence[object]:
    """Return the middleware classes installed on *app*.

    ``Middleware.cls`` is typed as a factory protocol, so the classes are
    handed back as plain objects: the identity check against a concrete
    middleware class stays exact without a false non-overlap report.
    """
    return [middleware.cls for middleware in app.user_middleware]


class TestMCPServerCreation:
    """Construction uses the supported SDK, not a fake or removed shim."""

    def test_create_server_returns_mcpserver_instance(self, temp_dir):
        server = create_server(working_dir=str(temp_dir))
        assert isinstance(server, MCPServer)
        assert server.name == "claude-task-master"

    def test_create_server_with_custom_name(self, temp_dir):
        server = create_server(name="custom-server", working_dir=str(temp_dir))
        assert isinstance(server, MCPServer)
        assert server.name == "custom-server"

    def test_incompatible_sdk_retains_import_evidence(self, temp_dir):
        with (
            patch("claude_task_master.mcp.server._MCP_IMPORT_ERROR", "missing MCPServer"),
            patch("importlib.metadata.version", return_value="1.28.1"),
            pytest.raises(ImportError) as excinfo,
        ):
            create_server(working_dir=str(temp_dir))
        message = str(excinfo.value)
        assert "MCP SDK 1.28.1 is installed but incompatible" in message
        assert "missing MCPServer" in message
        assert "mcp>=2.1.1,<3" in message
        assert "mcp<2" not in message
        assert "not installed" not in message

    def test_genuinely_missing_mcp_still_says_not_installed(self, temp_dir):
        with (
            patch("claude_task_master.mcp.server._MCP_IMPORT_ERROR", "No module named 'mcp'"),
            patch("importlib.metadata.version", side_effect=ModuleNotFoundError("mcp")),
            pytest.raises(ImportError) as excinfo,
        ):
            create_server(working_dir=str(temp_dir))
        assert "MCP SDK not installed" in str(excinfo.value)
        assert "mcp>=2.1.1,<3" in str(excinfo.value)


class TestMCPTransports:
    """App construction and runner delegation exercise actual MCP 2 APIs."""

    @pytest.mark.parametrize("transport,path", [("sse", "/sse"), ("streamable-http", "/mcp")])
    def test_apps_include_bearer_middleware(self, temp_dir, monkeypatch, transport, path):
        monkeypatch.setenv("CLAUDETM_PASSWORD", "test-password")
        monkeypatch.delenv("CLAUDETM_PASSWORD_HASH", raising=False)
        server = create_server(working_dir=str(temp_dir))
        app = _get_authenticated_app(server, transport)
        assert isinstance(app, Starlette)
        assert path in _route_paths(app)
        assert any(cls is PasswordAuthMiddleware for cls in _middleware_classes(app))
        with TestClient(app) as client:
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 403
            # A valid bearer reaches routing (without opening a blocking MCP stream).
            assert (
                client.get(
                    "/unknown", headers={"Authorization": "Bearer test-password"}
                ).status_code
                == 404
            )
            assert client.get("/health").status_code == 404  # Public, no auth challenge.

    @pytest.mark.parametrize("mount_path", [None, "/", "/prefix", "/prefix/"])
    def test_sse_mount_prefix(self, temp_dir, monkeypatch, mount_path):
        monkeypatch.delenv("CLAUDETM_PASSWORD", raising=False)
        monkeypatch.delenv("CLAUDETM_PASSWORD_HASH", raising=False)
        server = create_server(working_dir=str(temp_dir))
        app = _get_authenticated_app(server, "sse", mount_path)
        prefix = mount_path.rstrip("/") if mount_path else ""
        assert _route_paths(app) == {"/sse", f"{prefix}/messages"}
        assert not app.user_middleware

    def test_stdio_delegates_to_sdk(self, temp_dir):
        with patch.object(MCPServer, "run_stdio_async", new_callable=AsyncMock) as run:
            run_server(working_dir=str(temp_dir))
        run.assert_awaited_once_with()

    @pytest.mark.parametrize("transport", ["sse", "streamable-http"])
    def test_authenticated_network_runner(self, temp_dir, monkeypatch, transport):
        monkeypatch.setenv("CLAUDETM_PASSWORD", "test-password")
        monkeypatch.delenv("CLAUDETM_PASSWORD_HASH", raising=False)
        configs: list[uvicorn.Config] = []

        async def serve(uvicorn_server: uvicorn.Server) -> None:
            configs.append(uvicorn_server.config)

        with patch("uvicorn.Server.serve", autospec=True, side_effect=serve):
            run_server(working_dir=str(temp_dir), transport=transport, host="0.0.0.0", port=9080)
        config = configs[0]
        assert (config.host, config.port, config.log_level) == ("0.0.0.0", 9080, "info")
        app = config.app
        assert isinstance(app, Starlette)
        assert any(cls is PasswordAuthMiddleware for cls in _middleware_classes(app))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("transport", ["sse", "streamable-http"])
    async def test_async_runner_forwards_host(self, temp_dir, monkeypatch, transport):
        monkeypatch.setenv("CLAUDETM_PASSWORD", "test-password")
        server = create_server(working_dir=str(temp_dir))
        factory = "sse_app" if transport == "sse" else "streamable_http_app"
        with (
            patch.object(server, factory, wraps=getattr(server, factory)) as app_factory,
            patch("uvicorn.Server.serve", new_callable=AsyncMock) as serve,
        ):
            await _run_network_transport_async(server, transport, "0.0.0.0", 9080)
        assert app_factory.call_args.kwargs["host"] == "0.0.0.0"
        serve.assert_awaited_once()

    @pytest.mark.parametrize("transport", ["sse", "streamable-http"])
    def test_rejects_unauthenticated_non_localhost(self, temp_dir, monkeypatch, caplog, transport):
        monkeypatch.delenv("CLAUDETM_PASSWORD", raising=False)
        monkeypatch.delenv("CLAUDETM_PASSWORD_HASH", raising=False)
        with (
            patch("uvicorn.Server.serve", new_callable=AsyncMock) as serve,
            pytest.raises(SystemExit, match="1"),
        ):
            run_server(working_dir=str(temp_dir), transport=transport, host="0.0.0.0")
        serve.assert_not_called()
        assert "without authentication" in caplog.text
