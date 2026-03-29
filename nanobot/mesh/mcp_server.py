"""MCP server exposing mesh device tools (task 5.3.1).

Runs an SSE-based MCP server alongside the gateway so external AI
agents (Claude Desktop, ChatGPT plugins, etc.) can discover and
call device_control / device_reprogram / deployment tools.

Usage: Enabled via config field ``mcp_server_port`` in mesh config.
The server binds to 0.0.0.0:<port>/sse and exposes tools that
delegate to the existing nanobot Tool instances.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger
from mcp import types as mcp_types
from mcp.server import Server

from nanobot.agent.tools.base import Tool

# ---------------------------------------------------------------------------
# Bridge: nanobot Tool → MCP tool
# ---------------------------------------------------------------------------


def _nanobot_tool_to_mcp(tool: Tool) -> mcp_types.Tool:
    """Convert a nanobot Tool to an MCP Tool definition."""
    return mcp_types.Tool(
        name=tool.name,
        description=tool.description,
        inputSchema=tool.parameters,
    )


# ---------------------------------------------------------------------------
# MCP Server for mesh device tools
# ---------------------------------------------------------------------------


class MeshMCPServer:
    """Thin wrapper that exposes nanobot tools over MCP.

    Parameters
    ----------
    tools :
        Dict of tool_name → nanobot Tool instance.
    server_name :
        Human-readable server name.
    """

    def __init__(
        self,
        tools: dict[str, Tool] | None = None,
        server_name: str = "embed-nanobot-mesh",
    ):
        self._tools: dict[str, Tool] = dict(tools) if tools else {}
        self._server = Server(server_name)
        self._setup_handlers()

    def register_tool(self, tool: Tool) -> None:
        """Register an additional nanobot tool."""
        self._tools[tool.name] = tool

    def _setup_handlers(self) -> None:
        """Wire MCP server handlers."""

        @self._server.list_tools()
        async def handle_list_tools() -> list[mcp_types.Tool]:
            return [_nanobot_tool_to_mcp(t) for t in self._tools.values()]

        @self._server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[mcp_types.TextContent]:
            tool = self._tools.get(name)
            if tool is None:
                return [mcp_types.TextContent(
                    type="text",
                    text=json.dumps({"error": f"Unknown tool: {name}"}),
                )]

            params = arguments or {}
            try:
                # Use nanobot's built-in param casting and validation
                casted = tool.cast_params(params)
                errors = tool.validate_params(casted)
                if errors:
                    return [mcp_types.TextContent(
                        type="text",
                        text=json.dumps({"error": "Validation failed", "details": errors}),
                    )]
                result = await tool.execute(**casted)
                text = result if isinstance(result, str) else json.dumps(result)
            except Exception as e:
                logger.warning("MCP tool {} failed: {}", name, e)
                text = json.dumps({"error": str(e)})

            return [mcp_types.TextContent(type="text", text=text)]

    @property
    def server(self) -> Server:
        return self._server

    def create_init_options(self) -> Any:
        """Create MCP initialization options."""
        return self._server.create_initialization_options()

    async def run_sse(self, host: str = "0.0.0.0", port: int = 18801) -> None:
        """Start the MCP server as an SSE endpoint.

        Requires ``starlette`` and ``uvicorn``.
        """
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as (read_stream, write_stream):
                await self._server.run(
                    read_stream,
                    write_stream,
                    self.create_init_options(),
                )

        app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )

        import uvicorn
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        logger.info("MCP SSE server starting on {}:{}", host, port)
        await server.serve()
