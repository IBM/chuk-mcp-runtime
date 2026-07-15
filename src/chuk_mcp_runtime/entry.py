# chuk_mcp_runtime/entry.py
"""
Entry point for the CHUK MCP Runtime - async-native, proxy-aware,
with native session management and automatic chuk_artifacts integration.
"""

from __future__ import annotations

import asyncio
import os
import sys
from inspect import iscoroutinefunction
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple, Union

from dotenv import load_dotenv

load_dotenv()

from chuk_mcp_runtime.common.mcp_tool_decorator import (
    TOOLS_REGISTRY,
    initialize_tool_registry,
)
from chuk_mcp_runtime.common.openai_compatibility import (
    initialize_openai_compatibility,
)
from chuk_mcp_runtime.proxy.manager import ProxyServerManager
from chuk_mcp_runtime.server.config_loader import find_project_root, load_config
from chuk_mcp_runtime.server.logging_config import configure_logging, get_logger
from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.server.server_registry import ServerRegistry
from chuk_mcp_runtime.session.native_session_management import (
    create_mcp_session_manager,
)
from chuk_mcp_runtime.tools import (
    get_artifact_tools,
    register_artifacts_tools,
    register_session_tools,
)
from chuk_mcp_runtime.types import RuntimeConfig

logger = get_logger("chuk_mcp_runtime.entry")

# ───────────────────────────── Tool Registration ──────────────────────────

# ───────────────────────────── Configuration ──────────────────────────────
HAS_PROXY_SUPPORT = True  # tests may override


def _need_proxy(cfg: Union[RuntimeConfig, dict[str, Any]]) -> bool:
    """Check if proxy functionality is needed and available."""
    # Handle both RuntimeConfig and dict (for test compatibility)
    if isinstance(cfg, dict):
        enabled = cfg.get("proxy", {}).get("enabled", False)
    else:
        enabled = cfg.proxy.enabled
    return bool(enabled) and HAS_PROXY_SUPPORT


# ───────────────────────────── Helper Functions ────────────────────────────
def _iter_tools(container) -> Iterable[Tuple[str, Any]]:
    """Yield (name, callable) pairs from artifact tools container."""
    from chuk_mcp_runtime.tools import artifacts_tools as _at_mod

    if container is None:
        return

    if isinstance(container, dict):
        yield from ((n, f) for n, f in container.items() if hasattr(f, "_mcp_tool"))
    elif isinstance(container, (list, tuple, set)):
        for name in container:
            fn = TOOLS_REGISTRY.get(name) or getattr(_at_mod, name, None)
            if fn and hasattr(fn, "_mcp_tool"):
                yield name, fn
    else:
        logger.debug("Unexpected get_artifact_tools() return type: %s", type(container))


