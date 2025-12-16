# chuk_mcp_runtime/server/server.py
"""
CHUK MCP Server

* automatic session-ID injection for artifact tools via native session management
* optional bearer-token auth middleware
* transparent chuk_artifacts integration
* MCP resources integration with session-isolated artifact access
* global **and per-tool** timeout support
* end-to-end **token streaming** for async-generator tools
* JSON concatenation fixing for tool parameters
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import json
import os
import re
import time
from http.cookies import SimpleCookie
from inspect import (
    isasyncgen,
    isasyncgenfunction,
    iscoroutinefunction,
)
from typing import Any, AsyncIterator, Callable, List, Optional, Union

import uvicorn

# ─────────────────────────── chuk_artifacts integration ──────────────────────
from chuk_artifacts import ArtifactNotFoundError, ArtifactStore
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import (
    EmbeddedResource,
    ImageContent,
    Resource,
    TextContent,
    Tool,
)
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from chuk_mcp_runtime.common.mcp_resource_decorator import (
    get_registered_resources,
    get_resource_function,
    initialize_resource_registry,
)
from chuk_mcp_runtime.common.mcp_tool_decorator import (
    TOOLS_REGISTRY,
    initialize_tool_registry,
)
from chuk_mcp_runtime.common.tool_naming import resolve_tool_name, update_naming_maps
from chuk_mcp_runtime.common.verify_credentials import validate_token
from chuk_mcp_runtime.server.event_store import InMemoryEventStore
from chuk_mcp_runtime.server.logging_config import get_logger
from chuk_mcp_runtime.server.request_context import (
    MCPRequestContext,
    set_request_context,
    set_request_headers,
)
from chuk_mcp_runtime.session.native_session_management import (
    MCPSessionManager,
    SessionContext,
    create_mcp_session_manager,
    with_session_auto_inject,
)
from chuk_mcp_runtime.types import RuntimeConfig, ServerType, StorageProvider

# ------------------------------------------------------------------------------
# JSON Concatenation Fix Utilities
# ------------------------------------------------------------------------------


def parse_tool_arguments(arguments: Union[str, dict[str, Any]]) -> dict[str, Any]:
    """
    Parse tool arguments, handling concatenated JSON strings.

    Handles cases like: {"text":"hello"}{"delay":0.5} -> {"text":"hello", "delay":0.5}
    """
    # If it's already a dict, return as-is (most common case)
    if isinstance(arguments, dict):
        return arguments

    # If it's None or empty, return empty dict
    if not arguments:
        return {}

    # Handle string arguments (where concatenation might occur)
    if isinstance(arguments, str):
        # First, try to parse as normal JSON
        try:
            parsed = json.loads(arguments)
            # If successful and it's a dict, return it
            if isinstance(parsed, dict):
                return parsed
            # If it's not a dict, wrap it
            return {"value": parsed}
        except json.JSONDecodeError:
            pass

        # If normal parsing failed, try to fix concatenated JSON
        if "}" in arguments and "{" in arguments:
            # Pattern to find }{ concatenations (with optional whitespace)
            pattern = r"\}\s*\{"
            if re.search(pattern, arguments):
                # Replace }{ with },{ to make it a valid JSON array
                array_str = "[" + re.sub(pattern, "},{", arguments) + "]"
                try:
                    # Parse as array of objects
                    objects = json.loads(array_str)

                    # Merge all objects into one
                    merged = {}
                    for obj in objects:
                        if isinstance(obj, dict):
                            merged.update(obj)
                        else:
                            # If non-dict object in array, add with index
                            merged[f"value_{len(merged)}"] = obj

                    return merged
                except json.JSONDecodeError:
                    # If parsing the array fails, fall through to string handling
                    pass

        # If all JSON parsing fails, treat as plain string
        return {"text": arguments}

    # For any other type, convert to string and wrap
    return {"value": str(arguments)}


# ------------------------------------------------------------------------------
# Authentication middleware
# ------------------------------------------------------------------------------
class AuthMiddleware:
    """Simple bearer-token / cookie-based auth implemented as plain ASGI middleware."""

    def __init__(
        self,
        app: ASGIApp,
        auth: Optional[str] = None,
        health_path: str = "/health",
    ) -> None:
        self.app = app
        self.auth = auth
        self.health_path = health_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Let non-HTTP traffic pass straight through (e.g. websockets).
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]
        method: str = scope["method"]

        # --------------------  Extract headers  --------------------
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        scope["headers_dict"] = headers  # Always store headers for request context

        # Health check or "auth disabled" → no checks.
        if (path == self.health_path and method == "GET") or self.auth != "bearer":
            await self.app(scope, receive, send)
            return

        # --------------------  Extract token  --------------------
        token: Optional[str] = None

        # 1)  Authorization: Bearer <token>
        auth_header = headers.get("authorization")
        if auth_header:
            m = re.match(r"Bearer\s+(.+)", auth_header, re.I)
            if m:
                token = m.group(1)

        # 2)  Cookie: jwt_token=<token>
        if not token and "cookie" in headers:
            cookie = SimpleCookie()
            cookie.load(headers["cookie"])
            if "jwt_token" in cookie:
                token = cookie["jwt_token"].value
        # ---------------------------------------------------------

        if not token:
            await JSONResponse({"error": "Not authenticated"}, status_code=401)(
                scope, receive, send
            )
            return

        try:
            payload = await validate_token(token)
            scope["user"] = payload  # Stash for downstream handlers.
        except HTTPException as exc:
            await JSONResponse({"error": exc.detail}, status_code=exc.status_code)(
                scope, receive, send
            )
            return

        # Auth successful → continue.
        await self.app(scope, receive, send)


# ------------------------------------------------------------------------------
# MCPServer
# ------------------------------------------------------------------------------

_ARTIFACT_RX = re.compile(
    r"\b("
    r"write_file|upload_file|read_file|delete_file|"
    r"list_session_files|list_directory|copy_file|move_file|"
    r"get_file_metadata|get_presigned_url|get_storage_stats"
    r")\b"
)


class MCPServer:
    """
    Central MCP server with native session & artifact-store support.

    Type-safe, Pydantic-based configuration.
    Fully async-native implementation.
    """

    def __init__(
        self,
        config: Union[RuntimeConfig, dict[str, Any]],
        tools_registry: Optional[dict[str, Callable]] = None,
    ) -> None:
        # Support both RuntimeConfig and dict for backwards compatibility
        if isinstance(config, dict):
            self.config = RuntimeConfig.from_dict(config)
        else:
            self.config = config
        self.logger = get_logger("chuk_mcp_runtime.server", self.config.to_dict())
        self.server_name = self.config.host.name
        self.tools_registry = tools_registry or TOOLS_REGISTRY

        # Native session management
        self.session_manager = create_mcp_session_manager(self.config)

        # Artifact store
        self.artifact_store: Optional[ArtifactStore] = None

        # Tool timeout configuration
        self.tool_timeout = self._get_tool_timeout()
        self.logger.debug("Tool timeout configured: %.1fs (global default)", self.tool_timeout)

        update_naming_maps()  # make sure resolve_tool_name works

    def _get_tool_timeout(self) -> float:
        """Pick global timeout from config/env with sane fall-back."""
        # Check config first (Pydantic typed)
        if self.config.tools.timeout is not None:
            return self.config.tools.timeout

        # Check environment variables
        for env_var in ["MCP_TOOL_TIMEOUT", "TOOL_TIMEOUT"]:
            value = os.getenv(env_var)
            if value is not None:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    continue

        # Default
        return 60.0

    async def _setup_artifact_store(self) -> None:
        """Setup the artifact store with native session management."""
        cfg = self.config.artifacts

        # Get storage provider (config or env)
        storage = os.getenv("ARTIFACT_STORAGE_PROVIDER", cfg.storage_provider.value)

        # Get session provider (config or env)
        session = os.getenv("ARTIFACT_SESSION_PROVIDER", cfg.session_provider.value)

        # Get bucket (config or env)
        bucket = cfg.bucket or os.getenv("ARTIFACT_BUCKET", f"mcp-{self.server_name}")

        # Filesystem root (only when storage == filesystem)
        if storage == StorageProvider.FILESYSTEM.value:
            fs_root = (
                cfg.filesystem_root
                or os.getenv("ARTIFACT_FS_ROOT")
                or os.path.expanduser(f"~/.chuk_mcp_artifacts/{self.server_name}")
            )
            os.environ["ARTIFACT_FS_ROOT"] = fs_root  # chuk_artifacts honours this

        try:
            self.artifact_store = ArtifactStore(
                storage_provider=storage, session_provider=session, bucket=bucket
            )
            status = await self.artifact_store.validate_configuration()
            if status["session"]["status"] == "ok" and status["storage"]["status"] == "ok":
                self.logger.debug("Artifact store ready: %s/%s → %s", storage, session, bucket)
            else:
                self.logger.warning("Artifact-store config issues: %s", status)
        except Exception as exc:
            self.logger.error("Artifact-store init failed: %s", exc)
            self.artifact_store = None

    async def _import_tools_registry(self) -> dict[str, Callable]:
        """Import tools registry from configuration."""
        mod = self.config.tools.registry_module
        attr = self.config.tools.registry_attr

        try:
            m = importlib.import_module(mod)
            if iscoroutinefunction(getattr(m, "initialize_tool_registry", None)):
                await m.initialize_tool_registry()
            registry: dict[str, Callable] = getattr(m, attr, {})
        except Exception as exc:
            self.logger.error("Unable to import tool registry: %s", exc)
            registry = {}

        update_naming_maps()
        return registry

    async def _inject_session_context(
        self, tool_name: str, args: dict[str, Any], tool_func: Optional[Callable] = None
    ) -> dict[str, Any]:
        """Auto-inject session context using native session manager."""
        return await with_session_auto_inject(self.session_manager, tool_name, args, tool_func)

    async def _execute_tool_with_timeout(
        self, func: Callable, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        """
        Execute a tool with timeout support.

        * Coroutine tools → awaited with asyncio.wait_for()
        * Async-generator tools → streamed, still respecting timeout
        """
        timeout = getattr(func, "_tool_timeout", None) or self.tool_timeout

        # ── async-generator branch ───────────────────────────────────────────
        if isasyncgenfunction(func):
            agen = func(**arguments)  # create generator
            start = time.time()

            async def _wrapper():
                nonlocal start
                try:
                    async for chunk in agen:
                        yield chunk
                        if (time.time() - start) >= timeout:
                            raise asyncio.TimeoutError()
                finally:
                    await agen.aclose()

            return _wrapper()  # caller will iterate

        # ── classic coroutine branch ─────────────────────────────────────────
        try:
            self.logger.debug("Executing tool '%s' (timeout %.1fs)", tool_name, timeout)
            return await asyncio.wait_for(func(**arguments), timeout=timeout)
        except asyncio.TimeoutError:
            raise ValueError(f"Tool '{tool_name}' timed out after {timeout:.1f}s")

    async def serve(self, custom_handlers: Optional[dict[str, Callable]] = None) -> None:
        """Boot the MCP server and serve forever."""
        await self._setup_artifact_store()

        if not self.tools_registry:
            self.tools_registry = await self._import_tools_registry()

        await initialize_tool_registry()
        await initialize_resource_registry()
        update_naming_maps()

        server = Server(self.server_name)

        # ----------------------------- list_tools ----------------------------- #
        @server.list_tools()
        async def list_tools() -> List[Tool]:
            """List available tools with robust error handling."""
            try:
                self.logger.debug("list_tools called - %d tools total", len(self.tools_registry))

                tools = []
                for tool_name, func in self.tools_registry.items():
                    try:
                        if hasattr(func, "_mcp_tool"):
                            tool_obj = func._mcp_tool

                            # Verify the tool object is valid
                            if hasattr(tool_obj, "name") and hasattr(tool_obj, "description"):
                                tools.append(tool_obj)
                                self.logger.debug("Added tool to list: %s", tool_obj.name)
                            else:
                                self.logger.warning(
                                    "Tool %s has invalid _mcp_tool object: %s",
                                    tool_name,
                                    tool_obj,
                                )
                        else:
                            self.logger.warning("Tool %s missing _mcp_tool attribute", tool_name)

                    except Exception as e:
                        self.logger.error("Error processing tool %s: %s", tool_name, e)
                        continue

                self.logger.debug("Returning %d valid tools", len(tools))
                return tools

            except Exception as e:
                self.logger.error("Error in list_tools: %s", e)
                return []

        # ----------------------------- call_tool ----------------------------- #
        @server.call_tool()
        async def call_tool(
            name: str, arguments: dict[str, Any]
        ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
            """Execute a tool with native session management."""
            try:
                # Fix concatenated JSON in arguments
                original_args = arguments
                if arguments:
                    if isinstance(arguments, (str, dict)):
                        arguments = parse_tool_arguments(arguments)

                        if arguments != original_args:
                            self.logger.debug(
                                "Fixed concatenated JSON arguments for '%s': %s -> %s",
                                name,
                                original_args,
                                arguments,
                            )

                self.logger.debug("call_tool called with name='%s', arguments=%s", name, arguments)

                # Tool name resolution
                resolved = name if name in self.tools_registry else resolve_tool_name(name)
                if resolved not in self.tools_registry:
                    matches = [
                        k
                        for k in self.tools_registry
                        if k.endswith(f"_{name}") or k.endswith(f".{name}")
                    ]
                    if len(matches) == 1:
                        resolved = matches[0]

                if resolved not in self.tools_registry:
                    raise ValueError(f"Tool not found: {name}")

                func = self.tools_registry[resolved]
                self.logger.debug("Resolved tool '%s' to function: %s", name, func)

                # Capture MCP request context for progress notifications
                mcp_ctx = getattr(server, "request_context", None)
                progress_token = None
                mcp_session = None

                if mcp_ctx:
                    # Extract progress token from request metadata
                    if hasattr(mcp_ctx, "meta") and mcp_ctx.meta:
                        progress_token = getattr(mcp_ctx.meta, "progressToken", None)
                    # Get the MCP session
                    mcp_session = getattr(mcp_ctx, "session", None)

                # Set request context for tools to access via send_progress()
                set_request_context(
                    MCPRequestContext(
                        session=mcp_session,
                        progress_token=progress_token,
                        meta=getattr(mcp_ctx, "meta", None) if mcp_ctx else None,
                    )
                )

                # Native session injection
                arguments = await self._inject_session_context(resolved, arguments, func)

                # Execute within session context
                # Use MCP session if available, otherwise use session_id from arguments
                effective_session_id = (
                    mcp_session.session_id
                    if mcp_session and hasattr(mcp_session, "session_id")
                    else arguments.get("session_id")
                )
                async with SessionContext(
                    self.session_manager,
                    session_id=effective_session_id,
                    auto_create=True,
                ) as session_id:
                    self.logger.info(
                        f"[SESSION] Executing tool '{resolved}' in session {session_id}"
                    )
                    self.logger.debug(
                        "Executing tool '%s' in session %s (progress_token=%s)",
                        resolved,
                        session_id,
                        progress_token,
                    )
                    result = await self._execute_tool_with_timeout(func, resolved, arguments)
                    # Clear request context after execution
                    set_request_context(None)
                    self.logger.debug("Tool execution completed, result type: %s", type(result))

                    # Handle streaming results
                    if isasyncgen(result):
                        self.logger.debug(
                            "Tool returned async generator, collecting chunks for '%s'",
                            resolved,
                        )

                        collected_chunks = []
                        chunk_count = 0

                        try:
                            async for part in result:
                                chunk_count += 1
                                self.logger.debug(
                                    "Collecting streaming chunk %d for '%s'",
                                    chunk_count,
                                    resolved,
                                )

                                if isinstance(part, (TextContent, ImageContent, EmbeddedResource)):
                                    collected_chunks.append(part)
                                elif isinstance(part, str):
                                    collected_chunks.append(TextContent(type="text", text=part))
                                elif isinstance(part, dict) and "delta" in part:
                                    collected_chunks.append(
                                        TextContent(type="text", text=part["delta"])
                                    )
                                else:
                                    collected_chunks.append(
                                        TextContent(
                                            type="text",
                                            text=json.dumps(part, ensure_ascii=False),
                                        )
                                    )

                            return (
                                collected_chunks
                                if collected_chunks
                                else [
                                    TextContent(
                                        type="text",
                                        text="No output from streaming tool",
                                    )
                                ]
                            )

                        except Exception as e:
                            self.logger.error(
                                "Error collecting streaming chunks for '%s': %s",
                                resolved,
                                e,
                            )
                            return [TextContent(type="text", text=f"Streaming error: {str(e)}")]

                    # Handle regular results
                    self.logger.debug("Tool returned non-streaming result for '%s'", resolved)

                    # Format artifact tool results
                    if _ARTIFACT_RX.search(resolved):
                        if isinstance(result, dict) and not (
                            "content" in result and "isError" in result
                        ):
                            result = {
                                "session_id": session_id,
                                "content": result,
                                "isError": False,
                            }
                        elif isinstance(result, str):
                            result = {
                                "session_id": session_id,
                                "content": result,
                                "isError": False,
                            }

                    # Format response
                    if isinstance(result, list) and all(
                        isinstance(r, (TextContent, ImageContent, EmbeddedResource)) for r in result
                    ):
                        return result
                    elif isinstance(result, str):
                        return [TextContent(type="text", text=result)]
                    else:
                        return [TextContent(type="text", text=json.dumps(result, indent=2))]

            except Exception as e:
                self.logger.error("Error in call_tool for '%s': %s", name, e)
                return [TextContent(type="text", text=f"Tool execution error: {str(e)}")]

        # ----------------------------- list_resources ----------------------------- #
        @server.list_resources()
        async def list_resources() -> List[Resource]:
            """
            List all available resources:
            1. Custom resources (from @mcp_resource decorators)
            2. Artifact resources (session-isolated files)
            """
            all_resources = []

            # Part 1: Add custom resources (from decorators)
            try:
                custom_resources = get_registered_resources()
                all_resources.extend(custom_resources)
                self.logger.debug("Added %d custom resources", len(custom_resources))
            except Exception as e:
                self.logger.error("Failed to list custom resources: %s", e)

            # Part 2: Add artifact resources (session-isolated)
            if self.config.artifacts.enabled:
                current_session = self.session_manager.get_current_session()

                if current_session and self.artifact_store:
                    try:
                        # CRITICAL: Only list files in the CURRENT session
                        files = await self.artifact_store.list_by_session(current_session)

                        for f in files:
                            artifact_id = f.get("artifact_id", "")
                            if not artifact_id:
                                continue

                            uri = f"artifact://{artifact_id}"

                            all_resources.append(
                                Resource(
                                    uri=uri,
                                    name=f.get("filename", "unknown"),
                                    description=f.get("summary", ""),
                                    mimeType=f.get("mime", "application/octet-stream"),
                                )
                            )

                        self.logger.debug(
                            "Added %d artifact resources for session %s",
                            len(files),
                            current_session,
                        )
                    except Exception as e:
                        self.logger.error("Failed to list artifact resources: %s", e)
                else:
                    if not current_session:
                        self.logger.debug("No session context - skipping artifact resources")
                    if not self.artifact_store:
                        self.logger.debug("Artifact store not initialized")

            self.logger.debug("Listing %d total resources", len(all_resources))
            return all_resources

        # ----------------------------- read_resource ----------------------------- #
        @server.read_resource()
        async def read_resource(uri: str):
            """
            Read resource content from custom resources or artifacts.

            Handles:
            1. Custom resources (from @mcp_resource decorators)
            2. Artifact resources (session-isolated files)
            """

            # Try custom resources first
            # Convert AnyUrl to string if needed
            uri_str = str(uri)
            resource_func = get_resource_function(uri_str)
            if resource_func:
                try:
                    self.logger.debug("Reading custom resource: %s", uri)

                    # Call the resource function
                    result = resource_func()
                    if inspect.iscoroutine(result):
                        result = await result

                    # Get MIME type from metadata
                    mime_type = getattr(resource_func, "_mcp_resource", None)
                    mime = mime_type.mimeType if mime_type else "text/plain"

                    # SDK accepts: str | bytes | Iterable[ReadResourceContents]
                    # Return raw string/bytes for simple cases
                    if isinstance(result, bytes):
                        return result
                    else:
                        return str(result)

                except Exception as e:
                    self.logger.error("Failed to read custom resource %s: %s", uri, e)
                    raise ValueError(f"Failed to read custom resource: {str(e)}")

            # Try artifact resources
            if uri_str.startswith("artifact://"):
                if not self.config.artifacts.enabled:
                    raise ValueError("Artifacts not enabled")

                current_session = self.session_manager.get_current_session()
                if not current_session:
                    raise ValueError("No session context - cannot read artifact resource")

                if not self.artifact_store:
                    raise ValueError("Artifact store not initialized")

                try:
                    artifact_id = uri.replace("artifact://", "").strip("/")
                    if not artifact_id:
                        raise ValueError("Invalid URI: missing artifact ID")

                    # Get metadata first to verify session ownership
                    metadata = await self.artifact_store.metadata(artifact_id)
                    resource_session = metadata.get("session_id")

                    # CRITICAL SECURITY CHECK: Verify session ownership
                    if resource_session != current_session:
                        self.logger.warning(
                            "Session isolation violation: artifact %s belongs to %s, "
                            "requested by %s",
                            artifact_id,
                            resource_session,
                            current_session,
                        )
                        raise ValueError("Access denied: resource belongs to different session")

                    # Session validated - safe to read
                    data = await self.artifact_store.retrieve(artifact_id)
                    mime = metadata.get("mime", "application/octet-stream")

                    # SDK accepts: str | bytes | Iterable[ReadResourceContents]
                    # Return raw string/bytes for simple cases
                    if mime.startswith("text/"):
                        return data.decode("utf-8")
                    else:
                        return data

                except ArtifactNotFoundError:
                    self.logger.warning("Artifact resource not found: %s", uri)
                    raise ValueError(f"Resource not found: {uri}")
                except Exception as e:
                    self.logger.error("Failed to read artifact resource %s: %s", uri, e)
                    raise ValueError(f"Failed to read resource: {str(e)}")

            # Resource not found
            raise ValueError(f"Resource not found: {uri}")

        # ------------------------------------------------------------------ #
        # Transport bootstrapping (stdio / SSE / StreamableHTTP)            #
        # ------------------------------------------------------------------ #
        opts = server.create_initialization_options()
        mode = self.config.server.type

        if mode == ServerType.STDIO:
            self.logger.info("Starting MCP (stdio) - global timeout %.1fs", self.tool_timeout)
            async with stdio_server() as (r, w):
                await server.run(r, w, opts)

        elif mode == ServerType.SSE:
            cfg = self.config.sse
            host, port = cfg.host, cfg.port
            sse_path, msg_path, health_path = (
                cfg.sse_path,
                cfg.message_path,
                cfg.health_path,
            )
            transport = SseServerTransport(msg_path)

            async def _handle_sse(request: Request):
                # Extract and store headers for tools to access
                headers_dict = request.scope.get("headers_dict", {})
                set_request_headers(headers_dict)

                try:
                    async with transport.connect_sse(
                        request.scope, request.receive, request._send
                    ) as streams:
                        await server.run(streams[0], streams[1], opts)
                except Exception as e:
                    # Handle client disconnections gracefully
                    if "ClosedResourceError" in str(type(e).__name__):
                        self.logger.debug("Client disconnected from SSE stream")
                    else:
                        self.logger.error("Error in SSE handler: %s", e)
                        raise
                return Response()

            async def health(request):
                return PlainTextResponse("OK")

            app = Starlette(
                routes=[
                    Route(sse_path, _handle_sse, methods=["GET"]),
                    Mount(msg_path, app=transport.handle_post_message),
                    Route(health_path, health, methods=["GET"]),
                ],
                middleware=[
                    Middleware(
                        AuthMiddleware,
                        auth=self.config.server.auth.value if self.config.server.auth else None,
                        health_path=health_path,
                    )
                ],
            )
            self.logger.info(
                "Starting MCP (SSE) on %s:%s - global timeout %.1fs",
                host,
                port,
                self.tool_timeout,
            )
            await uvicorn.Server(
                uvicorn.Config(app, host=host, port=port, log_level="info")
            ).serve()

        elif mode == ServerType.STREAMABLE_HTTP:
            self.logger.info("Starting MCP server over streamable-http")

            # Get streamable-http server configuration
            http_cfg = self.config.streamable_http
            host = http_cfg.host
            port = http_cfg.port
            mcp_path = http_cfg.mcp_path
            json_response = http_cfg.json_response
            stateless = http_cfg.stateless

            event_store = None if stateless else InMemoryEventStore()

            # Create the session manager with our app and event store
            session_manager = StreamableHTTPSessionManager(
                app=server,
                event_store=event_store,
                stateless=stateless,
                json_response=json_response,
            )

            async def handle_streamable_http(
                scope: Scope, receive: Receive, send: Send
            ) -> Response:
                # Extract and store headers for tools to access
                headers_dict = scope.get("headers_dict", {})
                set_request_headers(headers_dict)

                try:
                    await session_manager.handle_request(scope, receive, send)
                except Exception as e:
                    # Handle client disconnections gracefully
                    if "ClosedResourceError" in str(type(e).__name__):
                        self.logger.debug("Client disconnected from StreamableHTTP stream")
                    else:
                        self.logger.error("Error in StreamableHTTP handler: %s", e)
                        raise
                return Response()

            async def health(request: Request) -> PlainTextResponse:
                return PlainTextResponse("OK")

            @contextlib.asynccontextmanager
            async def lifespan(app: Starlette) -> AsyncIterator[None]:
                async with session_manager.run():
                    self.logger.info("Application started with StreamableHTTP session manager!")
                    try:
                        yield
                    finally:
                        self.logger.info("Application shutting down...")

            app = Starlette(
                debug=True,
                routes=[
                    Mount(mcp_path, handle_streamable_http),
                    Route("/health", health, methods=["GET"]),
                ],
                middleware=[
                    Middleware(
                        AuthMiddleware,
                        auth=self.config.server.auth.value if self.config.server.auth else None,
                    )
                ],
                lifespan=lifespan,
            )

            self.logger.info(
                "Starting MCP (StreamableHTTP) on %s:%s - global timeout %.1fs",
                host,
                port,
                self.tool_timeout,
            )
            await uvicorn.Server(
                uvicorn.Config(app, host=host, port=port, log_level="info")
            ).serve()
        else:
            raise ValueError(f"Unknown server type: {mode}")

    # ------------------------------------------------------------------ #
    # Administrative helpers                                             #
    # ------------------------------------------------------------------ #

    async def register_tool(self, name: str, func: Callable) -> None:
        """Register a tool in the registry."""
        if not hasattr(func, "_mcp_tool"):
            self.logger.warning("Function %s lacks _mcp_tool metadata", func.__name__)
            return
        self.tools_registry[name] = func
        update_naming_maps()

    async def get_tool_names(self) -> List[str]:
        """Get list of registered tool names."""
        return list(self.tools_registry)

    # Session management helpers
    def get_session_manager(self) -> MCPSessionManager:
        """Get the session manager instance."""
        return self.session_manager

    async def create_user_session(
        self, user_id: str, metadata: Optional[dict[str, Any]] = None
    ) -> str:
        """Create a new user session."""
        return await self.session_manager.create_session(user_id=user_id, metadata=metadata)

    def get_artifact_store(self) -> Optional[ArtifactStore]:
        """Get the artifact store instance."""
        return self.artifact_store

    async def close(self) -> None:
        """Clean shutdown."""
        if self.artifact_store:
            try:
                await self.artifact_store.close()
            except Exception as exc:
                self.logger.warning("Error closing artifact store: %s", exc)
