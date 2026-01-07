"""
Hub ↔︎ Sandbox integration (per-request streams)
==============================================

Each sandbox advertises itself once; every tool invocation then dials the
sandbox’s endpoint *just for that request* and closes immediately.  This
avoids multiplexing complexity and removes back-pressure headaches.
Registry lives in the existing SESSION_PROVIDER (memory, Redis, …).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.parse
import uuid
from typing import AsyncContextManager, Callable, Optional

import aiohttp
from chuk_sessions import provider_factory  # ← reuse existing providers

from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY, mcp_tool
from chuk_mcp_runtime.proxy.tool_wrapper import create_proxy_tool
from chuk_mcp_runtime.server.logging_config import get_logger

logger = get_logger("hub")

# ─────────────────────────────────────────────────────────────────────────────
#  Registry helpers (shared with session provider)
# ─────────────────────────────────────────────────────────────────────────────

# Environment-based namespace (prevents staging/prod collisions)
_ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("ENV", "dev"))
_DEPLOYMENT_ID = os.getenv("DEPLOYMENT_ID", "default")
_SBXPREFIX = f"{_ENVIRONMENT}:{_DEPLOYMENT_ID}:sbx:"

# Configurable TTL (default 24h, override via environment)
_TTL = int(os.getenv("SANDBOX_REGISTRY_TTL", str(24 * 3600)))

_session_factory: Callable[[], AsyncContextManager] | None = None
_factory_lock = asyncio.Lock()


async def _get_session_factory():
    """Get session factory with thread-safe initialization."""
    global _session_factory  # noqa: PLW0603

    if _session_factory is None:
        async with _factory_lock:
            # Double-check after acquiring lock
            if _session_factory is None:
                _session_factory = provider_factory.factory_for_env()
                logger.info(
                    f"Initialized session factory for sandbox registry (namespace: {_SBXPREFIX})"
                )

    return _session_factory


async def _registry_put(sbx_id: str, record: dict):
    factory = await _get_session_factory()
    async with factory() as sess:
        await sess.setex(f"{_SBXPREFIX}{sbx_id}", _TTL, json.dumps(record))


async def _registry_get(sbx_id: str) -> Optional[dict]:
    factory = await _get_session_factory()
    async with factory() as sess:
        raw = await sess.get(f"{_SBXPREFIX}{sbx_id}")
    return None if raw is None else json.loads(raw)


async def _registry_del(sbx_id: str):
    factory = await _get_session_factory()
    async with factory() as sess:
        if hasattr(sess, "delete"):
            await sess.delete(f"{_SBXPREFIX}{sbx_id}")
        else:  # memory provider: overwrite with short TTL
            await sess.setex(f"{_SBXPREFIX}{sbx_id}", 1, "{}")


# ─────────────────────────────────────────────────────────────────────────────
#  Transport dials
# ─────────────────────────────────────────────────────────────────────────────
async def _dial(endpoint: str, transport: str):
    """Return `(reader, writer)` pair for the chosen transport."""
    transport = transport.lower()
    if transport == "sse":
        from mcp.lowlevel.client import connect_sse

        return await connect_sse(endpoint)  # returns StreamReader / StreamWriter

    if transport == "stdio":
        if endpoint.startswith("tcp://"):
            ep = urllib.parse.urlparse(endpoint)
            host = ep.hostname
            port_int: int = ep.port if ep.port else 0
        else:
            host_str, port_str = endpoint.split(":", 1)
            host = host_str
            port_int = int(port_str)
        reader, writer = await asyncio.open_connection(host, port_int)
        return reader, writer

    if transport == "ws":
        import websockets  # type: ignore

        uri = endpoint.replace("http://", "ws://").replace("https://", "wss://")
        ws = await websockets.connect(uri)
        reader = asyncio.StreamReader()
        proto = websockets.streams.StreamReaderProtocol(reader)
        loop = asyncio.get_running_loop()
        await loop.connect_accepted_socket(proto, ws.transport.get_extra_info("socket"))
        writer = asyncio.StreamWriter(ws.transport, proto, reader, loop)
        return reader, writer

    raise ValueError(f"Unsupported transport '{transport}'")


# ─────────────────────────────────────────────────────────────────────────────
#  Hub-side tool: register sandbox & create proxy wrappers
# ─────────────────────────────────────────────────────────────────────────────
_HUB_ID = os.getenv("HUB_ID", os.getenv("POD_NAME", "hub"))


@mcp_tool(
    name="hub.register_sandbox",
    description="Register a sandbox; expose its tools via proxy wrappers.",
)
async def register_sandbox(*, sandbox_id: str, endpoint: str, transport: str = "sse") -> str:  # noqa: D401
    """Hub entry-point called by sandboxes on boot."""
    # 1) Dial *once* just to fetch the tool catalogue
    reader, writer = await _dial(endpoint, transport)
    writer.write(b'{"role":"list_tools"}\n')
    await writer.drain()
    tools_meta = json.loads(await reader.readline())["result"]
    writer.close()
    await writer.wait_closed()

    # 2) Build proxy wrappers (per-request dial)
    ns_root = f"sbx.{sandbox_id}"
    for meta in tools_meta:
        tname = meta["name"]

        async def _remote_call(arguments, *, _t=tname, _ep=endpoint, _tr=transport):
            reader, writer = await _dial(_ep, _tr)
            req_id = uuid.uuid4().hex
            payload = {"id": req_id, "name": _t, "arguments": arguments}
            writer.write(json.dumps(payload).encode() + b"\n")
            await writer.drain()

            while True:
                line = await reader.readline()
                if not line:
                    raise RuntimeError("Remote closed before response")
                msg = json.loads(line)
                if msg.get("id") == req_id:
                    writer.close()
                    await writer.wait_closed()
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    return msg["result"]

        wrapper = await create_proxy_tool(ns_root, tname, _remote_call, meta)
        wrapper._owning_hub = _HUB_ID  # type: ignore[attr-defined]
        TOOLS_REGISTRY[f"{ns_root}.{tname}"] = wrapper

    # 3) Write/refresh registry entry
    record = {
        "hub": _HUB_ID,
        "transport": transport,
        "endpoint": endpoint,
        "ts": int(time.time()),
    }
    await _registry_put(sandbox_id, record)

    logger.info("Registered %s tool(s) from sandbox %s", len(tools_meta), sandbox_id)
    return f"registered {len(tools_meta)} tool(s) from {sandbox_id}"


# ─────────────────────────────────────────────────────────────────────────────
#  Cross-hub proxy helper
# ─────────────────────────────────────────────────────────────────────────────
async def proxy_call_tool(name: str, arguments: dict, *, self_execute):
    """Run locally or HTTP-forward to the hub that owns the sandbox."""
    # Fast path: tool exists locally & owned by this hub
    tool = TOOLS_REGISTRY.get(name)
    if tool and getattr(tool, "_owning_hub", _HUB_ID) == _HUB_ID:
        return await self_execute(name, arguments)

    if not name.startswith("sbx."):
        raise ValueError(f"Tool {name} not found and not sandbox-qualified")

    sbx_id = name.split(".")[1]
    rec = await _registry_get(sbx_id)
    if rec is None:
        raise ValueError(f"No registry entry for sandbox {sbx_id}")

    owner_hub = rec["hub"]
    if owner_hub == _HUB_ID:  # we own it but wrapper missing (race)
        return await self_execute(name, arguments)

    base_tpl = os.getenv("HUB_BASE_URL_TEMPLATE", "http://{hub}:8000")
    url = f"{base_tpl.format(hub=owner_hub)}/call/{name}"
    headers = {}
    if token := os.getenv("HUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    async with aiohttp.ClientSession(headers=headers) as sess:
        async with sess.post(url, json=arguments) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"Hub {owner_hub} error {resp.status}: {data}")
            return data


# ─────────────────────────────────────────────────────────────────────────────
#  Sandbox-side bootstrap helper
# ─────────────────────────────────────────────────────────────────────────────
async def register_with_hub() -> None:
    """Run once on sandbox start; then refresh TTL in background."""
    sbx_id = os.getenv("SANDBOX_ID")
    if not sbx_id:
        logger.error("SANDBOX_ID unset - skipping hub registration")
        return

    hub_addr = os.getenv("HUB_ADDR", "http://hub:8000")
    hub_token = os.getenv("HUB_TOKEN", "")
    transport = os.getenv("SBX_TRANSPORT", "sse").lower()

    endpoint = os.getenv("HUB_URL") or _infer_endpoint(transport)
    if endpoint is None:
        return

    payload = {"sandbox_id": sbx_id, "endpoint": endpoint, "transport": transport}
    headers = {"Authorization": f"Bearer {hub_token}"} if hub_token else {}

    async def _send_register():
        async with aiohttp.ClientSession(headers=headers) as sess:
            async with sess.post(f"{hub_addr}/call/hub.register_sandbox", json=payload) as resp:
                txt = await resp.text()
                if resp.status == 200:
                    logger.info("[sandbox %s] hub: %s", sbx_id, txt)
                else:
                    logger.error("Hub error %s: %s", resp.status, txt)

    # 1) initial registration
    await _send_register()

    # 2) heartbeat: refresh registry entry every TTL/3
    async def _heartbeat():
        while True:
            await asyncio.sleep(_TTL // 3)
            try:
                await _send_register()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Heartbeat failed: %s", exc)

    asyncio.create_task(_heartbeat())


def _infer_endpoint(transport: str) -> Optional[str]:
    pod_ip = os.getenv("POD_IP") or os.getenv("HOSTNAME")
    if not pod_ip:
        logger.error("Cannot infer sandbox endpoint - set HUB_URL")
        return None
    if transport == "sse":
        return f"http://{pod_ip}:8000/sse"
    if transport == "stdio":
        return f"tcp://{pod_ip}:9000"
    if transport == "ws":
        return f"ws://{pod_ip}:8765/ws"
    logger.error("Unknown transport '%s'", transport)
    return None