# ───────────────────────────── Main Runtime Function ──────────────────────
async def run_runtime_async(
    config_paths: Optional[List[Union[str, Path]]] = None,
    default_config: Optional[RuntimeConfig] = None,
    bootstrap_components: bool = True,
) -> None:
    """Boot the complete CHUK MCP runtime with native session management."""

    # 1) Configuration and logging setup
    cfg = load_config(config_paths, default_config)
    # Handle both RuntimeConfig and dict (for test mocks)
    if isinstance(cfg, dict):
        cfg = RuntimeConfig.from_dict(cfg)
    configure_logging(cfg.to_dict())
    project_root = find_project_root()
    logger.debug("Project root resolved to %s", project_root)

    # 2) Native session management initialization
    session_manager = create_mcp_session_manager(cfg)
    logger.debug("Native session manager initialized for sandbox: %s", session_manager.sandbox_id)

    # 3) Optional component bootstrap
    if bootstrap_components and not os.getenv("NO_BOOTSTRAP"):
        await ServerRegistry(project_root, cfg.to_dict()).load_server_components()

    # 4) Tool registry initialization
    await initialize_tool_registry()

    # 5) Artifact management tools
    await register_artifacts_tools(cfg.to_dict())
    logger.debug("Artifact tools registration completed")

    # 6) Session management tools
    # Pass the session manager to session tools
    session_cfg_dict = cfg.to_dict()
    if "session_tools" not in session_cfg_dict:
        session_cfg_dict["session_tools"] = {}
    session_cfg_dict["session_tools"]["session_manager"] = session_manager

    await register_session_tools(session_cfg_dict)
    logger.debug("Session tools registration completed")

    # 7) OpenAI compatibility layer
    try:
        if callable(initialize_openai_compatibility):
            if iscoroutinefunction(initialize_openai_compatibility):
                await initialize_openai_compatibility()
            else:
                # initialize_openai_compatibility is declared async, but
                # tests may monkeypatch it with a sync mock, so the runtime
                # check above is load-bearing even though mypy sees this
                # branch as statically unreachable.
                initialize_openai_compatibility()  # type: ignore[unused-coroutine]
    except Exception as exc:
        logger.warning("OpenAI-compat init failed: %s", exc)

    # 8) Proxy layer setup
    proxy_mgr = None
    if _need_proxy(cfg):
        try:
            proxy_mgr = ProxyServerManager(cfg.to_dict(), project_root)
            await proxy_mgr.start_servers()
            if proxy_mgr.running:
                logger.debug("Proxy layer enabled - %d server(s) booted", len(proxy_mgr.running))
        except Exception as exc:
            logger.error("Proxy bootstrap error: %s", exc, exc_info=True)
            proxy_mgr = None

    # 9) Main MCP server with native session management
    mcp_server = MCPServer(cfg, tools_registry=TOOLS_REGISTRY)
    logger.debug(
        "Local MCP server '%s' starting with native sessions",
        getattr(mcp_server, "server_name", "local"),
    )

    # 10) Log statistics
    tool_total = len(TOOLS_REGISTRY)
    art_related = sum(
        1
        for n in TOOLS_REGISTRY
        if any(kw in n for kw in ("file", "upload", "write", "read", "list"))
    )
    logger.debug("Tools in registry: %d total, %d artifact-related", tool_total, art_related)

    session_stats = session_manager.get_cache_stats()
    logger.debug("Session manager stats: %s", session_stats)

    # 11) Register additional artifact tools
    for name, fn in _iter_tools(get_artifact_tools()):
        try:
            await mcp_server.register_tool(name, fn)
        except Exception as exc:
            logger.error("Failed to register tool %s: %s", name, exc)

    # 12) Register proxy tools
    if proxy_mgr and hasattr(proxy_mgr, "get_all_tools"):
        for name, fn in (await proxy_mgr.get_all_tools()).items():
            try:
                await mcp_server.register_tool(name, fn)
            except Exception as exc:
                logger.error("Proxy tool %s registration error: %s", name, exc)

    # 13) Setup proxy text handler
    custom_handlers = None
    if proxy_mgr and hasattr(proxy_mgr, "process_text"):

        async def _handle_proxy_text(text: str):
            try:
                return await proxy_mgr.process_text(text)
            except Exception as exc:
                logger.error("Proxy text handler error: %s", exc, exc_info=True)
                return [{"error": f"Proxy error: {exc}"}]

        custom_handlers = {"handle_proxy_text": _handle_proxy_text}

    # 14) Serve forever
    try:
        await mcp_server.serve(custom_handlers=custom_handlers)
    finally:
        # Cleanup proxy layer
        if proxy_mgr:
            logger.debug("Stopping proxy layer")
            await proxy_mgr.stop_servers()


# ───────────────────────────── Sync Wrapper ─────────────────────────────────
def run_runtime(
    config_paths: Optional[List[Union[str, Path]]] = None,
    default_config: Optional[RuntimeConfig] = None,
    bootstrap_components: bool = True,
) -> None:
    """Synchronous wrapper for the async runtime."""
    try:
        asyncio.run(
            run_runtime_async(
                config_paths=config_paths,
                default_config=default_config,
                bootstrap_components=bootstrap_components,
            )
        )
    except KeyboardInterrupt:
        logger.warning("Received Ctrl-C → shutting down")
    except Exception as exc:
        logger.error("Uncaught exception: %s", exc, exc_info=True)
        raise


# ───────────────────────────── CLI Entry Points ────────────────────────────
async def main_async(default_config: Optional[RuntimeConfig] = None) -> None:
    """Async CLI entry point."""
    try:
        # Parse command line arguments for config file
        argv = sys.argv[1:]
        cfg_path = (
            os.getenv("CHUK_MCP_CONFIG_PATH")
            or (argv[argv.index("-c") + 1] if "-c" in argv else None)
            or (argv[argv.index("--config") + 1] if "--config" in argv else None)
            or (argv[0] if argv else None)
        )

        await run_runtime_async(
            config_paths=[cfg_path] if cfg_path else None,
            default_config=default_config,
        )
    except Exception as exc:
        print(f"Error starting CHUK MCP server: {exc}", file=sys.stderr)
        sys.exit(1)


def main(default_config: Optional[RuntimeConfig] = None) -> None:
    """Main CLI entry point."""
    try:
        asyncio.run(main_async(default_config))
    except KeyboardInterrupt:
        logger.warning("Received Ctrl-C → shutting down")
    except Exception as exc:
        logger.error("Uncaught exception: %s", exc, exc_info=True)
        sys.exit(1)


# ───────────────────────────── Direct Execution ────────────────────────────
if __name__ == "__main__":
    main()
