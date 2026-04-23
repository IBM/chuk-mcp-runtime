# chuk_mcp_runtime/common/openai_compatibility.py
"""
OpenAI API Compatibility Module for CHUK MCP Runtime - Async Native Implementation

This module provides functions to create OpenAI-compatible tool wrappers
for CHUK MCP tools, leveraging the async capabilities of the runtime.
"""

from __future__ import annotations

import copy
import inspect
import re
from typing import Any, Callable, Dict, List, Optional

from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY, Tool
from chuk_mcp_runtime.server.logging_config import get_logger

logger = get_logger("chuk_mcp_runtime.common.openai_compatibility")

# ───────────────────────── helpers ──────────────────────────


def to_openai_compatible_name(name: str) -> str:
    """Replace dots with underscores and strip disallowed chars."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name.replace(".", "_"))


def from_openai_compatible_name(name: str) -> str:
    """Naïve reverse mapping (underscores → dots)."""
    return name.replace("_", ".")


# ─────────────────── dynamic wrapper factory ─────────────────────


async def _build_wrapper_from_schema(
    *, alias_name: str, target: Callable, schema: Dict[str, Any]
) -> Callable:
    """Generate a coroutine whose signature mirrors *schema*."""

    props = schema.get("properties", {})
    required = set(schema.get("required", []))

    # FIXED: Separate required and optional parameters to avoid syntax error
    required_args: List[str] = []
    optional_args: List[str] = []
    kw_map: List[str] = []

    for pname in props:
        kw_map.append(f"'{pname}': {pname}")

        if pname in required:
            required_args.append(pname)  # No default value
        else:
            optional_args.append(f"{pname}=None")  # With default value

    # FIXED: Build signature with ALL required params first, then ALL optional params
    all_args = required_args + optional_args

    # Add the hidden target param at the end
    if all_args:
        arg_sig = ", ".join(all_args) + ", __target=__default_target"
    else:
        arg_sig = "__target=__default_target"

    kwargs_dict = "{" + ", ".join(kw_map) + "}"

    src = f"""
async def _alias({arg_sig}):
    kwargs = {kwargs_dict}
    kwargs = {{k: v for k, v in kwargs.items() if v is not None}}
    return await __target(**kwargs)
