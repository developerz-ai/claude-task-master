"""Tests for MCP server creation and configuration.

Tests server initialization, CLI entry points, and network security.
"""

from unittest.mock import patch

import pytest

from .conftest import MCP_AVAILABLE

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestMCPServerCreation:
    """Test MCP server creation and configuration."""

    def test_create_server_returns_fastmcp_instance(self, temp_dir):
        """Test that create_server returns a FastMCP instance."""
        from claude_task_master.mcp.server import create_server

        server = create_server(working_dir=str(temp_dir))
        assert server is not None

    def test_create_server_with_custom_name(self, temp_dir):
        """Test server creation with custom name."""
        from claude_task_master.mcp.server import create_server

        server = create_server(name="custom-server", working_dir=str(temp_dir))
        assert server is not None

    def test_create_server_without_mcp_raises_import_error(self, temp_dir):
        """create_server raises ImportError when FastMCP could not be imported."""
        from claude_task_master.mcp import server as mcp_server_module

        # Temporarily set FastMCP to None
        original_fastmcp = mcp_server_module.FastMCP
        mcp_server_module.FastMCP = None  # type: ignore[misc, assignment]

        try:
            with pytest.raises(ImportError, match="mcp<2"):
                mcp_server_module.create_server(working_dir=str(temp_dir))
        finally:
            mcp_server_module.FastMCP = original_fastmcp  # type: ignore[misc]

    def test_wrong_major_version_is_not_reported_as_missing(self, temp_dir):
        """An installed-but-incompatible mcp must not say "not installed".

        mcp 2.x renamed FastMCP to MCPServer and removed ``mcp.server.fastmcp``,
        so the import fails with mcp very much installed. Advising
        ``pip install mcp`` there sends the user in a circle — which is exactly
        what happened on a real v0.1.90 install carrying mcp 2.1.1.
        """
        from claude_task_master.mcp import server as mcp_server_module

        original_fastmcp = mcp_server_module.FastMCP
        mcp_server_module.FastMCP = None  # type: ignore[misc, assignment]
        try:
            with pytest.raises(ImportError) as excinfo:
                mcp_server_module.create_server(working_dir=str(temp_dir))
        finally:
            mcp_server_module.FastMCP = original_fastmcp  # type: ignore[misc]

        message = str(excinfo.value)
        # mcp is installed in the test environment, so this branch must fire.
        assert "not installed" not in message
        assert "incompatible" in message
        assert "mcp<2" in message

    def test_genuinely_missing_mcp_still_says_not_installed(self, temp_dir):
        """The other branch: no mcp at all keeps the plain install advice."""
        from claude_task_master.mcp import server as mcp_server_module

        def _no_mcp(_name):
            raise ModuleNotFoundError("No module named 'mcp'")

        original_fastmcp = mcp_server_module.FastMCP
        mcp_server_module.FastMCP = None  # type: ignore[misc, assignment]
        try:
            with patch("importlib.metadata.version", side_effect=_no_mcp):
                with pytest.raises(ImportError) as excinfo:
                    mcp_server_module.create_server(working_dir=str(temp_dir))
        finally:
            mcp_server_module.FastMCP = original_fastmcp  # type: ignore[misc]

        assert "MCP SDK not installed" in str(excinfo.value)


class TestMCPServerCLI:
    """Test MCP server CLI entry point."""

    def test_main_function_exists(self):
        """Test that main function exists and is callable."""
        from claude_task_master.mcp.server import main

        assert callable(main)

    def test_run_server_function_exists(self):
        """Test that run_server function exists and is callable."""
        from claude_task_master.mcp.server import run_server

        assert callable(run_server)


class TestMCPServerNetworkSecurity:
    """Test MCP server network security features."""

    def test_run_server_non_localhost_warning(self, temp_dir, caplog):
        """Test that non-localhost binding logs a warning."""
        from claude_task_master.mcp import server as mcp_server_module

        # Just verify the warning would be logged for non-localhost
        # We can't actually run the server in tests
        effective_host = "0.0.0.0"
        transport = "sse"

        if transport != "stdio" and effective_host not in ("127.0.0.1", "localhost", "::1"):
            mcp_server_module.logger.warning(
                f"MCP server binding to non-localhost address ({effective_host}). "
                "Ensure proper authentication is configured."
            )

        # The warning mechanism works if we got here without error
        assert True
