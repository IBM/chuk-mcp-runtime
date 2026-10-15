# tests/common/test_mcp_resource_decorator.py
"""
Tests for the MCP resource decorator.
"""

import pytest

from chuk_mcp_runtime.common.mcp_resource_decorator import (
    RESOURCES_REGISTRY,
    clear_resources_registry,
    get_registered_resources,
    get_resource_function,
    mcp_resource,
)


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear resources registry before and after each test."""
    clear_resources_registry()
    yield
    clear_resources_registry()


def test_mcp_resource_basic():
    """Test basic resource decoration."""

    @mcp_resource(uri="test://basic", name="Basic Resource")
    async def basic_resource():
        return "test content"

    assert "test://basic" in RESOURCES_REGISTRY
    assert RESOURCES_REGISTRY["test://basic"] == basic_resource
    assert hasattr(basic_resource, "_mcp_resource")
    assert basic_resource._resource_uri == "test://basic"


def test_mcp_resource_with_metadata():
    """Test resource decoration with full metadata."""

    @mcp_resource(
        uri="config://app",
        name="App Config",
        description="Application configuration",
        mime_type="application/json",
    )
    async def app_config():
        return '{"key": "value"}'

    resource = app_config._mcp_resource
    assert str(resource.uri) == "config://app"
    assert resource.name == "App Config"
    assert resource.description == "Application configuration"
    assert resource.mime_type == "application/json"


def test_mcp_resource_sync_function():
    """Test that synchronous functions can also be resources."""

    @mcp_resource(uri="sync://data", name="Sync Data")
    def sync_resource():
        return "sync content"

    assert "sync://data" in RESOURCES_REGISTRY
    result = sync_resource()
    assert result == "sync content"


def test_mcp_resource_async_function():
    """Test that async functions work as resources."""

    @mcp_resource(uri="async://data", name="Async Data")
    async def async_resource():
        return "async content"

    assert "async://data" in RESOURCES_REGISTRY


@pytest.mark.asyncio
async def test_mcp_resource_execution():
    """Test executing a resource function."""

    @mcp_resource(uri="exec://test", name="Test")
    async def test_resource():
        return "executed"

    result = await test_resource()
    assert result == "executed"


def test_get_registered_resources():
    """Test getting all registered resources."""

    @mcp_resource(uri="res1://", name="Resource 1")
    def resource1():
        return "1"

    @mcp_resource(uri="res2://", name="Resource 2")
    def resource2():
        return "2"

    resources = get_registered_resources()
    assert len(resources) == 2

    uris = {str(r.uri) for r in resources}
    assert "res1://" in uris
    assert "res2://" in uris


def test_get_resource_function():
    """Test retrieving a resource function by URI."""

    @mcp_resource(uri="find://me", name="Findable")
    def findable():
        return "found"

    func = get_resource_function("find://me")
    assert func is not None
    assert func == findable
    assert func() == "found"


def test_get_resource_function_not_found():
    """Test retrieving a non-existent resource."""
    func = get_resource_function("nonexistent://")
    assert func is None


def test_mcp_resource_invalid_signature():
    """Test that resources with required params raise error."""
    with pytest.raises(ValueError, match="required parameter"):

        @mcp_resource(uri="bad://resource", name="Bad")
        def bad_resource(required_param):
            return required_param


def test_mcp_resource_optional_params_allowed():
    """Test that resources with optional params are allowed."""

    @mcp_resource(uri="opt://resource", name="Optional")
    def optional_resource(optional_param="default"):
        return optional_param

    assert "opt://resource" in RESOURCES_REGISTRY


def test_mcp_resource_session_params_allowed():
    """Test that session_id and user_id params are allowed."""

    @mcp_resource(uri="session://resource", name="Session Aware")
    def session_resource(session_id, user_id):
        return f"{session_id}:{user_id}"

    assert "session://resource" in RESOURCES_REGISTRY


def test_clear_resources_registry():
    """Test clearing the registry."""

    @mcp_resource(uri="clear://test", name="Test")
    def test():
        return "test"

    assert len(RESOURCES_REGISTRY) == 1

    clear_resources_registry()

    assert len(RESOURCES_REGISTRY) == 0


def test_multiple_resources():
    """Test registering multiple resources."""

    @mcp_resource(uri="multi://1", name="First")
    def first():
        return "1"

    @mcp_resource(uri="multi://2", name="Second")
    def second():
        return "2"

    @mcp_resource(uri="multi://3", name="Third")
    def third():
        return "3"

    assert len(RESOURCES_REGISTRY) == 3
    resources = get_registered_resources()
    assert len(resources) == 3


def test_resource_metadata_preservation():
    """Test that resource metadata is preserved correctly."""

    @mcp_resource(
        uri="preserve://test",
        name="Preserve Test",
        description="Testing metadata preservation",
        mime_type="text/custom",
    )
    def preserved():
        return "data"

    func = get_resource_function("preserve://test")
    assert func._resource_uri == "preserve://test"
    assert func._mcp_resource.name == "Preserve Test"
    assert func._mcp_resource.description == "Testing metadata preservation"
    assert func._mcp_resource.mime_type == "text/custom"


def test_resource_binary_content():
    """Test resources that return binary content."""

    @mcp_resource(uri="binary://data", name="Binary Data", mime_type="application/octet-stream")
    def binary_resource():
        return b"binary content"

    assert "binary://data" in RESOURCES_REGISTRY
    result = binary_resource()
    assert isinstance(result, bytes)
    assert result == b"binary content"


@pytest.mark.asyncio
async def test_resource_async_binary():
    """Test async resources returning binary."""

    @mcp_resource(uri="async-binary://data", name="Async Binary")
    async def async_binary():
        return b"async binary"

    result = await async_binary()
    assert isinstance(result, bytes)
