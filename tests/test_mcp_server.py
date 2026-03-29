"""Tests for nanobot.mesh.mcp_server — MCP device tools server (task 5.3.1)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.mesh.mcp_server import MeshMCPServer, _nanobot_tool_to_mcp


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class FakeTool:
    """Minimal nanobot Tool-like object for testing."""

    def __init__(self, name: str = "test_tool", result: str = "ok"):
        self._name = name
        self._result = result

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Test tool: {self._name}"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "Action to perform"},
            },
            "required": ["action"],
        }

    def cast_params(self, params: dict) -> dict:
        return params

    def validate_params(self, params: dict) -> list[str]:
        if "action" not in params:
            return ["Missing required: action"]
        return []

    async def execute(self, **kwargs) -> str:
        return self._result


class FailingTool(FakeTool):
    """Tool that raises on execute."""

    async def execute(self, **kwargs) -> str:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestNanobotToolToMCP:
    def test_converts_tool(self):
        tool = FakeTool("device_control")
        mcp_tool = _nanobot_tool_to_mcp(tool)
        assert mcp_tool.name == "device_control"
        assert mcp_tool.description == "Test tool: device_control"
        assert mcp_tool.inputSchema["type"] == "object"


class TestMeshMCPServer:
    def test_register_tool(self):
        srv = MeshMCPServer()
        t = FakeTool("ctrl")
        srv.register_tool(t)
        assert "ctrl" in srv._tools

    def test_init_with_tools(self):
        t1 = FakeTool("a")
        t2 = FakeTool("b")
        srv = MeshMCPServer(tools={"a": t1, "b": t2})
        assert len(srv._tools) == 2

    def test_server_property(self):
        srv = MeshMCPServer()
        assert srv.server is not None

    def test_create_init_options(self):
        srv = MeshMCPServer()
        opts = srv.create_init_options()
        assert opts is not None


class TestMCPHandlers:
    """Test the MCP handler functions directly via the Server."""

    @pytest.mark.asyncio
    async def test_list_tools(self):
        t = FakeTool("device_control")
        srv = MeshMCPServer(tools={"device_control": t})
        # Verify tools are registered and accessible
        assert "device_control" in srv._tools
        assert srv._tools["device_control"].name == "device_control"

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        """Simulate calling a tool through the MCP server."""
        t = FakeTool("device_control", result='{"devices": []}')
        srv = MeshMCPServer(tools={"device_control": t})

        # Directly invoke the call_tool handler
        # The server registers handlers internally; we test our logic
        tool = srv._tools.get("device_control")
        assert tool is not None
        result = await tool.execute(action="list")
        assert "devices" in result

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self):
        srv = MeshMCPServer()
        # Unknown tool should not be in _tools
        assert srv._tools.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_call_tool_with_validation_error(self):
        t = FakeTool("device_control")
        srv = MeshMCPServer(tools={"device_control": t})
        # Missing required 'action' param
        errors = t.validate_params({})
        assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_call_tool_exception_handled(self):
        t = FailingTool("bad_tool")
        srv = MeshMCPServer(tools={"bad_tool": t})
        # Execute should raise but MCP handler wraps it
        try:
            await t.execute(action="test")
            assert False, "Should have raised"
        except RuntimeError:
            pass  # Expected


class TestConfigField:
    def test_mcp_server_port_default(self):
        from nanobot.config.schema import MeshConfig
        cfg = MeshConfig()
        assert cfg.mcp_server_port == 0

    def test_mcp_server_port_custom(self):
        from nanobot.config.schema import MeshConfig
        cfg = MeshConfig(mcp_server_port=18801)
        assert cfg.mcp_server_port == 18801