"""

    loc: Dict[str, Any] = {"__default_target": target}
    exec(src, loc)  # nosec B102 - Safe dynamic function creation for OpenAI compatibility
    fn = loc["_alias"]
    fn.__name__ = alias_name
    return fn


# ─────────────────── public wrapper builder ─────────────────────


async def create_openai_compatible_wrapper(
    original_name: str, original_func: Callable
) -> Optional[Callable]:
    """Return a wrapper with an OpenAI-safe name *and* real signature."""

    # Priority 1: metadata from remote MCP list-tools
    meta_dict: Optional[Dict[str, Any]] = getattr(original_func, "_proxy_metadata", None)
    schema: Dict[str, Any]
    description: str

    if meta_dict and meta_dict.get("inputSchema"):
        schema = copy.deepcopy(meta_dict["inputSchema"])
        description = meta_dict.get("description", "")
    elif hasattr(original_func, "_mcp_tool"):
        m = original_func._mcp_tool  # type: ignore[attr-defined]
        schema = copy.deepcopy(getattr(m, "inputSchema", {}))
        description = getattr(m, "description", "")
    else:
        logger.warning("No schema for %s - skipping OpenAI wrapper", original_name)
        return None

    if "properties" not in schema and isinstance(schema, dict):
        schema = {
            "type": "object",
            "properties": schema,
            "required": schema.get("required", []),
        }

    # Strip leading "proxy." if present to avoid redundant prefix
    clean_name = original_name.replace("proxy.", "", 1)
    alias_name = to_openai_compatible_name(clean_name)
    alias_fn = await _build_wrapper_from_schema(
        alias_name=alias_name, target=original_func, schema=schema
    )

    alias_meta = Tool(
        name=alias_name,
        description=description.strip().replace("\n", " "),
        inputSchema=schema,
    )
    alias_fn._mcp_tool = alias_meta  # type: ignore[attr-defined]

    return alias_fn


# ─────────────────── adapter class (async version) ─────────────
class OpenAIToolsAdapter:
    """Expose registry in an OpenAI-friendly way and allow execution."""

    def __init__(self, registry: Optional[Dict[str, Any]] = None):
        self.registry = registry or TOOLS_REGISTRY
        self.openai_to_original: Dict[str, str] = {}
        self.original_to_openai: Dict[str, str] = {}
        self._build_maps()

    def _build_maps(self):
        """Populate name maps, stripping leading ``proxy.`` when present."""
        self.openai_to_original.clear()
        self.original_to_openai.clear()
        for original in self.registry:
            core_name = original.replace("proxy.", "", 1)
            openai_name = to_openai_compatible_name(core_name)
            self.openai_to_original[openai_name] = original
            self.original_to_openai[original] = openai_name

    # ---------- wrapper registration --------------------------------
    async def register_openai_compatible_wrappers(self):
        """Register OpenAI-compatible wrappers for all tools with dots in their names."""
        # Register dot-named tools from TOOLS_REGISTRY
        registered_count = 0

        for o, fn in list(self.registry.items()):
            if "." not in o or o in self.original_to_openai.values():
                continue
            if to_openai_compatible_name(o) in self.registry:
                continue
            w = await create_openai_compatible_wrapper(o, fn)
            if w is None:
                continue
            self.registry[w._mcp_tool.name] = w  # type: ignore[attr-defined]
            registered_count += 1
            logger.debug("Registered OpenAI wrapper: %s → %s", w._mcp_tool.name, o)

        # Also register tools from the registry
        try:
            from chuk_tool_processor.registry import ToolRegistryProvider

            registry = await ToolRegistryProvider.get_registry()
            tools_list = await registry.list_tools()

            for tool_info in tools_list:
                # ToolInfo is a Pydantic model — access fields by attribute.
                # Guard against both Pydantic models and legacy (namespace, name) tuples.
                if hasattr(tool_info, "namespace") and hasattr(tool_info, "name"):
                    namespace = tool_info.namespace
                    name = tool_info.name
                else:
                    try:
                        namespace, name = tool_info
                    except (TypeError, ValueError):
                        continue
                # Skip tools that are already proxied
                if namespace.startswith("proxy.") and "." in namespace:
                    continue

                # Create the fully qualified name and check if we already have it
                fq_name = f"{namespace}.{name}" if namespace else name
                openai_name = to_openai_compatible_name(fq_name)

                if openai_name in self.registry:
                    continue

                try:
                    # Get the tool and metadata
                    tool_class = await registry.get_tool(name, namespace)
                    metadata = await registry.get_metadata(name, namespace)

                    if tool_class and metadata:
                        # Create a wrapper function that delegates to the tool class
                        async def execute_wrapper(**kwargs):
                            instance = tool_class()
                            result = instance.execute(**kwargs)
                            if inspect.isawaitable(result):
                                return await result
                            return result

                        # Get or create a schema
                        description = getattr(metadata, "description", f"Tool: {name}")
                        input_schema = getattr(metadata, "input_schema", {})
                        if not input_schema:
                            input_schema = {
                                "type": "object",
                                "properties": {},
                                "required": [],
                            }

                        # Create a Tool metadata object
                        tool_meta = Tool(
                            name=openai_name,
                            description=description.strip().replace("\n", " "),
                            inputSchema=input_schema,
                        )

                        # Attach metadata
                        execute_wrapper._mcp_tool = tool_meta  # type: ignore[attr-defined]

                        # Register in TOOLS_REGISTRY
                        self.registry[openai_name] = execute_wrapper
                        registered_count += 1
                        logger.debug(
                            f"Registered class-based tool wrapper: {openai_name} → {fq_name}"
                        )

                except Exception as e:
                    logger.warning(f"Error registering tool {namespace}.{name}: {e}")
        except ImportError:
            logger.debug("ToolRegistryProvider not available, skipping registry tool registration")

        # Rebuild maps after registration
        self._build_maps()

        return registered_count

    # ---------- schema export ---------------------------------------
    async def get_openai_tools_definition(self) -> List[Dict[str, Any]]:
        """
        Get OpenAI tools definition, prioritizing proxy tools and filtering duplicates.

        This method identifies unique tools by their base functionality
        and returns only the most feature-rich version of each tool.
        """
        # First, identify all tools and group them by their core functionality
        # We'll remove the server prefix to identify the actual function
        tool_groups: Dict[str, List[tuple[str, Any]]] = {}

        # Process all tools from TOOLS_REGISTRY with _mcp_tool attribute
        for name, fn in self.registry.items():
            if not hasattr(fn, "_mcp_tool"):
                continue

            # Extract the base tool name (without server or prefix)
            base_name = name
            if "_" in name:
                parts = name.split("_", 1)
                if len(parts) == 2:
                    server, tool = parts
                    base_name = tool

            # Group tools by their base functionality
            if base_name not in tool_groups:
                tool_groups[base_name] = []
            tool_groups[base_name].append((name, fn))

        # Now, select only the most feature-rich version of each tool
        out: List[Dict[str, Any]] = []
        for base_name, tools in tool_groups.items():
            # Sort by the number of properties in the schema (most first)
            # For ties, prioritize tools with "time_" prefix over "default_proxy_" prefix
            def sort_key(tool_tuple):
                name, fn = tool_tuple
                prop_count = len(fn._mcp_tool.inputSchema.get("properties", {}))
                # Prioritize server-specific tools (like time_*) over proxy tools
                prefix_priority = 0
                if name.startswith("default_proxy_"):
                    prefix_priority = -1
                elif "proxy_" in name:
                    prefix_priority = -2
                return (prop_count, prefix_priority)

            sorted_tools = sorted(tools, key=sort_key, reverse=True)

            if sorted_tools:
                # Take only the best tool for each base functionality
                name, fn = sorted_tools[0]
                meta = fn._mcp_tool

                out.append(
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": meta.description,
                            "parameters": meta.inputSchema,
                        },
                    }
                )

        return out

    # ---------- execution wrapper -----------------------------------
    async def execute_tool(self, name: str, **kw):
        """Execute a tool by name with the given kwargs."""
        fn = self.registry.get(name) or self.registry.get(self.openai_to_original.get(name, ""))
        if fn is None:
            raise ValueError(f"Tool not found: {name}")

        # Handle both function and class-based tools
        if inspect.isclass(fn):
            # Create an instance and call execute
            instance = fn()
            result = instance.execute(**kw)
            if inspect.isawaitable(result):
                result = await result
            return result
        else:
            # Call function directly
            return await fn(**kw)

    # ---------- translate -------------------------------------------
    def translate_name(self, name: str, to_openai: bool = True) -> str:
        """Translate between original and OpenAI-compatible names."""
        if to_openai:
            return self.original_to_openai.get(name, to_openai_compatible_name(name))
        return self.openai_to_original.get(name, from_openai_compatible_name(name))


# Create a global adapter instance
adapter = OpenAIToolsAdapter()


async def initialize_openai_compatibility():
    """Initialize OpenAI compatibility by registering wrappers."""
    count = await adapter.register_openai_compatible_wrappers()
    logger.debug(f"Registered {count} OpenAI-compatible wrappers")
    return adapter
