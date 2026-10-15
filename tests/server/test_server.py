# tests/server/test_server.py
"""
Fixed server tests that match the actual server behavior.
"""

import asyncio
from contextlib import asynccontextmanager

import pytest
from mcp.types import CallToolRequestParams

from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY, mcp_tool
from chuk_mcp_runtime.server.server import MCPServer

# Track created fake servers
_created_servers = []


class FakeServer:
    """Captures the mcp 2 on_* handlers; exposes call_tool in the old (name, arguments) style."""

    def __init__(self, name, **handlers):
        _created_servers.append(self)
        self.server_name = name
        self.raw_handlers = handlers
        self.handlers = {}
        on_call_tool = handlers.get("on_call_tool")
        if on_call_tool:

            async def call_tool(name, arguments):
                result = await on_call_tool(
                    None, CallToolRequestParams(name=name, arguments=arguments)
                )
                return result.content

            self.handlers["call_tool"] = call_tool

    def create_initialization_options(self):
        return {}

    async def run(self, read, write, opts):
        return


@asynccontextmanager
async def dummy_stdio():
    yield (None, None)


@pytest.fixture(autouse=True)
def setup_test(monkeypatch):
    import chuk_mcp_runtime.server.server as srv_mod

    monkeypatch.setattr(srv_mod, "Server", FakeServer)
    monkeypatch.setattr(srv_mod, "stdio_server", dummy_stdio)
    TOOLS_REGISTRY.clear()
    _created_servers.clear()
    yield
    TOOLS_REGISTRY.clear()
    _created_servers.clear()


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@mcp_tool(name="error_tool", description="Raises an error")
async def error_tool():
    raise ValueError("Test error message")


def test_call_tool_errors():
    """Test that call_tool handles errors properly - returns error messages, doesn't raise."""
    cfg = {"server": {"type": "stdio"}, "tools": {}}
    server = MCPServer(cfg)

    TOOLS_REGISTRY["error_tool"] = error_tool

    # Start server to register handlers
    run_async(server.serve())

    # Get the fake server that was created
    assert len(_created_servers) > 0, "No fake server was created"
    fake_server = _created_servers[-1]

    assert "call_tool" in fake_server.handlers, "call_tool handler not registered"
    call_tool = fake_server.handlers["call_tool"]

    # Test that calling a tool that raises an error returns an error message
    # The actual server catches exceptions and returns error messages
    result = run_async(call_tool("error_tool", {}))
    assert len(result) == 1
    assert "Tool execution error" in result[0].text
    assert "Test error message" in result[0].text

    # Test nonexistent tool also returns error message
    result2 = run_async(call_tool("does_not_exist", {}))
    assert len(result2) == 1
    assert "Tool execution error" in result2[0].text
    assert "Tool not found" in result2[0].text


if __name__ == "__main__":
    pytest.main(["-xvs", __file__])
