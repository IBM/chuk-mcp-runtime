# tests/server/test_server_json.py
"""
Fixed JSON serialization tests with proper server tracking.
"""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from mcp.types import CallToolRequestParams

from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY, mcp_tool
from chuk_mcp_runtime.server.server import MCPServer

# Capture FakeServer instances - CRITICAL: Use module-level variable
_created = []


class FakeServer:
    """Captures the mcp 2 on_* handlers; exposes call_tool in the old (name, arguments) style."""

    def __init__(self, name, **handlers):
        _created.append(self)
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
def patch_server(monkeypatch):
    import chuk_mcp_runtime.server.server as srv_mod

    monkeypatch.setattr(srv_mod, "Server", FakeServer)
    monkeypatch.setattr(srv_mod, "stdio_server", dummy_stdio)
    TOOLS_REGISTRY.clear()
    _created.clear()
    yield
    _created.clear()
    TOOLS_REGISTRY.clear()


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


# Test tools
@mcp_tool(name="dict_tool", description="Returns a dict")
async def dict_tool() -> dict:
    return {"a": 1, "b": [2, 3], "c": {"x": True}}


@mcp_tool(name="error_tool", description="Raises an error")
async def error_tool():
    raise RuntimeError("oh no")


def test_json_serialization_and_awaiting():
    """Test basic JSON serialization for different tool return types."""
    cfg = {"server": {"type": "stdio"}, "tools": {}}
    server = MCPServer(cfg)

    TOOLS_REGISTRY["dict_tool"] = dict_tool
    TOOLS_REGISTRY["error_tool"] = error_tool

    # CRITICAL: Server creation happens during serve() call
    run_async(server.serve())

    # Now check that fake server was created
    assert len(_created) > 0, f"No fake server was created. _created contains: {_created}"
    fake = _created[-1]
    assert "call_tool" in fake.handlers, "call_tool handler not found"

    call = fake.handlers["call_tool"]

    # Test dict_tool
    out = run_async(call("dict_tool", {}))
    assert len(out) == 1
    parsed = json.loads(out[0].text)
    assert parsed == {"a": 1, "b": [2, 3], "c": {"x": True}}

    # Test error_tool - should return error message, not raise
    out_error = run_async(call("error_tool", {}))
    assert len(out_error) == 1
    assert "Tool execution error" in out_error[0].text
    assert "oh no" in out_error[0].text


def test_error_handling_with_naming_resolution():
    """Test error handling with tool naming resolution."""
    cfg = {"server": {"type": "stdio"}, "tools": {}}
    server = MCPServer(cfg)

    TOOLS_REGISTRY["error_tool"] = error_tool

    run_async(server.serve())

    assert len(_created) > 0, f"No fake server was created. _created contains: {_created}"
    fake = _created[-1]
    assert "call_tool" in fake.handlers, "call_tool handler not found"

    call = fake.handlers["call_tool"]

    # Test error tool - should return error message
    out1 = run_async(call("error_tool", {}))
    assert len(out1) == 1
    assert "Tool execution error" in out1[0].text
    assert "oh no" in out1[0].text

    # Test nonexistent tool - should return error message
    out2 = run_async(call("nonexistent_tool", {}))
    assert len(out2) == 1
    assert "Tool execution error" in out2[0].text
    assert "Tool not found" in out2[0].text


def test_naming_compatibility():
    """Test tool calling with different naming conventions."""

    @mcp_tool(name="list.tool", description="Returns a list")
    async def list_tool() -> list:
        return ["hello", {"num": 5}, False]

    cfg = {"server": {"type": "stdio"}, "tools": {}}
    server = MCPServer(cfg)

    TOOLS_REGISTRY["list.tool"] = list_tool

    run_async(server.serve())

    assert len(_created) > 0, f"No fake server was created. _created contains: {_created}"
    fake = _created[-1]
    assert "call_tool" in fake.handlers, "call_tool handler not found"

    call = fake.handlers["call_tool"]

    # Test with original dot notation
    out1 = run_async(call("list.tool", {}))
    assert len(out1) == 1
    parsed1 = json.loads(out1[0].text)
    assert parsed1 == ["hello", {"num": 5}, False]


if __name__ == "__main__":
    pytest.main(["-xvs", __file__])
