# Enhanced chuk_mcp_runtime/common/mcp_tool_decorator.py
"""
CHUK MCP Tool Decorator Module - Enhanced with Per-Tool Timeout Support

This module provides decorators for registering functions as CHUK MCP tools
with automatic input schema generation and configurable timeouts.
"""

import asyncio
import importlib
import inspect
import logging
from functools import wraps
from inspect import isasyncgenfunction, iscoroutinefunction
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
    get_type_hints,
)

T = TypeVar("T")

# Try to import Pydantic
try:
    from pydantic import create_model

    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    logging.getLogger("chuk_mcp_runtime.tools").warning(
        "Pydantic not available, using fallback schema generation"
    )

# Try to import the MCP Tool class
try:
    from mcp.types import Tool
except ImportError:

    class Tool:
        def __init__(self, name: str, description: str, input_schema: Dict[str, Any]):
            self.name = name
            self.description = description
            self.input_schema = input_schema


# Global registry of tool functions (always async)
TOOLS_REGISTRY: Dict[str, Callable[..., Any]] = {}
TOOL_REGISTRY = TOOLS_REGISTRY

# FIXED: Add initialization locks to prevent race conditions
_INIT_LOCKS: Dict[str, asyncio.Lock] = {}
_INITIALIZATION_LOCK = asyncio.Lock()


def _extract_param_descriptions(func: Callable[..., Any]) -> Dict[str, str]:
    """Extract parameter descriptions from function docstring."""
    import inspect

    docstring = inspect.getdoc(func)
    if not docstring:
        return {}

    descriptions = {}
    lines = docstring.split("\n")

    # Look for Args: section
    in_args_section = False
    for line in lines:
        line = line.strip()

        if line.lower().startswith("args:"):
            in_args_section = True
            continue
        elif line.lower().startswith(("returns:", "raises:", "yields:", "note:")):
            in_args_section = False
            continue

        if in_args_section and ":" in line:
            # Parse parameter descriptions like "param_name: Description text"
            parts = line.split(":", 1)
            if len(parts) == 2:
                param_name = parts[0].strip()
                description = parts[1].strip()
                descriptions[param_name] = description

    return descriptions


def _get_type_schema(annotation: Type) -> Dict[str, Any]:
    """Map Python types to JSON Schema with better Optional handling."""
    import typing

    # Handle Optional types (Union[X, None])
    if hasattr(typing, "get_origin") and hasattr(typing, "get_args"):
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)

        if origin is typing.Union:
            # Check if it's Optional (Union[X, None])
            if len(args) == 2 and type(None) in args:
                # Get the non-None type
                non_none_type = args[0] if args[1] is type(None) else args[1]
                return _get_type_schema(non_none_type)

    # Handle basic types
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}

    # Handle generic types
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        return {"type": "array"}
    if origin is dict:
        return {"type": "object"}

    # Handle string representations of types (from get_type_hints)
    if isinstance(annotation, str):
        if annotation in ("str", "typing.Optional[str]", "Optional[str]"):
            return {"type": "string"}
        elif annotation in ("int", "typing.Optional[int]", "Optional[int]"):
            return {"type": "integer"}
        elif annotation in ("bool", "typing.Optional[bool]", "Optional[bool]"):
            return {"type": "boolean"}
        elif annotation in ("float", "typing.Optional[float]", "Optional[float]"):
            return {"type": "number"}

    # Special handling for common None-able types
    if str(annotation).startswith("typing.Union") or str(annotation).startswith("typing.Optional"):
        # Try to extract the base type from string representation
        if "str" in str(annotation):
            return {"type": "string"}
        elif "int" in str(annotation):
            return {"type": "integer"}
        elif "bool" in str(annotation):
            return {"type": "boolean"}
        elif "float" in str(annotation):
            return {"type": "number"}

    # Default fallback
    return {"type": "string"}


