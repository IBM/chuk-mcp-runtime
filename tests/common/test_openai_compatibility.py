# tests/test_openai_compatibility.py
"""
Test module for OpenAI API compatibility functionality.

Tests the conversion between dot notation and underscore notation,
as well as the creation and registration of OpenAI-compatible wrappers.
"""

import inspect
from unittest.mock import patch

import pytest

from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY, Tool

# Import the module being tested
from chuk_mcp_runtime.common.openai_compatibility import (
    OpenAIToolsAdapter,
    _build_wrapper_from_schema,
    adapter,
    create_openai_compatible_wrapper,
    from_openai_compatible_name,
    initialize_openai_compatibility,
    to_openai_compatible_name,
)


# Clear the registry before tests and restore after
@pytest.fixture
def clear_tools_registry():
    """Clear the tools registry before and after tests."""
    # Save the original registry
    saved_registry = dict(TOOLS_REGISTRY)
    TOOLS_REGISTRY.clear()

    yield

    # Restore the registry
    TOOLS_REGISTRY.clear()
    TOOLS_REGISTRY.update(saved_registry)


# --- Mock ToolRegistryProvider ---
class MockToolRegistry:
    async def list_tools(self):
        return []

    async def get_tool(self, name, namespace):
        return None

    async def get_metadata(self, name, namespace):
        return None


class MockToolRegistryProvider:
    @staticmethod
    async def get_registry():
        return MockToolRegistry()


# --- Tests for helper functions ---
def test_to_openai_compatible_name():
    """Test conversion from dot notation to underscore notation."""
    # Basic conversion
    assert to_openai_compatible_name("weather.get_forecast") == "weather_get_forecast"

    # Handle multiple dots
    assert to_openai_compatible_name("proxy.weather.get_forecast") == "proxy_weather_get_forecast"

    # Handle invalid characters
    assert to_openai_compatible_name("weather.get@forecast") == "weather_get_forecast"
    assert to_openai_compatible_name("weather.get+forecast") == "weather_get_forecast"
    assert to_openai_compatible_name("weather.get/forecast") == "weather_get_forecast"

    # Handle empty string
    assert to_openai_compatible_name("") == ""

    # Handle already compatible names
    assert to_openai_compatible_name("weather_get_forecast") == "weather_get_forecast"


def test_from_openai_compatible_name():
    """Test conversion from underscore notation to dot notation."""
    # Basic conversion
    assert from_openai_compatible_name("weather_get_forecast") == "weather.get.forecast"

    # Handle multiple underscores
    assert from_openai_compatible_name("proxy_weather_get_forecast") == "proxy.weather.get.forecast"

    # Handle empty string
    assert from_openai_compatible_name("") == ""

    # Handle already dot-notation names
    assert from_openai_compatible_name("weather.get.forecast") == "weather.get.forecast"


# --- Tests for wrapper building ---
@pytest.mark.asyncio
async def test_build_wrapper_from_schema():
    """Test building a wrapper function from a schema."""
    # Create a simple schema
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["query"],
    }

    # Create a target function
    async def target_func(**kwargs):
        return f"Received: {kwargs}"

    # Build the wrapper
    wrapper = await _build_wrapper_from_schema(
        alias_name="test_wrapper", target=target_func, schema=schema
    )

    # Check the wrapper function
    assert wrapper.__name__ == "test_wrapper"
    assert inspect.iscoroutinefunction(wrapper)

    # Check that the wrapper has the correct parameters
    sig = inspect.signature(wrapper)
    assert "query" in sig.parameters
    assert "limit" in sig.parameters

    # Test calling the wrapper
    result = await wrapper(query="test", limit=10)
    assert result == "Received: {'query': 'test', 'limit': 10}"

    # Test calling with only required params
    result = await wrapper(query="test")
    assert result == "Received: {'query': 'test'}"


