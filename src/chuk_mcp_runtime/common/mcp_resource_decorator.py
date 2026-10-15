# chuk_mcp_runtime/common/mcp_resource_decorator.py
"""
MCP Resource Decorator

Provides @mcp_resource decorator for defining custom MCP resources.
Similar to @mcp_tool but for read-only data resources.

Example:
    @mcp_resource(uri="config://app/settings", name="App Settings")
    async def get_app_settings() -> str:
        return load_settings_file()

    @mcp_resource(uri="logs://recent", name="Recent Logs", mimeType="text/plain")
    async def get_recent_logs() -> str:
        return read_log_file()
"""

from __future__ import annotations

import inspect
from typing import Callable, Dict, Optional

from mcp.types import Resource
from pydantic import AnyUrl, TypeAdapter

# Global registry for resources
RESOURCES_REGISTRY: Dict[str, Callable] = {}


def mcp_resource(
    uri: str,
    name: str,
    description: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> Callable:
    """
    Decorator to mark a function as an MCP resource provider.

    Args:
        uri: The URI for this resource (e.g., "config://settings")
        name: Human-readable name for the resource
        description: Optional description of the resource
        mime_type: Optional MIME type (default: text/plain)

    Returns:
        Decorated function with resource metadata

    Example:
        @mcp_resource(
            uri="config://database",
            name="Database Configuration",
            description="Current database connection settings",
            mime_type="application/json"
        )
        async def get_db_config() -> str:
            return json.dumps({"host": "localhost", "port": 5432})
    """

    def decorator(func: Callable) -> Callable:
        # Validate function signature
        sig = inspect.signature(func)

        # Resource functions should not have required parameters
        # (they can have optional parameters for context)
        for param_name, param in sig.parameters.items():
            if param.default == inspect.Parameter.empty and param_name not in (
                "session_id",
                "user_id",
            ):
                raise ValueError(
                    f"Resource function '{func.__name__}' has required parameter '{param_name}'. "
                    f"Resource functions should have no required parameters."
                )

        # Create Resource metadata object
        # Validate the uri as a URL; mcp 2 stores Resource.uri as a plain string
        url_adapter: TypeAdapter[AnyUrl] = TypeAdapter(AnyUrl)
        url_adapter.validate_python(uri)

        resource_metadata = Resource(
            uri=uri,
            name=name,
            description=description or "",
            mime_type=mime_type or "text/plain",
        )

        # Attach metadata to function
        func._mcp_resource = resource_metadata  # type: ignore[attr-defined]
        func._resource_uri = uri  # type: ignore[attr-defined]

        # Register in global registry
        RESOURCES_REGISTRY[uri] = func

        return func

    return decorator


def get_registered_resources() -> list[Resource]:
    """
    Get all registered resources as Resource objects.

    Returns:
        List of Resource metadata objects
    """
    resources = []
    for uri, func in RESOURCES_REGISTRY.items():
        if hasattr(func, "_mcp_resource"):
            resources.append(func._mcp_resource)
    return resources


def get_resource_function(uri: str) -> Optional[Callable]:
    """
    Get the function registered for a specific URI.

    Args:
        uri: The resource URI to look up

    Returns:
        The registered function, or None if not found
    """
    return RESOURCES_REGISTRY.get(uri)


def clear_resources_registry() -> None:
    """Clear all registered resources (useful for testing)."""
    RESOURCES_REGISTRY.clear()


async def initialize_resource_registry() -> None:
    """
    Initialize the resource registry.
    Can be extended to support dynamic resource loading.
    """
    # Currently a no-op, but provides a hook for future initialization
    pass


__all__ = [
    "mcp_resource",
    "RESOURCES_REGISTRY",
    "get_registered_resources",
    "get_resource_function",
    "clear_resources_registry",
    "initialize_resource_registry",
]
