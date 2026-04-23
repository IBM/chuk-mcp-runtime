# chuk_mcp_runtime/proxy/manager.py
"""
chuk_mcp_runtime.proxy.manager
================================

Fully async-native implementation of the proxy manager.

Single-switch design:

* `openai_compatible: true`  → expose **underscore** aliases only
* `openai_compatible: false` → expose **dot** aliases only

The internal dot-wrapper (`proxy.<server>.<tool>`) is always generated
so underscore aliases have something to delegate to - but it's removed
from `TOOLS_REGISTRY` when OpenAI mode is on.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Callable, Dict, List

from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY
from chuk_mcp_runtime.common.openai_compatibility import (
    create_openai_compatible_wrapper,
    to_openai_compatible_name,
)
from chuk_mcp_runtime.common.tool_naming import resolve_tool_name, update_naming_maps
from chuk_mcp_runtime.proxy.tool_wrapper import create_proxy_tool
from chuk_mcp_runtime.server.logging_config import get_logger

try:
    from chuk_tool_processor.mcp import setup_mcp_stdio
except ModuleNotFoundError:  # optional dep stubs

    async def setup_mcp_stdio(*_, **__):
        raise RuntimeError("chuk_tool_processor not installed-stdio proxy unsupported")


logger = get_logger("chuk_mcp_runtime.proxy")

# ───────────────────────── helpers ──────────────────────────


def strip_proxy_prefix(name: str) -> str:
    """Remove leading "proxy." from a dotted name if present."""
    return name[6:] if name.startswith("proxy.") else name


# ───────────────────────── manager ──────────────────────────
class ProxyServerManager:
    """Spin up MCP side-cars and expose their tools locally."""

    def __init__(self, cfg: Dict[str, Any], project_root: str):
        # Accept either a plain dict or a RuntimeConfig (Pydantic model).
        # entry.py already calls cfg.to_dict(), but examples often pass the
        # RuntimeConfig directly, so normalise here for convenience.
        if hasattr(cfg, "to_dict"):
            cfg = cfg.to_dict()
        pxy = cfg.get("proxy", {})
        self.enabled = pxy.get("enabled", False)
        self.ns_root = pxy.get("namespace", "proxy")
        self.openai_mode = pxy.get("openai_compatible", False)

        self.project_root = project_root
        self.mcp_servers = cfg.get("mcp_servers", {})
        logger.debug("Proxy init-openai_mode=%s", self.openai_mode)

        self.stream_manager = None
        self.running: Dict[str, Dict[str, Any]] = {}
        self.openai_wrappers: Dict[str, Callable] = {}
        self._tmp_cfg: Any = None  # tempfile._TemporaryFileWrapper type is internal

        # Update the tool naming maps
        update_naming_maps()

    # ─────────────────────── bootstrap / shutdown ───────────────────────
    async def start_servers(self) -> None:
        if not (self.enabled and self.mcp_servers):
            logger.warning("Proxy disabled or no MCP servers configured")
            return

        stdio_cfg: Dict[str, Any] = {"mcpServers": {}}
        stdio: list[str] = []
        stdio_map: dict[int, str] = {}
        for name, opts in self.mcp_servers.items():
            if opts.get("type", "stdio") != "stdio":
                continue
            stdio.append(name)
            stdio_map[len(stdio_map)] = name
            cwd = opts.get("location", "")
            if cwd and not os.path.isabs(cwd):
                cwd = os.path.join(self.project_root, cwd)
            stdio_cfg["mcpServers"][name] = {
                "command": opts.get("command", "python"),
                "args": opts.get("args", []),
                "cwd": cwd,
            }

        if not stdio:
            logger.error("No stdio servers configured")
            return

        self._tmp_cfg = tempfile.NamedTemporaryFile(mode="w", delete=False)
        json.dump(stdio_cfg, self._tmp_cfg)
        self._tmp_cfg.flush()
        _, self.stream_manager = await setup_mcp_stdio(
            config_file=self._tmp_cfg.name,
            servers=stdio,
            server_names=stdio_map,
            namespace=self.ns_root,
        )

        for srv in stdio:
            self.running[srv] = {"wrappers": {}}

        await self._discover_and_wrap()

        # Update naming maps after discovering tools
        update_naming_maps()

    async def stop_servers(self) -> None:
        if self.stream_manager:
            await self.stream_manager.close()
        if self._tmp_cfg:
            try:
                os.unlink(self._tmp_cfg.name)
            except OSError:
                pass

    # ───────────────────── internal helpers ─────────────────────
    async def _discover_and_wrap(self) -> None:
        if not self.stream_manager:
            return

        for server in self.running:
            for meta in await self.stream_manager.list_tools(server):
                tool_name = meta.get("name")
                if not tool_name:
                    continue

                dotted_ns = f"{self.ns_root}.{server}"
                dotted_full = f"{dotted_ns}.{tool_name}"

                # 1) Always create internal dot-wrapper
                wrapper = await create_proxy_tool(dotted_ns, tool_name, self.stream_manager, meta)
                self.running[server]["wrappers"][tool_name] = wrapper

                if self.openai_mode:
                    # Remove dot-wrapper from public registry
                    TOOLS_REGISTRY.pop(dotted_full, None)

                    # Build underscore alias once
                    under_name = to_openai_compatible_name(strip_proxy_prefix(dotted_full))
                    if under_name in self.openai_wrappers:
                        continue
                    alias = await create_openai_compatible_wrapper(dotted_full, wrapper)
                    if alias:
                        TOOLS_REGISTRY[under_name] = alias
                        self.openai_wrappers[under_name] = alias
                        logger.debug("Registered underscore wrapper: %s", under_name)
                # else (non-OpenAI mode) → keep dot wrapper; no underscore alias

        dot = [k for k in TOOLS_REGISTRY if "." in k]
        under = [k for k in TOOLS_REGISTRY if "_" in k and "." not in k]
        logger.debug("Registry overview-dot:%d | under:%d", len(dot), len(under))

        # Update naming maps after wrapping tools
        update_naming_maps()

    # ───────────────────── public helpers ─────────────────────────
    async def get_all_tools(self) -> Dict[str, Callable]:
        if self.openai_mode:
            return dict(self.openai_wrappers)
        # expose dot names
        exposed: Dict[str, Callable] = {}
        for srv, info in self.running.items():
            exposed.update({f"{self.ns_root}.{srv}.{n}": fn for n, fn in info["wrappers"].items()})
        return exposed

    async def call_tool(self, name: str, **kw):
        """Convenience proxy that maps between different tool naming conventions."""
        # First try to resolve the name using the compatibility layer
        resolved_name = resolve_tool_name(name)

        # If it's still not found in TOOLS_REGISTRY, try manual conversion
        if resolved_name not in TOOLS_REGISTRY:
            if "_" in name and name not in TOOLS_REGISTRY:
                # Convert back to dotted form
                parts = name.split("_", 1)
                if len(parts) == 2:
                    server, tool = parts
                    name = f"{self.ns_root}.{server}.{tool}"
            elif "." in name and name not in TOOLS_REGISTRY:
                # Try to extract the server and tool parts
                parts = name.split(".")
                if len(parts) >= 2:
                    server = parts[-2]
                    tool = parts[-1]
                    # Try different combinations
                    name = f"{self.ns_root}.{server}.{tool}"
        else:
            name = resolved_name

        # Extract server and tool information
        if name.startswith(f"{self.ns_root}."):
            parts = name[len(self.ns_root) + 1 :].split(".")
            if len(parts) >= 2:
                srv = parts[0]
                tool = parts[-1]
            else:
                # Fallback
                srv = name.split(".")[1] if len(name.split(".")) > 1 else ""
                tool = name.split(".")[-1]
        else:
            # Fallback to simple splitting
            parts = name.split(".")
            srv = parts[0] if len(parts) > 1 else ""
            tool = parts[-1]

        # Log the resolution for debugging
        logger.debug(f"Calling tool {tool} on server {srv} (from original name: {name})")

        # Make sure the stream manager exists
        if not self.stream_manager:
            raise RuntimeError("Stream manager not initialized")

        # Execute the tool via the stream manager
        return await self.stream_manager.call_tool(tool, kw, srv)  # type: ignore[arg-type]

    async def process_text(self, text: str) -> List[Dict[str, Any]]:
        """Process text with any available text processors in the proxy servers."""
        results: list[dict[str, Any]] = []

        # Check if any server supports text processing
        for server_name, server_info in self.running.items():
            if not self.stream_manager:
                continue

            try:
                # Try to call a 'process_text' tool if available
                processor_name = "process_text"
                tools = await self.stream_manager.list_tools(server_name)
                has_processor = any(t.get("name") == processor_name for t in tools)

                if has_processor:
                    logger.debug(f"Calling {server_name}.process_text")
                    result = await self.stream_manager.call_tool(
                        processor_name, {"text": text}, server_name
                    )

                    if isinstance(result, dict) and not result.get("isError", False):
                        results.append(
                            {
                                "server": server_name,
                                "content": result.get("content", []),
                            }
                        )
            except Exception as e:
                logger.error(f"Error processing text with {server_name}: {e}")

        return results