async def create_input_schema(func: Callable[..., Any]) -> Dict[str, Any]:
    """
    Build a JSON Schema for the parameters of `func`, using Pydantic if available.
    Enhanced to extract parameter descriptions from docstrings.
    """
    sig = inspect.signature(func)
    param_descriptions = _extract_param_descriptions(func)

    if HAS_PYDANTIC:
        fields: Dict[str, Any] = {}
        for name, param in sig.parameters.items():
            if name == "self" or name.startswith("__"):  # Skip internal parameters
                continue
            ann = param.annotation if param.annotation is not inspect.Parameter.empty else str

            # Handle Optional parameters correctly
            if param.default is not inspect.Parameter.empty:
                fields[name] = (ann, param.default)
            else:
                fields[name] = (ann, ...)

        Model = create_model(f"{func.__name__.capitalize()}Input", **fields)
        schema = Model.model_json_schema()

        # Add descriptions from docstring
        if "properties" in schema and param_descriptions:
            for param_name, description in param_descriptions.items():
                if param_name in schema["properties"]:
                    schema["properties"][param_name]["description"] = description

        return schema
    else:
        props: Dict[str, Any] = {}
        required = []
        hints = get_type_hints(func)

        for name, param in sig.parameters.items():
            if name == "self" or name.startswith("__"):  # Skip internal parameters
                continue

            ann = hints.get(name, str)
            param_schema = _get_type_schema(ann)

            # Add description if available
            if name in param_descriptions:
                param_schema["description"] = param_descriptions[name]

            props[name] = param_schema

            # Only mark as required if no default value
            if param.default is inspect.Parameter.empty:
                required.append(name)

        return {"type": "object", "properties": props, "required": required}


def mcp_tool(
    name: str | None = None,
    description: str | None = None,
    timeout: Optional[Union[int, float]] = None,
):
    """
    Register an **async** tool (coroutine *or* async-generator).

    Parameters
    ----------
    name          custom tool name (defaults to function name)
    description   fallback to function docstring
    timeout       per-tool timeout (seconds)
    """

    def decorator(original_func: Callable[..., Any]):
        # 1) ensure async coroutine OR async-generator
        if not (iscoroutinefunction(original_func) or isasyncgenfunction(original_func)):
            raise TypeError(f"{original_func.__name__} must be async (coroutine or generator)")

        tool_name = name or original_func.__name__
        tool_desc = description or (original_func.__doc__ or "").strip() or tool_name

        # 2) Create different wrappers based on function type
        if isasyncgenfunction(original_func):
            # For async generators, create an async generator wrapper
            @wraps(original_func)
            async def async_gen_wrapper(*args, **kwargs):
                async for item in original_func(*args, **kwargs):
                    yield item

            wrapper = async_gen_wrapper
        else:
            # For regular async functions, create a coroutine wrapper
            @wraps(original_func)
            async def async_wrapper(*args, **kwargs):
                return await original_func(*args, **kwargs)

            wrapper = async_wrapper

        # attach bookkeeping - schema & Tool will be added later
        wrapper._needs_init = True
        wrapper._init_name = tool_name
        wrapper._init_desc = tool_desc
        wrapper._orig_func = original_func
        wrapper._tool_timeout = timeout

        TOOLS_REGISTRY[tool_name] = wrapper
        return wrapper

    return decorator


# FIXED: Thread-safe tool initialization with proper locking
async def _initialize_tool(tool_name: str, placeholder: Callable[..., Any]):
    """Build schema + Tool object and replace placeholder in registry with proper locking."""
    # Use a per-tool lock to prevent race conditions
    async with _INITIALIZATION_LOCK:
        if tool_name not in _INIT_LOCKS:
            _INIT_LOCKS[tool_name] = asyncio.Lock()

    async with _INIT_LOCKS[tool_name]:
        # Check again if initialization is still needed (another coroutine might have done it)
        if not getattr(placeholder, "_needs_init", False):
            return

        # Build schema
        schema = await create_input_schema(placeholder._orig_func)
        tool_obj = Tool(
            name=placeholder._init_name,
            description=placeholder._init_desc,
            input_schema=schema,
        )

        # Create final wrapper based on original function type
        if isasyncgenfunction(placeholder._orig_func):
            # For async generators
            @wraps(placeholder._orig_func)
            async def final_wrapper(*args, **kwargs):
                try:
                    async for item in placeholder._orig_func(*args, **kwargs):
                        yield item
                except TypeError as exc:
                    sig = inspect.signature(placeholder._orig_func)
                    valid = [p for p in sig.parameters if not p.startswith("__")]
                    logging.error(
                        "Error calling %s: %s. Valid parameters: %s",
                        tool_name,
                        exc,
                        valid,
                    )
                    raise
        else:
            # For regular async functions
            @wraps(placeholder._orig_func)
            async def final_wrapper(*args, **kwargs):
                try:
                    return await placeholder._orig_func(*args, **kwargs)
                except TypeError as exc:
                    sig = inspect.signature(placeholder._orig_func)
                    valid = [p for p in sig.parameters if not p.startswith("__")]
                    logging.error(
                        "Error calling %s: %s. Valid parameters: %s",
                        tool_name,
                        exc,
                        valid,
                    )
                    raise

        final_wrapper._mcp_tool = tool_obj
        final_wrapper._tool_timeout = getattr(placeholder, "_tool_timeout", None)

        TOOLS_REGISTRY[tool_name] = final_wrapper
        placeholder._needs_init = False  # mark done


