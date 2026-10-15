# tests/server/test_mcp2_protocol.py
"""
The mcp 2 handlers against the real mcp Server and client, on both protocol
generations (the 2025 initialize handshake and 2026-07-28), plus the helpers
that keep mcp 1.x behaviour.
"""

import asyncio
import contextlib
import sys
from unittest.mock import AsyncMock, MagicMock

import mcp.types as types
import pytest
import pytest_asyncio
from mcp.client.client import Client
from mcp.server import Server as RealServer
from mcp.shared.exceptions import MCPError

import chuk_mcp_runtime.server.server as srv_mod
from chuk_mcp_runtime.common import mcp_resource_decorator
from chuk_mcp_runtime.common.mcp_resource_decorator import mcp_resource
from chuk_mcp_runtime.common.mcp_tool_decorator import (
    TOOLS_REGISTRY,
    initialize_tool_registry,
    mcp_tool,
)
from chuk_mcp_runtime.common.openai_compatibility import create_openai_compatible_wrapper
from chuk_mcp_runtime.server.request_context import (
    MCPRequestContext,
    get_request_headers,
    send_progress,
)
from chuk_mcp_runtime.session.native_session_management import get_user_or_none
from chuk_mcp_runtime.types import (
    DEFAULT_MAX_REQUEST_BODY_SIZE,
    SSEConfig,
    StreamableHTTPConfig,
)

# Client modes and the protocol each negotiates with this server
PROTOCOLS = {"legacy": "2025-11-25", "auto": "2026-07-28"}


@contextlib.asynccontextmanager
async def _no_stdio():
    yield (None, None)


@pytest_asyncio.fixture
async def runtime_server(monkeypatch, clear_tools_registry):
    """The real mcp Server built by MCPServer.serve(), ready for an in-memory Client."""
    servers = []

    class CapturingServer(RealServer):
        bootstrapping = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            servers.append(self)

        async def run(self, *args, **kwargs):
            if CapturingServer.bootstrapping:  # serve()'s stdio loop: skip it
                return None
            return await super().run(*args, **kwargs)

    monkeypatch.setattr(srv_mod, "Server", CapturingServer)
    monkeypatch.setattr(srv_mod, "stdio_server", _no_stdio)
    saved_resources = dict(mcp_resource_decorator.RESOURCES_REGISTRY)

    @mcp_tool(name="echo", description="Echo text back")
    async def echo(text: str) -> str:
        return f"echo:{text}"

    @mcp_tool(name="progress3", description="Report progress three times")
    async def progress3() -> str:
        for step in range(1, 4):
            await send_progress(progress=step, total=3, message=f"step {step}")
        return "done"

    @mcp_tool(name="bad_schema", description="Schema replaced below")
    async def bad_schema(x: int = 0) -> str:
        return "ran"

    @mcp_tool(name="unlisted", description="Schema replaced below")
    async def unlisted() -> str:
        return "ran"

    @mcp_resource(uri="test://hello", name="hello", description="Text", mime_type="text/plain")
    async def hello() -> str:
        return "hello"

    await initialize_tool_registry()
    # Not a valid JSON Schema, but valid on the wire: calls must fail as a tool error
    TOOLS_REGISTRY["bad_schema"]._mcp_tool = types.Tool(
        name="bad_schema",
        description="x",
        input_schema={"type": "object", "properties": {"x": {"type": "bogus"}}},
    )
    # Not valid on the 2025 wire (a property that is not a schema)
    TOOLS_REGISTRY["unlisted"]._mcp_tool = types.Tool(
        name="unlisted",
        description="x",
        input_schema={"type": "object", "properties": {"type": "object"}},
    )

    runtime = srv_mod.MCPServer(
        {
            "host": {"name": "test-runtime", "log_level": "ERROR"},
            "server": {"type": "stdio"},
            "artifacts": {"enabled": False},
        },
        tools_registry=TOOLS_REGISTRY,
    )
    await runtime.serve()
    CapturingServer.bootstrapping = False
    try:
        yield servers[-1]
    finally:
        mcp_resource_decorator.RESOURCES_REGISTRY.clear()
        mcp_resource_decorator.RESOURCES_REGISTRY.update(saved_resources)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", PROTOCOLS)
async def test_tools_list_and_call(runtime_server, mode):
    async with Client(runtime_server, mode=mode) as client:
        assert client.protocol_version == PROTOCOLS[mode]
        assert client.server_info.name == "test-runtime"
        assert client.server_info.version  # the runtime's version, not ""

        names = {tool.name for tool in (await client.list_tools()).tools}
        assert {"echo", "progress3", "bad_schema"} <= names

        result = await client.call_tool("echo", {"text": "hi"})
        assert not result.is_error
        assert result.content[0].text == "echo:hi"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", PROTOCOLS)