@pytest.mark.asyncio
async def test_create_openai_compatible_wrapper(clear_tools_registry):
    """Test creating an OpenAI-compatible wrapper for a function."""

    # Create a sample tool with proper schema
    async def get_forecast(location: str, days: int = 3):
        return f"Forecast for {location} for {days} days"

    # Manually create the tool metadata
    tool = Tool(
        name="weather.get_forecast",
        description="Get weather forecast",
        inputSchema={
            "type": "object",
            "properties": {"location": {"type": "string"}, "days": {"type": "integer"}},
            "required": ["location"],
        },
    )

    # Attach the tool metadata
    get_forecast._mcp_tool = tool

    # Add to registry
    TOOLS_REGISTRY["weather.get_forecast"] = get_forecast

    # Create the wrapper
    wrapper = await create_openai_compatible_wrapper("weather.get_forecast", get_forecast)

    # Check the wrapper
    assert wrapper is not None
    assert wrapper.__name__ == "weather_get_forecast"
    assert hasattr(wrapper, "_mcp_tool")
    assert wrapper._mcp_tool.name == "weather_get_forecast"
    assert wrapper._mcp_tool.description == "Get weather forecast"

    # Check that the schema was preserved
    assert "properties" in wrapper._mcp_tool.input_schema
    assert "location" in wrapper._mcp_tool.input_schema["properties"]
    assert "days" in wrapper._mcp_tool.input_schema["properties"]

    # Test calling the wrapper
    result = await wrapper(location="London", days=5)
    assert result == "Forecast for London for 5 days"


@pytest.mark.asyncio
async def test_create_openai_compatible_wrapper_with_proxy_metadata(
    clear_tools_registry,
):
    """Test creating a wrapper for a function with _proxy_metadata."""

    # Create a function with proxy metadata
    async def proxy_function(**kwargs):
        return f"Proxy result: {kwargs}"

    # Add proxy metadata
    proxy_function._proxy_metadata = {
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
        "description": "Proxy function description",
    }

    # Create the wrapper
    wrapper = await create_openai_compatible_wrapper("proxy.search.query", proxy_function)

    # Check the wrapper
    assert wrapper is not None
    assert wrapper.__name__ == "search_query"
    assert hasattr(wrapper, "_mcp_tool")
    assert wrapper._mcp_tool.name == "search_query"
    assert wrapper._mcp_tool.description == "Proxy function description"

    # Check that the schema was preserved
    assert "properties" in wrapper._mcp_tool.input_schema
    assert "query" in wrapper._mcp_tool.input_schema["properties"]
    assert "limit" in wrapper._mcp_tool.input_schema["properties"]

    # Test calling the wrapper
    result = await wrapper(query="test", limit=10)
    assert result == "Proxy result: {'query': 'test', 'limit': 10}"


# --- Tests for OpenAIToolsAdapter ---
@pytest.mark.asyncio
async def test_openai_tools_adapter_init(clear_tools_registry):
    """Test initializing the OpenAIToolsAdapter."""

    # Create and add properly configured tools to the registry
    async def get_forecast(location: str, days: int = 3):
        return f"Forecast for {location} for {days} days"

    get_forecast._mcp_tool = Tool(
        name="weather.get_forecast",
        description="Get weather forecast",
        inputSchema={
            "type": "object",
            "properties": {"location": {"type": "string"}, "days": {"type": "integer"}},
            "required": ["location"],
        },
    )

    async def search_query(query: str, limit: int = 10):
        return f"Search results for {query} (limit: {limit})"

    search_query._mcp_tool = Tool(
        name="proxy.search.query",
        description="Search for something",
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
    )

    # Add to registry
    TOOLS_REGISTRY["weather.get_forecast"] = get_forecast
    TOOLS_REGISTRY["proxy.search.query"] = search_query

    # Create an adapter instance
    adapter = OpenAIToolsAdapter(TOOLS_REGISTRY)

    # Check that the maps were built
    assert "weather_get_forecast" in adapter.openai_to_original
    assert "search_query" in adapter.openai_to_original
    assert adapter.openai_to_original["weather_get_forecast"] == "weather.get_forecast"
    assert adapter.openai_to_original["search_query"] == "proxy.search.query"

    assert "weather.get_forecast" in adapter.original_to_openai
    assert "proxy.search.query" in adapter.original_to_openai
    assert adapter.original_to_openai["weather.get_forecast"] == "weather_get_forecast"
    assert adapter.original_to_openai["proxy.search.query"] == "search_query"