async def ensure_tool_initialized(tool_name: str) -> Callable[..., Any]:
    """
    Ensure a tool is initialized and return it.

    Args:
        tool_name: Name of the tool to initialize

    Returns:
        The initialized tool function

    Raises:
        KeyError: If tool not found in registry
    """
    if tool_name not in TOOLS_REGISTRY:
        raise KeyError(f"Tool '{tool_name}' not registered")

    tool = TOOLS_REGISTRY[tool_name]

    if getattr(tool, "_needs_init", False):
        await _initialize_tool(tool_name, tool)
        tool = TOOLS_REGISTRY[tool_name]  # Get the updated tool

    return tool


async def initialize_tool_registry():
    """
    Initialize all tools in the registry that need initialization.
    """
    # Get a snapshot of tools that need initialization to avoid iteration issues
    tools_to_init = [
        (name, func)
        for name, func in list(TOOLS_REGISTRY.items())
        if hasattr(func, "_needs_init") and func._needs_init
    ]

    # Initialize all tools concurrently but safely
    tasks = [_initialize_tool(name, func) for name, func in tools_to_init]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def get_tool_timeout(tool_name: str, default_timeout: float = 60.0) -> float:
    """
    Get the timeout for a specific tool.

    Args:
        tool_name: Name of the tool
        default_timeout: Default timeout if no tool-specific timeout is set

    Returns:
        Timeout in seconds
    """
    if tool_name in TOOLS_REGISTRY:
        func = TOOLS_REGISTRY[tool_name]
        tool_timeout = getattr(func, "_tool_timeout", None)
        if tool_timeout is not None:
            return float(tool_timeout)

    return default_timeout


async def execute_tool(tool_name: str, **kwargs) -> Any:
    """
    Execute a registered tool asynchronously.
    """
    # Ensure tool is initialized before execution
    func = await ensure_tool_initialized(tool_name)

    # Execute the tool
    return await func(**kwargs)


async def scan_for_tools(module_paths: List[str]) -> None:
    """
    Scan the provided modules for decorated tools and initialize them.

    Args:
        module_paths: List of dotted module paths to scan
    """
    for module_path in module_paths:
        try:
            importlib.import_module(module_path)
        except ImportError as e:
            logging.getLogger("chuk_mcp_runtime.tools").warning(
                f"Failed to import module {module_path}: {e}"
            )

    # Initialize all tools that have been registered
    await initialize_tool_registry()


async def get_tool_metadata(tool_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get metadata for a tool or all tools.

    Args:
        tool_name: Optional name of the tool to get metadata for
                  If None, returns metadata for all tools

    Returns:
        Dict of tool metadata or dict of dicts
    """
    # Initialize any tools that need it
    await initialize_tool_registry()

    if tool_name:
        func = await ensure_tool_initialized(tool_name)
        if hasattr(func, "_mcp_tool"):
            metadata = {
                "name": func._mcp_tool.name,
                "description": func._mcp_tool.description,
                "inputSchema": func._mcp_tool.input_schema,
            }
            # Add timeout info if available
            if hasattr(func, "_tool_timeout") and func._tool_timeout is not None:
                metadata["timeout"] = func._tool_timeout
            return metadata
        return {}

    # Return metadata for all tools
    result = {}
    for name in list(TOOLS_REGISTRY.keys()):
        try:
            func = await ensure_tool_initialized(name)
            if hasattr(func, "_mcp_tool"):
                metadata = {
                    "name": func._mcp_tool.name,
                    "description": func._mcp_tool.description,
                    "inputSchema": func._mcp_tool.input_schema,
                }
                # Add timeout info if available
                if hasattr(func, "_tool_timeout") and func._tool_timeout is not None:
                    metadata["timeout"] = func._tool_timeout
                result[name] = metadata
        except Exception as e:
            logging.getLogger("chuk_mcp_runtime.tools").warning(
                f"Failed to get metadata for tool {name}: {e}"
            )

    return result