async def test_invalid_arguments_and_schemas_are_tool_errors(runtime_server, mode):
    async with Client(runtime_server, mode=mode) as client:
        missing = await client.call_tool("echo", {})
        assert missing.is_error
        assert missing.content[0].text.startswith("Input validation error:")

        # mcp 1.x returned an error result here too, not a protocol error
        broken = await client.call_tool("bad_schema", {"x": 1})
        assert broken.is_error
        assert "bogus" in broken.content[0].text


@pytest.mark.asyncio
async def test_non_conforming_schema_is_left_out_not_fatal(runtime_server):
    async with Client(runtime_server, mode="legacy") as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert "unlisted" not in names
        assert "echo" in names

        result = await client.call_tool("echo", {"text": "still works"})
        assert result.content[0].text == "echo:still works"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", PROTOCOLS)
async def test_resources(runtime_server, mode):
    async with Client(runtime_server, mode=mode) as client:
        listed = (await client.list_resources()).resources
        assert [str(r.uri) for r in listed] == ["test://hello"]

        contents = (await client.read_resource("test://hello")).contents
        assert contents[0].text == "hello"
        assert contents[0].mime_type == "text/plain"

        with pytest.raises(MCPError, match="Resource not found: test://missing"):
            await client.read_resource("test://missing")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", PROTOCOLS)
async def test_progress_reaches_the_client(runtime_server, mode):
    received = []

    async def on_progress(progress, total, message):
        received.append(progress)

    async with Client(runtime_server, mode=mode) as client:
        result = await client.call_tool("progress3", {}, progress_callback=on_progress)
        assert result.content[0].text == "done"
        for _ in range(50):
            if len(received) == 3:
                break
            await asyncio.sleep(0.01)
    assert received == [1, 2, 3]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol_version, modern", [("2025-11-25", False), ("2026-07-28", True)])
async def test_send_progress_routing(protocol_version, modern):
    session = MagicMock()
    session.protocol_version = protocol_version
    session.report_progress = AsyncMock()
    session.send_progress_notification = AsyncMock()

    ctx = MCPRequestContext(session=session, progress_token="tok")
    await ctx.send_progress(progress=1, total=2, message="half")

    if modern:
        # 2026-07-28 has no standalone stream: progress rides the request's response
        session.report_progress.assert_awaited_once_with(1, 2, "half")
        session.send_progress_notification.assert_not_awaited()
    else:
        session.send_progress_notification.assert_awaited_once_with(
            progress_token="tok", progress=1, total=2, message="half"
        )
        session.report_progress.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_identity_is_set_for_each_sse_post():
    seen = {}

    async def app(scope, receive, send):
        seen["user"] = get_user_or_none()
        seen["headers"] = get_request_headers()

    wrapped = srv_mod._with_request_identity(app)
    scope = {"type": "http", "user": {"sub": "alice"}, "headers_dict": {"x-probe": "hello"}}
    await wrapped(scope, None, None)

    assert seen == {"user": "alice", "headers": {"x-probe": "hello"}}
    assert get_user_or_none() is None  # reset after the request


def test_transport_limit_defaults():
    # A finite body limit, larger than mcp 2's 4 MiB; no idle timeout or session cap
    http_cfg = StreamableHTTPConfig()
    assert http_cfg.max_request_body_size == DEFAULT_MAX_REQUEST_BODY_SIZE == 50 * 1024 * 1024
    assert http_cfg.session_idle_timeout is None
    assert http_cfg.max_sessions is None
    assert SSEConfig().max_request_body_size == DEFAULT_MAX_REQUEST_BODY_SIZE

    # An explicit null disables the limit
    assert StreamableHTTPConfig(max_request_body_size=None).max_request_body_size is None
    assert srv_mod._body_limit(None) == sys.maxsize
    assert srv_mod._body_limit(1024) == 1024


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remote_schema, properties, required",
    [
        ({"type": "object"}, {}, []),
        ({"q": {"type": "string"}, "required": ["q"]}, {"q": {"type": "string"}}, ["q"]),
    ],
)
async def test_openai_wrapper_builds_valid_object_schemas(remote_schema, properties, required):
    async def remote_tool(**kwargs):
        return kwargs

    remote_tool._proxy_metadata = {"description": "remote", "inputSchema": remote_schema}
    wrapper = await create_openai_compatible_wrapper("proxy.remote.tool", remote_tool)

    schema = wrapper._mcp_tool.input_schema
    assert schema["type"] == "object"
    assert schema["properties"] == properties
    assert schema.get("required", []) == required