@pytest.mark.asyncio
async def test_openai_tools_adapter_register_wrappers(clear_tools_registry):
    """Test registering OpenAI-compatible wrappers."""

    # Create and add properly configured tools to the registry
    async def get_forecast(location: str, days: int = 3):
        return f"Forecast for {location} for {days} days"

    get_forecast._mcp_tool = Tool(
        name="weather.get_forecast",
        description="Get weather forecast",
        inputSchema={
            "type": "object",
            "properties": {"location": {"type": "string"}, "days": {"type": "integer"}},
            "required": ["location"],
        },
    )

    async def search_query(query: str, limit: int = 10):
        return f"Search results for {query} (limit: {limit})"

    search_query._mcp_tool = Tool(
        name="proxy.search.query",
        description="Search for something",
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
    )

    # Add to registry
    TOOLS_REGISTRY["weather.get_forecast"] = get_forecast
    TOOLS_REGISTRY["proxy.search.query"] = search_query

    # Create a customized adapter that doesn't try to use ToolRegistryProvider
    class TestAdapter(OpenAIToolsAdapter):
        async def register_openai_compatible_wrappers(self):
            """Register OpenAI-compatible wrappers without using ToolRegistryProvider."""
            registered_count = 0

            for o, fn in list(self.registry.items()):
                if "." not in o or o in self.original_to_openai.values():
                    continue
                if to_openai_compatible_name(o) in self.registry:
                    continue
                w = await create_openai_compatible_wrapper(o, fn)
                if w is None:
                    continue
                self.registry[w._mcp_tool.name] = w
                registered_count += 1

            # Rebuild maps after registration
            self._build_maps()

            return registered_count

    # Create an adapter instance and register wrappers
    adapter = TestAdapter(TOOLS_REGISTRY)
    count = await adapter.register_openai_compatible_wrappers()

    # Check that wrappers were registered
    assert count >= 2
    assert "weather_get_forecast" in TOOLS_REGISTRY
    assert "search_query" in TOOLS_REGISTRY


@pytest.mark.asyncio
async def test_openai_tools_adapter_get_tools_definition(clear_tools_registry):
    """Test getting OpenAI tools definition."""

    # Create and add properly configured tools to the registry
    async def get_forecast(location: str, days: int = 3):
        return f"Forecast for {location} for {days} days"

    get_forecast._mcp_tool = Tool(
        name="weather.get_forecast",
        description="Get weather forecast",
        inputSchema={
            "type": "object",
            "properties": {"location": {"type": "string"}, "days": {"type": "integer"}},
            "required": ["location"],
        },
    )

    # Add tools to registry that already have the OpenAI format
    async def weather_get_forecast(location: str, days: int = 3):
        return f"Forecast for {location} for {days} days"

    weather_get_forecast._mcp_tool = Tool(
        name="weather_get_forecast",
        description="Get weather forecast",
        inputSchema={
            "type": "object",
            "properties": {"location": {"type": "string"}, "days": {"type": "integer"}},
            "required": ["location"],
        },
    )

    # Add to registry
    TOOLS_REGISTRY["weather.get_forecast"] = get_forecast
    TOOLS_REGISTRY["weather_get_forecast"] = weather_get_forecast

    # Mock the ToolRegistryProvider
    with patch("chuk_tool_processor.registry.ToolRegistryProvider", MockToolRegistryProvider):
        # Create an adapter instance
        adapter = OpenAIToolsAdapter(TOOLS_REGISTRY)

        # Get the tools definition
        tools_def = await adapter.get_openai_tools_definition()

        # Check the tools definition
        assert isinstance(tools_def, list)
        assert len(tools_def) >= 1

        # Check that each tool has the required fields
        for tool in tools_def:
            assert "type" in tool
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]


@pytest.mark.asyncio
async def test_openai_tools_adapter_execute_tool(clear_tools_registry):
    """Test executing a tool by name."""

    # Create and add properly configured tools to the registry
    async def get_forecast(location: str, days: int = 3):
        return f"Forecast for {location} for {days} days"

    get_forecast._mcp_tool = Tool(
        name="weather.get_forecast",
        description="Get weather forecast",
        inputSchema={
            "type": "object",
            "properties": {"location": {"type": "string"}, "days": {"type": "integer"}},
            "required": ["location"],
        },
    )

    # Also add the OpenAI-compatible version
    async def weather_get_forecast(location: str, days: int = 3):
        return f"Forecast for {location} for {days} days (OpenAI version)"

    weather_get_forecast._mcp_tool = Tool(
        name="weather_get_forecast",
        description="Get weather forecast",
        inputSchema={
            "type": "object",
            "properties": {"location": {"type": "string"}, "days": {"type": "integer"}},
            "required": ["location"],
        },
    )

    # Add to registry
    TOOLS_REGISTRY["weather.get_forecast"] = get_forecast
    TOOLS_REGISTRY["weather_get_forecast"] = weather_get_forecast

    # Create an adapter instance
    adapter = OpenAIToolsAdapter(TOOLS_REGISTRY)

    # Execute the tool by original name
    result1 = await adapter.execute_tool("weather.get_forecast", location="London", days=5)
    assert result1 == "Forecast for London for 5 days"

    # Execute the tool by OpenAI-compatible name
    result2 = await adapter.execute_tool("weather_get_forecast", location="Paris", days=7)
    assert result2 == "Forecast for Paris for 7 days (OpenAI version)"

    # Test error handling for unknown tool
    with pytest.raises(ValueError):
        await adapter.execute_tool("unknown_tool", param="value")


def test_openai_tools_adapter_translate_name(clear_tools_registry):
    """Test translating between original and OpenAI-compatible names."""

    # Create and add properly configured tools to the registry
    async def get_forecast(location: str, days: int = 3):
        return f"Forecast for {location} for {days} days"

    get_forecast._mcp_tool = Tool(
        name="weather.get_forecast",
        description="Get weather forecast",
        inputSchema={
            "type": "object",
            "properties": {"location": {"type": "string"}, "days": {"type": "integer"}},
            "required": ["location"],
        },
    )

    # Add to registry
    TOOLS_REGISTRY["weather.get_forecast"] = get_forecast

    # Create an adapter instance
    adapter = OpenAIToolsAdapter(TOOLS_REGISTRY)

    # Test translation to OpenAI-compatible name
    assert adapter.translate_name("weather.get_forecast", to_openai=True) == "weather_get_forecast"

    # Test translation from OpenAI-compatible name
    assert adapter.translate_name("weather_get_forecast", to_openai=False) == "weather.get_forecast"

    # Test translation of unknown names
    assert adapter.translate_name("unknown.tool", to_openai=True) == "unknown_tool"
    assert adapter.translate_name("unknown_tool", to_openai=False) == "unknown.tool"


# --- Tests for global initialization ---
@pytest.mark.asyncio
async def test_initialize_openai_compatibility(clear_tools_registry):
    """Test the global initialization function."""

    # Create and add properly configured tools to the registry
    async def get_forecast(location: str, days: int = 3):
        return f"Forecast for {location} for {days} days"

    get_forecast._mcp_tool = Tool(
        name="weather.get_forecast",
        description="Get weather forecast",
        inputSchema={
            "type": "object",
            "properties": {"location": {"type": "string"}, "days": {"type": "integer"}},
            "required": ["location"],
        },
    )

    # Add to registry
    TOOLS_REGISTRY["weather.get_forecast"] = get_forecast

    # Mock the ToolRegistryProvider
    with patch("chuk_tool_processor.registry.ToolRegistryProvider", MockToolRegistryProvider):
        # Initialize OpenAI compatibility
        adapter_inst = await initialize_openai_compatibility()

        # Check that the adapter was returned
        assert adapter_inst is adapter
